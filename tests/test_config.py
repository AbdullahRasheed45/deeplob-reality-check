"""Tests for config loading, run directories and seeding (Phase 0)."""
from pathlib import Path

import pytest
import torch
import yaml

from lobrc.config import dump_config, load_config, to_namespace
from lobrc.runs import new_run, save_metrics
from lobrc.seed import set_seed


def _write(path: Path, d: dict) -> None:
    path.write_text(yaml.safe_dump(d))


def test_inherits_and_override(tmp_path):
    _write(tmp_path / "base.yaml", {"a": 1, "b": {"c": 2}})
    _write(tmp_path / "child.yaml", {"inherits": "base.yaml", "b": {"d": 3}})
    cfg = load_config(tmp_path / "child.yaml", ["b.c=5"])
    assert cfg == {"a": 1, "b": {"c": 5, "d": 3}}


def test_unknown_override_raises(tmp_path):
    _write(tmp_path / "base.yaml", {"a": 1, "b": {"c": 2}})
    with pytest.raises(KeyError):
        load_config(tmp_path / "base.yaml", ["b.zz=1"])


def test_override_parses_yaml_values(tmp_path):
    _write(tmp_path / "base.yaml", {"a": 1, "b": 0.1, "c": False, "d": [0]})
    cfg = load_config(tmp_path / "base.yaml", ["a=3", "b=0.5", "c=true", "d=[1,2]"])
    assert cfg == {"a": 3, "b": 0.5, "c": True, "d": [1, 2]}


def test_namespace_and_dump(tmp_path):
    ns = to_namespace({"a": {"b": 1}})
    assert ns.a.b == 1
    dump_config({"z": 1, "a": 2}, tmp_path / "out.yaml")
    text = (tmp_path / "out.yaml").read_text()
    assert text.index("a:") < text.index("z:")


def test_new_run_writes_files(tmp_path):
    run = new_run("test", "demo", {"x": 1}, root=tmp_path)
    assert (run / "config.yaml").exists()
    assert (run / "git.txt").exists()
    assert (run / "log.txt").exists()
    save_metrics(run, {"f1": 0.5})
    assert (run / "metrics.json").exists()


def test_seed_reproducible():
    set_seed(1)
    a = torch.rand(3)
    set_seed(1)
    b = torch.rand(3)
    assert torch.equal(a, b)
