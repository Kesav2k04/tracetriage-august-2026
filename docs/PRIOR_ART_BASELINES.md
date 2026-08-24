# Image-only baselines built here, and why they are the bar

**Unit A6.** Two image-only baselines and a floor, so that "the physics model
works" can be a comparison rather than an assertion.

## No published waterfall classifier was reproduced

The filename says prior art. The contents are not prior art, and this section is
the correction rather than a caveat.

Every model measured below was built in this repository: a base-rate floor, a
centre-energy heuristic, and HOG features into a logistic regression. **No
published waterfall classifier was reproduced and no external benchmark was
run.** The README names the prior art correctly, that SatNOGS already assigns
observation and waterfall statuses, that public projects already classify
waterfalls with CNNs, and that STRF-based tooling already extracts Doppler
traces, and it claims novelty for none of them. None of those three appears as an
arm anywhere in this repository. There is no CNN arm at any point in the ladder.

The reason, taken from the build record rather than reconstructed: unit A6's task
as written in `docs/BOB_BUILD_LOG.md` asked for "the first two rungs of the model
ladder as the honest baseline everything later must beat: a centre-energy
heuristic and HOG+regularised logistic regression, both calibrated". An external
reproduction was never in that unit's scope. Nothing in
`docs/BOB_BUILD_LOG.md` or `docs/PRE_BUILD_BASELINE.md` records a decision to
attempt one, to defer one, or to drop one, and neither does the build's credit
plan, which is a working document this repository does not publish. That plan ran
on 40 credits per trial account and allocated roughly 20 of the first account's to
the whole of Wave A across eight units, so no budget was set aside for an external
reproduction either. That is all the record supports, and it is stated here rather
than replaced with a tidier reason.

Two consequences a reader should carry into the gate 5 result. HOG dates from
2005, so it is a weak stand-in for the CNN classifiers the README concedes
already exist, and the bar the physics has to clear here is lower than the
published state of the field. And this document holds three rungs, not the six
ablations the README's document index calls it: the ten-arm ladder is in
`artifacts/FUSION_RECEIPT.json`, and the six items the README lists under prior
art are the components of the combination claim, not baselines.

The filename is unchanged because `README.md`,
`apps/web/public/data/bob.json` and `docs/BOB_BUILD_LOG.md` all reference it by
that name, and a broken link is worse than a filename with a correction at the
top of the file it names.

`artifacts/BASELINE_RECEIPT.json` is the source of truth for every number here.
It carries the snapshot id, the manifest sha256, the seed, the full exclusion
table and the split audit. If this document and the receipt ever disagree, the
receipt is right and this document is stale.

Reproduce with:

```
.venv\Scripts\python.exe scripts\run_baseline.py ^
  --snapshot D:/tracetriage_data/snap-stage1 ^
  --out artifacts/BASELINE_RECEIPT.json --seed 42
```

About 21 minutes, almost all of it OCR on 739 waterfalls.

## The three rungs

| Model | Brier | Log loss | Cal. slope | ECE | Improvement on the floor | 95% CI | Beats the floor |
|---|---|---|---|---|---|---|---|
| `prior_only` | 0.2162 | 0.6248 | 0.328 | 0.1138 | floor | | by definition |
| `centre_energy` | 0.2155 | 0.6227 | 3.843 | 0.1130 | +0.0007 | [-0.0003, +0.0027] | **no** |
| `hog_logistic_regression` | 0.1516 | 0.4619 | 2.154 | 0.1028 | +0.0646 | [+0.0476, +0.0809] | **yes** |

591 training and 148 validation observations, seed 42, train prior 0.6024.
Zero geometry failures in either half.

**`hog_logistic_regression` is the bar gate 5 has to clear.** It is the
calibrated image-only baseline, and its improvement on the floor is
distinguishable from zero. Its calibration slope of 2.154 says it is
under-confident, which B3 addresses; an under-confident baseline is still a
legitimate bar, and sharpening it later can only raise it.

## Why "beats the floor" is a hypothesis test and not a comparison

The floor predicts the training base rate for every observation. It cannot
distinguish one waterfall from another, so anything that fails to improve on it
has demonstrated nothing.

The obvious way to check that is `model.brier < floor.brier`. That was the
original implementation, and on this corpus it reported that the centre-energy
heuristic beat the floor by 0.0007 on 148 observations. A paired bootstrap over
those observations puts a 95% interval of [-0.0003, +0.0027] on that
improvement. The interval crosses zero, so the honest reading is that the
heuristic has not been shown to learn anything, and the receipt now says exactly
that.

The bootstrap is paired because both models score the same observations, so
resampling the per-observation squared-error *difference* removes the variance
the two share and asks only whether one is reliably better than the other.

## Why accuracy is not reported

Among the 739 decisive labels the split is 1.67 positives per negative. A model
that answers "positive" every time scores 62.5% accuracy and has learned nothing,
which is why the metrics here are Brier score, log loss, calibration slope and
intercept, and a reliability curve.

## What the split does and does not demonstrate

Ordered by each observation's own start time, taken from its waterfall URL
because the dataset manifest stores no timestamp and the local filename carries
none. Train covers 14:34 to 22:00 on 2026-08-09, validation 22:00 to 23:53, with
no overlap.

Ordering by observation id was tried first and described as chronological. It is
not: id order disagrees with time order on 27% of adjacent pairs here, and the
halves it produced overlapped in time by more than five hours, which is a
quasi-random split wearing a temporal label.

Three things bound what the validation numbers mean, all recorded under
`split.audit` in the receipt:

1. **The corpus spans a single evening,** 9 hours 19 minutes. No ordering of it
   can demonstrate temporal generalisation.
2. **129 of the 148 validation observations sit on a ground station that appears
   in training,** and 93 on a transmitter that does.
3. **Station identity is learnable from the image.** From HOG features alone, a
   logistic regression picks which of the six busiest stations produced an
   observation with 70.5% accuracy against a 24.6% majority-class baseline.
   Cropping to the spectrogram drops that to 57.3%, so roughly 13 points of it
   was the axes, tick labels and colorbar. The remainder is in the spectrogram
   itself, and reasonably so: a station's noise floor, bandwidth and RFI
   environment are visible in its captures.

Point 3 is the useful one. No amount of cropping makes station identity
unlearnable, so a split that lets a station appear on both sides cannot separate
signal detection from station recognition. **Treat everything in the table above
as in-distribution.** Cold-station, cold-transmitter and combined splits are B1's
job, and that is what any generalisation claim has to rest on.

## The centre-energy heuristic

Mean row-normalised intensity in a ±30 px strip around the tuned frequency,
turned into a probability by Platt scaling. Each row is z-scored against its own
median and MAD first, because a pass brightens as the satellite closes range, so
raw row means carry a vertical gradient that has nothing to do with frequency.

It is kept in the ladder despite not clearing the floor, for two reasons. It is
the cheapest thing that could have worked, which is what a first rung is for; and
a rung that fails is informative, because it says the answer is not simply "is
there energy near the tuned frequency". The receipt records it as not beating the
floor, so nothing downstream can quote it as a baseline.

One caution for anyone revisiting it. An earlier version computed
`1 - strip_mean / full_mean` and clipped to `[0, 1]`. On this corpus that
expression is negative for every observation, about -0.11 for both classes, so
the clip pinned all 591 training samples to exactly 0.0. The feature became a
constant, the model received one input value for every sample, and its Brier
score landed exactly on the floor, which read as evidence that centre energy does
not separate the classes. It was not evidence of anything: the feature had never
been computed. `tests/test_centre_energy_feature.py` now pins that the score
varies, points the right way, is not squashed into a bounded range, and is
invariant to a per-row gain.

## The HOG baseline

HOG over A2's spectrogram crop, resized to 128 by 256, L2-normalised, into an
L2-regularised logistic regression calibrated with Platt scaling
(`CalibratedClassifierCV`, sigmoid, `cv=5`).

The crop is load-bearing rather than tidy, for the reason in point 3 above: over
the full page HOG reads the furniture. An image whose geometry cannot be parsed
is excluded and counted, never handed a full-frame feature vector, which would
put the leak back silently.

## Exclusions

Every one of the 2,727 observations in the snapshot is accounted for, with no
residual bucket:

| Disposition | Count |
|---|---|
| `with-signal`, decisive positive | 462 |
| `without-signal`, decisive negative | 277 |
| `unknown`, never coerced to negative | 1,761 |
| No waterfall URL, artifact unusable | 227 |
| Transient fetch failure, retry candidate | 0 |
| Geometry parse failed, train | 0 |
| Geometry parse failed, validation | 0 |
| **Total** | **2,727** |

The three exclusions that matter are the three ways a loader can manufacture a
negative. `unknown` is not a negative: reading it as one would turn 277 negatives
into 2,265 and produce a model that has learned which observations a human got
round to vetting. A missing artifact is not a negative either. Nor is a transient
fetch failure, which means the server refused for now.
