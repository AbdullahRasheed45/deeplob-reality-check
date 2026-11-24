"""Tests run against a local fake exchange, so no internet or Binance access is needed.

    pytest -q collector/test_collector.py
"""
import asyncio
import json
import math
import time
from pathlib import Path

import pyarrow.parquet as pq
from websockets.asyncio.server import serve

import collector as c


# ---------------------------------------------------------------- parsing

def test_parse_book_pads_missing_levels_with_nan():
    d = {"lastUpdateId": 7, "bids": [["100.0", "1.5"], ["99.5", "2"]], "asks": [["100.5", "0.3"]]}
    row = c.parse_book("btcusdt", 123, d)
    assert row["symbol"] == "BTCUSDT" and row["last_update_id"] == 7
    assert row["bid_px_0"] == 100.0 and row["bid_sz_1"] == 2.0
    assert row["ask_px_0"] == 100.5 and math.isnan(row["ask_px_1"])
    assert set(row) == set(c.BOOK_SCHEMA.names)


def test_parse_trade():
    d = {"e": "trade", "E": 1, "s": "ETHUSDT", "t": 9, "p": "2000.10", "q": "0.5", "T": 2, "m": True}
    row = c.parse_trade(5, d)
    assert row["price"] == 2000.10 and row["buyer_is_maker"] is True and row["trade_id"] == 9
    assert set(row) == set(c.TRADE_SCHEMA.names)


def test_handler_flags_out_of_order_and_gap(tmp_path):
    rec = c.Recorder(c.Config(out=tmp_path, gap_secs=0.5))

    def msg(uid):
        return json.dumps({"stream": "btcusdt@depth20@100ms",
                           "data": {"lastUpdateId": uid, "bids": [["1", "1"]], "asks": [["2", "1"]]}})
    t = time.time_ns()
    rec.handle(msg(10), t)
    rec.handle(msg(9), t + 10_000_000)             # id went backwards
    rec.handle(msg(11), t + 3_000_000_000)         # 3 s of silence
    kinds = [json.loads(l)["kind"] for l in open(rec.events_path)]
    assert "out_of_order" in kinds and "gap" in kinds


# ---------------------------------------------------------------- end to end

def _depth(sym, uid):
    return json.dumps({"stream": f"{sym}@depth20@100ms", "data": {
        "lastUpdateId": uid,
        "bids": [[f"{100 - i * 0.01:.2f}", "1.0"] for i in range(20)],
        "asks": [[f"{100.01 + i * 0.01:.2f}", "1.0"] for i in range(20)]}})


def _trade(sym, tid):
    ms = int(time.time() * 1000)
    return json.dumps({"stream": f"{sym}@trade", "data": {
        "e": "trade", "E": ms, "s": sym.upper(), "t": tid, "p": "100.00", "q": "0.1", "T": ms, "m": False}})


def test_records_survives_drop_and_flushes_on_stop(tmp_path):
    conns = {"n": 0}

    async def handler(ws):
        conns["n"] += 1
        first = conns["n"] == 1
        uid, end = 0, time.monotonic() + (1.0 if first else 60)
        try:
            while time.monotonic() < end:
                for sym in ("btcusdt", "ethusdt"):
                    uid += 1
                    await ws.send(_depth(sym, uid))
                    await ws.send(_trade(sym, uid))
                await asyncio.sleep(0.05)
            await ws.close(code=1011)   # abnormal close: client must reconnect on its own
        except Exception:
            pass

    async def scenario():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            cfg = c.Config(out=tmp_path, url=f"ws://127.0.0.1:{port}/stream",
                           flush_secs=0.5, gap_secs=0.5, stale_secs=5)
            stop = asyncio.Event()
            task = asyncio.create_task(c.run(cfg, stop, install_signals=False))
            await asyncio.sleep(4.5)
            stop.set()
            return await asyncio.wait_for(task, timeout=10)

    rec = asyncio.run(scenario())

    assert conns["n"] >= 2, "collector should have reconnected after the drop"
    events = [json.loads(l) for l in open(tmp_path / "events.jsonl")]
    kinds = [e["kind"] for e in events]
    assert kinds.count("connect") >= 2
    assert "disconnect" in kinds
    assert "gap" in kinds, "the reconnect pause must be recorded as a gap"
    assert kinds[-1] == "stopped"

    book = pq.ParquetDataset(tmp_path / "book" / "BTCUSDT").read()
    assert book.schema.equals(c.BOOK_SCHEMA)
    eth = pq.ParquetDataset(tmp_path / "book" / "ETHUSDT").read()
    assert book.num_rows + eth.num_rows == rec.n_book, "every received row must reach disk"
    t = book.to_pydict()
    assert all(b < a for b, a in zip(t["bid_px_0"], t["ask_px_0"])), "book must never be crossed"
    assert t["recv_ns"] == sorted(t["recv_ns"])
    assert pq.ParquetDataset(tmp_path / "trades" / "ETHUSDT").read().num_rows > 10
    assert not list(Path(tmp_path).rglob("*.tmp")), "no half-written files left behind"
