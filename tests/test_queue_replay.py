"""Active-selection replay against every baseline, paired within each draw (C4).

Gate 6 asks only whether the queue beats random. A queue that beats random and
loses to FIFO has not earned a reviewer's attention, because FIFO is what a
reviewer already does. So every ordering is replayed over the same resampled
populations and the comparisons are paired.

Three properties are pinned here, each because getting it wrong produces a
plausible-looking number.

Pairing: one draw produces one population and every ordering is scored on it
before the next draw. Drawing separately per ordering compares two orderings
across two populations and attributes the difference between the populations to
the difference between the orderings.

Re-sorting inside the draw: an ordering's top-k in a resampled population is not
its top-k in the original, because the draw may not contain those rows.

A representable loss: ``baseline_better`` has to be reachable. A one-sided
survival test is what left an ablation rule's DROP branch as dead code in Wave B.
"""

from __future__ import annotations

import pytest

from pipeline.tracetriage.queue import combine_replays, compare_orderings


def _population(n: int, conflict_ranks: set[int], per_group: int = 1):
    """Observations 1000..1000+n with conflicts at chosen positions of the queue."""
    ids = list(range(1000, 1000 + n))
    flags = {oid: (i in conflict_ranks) for i, oid in enumerate(ids)}
    group_of = {oid: f"g{i // per_group:03d}" for i, oid in enumerate(ids)}
    return ids, flags, group_of


# ---------------------------------------------------------------------------
# Direction, in all three states
# ---------------------------------------------------------------------------


def test_a_better_queue_reads_as_queue_better():
    """Queue holds every conflict above the budget line, baseline holds none."""
    ids, flags, group_of = _population(80, set(range(16)))
    orderings = {"queue": ids, "lazy": list(reversed(ids))}

    out = compare_orderings(
        orderings, flags, group_of, budget=40, n_boot=1500, seed=5
    )

    assert out["measurable"] is True
    c = out["comparisons"]["lazy"]
    assert c["diff_point"] == 16.0
    assert c["direction"] == "queue_better"
    assert c["diff_ci95"][0] > 0
    assert c["survives_correction"] is True


def test_a_worse_queue_reads_as_baseline_better():
    """The branch that must not be unreachable.

    A queue that ranks every conflict below the budget line while the baseline
    ranks them at the top has to come out as a measured loss, not as "no
    difference". A comparison that can only report good news is not a comparison.
    """
    ids, flags, group_of = _population(80, set(range(64, 80)))
    orderings = {"queue": ids, "sharp": list(reversed(ids))}

    out = compare_orderings(
        orderings, flags, group_of, budget=40, n_boot=1500, seed=5
    )

    c = out["comparisons"]["sharp"]
    assert c["diff_point"] == -16.0
    assert c["direction"] == "baseline_better"
    assert c["diff_ci95"][1] < 0
    assert c["survives_correction"] is True, (
        "a corrected loss has to survive correction too, or a measured harm is "
        "unrepresentable"
    )


def test_identical_orderings_are_indistinguishable():
    ids, flags, group_of = _population(80, set(range(0, 40, 3)))
    orderings = {"queue": ids, "twin": list(ids)}

    out = compare_orderings(
        orderings, flags, group_of, budget=40, n_boot=1500, seed=5
    )

    c = out["comparisons"]["twin"]
    assert c["diff_point"] == 0.0
    assert c["diff_ci95"] == [0.0, 0.0]
    assert c["direction"] == "indistinguishable"
    assert c["survives_correction"] is False
    assert c["ratio_point"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Pairing and re-sorting
# ---------------------------------------------------------------------------


def test_every_ordering_sees_the_same_drawn_population():
    """Pairing, tested through its consequence.

    Two orderings that are permutations of each other must find, in total across
    the budget, counts drawn from one population per draw. The check: an ordering
    identical to the queue has a difference of exactly zero in every draw, which
    is only true if both were scored on the same draw.
    """
    ids, flags, group_of = _population(60, {0, 5, 9, 20, 33, 41, 50}, per_group=2)
    out = compare_orderings(
        {"queue": ids, "twin": list(ids)},
        flags,
        group_of,
        budget=30,
        n_boot=800,
        seed=11,
    )
    c = out["comparisons"]["twin"]
    # A zero-width interval on the difference can only happen under pairing.
    assert c["diff_ci95"] == [0.0, 0.0]
    assert c["diff_ci_adjusted"] == [0.0, 0.0]


def test_ordering_is_resorted_inside_the_draw():
    """An ordering's top-k is recomputed from the drawn pool.

    Constructed so the two orderings disagree only about rows that a resample will
    often omit: conflicts sit at the very top for the queue and the very bottom
    for the baseline. If the original top-k were reused instead of re-derived, the
    baseline would keep scoring rows the draw may not contain and the interval
    would not widen with the resample.
    """
    ids, flags, group_of = _population(100, set(range(10)))
    out = compare_orderings(
        {"queue": ids, "reversed": list(reversed(ids))},
        flags,
        group_of,
        budget=20,
        n_boot=1200,
        seed=3,
    )
    c = out["comparisons"]["reversed"]
    lo, hi = c["diff_ci95"]
    assert lo <= c["diff_point"] <= hi
    assert hi > lo, "a re-derived top-k varies across draws, so the interval has width"


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_no_conflicts_is_unmeasurable_with_a_reason():
    ids, flags, group_of = _population(40, set())
    out = compare_orderings(
        {"queue": ids, "other": list(reversed(ids))},
        flags,
        group_of,
        budget=20,
        n_boot=500,
        seed=1,
    )
    assert out["measurable"] is False
    assert "No actionable conflicts" in out["reason"]
    assert out["comparisons"] == {}


def test_empty_population_is_unmeasurable():
    out = compare_orderings({"queue": []}, {}, {}, budget=10, n_boot=100, seed=1)
    assert out["measurable"] is False
    assert "No population to replay" in out["reason"]


def test_a_missing_queue_ordering_raises():
    ids, flags, group_of = _population(20, {0, 1})
    with pytest.raises(KeyError, match="must be present"):
        compare_orderings(
            {"fifo": ids}, flags, group_of, budget=10, n_boot=100, seed=1
        )


def test_orderings_over_different_populations_raise():
    """Two orderings covering different rows do not share a budget.

    Comparing them would silently compare 20 of one set against 20 of another.
    """
    ids, flags, group_of = _population(20, {0, 1})
    with pytest.raises(ValueError, match="different set of observations"):
        compare_orderings(
            {"queue": ids, "short": ids[:-1]},
            flags,
            group_of,
            budget=10,
            n_boot=100,
            seed=1,
        )


def test_ratio_is_finite_when_a_baseline_finds_nothing():
    """The continuity correction, applied in every draw and not only where it is
    needed, so the estimator does not change between draws."""
    ids, flags, group_of = _population(60, set(range(6)))
    out = compare_orderings(
        {"queue": ids, "blind": list(reversed(ids))},
        flags,
        group_of,
        budget=10,
        n_boot=800,
        seed=7,
    )
    c = out["comparisons"]["blind"]
    assert c["ratio_point"] == pytest.approx((6 + 0.5) / (0 + 0.5))
    for bound in c["ratio_ci95"]:
        assert bound == bound and abs(bound) != float("inf"), "ratio must be finite"


# ---------------------------------------------------------------------------
# Multiplicity and determinism
# ---------------------------------------------------------------------------


def test_correction_widens_the_interval():
    ids, flags, group_of = _population(80, set(range(0, 30, 2)))
    out = compare_orderings(
        {"queue": ids, "other": list(reversed(ids))},
        flags,
        group_of,
        budget=40,
        n_boot=2000,
        seed=9,
        n_comparisons=4,
    )
    c = out["comparisons"]["other"]
    lo, hi = c["diff_ci95"]
    lo_a, hi_a = c["diff_ci_adjusted"]
    assert lo_a <= lo and hi_a >= hi
    assert c["n_comparisons"] == 4
    assert c["adjusted_confidence"] == pytest.approx(1 - 0.05 / 4)


def test_uncorrected_family_would_be_a_weaker_standard():
    """n_comparisons=1 must give a strictly narrower interval than 4.

    Pins that the parameter does something: a correction that is accepted and
    ignored is worse than none, because the reader believes it was applied.
    """
    ids, flags, group_of = _population(80, set(range(0, 30, 2)))
    kwargs = dict(budget=40, n_boot=2000, seed=9)
    one = compare_orderings(
        {"queue": ids, "other": list(reversed(ids))},
        flags, group_of, n_comparisons=1, **kwargs,
    )["comparisons"]["other"]["diff_ci_adjusted"]
    four = compare_orderings(
        {"queue": ids, "other": list(reversed(ids))},
        flags, group_of, n_comparisons=4, **kwargs,
    )["comparisons"]["other"]["diff_ci_adjusted"]
    assert four[0] <= one[0] and four[1] >= one[1]
    assert (four[1] - four[0]) > (one[1] - one[0])


def test_replay_is_deterministic():
    ids, flags, group_of = _population(80, set(range(0, 30, 2)))
    args = (
        {"queue": ids, "other": list(reversed(ids))},
        flags,
        group_of,
    )
    a = compare_orderings(*args, budget=40, n_boot=1000, seed=42)
    b = compare_orderings(*args, budget=40, n_boot=1000, seed=42)
    assert a == b


# ---------------------------------------------------------------------------
# Combining two groupings
# ---------------------------------------------------------------------------


def _replay(direction: str, survives: bool) -> dict:
    return {
        "measurable": True,
        "reason": None,
        "comparisons": {
            "fifo": {
                "direction": direction,
                "survives_correction": survives,
                "diff_point": 6.0,
                "diff_ci_adjusted": [1.0, 12.0],
            }
        },
    }


def test_a_baseline_is_claimed_only_when_both_groupings_agree_and_survive():
    out = combine_replays(
        _replay("queue_better", True), _replay("queue_better", True)
    )
    assert out["baselines"]["fifo"]["claim"] == "queue_better"
    assert out["beaten"] == ["fifo"]
    assert out["lost_to"] == []


@pytest.mark.parametrize(
    "ep_dir,ep_sur,st_dir,st_sur",
    [
        ("queue_better", True, "queue_better", False),
        ("queue_better", False, "queue_better", True),
        ("queue_better", True, "indistinguishable", False),
        ("indistinguishable", False, "queue_better", True),
    ],
)
def test_disagreement_is_not_established_rather_than_resolved(
    ep_dir, ep_sur, st_dir, st_sur
):
    """Where the two groupings disagree, neither answer is adopted.

    Folding a disagreement into the favourable reading is the same failure as
    quoting whichever interval clears the threshold.
    """
    out = combine_replays(_replay(ep_dir, ep_sur), _replay(st_dir, st_sur))
    b = out["baselines"]["fifo"]
    assert b["claim"] == "not_established"
    assert out["beaten"] == []
    assert b["reason"] is not None
    assert ep_dir in b["reason"] and st_dir in b["reason"]


def test_a_loss_under_both_groupings_is_reported_as_a_loss():
    out = combine_replays(
        _replay("baseline_better", True), _replay("baseline_better", True)
    )
    assert out["baselines"]["fifo"]["claim"] == "baseline_better"
    assert out["lost_to"] == ["fifo"]
    assert out["beaten"] == []


def test_combining_needs_both_groupings_measured():
    out = combine_replays(
        {"measurable": False, "reason": "no conflicts", "comparisons": {}},
        _replay("queue_better", True),
    )
    assert out["measurable"] is False
    assert "no conflicts" in out["reason"]
    assert out["baselines"] == {}
