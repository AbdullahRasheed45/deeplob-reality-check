# P0: Repository scaffold, configuration and CI

**Goal:** an installable package with config loading, run directories, a CLI entry point, seeding and CI, so every later phase plugs in the same way.

## Files to create

### `pyproject.toml`
- `[project]` name `lobrc`, version `0.1.0`, `requires-python = ">=3.11"`, dependencies exactly as in PLAN.md section 3.
- `[project.optional-dependencies] dev = ["pytest>=8", "ruff>=0.4"]`.
- `[project.scripts] lobrc = "lobrc.cli:main"`.
- `[tool.setuptools.packages.find] where = ["src"]`.
- `[tool.pytest.ini_options] testpaths = ["tests", "collector"]`, `addopts = "-q"`.
- `[tool.ruff] line-length = 100`, `target-version = "py311"`, select `["E", "F", "I", "B", "UP"]`.

### `.gitignore`
`data/`, `runs/`, `datasets/`, `site/`, `*.parquet`, `*.npz`, `*.pt`, `__pycache__/`, `.pytest_cache/`, `.venv/`, `*.tmp`, `fi2010/` (downloaded raw benchmark).

### `Makefile` targets
`install` (`pip install -e ".[dev]"`), `test` (`pytest`), `lint` (`ruff check .`), `fi2010-download`, `fi2010-train`, `crypto-dataset`, `train-baselines`, `train-deeplob`, `backtest`, `report`. Each target calls the `lobrc` CLI with the matching config (commands defined in later phases).

### `src/lobrc/config.py`
- `load_config(path: str | Path, overrides: list[str] = ()) -> dict`: reads YAML; if the file has key `inherits: <other.yaml>`, load that first (relative to the same folder) and deep-merge the child over it. Apply overrides of the form `a.b.c=value`, where `value` is parsed with `yaml.safe_load` (so `3`, `0.5`, `true`, `[1,2]` work). Unknown override keys raise `KeyError` (prevents typos).
- `to_namespace(d: dict)`: converts nested dicts into read-only `types.SimpleNamespace` (attribute access). Tests may use dicts directly.
- `dump_config(cfg: dict, path)`: writes YAML with sorted keys.

### `src/lobrc/runs.py`
- `new_run(kind: str, name: str, cfg: dict, root="runs") -> Path`: creates `runs/<kind>/<UTC YYYYmmdd-HHMMSS>-<name>/`, writes `config.yaml`, writes `git.txt` (`git rev-parse HEAD` and `git status --porcelain | wc -l > 0` as `dirty=true/false`; if git is missing, write `unknown`), attaches a file handler for `log.txt`, returns the path.
- `save_metrics(run_dir, metrics: dict)`: writes `metrics.json` (indent 2, sorted keys, floats as given).

### `src/lobrc/seed.py`
`set_seed(seed: int = 1234)`: seeds `random`, `numpy`, `torch` (CPU and CUDA), sets cudnn deterministic/benchmark flags, sets env `PYTHONHASHSEED`.

### `src/lobrc/cli.py`
`argparse` with subcommands. P0 only registers `lobrc version`. Later phases add subcommands in their own modules via a `register(subparsers)` function each module exposes; `cli.py` imports and calls them. Every subcommand accepts `--config PATH` and repeated `--set KEY=VALUE`.

### `configs/default.yaml`
```yaml
seed: 1234
paths:
  data_dir: data            # raw collector output (on the VM, or rsynced copy on the laptop)
  datasets_dir: datasets
  runs_dir: runs
  results_dir: results
  fi2010_dir: fi2010
symbols: [BTCUSDT, ETHUSDT]
primary_symbol: BTCUSDT
levels: 10
snapshot_ms: 100
gap_secs: 1.0
```
Later phases add their own config files that `inherits: default.yaml`.

### `.github/workflows/ci.yml`
On push and pull request: Ubuntu latest, Python 3.11, install CPU torch (`pip install torch --index-url https://download.pytorch.org/whl/cpu`), then `pip install -e ".[dev]"`, then `ruff check .` and `pytest`. Cache pip.

### `STATUS.md`, `DECISIONS.md`
Create with headers only. `DECISIONS.md` header row: `Date | Phase | Decision | Reason`.

## Tests (`tests/test_config.py`)
1. `test_inherits_and_override`: base `{a: 1, b: {c: 2}}`, child `inherits: base.yaml` with `{b: {d: 3}}`; override `b.c=5` gives `{a: 1, b: {c: 5, d: 3}}`.
2. `test_unknown_override_raises`: override `b.zz=1` raises `KeyError`.
3. `test_new_run_writes_files` (tmp_path): `config.yaml`, `git.txt` and `log.txt` exist.
4. `test_seed_reproducible`: two calls to `set_seed(1)` then `torch.rand(3)` give identical tensors.

## Acceptance criteria
- `pip install -e ".[dev]"` works in a fresh venv; `lobrc version` prints `0.1.0`.
- `pytest` passes (including the existing `collector/test_collector.py`); `ruff check .` clean; CI green on GitHub.
