# Kill gate: status board

The plan sets six thresholds that must pass before TraceTriage is worth building. Three were pre-measured on 2026-08-16 before Bob's first task, using live read-only probes. Three remain and can only be settled with the frozen snapshot in hand.

**Thresholds were fixed before any measurement. Do not move one after seeing a result.** If a gate fails, record the failure here with its number and stop. A documented honest failure beats a concealed one.

---

## Status summary

| # | Gate | Threshold | Status |
|---|---|---|---|
| 1 | Dataset volume and entity spread | ≥2,000 mature waterfalls, ≥12 transmitters, ≥30 stations | **PRE-PASSED on feasibility** |
| 2 | Metadata coverage for the corridor | ≥80% of the sample computable | **PRE-PASSED** |
| 3 | Corridor intersects a visible trace | ≥70% of reviewed positives | **PASSED, 3/3 testable (100%); 4 of 7 not testable, and the 3 span 2 stations on 1 night** |
| 4 | Blinded human decidability | ≥80% of a balanced sample decidable | **OPEN** |
| 5 | Physics beats image-only on Brier | strict improvement, chronological split | **OPEN** |
| 6 | Queue lift over random | ≥1.5x actionable conflicts at equal budget | **OPEN** |

---

## Gate 1: dataset volume and entity spread — PRE-PASSED on feasibility

**Threshold:** at least 2,000 mature waterfalls across at least 12 transmitters and 30 stations, including decisive positive, decisive negative and unknown examples, with raw responses, retrieval times, hashes, schema version and CC BY-SA terms preserved.

**Measured** on 600 consecutive observations ending before 2026-07-15:

| Quantity | Result | Floor | Margin |
|---|---|---|---|
| Unique transmitters | 197 | 12 | 16x |
| Unique stations | 211 | 30 | 7x |
| Unique NORAD IDs | 179 | — | — |
| Waterfall URL present | 92.3% | — | — |
| Decisive `waterfall_status` | 29.0% | — | — |

Entity spread passes with enormous margin in a sample less than a third of the required size. Volume is a download, not a research question: ~2,170 fetched records yield ~2,000 waterfalls, about 87 cursor pages and roughly 3.4 GB of PNG.

**Why "on feasibility" and not "passed":** the gate also requires the preservation obligations, hashes, retrieval times, licence terms. Those are satisfied by the snapshot builder, which is Bob's Wave A work. **Gate 1 closes when the snapshot exists, not when the counts are known.**

### The constraint that is easy to miss

Decisive negatives ran at **10.2%** (61/600), against 18.8% positives, a **1.85 : 1** positive-to-negative imbalance among decisive labels.

A 2,000-waterfall snapshot yields roughly 380 decisive positives and 200 decisive negatives, which is too thin to hold up a cold-entity claim.

### DECIDED, 2026-08-16 15:20 IST: snapshot target is 10,000 observations

The operator approved a **20 GB** data budget for exactly this reason. At the measured rates:

| | |
|---|---|
| Observations fetched | 10,000 |
| Waterfalls at 92.3% | ~9,230, about **15.7 GB** at 1.7 MB mean |
| Decisive negatives at 10.17% | **~1,017** |
| Decisive positives at 18.83% | ~1,883 |
| Cursor pages at 25/page | ~400, roughly 15 minutes at 0.4 s spacing |

That clears roughly 1,000 decisive per class on the negative side, which is the binding one. Task A1 carries this number and must not scale it down.

Report the 1.85:1 imbalance in the results; do not silently rebalance it.

---

## Gate 2: metadata coverage for the corrected corridor — PRE-PASSED

**Threshold:** enough stored TLE, timing, station, transmitter-frequency and artifact metadata to compute a corrected centre corridor for at least 80% of the sample.

**Measured** on the same 600:

| Field group | Coverage |
|---|---|
| `tle1` + `tle2` | **100.0%** |
| `client_metadata` (rx-freq, sample rate, client version) | **94.0%** |
| `waterfall` URL | 92.3% |
| Station lat/lng/alt, start/end, observation_frequency | 100% (always present on the record) |

Binding coverage is the intersection: an observation needs TLE **and** client metadata **and** a waterfall. Worst case that intersection is bounded below by 1 - (0 + 0.06 + 0.077) = **86.3%**, above the 80% floor even if every gap is disjoint.

One correction to the plan's assumption: **`center_frequency` is null in practice**, on every record inspected. The receiver truth is `client_metadata.radio.parameters.rx-freq`, inside a JSON-encoded string. An ingestion that depends on `center_frequency` will find 0% coverage and wrongly conclude this gate fails.

---

## Gate 3: corridor intersects a visible trace — PASSED on 3 testable observations

**Threshold:** on a blinded check, the expected corridor intersects a visible target-like trace in at least 70% of reviewed positive examples.

**First claimed by A7 on 2026-08-17, withdrawn the same day, re-measured and closed by `scripts/run_gate3.py`.** Receipt: `artifacts/GATE3_RECEIPT.json`.

### What the withdrawn A7 result was

A7 computed `trace_half_width_hz = 3 * hz_per_px / 2` and compared it against the corridor half-width. Both sides are constants: the left one a matched-filter kernel width (116 to 192 Hz across the two known client layouts), the right one a hardcoded 1200 or 2000 Hz. Nothing in the comparison depended on where the trace sat, so it returned True for all seven of A3's decisive observations and could not return False for any waterfall with a normal axis scale. It was reported as 1/1 = 100%, and a 70% rate cannot be measured on one observation in any case.

A7 also left `freq_offset_hz` at its `0.0` default, so the corridor it checked sat at rx-freq. A3's stored `curved_offset_hz` for this same observation is -13,985 Hz against a corridor whose outer edge is 10,303 Hz from rx-freq, which puts the trace 3,682 Hz outside the band entirely. On the one position number the artifacts held, the unshifted corridor missed by 7x its own half-width.

### The correct measurement

The absolute downlink frequency is not known to better than tens of ppm: a cubesat oscillator drifts, and the SatNOGS transmitter frequency a station tunes to is community-maintained. So one constant frequency offset is fitted per observation, bounded at **50 ppm of the downlink**, which is about 20 kHz at 400 MHz and 6.9 kHz at 137 MHz. A3's own scan bounded this at plus or minus 76.9 kHz, 9.3x the Doppler swing, which lets the curve land anywhere and is why A3's sigma establishes shape rather than position.

A fitted offset is a free parameter, so an absolute score carries no evidence. The statistic is the true corridor against **200 null corridors built by permuting its own Doppler samples in time**, which preserves every frequency value and the whole swing while destroying the monotone shape. Both get the identical bounded fit. Time reversal is deliberately not used: A3 established that a Doppler curve is near odd-symmetric about closest approach, so a reversed curve still fits.

| obs | corridor | fitted offset | sigma | 200-null max | margin | nulls >= true | p |
|---|---|---|---|---|---|---|---|
| 14740031 | uncorrected | +13,985 Hz (+32.0 ppm) | **2.02** | 0.57 | +1.45 | 0 of 200 | 0.005 |
| 14745664 | uncorrected | -7,149 Hz (-16.4 ppm) | **1.54** | 0.41 | +1.13 | 0 of 200 | 0.005 |
| 14745929 | uncorrected | -7,149 Hz (-16.4 ppm) | **1.65** | 0.40 | +1.25 | 0 of 200 | 0.005 |

The fitted offsets reproduce A3's independently measured `curved_offset_hz` for all three, which is a cross-check between two separately written estimators.

**Scaled-swing controls.** The obvious objection is that this rewards any smooth bright path rather than the predicted physics. So the same curve was rescaled to 0.25x, 0.5x, 2x and 4x its predicted swing, holding shape and smoothness exactly fixed and varying only magnitude:

| obs | true (1x) | 0.25x | 0.5x | 2x | 4x |
|---|---|---|---|---|---|
| 14740031 | **2.02** | 0.65 | 0.74 | 0.62 | 0.31 |
| 14745664 | **1.54** | 0.52 | 0.56 | 0.47 | -3.49 |
| 14745929 | **1.65** | 0.49 | 0.53 | 0.49 | -1.53 |

The predicted swing beats every rescaling on every observation. The measurement is confirming the magnitude SGP4 predicted, not the presence of a smooth line.

**Gate 3 passes: 3 of 3 testable observations discriminate (100%) against a 70% threshold.**

### The scope limit, which is a real finding and not a pass

**Only 3 of A3's 7 decisive observations are testable at all.** The corrected corridor is **identically 0 Hz across the whole pass**, a bare vertical line with a free horizontal offset. It predicts no shape, so there is nothing to confirm, and every null built from it reproduces it exactly. Measured before this was guarded: on obs 14745602 the true corridor and the flat null both scored coverage 1.000, and on obs 14746118 true and scrambled sigmas agreed to every decimal place. That reads as "the physics has no discriminating power" and is really "the control was the same corridor".

So the physics-conditioned part of TraceTriage has predictive content **only on uncorrected captures**. A3 found 3 uncorrected among 24 vetted with-signal observations. Excluding the corrected four is a limit on the gate's scope, recorded as `observations_not_testable` in the receipt. It is not a pass, and any claim about physics value has to carry it.

### n = 3, and the three are not independent

Each observation carries its own p-value at the 1/201 floor and beats all four scaled-swing controls, so the **per-observation** evidence is strong. The **cross-observation rate does not carry three independent samples**, and the receipt now records why under `entity_grouping`:

| obs | NORAD | station | window (UTC, 2026-08-09) |
|---|---|---|---|
| 14740031 | 63214 | 91 | 23:50:08 to 23:54:09 |
| 14745664 | 63218 | 1696 | 23:32:49 to 23:40:58 |
| 14745929 | 63217 | 1696 | 23:43:40 to 23:51:28 |

2 ground stations, 3 satellites, **1 UTC night**, all inside a 22-minute window. The NORAD IDs are consecutive, so these are almost certainly one deployment cluster. Two of the three share station 1696 three minutes apart, which is exactly why they fit an identical -7,149 Hz offset: the same receiver carries the same local-oscillator error and the same stale transmitter frequency, so that is **one systematic offset measured twice**, not two independent confirmations.

The plan requires bootstrapping "by orbital episode or day, not by image row" and keeping each transmitter and orbital revolution in one split. By that rule this is closer to 2 station-days on 1 night than to n=3. Gate 3 is passed, and the generalisation it supports is narrow until Wave B re-runs it at snapshot scale across stations, bands and dates.

### Diagnostics that are reported but are not the gate

Per-row residuals and corridor coverage are in the receipt as `fit.*` and are **not** the gate statistic. These traces integrate to significance along the path while individual rows stay below the 4.0 robust-z detection floor: on obs 14740031, 2.1% of rows carry a per-row detection, so `fit.degraded` reads `TRACE_NOT_MEASURABLE` and `residual_hz` is null. A per-row instrument reports nothing on a trace A3 localised at high sigma, which is why the gate uses the path-integrated statistic. Reporting a null residual honestly is the point; A7's 185.6 Hz was a constant standing in for this missing measurement.

### Thresholds

Every threshold is a constant in `pipeline/tracetriage/corridor_fit.py`, fixed before any observation was scored, with its reasoning in `THRESHOLD_RATIONALE` and pinned by `tests/test_corridor_fit.py::test_thresholds_are_the_documented_values`: `z_min=4.0`, `min_detect_frac=0.30`, `coverage_threshold=0.70`, `offset_ppm_limit=50.0`, `n_nulls=200`, `p_value_max=0.05`, `swing_scale_factors=(0.25, 0.5, 2.0, 4.0)`, `seed=42`.

### Physics verification (Trap 1 and 2 guard)

Time runs **bottom to top** (top row = end of pass). The frequency axis runs **against the Doppler sign** (`AXIS_SIGN_CONVENTION = -1`). Both are encoded in `physics.corridor_columns` and guarded in `tests/test_physics.py`. These two errors cancel visually, which is why the verdict is a measurement with a stated margin rather than a visual read.

That same sign convention broke the first version of this measurement: the offset was searched in column space and handed back as `off_px * hz_per_px`, so it was re-applied to the opposite side of the axis, displaced the curve by twice the fitted 113 px, and detected nothing while every intermediate number looked plausible. Conversion now goes through `px_to_offset_hz`, guarded by three tests.

The Hz/px derivation was verified: **123.76 Hz/px** from axis-tick OCR maps the 17,290 Hz swing to ~140 px of the 621 px plot, about 22% of the frequency axis. Assuming `samp-rate-rx` (2.5 MHz) would compress the corridor to ~7 px and fail this gate for a reason that is purely a wrong constant.

---

## Gate 4: blinded human decidability — OPEN

**Threshold:** a balanced sample reviewed with API labels and model output hidden; at least 80% must support a decisive artifact or target-consistency judgment.

Requires the snapshot and a blinded review harness. Split assignment must be frozen **before** review begins. Separate axes: artifact usability, visible signal, target consistency. Relabel a fixed subset after a delay and report intra-rater agreement.

If below 80%, the labelling protocol is the problem, not the model. Fix the protocol before training anything.

---

## Gate 5: physics improves probability quality — OPEN

**Threshold:** the physics-conditioned model lowers Brier score against a calibrated image-only baseline on a temporary chronological split.

Both baselines are Bob's Wave A and B work. The comparison must be against a **calibrated** image-only baseline, not a raw one, or the improvement is just calibration wearing a physics costume.

Use the temporary chronological split here. The frozen test set is not touched at this stage.

---

## Gate 6: queue lift over random — OPEN

**Threshold:** the top of the review queue surfaces at least 1.5x as many manually actionable conflicts as random ordering, at the same budget.

Needs gate 4's annotations to define "actionable". Compare against random, FIFO, entropy-only and image-confidence orderings, with grouped bootstrap intervals by orbital episode or day. The 95% interval for lift over random must sit above 1.0.

---

## If a gate fails

Record it here: gate number, threshold, measured value, the artifact that produced it, and the date. Then stop.

Do not submit another image-only waterfall classifier under this plan. The plan is explicit: more features cannot repair a false claim.

---

## Failure log

*No gate failures recorded. Gates 3 to 6 are unmeasured, which is not the same as passing.*
