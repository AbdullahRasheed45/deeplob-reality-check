# P1: Data collection, health, quality and compaction

**Goal:** the collector records 24/7 on the server, and we can prove the data is continuous and correct.

The collector (`collector/collector.py`) already exists and is tested. It subscribes to `<symbol>@depth20@100ms` and `<symbol>@trade` on the Binance combined stream and writes:

- `data/book/<SYMBOL>/<YYYY-MM-DD>/part-<first_recv_ns>.parquet` with columns `recv_ns, symbol, last_update_id, bid_px_0..9, bid_sz_0..9, ask_px_0..9, ask_sz_0..9` (missing levels are NaN).
- `data/trades/<SYMBOL>/<YYYY-MM-DD>/part-<first_recv_ns>.parquet` with columns `recv_ns, symbol, trade_id, event_ms, trade_ms, price, qty, buyer_is_maker`.
- `data/events.jsonl`: one JSON object per line with `ts_ns`, `kind` and fields. Kinds: `start, connect, disconnect, gap, out_of_order, stale_connection, planned_reconnect, server_shutdown, bad_json, stopped`.

Keep the collector standalone (only `websockets` and `pyarrow`), so it can run on a tiny server without torch.

## Step 1: verify the live message format (owner runs this on the server)
`python collector.py --probe 5`. Paste the output into `tests/fixtures/binance_probe.txt`. Then add `collector/test_probe_fixture.py`: parse every line in the fixture with `json.loads`, pass depth messages to `parse_book` and trade messages to `parse_trade`, and assert no exception, `bid_px_0 < ask_px_0`, 10 non-NaN levels per side, and `last_update_id > 0`. If the real format differs (e.g. different key names), update `parse_book`/`parse_trade` and their tests, and record it in `DECISIONS.md`.

If the server cannot reach `stream.binance.com` (HTTP 451/403, or connection reset), first try `wss://data-stream.binance.vision/stream?streams=...` by passing `--url`. If that also fails, stop and report in `STATUS.md`.

## Step 2: deploy
Follow `DEPLOY.md` steps 1 to 9 exactly. The systemd unit is `collector/lob-collector.service`.

## Step 3: `src/lobrc/data/health.py` and CLI `lobrc health`
Function `check_health(data_dir, symbols, max_age_secs=300, now_ns=None) -> HealthResult` where `HealthResult` is a dataclass `(ok: bool, problems: list[str], newest_file_age_secs: dict[str, float], last_event: dict | None)`.
Rules, each failing rule appends a human-readable problem:
1. For each symbol, the newest `part-*.parquet` under `data/book/<SYMBOL>/` (any date folder) must have modification time within `max_age_secs` of now.
2. The last line of `events.jsonl` must not be `disconnect` older than 120 s (a recent disconnect is normal during reconnect).
3. Free disk space on the partition holding `data_dir` must be at least 10% (`shutil.disk_usage`).
CLI exits 0 if ok, 1 otherwise, printing one line per problem. If env var `HC_URL` is set, `lobrc health` sends an HTTP GET to `HC_URL` on success and to `HC_URL + "/fail"` on failure (healthchecks.io convention), with a 10 s timeout and errors ignored.

Ops: `ops/lob-health.service` (oneshot running `lobrc health --config configs/default.yaml`) and `ops/lob-health.timer` (`OnCalendar=*:0/10`, every 10 minutes, `Persistent=true`).

Tests (`tests/test_health.py`, tmp_path): fresh file gives ok; file with mtime 1 hour old gives not ok with a problem mentioning the symbol; last event `disconnect` 10 minutes old gives not ok.

## Step 4: `src/lobrc/data/quality.py` and CLI `lobrc quality --date YYYY-MM-DD` (default: all dates)
For each symbol and UTC date produce a row:

| Column | Definition |
| --- | --- |
| `rows` | number of book rows |
| `expected_rows` | seconds covered by the day (86,400, or less on the first/last recorded day: from first to last `recv_ns`) x 10 |
| `coverage` | `rows / expected_rows` |
| `n_gaps`, `gap_secs_total`, `max_gap_secs` | from consecutive `recv_ns` differences greater than `gap_secs` (1.0 s) |
| `crossed_rows` | rows with `bid_px_0 >= ask_px_0` (must be 0; any non-zero value is a bug to investigate) |
| `nan_level_rows` | rows with any NaN in levels 0-9 |
| `dup_update_id_frac` | fraction of rows whose `last_update_id` equals the previous row's |
| `spread_bps_p50`, `spread_bps_p99` | percentiles of spread in bps |
| `trades`, `trade_gaps` | trade count; number of gaps > 10 s between consecutive trades |
| `disconnects` | count of `disconnect` events that day from `events.jsonl` |

Writes `results/quality/quality_<symbol>.csv` (one row per date, appended/overwritten by date) and `results/quality/spread_<symbol>_<date>.png` (histogram of spread in bps, 100 bins, clipped at p99.5). Also writes `results/quality/gaps.csv` listing every gap `(symbol, start_ns, end_ns, secs)`.

Tests use `tests/synth.py` (defined in P2) to create a day with one injected 5 s gap and one crossed row; assert `n_gaps == 1`, `max_gap_secs` between 4.9 and 5.2, `crossed_rows == 1`.

## Step 5: `src/lobrc/data/compact.py` and CLI `lobrc compact --before YYYY-MM-DD`
For each symbol, kind (`book`, `trades`) and date strictly before `--before` (never today, which is still being written):
1. Read all `part-*.parquet` files of that date folder, concatenate, sort by `recv_ns` (stable).
2. Group rows by UTC hour; write `hour-HH.parquet` (zstd) through a `.tmp` file and `rename`.
3. Verify the total row count of new files equals the total of the parts, and that the min/max `recv_ns` match. Only then move the original parts into `data/_compacted_parts/<kind>/<SYMBOL>/<date>/` (never delete).
4. Idempotent: if `hour-*.parquet` already exist and no `part-*` remain, skip.
All readers (P2) must read both `part-*.parquet` and `hour-*.parquet`.

Tests: create 30 small part files spanning 2 hours; compact; assert 2 hour files, row count preserved, sorted, originals moved.

## Acceptance criteria
- Collector running under systemd on the server; `lobrc health` passes there.
- Probe fixture committed and its test passes.
- `lobrc quality` runs on the first 24 h of real data; `crossed_rows == 0`; every gap is explained in `STATUS.md` (reconnects, server shutdowns, maintenance).
- Compaction tested and run once on real data with row counts verified.
