# P4: Crypto dataset: labels, normalisation, windows and splits

**Goal:** build model-ready datasets from the recorded Binance data, with no look-ahead, explicit splits and everything the backtest needs stored alongside.

Prerequisite: P2 done. To build the full dataset, at least 10 complete UTC days must exist. The code is developed and tested on synthetic data first.

## 1. Labels: `src/lobrc/labels.py`
All label functions work **within one segment** (never across a gap) on the mid-price array `m` of that segment, index `t` is the last snapshot of the input window. `k` is the horizon in snapshots.

- **Smoothed label (DeepLOB, LSE definition; used for training):**
  - `m_minus(t) = mean(m[t-k+1 .. t])` (past k mids including t)
  - `m_plus(t) = mean(m[t+1 .. t+k])` (next k mids)
  - `l(t) = (m_plus - m_minus) / m_minus`
  - Defined only when `t-k+1 >= segment_start` and `t+k <= segment_end`; otherwise NaN.
- **Point return (tradable; used for evaluation and backtest):** `r_bps(t) = (m[t+k] - m[t]) / m[t] * 1e4`.
- **Classification with threshold alpha:** class 2 (up) if `l > alpha`, class 0 (down) if `l < -alpha`, else class 1 (stationary).
- **Choosing alpha:** computed on the **training split only**, separately per horizon: `alpha = quantile(|l_train|, 1/3)` (so about one third of training samples are stationary). If more than one third of `|l_train|` values are exactly 0, alpha becomes 0 and "stationary" means no change; record class proportions either way. Store alpha in the dataset metadata; reuse unchanged for validation, test and live.
- Implement with cumulative sums per segment (O(N)), no Python loop over t.

Horizons: `k in {10, 20, 50, 100}` snapshots (1, 2, 5 and 10 seconds at 100 ms).

Tests (`tests/test_labels.py`):
1. Hand example: `m = [1,1,1,1,2,2,2,2]`, k=2, t=3: `m_minus = mean(m[2..3]) = 1`, `m_plus = mean(m[4..5]) = 2`, `l = 1.0`; at t=0, l is NaN (not enough history).
2. Labels never use data across a segment boundary: build two segments; for t within k of the boundary, label is NaN.
3. `alpha` on `|l| = [0,0,0,0,1,2]` is 0 and classes come out as expected.
4. Point return at the end of a segment is NaN.

## 2. Normalisation: `src/lobrc/features/normalize.py`
Input: FI-order raw features `[N, 40]` (float64). Two variants; the dataset stores both so P5 can compare them on validation.

**Variant `paper` (DeepLOB style: z-score with statistics from previous days):**
- Price columns (20 of them: indices 0, 2 of each group of 4) share one mean and one standard deviation; size columns (indices 1, 3) share another pair. Pooling keeps the relative ordering across levels.
- For each UTC day D, statistics come from all rows of the **previous up to 5 recorded days** (D-5 .. D-1, using whichever exist). The first recorded day has no previous days: it is used only to provide statistics and gets no samples.
- `z = (x - mean) / std`. Store the per-day statistics in metadata.

**Variant `stationary` (our robustness variant):**
- Price columns: `(p - mid) / mid * 1e4` (distance from mid in bps, so the features do not drift with the price level).
- Size columns: `log1p(size)`.
- Then per-column z-score with mean and std computed on the **training split only**; the same stats are applied to validation, test and live.

Both return float32 arrays. Guard against std = 0 by using `max(std, 1e-8)` and log a warning.

Tests: paper variant on a 3-day synthetic set: day 2 uses day 1 stats only; day 3 uses days 1-2; changing day 3's data does not change day 3's stats. Stationary variant: a constant price offset of +1000 to every price leaves the price features unchanged (up to float tolerance).

## 3. Splits: `src/lobrc/datasets/splits.py`
- Collect the list of complete UTC days (coverage >= 0.9 from the P1 quality report; others are excluded and listed in metadata).
- Exclude the first day if using the `paper` normalisation (warm-up).
- Chronological split by day: `n_test = max(2, round(0.2 n))`, `n_val = max(2, round(0.2 n))`, rest train. Train days come first, then validation, then test. With fewer than 10 usable days, raise an error.
- Segments never cross a split boundary: start a new segment at the first row of each split's first day.
- **Purging:** an anchor is valid only if its whole input window `[t-T+1, t]` and its label horizon `[t-k+1, t+k]` lie within one segment of one split. With segment boundaries at split edges, this is automatic.

## 4. Handcrafted features: `src/lobrc/features/handcrafted.py`
For baselines (P5). At each anchor t, using only data up to and including t:
`spread_bps`, `imb_1`, `imb_3`, `imb_5`, `imb_10` (imbalance over the first n levels), `micro_offset_bps`, mid returns over the last 1, 5, 10, 50 and 100 snapshots (bps; NaN if not enough history within the segment, then the anchor is invalid), `rv_50` (standard deviation of 1-step mid returns in bps over the last 50 snapshots), `depth_ratio_5 = log(sum bid_sz[:5] / sum ask_sz[:5])`, and for crypto only `tfi_1000`, `tfi_5000`, `n_trades_5000` (from P2 trade flow). FI-2010 has no trades, so its baselines use the book features only.

## 5. Builder: `src/lobrc/datasets/build_crypto.py`, CLI `lobrc dataset build --config configs/crypto_dataset.yaml`
`configs/crypto_dataset.yaml`:
```yaml
inherits: default.yaml
dataset:
  name: btc_v1
  symbol: BTCUSDT
  start_date: null       # null = first usable day
  end_date: null         # null = last complete day before today
  T: 100
  horizons: [10, 20, 50, 100]
  norm_variants: [paper, stationary]
  train_stride: 5        # use every 5th anchor for training (reduces size and correlation)
  eval_stride: 1         # validation and test keep every anchor
  min_coverage: 0.9
```
Output folder `datasets/<name>/`:
- `meta.json`: config, days per split, excluded days with reasons, alpha per horizon, class proportions per split and horizon, normalisation stats, row counts, code git hash.
- For each split (`train`, `val`, `test`) a file `<split>.npz` containing:
  - `recv_ns` int64 [N], `segment_id` int32 [N], `day_idx` int16 [N]
  - `x_paper` float32 [N, 40], `x_stationary` float32 [N, 40]
  - `mid` float64 [N], `bid_px`, `ask_px` float64 [N,10], `bid_sz`, `ask_sz` float32 [N,10] (needed by the backtest to walk the book)
  - `anchors` int64 [M] (valid for **all** horizons simultaneously; simpler and lets every model be compared on the same samples)
  - `y_k{k}` int8 [M] (class), `l_k{k}` float32 [M] (smoothed label value), `r_k{k}_bps` float32 [M] (point return), for each horizon
  - `hand` float32 [M, F] and `hand_names` (handcrafted features at each anchor)
- Training anchors are subsampled with `train_stride`; validation and test use `eval_stride`.
- Print and log the sizes. Expect about 864,000 snapshots per symbol-day; check that file sizes fit in memory on the training machine (roughly 0.4 GB per day of raw arrays in this layout). If they do not, write one `npz` per day per split instead and record the choice in `DECISIONS.md`.

Also build `eth_v1` (ETHUSDT) with the same days, used for the transfer test in P5.

## 6. Dataset class for crypto
Reuse `WindowDataset` from P3 with `x = x_<variant>` and `anchors`, `y = y_k{k}`.

## Tests (`tests/test_build_crypto.py`)
Build a dataset from 12 synthetic days (written with `write_synthetic_day`, `signal_strength=0.2`, gaps injected): assert split days are chronological and disjoint; no anchor window crosses a segment boundary (check `segment_id[t-T+1] == segment_id[t+100]` for all anchors); alpha computed from train only (changing test data leaves alpha unchanged); handcrafted features at t equal recomputation using data only up to t (look-ahead test: perturb all rows after t and confirm features at t are unchanged).

## Acceptance criteria
- `btc_v1` and `eth_v1` built from real data, `meta.json` reviewed: class proportions roughly a third each on train for every horizon (or documented if alpha = 0), and no split has fewer than 2 days.
- `results/crypto/dataset_summary.md` written: days per split, excluded days, alpha and class mix per horizon, median spread, fraction of snapshots where the mid changes.
