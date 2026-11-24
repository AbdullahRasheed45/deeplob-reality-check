"""Synthetic order-book data for tests (no network, fully deterministic).

Concept: to test code that cleans and scores real order books we need books whose truth we
know: where the gaps are, which rows are crossed, and whether the book really predicts the
next price move. The generator below hides a latent imbalance `z`; when `signal_strength > 0`
the next mid-price move leans in the direction of `z`, like real queue imbalance does.

P1 needs the array generator and the Parquet day writer. P2 adds `BookData` wrappers on top.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

LEVELS = 10


def book_schema() -> pa.Schema:
    """Same column order and types as the collector's BOOK_SCHEMA."""
    fields = [("recv_ns", pa.int64()), ("symbol", pa.string()), ("last_update_id", pa.int64())]
    for side in ("bid", "ask"):
        for i in range(LEVELS):
            fields += [(f"{side}_px_{i}", pa.float64()), (f"{side}_sz_{i}", pa.float64())]
    return pa.schema(fields)


TRADE_SCHEMA = pa.schema([
    ("recv_ns", pa.int64()), ("symbol", pa.string()), ("trade_id", pa.int64()),
    ("event_ms", pa.int64()), ("trade_ms", pa.int64()),
    ("price", pa.float64()), ("qty", pa.float64()), ("buyer_is_maker", pa.bool_()),
])


def day_start_ns(date: str) -> int:
    """Nanoseconds since the epoch at 00:00:00 UTC of `date` (YYYY-MM-DD)."""
    dt = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    return int(dt.timestamp()) * 1_000_000_000


def make_synthetic_arrays(
    n: int = 20_000,
    seed: int = 0,
    tick: float = 0.01,
    start_ns: int = 1_700_000_000_000_000_000,
    signal_strength: float = 0.0,
    gaps: tuple = (),
    crossed_rows: tuple = (),
) -> tuple[dict[str, np.ndarray], dict]:
    """Generate n snapshots every 100 ms. Returns (arrays, info).

    `gaps` is a list of (index, secs): `secs` extra seconds are inserted before row `index`.
    `crossed_rows` lists indices whose best bid is pushed above the best ask (a data bug).
    """
    rng = np.random.default_rng(seed)
    eps = rng.standard_normal(n)
    z = np.zeros(n)
    for t in range(1, n):
        z[t] = 0.95 * z[t - 1] + 0.3 * eps[t]

    # Mid moves one tick with probability 0.3; direction leans on the previous latent z.
    moves = rng.random(n) < 0.3
    p_up = 0.5 + signal_strength * np.tanh(np.concatenate([[0.0], z[:-1]]))
    ups = rng.random(n) < p_up
    step = np.where(moves, np.where(ups, tick, -tick), 0.0)
    mid = np.round(100.005 + np.cumsum(step), 8)

    recv_ns = start_ns + np.arange(n, dtype=np.int64) * 100_000_000
    for idx, secs in gaps:
        recv_ns[idx:] += int(round(secs * 1e9))

    lv = np.arange(LEVELS)
    bid_px = np.round((mid - tick / 2)[:, None] - lv[None, :] * tick, 8)
    ask_px = np.round((mid + tick / 2)[:, None] + lv[None, :] * tick, 8)

    bid_sz = rng.lognormal(0.5, 0.5, (n, LEVELS))
    ask_sz = rng.lognormal(0.5, 0.5, (n, LEVELS))
    bid_sz[:, 0] = rng.lognormal(0, 0.5, n) * (1 + 0.5 * np.maximum(z, 0))
    ask_sz[:, 0] = rng.lognormal(0, 0.5, n) * (1 + 0.5 * np.maximum(-z, 0))

    for i in crossed_rows:
        bid_px[i, 0] = ask_px[i, 0] + tick

    arrays = {
        "recv_ns": recv_ns,
        "last_update_id": 1000 + np.arange(n, dtype=np.int64),
        "bid_px": bid_px, "bid_sz": bid_sz, "ask_px": ask_px, "ask_sz": ask_sz,
    }
    return arrays, {"z": z, "mid": mid, "tick": tick, "signal_strength": signal_strength}


def write_synthetic_day(
    data_dir: str | Path,
    symbol: str,
    date: str,
    arrays: dict[str, np.ndarray],
    n_parts: int = 4,
) -> list[Path]:
    """Write arrays as `n_parts` collector-style part files under book/<symbol>/<date>/."""
    out = Path(data_dir) / "book" / symbol / date
    out.mkdir(parents=True, exist_ok=True)
    n = len(arrays["recv_ns"])
    paths = []
    for chunk in np.array_split(np.arange(n), n_parts):
        if len(chunk) == 0:
            continue
        cols = {
            "recv_ns": arrays["recv_ns"][chunk],
            "symbol": [symbol] * len(chunk),
            "last_update_id": arrays["last_update_id"][chunk],
        }
        for side in ("bid", "ask"):
            for i in range(LEVELS):
                cols[f"{side}_px_{i}"] = arrays[f"{side}_px"][chunk, i]
                cols[f"{side}_sz_{i}"] = arrays[f"{side}_sz"][chunk, i]
        table = pa.table(cols, schema=book_schema())
        path = out / f"part-{int(arrays['recv_ns'][chunk[0]])}.parquet"
        pq.write_table(table, path)
        paths.append(path)
    return paths


def write_trades_file(
    data_dir: str | Path, symbol: str, date: str, recv_ns: np.ndarray, price: float = 100.0
) -> Path:
    """Write one trades part file with trades at the given receive times."""
    out = Path(data_dir) / "trades" / symbol / date
    out.mkdir(parents=True, exist_ok=True)
    m = len(recv_ns)
    table = pa.table(
        {
            "recv_ns": recv_ns.astype(np.int64),
            "symbol": [symbol] * m,
            "trade_id": np.arange(m, dtype=np.int64),
            "event_ms": (recv_ns // 1_000_000).astype(np.int64),
            "trade_ms": (recv_ns // 1_000_000).astype(np.int64),
            "price": np.full(m, price),
            "qty": np.full(m, 0.1),
            "buyer_is_maker": np.zeros(m, dtype=bool),
        },
        schema=TRADE_SCHEMA,
    )
    path = out / f"part-{int(recv_ns[0])}.parquet"
    pq.write_table(table, path)
    return path
