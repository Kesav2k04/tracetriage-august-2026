"""The axis reader audit, and what it is allowed to conclude.

`artifacts/AXIS_READER_AUDIT.json` exists because two surfaces of this project can read a
different frequency axis off the same image. Every number in `artifacts/GATE3_POOL.json` came
through easyocr, which `parse_waterfall` still defaults to; the deployed endpoint passes
`"auto"` and so prefers the template matcher. On observation 14745990 they differ by 9.35x and
the mode verdict flips across the 8 sigma floor.

These tests do not assert that the audit's conclusion is favourable. They assert that its
arithmetic is reproducible, that its baseline is the gate's own published figure rather than a
recomputation that happens to look like it, and that a scenario which failed the threshold
would be recorded as failing rather than dropped. A test that required the pleasant answer
would be the same defect one level up: it would pass on an audit that had stopped measuring.

The expensive half of the audit needs the stage-1 snapshot, because it re-reads 2,424 images.
Everything here runs offline against the committed artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
AUDIT = REPO / "artifacts" / "AXIS_READER_AUDIT.json"
RECEIPT = REPO / "artifacts" / "GATE3_RECEIPT.json"


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT.is_file(), (
        "artifacts/AXIS_READER_AUDIT.json is missing. Rebuild it with "
        "scripts/audit_pool_axes.py and the snapshot configured."
    )
    return json.loads(AUDIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_listed_disagreements_are_the_counted_ones(audit: dict) -> None:
    """A summary that outruns its own list is the failure this catches."""
    listed = audit["disagreements"]
    assert len(listed) == audit["counts"]["disagree"], (
        f"the summary says {audit['counts']['disagree']} disagreements and lists {len(listed)}"
    )
    ids = [d["obs_id"] for d in listed]
    assert len(set(ids)) == len(ids), "an observation is listed twice"
    total = (
        audit["counts"]["agree"]
        + audit["counts"]["disagree"]
        + audit["counts"]["could_not_read"]
    )
    assert total == audit["counts"]["rows_with_an_axis"], (
        f"the three outcomes sum to {total} over {audit['counts']['rows_with_an_axis']} rows, "
        "so a row was counted twice or not at all"
    )


def test_every_listed_row_is_outside_the_tolerance(audit: dict) -> None:
    """The ratio is recomputed from the two readings, so a hand-edited row is caught."""
    tolerance = audit["tolerance"]
    assert 0 < tolerance < 0.5, "the tolerance is not a fraction"
    for row in audit["disagreements"]:
        ratio = row["glyph_hz_per_px"] / row["pool_hz_per_px"]
        assert ratio == pytest.approx(row["ratio"], rel=1e-12), (
            f"observation {row['obs_id']}'s stored ratio is not its two readings' quotient"
        )
        assert abs(ratio - 1.0) > tolerance, (
            f"observation {row['obs_id']} is inside the tolerance and should not be listed"
        )


def test_a_reading_inside_the_tolerance_would_not_be_listed(audit: dict) -> None:
    """A self-proof of the test above, so it is not green because it asks nothing."""
    tolerance = audit["tolerance"]
    same_axis = {"obs_id": 0, "pool_hz_per_px": 123.7624, "glyph_hz_per_px": 123.7700}
    ratio = same_axis["glyph_hz_per_px"] / same_axis["pool_hz_per_px"]
    assert abs(ratio - 1.0) <= tolerance, (
        "a sub-pixel difference between the two readers must count as the same axis, or every "
        "row in the pool would be a disagreement"
    )


def test_the_baseline_is_the_gate_receipts_own_published_figure(
    audit: dict, receipt: dict
) -> None:
    """The comparison is only meaningful against the number the gate published."""
    effect = audit["gate3_effect"]
    assert effect["published_rate"] == receipt["discriminating_rate"]
    assert effect["published_rate_lower_bound_95"] == receipt["rate_lower_bound_95"]
    assert effect["threshold"] == receipt["threshold"]
    published = effect["scenarios"]["as_published"]
    assert published["scored"] == receipt["observations_scored"]
    assert published["rate"] == pytest.approx(receipt["discriminating_rate"], rel=1e-12)
    assert published["rate_lower_bound_95"] == pytest.approx(
        receipt["rate_lower_bound_95"], rel=1e-9
    )


def test_the_disputed_scored_rows_are_the_ones_the_receipt_scores(
    audit: dict, receipt: dict
) -> None:
    """The overlap is recomputed here, by a second route, from the receipt's own rows."""
    effect = audit["gate3_effect"]
    disputed = {d["obs_id"] for d in audit["disagreements"]}
    scored = [
        row
        for row in receipt["observations"]
        if (row.get("null_calibration") or {}).get("discriminates") is not None
    ]
    hit = [row for row in scored if row["obs_id"] in disputed]
    assert sorted(row["obs_id"] for row in hit) == effect["disputed_scored_obs_ids"]
    assert len(hit) == effect["scored_rows_with_a_disputed_axis"]
    discriminating = [row for row in hit if row["null_calibration"]["discriminates"]]
    assert len(discriminating) == effect["of_those_currently_discriminating"]


def test_each_scenario_records_whether_it_clears_rather_than_that_it_does(
    audit: dict,
) -> None:
    """Consistency, not a favourable answer.

    A scenario that fell below the threshold has to be recorded as falling below it. Asserting
    that all three clear would turn this file into a test that only passes while the result is
    convenient, and would go green on an audit that had stopped looking.
    """
    effect = audit["gate3_effect"]
    threshold = effect["threshold"]
    for name, scenario in effect["scenarios"].items():
        rate = scenario["discriminating"] / scenario["scored"]
        assert rate == pytest.approx(scenario["rate"], rel=1e-12), f"{name}'s rate is not k/n"
        assert scenario["clears_threshold"] is (
            scenario["rate_lower_bound_95"] >= threshold
        ), f"{name} records clears_threshold against a bound that says otherwise"
    assert set(effect["scenarios"]) == {
        "as_published",
        "disputed_rows_dropped",
        "disputed_rows_counted_as_misses",
    }, "the scenario set changed, so the reading beside it may no longer describe it"


def test_the_worked_examples_arithmetic_holds(audit: dict) -> None:
    """The claim that settles which reader is right is the label span, so check it."""
    example = audit["worked_example"]
    labels = example["tick_labels_khz"]
    span_hz = (max(labels) - min(labels)) * 1000
    width = example["image_width_px"]
    glyph_px = span_hz / example["glyph_hz_per_px"]
    pool_px = span_hz / example["pool_hz_per_px"]
    assert 0.4 * width < glyph_px < width, (
        f"the model-free reading puts the labelled span at {glyph_px:.0f} px of {width}, which "
        "is not what an axis labelled across the plot looks like"
    )
    assert pool_px < 0.15 * width, (
        f"the committed reading puts the same span at {pool_px:.0f} px of {width}, and the "
        "argument in the artifact depends on that being implausible"
    )
