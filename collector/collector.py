"""Order-book and trade recorder: Day 1 of the DeepLOB Reality Check project.

Records Binance spot top-of-book snapshots (20 levels pushed every 100 ms, we keep
the best LEVELS) and individual trades for a few symbols, writing Parquet files.

Design rules (each one exists because a quiet data bug ruins the research later):
  * Every row carries recv_ns, our own wall-clock receive time. The depth stream has
    no exchange timestamp, so this is the only clock we have. Keep the VM clock synced.
  * Never crash on a dropped connection; reconnect with backoff and LOG the gap.
  * Never lose more than flush_secs of data, and never leave half-written files.
  * Missing data is recorded as an event, not silently papered over.

Usage:
    python collector.py --out data --symbols btcusdt ethusdt
    python collector.py --probe 5          # print 5 raw messages and exit (format check)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import signal
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from websockets.asyncio.client import connect

LEVELS = 10
log = logging.getLogger("collector")


def _book_schema() -> pa.Schema:
    fields = [("recv_ns", pa.int64()), ("symbol", pa.string()), ("last_update_id", pa.int64())]
    for side in ("bid", "ask"):
        for i in range(LEVELS):
            fields += [(f"{side}_px_{i}", pa.float64()), (f"{side}_sz_{i}", pa.float64())]
    return pa.schema(fields)


BOOK_SCHEMA = _book_schema()
TRADE_SCHEMA = pa.schema([
    ("recv_ns", pa.int64()), ("symbol", pa.string()), ("trade_id", pa.int64()),
    ("event_ms", pa.int64()), ("trade_ms", pa.int64()),
    ("price", pa.float64()), ("qty", pa.float64()), ("buyer_is_maker", pa.bool_()),
])


@dataclass
class Config:
    out: Path = Path("data")
    symbols: tuple = ("btcusdt", "ethusdt")
    url: str | None = None           # override for tests / other endpoints
    flush_secs: float = 120.0        # max data lost on a hard kill (SIGTERM flushes first)
    stale_secs: float = 30.0         # no message for this long => assume dead, reconnect
    gap_secs: float = 1.0            # book silence longer than this is logged as a gap
    max_conn_secs: float = 23 * 3600  # Binance drops connections at 24h; reconnect first


def build_url(symbols) -> str:
    streams = []
    for s in symbols:
        streams += [f"{s}@depth20@100ms", f"{s}@trade"]
    return "wss://stream.binance.com:9443/stream?streams=" + "/".join(streams)


# ---------------------------------------------------------------- parsing

def parse_book(symbol: str, recv_ns: int, d: dict) -> dict:
    row = {"recv_ns": recv_ns, "symbol": symbol.upper(),
           "last_update_id": int(d.get("lastUpdateId", -1))}
    for side, key, alt in (("bid", "bids", "b"), ("ask", "asks", "a")):
        levels = d.get(key, d.get(alt)) or []
        for i in range(LEVELS):
            if i < len(levels):
                row[f"{side}_px_{i}"] = float(levels[i][0])
                row[f"{side}_sz_{i}"] = float(levels[i][1])
            else:
                row[f"{side}_px_{i}"] = math.nan
                row[f"{side}_sz_{i}"] = math.nan
    return row


def parse_trade(recv_ns: int, d: dict) -> dict:
    return {"recv_ns": recv_ns, "symbol": d["s"].upper(), "trade_id": int(d["t"]),
            "event_ms": int(d["E"]), "trade_ms": int(d["T"]),
            "price": float(d["p"]), "qty": float(d["q"]), "buyer_is_maker": bool(d["m"])}


# ---------------------------------------------------------------- recording

class Recorder:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cfg.out.mkdir(parents=True, exist_ok=True)
        self.events_path = cfg.out / "events.jsonl"
        self.buf = {"book": defaultdict(list), "trades": defaultdict(list)}
        self.last_book_ns: dict[str, int] = {}
        self.last_uid: dict[str, int] = {}
        self.n_book = self.n_trade = 0
        self._last_flush = time.monotonic()
        self._last_heartbeat = time.monotonic()

    # -- events: connects, disconnects, gaps, anomalies. Read these before trusting any data.
    def event(self, kind: str, **fields) -> None:
        rec = {"ts_ns": time.time_ns(), "kind": kind, **fields}
        with open(self.events_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        log.info("event %s %s", kind, fields)

    def handle(self, raw, recv_ns: int) -> bool:
        """Process one websocket message. Returns False to request a reconnect."""
        try:
            msg = json.loads(raw)
        except ValueError:
            self.event("bad_json", sample=str(raw)[:80])
            return True
        stream, data = msg.get("stream"), msg.get("data")
        if not isinstance(data, dict):
            return True
        if data.get("e") == "serverShutdown":
            self.event("server_shutdown")
            return False
        symbol, _, kind = stream.partition("@")
        if kind.startswith("depth"):
            row = parse_book(symbol, recv_ns, data)
            sym = row["symbol"]
            prev = self.last_book_ns.get(sym)
            if prev is not None and recv_ns - prev > self.cfg.gap_secs * 1e9:
                self.event("gap", symbol=sym, start_ns=prev, end_ns=recv_ns,
                           secs=round((recv_ns - prev) / 1e9, 3))
            pu = self.last_uid.get(sym)
            if pu is not None and row["last_update_id"] < pu:
                self.event("out_of_order", symbol=sym, prev=pu, new=row["last_update_id"])
            self.last_book_ns[sym] = recv_ns
            self.last_uid[sym] = row["last_update_id"]
            self.buf["book"][sym].append(row)
            self.n_book += 1
        elif kind == "trade":
            row = parse_trade(recv_ns, data)
            self.buf["trades"][row["symbol"]].append(row)
            self.n_trade += 1
        return True

    def maybe_flush(self) -> None:
        now = time.monotonic()
        if now - self._last_flush >= self.cfg.flush_secs:
            self.flush()
        if now - self._last_heartbeat >= 60:
            log.info("heartbeat: %d book rows, %d trades so far", self.n_book, self.n_trade)
            self._last_heartbeat = now

    def flush(self) -> None:
        for kind, schema in (("book", BOOK_SCHEMA), ("trades", TRADE_SCHEMA)):
            for symbol, rows in self.buf[kind].items():
                by_date = defaultdict(list)
                for r in rows:
                    by_date[time.strftime("%Y-%m-%d", time.gmtime(r["recv_ns"] / 1e9))].append(r)
                for date, rs in by_date.items():
                    d = self.cfg.out / kind / symbol / date
                    d.mkdir(parents=True, exist_ok=True)
                    stem = f"part-{rs[0]['recv_ns']}"
                    tmp, final = d / f".{stem}.tmp", d / f"{stem}.parquet"
                    pq.write_table(pa.Table.from_pylist(rs, schema=schema), tmp,
                                   compression="zstd")
                    tmp.rename(final)  # atomic: readers never see a half-written file
            self.buf[kind].clear()
        self._last_flush = time.monotonic()


# ---------------------------------------------------------------- main loop

async def run(cfg: Config, stop: asyncio.Event | None = None,
              install_signals: bool = True) -> Recorder:
    stop = stop or asyncio.Event()
    rec = Recorder(cfg)
    if install_signals:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
    url = cfg.url or build_url(cfg.symbols)
    rec.event("start", url=url, symbols=list(cfg.symbols))
    backoff = 1.0
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            async with connect(url, open_timeout=10, max_queue=1024) as ws:
                rec.event("connect")
                got_data = False
                idle_since = time.monotonic()
                while not stop.is_set():
                    if time.monotonic() - t0 > cfg.max_conn_secs:
                        rec.event("planned_reconnect")
                        break
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        if time.monotonic() - idle_since > cfg.stale_secs:
                            rec.event("stale_connection", idle_secs=cfg.stale_secs)
                            break
                        rec.maybe_flush()
                        continue
                    recv_ns = time.time_ns()  # stamp immediately, before any parsing
                    idle_since = time.monotonic()
                    if not got_data:
                        got_data, backoff = True, 1.0
                    if not rec.handle(raw, recv_ns):
                        break
                    rec.maybe_flush()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # network errors, handshake errors, bad frames: all recoverable
            rec.event("disconnect", error=f"{type(e).__name__}: {e}")
        if stop.is_set():
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
        backoff = min(backoff * 2, 60.0)
    rec.flush()
    rec.event("stopped", n_book=rec.n_book, n_trade=rec.n_trade)
    return rec


async def probe(url: str, n: int) -> None:
    """Print the first n raw messages so you can eyeball the real format."""
    async with connect(url, open_timeout=10) as ws:
        for _ in range(n):
            print(await asyncio.wait_for(ws.recv(), timeout=10))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("data"))
    p.add_argument("--symbols", nargs="+", default=["btcusdt", "ethusdt"])
    p.add_argument("--url", default=None)
    p.add_argument("--flush-secs", type=float, default=120.0)
    p.add_argument("--stale-secs", type=float, default=30.0)
    p.add_argument("--gap-secs", type=float, default=1.0)
    p.add_argument("--probe", type=int, default=0, metavar="N")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config(out=a.out, symbols=tuple(s.lower() for s in a.symbols), url=a.url,
                 flush_secs=a.flush_secs, stale_secs=a.stale_secs, gap_secs=a.gap_secs)
    if a.probe:
        asyncio.run(probe(cfg.url or build_url(cfg.symbols), a.probe))
    else:
        asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
