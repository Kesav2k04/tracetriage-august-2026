# E16 pre-registration: growing gate 3's testable pool

Written and committed **before `scripts/run_gate3.py` was run against the larger pool**,
so that no rule below can have been chosen after seeing what it produces. Same discipline
as `docs/C2_PREREGISTRATION.md`: fix the definition, then measure.

Committed: 2026-08-22.

## 1. Why this unit exists

Gate 3 asks whether the expected Doppler corridor intersects a visible trace in at least
70% of reviewed positive examples. It was measured on the 3 uncorrected captures inside
A3's 24-observation live sample. All 3 discriminated.

A perfect rate at n = 3 has an exact one-sided Clopper-Pearson 95% lower bound of
`0.05 ** (1/3) = 0.3684`, which is below 0.70. The first n whose perfect rate clears the
bar is 9, because `0.05 ** (1/9) = 0.7169` and `0.05 ** (1/8) = 0.6877`. So the gate reads
`NOT_ESTABLISHED` on the count, not on the measurements: every testable observation in the
sample behaved, and there were not enough of them.

`artifacts/GATE_POWER_RECEIPT.json` records this as an **exact, non-frozen** closure. Non-
frozen because, unlike gates 5 and 6, closing it needs no change to a pre-registered split
or budget. The snapshot `snap-stage1` already holds 2,500 waterfall images on disk. Nothing
is fetched and no new data is collected.

## 2. The methodological problem, stated before the run

A3 labelled an observation `UNCORRECTED` when

    sigma_curved - sigma_vertical >= SIGMA_MARGIN     (3.0)

That is a statement about how well the predicted Doppler corridor fits the image. Building
the testable pool from it and then asking whether the corridor discriminates is **selection
on a quantity correlated with the outcome**. A rate measured that way is partly a
measurement of the selection rule, and growing n under it would produce a bigger number
that means less than the small one it replaced.

This is the reason the unit exists as a pre-registration rather than as a re-run.

## 3. The two pools, fixed here

Both are built by `scripts/build_gate3_pool.py` over every observation in the snapshot
that has a waterfall on disk. No sampling, no ordering, no cap. An observation that cannot
be measured is written out with the reason, so the denominator is as auditable as the
numerator.

### Pool A, corridor-selected

A3's rule verbatim: `verdict_from_scores` returns `UNCORRECTED`. Published so the larger
run is comparable with the n = 3 result. **This pool does not decide the gate.**

### Pool B, the pre-registered pool

An observation enters when all of the following hold. None of them reads the corridor's
fit to the image.

1. Geometry derived and not degraded: `parse_waterfall` returns a crop box and a Hz/px.
2. Physics not degraded: `corridor_for_obs` returns without a degradation code, which
   covers a missing TLE, an unparseable epoch and a stale epoch.
3. Predicted swing `>= MIN_PREDICTED_SWING_HZ` (3000 Hz). This is a property of the
   orbital prediction and the receive frequency. It is computed without touching the
   image, so it cannot be influenced by whether the corridor matches anything.
4. A trace is visible: `trace_q75 >= TRACE_Q75_MIN`.
5. The vertical hypothesis does not fit: `sigma_vertical < SIGMA_MIN` (8.0). A vertical
   matched filter uses no Doppler prediction; it is the test for a Doppler-corrected
   capture, whose corridor is identically 0 Hz and predicts no shape.

**Pool B decides the gate.**

### The presence statistic

`trace_q75` is the 75th percentile of the per-row maximum z-score over the spectrogram
interior, each row scored against its own median and MAD, which is the normalisation
`corridor_fit` already uses. A percentile rather than a maximum, so one bright row of
interference does not admit an observation: the trace has to be there through at least a
quarter of the pass.

**How the bar was set, and the reasoning that was wrong first.** The first value tried was
6.0, argued from the maximum of W independent Gaussian columns sitting near
`sqrt(2 ln W)`, about 3.7 at these image widths. Measured on a 12-observation timing probe
that reasoning is wrong for this normalisation: the noise ceiling is near 2.0, and 6.0
excluded observation 14740031, whose matched filter reaches 25.1 sigma on the same image.
The probe's numbers, which are the only observations looked at before this document was
written:

| obs | verdict | trace_q75 | trace_median | trace_max | sigma_vertical | sigma_curved |
|---|---|---|---|---|---|---|
| 14746129 | UNRESOLVED | 2.02 | 1.91 | 2.70 | 1.14 | 1.32 |
| 14745696 | UNCORRECTED | 11.02 | 9.67 | 16.64 | 8.05 | 19.93 |
| 14744333 | UNRESOLVED | 2.08 | 1.93 | 5.11 | 2.47 | 2.56 |
| 14746118 | CORRECTED | 8.29 | 7.03 | 11.69 | 49.39 | 6.67 |
| 14740801 | UNRESOLVED | 2.14 | 2.02 | 5.82 | 1.38 | 2.53 |
| 14745873 | UNRESOLVED | 2.70 | 2.31 | 5.28 | 2.89 | 1.34 |
| 14746035 | CORRECTED | 2.14 | 1.93 | 16.19 | 9.63 | 2.95 |
| 14746063 | UNRESOLVED | 2.02 | 1.92 | 2.70 | 1.08 | 3.74 |
| 14735176 | UNRESOLVED | 2.02 | 1.91 | 8.67 | 1.24 | 1.29 |
| 14740031 | UNCORRECTED | 4.21 | 3.35 | 11.02 | 2.86 | 25.25 |
| 14744941 | UNRESOLVED | 2.12 | 1.93 | 3.04 | 3.60 | 3.03 |
| 14739506 | UNRESOLVED | 2.02 | 1.93 | 2.59 | 1.06 | 0.93 |

`TRACE_Q75_MIN` is confirmed against the marginal distribution of `trace_q75` over the
whole snapshot before gate 3 is run. That distribution is a histogram of a corridor-free
image statistic. It contains no gate 3 result and no corridor fit, so reading a threshold
off it is a decision about the detector, not about the answer. The histogram is published
in `artifacts/GATE3_POOL.json` by way of every observation's own `trace_q75`, selected or
not, so any reader can recut the pool at another threshold from that file alone.

**This is a researcher degree of freedom and it is named as one.** The mitigation is that
the statistic is blind to the corridor, the calibration set is the 12 rows above, the
threshold is fixed in this document before the gate runs, and the sensitivity of the final
verdict to the threshold is published beside the verdict rather than on request.

## 4. What does not change

Every gate 3 threshold stays exactly where `THRESHOLD_RATIONALE` in
`pipeline/tracetriage/corridor_fit.py` already fixed it:

- the gate bar, 0.70 of reviewed positive examples;
- the verdict rule, an exact one-sided Clopper-Pearson 95% lower bound against that bar,
  not the point estimate;
- the discrimination criterion, a margin of at least **5.0 null standard deviations** over
  200 corridors built by permuting that observation's own Doppler samples in time;
- the reversal control and the four scaled-swing controls, at 0.25x, 0.5x, 2x and 4x;
- the ppm bound on the fitted frequency offset, 50 ppm of the downlink.

The offset fit remains one constant per observation, and the entity grouping for any
interval remains the pass episode.

## 5. What will be published, whatever it says

All of it, in `artifacts/GATE3_RECEIPT.json`, `docs/KILL_GATE.md`, `README.md`,
`FOR_JUDGES.md` and the console:

- Pool B's n, discriminating count, rate, exact 95% lower bound and verdict;
- Pool A's same five numbers beside them, labelled corridor-selected;
- the count of observations examined and the reason each unmeasurable one was dropped;
- the verdict's sensitivity to `TRACE_Q75_MIN`.

**If Pool B's lower bound does not clear 0.70, gate 3 stays `NOT_ESTABLISHED` at the
larger n and this document is the record that the pool was fixed first. If the rate itself
comes in below 0.70, gate 3 is recorded as failed.** The submission publishes the number
either way. A gate that only reports when it passes is not a gate.

## 6. What would invalidate this

Any of: changing a threshold in section 4 after seeing a result; changing a pool rule in
section 3 after seeing a result; dropping an observation from a pool for a reason not
listed in section 3; reporting Pool A's rate as the gate; or running the gate more than
once against the same pool and keeping the better run. `scripts/run_gate3.py` is
deterministic given the snapshot and the pool file, so the last of those is checkable by
re-running it.

## 7. Amendment, committed before the gate was run

The pool was built, its marginal distribution was read as section 3 requires, and the
statistic was found to be degenerating. This section records the correction and the
rebuild. It is committed before `scripts/run_gate3.py` was run against either pool, so
the ordering is checkable in git rather than asserted here, and
`tests/test_gate3_pool.py::test_the_pre_registration_predates_the_gate_receipt_in_git`
fails if it ever stops being true.

**What the distribution showed.** Pool B's `trace_q75` had a median of
4.72 and a 90th percentile of 22,666,664, with a
maximum of 89,000,000. A z-score of 89 million is not a trace. It is a
divisor collapsing: `_normalised_rows` divided by `max(MAD, 1e-6)`, and a row with no
variation at all, a blank or saturated line, has MAD exactly 0. The floor turned the
emptiest row in an image into the largest value in it, so the statistic was inverted
precisely where it degenerated, and a mostly-blank waterfall could outrank a real
detection at 25 sigma by six orders of magnitude.

**Why fixing it is not a change to the rule in section 3.** Section 3 defines the
statistic as each row scored against its own median and MAD. A row whose MAD is zero has
no z-score, not an infinite one, so the 1e-6 floor was never the statistic this document
specified. Rows below the quantisation step of the luminance mean are now dropped from
the percentile instead of floored, and the count is written to each record as
`n_rows_unmeasurable`. An image with no measurable row at all is refused rather than
scored low, because "could not be measured" and "no trace" are different answers and only
one of them is true.

**`TRACE_Q75_MIN` is unchanged at 3.5.** The defect inflates the statistic and only ever
upward, so it could add observations to pool B and never remove one. The bar stays where
section 3 fixed it. Moving it now, having seen a distribution, is the move section 6 says
invalidates this document.

**A second correction, with no effect on membership.** The swing short circuit returned
`status: "ok"` before the image was opened, so `counts.measurable` counted observations
nothing had measured. Those rows now carry `status: "swing_below_floor"`. Pool B's rule
contains the same swing floor, so every one of them was already out at every threshold;
what changes is that the published count means what it says.

**The pool before and after.**

| | first build | after the correction |
|---|---|---|
| examined | 2,750 | 2,750 |
| measurable | 2,463 | 2,412 |
| pool A, corridor-selected | 311 | 308 |
| **pool B, pre-registered** | **321** | **303** |
| in both | 141 | 137 |
| pool B `trace_q75` 90th percentile | 22,666,664 | 10.79 |

No gate 3 result of any kind had been produced from either pool when this was written.
The receipt in the tree at that moment was still the three-observation A3 run from
2026-08-19, which is what `pool.name` records and what the ordering test keys on.

## 8. A third correction, recorded after the gate had been scored, 2026-08-23

This one is a denominator and only a denominator, and it is recorded here because
section 7's table above says 2,750 examined in both of its columns and the pool now says
2,727.

`scripts/build_gate3_pool.py` enumerated `snapshot/pages/*.json`, the raw cursor
responses as fetched. The ingest took whole pages and stopped at its 2,500-waterfall
target part-way through the last one, which had already been written complete, so 23 rows
sit on disk that the dataset never stored. `artifacts/DATASET_MANIFEST.json` freezes 2,727
observations and the pool examined 2,750 of them. The builder now enumerates the manifest,
which is what `pipeline/tracetriage/splits.py` and `scripts/run_precedent_study.py`
already did.

**Membership is unchanged, and that is checkable rather than asserted.** All 23 extra rows
carry `status: "no_waterfall"`, so no image was ever opened for any of them and none could
enter either pool at any threshold. Every retained record is byte-identical to the one the
first build wrote. The counts that move are `examined` 2,750 to 2,727 and
`by_status.no_waterfall` 250 to 227, which is now exactly the manifest's own
`waterfalls_missing`. `measurable` stays 2,412, pool A stays 308, pool B stays 303, `in
both` stays 137, and every verdict tally is unchanged.

**This was written after gate 3 had been scored, so it is worth being exact about what it
could have influenced.** Nothing in section 3's rule reads a count. The bar is
`TRACE_Q75_MIN`, fixed at 3.5 before any of this and unmoved, and the two pools are
per-observation predicates. A correction that removes only rows no predicate can admit
cannot select a pool, and the re-run reproduced every fit.
