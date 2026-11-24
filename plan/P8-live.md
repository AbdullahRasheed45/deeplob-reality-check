# P8: Live paper trader

**Goal:** run the frozen model on the live stream for 4 to 8 weeks with the exact backtest rules, log everything, and prove offline that the live code and the backtest make identical decisions.

The trader never sends orders anywhere. "Fills" are simulated from the book it receives.

## 0. Before the P7 freeze: benchmark inference on the server
`lobrc live bench --model <run_dir>/best.pt --n 2000` on the server (same instance type as live): random inputs of shape `[1,1,100,40]`, `torch.set_num_threads(1)`, `torch.inference_mode()`, 100 warm-up calls. Report p50, p90 and p99 latency in ms. Requirement: p99 below 50 ms. The measured p50 becomes `infer_ms` in the manifest and in the backtest. If p99 is above 50 ms, try `torch.set_num_threads(2)`; if still too slow, report it in `STATUS.md` and stop (do not silently skip snapshots).

Use the Arm A1 instance (1 OCPU, 6 GB); the 1 GB AMD Micro instance is too small for torch.

## 1. Process layout: `src/lobrc/live/trader.py`, CLI `lobrc live run --config configs/live.yaml`
A separate process from the collector, with its own websocket connection to `<symbol>@depth20@100ms` and `<symbol>@trade` for the single live symbol. It does not write raw book data (the collector does), only what it needs to audit its own decisions.

`configs/live.yaml`:
```yaml
inherits: default.yaml
live:
  manifest: prereg/manifest.json
  site: A                      # "A" (London) or "B" (Tokyo); see plan/P11. Written into every log row.
  out_dir: data/live
  url: null                    # null = Binance combined stream for the manifest symbol
  ping_interval_s: 10
  rtt_window: 10               # median of the last 10 ping round trips
  rtt_default_ms: 100          # used until the first measurement
  max_conn_hours: 23
  stale_secs: 30
```

Startup sequence (abort with a clear log line on any failure):
1. Load and verify `prereg/manifest.json` (all SHA-256 hashes match the files). Log the manifest hash as the first line.
2. Load the DeepLOB model (eval mode, CPU, 1 thread) and the LightGBM control model.
3. Load normalisation stats (`stationary`: frozen file; `paper`: compute from the previous 5 recorded days in the collector's data directory, and recompute at each UTC midnight; if fewer days are available, use what exists and log it).
4. Start flat. If the previous run left an open position (`state.json`), log it as `aborted` in the trades log.

## 2. Components
- `ringbuffer.py`: `SnapshotRing(T=100, levels=10)` holding the last T snapshots as raw float64 arrays (same columns as `BookData`) plus `recv_ns` and `segment` counters. A new segment starts on the same rules as P2 (gap above 1 s, `last_update_id` decreasing, invalid book). The window is "ready" when it holds T consecutive snapshots of the current segment.
- `TradeRing`: the last 10 s of trades for trade-flow features.
- `paper.py`: `PaperBook` state machine with states `FLAT`, `PENDING_ENTRY`, `OPEN`. It uses **the same functions** as `backtest/fills.py` and `book_features.walk_book` (import them; do not reimplement). At decision time it stores `recv_ns_t` and `mid_t`; it records `mid_th` at the first snapshot with `recv_ns >= recv_ns_t + hold_ns` (needed for `ideal_bps`, because the ring buffer may no longer hold snapshot t by then).
- Control-model features: compute the P4 handcrafted features on the ring buffers using the same functions as the dataset builder (vectorised functions applied to the last 100 snapshots and the trade ring), so offline and live features are identical.

## 3. Per-snapshot loop (in this order, for every depth message)
1. Stamp `recv_ns = time.time_ns()` immediately on receipt; parse with the collector's `parse_book`.
2. Push into the ring (handles segmentation). Append `(recv_ns, last_update_id, bid_px_0, ask_px_0, mid, segment)` to the snapshot audit log.
3. Advance `PaperBook` with this snapshot:
   - `PENDING_ENTRY` and `recv_ns >= decide_ns + L` gives the entry fill at this snapshot: walk the book, go `OPEN`, set `exit_decide_ns = recv_ns + hold_ns`.
   - `OPEN` and `recv_ns >= exit_decide_ns + L` gives the exit fill at this snapshot (the exit order is treated as sent at exactly `exit_decide_ns`, as in the backtest); write the trade with all P6 components; go `FLAT`.
   - A segment break while not `FLAT` aborts the trade: log `aborted_segment_break`, go `FLAT` (mirrors the backtest's "dropped" rule).
   - `L` is fixed per trade at decision time (the RTT estimate then), and the same `L` is used for entry and exit.
4. If the window is ready: normalise, run DeepLOB (`predict_proba`) and the control model; record `infer_ns` measured around the model call. Write the decision log row.
5. If `FLAT` and the DeepLOB prediction passes the trading rule (P6 section 1, frozen `tau`): set `decide_ns = recv_ns + infer_ns`, `L = current RTT estimate`, state `PENDING_ENTRY`. The control model's decisions are simulated by an independent second `PaperBook` instance with identical rules.

Timing must match P6 exactly: `e` = first snapshot with `recv_ns >= decide_ns + L`; `exit_decide_ns = recv_ns[e] + hold_ns`; `x` = first snapshot with `recv_ns >= exit_decide_ns + L`. The equivalence test in section 5 enforces this.

**Latency L in live:** the median of the last `rtt_window` websocket ping round-trip times (`websockets` connection attribute `latency`, in seconds), converted to ns. Log the L used on each trade. Ping every `ping_interval_s` (this is well within Binance's 5 messages per second limit).

Connection handling: copy the collector's reconnect logic (backoff, stale detection, planned reconnect before 24 h, `serverShutdown`). A reconnect always breaks the segment.

## 4. Logs (`data/live/`, Parquet written hourly through `.tmp` and rename; plus `state.json` updated every 10 s)
- `snapshots/<date>/hour-HH.parquet`: snapshot audit log from step 2.
- `decisions/<date>/hour-HH.parquet`: `recv_ns, last_update_id, model ("deeplob"/"control"), p_down, p_flat, p_up, pred, conf, infer_us, rtt_ms, state_before, action` (`none`, `enter_long`, `enter_short`).
- `trades/<date>/hour-HH.parquet`: one row per closed or aborted trade with the same columns as the backtest `trades_df` plus `model`, `L_ms`, `status` (`closed`, `aborted_segment_break`, `aborted_restart`).
- `status.json`: last message time, current state, counts today, current RTT, model hash. Read by `lobrc health` (extend the health check: live status must be updated within 60 s).

## 5. Replay mode and the equivalence test (most important test in the project)
`src/lobrc/live/replay.py`: `replay(book: BookData, trades: TradeData, manifest, fixed_L_ms, fixed_infer_ms) -> trades_df` feeds historical snapshots through the **same** loop with an injected clock (no websocket, no `time.time_ns()`), with L and inference time fixed.

`tests/test_live_equivalence.py`: on a synthetic day with `signal_strength=0.3`, a small trained logistic model wrapped in the DeepLOB interface (or a tiny randomly initialised DeepLOB with a fixed seed), and fixed L and inference time:
- `replay(...)` and `backtest.simulate(...)` on the same data produce **identical** trades (same t, e, x, direction, entry and exit prices, net to 1e-9).
- With a gap injected mid-trade, both drop or abort the same trade.

Also `lobrc live replay --date YYYY-MM-DD` on a real recorded day, compared with the backtest; any difference is a bug to fix before going live.

## 6. Deployment
`ops/lob-live.service` (systemd, `Restart=always`, `RestartSec=5`, `KillSignal=SIGTERM`, `TimeoutStopSec=30`, `After=lob-collector.service`). On SIGTERM: flush logs, write `state.json`, exit; an open position is recorded as `aborted_restart` on the next start.

## Acceptance criteria
- Equivalence tests pass, and the real-day replay matches the backtest exactly.
- On the server, 24 hours of live operation with: no crash loops, `status.json` fresh, p99 inference under 50 ms in the decision log, and RTT logged on every trade.
- Then the live period officially starts (date written into `STATUS.md`).
