# TraceTriage

**A read-only, physics-conditioned review queue for public SatNOGS radio observations.**

Submitted to the AI Builders Challenge with IBM Bob, August 2026 theme: **Advance Space Exploration with AI**.

> **Status: six kill gates asked, two met, three inconclusive, one not run.** Every number in this README is generated from a frozen artifact under `artifacts/` and carries a row in `docs/CLAIM_REGISTER.md`; `tests/test_claim_drift.py` fails if a README number loses its register row. It does not yet compare a quoted value against its artifact, and saying that it did was wrong: mutating the AUC row from 0.875 to 0.999 leaves the suite green. Task D2 closes that, and `tests/test_gate3_bound.py` is the pattern. The three inconclusive gates are reported as NOT_ESTABLISHED rather than rounded into a pass, and the gate that was never run is reported as OPEN rather than omitted. Gate 3 moved from PASSED to NOT_ESTABLISHED on 2026-08-18: every one of its three testable observations discriminates, and three successes in three trials cannot establish the 70 percent rate the gate asked for, because the exact one-sided 95 percent lower bound is 0.368.

---

## Problem statement

The SatNOGS network publishes hundreds of thousands of ground-station radio observations of satellites. Each one produces a waterfall image, a spectrogram of received power over frequency and time. Volunteers review these by eye to decide whether a satellite was actually heard.

There are far more observations than there is human attention. In a 600-observation sample measured on 2026-08-16, **71% carried no decisive human waterfall verdict at all** (426/600 were `unknown`; see `docs/SATNOGS_API_RECON.md` section 5). The backlog is not a storage problem, it is an attention-allocation problem.

A student researcher or volunteer reviewer with a fixed budget of, say, forty minutes faces one concrete decision: **which observations, out of thousands, deserve those forty minutes?**

Reviewing in arrival order spends the budget on the easy and the already-obvious. What is worth a human's time is the subset where the evidence disagrees with itself: the image looks like signal but the orbital geometry says the satellite was below the horizon, or the network label says nothing was heard but a trace sits exactly where physics predicts it.

## Solution description

TraceTriage ranks a **read-only review queue** over observations that already exist. For each one it produces an evidence card showing:

- the waterfall image as published
- the **expected corrected-centre corridor**, the frequency band where a real signal from that satellite should appear, computed from the observation's own stored TLE, station coordinates, timing and receiver metadata
- the detected trace and its residual against that corridor
- artifact-quality checks
- the current SatNOGS label and where that label came from
- a calibrated confidence score, or an explicit **abstention with a reason code** when the evidence is not sufficient

The queue puts disagreement and uncertainty at the top, subject to duplicate control and station/transmitter diversity so a single noisy station cannot flood the budget.

**What this system will never do.** It does not vote on SatNOGS, does not change any public label, does not schedule or control a station, and does not hold a write credential. It does not claim confirmed satellite identity, decoded telemetry, mission success, or official endorsement. Local annotations stay local. The permission boundary is specified in `docs/ACTOR_AND_PERMISSION_CONTRACT.md` and enforced by test, not by convention.

The strongest statement this project is permitted to make, once and only once the evidence exists, is:

> On a frozen chronological sample of public SatNOGS observations, TraceTriage concentrated independently reviewable label or physics conflicts near the top of a fixed review budget while abstaining when the evidence was insufficient.

## AI approach and architecture

The design principle is that **every layer must earn its place through an ablation**. A component that does not improve calibration or queue utility gets deleted, not defended.

```
SatNOGS metadata + waterfalls
        |
   immutable snapshot (hashes, retrieval times, CC BY-SA terms)
        |
   +----+----+----------+-----------+
   |         |          |           |
provenance  image   SGP4 residual  artifact
 + labels   crop      geometry      quality
   |         |          |           |
   |         +----+-----+-----------+
   |              |
   |     small calibrated fusion head
   |              |
   |    calibration -> OOD -> abstention
   |              |
   +---> disagreement reason codes
                  |
          review-value queue
                  |
      per-item evidence receipt -> static console
```

**Step by step, in the order it runs.** The diagram above is the shape; this is the
sequence, and every step writes a file that the next one reads.

1. **Snapshot.** `scripts/recon` pulls SatNOGS observation metadata and waterfall
   images through the public API and freezes them, recording a SHA-256 per file, the
   retrieval time, and the CC BY-SA 4.0 terms. Nothing downstream reaches the network.
   The snapshot id is printed on every page of the console.
2. **Contracts.** Each stage's output schema is written and ratified in `contracts/`
   before the script that writes against it runs. A receipt that violates its contract
   never reaches disk, so a malformed measurement cannot be published and noticed
   later. `schema_version` is pinned by `const`, so a receipt from an older script
   cannot validate as current.
3. **Physics.** `pipeline/tracetriage/physics.py` propagates each pass with SGP4 from
   the TLE that was current at the observation start, computes the Doppler curve from
   range rate, and maps it to pixel columns through the image's own frequency axis.
   Elevation is measured from the WGS-84 geodetic normal.
4. **Splits.** `pipeline/tracetriage/splits.py` builds four holdouts: chronological,
   cold-station, cold-transmitter, and cold on both at once. Each transmitter and each
   orbital revolution is confined to one partition. The combined split excludes rather
   than assigns the rows that would break its own guarantee, and states the count.
   Leakage checks fail the build if any check examined zero records.
5. **Features and the model ladder.** Centre-energy heuristic, then HOG with
   regularised logistic regression, then a corridor matched filter, then a fusion head
   over image plus metadata plus physics. Each rung is compared against the one below
   it with a grouped bootstrap, and a rung that does not improve on the last is
   dropped by the ablation rather than kept.
6. **Calibration and abstention.** Temperature or isotonic fitting on a later time
   period than training, then a selective-prediction curve so a risk ceiling can be
   traded against coverage.
7. **Queue.** `scripts/run_queue.py` ranks the test partition, deduplicates repeated
   observations of one pass episode, and measures lift against random, against
   first-in-first-out, and against an image-only uncertainty ordering at the same
   review budget. Intervals are bootstrapped over pass episodes and over ground
   stations, and the reported interval is the union of the two.
8. **Export and console.** `scripts/build_console_data.py` projects the receipts into
   the four JSON files the site reads, refusing to substitute a null for a field it
   could not find. `apps/web` is a Next.js static export: no server, no database, no
   runtime fetch, no credentials.

**Model ladder**, each rung compared against the last: centre-energy heuristic, HOG plus regularised logistic regression, a frozen MobileNetV3-Small or ResNet18 encoder, a physics-only residual model, then a fusion head over image plus metadata plus physics. Calibration by temperature or isotonic fitting on a later time period. Selective or conformal abstention on top.

**Evaluation is grouped, never random.** Random image splits leak station, satellite and rendering patterns. Holdouts are chronological, cold-station, cold-transmitter, and combined cold-station-and-transmitter, with each transmitter and orbital revolution confined to a single split. Bootstrap intervals are computed over orbital episodes or days, not image rows.

**Labels are silver, not truth.** `waterfall_status` supplies weak supervision. Unknowns stay unlabelled rather than being coerced into a negative class. A blinded local audit with separate artifact, visible-signal and target-consistency axes decides the evaluation target.

**IBM Granite was scoped and not built, and the reason is on the record.** The plan was
a local open Granite model translating a bounded natural-language request into typed
queue filters, with a plain form as the primary control and three conditions for
removal: if it altered a single number, accepted an unsupported field, or failed an
exact semantic test. None of that shipped. The queue's filters are a plain form, which
is what the plan called the primary control. Stating this as delivered would be the
easiest claim in this document to make and the easiest to check, so it is stated as
not delivered instead.

### Selected challenge theme

**Advance Space Exploration with AI.** The theme asks for solutions that turn data-heavy space operations into insight-driven ones and make space more accessible. SatNOGS is open, volunteer-run space infrastructure whose bottleneck is human review capacity. Spending scarce reviewer attention where it changes an outcome is directly that problem.

## How IBM Bob was used

IBM Bob is the primary development tool for this project and builds every load-bearing subsystem: ingestion, physics, model interface, calibration, abstention, ranking, the evidence console, the test suite, and final release acceptance.

Bob's work is recorded, not asserted:

- `docs/BOB_BUILD_LOG.md` maps each Bob task to files, commits, tests, failures and repairs, with actual build credit consumption
- `docs/BOB_HANDOFF.md` carries exact state across trial-account rotations
- `bob_sessions/` holds exported task histories and screenshots with secrets removed
- a final Bob task inspects the release commit, runs the acceptance suite, repairs failures and generates a sign-off receipt

`docs/PRE_BUILD_BASELINE.md` lists exactly what existed before Bob's first task, so the line between scaffolding and Bob's work is auditable rather than implied.

## Measured results

### Established, with receipts

These are generated from frozen artifacts and registered in `docs/CLAIM_REGISTER.md`.

| Metric | Value | Receipt |
|---|---|---|
| Corrected and uncorrected captures both occur | 4 corrected, 3 uncorrected, 17 undecidable, of 24 vetted `with-signal` observations | `artifacts/a3_overlays/summary.json` |
| Metadata cannot reveal correction status | `doppler-correction-per-sec` null and `rigctl-port` `4532` on 24 of 24, in both groups | `artifacts/a3_overlays/summary.json` |
| Strongest corrected match | vertical carrier at 54.2 sigma against 7.3 for the swept curve | `artifacts/a3_overlays/overlay_14746118.png` |
| Strongest uncorrected match | swept curve at 25.1 sigma against 2.8 for the best vertical line | `artifacts/a3_overlays/overlay_14740031.png` |
| Observations with no measurable narrowband trace | 17 of 24 vetted `with-signal`, scoring 0.7 to 3.5 sigma | `artifacts/a3_overlays/summary.json` |
| Pass geometry against reported max_altitude | median 0.22 deg, p99 0.53 deg, 99.5% within 1 deg, 199 of 200. The reference is integer-valued on all 200 records, so this bounds the error near half a degree and resolves nothing finer | `artifacts/PHYSICS_VALIDATION.json` |
| Pass azimuth against reported rise and set azimuth | median 0.27 deg at rise and 0.27 deg at set, max 1.96 deg, 100% within 3 deg, on an unrounded reference. Swapping the atan2 arguments gives 93.9 deg and mirroring the azimuth gives 27.0 deg | `artifacts/PHYSICS_VALIDATION.json` |
| Frequency axis direction, re-measured per observation | the shipped convention wins on all 3 observations where it is measurable; the other 4 are corrected passes whose flat corridor cannot orient an axis at all. It was measured on 2 of the 20 client families in the snapshot, so 1032 of 2750 observations come from a family it was measured on and 1718 inherit it | `artifacts/GATE3_RECEIPT.json` |

The first two are the reason this project exists. A reviewer cannot tell from an
observation record whether its waterfall was Doppler corrected, the two cases
produce completely different expected traces, and the difference is measurable
from the image. That gap between what the record says and what the image
supports is what TraceTriage ranks on.

Full method, margins and open questions: **`docs/DOPPLER_CORRECTION_FINDING.md`**.

### Measured, with receipts

Every cell below is read from a receipt under `artifacts/` and registered in
`docs/CLAIM_REGISTER.md`. Two of the six kill gates came back inconclusive and one was
never run; those rows say so rather than being left out.

| Metric | Value | Receipt |
|---|---|---|
| Brier score, chronological holdout | 0.1292 for the shipped arm, against 0.1495 image-only and 0.2085 for a prior-only floor | `FUSION_RECEIPT.json` |
| AUC, chronological holdout | 0.875, against 0.842 image-only | `FUSION_RECEIPT.json` |
| Calibration slope and intercept | 1.483 and -0.246, ECE 0.0713 | `FUSION_RECEIPT.json` |
| Selective risk near 80% coverage | 0.0857 at 79.5% coverage | `FUSION_RECEIPT.json` |
| Queue lift over random, chronological | 1.582x, 95% CI [1.353, 1.755], **NOT_ESTABLISHED** against a 1.5x threshold | `QUEUE_RECEIPT.json` |
| Queue lift over image-only uncertainty | 1.582x against 1.186x at the same budget | `QUEUE_RECEIPT.json` |
| Queue lift over first-in-first-out | 1.582x against 1.107x | `QUEUE_RECEIPT.json` |
| Cold-station holdout | **PASSED**, 2.253x, 95% CI [1.920, 3.896] | `QUEUE_RECEIPT.json` |
| Cold-transmitter holdout | 1.656x, 95% CI [1.340, 1.913], NOT_ESTABLISHED | `QUEUE_RECEIPT.json` |
| Cold station and transmitter together | 1.292x, 95% CI [1.073, 1.520], NOT_ESTABLISHED | `QUEUE_RECEIPT.json` |
| Physics beats image-only on Brier | **NOT ESTABLISHED**. Margin +0.02079, interval spans zero | `FUSION_RECEIPT.json` gate5 |

### Still unmeasured, and named as such

| Metric | Value | Why |
|---|---|---|
| Human minutes per confirmed finding | `[UNMEASURED]` | Kill gate 4, the blinded human decidability study, was never run. Any number here would be an estimate wearing a measurement's clothes. |
| Blinded human decidability rate | `[UNMEASURED]` | Kill gate 4 again, and it is the gate itself rather than a derived quantity. The console reports gate 4 as OPEN rather than as a value, and the gate tally counts it as not met. |

The queue's headline result is inconclusive, and that is the honest reading:
1.582x is above the 1.5x threshold as a point estimate,
but its interval contains 1.5, so the evidence does not exclude a queue that clears the
bar by nothing. It also sits entirely above 1.0, so the ranking is not nothing either.
The cold-station split, the one where a reviewer meets stations the model never trained
on, does clear the threshold. It does not substitute for the primary split and is not
presented as if it did.

## Setup

Requires Python 3.12 and Node 22. All caches are directed to `D:\dev-cache`, never `C:\`.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev,onnx]"
.venv/Scripts/python.exe -m pytest -q
```

The offline replay path must work with networking disabled. `pytest -m "not network"` is the gate that proves it.

## Prior art and honest scope

SatNOGS already assigns observation and waterfall statuses. Public projects already classify waterfalls with CNNs. STRF-based tooling already extracts Doppler traces. **TraceTriage claims novelty for none of those.**

The contribution it must defend, through six ablations documented in `docs/PRIOR_ART_BASELINES.md`, is the combination of calibrated selective prediction, expected residual geometry fused with image evidence, explicit label-provenance and disagreement analysis, queue ranking by measured review value, per-observation evidence receipts, and evaluation by findings per fixed review budget under temporal and entity holdouts.

If the physics does not improve probability quality, or the queue does not beat random ordering at the same budget, the correct outcome is to stop and document the failure. See `docs/KILL_GATE.md`.

## Licence

Code: MIT, see `LICENSE`.
SatNOGS data and derived artifacts: CC BY-SA 4.0, see `DATA_LICENSE.md`.

Author: Kesav2k04 <kesavk659@gmail.com>
