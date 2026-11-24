"""YAML configuration loading with inheritance and command-line overrides.

Finance concept: a backtest is only credible if every setting (fees, latency, horizons) is
written down and reproducible. Keeping all of them in versioned YAML, and saving the fully
resolved config with every run, lets anyone re-create a result exactly.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml


def _deep_merge(base: dict, child: dict) -> dict:
    out = deepcopy(base)
    for k, v in child.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def _load_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    parent = cfg.pop("inherits", None)
    if parent:
        base = _load_file(path.parent / parent)
        cfg = _deep_merge(base, cfg)
    return cfg


def _apply_override(cfg: dict, override: str) -> None:
    if "=" not in override:
        raise ValueError(f"override must look like a.b.c=value, got {override!r}")
    key, raw = override.split("=", 1)
    parts = key.split(".")
    node: Any = cfg
    for p in parts[:-1]:
        if not isinstance(node, dict) or p not in node:
            raise KeyError(f"unknown config key {key!r}")
        node = node[p]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise KeyError(f"unknown config key {key!r}")
    node[parts[-1]] = yaml.safe_load(raw)


def load_config(path: str | Path, overrides: list[str] | tuple[str, ...] = ()) -> dict:
    """Load a YAML config, resolving `inherits:` and applying `a.b.c=value` overrides."""
    cfg = _load_file(Path(path))
    for o in overrides:
        _apply_override(cfg, o)
    return cfg


def to_namespace(d: dict) -> SimpleNamespace:
    """Convert nested dicts to attribute-access namespaces."""
    return SimpleNamespace(
        **{k: to_namespace(v) if isinstance(v, dict) else v for k, v in d.items()}
    )


def dump_config(cfg: dict, path: str | Path) -> None:
    """Write a config to YAML with sorted keys."""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=True)
