# TraceTriage

**A read-only, physics-conditioned review queue for public SatNOGS radio observations.**

Submitted to the AI Builders Challenge with IBM Bob, August 2026 theme: **Advance Space Exploration with AI**.

> **Status: pre-kill-gate scaffold.** No measured result exists yet. Every number in this README is a placeholder marked `[UNMEASURED]` and must be replaced by a value generated from a frozen artifact in `artifacts/`, never typed by hand. `tests/test_claim_drift.py` is designed to fail if a README number stops matching its receipt. Do not remove a marker without adding the receipt that replaces it.

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

**Model ladder**, each rung compared against the last: centre-energy heuristic, HOG plus regularised logistic regression, a frozen MobileNetV3-Small or ResNet18 encoder, a physics-only residual model, then a fusion head over image plus metadata plus physics. Calibration by temperature or isotonic fitting on a later time period. Selective or conformal abstention on top.

**Evaluation is grouped, never random.** Random image splits leak station, satellite and rendering patterns. Holdouts are chronological, cold-station, cold-transmitter, and combined cold-station-and-transmitter, with each transmitter and orbital revolution confined to a single split. Bootstrap intervals are computed over orbital episodes or days, not image rows.

**Labels are silver, not truth.** `waterfall_status` supplies weak supervision. Unknowns stay unlabelled rather than being coerced into a negative class. A blinded local audit with separate artifact, visible-signal and target-consistency axes decides the evaluation target.

**IBM Granite is conditional and optional.** A local open Granite model may translate a bounded natural-language request into typed queue filters. A plain form remains the primary control. Granite is removed if it alters a single number, accepts an unsupported field, or fails an exact semantic test.

### Selected challenge theme

**Advance Space Exploration with AI.** The theme asks for solutions that turn data-heavy space operations into insight-driven ones and make space more accessible. SatNOGS is open, volunteer-run space infrastructure whose bottleneck is human review capacity. Spending scarce reviewer attention where it changes an outcome is directly that problem.

## How IBM Bob was used

IBM Bob is the primary development tool for this project and builds every load-bearing subsystem: ingestion, physics, model interface, calibration, abstention, ranking, the evidence console, the test suite, and final release acceptance.

Bob's work is recorded, not asserted:

- `docs/BOB_BUILD_LOG.md` maps each Bob task to files, commits, tests, failures and repairs, with actual Bobcoin consumption
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
| Pass geometry against reported max_altitude | median 0.21 deg, p99 0.61 deg, 99.5% within 1 deg, 199 of 200 | `artifacts/PHYSICS_VALIDATION.json` |

The first two are the reason this project exists. A reviewer cannot tell from an
observation record whether its waterfall was Doppler corrected, the two cases
produce completely different expected traces, and the difference is measurable
from the image. That gap between what the record says and what the image
supports is what TraceTriage ranks on.

Full method, margins and open questions: **`docs/DOPPLER_CORRECTION_FINDING.md`**.

### Not yet measured

| Metric | Value | Receipt |
|---|---|---|
| Brier score, chronological holdout | `[UNMEASURED]` | pending |
| Calibration slope / intercept | `[UNMEASURED]` | pending |
| Queue lift over random, at fixed budget | `[UNMEASURED]` | pending |
| Queue lift over image-only uncertainty | `[UNMEASURED]` | pending |
| Selective risk at 80% coverage | `[UNMEASURED]` | pending |
| Cold-station holdout result | `[UNMEASURED]` | pending |
| Cold-transmitter holdout result | `[UNMEASURED]` | pending |
| Human minutes per confirmed finding | `[UNMEASURED]` | pending |

Nothing above may be filled in from a training run alone. Each cell needs a generated artifact under `artifacts/` and a row in `docs/CLAIM_REGISTER.md`.

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
