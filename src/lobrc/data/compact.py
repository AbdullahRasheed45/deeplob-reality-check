"""Compaction: merge the collector's many small Parquet files into one file per hour.

Concept: the collector flushes every couple of minutes, so a day leaves hundreds of tiny
files. Reading many small files is slow (each open costs a syscall plus Parquet metadata
parsing), while a handful of hour files scan fast and compress better. Compaction is the only
thing allowed to rewrite raw data, and it is paranoid: it writes new files first, verifies row
counts and time ranges, and only then moves the originals aside (never deletes them).
"""
from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from lobrc.cli import add_common_args
from lobrc.config import load_config
from lobrc.data.files import list_dates

log = logging.getLogger(__name__)

HOUR_NS = 3_600 * 1_000_000_000
DAY_NS = 24 * HOUR_NS
KINDS = ("book", "trades")


def compact_day(data_dir: Path, kind: str, symbol: str, date: str) -> str:
    """Compact one day. Returns 'compacted', 'skipped' or 'needs-attention'."""
    day = data_dir / kind / symbol / date
    parts = sorted(day.glob("part-*.parquet"))
    hours = sorted(day.glob("hour-*.parquet"))
    if not parts:
        return "skipped"  # already compacted (or empty)
    if hours:
        log.error("%s has both part and hour files; inspect by hand, not touching it", day)
        return "needs-attention"

    table = pa.concat_tables([pq.read_table(p) for p in parts])
    table = table.take(pc.sort_indices(table["recv_ns"]))  # stable sort
    recv = table["recv_ns"].to_numpy()
    hour_of_day = (recv % DAY_NS) // HOUR_NS

    written: list[Path] = []
    for h in np.unique(hour_of_day):
        sub = table.filter(pa.array(hour_of_day == h))
        final = day / f"hour-{int(h):02d}.parquet"
        tmp = day / f".hour-{int(h):02d}.parquet.tmp"
        pq.write_table(sub, tmp, compression="zstd")
        tmp.rename(final)
        written.append(final)

    new_rows = sum(pq.read_metadata(f).num_rows for f in written)
    old_rows = sum(pq.read_metadata(p).num_rows for p in parts)
    new_recv = pa.concat_tables([pq.read_table(f, columns=["recv_ns"]) for f in written])
    new_min, new_max = pc.min_max(new_recv["recv_ns"]).as_py().values()
    if new_rows != old_rows or new_min != int(recv[0]) or new_max != int(recv[-1]):
        for f in written:
            f.unlink()  # remove our new files; originals untouched
        raise RuntimeError(f"verification failed for {day}: rows {old_rows}->{new_rows}")

    dest = data_dir / "_compacted_parts" / kind / symbol / date
    dest.mkdir(parents=True, exist_ok=True)
    for p in parts:
        shutil.move(str(p), str(dest / p.name))
    log.info("compacted %s: %d parts -> %d hour files, %d rows", day, len(parts), len(written),
             new_rows)
    return "compacted"


def compact_all(data_dir: str | Path, symbols: list[str], before: str) -> dict[str, int]:
    """Compact every symbol/kind/date strictly before `before` (YYYY-MM-DD)."""
    data_dir = Path(data_dir)
    counts = {"compacted": 0, "skipped": 0, "needs-attention": 0}
    for sym in symbols:
        for kind in KINDS:
            for date in list_dates(data_dir, kind, sym):
                if date < before:
                    counts[compact_day(data_dir, kind, sym, date)] += 1
    return counts


def _cmd_compact(args: argparse.Namespace) -> int:
    cfg = load_config(args.config, args.overrides)
    counts = compact_all(cfg["paths"]["data_dir"], cfg["symbols"], args.before)
    print(counts)
    return 1 if counts["needs-attention"] else 0


def register(sub) -> None:
    """Add `lobrc compact` to the CLI."""
    p = sub.add_parser("compact", help="merge part files into hourly files")
    add_common_args(p)
    p.add_argument("--before", required=True, help="compact UTC dates strictly before this")
    p.set_defaults(func=_cmd_compact)
