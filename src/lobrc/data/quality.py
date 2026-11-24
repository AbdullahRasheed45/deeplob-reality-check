"""Data-quality report: can we trust the recorded order books?

Concept: a backtest is only as honest as its data. Gaps (missing seconds), crossed books
(best bid >= best ask, which is impossible in a real market and so means a bug), duplicate
update ids (stale snapshots) and the spread distribution are the first things a quant checks
before touching a model. Spread in basis points (bps) is (ask - bid) / mid * 1e4.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from lobrc.cli import add_common_args  # noqa: E402
from lobrc.config import load_config  # noqa: E402
from lobrc.data.files import list_dates, read_day  # noqa: E402

log = logging.getLogger(__name__)

LEVELS = 10
DAY_SECS = 86_400
SNAPSHOTS_PER_SEC = 10
TRADE_GAP_SECS = 10.0
BOOK_COLS = (
    ["recv_ns", "last_update_id"]
    + [f"{s}_{k}_{i}" for s in ("bid", "ask") for k in ("px", "sz") for i in range(LEVELS)]
)


def _date_of_ns(ts_ns: int) -> str:
    return datetime.fromtimestamp(ts_ns / 1e9, tz=UTC).strftime("%Y-%m-%d")


def _load_events(data_dir: Path) -> list[dict]:
    path = data_dir / "events.jsonl"
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _day_row(
    symbol: str, date: str, book, trades, events: list[dict], gap_secs: float, is_edge_day: bool
) -> tuple[dict, list[dict], np.ndarray]:
    recv = book["recv_ns"].to_numpy()
    uid = book["last_update_id"].to_numpy()
    cols = {c: book[c].to_numpy() for c in BOOK_COLS if c not in ("recv_ns", "last_update_id")}

    rows = len(recv)
    span_secs = (recv[-1] - recv[0]) / 1e9 if rows > 1 else 0.0
    expected = (span_secs if is_edge_day else DAY_SECS) * SNAPSHOTS_PER_SEC

    dt = np.diff(recv)
    gap_idx = np.flatnonzero(dt > gap_secs * 1e9)
    gaps = [
        {"symbol": symbol, "date": date, "start_ns": int(recv[i]), "end_ns": int(recv[i + 1]),
         "secs": float(dt[i] / 1e9)}
        for i in gap_idx
    ]

    bid0, ask0 = cols["bid_px_0"], cols["ask_px_0"]
    nan_rows = np.zeros(rows, dtype=bool)
    for v in cols.values():
        nan_rows |= np.isnan(v)
    valid = ~nan_rows & (bid0 < ask0)
    mid = (ask0 + bid0) / 2
    spread = np.full(rows, np.nan)
    spread[valid] = (ask0[valid] - bid0[valid]) / mid[valid] * 1e4
    spread_ok = spread[valid]

    out = {
        "symbol": symbol, "date": date, "rows": rows, "expected_rows": expected,
        "coverage": rows / expected if expected > 0 else np.nan,
        "n_gaps": len(gaps),
        "gap_secs_total": float(sum(g["secs"] for g in gaps)),
        "max_gap_secs": float(max((g["secs"] for g in gaps), default=0.0)),
        "crossed_rows": int(np.sum(~nan_rows & (bid0 >= ask0))),
        "nan_level_rows": int(nan_rows.sum()),
        "dup_update_id_frac": float(np.mean(uid[1:] == uid[:-1])) if rows > 1 else 0.0,
        "spread_bps_p50": float(np.percentile(spread_ok, 50)) if len(spread_ok) else np.nan,
        "spread_bps_p99": float(np.percentile(spread_ok, 99)) if len(spread_ok) else np.nan,
        "trades": 0, "trade_gaps": 0,
        "disconnects": sum(
            1 for e in events
            if e.get("kind") == "disconnect" and _date_of_ns(int(e["ts_ns"])) == date
        ),
    }
    if trades is not None:
        tr = trades["recv_ns"].to_numpy()
        out["trades"] = len(tr)
        out["trade_gaps"] = int(np.sum(np.diff(tr) > TRADE_GAP_SECS * 1e9))
    return out, gaps, spread_ok


def _plot_spread(spread_ok: np.ndarray, symbol: str, date: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    if len(spread_ok):
        clip = np.percentile(spread_ok, 99.5)
        ax.hist(np.clip(spread_ok, None, clip), bins=100)
    ax.set_xlabel("spread (bps)")
    ax.set_ylabel("snapshots")
    ax.set_title(f"{symbol} spread, {date} (clipped at p99.5)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _merge_csv(path: Path, new: pd.DataFrame, key: list[str]) -> pd.DataFrame:
    """Append `new` to the CSV, replacing existing rows with the same key values."""
    if path.exists() and len(new):
        old = pd.read_csv(path)
        merged_keys = new[key].astype(str).agg("|".join, axis=1)
        old_keys = old[key].astype(str).agg("|".join, axis=1)
        new = pd.concat([old[~old_keys.isin(set(merged_keys))], new], ignore_index=True)
    elif path.exists():
        new = pd.read_csv(path)
    return new


def run_quality(
    data_dir: str | Path,
    symbols: list[str],
    results_dir: str | Path,
    dates: list[str] | None = None,
    gap_secs: float = 1.0,
) -> pd.DataFrame:
    """Compute one quality row per symbol and date; write CSVs and spread plots."""
    data_dir, out_dir = Path(data_dir), Path(results_dir) / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    events = _load_events(data_dir)
    all_rows, all_gaps = [], []
    for sym in symbols:
        recorded = list_dates(data_dir, "book", sym)
        if not recorded:
            log.warning("no book data for %s", sym)
            continue
        for date in (dates or recorded):
            book = read_day(data_dir, "book", sym, date, columns=BOOK_COLS)
            if book is None or book.num_rows == 0:
                continue
            trades = read_day(data_dir, "trades", sym, date, columns=["recv_ns"])
            edge = date in (recorded[0], recorded[-1])
            row, gaps, spread_ok = _day_row(sym, date, book, trades, events, gap_secs, edge)
            all_rows.append(row)
            all_gaps += gaps
            _plot_spread(spread_ok, sym, date, out_dir / f"spread_{sym}_{date}.png")
            log.info("%s %s rows=%d gaps=%d crossed=%d", sym, date, row["rows"], row["n_gaps"],
                     row["crossed_rows"])
    df = pd.DataFrame(all_rows)
    for sym in symbols:
        part = df[df["symbol"] == sym] if len(df) else df
        if len(part):
            merged = _merge_csv(out_dir / f"quality_{sym}.csv", part, ["date"])
            merged.sort_values("date").to_csv(out_dir / f"quality_{sym}.csv", index=False)
    gap_cols = ["symbol", "date", "start_ns", "end_ns", "secs"]
    gdf = pd.DataFrame(all_gaps, columns=gap_cols)
    gpath = out_dir / "gaps.csv"
    if gpath.exists() and len(df):
        # replace gaps of the (symbol, date) pairs recomputed in this run
        old = pd.read_csv(gpath)
        done = set(zip(df["symbol"], df["date"], strict=True))
        old = old[[(s, d) not in done for s, d in zip(old["symbol"], old["date"], strict=True)]]
        gdf = pd.concat([old, gdf], ignore_index=True)
    gdf.sort_values(["symbol", "start_ns"]).to_csv(gpath, index=False)
    return df


def _cmd_quality(args: argparse.Namespace) -> int:
    cfg = load_config(args.config, args.overrides)
    df = run_quality(
        cfg["paths"]["data_dir"], cfg["symbols"], cfg["paths"]["results_dir"],
        dates=[args.date] if args.date else None, gap_secs=float(cfg["gap_secs"]),
    )
    print(df.to_string(index=False) if len(df) else "no data found")
    return 1 if len(df) and (df["crossed_rows"] > 0).any() else 0


def register(sub) -> None:
    """Add `lobrc quality` to the CLI."""
    p = sub.add_parser("quality", help="per-day data-quality report")
    add_common_args(p)
    p.add_argument("--date", default=None, help="UTC date YYYY-MM-DD (default: all dates)")
    p.set_defaults(func=_cmd_quality)
