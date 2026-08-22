"""Gate 3's threshold must be read off an interval, not off a point estimate.

The gate asks whether the corridor intersects a visible trace in at least 70 percent
of reviewed positives. It was answered with 3 successes in 3 trials, a rate of 1.0,
and `1.0 >= 0.70` is True, so the receipt said PASSED. The identical comparison would
have passed 1 of 1. `docs/KILL_GATE.md` had already made that exact argument when the
earlier one-observation version of this gate was withdrawn, noting that "a 70% rate
cannot be measured on one observation in any case", and the three-observation version
was then accepted on the same logic twenty-eight lines later in the same file.

These tests pin the rule and not the answer. The arithmetic ones fix the bound at sample
sizes that cannot change; the receipt ones recompute the verdict from the receipt's own
counts, so a larger pool moves every number and this file still fails the moment a verdict
stops following its bound. Reverting `scripts/run_gate3.py` to compare
`hit_rate >= threshold` fails `test_three_of_three_does_not_establish_seventy_percent` and
`test_the_receipt_verdict_follows_its_own_bound`.

An earlier version asserted `verdict == "NOT_ESTABLISHED"` and `len(scored) == 3`. Both
were true and neither was a check: the first would have had to be edited by whoever
changed the verdict, and the second failed on a larger pool for the one reason that is not
a defect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_gate3 import rate_lower_bound

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "GATE3_RECEIPT.json"


def test_three_of_three_does_not_establish_seventy_percent():
    """The whole finding, in one assertion."""
    bound = rate_lower_bound(3, 3)
    assert bound is not None
    # Exact one-sided Clopper-Pearson for k = n is alpha ** (1/n).
    assert bound == pytest.approx(0.05 ** (1 / 3), abs=1e-12)
    assert bound == pytest.approx(0.3684, abs=5e-5)
    assert bound < 0.70, (
        "3 of 3 successes cannot establish a rate of 0.70: the 95 percent lower "
        f"bound is {bound:.4f}, roughly half the threshold."
    )


def test_two_of_two_is_weaker_still():
    """The grouped rate, which is the one the plan's grouping rule actually asks for."""
    bound = rate_lower_bound(2, 2)
    assert bound is not None
    assert bound == pytest.approx(0.05 ** (1 / 2), abs=1e-12)
    assert bound < 0.70


def test_closed_form_agrees_with_the_beta_quantile():
    """k == n takes a closed form; the general branch must not disagree with it."""
    from scipy.stats import beta

    for n in (1, 2, 3, 5, 12, 40):
        closed = 0.05 ** (1 / n)
        # The Beta quantile at k = n reduces to the same value in the limit b -> 1.
        general = float(beta.ppf(0.05, n, 1))
        assert closed == pytest.approx(general, rel=1e-9), n


def test_bound_rises_with_sample_size_at_a_perfect_rate():
    """A perfect rate says more the more trials it survived."""
    bounds = [rate_lower_bound(n, n) for n in (1, 2, 3, 10, 100)]
    assert all(b is not None for b in bounds)
    assert bounds == sorted(bounds), bounds
    # 3 of 3 cannot clear 0.70 but 9 of 9 can, which is the sample size this gate
    # would need at a perfect rate. It is a useful number to have written down.
    assert rate_lower_bound(3, 3) < 0.70 <= rate_lower_bound(9, 9)


def test_bound_is_none_or_zero_on_degenerate_input():
    assert rate_lower_bound(0, 0) is None
    assert rate_lower_bound(-1, 3) is None
    assert rate_lower_bound(4, 3) is None
    assert rate_lower_bound(0, 3) == 0.0


def test_partial_success_uses_the_general_branch():
    """A rate below 1.0 must still produce a bound below the point estimate."""
    bound = rate_lower_bound(7, 10)
    assert bound is not None
    assert 0.0 < bound < 0.70


@pytest.mark.skipif(not RECEIPT.exists(), reason="gate 3 receipt not generated")
def test_the_receipt_verdict_follows_its_own_bound():
    """The verdict is derived here rather than named.

    This asserted ``verdict == "NOT_ESTABLISHED"`` while n was 3 and no larger pool
    existed. That is a test of one run's answer rather than of the rule the run has to
    obey, and it would have had to be edited by whoever changed the answer, which is the
    worst moment to be editing the test that checks it. The rule is recomputed from the
    receipt's own counts instead: whichever verdict word is published, the bound has to
    support it.
    """
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    scored = receipt["observations_scored"]
    rate = receipt["discriminating_rate"]
    threshold = receipt["threshold"]

    if not scored:
        assert receipt["verdict"] == "UNMEASURABLE"
        return

    discriminating = round(rate * scored)
    bound = rate_lower_bound(discriminating, scored)
    assert bound == pytest.approx(receipt["rate_lower_bound_95"], abs=5e-5), (
        "the published bound is not the one this receipt's own counts produce"
    )

    clears = bound >= threshold
    assert receipt["clears_threshold"] is clears
    assert receipt["clears_point_estimate"] is (rate >= threshold)

    grouping = receipt["entity_grouping"]
    if clears and grouping["grouped_clears_threshold"]:
        expected = "PASSED"
    elif clears:
        expected = "PASSED_UNGROUPED_ONLY"
    elif rate >= threshold or grouping["grouped_clears_point_estimate"]:
        # Every observation behaved and the sample cannot resolve the bar. Gates 5 and 6
        # report that as NOT_ESTABLISHED, and this gate uses their word, not FAILED.
        expected = "NOT_ESTABLISHED"
    else:
        expected = "FAILED"
    assert receipt["verdict"] == expected, (
        f"verdict {receipt['verdict']!r} with rate {rate}, bound {bound:.4f} and "
        f"threshold {threshold} should read {expected!r}"
    )


@pytest.mark.skipif(not RECEIPT.exists(), reason="gate 3 receipt not generated")
def test_the_receipt_records_both_the_point_estimate_and_the_bound():
    """Publishing only the bound would hide a strong per-observation result.

    The grouped figures are recomputed from the grouped counts for the same reason the
    ungrouped ones are: a bound nobody re-derives is a number, not a check.
    """
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for key in (
        "discriminating_rate",
        "rate_lower_bound_95",
        "clears_point_estimate",
        "clears_threshold",
    ):
        assert key in receipt, f"receipt is missing {key}"

    grouping = receipt["entity_grouping"]
    groups = grouping["groups_scored"]
    if groups:
        flags = round(grouping["grouped_discriminating_rate"] * groups)
        assert grouping["grouped_rate_lower_bound_95"] == pytest.approx(
            rate_lower_bound(flags, groups), abs=5e-5
        )
        assert grouping["grouped_clears_threshold"] is (
            grouping["grouped_rate_lower_bound_95"] >= receipt["threshold"]
        )


@pytest.mark.skipif(not RECEIPT.exists(), reason="gate 3 receipt not generated")
def test_the_per_observation_evidence_is_reported_for_every_scored_observation():
    """The per-observation invariants, over whatever the pool turned out to be.

    This asserted ``len(scored) == 3``, which stopped being a check the moment the pool
    could grow: it would fail on a larger run for the one reason that is not a defect.
    What has to hold is that the receipt reports the same quantities for every
    observation it scored, that the count it publishes is the count it scored, and that
    anything it calls discriminating cleared the pre-registered margin floor.
    """
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    scored = [
        o for o in receipt["observations"]
        if o.get("null_calibration", {}).get("p_value") is not None
    ]
    assert len(scored) == receipt["observations_scored"], (
        "the receipt's scored count is not the number of observations it scored"
    )
    if not scored:
        return

    discriminating = [o for o in scored if o["null_calibration"]["discriminates"]]
    assert receipt["discriminating_rate"] == pytest.approx(
        len(discriminating) / len(scored)
    )
    for obs in scored:
        cal = obs["null_calibration"]
        for key in ("discriminates", "n_at_least", "p_value", "margin_in_null_sd",
            "beats_reversed", "beats_scaled_swing"):
            assert key in cal, f"obs {obs['obs_id']} is missing {key}"
        if cal["discriminates"]:
            assert cal["margin_in_null_sd"] >= 5.0, obs["obs_id"]
            assert cal["beats_reversed"] is True, obs["obs_id"]
            assert cal["beats_scaled_swing"] is True, obs["obs_id"]
            assert cal["p_value"] <= 0.05, obs["obs_id"]


@pytest.mark.skipif(not RECEIPT.exists(), reason="gate 3 receipt not generated")
def test_the_receipt_says_which_rule_chose_its_observations():
    """A rate means a different thing under a corridor-selected pool.

    ``docs/E16_PREREGISTRATION.md`` fixes two pools and says only one decides the gate. A
    receipt that did not name its pool would let the corridor-selected rate be read as
    the gate's, which is the exact substitution the pre-registration exists to prevent.
    """
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    pool = receipt.get("pool")
    if pool is None:
        # The n = 3 receipt predates the field, and is A3's pool by construction.
        pytest.skip("this receipt predates the pool field")
    assert pool["name"] in ("a3", "pool_a", "pool_b")
    assert pool["n_selected"] == receipt["observations_decisive"]
    if pool["name"] == "pool_a":
        raise AssertionError(
            "the published gate 3 receipt was built from the corridor-selected pool, "
            "which docs/E16_PREREGISTRATION.md says does not decide the gate"
        )
