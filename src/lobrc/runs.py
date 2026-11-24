"""Run directories: one folder per experiment holding config, git hash, log and metrics.

Finance concept: research results are only trustworthy if you can say exactly which code and
settings produced them. Recording the commit hash and resolved config beside every result
is the cheapest guard against "it worked on my machine" backtests.
"""
from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from lobrc.config import dump_config

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def _git_info() -> str:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return f"{head}\ndirty={'true' if status else 'false'}\n"
    except (OSError, subprocess.CalledProcessError):
        return "unknown\n"


def new_run(kind: str, name: str, cfg: dict, root: str | Path = "runs") -> Path:
    """Create runs/<kind>/<UTC stamp>-<name>/ with config.yaml, git.txt and a log.txt handler."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = Path(root) / kind / f"{stamp}-{name}"
    run_dir.mkdir(parents=True, exist_ok=True)
    dump_config(cfg, run_dir / "config.yaml")
    (run_dir / "git.txt").write_text(_git_info(), encoding="utf-8")
    handler = logging.FileHandler(run_dir / "log.txt", encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    return run_dir


def save_metrics(run_dir: str | Path, metrics: dict) -> None:
    """Write metrics.json (indent 2, sorted keys)."""
    with open(Path(run_dir) / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, sort_keys=True)
