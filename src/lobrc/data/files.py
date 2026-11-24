"""Locating the collector's Parquet files on disk.

Concept: the collector writes many small `part-*.parquet` files per UTC day, and the compactor
later merges them into one `hour-HH.parquet` per hour. Every reader must understand both
layouts, so file discovery lives in one place.

Layout: <data_dir>/<kind>/<SYMBOL>/<YYYY-MM-DD>/{part,hour}-*.parquet, kind in {book, trades}.
"""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DATE_LEN = len("YYYY-MM-DD")


def list_dates(data_dir: str | Path, kind: str, symbol: str) -> list[str]:
    """Sorted UTC date folders that exist for this kind and symbol."""
    root = Path(data_dir) / kind / symbol
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and len(p.name) == DATE_LEN)


def list_files(data_dir: str | Path, kind: str, symbol: str, date: str) -> list[Path]:
    """All `part-*` and `hour-*` Parquet files of one day, sorted by name."""
    d = Path(data_dir) / kind / symbol / date
    if not d.is_dir():
        return []
    return sorted([*d.glob("part-*.parquet"), *d.glob("hour-*.parquet")])


def read_day(
    data_dir: str | Path, kind: str, symbol: str, date: str, columns: list[str] | None = None
) -> pa.Table | None:
    """Concatenate every file of one day into a single table, sorted by recv_ns (stable)."""
    files = list_files(data_dir, kind, symbol, date)
    if not files:
        return None
    table = pa.concat_tables([pq.read_table(f, columns=columns) for f in files])
    if "recv_ns" in table.column_names:
        table = table.take(pc.sort_indices(table["recv_ns"]))
    return table
