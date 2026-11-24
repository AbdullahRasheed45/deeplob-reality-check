"""Tests for the compactor (Phase 1, step 5)."""
import pyarrow as pa
import pyarrow.parquet as pq
from synth import day_start_ns, make_synthetic_arrays, write_synthetic_day

from lobrc.data.compact import compact_all

DATE = "2026-11-20"


def _setup(tmp_path):
    start = day_start_ns(DATE) + 10 * 3_600_000_000_000 + 1_800_000_000_000  # 10:30 UTC
    arrays, _ = make_synthetic_arrays(n=36_000, start_ns=start)  # one hour: 10:30-11:30
    paths = write_synthetic_day(tmp_path / "data", "BTCUSDT", DATE, arrays, n_parts=30)
    return arrays, paths


def test_compact_two_hours(tmp_path):
    arrays, parts = _setup(tmp_path)
    assert len(parts) == 30
    compact_all(tmp_path / "data", ["BTCUSDT"], before="2026-11-21")
    day = tmp_path / "data" / "book" / "BTCUSDT" / DATE
    hours = sorted(p.name for p in day.glob("hour-*.parquet"))
    assert hours == ["hour-10.parquet", "hour-11.parquet"]
    assert not list(day.glob("part-*.parquet"))
    total = sum(pq.read_table(day / h).num_rows for h in hours)
    assert total == 36_000
    t = pa.concat_tables([pq.read_table(day / h) for h in hours])
    recv = t["recv_ns"].to_numpy()
    assert (recv[1:] >= recv[:-1]).all()
    assert recv[0] == arrays["recv_ns"][0] and recv[-1] == arrays["recv_ns"][-1]
    moved = tmp_path / "data" / "_compacted_parts" / "book" / "BTCUSDT" / DATE
    assert len(list(moved.glob("part-*.parquet"))) == 30


def test_idempotent_and_skips_today(tmp_path):
    _setup(tmp_path)
    compact_all(tmp_path / "data", ["BTCUSDT"], before=DATE)  # DATE itself is not before DATE
    day = tmp_path / "data" / "book" / "BTCUSDT" / DATE
    assert len(list(day.glob("part-*.parquet"))) == 30 and not list(day.glob("hour-*"))
    compact_all(tmp_path / "data", ["BTCUSDT"], before="2026-11-21")
    compact_all(tmp_path / "data", ["BTCUSDT"], before="2026-11-21")  # second run: no-op
    names = sorted(p.name for p in day.glob("hour-*.parquet"))
    assert names == ["hour-10.parquet", "hour-11.parquet"]
