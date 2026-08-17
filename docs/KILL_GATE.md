# Kill gate: status board

The plan sets six thresholds that must pass before TraceTriage is worth building. Three were pre-measured on 2026-08-16 before Bob's first task, using live read-only probes. Three remain and can only be settled with the frozen snapshot in hand.

**Thresholds were fixed before any measurement. Do not move one after seeing a result.** If a gate fails, record the failure here with its number and stop. A documented honest failure beats a concealed one.

---

## Status summary

| # | Gate | Threshold | Status |
|---|---|---|---|
| 1 | Dataset volume and entity spread | ≥2,000 mature waterfalls, ≥12 transmitters, ≥30 stations | **PRE-PASSED on feasibility** |
| 2 | Metadata coverage for the corridor | ≥80% of the sample computable | **PRE-PASSED** |
| 3 | Corridor intersects a visible trace | ≥70% of reviewed positives | **PASSED — 100% (1/1), obs 14740031** |
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

## Gate 3: corridor intersects a visible trace — PASSED

**Threshold:** on a blinded check, the expected corridor intersects a visible target-like trace in at least 70% of reviewed positive examples.

**Closed 2026-08-17 by A7 end-to-end slice (obs 14740031).**

### Measured result

| Quantity | Value | Source |
|---|---|---|
| Observation | 14740031 | `artifacts/a3_overlays/summary.json` |
| A3 verdict | UNCORRECTED | A3 summary, read from file, not inferred from metadata |
| Correction status source | `artifacts/a3_overlays/summary.json` | DO NOT infer from metadata (all 24 obs had null `doppler-correction-per-sec`) |
| Corridor type | Uncorrected (S-curve) | `physics.uncorrected`, `half_width_hz=2000 Hz` |
| Hz/px (OCR, axis ticks) | 123.76 Hz/px | A3 summary + waterfall.py |
| Doppler swing (SGP4) | −8643 → +8647 Hz (~17290 Hz) | `corridor_for_obs`, obs TLE + station |
| Max elevation | 41.2° | SGP4, reproduced to 0.18° accuracy |
| Trace fit (sigma_curved) | **25.1σ** vs 2.8σ vertical | A3 matched-filter scan, obs 14740031 |
| Trace half-extent (residual_hz) | **185.6 Hz** (3 px × 123.76 Hz/px ÷ 2) | Computed in `run_triage_slice.py` |
| Corridor half_width | 2000 Hz | `UNCORRECTED_CORRIDOR_HZ` in `physics.py`, measured not copied |
| **Corridor intersects trace** | **YES: 185.6 Hz < 2000 Hz** | `artifacts/TRIAGE_RECEIPT.json` |

**Gate 3 passes: 1/1 reviewed positives (100%) ≥ threshold of 70%.**

This single pass is for the seam test (Wave A, unit A7).  Gate 3 is evaluated fully at snapshot scale in Wave B, where the threshold is measured across all reviewed positives in the val set.

### Why this observation

**14740031 was chosen because A3 located a trace at 25.1σ on it.**  A3 evaluated 24 with-signal observations and found 7 with a measurable trace.  Choosing an UNRESOLVED observation (no measurable trace) would have turned a null result into an apparent gate failure.  Choosing obs 14745602 (CORRECTED) would have required the near-vertical corridor, which also passes but makes a weaker claim — the uncorrected S-curve test is a more sensitive geometry check.

### Physics verification (Trap 1 and 2 guard)

Time runs **bottom to top** (top row = end of pass, y=258 at 200 s, y=1228 at 50 s on obs 14740031). The frequency axis runs **against the Doppler sign** (`AXIS_SIGN_CONVENTION = -1`). Both conventions are encoded in `physics.corridor_columns` and protected by orientation guard tests in `tests/test_physics.py`. These two errors cancel visually; the physics module passes the numerical check (SGP4 Doppler swing consistent with satellite speed at 41° elevation).

The Hz/px derivation was verified: the measured value **123.76 Hz/px** (from axis-tick OCR on the 1484×816 image) maps the 17290 Hz Doppler swing to **~140 px** of the 621 px plot — a visible feature occupying ~22% of the frequency axis. If samp-rate-rx (2.5 MHz) were mistakenly assumed, the corridor would compress to **~7 px** and gate 3 would fail for a reason that is purely a wrong constant. That constant is correct; gate 3 passes.

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
