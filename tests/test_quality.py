"""Tests for the data-quality report (Phase 1, step 4)."""
import json

import pandas as pd
from synth import day_start_ns, make_synthetic_arrays, write_synthetic_day, write_trades_file

from lobrc.data.quality import run_quality

DATE = "2026-11-20"


def _setup(tmp_path):
    start = day_start_ns(DATE) + 3_600_000_000_000  # 01:00 UTC
    arrays, _ = make_synthetic_arrays(
        n=20_000, start_ns=start, gaps=[(5000, 5.0)], crossed_rows=[7000]
    )
    write_synthetic_day(tmp_path / "data", "BTCUSDT", DATE, arrays)
    # trades: 100 trades one per second, with a 20 s hole in the middle
    t0 = int(arrays["recv_ns"][0])
    secs = [*range(0, 50), *range(70, 120)]
    import numpy as np

    write_trades_file(tmp_path / "data", "BTCUSDT", DATE, t0 + np.array(secs) * 1_000_000_000)
    ev = {"ts_ns": t0 + 1_000_000_000, "kind": "disconnect"}
    (tmp_path / "data" / "events.jsonl").write_text(json.dumps(ev) + "\n")
    return arrays


def test_gap_and_crossed_detection(tmp_path):
    _setup(tmp_path)
    df = run_quality(tmp_path / "data", ["BTCUSDT"], tmp_path / "results", dates=[DATE])
    row = df.iloc[0]
    assert row["n_gaps"] == 1
    assert 4.9 <= row["max_gap_secs"] <= 5.2
    assert row["crossed_rows"] == 1
    assert row["rows"] == 20_000
    assert row["nan_level_rows"] == 0
    assert row["trades"] == 100
    assert row["trade_gaps"] == 1
    assert row["disconnects"] == 1
    assert 0.9 < row["coverage"] <= 1.0
    assert row["spread_bps_p50"] > 0


def test_outputs_written_and_overwritten_by_date(tmp_path):
    _setup(tmp_path)
    for _ in range(2):  # running twice must not duplicate the date
        run_quality(tmp_path / "data", ["BTCUSDT"], tmp_path / "results", dates=[DATE])
    out = tmp_path / "results" / "quality"
    csv = pd.read_csv(out / "quality_BTCUSDT.csv")
    assert len(csv) == 1
    gaps = pd.read_csv(out / "gaps.csv")
    assert len(gaps) == 1 and gaps.iloc[0]["symbol"] == "BTCUSDT"
    assert (out / f"spread_BTCUSDT_{DATE}.png").exists()
