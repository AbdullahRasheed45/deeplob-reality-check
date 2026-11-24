"""Collector health check: is the recorder still writing fresh, complete data?

Concept: a silent recorder is the most expensive failure in this project, because market data
cannot be re-downloaded later. A cron or systemd timer runs this check every few minutes and
(optionally) pings an external dead-man's-switch such as healthchecks.io.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from lobrc.cli import add_common_args
from lobrc.config import load_config

log = logging.getLogger(__name__)

DISCONNECT_TOLERANCE_SECS = 120.0


@dataclass
class HealthResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    newest_file_age_secs: dict[str, float] = field(default_factory=dict)
    last_event: dict | None = None


def _last_event(path: Path) -> dict | None:
    """Parse the last non-empty line of events.jsonl without reading the whole file."""
    if not path.is_file():
        return None
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 8192))
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    for raw in reversed(lines):
        try:
            return json.loads(raw)
        except ValueError:
            continue  # a truncated first line of the tail window, or a partial write
    return None


def check_health(
    data_dir: str | Path,
    symbols: list[str],
    max_age_secs: float = 300.0,
    now_ns: int | None = None,
    min_free_frac: float = 0.10,
) -> HealthResult:
    """Run the three health rules and collect a human-readable problem for each failure."""
    data_dir = Path(data_dir)
    now_ns = time.time_ns() if now_ns is None else now_ns
    problems: list[str] = []
    ages: dict[str, float] = {}

    for sym in symbols:  # rule 1: fresh book files
        files = list((data_dir / "book" / sym).glob("*/part-*.parquet"))
        if not files:
            problems.append(f"{sym}: no book part files found")
            continue
        newest = max(f.stat().st_mtime_ns for f in files)
        ages[sym] = (now_ns - newest) / 1e9
        if ages[sym] > max_age_secs:
            problems.append(
                f"{sym}: newest book file is {ages[sym]:.0f}s old (limit {max_age_secs:.0f}s)"
            )

    last = _last_event(data_dir / "events.jsonl")  # rule 2: no stale disconnect
    if last and last.get("kind") == "disconnect":
        age = (now_ns - int(last.get("ts_ns", now_ns))) / 1e9
        if age > DISCONNECT_TOLERANCE_SECS:
            problems.append(f"last event is a disconnect from {age:.0f}s ago (not reconnected)")

    if data_dir.exists():  # rule 3: disk space
        usage = shutil.disk_usage(data_dir)
        free = usage.free / usage.total
        if free < min_free_frac:
            problems.append(f"disk only {free:.1%} free (need {min_free_frac:.0%})")

    return HealthResult(not problems, problems, ages, last)


def _ping(url: str) -> None:
    """healthchecks.io convention: GET url on success, url/fail on failure. Errors ignored."""
    try:
        urllib.request.urlopen(url, timeout=10).close()  # noqa: S310 (fixed https URL from env)
    except Exception:  # noqa: BLE001
        log.debug("health ping failed", exc_info=True)


def _cmd_health(args: argparse.Namespace) -> int:
    cfg = load_config(args.config, args.overrides)
    res = check_health(cfg["paths"]["data_dir"], cfg["symbols"], args.max_age_secs)
    for p in res.problems:
        print(p)
    if res.ok:
        print("ok", {k: round(v) for k, v in res.newest_file_age_secs.items()})
    hc = os.environ.get("HC_URL")
    if hc:
        _ping(hc if res.ok else hc.rstrip("/") + "/fail")
    return 0 if res.ok else 1


def register(sub) -> None:
    """Add `lobrc health` to the CLI."""
    p = sub.add_parser("health", help="exit 1 if the collector looks unhealthy")
    add_common_args(p)
    p.add_argument("--max-age-secs", type=float, default=300.0)
    p.set_defaults(func=_cmd_health)
