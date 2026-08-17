# Claim register

Every number that appears in the README, in the video, on a chart, or in the
submission text maps to a row here, and every row points at a generated artifact.

A number with no row is a defect. `tests/test_claim_drift.py` enforces this, and
task D2 extends it to compare each quoted value against its artifact so that
updating the README without regenerating the receipt fails CI.

## Rules

1. **Numbers are generated, never typed.** If it was typed, it is wrong until proven.
2. Every row cites an artifact path and the commit that produced it.
3. A claim whose artifact changed but whose text did not is a **drift failure**, not a rounding difference.
4. Video numbers are registered too. The video is public and unversioned; drift there is not recoverable after submission.
5. Claims about what the system *cannot* do belong here as well, and are checked the same way.

## Register

| Claim | Value | Where it appears | Artifact | Commit | Verified |
|---|---|---|---|---|---|
| Corrected and uncorrected captures both occur | 4 corrected, 3 uncorrected of 24 | A3 finding, README, video | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Metadata cannot reveal correction status | `doppler-correction-per-sec` null and `rigctl-port` 4532 on 24/24 | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Strongest uncorrected match | 25.1 sigma curved against 2.8 sigma vertical, obs 14740031 | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Strongest corrected match | 54.2 sigma vertical against 7.3 sigma curved, obs 14746118 | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Observations with no measurable narrowband trace | 17 of 24 vetted with-signal | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Pass geometry against reported max_altitude | median 0.21 deg, p99 0.61 deg, 99.5% within 1 deg, 199 of 200 | A4 finding, README, video | `artifacts/PHYSICS_VALIDATION.json` | `0f21ce7` | 2026-08-17 |
| Gate 6 point lift (chronological) | 1.600x over random at budget 50 | KILL_GATE.md, gate 6 section | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Gate 6 95% CI (chronological) | [1.354, 1.760], contains 1.5 | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Gate 6 bootstrap median (chronological) | 1.592 over 4000 of 4000 surviving resamples | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Gate 6 cold_station point lift | 3.005x [2.493, 3.454] (PASSED), 217 decisive | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| n_queue_conflicts at budget 50 (chronological) | 20 of 50, against 12.5 expected by random | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Every ordering's lift over random (chronological) | queue 1.600, FIFO 1.120, image uncertainty 1.120, physics-only 1.040 | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Superseded: gate 6 CI published in C1 | [1.00, 1.20] was a resample artefact, not a measurement | KILL_GATE.md failure log | reproduced at [1.0000, 1.2200] from the old loop | C2 | 2026-08-18 |

## Pre-registered limits

These are stated before results exist, so they cannot be quietly relaxed once
numbers arrive:

- No generalisation claim survives a failed cold-entity result.
- Queue lift is only claimed when the grouped 95% interval sits above random.
- "Target-consistent trace" is never restated as confirmed identity, decoded
  telemetry, mission success, or a corrected community label.
- Physics is claimed to help only if it lowers Brier score against a **calibrated**
  image-only baseline, not an uncalibrated one.
- Any metric measured on a single window is reported as such, never as a
  population constant.
