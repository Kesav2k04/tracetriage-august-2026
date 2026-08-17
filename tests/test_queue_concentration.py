"""Entity-concentration caps, clustering measurement and the governing interval (C2).

Three things are pinned here.

The caps, because a rule that reorders a reviewer's queue must not lose a row: a
displaced observation is still a real candidate, and a silently dropped one is a
suppressed finding.

The intra-class correlation, because it is what showed that the episode grouping
used throughout Waves B and C was doing nothing. On the chronological test
partition the decisive observations fall into 87 pass episodes of mean size
exactly 1.000, so a grouped bootstrap over them is an ordinary bootstrap. The ICC
reports that as unmeasurable with its counts rather than as a zero.

The union rule for combining two groupings, because "take the wider interval" is
not the same as "take the conservative one" and the corpus contains a case where
they differ.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.tracetriage.queue import (
    CONCENTRATION_CAPS,
    QUEUE_REASONS,
    apply_concentration_caps,
    cap_entries,
    intraclass_correlation,
    verdict_from_interval,
)

_CONTRACT = (
    Path(__file__).resolve().parents[1] / "contracts" / "queue_receipt.schema.json"
)
_RECEIPT = Path(__file__).resolve().parents[1] / "artifacts" / "QUEUE_RECEIPT.json"


def _entities(station_of: dict[int, str], tx_of: dict[int, str] | None = None):
    return {
        "ground_station": station_of,
        "transmitter_uuid": tx_of if tx_of is not None else {},
    }


# ---------------------------------------------------------------------------
# The caps
# ---------------------------------------------------------------------------


def test_cap_entries_never_rounds_down_to_zero():
    """A 10% cap on a budget of 5 must not exclude every entity from review."""
    assert cap_entries(5, 0.10) == 1
    assert cap_entries(1, 0.10) == 1
    assert cap_entries(50, 0.10) == 5
    assert cap_entries(50, 0.20) == 10
    # Rounded up, so a cap is never quietly tighter than its stated share.
    assert cap_entries(45, 0.10) == 5


def test_one_station_cannot_flood_the_budget():
    """The case the cap exists for: one station holding every top-ranked row."""
    ranked = list(range(100, 130))
    station_of = {oid: "station-A" if oid < 120 else f"station-{oid}" for oid in ranked}

    order, record = apply_concentration_caps(
        ranked, _entities(station_of), budget=10, caps={"ground_station": 0.10}
    )

    admitted = order[:10]
    from_a = [oid for oid in admitted if station_of[oid] == "station-A"]
    assert len(from_a) == 1, (
        f"cap is 1 entry at budget 10, so station-A may hold one slot, got {from_a}"
    )
    assert record["caps"]["ground_station"]["entries_at_budget"] == 1
    assert record["binding"] is True
    assert record["budget_filled"] is True


def test_nothing_is_deleted_only_reordered():
    """A displaced observation stays a candidate. The output is a permutation."""
    ranked = list(range(200, 260))
    station_of = {oid: "station-A" if oid % 2 == 0 else f"station-{oid}" for oid in ranked}

    order, record = apply_concentration_caps(
        ranked, _entities(station_of), budget=20, caps={"ground_station": 0.10}
    )

    assert sorted(order) == sorted(ranked)
    assert len(order) == len(ranked)
    displaced = set(record["caps"]["ground_station"]["displaced_obs_ids"])
    # Every displaced entry is present, and sits below the budget line.
    for oid in displaced:
        assert oid in order
        assert order.index(oid) >= record["n_admitted_to_budget"]


def test_relative_order_is_preserved_within_admitted_and_displaced():
    ranked = list(range(300, 340))
    station_of = {oid: "station-A" if oid < 330 else f"station-{oid}" for oid in ranked}

    order, record = apply_concentration_caps(
        ranked, _entities(station_of), budget=10, caps={"ground_station": 0.20}
    )
    n_adm = record["n_admitted_to_budget"]
    admitted, displaced = order[:n_adm], order[n_adm:]
    assert admitted == sorted(admitted), "admitted entries keep their ranking order"
    assert displaced == sorted(displaced), "displaced entries keep their ranking order"


def test_a_cap_that_displaces_nothing_says_so():
    """The falsification clause: an inert cap is reported, not implied to have run."""
    ranked = list(range(400, 420))
    station_of = {oid: f"station-{oid}" for oid in ranked}

    _, record = apply_concentration_caps(
        ranked, _entities(station_of), budget=10, caps={"ground_station": 0.10}
    )

    assert record["binding"] is False
    assert record["caps"]["ground_station"]["bound"] is False
    assert record["caps"]["ground_station"]["n_displaced"] == 0
    assert "inert" in record["note"]


def test_both_blocking_caps_are_credited():
    """An entry blocked by two caps is credited to both.

    Crediting only the first cap the loop checks would make the other read as
    inert when it had simply never been reached, and "inert" would then be a
    property of dict ordering rather than of the data.
    """
    ranked = list(range(500, 520))
    # Every entry shares one station and one transmitter, so past the first slot
    # both caps block every entry.
    station_of = {oid: "station-A" for oid in ranked}
    tx_of = {oid: "tx-A" for oid in ranked}

    _, record = apply_concentration_caps(
        ranked,
        _entities(station_of, tx_of),
        budget=10,
        caps={"ground_station": 0.10, "transmitter_uuid": 0.10},
    )

    st = record["caps"]["ground_station"]
    tx = record["caps"]["transmitter_uuid"]
    assert st["n_displaced"] == tx["n_displaced"] == 19
    assert st["bound"] is True and tx["bound"] is True
    # The distinct count does not double count an entry blocked twice.
    assert record["n_displaced_total"] == 19


def test_a_cap_tight_enough_to_starve_the_budget_reports_it():
    """When the caps cannot fill the budget, "at the same budget" changes meaning."""
    ranked = list(range(600, 610))
    station_of = {oid: "station-A" for oid in ranked}

    order, record = apply_concentration_caps(
        ranked, _entities(station_of), budget=10, caps={"ground_station": 0.10}
    )

    assert record["n_admitted_to_budget"] == 1
    assert record["budget_filled"] is False, (
        "one station, cap of one entry, so nine of the ten budget slots cannot be "
        "filled and the gate's 'at the same budget' comparison is affected"
    )
    assert sorted(order) == sorted(ranked)


def test_unknown_entity_is_its_own_singleton():
    """An observation with no known station cannot be shown to share a receiver."""
    ranked = [700, 701, 702, 703]
    order, record = apply_concentration_caps(
        ranked, _entities({}), budget=4, caps={"ground_station": 0.25}
    )
    assert order == ranked
    assert record["binding"] is False


def test_caps_are_deterministic():
    ranked = list(range(800, 900))
    station_of = {oid: f"station-{oid % 7}" for oid in ranked}
    a, ra = apply_concentration_caps(ranked, _entities(station_of), budget=30)
    b, rb = apply_concentration_caps(ranked, _entities(station_of), budget=30)
    assert a == b
    assert ra == rb


def test_preregistered_shares_are_what_the_code_uses():
    """The committed pre-registration and the constant cannot drift apart."""
    assert CONCENTRATION_CAPS == {"ground_station": 0.10, "transmitter_uuid": 0.20}


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def test_singleton_groups_are_unmeasurable_with_a_reason():
    """The C2 finding, as a test.

    87 groups over 87 observations is what the chronological test partition
    actually contains. There is no within-group variance to partition, so the
    correlation is undefined. Reporting it as 0.0 would say "measured, no
    clustering", which is a different and false claim.
    """
    groups = [[1.0] for _ in range(87)]
    out = intraclass_correlation(groups)

    assert out["measurable"] is False
    assert out["icc"] is None
    assert out["design_effect"] is None
    assert out["n_groups"] == 87
    assert out["n_observations"] == 87
    assert out["mean_group_size"] == 1.0
    assert "more observations than groups" in out["reason"]


def test_perfect_clustering_scores_near_one():
    groups = [[1.0] * 5 for _ in range(10)] + [[0.0] * 5 for _ in range(10)]
    out = intraclass_correlation(groups)
    assert out["measurable"] is True
    assert out["icc"] > 0.95, out["icc"]
    assert out["design_effect"] > 4.0


def test_identical_group_means_score_below_zero_not_at_zero():
    """Worth pinning exactly, because the intuitive expectation is wrong.

    Every group here holds the same alternating pattern, so the between-group
    variance is exactly zero. That is *less* between-group spread than chance
    would produce, so the correlation is negative rather than zero: with equal
    groups of size m the estimator returns -1/(m-1), here -1/3. Reading this as
    "no clustering, near zero" would misread a real property of the estimator.
    """
    groups = [[1.0, 0.0, 1.0, 0.0] for _ in range(25)]
    out = intraclass_correlation(groups)
    assert out["measurable"] is True
    assert out["icc"] == pytest.approx(-1 / 3, abs=1e-9), out["icc"]
    # A negative correlation cannot inflate a variance, so the design effect
    # floors at 1 and the interval is left unchanged.
    assert out["design_effect"] == 1.0


def test_unclustered_assignment_scores_near_zero():
    """Group membership carrying no information about the outcome.

    Random assignment of a fixed marginal rate across fixed-size groups, over six
    seeds rather than one, so the result is a property of the estimator and not a
    lucky draw. Measured over these seeds: -0.081, +0.015, -0.024, -0.004, +0.034,
    -0.024, which is the sampling spread of an ICC of zero on 120 observations in
    24 groups.

    A deterministic interleave was tried first and was wrong: with 24 groups taken
    at stride 24 and values keyed on i % 3, every member of a group shares a
    residue and the ICC comes out at exactly 1.0. The construction has to break
    the alignment between the grouping and the outcome, not just look as though
    it does.
    """
    import random  # noqa: PLC0415

    for seed in (0, 1, 2, 3, 7, 42):
        rng = random.Random(seed)
        values = [1.0] * 40 + [0.0] * 80
        rng.shuffle(values)
        groups = [values[5 * k: 5 * k + 5] for k in range(24)]
        out = intraclass_correlation(groups)
        assert out["measurable"] is True
        assert abs(out["icc"]) < 0.15, (seed, out["icc"])
        assert out["design_effect"] < 1.6, (seed, out["design_effect"])


def test_design_effect_never_falls_below_one():
    """A negative ICC is a real small-sample result and is reported as measured,
    but a variance cannot be inflated by a factor below 1."""
    groups = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0], [0.0, 1.0]]
    out = intraclass_correlation(groups)
    assert out["measurable"] is True
    assert out["design_effect"] >= 1.0
    if out["icc"] < 0:
        assert out["design_effect"] == 1.0


def test_one_group_is_unmeasurable():
    out = intraclass_correlation([[1.0, 0.0, 1.0]])
    assert out["measurable"] is False
    assert "at least 2 populated groups" in out["reason"]


def test_empty_groups_are_dropped_not_counted():
    out = intraclass_correlation([[], [1.0, 0.0], [], [0.0, 1.0]])
    assert out["n_groups"] == 2


# ---------------------------------------------------------------------------
# The governing interval
# ---------------------------------------------------------------------------


def test_union_is_taken_not_the_wider_interval():
    """A wider interval is not necessarily the conservative one.

    cold_station produces exactly this shape: the station interval
    [2.0259, 3.8956] is wider than the episode interval [1.9196, 3.0115] and yet
    has the higher lower bound. For a one-sided threshold test, taking "the wider
    one" would quote a lower bound of 2.0259 when a defensible grouping supports
    only 1.9196. The union takes the lower bound from one and the upper from the
    other.
    """
    episode = (1.9196, 3.0115)
    station = (2.0259, 3.8956)
    union = (min(episode[0], station[0]), max(episode[1], station[1]))

    assert union == (1.9196, 3.8956)
    assert (station[1] - station[0]) > (episode[1] - episode[0]), "station is wider"
    assert station[0] > episode[0], "yet its lower bound is higher"
    # Both still clear 1.5 here, so the conservative choice does not change the
    # verdict on this split. It is taken because it cannot be gamed, not because
    # it happens to agree.
    assert verdict_from_interval(*union, 1.5)[1] == "PASSED"
    assert verdict_from_interval(*episode, 1.5)[1] == "PASSED"


def test_union_can_only_widen():
    for ep, st in [
        ((1.0, 2.0), (1.5, 1.8)),
        ((1.4, 1.9), (1.2, 2.4)),
        ((2.0, 3.0), (2.0, 3.0)),
    ]:
        union = (min(ep[0], st[0]), max(ep[1], st[1]))
        assert union[0] <= ep[0] and union[1] >= ep[1]
        assert union[0] <= st[0] and union[1] >= st[1]


def test_verdict_rule_is_decided_by_the_interval():
    assert verdict_from_interval(1.6, 2.0, 1.5) == ("above_threshold", "PASSED")
    assert verdict_from_interval(1.0, 1.4, 1.5) == ("below_threshold", "FAILED")
    assert verdict_from_interval(1.3, 1.8, 1.5) == ("spans_threshold", "NOT_ESTABLISHED")
    # Exactly on the bound does not clear it.
    assert verdict_from_interval(1.5, 2.0, 1.5) == ("spans_threshold", "NOT_ESTABLISHED")
    assert verdict_from_interval(1.0, 1.5, 1.5) == ("spans_threshold", "NOT_ESTABLISHED")
    # An inconsistent statistic reports no verdict about the gate at all.
    assert verdict_from_interval(1.6, 2.0, 1.5, point_in_ci=False) == (
        "inconsistent_interval",
        "NOT_MEASURABLE",
    )


# ---------------------------------------------------------------------------
# Contract and receipt shape
# ---------------------------------------------------------------------------


def test_reason_vocabulary_matches_the_contract():
    """The fixed vocabulary lives in two files and they cannot drift."""
    schema = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    enum = set(
        schema["$defs"]["queue_entry"]["properties"]["reasons"]["items"]["enum"]
    )
    assert enum == set(QUEUE_REASONS), (
        f"only in schema: {sorted(enum - set(QUEUE_REASONS))}, "
        f"only in code: {sorted(set(QUEUE_REASONS) - enum)}"
    )


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not generated yet")
def test_receipt_episode_keys_are_revolution_based_not_hour_buckets():
    """Regression guard on the grouping unit.

    The queue previously grouped by (station, satellite, start[:13]). An hour
    bucket splits any pass crossing an hour boundary into two groups, and a
    grouped interval built on that treats correlated captures as independent.
    A key carrying a timestamp is the tell.
    """
    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    keys = [e["episode_key"] for e in receipt["queue"]]
    assert keys, "receipt carries no queue entries"

    for key in keys[:200]:
        parts = key.split(":")
        assert len(parts) == 3, f"expected station:norad:revolution, got {key!r}"
        station, norad, revolution = parts
        assert station.lstrip("-").isdigit(), key
        assert norad.lstrip("-").isdigit(), key
        assert revolution.lstrip("-").isdigit(), (
            f"revolution component {revolution!r} is not an integer, which is what "
            f"an hour bucket looks like: {key!r}"
        )
        assert "T" not in key and "-" not in station, f"timestamp in key: {key!r}"
