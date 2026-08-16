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
| *empty* | | | | | |

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
