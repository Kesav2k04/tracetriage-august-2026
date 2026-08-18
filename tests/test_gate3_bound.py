"""Gate 3's threshold must be read off an interval, not off a point estimate.

The gate asks whether the corridor intersects a visible trace in at least 70 percent
of reviewed positives. It was answered with 3 successes in 3 trials, a rate of 1.0,
and `1.0 >= 0.70` is True, so the receipt said PASSED. The identical comparison would
have passed 1 of 1. `docs/KILL_GATE.md` had already made that exact argument when the
earlier one-observation version of this gate was withdrawn, noting that "a 70% rate
cannot be measured on one observation in any case", and the three-observation version
was then accepted on the same logic twenty-eight lines later in the same file.

These tests pin the bound and the verdict vocabulary. Reverting
`scripts/run_gate3.py` to compare `hit_rate >= threshold` fails
`test_three_of_three_does_not_establish_seventy_percent` and
`test_receipt_verdict_is_not_established`.
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
def test_receipt_verdict_is_not_established():
    """The published verdict must match what the bound supports."""
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["verdict"] == "NOT_ESTABLISHED", (
        "Gate 3's verdict must follow its lower bound. Got "
        f"{receipt['verdict']!r} with rate_lower_bound_95="
        f"{receipt.get('rate_lower_bound_95')!r} against threshold "
        f"{receipt.get('threshold')!r}."
    )


@pytest.mark.skipif(not RECEIPT.exists(), reason="gate 3 receipt not generated")
def test_receipt_records_both_the_point_estimate_and_the_bound():
    """Publishing only the bound would hide a strong per-observation result."""
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for key in (
        "discriminating_rate",
        "rate_lower_bound_95",
        "clears_point_estimate",
        "clears_threshold",
    ):
        assert key in receipt, f"receipt is missing {key}"

    assert receipt["discriminating_rate"] == 1.0
    assert receipt["clears_point_estimate"] is True
    assert receipt["clears_threshold"] is False
    assert receipt["rate_lower_bound_95"] == pytest.approx(0.3684, abs=5e-5)

    grouping = receipt["entity_grouping"]
    assert grouping["grouped_rate_lower_bound_95"] == pytest.approx(0.2236, abs=5e-5)
    assert grouping["grouped_clears_threshold"] is False


@pytest.mark.skipif(not RECEIPT.exists(), reason="gate 3 receipt not generated")
def test_every_scored_observation_still_discriminates():
    """The correction is to the rate claim, not to the per-observation evidence.

    Each observation still beats 200 scrambled corridors with none reaching it and
    beats all four scaled-swing controls. Losing that in the rewrite would be a
    worse error than the one being fixed.
    """
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    scored = [
        o for o in receipt["observations"]
        if o["null_calibration"]["p_value"] is not None
    ]
    assert len(scored) == 3
    for obs in scored:
        cal = obs["null_calibration"]
        assert cal["discriminates"] is True, obs["obs_id"]
        assert cal["n_at_least"] == 0, obs["obs_id"]
        assert cal["p_value"] <= 0.05, obs["obs_id"]
