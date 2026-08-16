# Kill gate: status board

The plan sets six thresholds that must pass before TraceTriage is worth building. Three were pre-measured on 2026-08-16 before Bob's first task, using live read-only probes. Three remain and can only be settled with the frozen snapshot in hand.

**Thresholds were fixed before any measurement. Do not move one after seeing a result.** If a gate fails, record the failure here with its number and stop. A documented honest failure beats a concealed one.

---

## Status summary

| # | Gate | Threshold | Status |
|---|---|---|---|
| 1 | Dataset volume and entity spread | ≥2,000 mature waterfalls, ≥12 transmitters, ≥30 stations | **PRE-PASSED on feasibility** |
| 2 | Metadata coverage for the corridor | ≥80% of the sample computable | **PRE-PASSED** |
| 3 | Corridor intersects a visible trace | ≥70% of reviewed positives | **OPEN, highest risk** |
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

A 2,000-waterfall snapshot yields roughly 380 decisive positives and 200 decisive negatives. If the evaluation needs 1,000 decisive per class, the snapshot must grow to roughly **10,000 observations and about 17 GB**. Decide the target decisive-negative count *before* starting the download. Report the imbalance; do not silently rebalance it.

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

## Gate 3: corridor intersects a visible trace — OPEN, highest risk

**Threshold:** on a blinded check, the expected corridor intersects a visible target-like trace in at least 70% of reviewed positive examples.

This is the gate the project lives or dies on, and it cannot be pre-measured without the snapshot. Two of its three inputs are already settled, which is why it is now tractable rather than speculative:

**Settled — orbital geometry.** Observation 14513023's own stored TLE plus station coordinates reproduced the pass to **0.18 degrees** against the API's reported `max_altitude` (computed 31.18, reported 31.0). Range rate flips sign exactly at peak elevation. The geometry chain is correct.

**Settled — pixel mapping.** Measured **123.46 Hz/px** on one client and **80.00 Hz/px** on another, read off the rendered axis. The computed 14,631 Hz Doppler swing maps to about **118 px of a 621 px plot**, roughly 19% of the width. The corridor is a visible feature, not a vertical line.

> The trap this avoids: assuming the image spans `samp-rate-rx` (2.5 MHz) compresses that swing to about **5 pixels**. Gate 3 would then fail, and it would fail for a reason that is purely a wrong constant. **If gate 3 fails, re-verify the Hz/px derivation before accepting the failure.**

**Unsettled — is the waterfall already corrected?** `doppler-correction-per-sec` was null while `rigctl-port` was populated, which suggests correction happened externally via rig control. If corrected, model the residual around a near-vertical centre corridor. If uncorrected, the full S-curve is expected. **These two produce completely different overlays and the wrong choice fabricates evidence.** Resolve this first, on known-good passes, before building anything on top.

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
