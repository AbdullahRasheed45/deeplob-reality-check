# P9: Dashboard, weekly reports and final write-up

**Goal:** make the work visible and checkable: a public dashboard that updates daily, honest weekly reports, and a final research note.

## 1. Live evaluation: `src/lobrc/report/live_eval.py`
Inputs: `data/live/` logs and `prereg/manifest.json`. All metrics use only the trader's own snapshot log, so live evaluation never depends on the collector.
- Live labels: from the snapshot log, rebuild mids per segment and compute the smoothed label (with the frozen alpha) and the point return at the frozen horizon for every decision row (P4 functions).
- Classification: macro F1, accuracy, confusion matrix, IC (Spearman of `p_up - p_down` vs point return) for DeepLOB and control, overall and per day.
- Trading: per model and per fee scenario (fees are applied after the fact to the logged `spread_bps_trade`, so all four scenarios come from the same live trades): number of trades, mean `net_bps` with block-bootstrap 95% CI, hit rate with Wilson CI, cumulative net, waterfall components, mean L and inference time.
- Expected-vs-live: the test-split backtest result for the same model and scenario, shown alongside.
- Pre-registered hypotheses H1-H4: current status with the exact statistic and CI, labelled "interim" until the live period ends.
- Data quality: gaps, aborted trades, reconnects.

## 2. Dashboard: `src/lobrc/report/site.py`, CLI `lobrc report site`
Builds a static `site/index.html` (single page, Plotly loaded from its CDN with a pinned version) with these sections, top to bottom:
1. Headline sentence generated from the numbers (e.g. "After N live days, DeepLOB's mean net edge at 2 bps fees is X bps per trade (95% CI [a, b])").
2. Cumulative net bps, live, per fee scenario, DeepLOB vs control.
3. Waterfall (live) next to waterfall (backtest test split).
4. Rolling 1-day IC and macro F1 vs the test-split values.
5. Latency: histograms of RTT and inference time.
6. Data quality table: daily coverage, gaps, aborted trades.
6b. Distance (two-location experiment): the charts listed in plan/P11 section 5.
7. Pre-registration: link to the tagged `prereg/` folder on GitHub and the manifest hash; hypothesis status table.
8. Footer: "Paper trading on public market data. No real orders. Not investment advice." and last-updated time in UTC.

Also writes `site/data/*.json` with the numbers behind each chart, so anyone can check them.

## 3. Publishing
- Separate branch `gh-pages` in the same public repository; GitHub Pages serves it.
- On the server: `lobrc report publish` copies `site/` into a checkout of `gh-pages`, commits `Daily update <date>`, and pushes using a **repository-scoped deploy key with write access** (never a personal token). Document key setup in `DEPLOY.md`.
- `ops/lob-report.service` (oneshot: `lobrc report site && lobrc report publish`) and `ops/lob-report.timer` (`OnCalendar=*-*-* 00:30:00 UTC`, `Persistent=true`).

## 4. Weekly report: `lobrc report weekly --week N`
Generates `reports/week-NN.md` from a template with all numbers filled for the week and cumulative, and empty sections for the owner to write: "What happened", "What surprised me", "Anything I would change (but won't until the live period ends)". Commit each week.

## 5. Final write-up: `lobrc report writeup`
Generates `results/writeup/report.md` with numbers and figures filled, and section headings the owner completes. Convert to PDF with `pandoc` if available (optional). Sections:
1. Abstract (5 sentences: question, data, method, main result with CI, implication).
2. Background: limit order books, DeepLOB, why replication matters.
3. Data: FI-2010; our Binance recording (days, coverage, gap log, quality checks).
4. Replication on FI-2010 (table vs published, softmax quirk, cross-stock windows, label caveat).
5. Crypto models (baselines vs DeepLOB, normalisation variants, transfer to ETH).
6. Reality check: waterfall, edge vs latency, breakeven fees, oracle and random references.
7. Live pre-registered test: results per hypothesis, live vs backtest.
8. Limitations (sample size, paper fills, taker-only, single venue, retail latency, short period) and what a firm with better infrastructure would do differently.
9. Reproducibility: commands, versions, checksums.

## 6. README (final)
Top: one figure (headline waterfall or live cumulative chart) and one sentence with the main finding and its CI. Then: links to dashboard, pre-registration tag and write-up; "Reproduce" section with `make` targets; repository map; licence; disclaimer.

## Acceptance criteria
- Dashboard public and updating daily for the whole live period; weekly reports committed; final write-up complete with every pre-registered metric reported.
