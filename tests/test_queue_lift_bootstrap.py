"""Tests for the grouped lift bootstrap and its consistency guard (unit C2).

These exist because of a defect in C1's bootstrap that no test caught. The
resample deduplicated its own draw:

    pool_set = set(pool)
    drawn_ranked = [oid for oid in ranked_obs_ids if oid in pool_set]

A draw of k episodes with replacement covers only about 63% of them, so the
drawn population fell from 88 rows to roughly 55 while the budget stayed at 50.
Selecting 50 of 55 is not selection, the drawn conflict rate converged on the
population rate, and lift was driven to 1.0 by construction. The published
symptom was an interval lying entirely below its own point estimate on all four
splits (1.60 against [1.00, 1.20] on the chronological split).

The tests below fix the invariant that would have caught it: a point estimate
belongs inside its own interval, and a queue that genuinely selects conflicts
has to show a lift above 1.0 under resampling.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from pipeline.tracetriage import queue as queue_mod
from pipeline.tracetriage.queue import (
    _GATE6_RESULT_KEYS,
    _gate6_result,
    compute_lift,
    unmeasurable_gate6_result,
)

_CONTRACT = (
    Path(__file__).resolve().parents[1] / "contracts" / "queue_receipt.schema.json"
)


# ---------------------------------------------------------------------------
# Synthetic populations
# ---------------------------------------------------------------------------


def _population(
    n_obs: int,
    obs_per_episode: int,
    conflict_ranks: set[int],
) -> tuple[list[int], dict[int, bool], dict[int, str]]:
    """A ranked population with conflicts planted at chosen rank positions.

    ``conflict_ranks`` holds 0-based rank positions, so a caller decides exactly
    how well the queue separates conflicts rather than relying on a seed.
    """
    ranked = list(range(1000, 1000 + n_obs))
    flags = {oid: (i in conflict_ranks) for i, oid in enumerate(ranked)}
    episode_of = {
        oid: f"ep-{i // obs_per_episode:03d}" for i, oid in enumerate(ranked)
    }
    return ranked, flags, episode_of


# ---------------------------------------------------------------------------
# The regression: a selective queue must not have its lift crushed to 1.0
# ---------------------------------------------------------------------------


def test_selective_queue_keeps_its_lift_under_resampling():
    """The exact shape of the C1 defect, at the real corpus's proportions.

    88 observations, one per episode, 20 conflicts all ranked above the budget
    line, budget 50. A perfectly separating queue at 50/88 selectivity has lift
    88/50 = 1.76 whatever the draw, so the interval is tight and above 1.5.

    Under the deduplicating resample this returned roughly [1.00, 1.20]: the
    drawn population shrank to about 55 rows, the budget of 50 covered 91% of
    it, and any draw yielding 50 or fewer distinct rows gave lift exactly 1.0.
    """
    ranked, flags, episode_of = _population(88, 1, set(range(20)))

    result = compute_lift(ranked, flags, episode_of, budget=50, n_boot=2000, seed=7)

    assert result.lift_point == pytest.approx(88 / 50, rel=1e-9)
    lo, hi = result.ci95
    assert lo > 1.5, (
        f"A perfectly separating queue at this budget cannot have a lower bound "
        f"at or below the 1.5 threshold. Got [{lo}, {hi}] against a point of "
        f"{result.lift_point}. A lower bound near 1.0 is the deduplicated-resample "
        f"defect."
    )
    assert result.verdict == "PASSED"
    assert result.direction == "above_threshold"
    assert result.point_in_ci is True
    assert result.consistency_note is None


def test_multi_capture_episodes_resample_with_multiplicity():
    """Four captures per pass, which is where dropping multiplicity hurts most.

    22 episodes of 4 captures. An episode drawn twice must contribute eight rows,
    not four, or the population shrinks and the budget stops being selective.
    """
    ranked, flags, episode_of = _population(88, 4, set(range(20)))

    result = compute_lift(ranked, flags, episode_of, budget=50, n_boot=2000, seed=11)

    assert result.n_groups == 22
    lo, hi = result.ci95
    assert lo <= result.lift_point <= hi
    assert lo > 1.0, (
        f"Interval [{lo}, {hi}] reaches down to no-better-than-random for a queue "
        f"holding every conflict above the budget line."
    )


# ---------------------------------------------------------------------------
# The invariant the defect violated, across many shapes
# ---------------------------------------------------------------------------


#: (label, n_obs, obs_per_episode, conflict ranks, budget). Chosen to cover a
#: separating queue, an anti-selective one, a queue straddling the budget line,
#: sparse conflicts, and multi-capture episodes.
_SHAPES = [
    ("separating", 88, 1, set(range(20)), 50),
    ("anti_selective", 88, 1, set(range(68, 88)), 50),
    ("straddling", 88, 1, set(range(40, 60)), 50),
    ("sparse", 88, 1, {10, 20, 30, 40, 45, 60}, 50),
    ("multi_capture", 88, 4, set(range(20)), 50),
    ("wide_budget", 120, 2, set(range(0, 60, 3)), 30),
    ("narrow_budget", 200, 1, set(range(0, 40)), 10),
]


@pytest.mark.parametrize("label,n_obs,per_ep,conflicts,budget", _SHAPES)
def test_point_estimate_lies_inside_its_own_interval(
    label, n_obs, per_ep, conflicts, budget
):
    """The invariant no C1 test asserted, which is why the defect shipped.

    A point estimate can sit off-centre in a bootstrap interval. It cannot sit
    outside one. When it does, the resample and the point estimate are computing
    different quantities, and the interval describes something nobody asked for.
    """
    ranked, flags, episode_of = _population(n_obs, per_ep, conflicts)
    result = compute_lift(
        ranked, flags, episode_of, budget=budget, n_boot=1500, seed=3
    )

    assert result.verdict != "NOT_MEASURABLE", (
        f"{label}: expected a measurable shape, got {result.not_measurable_reason}"
    )
    lo, hi = result.ci95
    assert result.point_in_ci is True, f"{label}: {result.consistency_note}"
    tol = 1e-9 + 0.05 * (hi - lo)
    assert (lo - tol) <= result.lift_point <= (hi + tol), (
        f"{label}: point {result.lift_point:.4f} outside [{lo:.4f}, {hi:.4f}]"
    )


@pytest.mark.parametrize("label,n_obs,per_ep,conflicts,budget", _SHAPES)
def test_verdict_follows_the_interval_not_the_point_estimate(
    label, n_obs, per_ep, conflicts, budget
):
    """PASSED needs lo above the bar, FAILED needs hi below it, and anything
    containing the bar is NOT_ESTABLISHED whichever side the point falls on."""
    ranked, flags, episode_of = _population(n_obs, per_ep, conflicts)
    result = compute_lift(
        ranked, flags, episode_of, budget=budget, n_boot=1500, seed=3
    )
    lo, hi = result.ci95
    threshold = result.threshold

    if lo > threshold:
        assert result.verdict == "PASSED", label
        assert result.direction == "above_threshold", label
    elif hi < threshold:
        assert result.verdict == "FAILED", label
        assert result.direction == "below_threshold", label
    else:
        assert result.verdict == "NOT_ESTABLISHED", label
        assert result.direction == "spans_threshold", label


def test_the_shape_table_is_not_vacuous():
    """The shapes above have to actually exercise all three verdicts.

    A parametrised test where every case lands on one verdict proves one branch
    and reports as seven. The repo's own rule: a check that examines nothing is
    not a passing check, so count what was examined.
    """
    seen: dict[str, list[str]] = {}
    for label, n_obs, per_ep, conflicts, budget in _SHAPES:
        ranked, flags, episode_of = _population(n_obs, per_ep, conflicts)
        result = compute_lift(
            ranked, flags, episode_of, budget=budget, n_boot=1500, seed=3
        )
        seen.setdefault(result.verdict, []).append(label)

    assert set(seen) >= {"PASSED", "FAILED", "NOT_ESTABLISHED"}, (
        f"The shape table exercises only {sorted(seen)} over {len(_SHAPES)} shapes, "
        f"as {seen}. Every verdict branch needs at least one case or it is untested."
    )


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------


def test_inconsistent_interval_refuses_to_report_a_verdict(monkeypatch):
    """An interval that excludes its own point estimate yields NOT_MEASURABLE.

    Forced with a stubbed percentile, because the fixed code cannot produce this
    shape on real input. That is the point: the guard has to be exercised
    deliberately or it is untested code that only runs during a future defect.
    """
    def _fake_percentile(values, qs):
        # An interval well below any plausible point estimate for this input.
        return np.array([0.10, 0.20, 0.15])

    monkeypatch.setattr(queue_mod.np, "percentile", _fake_percentile)

    ranked, flags, episode_of = _population(88, 1, set(range(20)))
    result = compute_lift(ranked, flags, episode_of, budget=50, n_boot=200, seed=7)

    assert result.verdict == "NOT_MEASURABLE"
    assert result.direction == "inconsistent_interval"
    assert result.point_in_ci is False
    assert result.consistency_note is not None
    # The note has to carry both numbers and the gap, not just an accusation.
    assert "1.7600" in result.consistency_note
    assert "0.1000" in result.consistency_note
    assert "0.2000" in result.consistency_note
    assert result.not_measurable_reason == result.consistency_note


def test_guard_tolerates_a_degenerate_interval():
    """A perfectly separating queue has zero bootstrap spread at fixed
    selectivity, so lo == hi == point. The guard must not call that a defect."""
    ranked, flags, episode_of = _population(88, 1, set(range(20)))
    result = compute_lift(ranked, flags, episode_of, budget=50, n_boot=500, seed=7)
    lo, hi = result.ci95
    assert hi - lo < 1e-9, f"expected a degenerate interval, got [{lo}, {hi}]"
    assert result.point_in_ci is True
    assert result.verdict == "PASSED"


# ---------------------------------------------------------------------------
# Unmeasurable causes carry their own reason
# ---------------------------------------------------------------------------


def test_zero_conflict_population_names_its_own_cause():
    """A split with no conflicts is not a bootstrap that ran short.

    C1 reported both through one hardcoded message, so a population with nothing
    to find was published as a resampling failure.
    """
    ranked, flags, episode_of = _population(40, 1, set())
    result = compute_lift(ranked, flags, episode_of, budget=20, n_boot=500, seed=1)

    assert result.verdict == "NOT_MEASURABLE"
    assert result.direction == "unmeasurable"
    assert math.isnan(result.lift_point)
    assert result.not_measurable_reason is not None
    assert "No actionable conflicts" in result.not_measurable_reason
    assert "40 ranked observations" in result.not_measurable_reason
    assert "resample" not in result.not_measurable_reason.lower()


def test_a_single_conflict_episode_still_measures():
    """Worth pinning, because it was the first guess at an unmeasurable case.

    With one conflict episode among 300, a draw of 300 episodes with replacement
    contains it about 63% of the time, so roughly 63% of resamples produce a
    finite lift. That is plenty for an interval, and the split is measurable with
    a real verdict. Scarcity of conflicts does not by itself make a split
    unmeasurable, and asserting otherwise would have been a fixture that lacks
    the property under test.
    """
    ranked, flags, episode_of = _population(300, 1, {299})
    result = compute_lift(ranked, flags, episode_of, budget=2, n_boot=400, seed=5)

    assert result.verdict == "FAILED", "the only conflict sits far below budget"
    assert 0.5 < result.n_boot_effective / result.n_boot < 0.75, (
        f"expected about 63% survival, got "
        f"{result.n_boot_effective}/{result.n_boot}"
    )


def test_too_few_surviving_resamples_names_its_own_cause():
    """Too few draws to support a percentile interval at all.

    Reached with a resample count small enough that even 63% survival falls
    below the required floor, which is the honest way to exercise this branch:
    the conflict-scarcity route caps out at about 63% survival however few
    conflicts a split has.
    """
    ranked, flags, episode_of = _population(300, 1, {299})
    result = compute_lift(ranked, flags, episode_of, budget=2, n_boot=20, seed=5)

    assert result.verdict == "NOT_MEASURABLE"
    assert result.not_measurable_reason is not None
    assert "resamples produced a finite lift" in result.not_measurable_reason
    assert str(result.n_boot_effective) in result.not_measurable_reason


# ---------------------------------------------------------------------------
# The result constructor and its contract
# ---------------------------------------------------------------------------


def test_result_constructor_rejects_an_unknown_key():
    """A typo has to fail at the call site, not read as an absent measurement.

    With additionalProperties closed, a misspelled key and a key nobody set are
    indistinguishable to a reader of the receipt.
    """
    with pytest.raises(KeyError, match="lift_ci_95"):
        _gate6_result(measurable=True, verdict="PASSED", lift_ci_95=[1.0, 2.0])


def test_result_constructor_emits_every_contract_key():
    result = _gate6_result(measurable=True, verdict="PASSED")
    assert set(result) == set(_GATE6_RESULT_KEYS)


def test_unmeasurable_result_requires_a_reason_with_content():
    for bad in ["", "   ", "n/a", "not measurable"]:
        with pytest.raises(ValueError, match="at least 20 characters"):
            unmeasurable_gate6_result(bad)


def test_result_keys_match_the_ratified_contract_exactly():
    """Drift guard between the constructor and the schema.

    additionalProperties is false on split_gate6_result, so a key added to one
    side and not the other either fails validation at write time or silently
    goes unreported. Neither is acceptable, so the two sets are compared here.
    """
    schema = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    split_result = schema["$defs"]["split_gate6_result"]
    assert split_result["additionalProperties"] is False

    schema_keys = set(split_result["properties"])
    assert schema_keys == set(_GATE6_RESULT_KEYS), (
        f"only in schema: {sorted(schema_keys - set(_GATE6_RESULT_KEYS))}, "
        f"only in code: {sorted(set(_GATE6_RESULT_KEYS) - schema_keys)}"
    )

    for required in split_result["required"]:
        assert required in _GATE6_RESULT_KEYS


# ---------------------------------------------------------------------------
# The ceiling: no draw may be more selective than the measurement it stands for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n_obs", "per_ep", "budget", "n_conflicts"),
    [
        (87, 1, 50, 22),
        (87, 4, 50, 22),
        (95, 1, 50, 39),
        (76, 2, 50, 20),
        (217, 3, 52, 52),
    ],
)
def test_no_resample_beats_the_ceiling_of_the_real_population(
    n_obs, per_ep, budget, n_conflicts
):
    """The upper end of a lift interval cannot exceed what an oracle could score.

    An oracle finds every conflict it has budget for, so on a population of n holding
    c conflicts at budget b the best possible lift is min(b, c) / (b * c / n). Every
    resample is supposed to stand in for that same measurement, which means holding its
    selectivity: a draw allowed to review a smaller share of its own population has a
    higher ceiling than the thing being measured, and the interval inherits it.

    This was ``round(budget / n * drawn_n)``. Rounding down on draws whose product fell
    under .5 made 7.92% of chronological draws exceed 87/50 = 1.740, and the published
    95% upper bound was 93/53 = 1.7547: a bound above the ceiling of the quantity it
    bounded, printed 150 lines from a register entry stating the cap was 1.740.
    """
    ranked, flags, episode_of = _population(n_obs, per_ep, set(range(n_conflicts)))
    result = compute_lift(ranked, flags, episode_of, budget=budget, n_boot=2000, seed=11)
    expected = budget * n_conflicts / n_obs
    ceiling = min(budget, n_conflicts) / expected
    lo, hi = result.ci95
    assert math.isfinite(hi)
    assert hi <= ceiling + 1e-9, (
        f"the 95% upper bound is {hi} on a population whose ceiling is {ceiling}, so at "
        "least one resample was allowed to be more selective than the real measurement"
    )
    assert lo <= result.lift_point <= hi + 1e-9


def test_a_draw_the_size_of_the_population_gets_the_populations_own_budget():
    """The floating-point trap in the ceiling fix, pinned.

    ``math.ceil(budget / n * drawn_n)`` is 51 rather than 50 at n = drawn_n = 88 and
    budget = 50, because 50 / 88 * 88 is 50.000000000000007 in binary floating point. A
    draw identical to the population would then review one row more than the population
    did, which is the same defect as the one being fixed with its sign flipped. The
    integer form cannot do that, and a single-observation-per-episode population draws
    exactly n rows every time.
    """
    ranked, flags, episode_of = _population(88, 1, set(range(20)))
    result = compute_lift(ranked, flags, episode_of, budget=50, n_boot=400, seed=7)
    lo, hi = result.ci95
    # Every draw has drawn_n == 88 and therefore drawn_budget == 50, so every draw
    # reproduces the point estimate exactly and the interval is a point.
    assert hi - lo < 1e-9, f"expected a degenerate interval, got [{lo}, {hi}]"
    assert lo == pytest.approx(result.lift_point)
