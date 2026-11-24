# P5: Baselines and DeepLOB on crypto

**Goal:** train every model on the same samples and produce comparable predictions files for the backtest.

## 1. Baselines: `src/lobrc/models/baselines.py`
All take the handcrafted feature matrix `hand [M, F]` and class labels.
1. **Majority:** always predict the most frequent training class; probabilities = training class frequencies.
2. **Logistic regression:** `sklearn.pipeline.make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))` (multinomial is the default for 3 classes in recent scikit-learn; if your version warns, pass the explicit option).
3. **LightGBM:** `LGBMClassifier(objective="multiclass", num_leaves=31, learning_rate=0.05, n_estimators=2000, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=1234)`, fitted with early stopping on the validation split (`callbacks=[lightgbm.early_stopping(50)]`).

Each saves its model with `joblib`, plus `feature_names.json`. Also save LightGBM feature importances (gain) to CSV.

## 2. DeepLOB on crypto, config `configs/crypto_deeplob.yaml`
```yaml
inherits: default.yaml
task: crypto
dataset: {name: btc_v1, norm: stationary}   # P5 runs both norms; see matrix
data: {T: 100, horizon: 50}
model: {name: deeplob, apply_softmax_in_forward: false}
train:
  lr: 0.0001
  batch_size: 64
  epochs: 30
  early_stop_patience: 5          # on validation loss
  max_train_samples_per_epoch: 500000   # random subset each epoch, seeded
  seeds: [1234]
```
Training uses the P3 trainer unchanged. If an epoch takes over 30 minutes on the available GPU, halve `max_train_samples_per_epoch` and note it.

## 3. Experiment matrix
For each horizon k in {10, 20, 50, 100}:
| Run | Inputs |
| --- | --- |
| `majority_k{k}` | none |
| `logreg_k{k}` | handcrafted |
| `lgbm_k{k}` | handcrafted |
| `deeplob_paper_k{k}` | `x_paper` |
| `deeplob_stat_k{k}` | `x_stationary` |

**Selection rule (decided now, before seeing test results):** for each horizon, the DeepLOB normalisation variant with the higher **validation** macro F1 becomes `deeplob_k{k}`. The headline horizon for the waterfall and the live test is the one where the selected DeepLOB has the highest validation macro F1; ties go to the longer horizon (cheaper to trade). Write the selection to `results/crypto/selection.json` **before** running test evaluation.

## 4. Evaluation (`lobrc evaluate`, reused from P3)
On validation and test separately:
- accuracy, macro and weighted precision/recall/F1, confusion matrix,
- **directional hit rate on point returns:** among predictions of up or down where `r_bps != 0`, the fraction with `sign(r) == direction`,
- **information coefficient:** Spearman correlation between `p_up - p_down` and `r_bps` (all anchors),
- per-day versions of these metrics.

Predictions file `predictions_<split>.parquet` with columns: `anchor_idx, recv_ns, y_true, l_true, r_bps, p_down, p_flat, p_up`. This is the only interface between models and the backtest.

## 5. Transfer test (out-of-sample instrument, like the paper's test on unseen stocks)
Apply the selected BTC DeepLOB for the headline horizon to the `eth_v1` test split without retraining. For the `stationary` variant use ETH's own training-split statistics (record which choice was made).

## 6. Results
`results/crypto/models.md` and `models.csv`: one table per split with every run's metrics; a short paragraph on whether DeepLOB beats LightGBM on handcrafted features and by how much (validation and test). Figures: test macro F1 by horizon for each model (`results/crypto/f1_by_horizon.png`).

## Tests
- `tests/test_baselines.py`: on synthetic data with `signal_strength=0.3`, logistic regression beats majority on macro F1 by at least 0.05; with `signal_strength=0`, logistic regression macro F1 is within 0.05 of majority (no fake signal).
- `tests/test_predictions_schema.py`: predictions file has exactly the columns above, probabilities sum to 1 within 1e-5, `anchor_idx` is strictly increasing.

## Acceptance criteria
- All runs in the matrix complete; `selection.json` written before any test-set evaluation (its timestamp in git must precede the test metrics file).
- `models.md` complete, including the ETH transfer row.
