# Prior-art baselines — unit A6

These are the two baselines that gate 5 measures the physics-conditioned model against.
Every number here is generated from `artifacts/BASELINE_RECEIPT.json` (snapshot
`snap-20260817-stage1`, seed 42, manifest sha256 `9fb0c0a28175e7ef8f5d396cfe576f3e9cb4e3208b4358d1caaf054124d97f05`).

---

## Why two baselines, not one

Gate 5 reads: "the physics-conditioned model lowers Brier score against a
**calibrated** image-only baseline."  That one word, *calibrated*, eliminates
a large class of phantom improvements.  An uncalibrated model that outputs
raw logits near 0 and 1 has terrible Brier score.  Adding physics and then
calibrating produces a lower Brier not because physics helped but because
calibration helped.  The physics claim requires beating a baseline that is
already calibrated.

The centre-energy heuristic is included because it is the simplest non-trivial
score one could define, and its failure on this corpus is an honest result that
needs to be on record.

---

## Corpus and split

| Item | Value |
|---|---|
| Snapshot | `snap-20260817-stage1` |
| Total observations in manifest | 2,727 |
| Decisive (with-signal + without-signal) | 739 |
| Positive (with-signal) | 462 |
| Negative (without-signal) | 277 |
| Positive-to-negative ratio among decisive | 1.67 : 1 |
| Training set (oldest 80% by id) | 591 decisive |
| Validation set (newest 20% by id) | 148 decisive |
| Train prior P(positive) | 0.6159 |

**Split method: chronological, ascending observation id.**
A random split would leak because a few hundred ground stations are spread
across the corpus and station identity carries signal.  Real grouped splits
(cold-station, cold-transmitter, combined) are built in B1; this split is
temporary and used only for gate-5 baseline evaluation.

### Exclusion table

Every observation is accounted for; the counts sum to 2,727.

| Bucket | Count | Reason |
|---|---|---|
| `n_positive` | 462 | with-signal, URL present — used for training/eval |
| `n_negative` | 277 | without-signal, URL present — used for training/eval |
| `n_unknown_label` | 1,761 | URL present but `waterfall_status == "unknown"` — never labelled |
| `n_missing_url` | 227 | No waterfall URL (`NO_WATERFALL_URL`) — not a negative |
| `n_transient_fail` | 0 | THROTTLED / TIMEOUT / HTTP_ERROR — zero after hardening in A1 |
| **Total** | **2,727** | |

**Trap 1 (unknown ≠ negative):** 1,761 observations carry a URL but no decisive
label.  Reading `unknown` as `without-signal` would inflate the negative class
from 277 to 2,038 — more than sevenfold — and yield a model that has learned
which observations a human vetter got round to rather than anything about signals.
None of them enter any split.

**Trap 2 (missing URL ≠ negative):** 227 observations have no waterfall URL.
A missing artifact says nothing about whether the satellite was transmitting.
None of them enter any split, and none are scored as zero energy.

**Trap 3 (transient failures):** zero in this snapshot.  The A1 hardening
that made throttle events retryable means no observation in stage 1 carries
`THROTTLED`, `TIMEOUT`, or `HTTP_ERROR`.

---

## Model 1: Centre-energy heuristic

**Idea.** Signal concentrates energy near the tuned frequency; noise is
spatially flat.  Crop the waterfall to the physics-predicted central band
(±30 px around `centre_px`) and return `1 − (strip_mean / full_mean)`.
A darker strip (lower pixel value = more energy) produces a higher score.
Calibrated via Platt scaling (logistic regression on the raw score, fitted
on training observations only).

**Result.**

| Metric | Value |
|---|---|
| n scored (val) | 148 |
| Brier score | 0.2258 |
| Log loss | 0.6442 |
| Calibration slope | 0.260 |
| ECE | 0.0463 |
| Beats prior-only floor? | **No** |

The prior-only floor (always predict 0.6159) achieves Brier = 0.2258.
The centre-energy heuristic matches it exactly after calibration, meaning the
calibration converged to the prior and the raw score is not discriminative at
corpus scale.  This is not a bug — it is a real finding.  The brightness ratio
is not a reliable signal-presence indicator on this dataset.

**Centre-energy is therefore not a valid gate-5 comparison target.**

---

## Model 2: HOG + regularised logistic regression (calibrated)

**Idea.** Resize the cropped spectrogram to 128×256, compute HOG orientation
histograms (9 orientations, 8×8 cells, 2×2 blocks), L2-normalise, and fit
`LogisticRegression(C=0.1, class_weight="balanced")`.  Calibrated via
`CalibratedClassifierCV` with Platt scaling (sigmoid, 5-fold stratified cv
on training data only).

**Why this is the gate-5 bar.**
- It uses the image directly, without physics.
- It is calibrated.  The Brier score improvement a physics model achieves must
  survive the same calibration step, or it is not physics that helped.
- It beats the prior-only floor, confirming it has learned something.

**Result.**

| Metric | Value |
|---|---|
| n scored (val) | 148 |
| Brier score | 0.1958 |
| Log loss | 0.5826 |
| Calibration slope | 1.449 |
| ECE | 0.1048 |
| Beats prior-only floor? | **Yes** |

Brier improvement over prior: 0.2258 − 0.1958 = **0.030** (13.4% relative reduction).

The calibration slope of 1.45 (> 1) indicates the model is still slightly
underconfident on the validation set.  This is expected for a small-dataset
logistic regression with 5-fold cross-calibration; the score is usable.

---

## Prior-only floor

Every baseline must beat the prior-only model, which predicts the training base
rate (0.6159) for every observation.

| Metric | Prior-only |
|---|---|
| Brier score | 0.2258 |
| Log loss | 0.6442 |

A model that does not beat this on Brier score has learned nothing.

---

## Summary table

| Model | Brier | LogLoss | CalSlope | ECE | Beats floor? |
|---|---|---|---|---|---|
| prior_only | 0.2258 | 0.6442 | 0.260 | 0.0463 | — (floor) |
| centre_energy | 0.2258 | 0.6442 | 0.260 | 0.0463 | **No** |
| hog_logistic_regression | **0.1958** | **0.5826** | 1.449 | 0.1048 | **Yes** |

**Gate-5 comparison target: `hog_logistic_regression`, Brier = 0.1958.**

The physics-conditioned model (A7+) must achieve Brier < 0.1958 on the same
chronological split to pass gate 5.  A result against the uncalibrated
raw score, or against `centre_energy`, would not close the gate.

---

## Reproducibility

Re-running `scripts/run_baseline.py` with `--seed 42` regenerates identical numbers
from the same snapshot.  All randomness passes through `numpy.random.default_rng(seed)`
and `sklearn random_state=seed`.  The receipt records the manifest sha256 so a
mismatch between snapshot and receipt is detectable.

```
python scripts/run_baseline.py \
    --snapshot D:/tracetriage_data/snap-stage1 \
    --out artifacts/BASELINE_RECEIPT.json \
    --seed 42
```

Runtime on CPU: ~21 minutes (EasyOCR processes 739 waterfall images).
No GPU is used in A6; HOG and logistic regression are CPU-only.
