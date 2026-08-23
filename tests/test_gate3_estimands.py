"""Gate 3 reports two estimands, and only the pre-registered one may move the verdict.

The gate's threshold is worded as a rate over reviewed positive examples. Two statistics
can be built from that sentence. The pre-registered one collapses each (station, UTC date)
group to a single all-or-nothing indicator, and it is the one the verdict is read from. The
second takes the rate over observations and pays for the dependence with a cluster
bootstrap over the same groups, and it clears the bar the first one misses.

That second analysis was written after the first had been seen to fail. Everything in this
file exists because that ordering is the only thing keeping the pair honest: a statistic
adopted after seeing the result it is applied to must not be able to reach the verdict, and
the receipt and the document must both say when it was added.

The tests recompute rather than restate. Nothing here asserts 0.7104 or 0.4706, because a
larger pool moves both and neither number is the property worth pinning.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from scripts.run_gate3 import (
    all_or_nothing_under_independence,
    cluster_corrected_rate,
    rate_statistics,
    recompute_derived,
)

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "GATE3_RECEIPT.json"
KILL_GATE = REPO / "docs" / "KILL_GATE.md"


@pytest.fixture(scope="module")
def receipt() -> dict:
    if not RECEIPT.exists():
        pytest.skip("no gate 3 receipt in this checkout")
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def estimand(receipt: dict) -> dict:
    block = receipt.get("cluster_corrected_estimand")
    if not block:
        pytest.skip("the committed receipt predates the second estimand")
    if not block.get("measurable"):
        pytest.skip(f"the second estimand is not measurable here: {block.get('reason')}")
    return block


def test_the_second_estimand_says_it_decides_nothing(estimand: dict):
    """The one field a downstream consumer has to be able to read."""
    assert estimand["decides_the_gate"] is False
    assert estimand["why_it_does_not_decide"]
    assert "added" in estimand["added_after"].lower() or estimand["added_after"]


def test_a_clearing_second_estimand_does_not_turn_the_verdict_into_a_pass(
    receipt: dict, estimand: dict
):
    """The rule, stated so that wiring the block into the verdict fails here.

    This is the whole risk of publishing a second estimand that clears a bar the
    pre-registered one misses. The verdict has to keep following the pre-registered
    statistic, whatever the second one says.
    """
    grouped_clears = receipt["entity_grouping"]["grouped_clears_threshold"]
    if estimand["clears_threshold"] and not grouped_clears:
        assert receipt["verdict"] != "PASSED", (
            "the cluster-corrected estimand clears the bar and the pre-registered "
            "grouped statistic does not, so the verdict must not read PASSED. It was "
            "added after the pre-registered analysis had failed, and a rule chosen after "
            "seeing a result cannot be the rule that decides."
        )


def test_the_published_bound_is_the_lowest_of_its_seeds(estimand: dict):
    """A margin of 0.01 on a bootstrap bound must not be a property of one seed."""
    boot = estimand["cluster_bootstrap"]
    per_seed = [row["lower_bound_95_one_sided"] for row in boot["per_seed"]]
    assert len(per_seed) >= 2, "one seed is not a seed sensitivity check"
    assert boot["lower_bound_95_one_sided"] == pytest.approx(min(per_seed), abs=1e-12)
    assert boot["lower_bound_95_one_sided_range"] == [
        pytest.approx(min(per_seed), abs=1e-12),
        pytest.approx(max(per_seed), abs=1e-12),
    ]


def test_the_two_sided_interval_is_published_even_where_it_does_not_clear(
    estimand: dict
):
    """Publishing only the one-sided bound would be choosing the test after the result."""
    boot = estimand["cluster_bootstrap"]
    lo, hi = boot["ci95_two_sided"]
    assert lo <= boot["lower_bound_95_one_sided"] <= hi, (
        "a one-sided 95% lower bound sits above the two-sided 95% lower bound and below "
        "the upper one, so this ordering is arithmetic rather than a result"
    )


def test_the_design_effect_follows_the_icc_and_the_mean_group_size(estimand: dict):
    """Recomputed, because a design effect typed beside an ICC is two numbers, not one."""
    clustering = estimand["clustering"]
    if not clustering["measurable"]:
        pytest.skip("clustering not measurable on this pool")
    expected = 1.0 + (clustering["mean_group_size"] - 1.0) * max(clustering["icc"], 0.0)
    assert clustering["design_effect"] == pytest.approx(expected, rel=1e-12)


def test_the_three_routes_to_the_bound_agree_to_within_two_points(estimand: dict):
    """A bound this close to its bar should not depend on which method produced it."""
    routes = [
        estimand["cluster_bootstrap"]["lower_bound_95_one_sided"],
        estimand["design_effect_normal_lower_bound_95"],
        estimand["effective_n_exact_lower_bound_95"]["lower_bound"],
    ]
    routes = [r for r in routes if r is not None]
    assert len(routes) == 3
    assert max(routes) - min(routes) < 0.02, (
        f"the three bounds are {routes}, which is a spread wide enough that the verdict "
        "would depend on the choice of method rather than on the data"
    )


def test_the_collapsed_statistic_cannot_reach_the_bar_at_these_group_sizes(
    receipt: dict,
):
    """Why the pre-registered statistic missing the bar is not evidence against the gate.

    The all-or-nothing indicator falls as groups grow whether or not any dependence
    exists. Measured on the realised group sizes under zero clustering, and the number
    that matters is the per-observation rate the collapse would need before it could touch
    the bar in expectation.
    """
    sim = receipt["entity_grouping"].get("all_or_nothing_under_independence")
    if not sim or not sim.get("measurable"):
        pytest.skip("the committed receipt predates the independence simulation")
    needed = sim["per_observation_rate_needed_to_reach_the_threshold"]
    observed = sim["per_observation_rate_held_at"]
    assert needed > observed, (
        f"the collapsed statistic needs a per-observation rate of {needed:.4f} to reach "
        f"{sim['threshold']:.2f} and the observed rate is {observed:.4f}. If that "
        "inequality ever reverses the collapse is a reachable bar and this section's "
        "argument has to be rewritten."
    )
    assert sim["max_all_pass_group_rate_drawn"] < sim["threshold"], (
        "no draw under zero clustering reached the bar, which is what makes the "
        "collapsed statistic's failure uninformative about the corridor"
    )


def test_the_published_grouped_rate_sits_inside_the_no_clustering_range(receipt: dict):
    """The finding: the collapse detected the group-size distribution, not dependence."""
    sim = receipt["entity_grouping"].get("all_or_nothing_under_independence")
    if not sim or not sim.get("measurable"):
        pytest.skip("the committed receipt predates the independence simulation")
    assert sim["observed_is_inside_the_range"] is True
    lo, hi = sim["range95"]
    assert lo <= sim["observed_all_pass_group_rate"] <= hi


def test_the_independence_simulation_reproduces_its_own_arithmetic():
    """Against the closed form, on sizes chosen here rather than read from a receipt.

    Under independence the expected all-pass rate is mean(p ** n_i) over the group sizes.
    The simulation is a Monte Carlo estimate of exactly that, so it has an answer to check
    against and this fails if the draw loop stops meaning what its docstring says.
    """
    sizes = [1, 1, 2, 3, 5, 8, 13]
    p = 0.8
    out = all_or_nothing_under_independence(sizes, p, None, 0.7, n_draws=20_000, seed=7)
    closed_form = float(np.mean([p**n for n in sizes]))
    assert out["mean_all_pass_group_rate"] == pytest.approx(closed_form, abs=0.01)
    # And the solved rate really is the one that hits the bar in expectation.
    needed = out["per_observation_rate_needed_to_reach_the_threshold"]
    assert float(np.mean([needed**n for n in sizes])) == pytest.approx(0.7, abs=1e-6)


def test_one_group_of_one_is_refused_rather_than_reported():
    """A cluster-corrected interval over a single group is not an interval."""
    out = cluster_corrected_rate({("s", "d"): [True]}, 0.7, "(station, date)")
    assert out["measurable"] is False
    assert out["decides_the_gate"] is False
    assert "at least 2 groups" in out["reason"]


def test_a_perfectly_clustered_pool_pays_for_it(receipt: dict):
    """The correction has to bite when every group is internally identical.

    Two groups of ten, one all-success and one all-failure, is a rate of 0.5 carrying two
    independent observations rather than twenty. A bound that ignored the clustering would
    put the lower end near 0.28; one that pays for it cannot.
    """
    del receipt
    groups = {("a", "d"): [True] * 10, ("b", "d"): [False] * 10}
    out = cluster_corrected_rate(groups, 0.7, "(station, date)", n_boot=2_000, seeds=(1,))
    assert out["rate"] == pytest.approx(0.5)
    assert out["clustering"]["icc"] == pytest.approx(1.0, abs=1e-9)
    assert out["clustering"]["design_effect"] == pytest.approx(10.0, rel=1e-9)
    assert out["cluster_bootstrap"]["lower_bound_95_one_sided"] == pytest.approx(0.0)
    assert out["clears_threshold"] is False


def _write_receipt(path: Path, source: dict) -> None:
    path.write_text(json.dumps(source, indent=2), encoding="utf-8", newline="\n")


def test_the_recompute_mode_refuses_a_receipt_it_cannot_reproduce(
    receipt: dict, tmp_path: Path
):
    """The guard that stops a partial rewrite from hiding an inconsistent file.

    `--recompute-derived` opens no image, so the only thing standing between it and
    overwriting derived numbers with numbers derived from something else is this check.
    """
    tampered = json.loads(json.dumps(receipt))
    tampered["discriminating_rate"] = 0.9999
    target = tmp_path / "GATE3_RECEIPT.json"
    _write_receipt(target, tampered)

    with pytest.raises(SystemExit) as caught:
        recompute_derived(target, tampered["threshold"])
    assert "do not reproduce" in str(caught.value)
    assert "discriminating_rate" in str(caught.value)


def test_the_recompute_mode_refuses_when_the_scored_count_disagrees(
    receipt: dict, tmp_path: Path
):
    tampered = json.loads(json.dumps(receipt))
    tampered["observations_scored"] = tampered["observations_scored"] + 1
    target = tmp_path / "GATE3_RECEIPT.json"
    _write_receipt(target, tampered)

    with pytest.raises(SystemExit) as caught:
        recompute_derived(target, tampered["threshold"])
    assert "not a function of the stored rows" in str(caught.value)


def test_the_recompute_mode_refuses_when_the_pool_selection_moved(
    receipt: dict, tmp_path: Path
):
    """Refreshing a count is safe only while the pool still selects the same rows."""
    tampered = json.loads(json.dumps(receipt))
    pool_name = (tampered.get("pool") or {}).get("name")
    if pool_name not in ("pool_a", "pool_b"):
        pytest.skip("the committed receipt predates the pre-registered pools")

    moved = tmp_path / "MOVED_POOL.json"
    moved.write_text(
        json.dumps({
            "trace_q75_min": 3.5,
            "counts": {"examined": 2},
            "selection": {pool_name: "a fixture, not the real rule"},
            "observations": [
                {"obs_id": -1, "verdict": "UNCORRECTED", pool_name: True},
                {"obs_id": -2, "verdict": "UNCORRECTED", pool_name: True},
            ],
        }),
        encoding="utf-8",
    )
    tampered["pool"]["source"] = str(moved).replace("\\", "/")
    target = tmp_path / "GATE3_RECEIPT.json"
    _write_receipt(target, tampered)

    with pytest.raises(SystemExit) as caught:
        recompute_derived(target, tampered["threshold"])
    assert "the selection moved" in str(caught.value)


def test_rate_statistics_is_the_only_place_the_rates_are_computed(receipt: dict):
    """The full run and the recompute must not be two copies of the same arithmetic.

    Both call ``rate_statistics``, so running it on the receipt's own rows has to
    reproduce every rate the receipt publishes. If the two ever drift apart this fails,
    which is the property that makes the recompute mode trustworthy at all.
    """
    scored = [
        r for r in receipt["observations"]
        if r["testable"] and r["null_calibration"]["p_value"] is not None
    ]
    stats = rate_statistics(scored, receipt["threshold"])
    assert stats["discriminating_rate"] == pytest.approx(
        receipt["discriminating_rate"], rel=1e-12
    )
    assert stats["rate_lower_bound_95"] == pytest.approx(
        receipt["rate_lower_bound_95"], rel=1e-12
    )
    for key in ("groups_scored", "grouped_discriminating_rate",
                "grouped_rate_lower_bound_95", "grouped_clears_threshold"):
        assert stats["entity_grouping"][key] == pytest.approx(
            receipt["entity_grouping"][key]
        ), key


def test_the_document_says_the_second_estimand_was_added_after_the_first_failed():
    """The sentence the whole framing rests on, pinned in the judge-facing document.

    Without it the section reads as a correction that happens to clear the bar, which is
    the reading it exists to refuse.
    """
    if not KILL_GATE.exists():
        pytest.skip("no KILL_GATE.md in this checkout")
    text = KILL_GATE.read_text(encoding="utf-8")
    assert "Two estimands" in text, "the section is missing from the document"
    assert "after the pre-registered statistic had been seen to" in text, (
        "the document must state that the cluster-corrected analysis was written after "
        "the pre-registered one had failed. That ordering is the reason the "
        "pre-registered verdict is the one that stands."
    )
    assert "The margin is narrow" in text
