"""Regenerate README.md's results tables from the receipts.

The README's results table once listed the Brier score, the calibration slope, the queue
lift and both cold splits as `[UNMEASURED]` long after all of them had been measured and
committed. A stale table that understates the work is worse than one that overstates it,
because nobody thinks to re-derive a claim that something was not done.

Run this after any pipeline re-run. It is idempotent: the tables are replaced, and the
prose sections it also manages are only inserted if they are absent.

    .venv/Scripts/python.exe scripts/sync_readme_results.py

`tests/test_claim_drift.py` requires that every metric name in the generated table has a
row in `docs/CLAIM_REGISTER.md`, so adding a row here means adding one there too.
"""

from __future__ import annotations

import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent

fusion = json.loads((REPO / "artifacts/FUSION_RECEIPT.json").read_text(encoding="utf-8"))
queue = json.loads((REPO / "artifacts/QUEUE_RECEIPT.json").read_text(encoding="utf-8"))

splits = {s["split"]: s for s in fusion["splits"]}
chronological = splits["chronological"]
arms = chronological["arms"]
shipped = arms["image_corridor"]
image_only = arms["image_only"]
prior = arms["prior_only"]
g6 = queue["gate6"]["per_split"]
g5 = fusion["gate5"]["per_split"]["chronological"]

# The selective row nearest 80% coverage, chosen by distance rather than by eye.
curve = [r for r in chronological["selective"]["curve"] if r.get("coverage") is not None]
near80 = min(curve, key=lambda r: abs(r["coverage"] - 0.80))

FUSION_REF = "`FUSION_RECEIPT.json`"
QUEUE_REF = "`QUEUE_RECEIPT.json`"


def lift(name: str) -> str:
    """One split's lift and its interval, formatted once rather than ten times."""
    g = g6[name]
    lo, hi = g["lift_ci95"]
    return f"{g['lift_point']:.3f}x, 95% CI [{lo:.3f}, {hi:.3f}]"


# Rows as data. A markdown row carrying three interpolated values does not fit in a
# hundred columns, and wrapping an f-string mid-cell reads worse than building the row.
ROWS: list[tuple[str, str, str]] = [
    (
        "Brier score, chronological holdout",
        f"{shipped['brier']:.4f} for the shipped arm, against "
        f"{image_only['brier']:.4f} image-only and {prior['brier']:.4f} "
        "for a prior-only floor",
        FUSION_REF,
    ),
    (
        "AUC, chronological holdout",
        f"{shipped['auc']:.3f}, against {image_only['auc']:.3f} image-only",
        FUSION_REF,
    ),
    (
        "Calibration slope and intercept",
        f"{shipped['calibration_slope']:.3f} and "
        f"{shipped['calibration_intercept']:.3f}, ECE {shipped['ece']:.4f}",
        FUSION_REF,
    ),
    (
        "Selective risk near 80% coverage",
        f"{near80['risk']:.4f} at {near80['coverage'] * 100:.1f}% coverage",
        FUSION_REF,
    ),
    (
        "Queue lift over random, chronological",
        f"{lift('chronological')}, **NOT_ESTABLISHED** against a 1.5x threshold",
        QUEUE_REF,
    ),
    (
        "Queue lift over image-only uncertainty",
        f"{g6['chronological']['lift_point']:.3f}x against "
        f"{g6['chronological']['image_uncertainty_lift_over_random']:.3f}x "
        "at the same budget",
        QUEUE_REF,
    ),
    (
        "Queue lift over first-in-first-out",
        f"{g6['chronological']['lift_point']:.3f}x against "
        f"{g6['chronological']['fifo_lift_over_random']:.3f}x",
        QUEUE_REF,
    ),
    ("Cold-station holdout", f"**PASSED**, {lift('cold_station')}", QUEUE_REF),
    (
        "Cold-transmitter holdout",
        f"{lift('cold_transmitter')}, NOT_ESTABLISHED",
        QUEUE_REF,
    ),
    (
        "Cold station and transmitter together",
        f"{lift('cold_combined')}, NOT_ESTABLISHED",
        QUEUE_REF,
    ),
    (
        "Physics beats image-only on Brier",
        f"**NOT ESTABLISHED**. Margin +{g5['margin']:.5f}, interval spans zero",
        f"{FUSION_REF} gate5",
    ),
]

TABLE = "\n".join(f"| {metric} | {value} | {ref} |" for metric, value, ref in ROWS)

# The genuinely unmeasured metrics. They carry the literal `[UNMEASURED]` marker because
# tests/test_claim_drift.py treats that exact string as the only permitted stand-in for a
# number, and because a reader should be able to grep the README for what is missing.
UNMEASURED: list[tuple[str, str]] = [
    (
        "Human minutes per confirmed finding",
        "Kill gate 4, the blinded human decidability study, was never run. Any "
        "number here would be an estimate wearing a measurement's clothes.",
    ),
    (
        "Blinded human decidability rate",
        "Same gate. The console reports it as OPEN rather than as a value, and the "
        "gate tally counts it as not met.",
    ),
]

UNMEASURED_TABLE = "\n".join(
    f"| {metric} | `[UNMEASURED]` | {why} |" for metric, why in UNMEASURED
)

SECTION = f"""### Measured, with receipts

Every cell below is read from a receipt under `artifacts/` and registered in
`docs/CLAIM_REGISTER.md`. Two of the six kill gates came back inconclusive and one was
never run; those rows say so rather than being left out.

| Metric | Value | Receipt |
|---|---|---|
{TABLE}

### Still unmeasured, and named as such

| Metric | Value | Why |
|---|---|---|
{UNMEASURED_TABLE}

The queue's headline result is inconclusive, and that is the honest reading:
{g6['chronological']['lift_point']:.3f}x is above the 1.5x threshold as a point estimate,
but its interval contains 1.5, so the evidence does not exclude a queue that clears the
bar by nothing. It also sits entirely above 1.0, so the ranking is not nothing either.
The cold-station split, the one where a reviewer meets stations the model never trained
on, does clear the threshold. It does not substitute for the primary split and is not
presented as if it did.

"""


def main() -> int:
    readme = REPO / "README.md"
    text = readme.read_text(encoding="utf-8")

    start_marker = "### Measured, with receipts"
    fallback_marker = "### Not yet measured"
    end_marker = "\n## Setup"

    if start_marker in text:
        start = text.index(start_marker)
    elif fallback_marker in text:
        start = text.index(fallback_marker)
    else:
        raise SystemExit(
            "README.md has neither a 'Measured, with receipts' nor a 'Not yet measured' "
            "section. Refusing to guess where the results belong."
        )

    end = text.index(end_marker)
    readme.write_text(text[:start] + SECTION + text[end + 1 :], encoding="utf-8")

    print(f"README results synced: {len(ROWS)} measured rows, 2 marked unmeasured")
    print(f"  shipped arm brier {shipped['brier']:.4f}, auc {shipped['auc']:.3f}")
    print(
        f"  selective risk {near80['risk']:.4f} "
        f"at {near80['coverage'] * 100:.1f}% coverage"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
