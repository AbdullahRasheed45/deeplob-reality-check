# DeepLOB Reality Check: master build plan

This is the single source of truth for building the project. It is written for an implementing agent (e.g. Claude Sonnet) working phase by phase. Read this file fully, then the phase file you are working on in `plan/`. Do not skip ahead.

## 1. What we are building

**Research question.** How much of the edge of a published deep-learning limit-order-book model (DeepLOB, Zhang, Zohren and Roberts, 2019, arXiv:1808.03668) survives (a) new data from a different market, (b) realistic latency, (c) spread and depth costs, and (d) exchange fees?

**Deliverables at the end:**
1. A faithful replication of DeepLOB on the public FI-2010 benchmark, compared with the published numbers.
2. A dataset of live Binance spot order books (BTCUSDT, ETHUSDT) recorded by our own collector, with a published data-quality and gap log.
3. DeepLOB plus three baselines trained and evaluated on that crypto data, chronologically split.
4. A cost-and-latency **waterfall**: gross edge, then latency, then spread/depth, then fees, for each latency and fee scenario, with bootstrap confidence intervals.
5. A **pre-registration** document committed before going live (hypotheses, success criteria, frozen model hash).
6. A **live paper-trading service** that runs the frozen model on the live stream for 4 to 8 weeks with no changes, using exactly the same fill logic as the backtest.
6b. A **two-location experiment**: the same frozen model runs simultaneously in London and Tokyo, and the edge lost to distance is measured signal by signal (plan/P11).
7. A public static **dashboard** (GitHub Pages), weekly reports and a final 6 to 8 page write-up.

**Never** place real orders, store exchange API keys, or call any authenticated or order endpoint. This project only reads public market data.

## 2. Verified facts the plan relies on (checked 23 Nov 2026)

| Fact | Value | Source |
| --- | --- | --- |
| FI-2010 download | `https://raw.githubusercontent.com/zcakhaa/DeepLOB-Deep-Convolutional-Neural-Networks-for-Limit-Order-Books/master/data/data.zip` (56 MB zip) | Reference repo, file `data/data.zip` |
| FI-2010 files | `Train_Dst_NoAuction_DecPre_CF_7.txt` (149 x 254,750), `Test_Dst_NoAuction_DecPre_CF_7.txt` (149 x 55,478), `..._CF_8.txt` (149 x 52,172), `..._CF_9.txt` (149 x 31,937) | Inspected directly |
| FI-2010 layout | Rows are features, columns are events. Rows 0-39 = 10 levels x [ask px, ask size, bid px, bid size]. Last 5 rows = labels for horizons 10, 20, 30, 50, 100 events | Inspected; ask > bid in 100% of columns |
| FI-2010 label codes | 1 = up, 2 = stationary, 3 = down | Verified empirically (label 1 aligns with rising future mid) |
| FI-2010 label reproducibility | Labels **cannot** be exactly recomputed from the released prices (best reconstruction about 74% at k=10). Use the provided labels | Inspected; see plan/P3 |
| FI-2010 stock boundaries | Each day file concatenates 5 stocks; boundaries show as mid jumps > 5% between consecutive events | Inspected (Test_7 has 4 such jumps, 5 segments) |
| Published DeepLOB F1, FI-2010 (7 train days / 3 test days) | k=10: 83.40%, k=20: 72.82%, k=50: 80.35% | DeepLOB paper as cited in later literature |
| Reference PyTorch notebook result (k=100, row -1) | accuracy 75.35%, macro F1 75.33% | `jupyter_pytorch/run_train_pytorch.ipynb` saved output |
| Reference training setup | Adam lr 1e-4, batch 64, 50 epochs, best checkpoint by validation loss, validation = last 20% (in time) of the training file, window T=100 | Same notebook |
| Reference quirk | `forward` returns `softmax(logits)` and the loss is `nn.CrossEntropyLoss` (which applies log-softmax again) | Same notebook |
| Binance combined stream | `wss://stream.binance.com:9443/stream?streams=a/b`, payload `{"stream": name, "data": payload}`; also `wss://data-stream.binance.vision` (market data only) | Binance docs |
| Binance connection limits | A connection is valid for 24 h; server pings every 20 s; disconnects if no pong within 1 minute | Binance docs |
| Binance spot fees | Regular user 0.100% maker and taker (10 bps); 25% lower if paying with BNB (7.5 bps). Binance.US: 0% maker, 0.02% taker | Fee guides, 2026 |

## 3. Global conventions (follow exactly; do not improvise)

- **Python** 3.11 or newer. Package name `lobrc`, source in `src/lobrc/`. Install with `pip install -e ".[dev]"`.
- **Dependencies** (minimum versions): numpy 1.26, pandas 2.1, pyarrow 15, torch 2.2, scikit-learn 1.4, lightgbm 4.3, pyyaml 6, plotly 5.20, matplotlib 3.8, websockets 14, tqdm 4.66. Dev: pytest 8, ruff 0.4. Add nothing else without recording it in `DECISIONS.md`.
- **Time:** all timestamps are `int64` nanoseconds since the Unix epoch, UTC, in columns ending `_ns`. Days are UTC dates `YYYY-MM-DD`.
- **Numbers:** prices and sizes `float64` in raw data; model tensors `float32`. Returns and costs are in **basis points (bps)**: `1 bp = 1e-4`. Variable names ending `_bps` are in bps.
- **Class encoding (internal, everywhere):** `0 = down, 1 = stationary, 2 = up`. So `direction = class - 1` gives -1, 0, +1. FI-2010 labels are mapped `{1: 2, 2: 1, 3: 0}` on load.
- **Feature order ("FI order"):** a book snapshot becomes 40 numbers: for level i = 0..9: `[ask_px_i, ask_sz_i, bid_px_i, bid_sz_i]`. Level 0 is the best price.
- **Mid-price:** `mid = (ask_px_0 + bid_px_0) / 2`. **Spread (bps):** `(ask_px_0 - bid_px_0) / mid * 1e4`.
- **Seeds:** global seed `1234` (numpy, torch, python `random`). Use `torch.backends.cudnn.deterministic = True` and `benchmark = False`.
- **Configs:** YAML in `configs/`, loaded into frozen dataclasses (`src/lobrc/config.py`). CLI overrides with `--set a.b=value`. Every run writes its fully resolved config.
- **Run directories:** `runs/<kind>/<YYYYmmdd-HHMMSS>-<name>/` containing `config.yaml`, `git.txt` (commit hash and dirty flag), `log.txt`, `metrics.json`, and artifacts. `runs/` is git-ignored except files explicitly copied to `results/`.
- **Results that go public** live in `results/` (small JSON, CSV, PNG, HTML). Never commit raw market data or large arrays.
- **Logging:** standard `logging`, INFO by default, format `%(asctime)s %(levelname)s %(name)s %(message)s`.
- **Style:** type hints everywhere, docstrings on public functions, `ruff check` clean. Pure functions where possible. No notebooks in the main pipeline (notebooks allowed only under `notebooks/` for exploration).
- **Teaching comments:** the human owner is learning quant finance from this code. At the top of every module, add a short docstring explaining the finance concept it implements (e.g. what a microprice is and why it matters). Keep them accurate and short.

## 4. Rules for the implementing agent

1. Work **one phase at a time** in order. A phase is done only when every item in its "Acceptance criteria" passes. Then commit with message `Phase N: <title>` and update `STATUS.md` (phase, date, what passed, open issues).
2. **No guessing.** If something is not specified, pick the simplest option consistent with this plan, and record it in `DECISIONS.md` as `YYYY-MM-DD | Phase | Decision | Reason`. Never silently invent a behaviour.
3. **Tests first for algorithms.** Every algorithm in the phase files has named tests with exact expected values. Write them, watch them fail, then implement.
4. **No network in tests.** Tests use small synthetic data from `tests/synth.py` (spec in plan/P2) or tiny fixtures under `tests/fixtures/`. FI-2010 and Binance are only touched by explicit CLI commands.
5. **Never tune on test data.** Test splits are evaluated once per frozen configuration. If a result disappoints, report it; do not change settings and re-run on test. Record any re-run in `DECISIONS.md` with the reason.
6. **Never modify raw data.** Raw Parquet under `data/` is read-only for everything except the collector and the compactor (which only rewrites into new files and verifies row counts).
7. **Respect phase boundaries in the live period.** Once Phase 7 (pre-registration) is committed, the model file, normalization statistics, thresholds and fill rules are frozen. Code changes during the live period are limited to bug fixes in logging and reporting that do not change any trading decision; each such change goes in `DECISIONS.md`.
8. If a required external resource is unreachable (FI-2010 URL, Binance), stop and report it in `STATUS.md` with the exact error. Do not substitute another data source without the owner's approval.

## 5. Repository layout (final state)

```
deeplob-reality-check/
  PLAN.md  STATUS.md  DECISIONS.md  README.md  DEPLOY.md  LICENSE (MIT)
  pyproject.toml  Makefile  .gitignore  .github/workflows/ci.yml
  configs/
    default.yaml  fi2010.yaml  crypto_dataset.yaml  crypto_deeplob.yaml  baselines.yaml
    backtest.yaml  live.yaml
  collector/                  # Phase 1 (already exists; standalone, minimal deps)
    collector.py  test_collector.py  requirements.txt  lob-collector.service
  src/lobrc/
    __init__.py  config.py  runs.py  cli.py  logging_setup.py  seed.py
    data/        book.py  trades.py  quality.py  compact.py  health.py  fi2010.py
    features/    book_features.py  normalize.py  windows.py  handcrafted.py
    labels.py
    datasets/    build_crypto.py  splits.py
    models/      deeplob.py  baselines.py  registry.py
    train.py  evaluate.py
    backtest/    fills.py  simulator.py  waterfall.py  grid.py
    stats.py
    live/        trader.py  ringbuffer.py  paper.py  replay.py
    report/      figures.py  site.py  weekly.py  writeup.py
  tests/         synth.py  fixtures/  test_*.py
  ops/           lob-live.service  lob-report.service  lob-report.timer  lob-health.service  lob-health.timer
  prereg/        PREREGISTRATION.md  manifest.json   (Phase 7)
  results/       fi2010/  crypto/  waterfall/  live/
  plan/          P0..P10 phase files
  site/          generated dashboard (published to gh-pages, git-ignored on main)
```

## 6. Phases and schedule

The owner works about 5 hours a day, 6 days a week. The collector must run from Day 1 because data cannot be recorded retroactively. Phase 5 needs at least 10 complete UTC days of crypto data.

| Phase | File | Title | Sprint days | Needs |
| --- | --- | --- | --- | --- |
| P0 | plan/P0-scaffold.md | Repo scaffold, config, CI | 1 | nothing |
| P1 | plan/P1-collection.md | Collector deployment, health, quality, compaction | 1-3 | P0 |
| P2 | plan/P2-book-data.md | Loading books and trades, segmentation, features, synthetic data | 3-6 | P1 |
| P3 | plan/P3-fi2010.md | DeepLOB model and FI-2010 replication | 5-10 | P0 (GPU recommended) |
| P4 | plan/P4-crypto-dataset.md | Labels, normalization, windows, splits for crypto | 8-12 | P2 |
| P5 | plan/P5-models.md | Baselines and DeepLOB on crypto | 12-15 | P3, P4, >= 10 days of data |
| P6 | plan/P6-backtest.md | Fill simulator, waterfall, statistics, figures | 14-18 | P5 |
| P7 | plan/P7-prereg.md | Pre-registration and freeze | 19 | P6 |
| P8 | plan/P8-live.md | Live paper trader and replay equivalence | 19-21 | P7 |
| P9 | plan/P9-reporting.md | Dashboard, weekly reports, final write-up | 21 and through live period | P8 |
| P11 | plan/P11-two-sites.md | Two-location latency experiment (London vs Tokyo), pre-registered | 18-21, then the live period | P8; must be running before P7 freeze |
| P10 | plan/P10-cpp.md | Optional: C++ feature engine and latency benchmark | curriculum Week 10 | P8 |

## 6b. Costs (checked 24 Nov 2026; expected cash cost $0)

| Item | Provider | Cost | Notes |
| --- | --- | --- | --- |
| Site A server (collector, live trader, reports) | Oracle Always Free, home region London, Arm A1 1 OCPU / 6 GB | free | Always Free A1 is 2 OCPU / 12 GB in total since June 2026; idle instances can be reclaimed (see DEPLOY.md). Upgrading to Pay As You Go keeps Always Free resources free. |
| Site B server (Tokyo) | AWS EC2 t4g.medium, Free plan credits | about $37/month, about $90 in total, covered by $100-200 new-account credits | Free plan cannot bill; see plan/P11. Fallback: Google Cloud $300 / 90-day trial. |
| GPU training | Kaggle Notebooks (about 30 GPU hours per week, floating quota), Google Colab free tier as backup | free | Plan GPU work across weeks; the FI-2010 matrix alone is many GPU hours. |
| Data | FI-2010 (CC BY 4.0), Binance public market-data streams | free | No exchange account or API key needed. |
| Code, CI, dashboard | GitHub public repository, Actions, Pages | free for public repositories | |
| Health pings | healthchecks.io | optional | Skip if its free plan does not suit; `lobrc health` works without it. |

All three cloud providers ask for a payment card at sign-up for identity checks. Set a billing alert on every account. Never leave stopped AWS volumes or unattached Elastic IPs behind after the project; they bill.

## 7. Definition of done for the whole project

- `pytest -q` passes; `ruff check .` is clean; CI is green.
- `results/fi2010/summary.md` shows the replication table vs published numbers.
- `results/waterfall/` contains the headline waterfall PNG, the full grid CSV and the edge-vs-latency figure.
- `prereg/` is committed and git-tagged `prereg-v1` before the first live trade, and the live service refuses to start if the model hash differs from `prereg/manifest.json`.
- The dashboard is public and updates daily; at least 4 weekly reports exist.
- `results/writeup/report.md` (and PDF) follows the template in plan/P9.
- `results/twosites/summary.md` reports the pre-registered H5 and H6 with confidence intervals.
- `README.md` leads with one figure and one sentence stating the finding, then how to reproduce everything with `make` targets.
