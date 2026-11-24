# P2: Loading order books and trades, segmentation, features, synthetic data

**Goal:** turn raw Parquet into clean contiguous arrays with explicit segment boundaries, plus the feature functions every later phase uses.

## 1. `src/lobrc/data/book.py`

```python
@dataclass(frozen=True)
class BookData:
    symbol: str
    recv_ns: np.ndarray        # int64 [N], strictly non-decreasing
    last_update_id: np.ndarray # int64 [N]
    bid_px: np.ndarray         # float64 [N, 10]
    bid_sz: np.ndarray         # float64 [N, 10]
    ask_px: np.ndarray         # float64 [N, 10]
    ask_sz: np.ndarray         # float64 [N, 10]
    segment_id: np.ndarray     # int32 [N], 0..S-1, non-decreasing

def load_book(data_dir, symbol: str, start_date: str, end_date: str, gap_secs: float = 1.0) -> BookData
```
Algorithm:
1. Collect files `data_dir/book/<SYMBOL>/<date>/{part,hour}-*.parquet` for dates in `[start_date, end_date]` inclusive. Read with `pyarrow.parquet.read_table`, concatenate, convert to numpy.
2. Sort by `recv_ns` with `np.argsort(kind="stable")`.
3. **Drop invalid rows** (count each reason and log it): any NaN in levels 0-9 on either side; crossed or locked book (`bid_px_0 >= ask_px_0`); non-positive prices or negative sizes; bid levels not strictly decreasing or ask levels not strictly increasing.
4. **Segment boundaries.** Row i (i > 0) starts a new segment if any of: `recv_ns[i] - recv_ns[i-1] > gap_secs * 1e9`; `last_update_id[i] < last_update_id[i-1]`; or rows were dropped between i-1 and i (an invalid row breaks continuity). `segment_id = cumsum(new_segment_flags)`.
5. Return `BookData`. Arrays must be C-contiguous.

Also provide `book_from_arrays(...)` for tests, and `BookData.slice(i0, i1)`.

## 2. `src/lobrc/data/trades.py`

```python
@dataclass(frozen=True)
class TradeData:
    symbol: str
    recv_ns: np.ndarray   # int64 [M] sorted
    price: np.ndarray     # float64
    qty: np.ndarray       # float64
    taker_buy: np.ndarray # bool: True when the aggressor bought (= not buyer_is_maker)

def load_trades(data_dir, symbol, start_date, end_date) -> TradeData
def flow_on_book_clock(book: BookData, trades: TradeData, windows_ms=(1000, 5000)) -> dict[str, np.ndarray]
```
`flow_on_book_clock` returns, for each window w and each book index i, using only trades with `recv_ns` in `(recv_ns[i] - w, recv_ns[i]]` (strictly no future trades):
- `buy_vol_{w}`, `sell_vol_{w}` (sum of `qty` by `taker_buy`), `n_trades_{w}`,
- `tfi_{w} = (buy - sell) / (buy + sell)`, defined as 0 when there were no trades.
Implement with cumulative sums and `np.searchsorted` (O(N log M)); no Python loop over rows.

Note in the module docstring: `buyer_is_maker = True` means the seller was the aggressor (a taker sell).

## 3. `src/lobrc/features/book_features.py`
All functions are vectorised over N rows and return float64 arrays.
- `mid(book) = (ask_px[:,0] + bid_px[:,0]) / 2`
- `spread_bps(book) = (ask_px[:,0] - bid_px[:,0]) / mid * 1e4`
- `microprice(book) = (ask_px[:,0]*bid_sz[:,0] + bid_px[:,0]*ask_sz[:,0]) / (bid_sz[:,0] + ask_sz[:,0])`
- `micro_offset_bps = (microprice - mid) / mid * 1e4`
- `imbalance(book, n_levels) = (sum bid_sz[:, :n] - sum ask_sz[:, :n]) / (sum bid_sz[:, :n] + sum ask_sz[:, :n])`, in [-1, 1]
- `fi_order(book) -> float32 [N, 40]`: columns `[ask_px_i, ask_sz_i, bid_px_i, bid_sz_i]` for i = 0..9 (PLAN.md section 3).
- `walk_book(px_levels, sz_levels, qty) -> (vwap, filled_qty, levels_used)`: fill `qty` against one side (pass asks for a buy, bids for a sell) level by level from level 0. If depth is exhausted, the remainder is filled at the last level's price and `filled_qty` still equals `qty`; return `exhausted=True` as a fourth value. Vectorised version `walk_book_many` over rows with per-row qty.

## 4. `tests/synth.py` (used by tests in every phase)
`make_synthetic_book(n=20_000, seed=0, tick=0.01, start_ns=1_700_000_000_000_000_000, signal_strength=0.0, gaps=(), crossed_rows=()) -> (BookData, info)`:
1. Snapshots every 100 ms (`recv_ns = start_ns + i * 100_000_000`), plus extra `gap` seconds inserted at each index listed in `gaps` (list of `(index, secs)`).
2. Latent imbalance `z_t` follows AR(1): `z_t = 0.95 z_{t-1} + 0.3 * eps`, eps standard normal.
3. At each step, with probability 0.3 the mid moves by exactly one tick; the move is up with probability `0.5 + signal_strength * tanh(z_{t-1})`, else down. Spread is always 1 tick, so `bid_px_0 = mid - tick/2`, `ask_px_0 = mid + tick/2`. Start mid at 100.005, so bids and asks stay on the 0.01 grid. Round prices to 8 decimals to avoid float drift. Levels i: `bid_px_i = bid_px_0 - i*tick`, `ask_px_i = ask_px_0 + i*tick`.
4. Sizes: `bid_sz_i = lognormal(0, 0.5) * (1 + 0.5*max(z,0))` for i=0, `ask_sz_0 = lognormal(0,0.5) * (1 + 0.5*max(-z,0))`, deeper levels `lognormal(0.5, 0.5)`. So level-0 imbalance carries the signal when `signal_strength > 0`.
5. `last_update_id = 1000 + i`. For indices in `crossed_rows`, set `bid_px_0 = ask_px_0 + tick`.
6. `info` returns `z`, the true mid path and parameters.
Also `make_synthetic_trades(book, seed, rate_per_sec=5)` with Poisson arrivals, price = touch price on the aggressor side, `taker_buy` more likely when `z > 0`.
Also `write_synthetic_day(data_dir, symbol, date, ...)` that writes the arrays in exactly the collector's Parquet layout (several part files), for loader, quality and compaction tests.

## 5. Tests (`tests/test_book.py`, `tests/test_features.py`, `tests/test_trades.py`)
1. `test_load_roundtrip`: write a synthetic day with `write_synthetic_day`, load it, arrays equal the generated ones (order and values).
2. `test_segments_on_gap`: gaps at indices 5000 (3 s) and 12000 (0.5 s) give exactly 2 segments (0.5 s is below `gap_secs`).
3. `test_crossed_row_dropped_and_splits_segment`: one crossed row at 7000 is dropped and starts a new segment.
4. `test_fi_order_columns`: for a hand-made 1-row book, `fi_order[0,:8] == [a0, as0, b0, bs0, a1, as1, b1, bs1]`.
5. `test_microprice_hand_example`: bid 100 x 3, ask 101 x 1 gives microprice 100.75 and imbalance(1) = 0.5.
6. `test_walk_book`: asks `[100, 101, 102]` with sizes `[1, 2, 5]`, qty 2.5 gives vwap `(1*100 + 1.5*101)/2.5 = 100.6`, levels_used 2, exhausted False; qty 10 gives exhausted True and the remainder priced at 102.
7. `test_flow_no_lookahead`: a trade exactly 1 ms after `recv_ns[i]` must not appear in row i's features.

## Acceptance criteria
- All tests pass. `load_book` on one real day completes in under 30 s on a laptop and reports drop counts per reason.
- A short notebook or script `scripts/explore_day.py` prints: rows, segments, median spread in bps and ticks, fraction of snapshots where the mid changed versus the previous snapshot. Paste these numbers into `STATUS.md`; they inform P4 thresholds.
