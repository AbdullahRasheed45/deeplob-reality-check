# P7: Pre-registration and freeze

**Goal:** commit, publicly and before the first live prediction, exactly what will be tested and how it will be judged. This is what makes the live record credible.

## 1. What gets frozen
- The headline model: the selected DeepLOB at the headline horizon (`results/crypto/selection.json`). Retrain is **not** allowed; copy its `best.pt` and `model_config.json` to `prereg/model/`.
- Normalisation: for `stationary`, the training-split statistics file; for `paper`, the rule (previous up to 5 days, pooled price/size stats) and the code version that computes it daily.
- `alpha` for the headline horizon, `tau*` from `tau.json`, `hold_ns`, `Q`, the fill rules (P6 sections 1-3), the fee scenarios and latency handling (live uses measured round trip time; see P8).
- One baseline that runs live in parallel as a control: the LightGBM model at the same horizon (it needs the trade-flow features, which the live trader computes from the trade stream).

## 2. `prereg/manifest.json`
```json
{
  "created_utc": "...",
  "git_commit": "...",
  "symbol": "BTCUSDT",
  "horizon_snapshots": 50,
  "model": {"path": "prereg/model/best.pt", "sha256": "...", "config_sha256": "..."},
  "control_model": {"path": "prereg/control/lgbm.joblib", "sha256": "..."},
  "normalization": {"variant": "stationary", "stats_path": "...", "sha256": "..."},
  "alpha": 0.0, "tau": 0.55, "notional_usd": 1000,
  "fee_scenarios_bps": [0, 2, 7.5, 10],
  "live_start_utc": "...", "live_min_days": 28, "live_max_days": 56,
  "git_tag": "prereg-v1",
  "sites": [{"name": "A", "location": "London", "provider": "Oracle"}, {"name": "B", "location": "Tokyo", "provider": "..."}]
}
```
Values shown are placeholders; fill from the real artifacts. `lobrc prereg freeze` builds this file, computes the hashes, and refuses to run if the git working tree is dirty.

## 3. `prereg/PREREGISTRATION.md` (template; the owner fills the bracketed parts, defaults given)
1. **Question:** how much of DeepLOB's offline predictive power and simulated edge persists on live data it has never seen, under real timing?
2. **Hypotheses:**
   - H1 (prediction quality): live macro F1 on smoothed labels is at least the test macro F1 minus 0.05. [default]
   - H2 (signal survives): live Spearman IC between `p_up - p_down` and point return is positive, with the 95% bootstrap CI excluding 0.
   - H3 (economics): live mean `net_bps` per trade at fee 2 bps is positive with the 95% block-bootstrap CI lower bound above 0. Our prior expectation, stated now: [e.g. "H3 will be rejected; the offline test shows net edge below zero at every fee above 0"].
   - H4 (control): DeepLOB live IC exceeds the LightGBM control's live IC.
   - H5 and H6 (two-location experiment): exactly as worded in plan/P11 section 4.
3. **Primary metric:** H3 at fee 2 bps with measured latency (site A). For the two-location experiment the primary metric is H5. Everything else is secondary.
4. **Duration:** at least 28 and at most 56 days. Stop early only for infrastructure failure, never for results.
5. **Exclusions:** data gaps (as defined in P1) and trades dropped by the segment-end rule are excluded and reported with counts. No other exclusions.
6. **No changes:** no retraining, no threshold changes, no new features during the live period. Bug fixes that change no trading decision are allowed and logged in `DECISIONS.md`.
7. **Reporting:** every week, whatever the result. The final report includes every pre-registered metric.

## 4. Procedure
1. Fill in `PREREGISTRATION.md` and run `lobrc prereg freeze`.
2. Commit `prereg/` with message `Pre-registration v1`, create the annotated tag `prereg-v1`, push to the public GitHub repository. The push timestamp is the public proof of when it was written.
3. Only then start the live service (P8). The live service checks the manifest hashes at startup.

## Tests
- `lobrc prereg freeze` on a dirty tree exits non-zero.
- A modified model file (one byte changed) fails hash verification in `lobrc.models.registry.verify_manifest`.

## Acceptance criteria
- Tag `prereg-v1` exists on GitHub; the live service log's first line shows the matching manifest hash.
