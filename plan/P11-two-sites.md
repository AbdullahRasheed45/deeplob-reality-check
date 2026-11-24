# P11: Two-location latency experiment (London vs Tokyo)

**Goal:** measure, on real live data, how much of the model's edge is lost purely because of physical distance to the exchange. The same frozen model, code and rules run at the same time in two places; the only difference is location. Because both sites see the same signals at the same moments, we can compare them **signal by signal** (a paired design), which gives tight confidence intervals from a few weeks of data.

**Why it is new:** latency cost in published LOB papers is simulated with assumed numbers. Here it is measured live, with a pre-registered hypothesis, on identical decisions.

**Timing:** must be built and both sites running before the P7 freeze, because H5 (below) is pre-registered and both sites start the live period on the same day. Build it alongside P8 (sprint days 18-21).

## 1. Sites
| Site | Where | Server | Cost |
| --- | --- | --- | --- |
| A ("far") | London (Oracle home region, if the owner's home region is UK South; otherwise any Europe location; record it) | Oracle Always Free A1, 1 OCPU / 6 GB | free |
| B ("near") | Tokyo, AWS ap-northeast-1 | EC2 `t4g.medium` (2 vCPU Arm, 4 GB), Ubuntu 24.04 arm64, 20 GB gp3 disk, **credit specification "standard"** (so heavy CPU is throttled, never billed extra) | about $0.0432/h for the instance, roughly $37 per month including disk and public IPv4 (checked 24 Nov 2026); paid from new-account AWS Free Tier credits |

Oracle Always Free instances must be in the tenancy's home region, so site B cannot be a second free Oracle instance in Tokyo.

**Paying for site B with free credits (no cash cost):**
- Create a **new AWS account on the Free plan**. New customers get $100 in credits at sign-up and can earn up to $100 more through console activities (one is launching and terminating an EC2 instance). The Free plan never bills: the account closes when the credits run out or after 6 months. Accounts that have existed before are not eligible.
- Budget: site B runs from about sprint day 17 to the end of an 8-week live period, about 75 days, roughly $90 at the rate above. That fits in the credits. Set an AWS Budgets alert at $50 and $90 anyway.
- Sign up only when you are ready to launch the instance (about sprint day 16), so the 6-month window covers the whole live period.
- If you are not eligible: Google Cloud's free trial gives $300 for 90 days (new customers; an `e2-medium` in Tokyo, `asia-northeast1`, is comfortably covered), but the 90-day clock starts at sign-up, so sign up no earlier than sprint day 16. Otherwise a paid Tokyo server costs about $22-37 per month.
- A 2 GB instance (`t4g.small`, about $0.0216/h) also works if you add 2 GB of swap and the 24 h shakedown shows memory below 80%; it roughly halves the cost.

Where Binance's spot matching engine sits is not officially published. Community measurements point to AWS Tokyo, so Tokyo is the "near" site, but **the experiment does not assume it**: it measures the round-trip time (RTT) at each site and reports results against measured latency. If site B's measured median RTT is not clearly lower than site A's, report that as a finding.

Optional site C (US East, Virginia) only if the owner wants a third point on the distance curve; same setup.

## 2. What runs at each site
Identical software, deployed from the same git tag (`prereg-v1`):
- the collector (P1), recording full 10-level books and trades, and
- the live trader (P8), with `live.site: A` or `B` in its config. The site name is written into every log row and into `status.json`.
- `chrony` for clock sync, plus a logger that runs `chronyc tracking` every 10 minutes and appends `(ts_ns, site, offset_ms, rms_offset_ms)` to `data/clock/<date>.csv`. Periods where `|offset_ms| > 5` are excluded from cross-site timing comparisons (not from trading results) and counted.

Daily, both sites' `data/live/`, `data/clock/` and collector data are copied to the analysis machine (rsync from the laptop, as in DEPLOY.md). Site B's data is pulled the same way.

## 3. Measurements: `src/lobrc/experiments/two_sites.py`, CLI `lobrc twosites analyze --start D --end D`

### 3.1 Network latency
Per site: distribution (p50, p90, p99) of websocket ping RTT (from the trader's decision log `rtt_ms`), per day.

### 3.2 Data arrival delay
- **Trades:** for each trade id seen at both sites, `arrival_delay = recv_ns - E*1e6` (E = exchange event time in ms from the trade message). The exchange clock offset is the same for both sites, so the **difference** `delay_A - delay_B` cancels it, leaving the relative delay plus the two sites' clock errors (bounded by the chrony offsets; report them).
- **Depth snapshots:** match by `last_update_id`; report `recv_A - recv_B` distribution. Also report the fraction of `last_update_id`s seen at only one site (should be near 0; anything else means the stream differs by location, which is itself worth reporting).

### 3.3 Paired signal-level economics (the core result)
The live traders' actual trades diverge between sites (different fill times change when the next trade can start), so they cannot be paired directly. Instead:
1. **Signals:** a signal is a DeepLOB decision where `pred != stationary` and `conf >= tau`, regardless of position state. Match signals across sites by the anchor snapshot's `last_update_id`. Both sites must have produced the same prediction (identical inputs give identical outputs; assert the probabilities agree to 1e-5 and report any mismatches).
2. For each matched signal and each site, simulate the trade with that site's **own** snapshot log, its own measured `L` at that moment and inference time, using the P6 fill functions unchanged: `latency_bps`, `spread_bps_trade`, and `net_bps` for each fee scenario.
3. **Paired difference** per signal: `delta_bps = latency_bps_B - latency_bps_A` (also for `net_bps`). Positive means being near the exchange helps.
4. Statistics: mean `delta_bps` with a moving-block bootstrap 95% CI (P6 `stats.py`, ordered by time); also the regression `latency_bps ~ L_ms` pooled over both sites with block-bootstrap CI on the slope (bps lost per extra millisecond).
5. Also report the actual live trader results per site (P9 metrics), labelled as unpaired.

## 4. Pre-registration additions (update P7)
Add to `prereg/PREREGISTRATION.md`:
- **H5 (cost of distance):** the mean paired difference `latency_bps_B - latency_bps_A` per signal is positive, with the 95% block-bootstrap CI excluding 0. State the prior expectation in numbers before going live (for example from the backtest's edge-vs-latency curve evaluated at each site's measured median RTT in the 24 h shakedown).
- **H6 (stream equivalence):** at least 99.9% of depth `last_update_id`s are observed at both sites.
- Primary metric remains H3; H5 is the primary metric **of this experiment**.
Add to `prereg/manifest.json`: `"sites": [{"name": "A", "location": "...", "provider": "..."}, {"name": "B", ...}]`, and the git tag both sites must run.

## 5. Dashboard and write-up additions (update P9)
- Dashboard section "Distance": RTT histograms per site; arrival-delay difference histogram; cumulative paired `delta_bps`; bps lost per millisecond with CI; clock-offset health.
- Write-up: a dedicated section between "Reality check" and "Live test" titled "What distance costs", reporting H5 and H6 and the slope estimate, with the clock-sync caveat.

## 6. Tests (`tests/test_two_sites.py`)
1. **Paired simulation:** synthetic day; site B's snapshot log = the same snapshots shifted by +2 ms, site A's shifted by +120 ms; RTT 5 ms (B) and 240 ms (A); a model with real signal (`signal_strength=0.3`). Mean `delta_bps` > 0, and identical signals are matched one to one.
2. **Matching:** signals present at only one site are excluded and counted.
3. **Clock exclusion:** rows during a period with `|offset_ms| > 5` are excluded from the arrival-delay statistics.
4. **Exchange-clock cancellation:** adding a constant to every trade's `E` leaves `delay_A - delay_B` unchanged.

## Acceptance criteria
- Both sites run the same tag and manifest hash (first log line at each site) and pass a 24 h shakedown together before the live start.
- `results/twosites/summary.md` updated weekly with H5 and H6 status, RTT and arrival-delay tables, and the bps-per-millisecond estimate.
