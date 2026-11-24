"""Tests for the collector health check (Phase 1, step 3)."""
import json
import os
import time

from lobrc.data.health import check_health


def _make_part(data_dir, symbol="BTCUSDT", age_secs=0.0):
    d = data_dir / "book" / symbol / "2026-11-24"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "part-1.parquet"
    f.write_bytes(b"x")
    t = time.time() - age_secs
    os.utime(f, (t, t))


def _write_event(data_dir, kind, age_secs):
    rec = {"ts_ns": int((time.time() - age_secs) * 1e9), "kind": kind}
    with open(data_dir / "events.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")


def test_fresh_file_is_ok(tmp_path):
    _make_part(tmp_path, age_secs=5)
    _write_event(tmp_path, "connect", 10)
    res = check_health(tmp_path, ["BTCUSDT"])
    assert res.ok, res.problems
    assert res.newest_file_age_secs["BTCUSDT"] < 60
    assert res.last_event["kind"] == "connect"


def test_old_file_fails_and_names_symbol(tmp_path):
    _make_part(tmp_path, age_secs=3600)
    res = check_health(tmp_path, ["BTCUSDT"])
    assert not res.ok
    assert any("BTCUSDT" in p for p in res.problems)


def test_missing_symbol_fails(tmp_path):
    _make_part(tmp_path, "BTCUSDT", age_secs=1)
    res = check_health(tmp_path, ["BTCUSDT", "ETHUSDT"])
    assert not res.ok
    assert any("ETHUSDT" in p for p in res.problems)


def test_old_disconnect_fails(tmp_path):
    _make_part(tmp_path, age_secs=1)
    _write_event(tmp_path, "disconnect", 600)
    res = check_health(tmp_path, ["BTCUSDT"])
    assert not res.ok
    assert any("disconnect" in p for p in res.problems)


def test_recent_disconnect_is_tolerated(tmp_path):
    _make_part(tmp_path, age_secs=1)
    _write_event(tmp_path, "disconnect", 20)
    assert check_health(tmp_path, ["BTCUSDT"]).ok


def test_low_disk_fails(tmp_path):
    _make_part(tmp_path, age_secs=1)
    res = check_health(tmp_path, ["BTCUSDT"], min_free_frac=1.01)
    assert not res.ok
    assert any("disk" in p for p in res.problems)
