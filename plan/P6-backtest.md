# P6: Fill simulator, cost-and-latency waterfall, statistics

**Goal:** turn predictions into simulated trades with realistic latency, spread, depth and fees, decompose the edge into a waterfall, and attach honest uncertainty. The same fill code is used by the live trader in P8.

## 1. Trading rule (fixed; identical in backtest and live)
- One position at a time, long or short, fixed notional `Q` USD (default 1,000). Short selling is simulated (the result is the same as a long for P&L purposes in this paper study).
- At each anchor t (in time order) when flat: `pred = argmax(p)`, `conf = max(p)`. Trade only if `pred != 1` and `conf >= tau`. Direction `d = +1` for up, `-1` for down.
- Hold for `hold_ns = k * 100 ms` (the label horizon), then close. No stop-loss, no overlapping positions. Signals that arrive while a position is open are ignored.
- Both entry and exit are **taker** (market) orders.

## 2. Timing and fills: `src/lobrc/backtest/fills.py`
Definitions for one trade decided at anchor t:
- `decide_ns = recv_ns[t] + infer_ns` (model inference time; backtest uses the measured median from P8 benchmarks, default 5 ms until measured).
- **Latency L** is the total round trip: the order reaches the exchange about L/2 after we send it, and the book we see is about L/2 old. The order therefore executes against the book we receive about L after sending. Rule: **entry index `e` = first index j with `recv_ns[j] >= decide_ns + L` in the same segment** (if `infer_ns = 0` and `L = 0`, `e = t`).
- Exit decision at `exit_decide_ns = recv_ns[e] + hold_ns`; **exit index `x` = first index j with `recv_ns[j] >= exit_decide_ns + L`** in the same segment.
- If `e` or `x` does not exist inside the segment, the trade is **dropped** and counted in `n_dropped_segment_end`.
- **Fill prices:** quantity `q = Q / mid[e]` base units. Long entry walks the asks at index e (`walk_book` from P2); long exit walks the bids at index x with the same q. Short is the mirror (entry walks bids, exit walks asks). If depth runs out, the fill uses the last level price for the remainder and the trade is flagged `depth_exhausted`.
- Implement `find_index_at_or_after(recv_ns, segment_end_idx, start_idx, target_ns)` with `np.searchsorted` restricted to the segment.

## 3. Per-trade decomposition: `src/lobrc/backtest/simulator.py`
For each executed trade (all in bps, signed by direction d so positive is good):
1. `ideal_bps = d * (mid[t_h] - mid[t]) / mid[t] * 1e4`, where `t_h` = first index with `recv_ns >= recv_ns[t] + hold_ns` (no latency, mid-to-mid, the "paper" view). Because `L >= 0`, `t_h <= x` always, so `t_h` exists whenever the trade was not dropped.
2. `latency_bps = d * (mid[x] - mid[e]) / mid[e] * 1e4` (mid-to-mid with real timing).
3. `spread_bps_trade = d * (exit_px - entry_px) / entry_px * 1e4` (after crossing the spread and walking the book).
4. `net_bps = spread_bps_trade - 2 * fee_bps` (fee charged on notional on both sides).

Waterfall components per trade: `gross = ideal_bps`; `latency_cost = latency_bps - ideal_bps`; `spread_cost = spread_bps_trade - latency_bps`; `fee_cost = -2 * fee_bps`. They sum to `net_bps` exactly (assert to 1e-9).

`simulate(pred_df, split_arrays, k, L_ms, fee_bps, tau, Q, infer_ms) -> (trades_df, summary)`.
`trades_df` columns: `t, e, x, d, conf, recv_ns_t, recv_ns_e, recv_ns_x, entry_px, exit_px, ideal_bps, latency_bps, spread_bps_trade, net_bps, depth_exhausted`.
`summary`: `n_trades, n_dropped_segment_end, mean/median of each component, hit_rate_net (net_bps > 0), total_net_bps, trades_per_day, breakeven_fee_bps = mean(spread_bps_trade) / 2`.

Reference strategies run through the same simulator:
- **Oracle:** direction = sign of the true point return `r_bps` at the trade's horizon (trades whenever `r != 0`). Upper bound on gross.
- **Random:** same number of trades as the model at the same timestamps, random direction (seed 1234). Its net should be close to minus spread minus fees; a big deviation means a bug.

## 4. Threshold tau
Two settings: `tau = 0` (plain argmax) and `tau*` chosen on the **validation** split: the value in `{0.40, 0.45, ..., 0.90}` that maximises mean `net_bps` per trade at the headline scenario (`L = 100 ms`, `fee = 2 bps`), subject to at least 200 validation trades. Freeze `tau*` before running the test split; write it into `results/waterfall/tau.json`.

## 5. Grid: `src/lobrc/backtest/grid.py`, CLI `lobrc backtest --config configs/backtest.yaml`
```yaml
inherits: default.yaml
backtest:
  run_dirs: {}                # filled automatically from results/crypto/selection.json
  splits: [val, test]
  horizons: [10, 20, 50, 100]
  latency_ms: [0, 10, 50, 100, 250, 500]
  fee_bps: [0, 2, 7.5, 10]    # 0 = ideal; 2 = Binance.US taker; 7.5 = Binance with BNB; 10 = Binance regular
  tau: [argmax, tuned]
  notional_usd: 1000
  infer_ms: 5
  headline: {latency_ms: 100, fee_bps: 2}
```
Run every model (majority excluded), oracle and random over the full grid. Save `results/waterfall/grid_<split>.csv` with one row per (model, horizon, tau, L, fee) and all summary fields plus confidence intervals.

## 6. Statistics: `src/lobrc/stats.py`
- `block_bootstrap_mean_ci(x, block_len=None, n_boot=2000, alpha=0.05, seed=1234)`: moving-block bootstrap of the mean; default `block_len = max(1, round(len(x) ** (1/3)))`; percentile interval. Use on per-trade `net_bps` (trades are serially correlated).
- `wilson_ci(successes, n, alpha=0.05)` for hit rates.
- `daily_series(trades_df)`: per-UTC-day sums and counts.
- Tests: bootstrap CI of a constant series has zero width; for iid normal data with n=10,000 the 95% CI covers the true mean in at least 90 of 100 seeded repetitions; Wilson CI of 50/100 is about (0.404, 0.596).

## 7. Figures: `src/lobrc/report/figures.py`
Use matplotlib, 150 dpi PNG, consistent style, units in every axis title.
1. `waterfall_<model>_k<k>.png` for the headline scenario: bars for gross, latency cost, spread cost, fee cost, net (mean bps per trade), each with its 95% CI whisker, net bar coloured by sign.
2. `edge_vs_latency.png`: mean `latency_bps` (before spread and fees) against L for each model at the headline horizon, with CI bands; oracle as a dashed line.
3. `breakeven_fee.png`: breakeven fee (bps per side) by horizon for each model, with horizontal lines at 0, 2, 7.5 and 10 bps.
4. `cum_net_test.png`: cumulative `net_bps` over test trades for the headline scenario, model vs random.

## 8. Tests (`tests/test_fills.py`, `tests/test_simulator.py`)
1. **Hand-built book, zero latency:** mids `[100, 100, 101, 101, 101, 101, 101, 101]` with spread 0.02 (ask = mid + 0.01, bid = mid - 0.01) and large sizes, snapshots every 100 ms in one segment, up prediction at t=0 with k=2 (`hold_ns` = 200 ms), `L=0`, `infer_ms=0`, fee 0, small Q (fills at level 0). Then e=0, x=2, `ideal_bps = 100`, entry 100.01, exit 100.99, `spread_bps_trade = (100.99 - 100.01) / 100.01 * 1e4`, and the components sum to net.
2. **Latency moves the fill:** same book with `L=150 ms`: e=2 (first snapshot received at or after 150 ms is at 200 ms); exit decision at 200 + 200 = 400 ms; x=6 (first snapshot at or after 550 ms is at 600 ms).
3. **Segment end:** a trade whose exit falls past the segment end is dropped and counted.
4. **One position at a time:** two consecutive up signals produce one trade.
5. **Depth walk:** Q larger than level-0 size uses level 1 and the VWAP matches `walk_book`.
6. **Oracle on synthetic data has positive mean `ideal_bps`; random has mean `net_bps` within 3 standard errors of `-(spread + 2*fee)`.**
7. **Fees:** net with fee 10 equals net with fee 0 minus 20 bps, trade by trade.

## Acceptance criteria
- Tests pass; the full grid runs on validation and test; `tau.json` committed before test grid results.
- `results/waterfall/summary.md`: the headline waterfall for the selected model, the edge-vs-latency figure, the breakeven-fee figure, and a 5-sentence plain-English conclusion that states the numbers with confidence intervals (for example whether any model's net edge is positive at any realistic fee).
