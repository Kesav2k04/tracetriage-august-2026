"""The circularity analysis has to reproduce the gate before it is allowed to bound it.

`scripts/run_circularity_check.py` exists to say how much of gate 6's lift is guaranteed by
the queue being ranked on the same three quantities the conflict criteria threshold. That is
a claim about the same measurement, so the first thing it must do is recover the published
number from the queue receipt alone. A bounding analysis computed over a different population
would be a different result wearing the gate's name, which is worse than no analysis.

The checks here go in that order: the reproduction first, then the properties of the bound.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "CIRCULARITY_RECEIPT.json"
QUEUE = REPO / "artifacts" / "QUEUE_RECEIPT.json"


def _load_script():
    path = REPO / "scripts" / "run_circularity_check.py"
    spec = importlib.util.spec_from_file_location("run_circularity_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_circularity_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture(scope="module")
def receipt() -> dict:
    if not RECEIPT.exists():
        pytest.skip(
            "artifacts/CIRCULARITY_RECEIPT.json is absent. Run "
            "scripts/run_circularity_check.py."
        )
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def queue() -> dict:
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def test_the_committed_receipt_is_what_the_queue_receipt_produces(script, receipt):
    fresh = script.build()
    a = {k: v for k, v in fresh.items() if k != "generated_at"}
    b = {k: v for k, v in receipt.items() if k != "generated_at"}
    assert a == b, "the committed circularity receipt is stale against QUEUE_RECEIPT.json"


def test_it_reproduces_the_published_lift(receipt, queue):
    """The precondition. Everything else in the file is about a different queue without it."""
    published = queue["gate6"]["per_split"]["chronological"]
    rep = receipt["reproduction"]
    assert rep["matches_the_queue_receipt"] is True
    assert rep["lift_point"] == pytest.approx(published["lift_point"], abs=1e-9)
    assert rep["n_at_budget"] == published["n_queue_conflicts"]
    assert rep["n_population"] == published["replay_episode"]["n_population"]


def test_a_population_that_does_not_match_refuses_to_write(script, tmp_path, monkeypatch):
    """The reproduction check has to be able to fail, or it is a comment.

    Dropping one observation from the population changes the random expectation and the
    published lift is no longer recoverable. The script must stop rather than publish a
    bound computed over a different set.
    """
    doc = json.loads(QUEUE.read_text(encoding="utf-8"))
    doc["queue"] = [
        entry
        for entry in doc["queue"]
        if not (
            entry["waterfall_status"] in ("with-signal", "without-signal")
            and entry["rank"] > 300
        )
    ]
    path = tmp_path / "QUEUE_RECEIPT.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(script, "QUEUE_RECEIPT", path)
    with pytest.raises(SystemExit) as raised:
        script.build()
    assert "reproduce the published lift" in str(raised.value)


def test_every_conflict_criterion_is_mapped_to_a_score_weight(script):
    """An unmapped criterion would leave a shared signal out of the accounting.

    The accounting is the whole point of the file, so a criterion added to the pipeline
    without a weight beside it has to stop the run rather than shrink the total quietly.
    """
    from pipeline.tracetriage.queue import CONFLICT_CRITERIA

    mapped = set(script.SHARED_SIGNALS)
    defined = {c["reason_code"] for c in CONFLICT_CRITERIA}
    assert mapped == defined


def test_the_weights_sum_to_one_with_the_unshared_signal(script):
    shared = sum(v["score_weight"] for v in script.SHARED_SIGNALS.values())
    assert shared + script.UNSHARED_SIGNAL["score_weight"] == pytest.approx(1.0)


def test_the_shared_weight_is_reported_and_is_most_of_the_score(receipt):
    """The finding, asserted rather than described.

    If a future reweighting moved most of the score onto a signal no criterion reads, the
    circularity would be smaller and this test would fail, which is the correct outcome:
    the README sentence it supports would need rewriting.
    """
    signals = receipt["shared_signals"]
    named = signals["score_weight_on_quantities_the_definition_names"]
    independent = signals["score_weight_independent_of_the_target"]
    assert named + independent == pytest.approx(1.0)
    assert named >= 0.5, (
        "most of the score no longer sits on quantities the conflict definition reads, so "
        "the README's circularity paragraph overstates the problem and needs rewriting"
    )


def test_the_active_weight_is_published_separately_from_the_named_weight(receipt):
    """A criterion that fires on nothing still carries its weight into the named total.

    The two totals answer different questions and were one number until a review counted
    the reason codes: 0.90 of the score sits on quantities the definition names, 0.75 on
    quantities a conflict in this corpus is defined from, and the 0.15 gap is DEAD_CAPTURE,
    which fires zero times here. Publishing only the first overstates the loop by the
    weight of a criterion that never fires.
    """
    signals = receipt["shared_signals"]
    named = signals["score_weight_on_quantities_the_definition_names"]
    active = signals["score_weight_on_quantities_a_realised_conflict_is_defined_from"]
    fired = signals["fired"]
    assert active <= named
    expected_gap = sum(
        signals["criteria"][code]["score_weight"]
        for code, row in fired.items()
        if row["n_flagged"] == 0
    )
    assert named - active == pytest.approx(expected_gap, abs=1e-9)
    assert set(signals["inert"]) == {c for c, r in fired.items() if r["n_flagged"] == 0}
    assert set(signals["active"]) == {c for c, r in fired.items() if r["n_flagged"] > 0}


def test_an_inert_criterion_is_named_with_the_value_that_makes_it_inert(receipt):
    """"Fires zero times" is a claim, and the number behind it travels with it.

    A reader who sees DEAD_CAPTURE in the definition and nowhere in the counts should not
    have to guess whether the images were clean or the threshold was unreachable. The
    receipt carries the highest value observed and the number of rows it was measurable on.
    """
    for code in receipt["shared_signals"]["inert"]:
        row = receipt["shared_signals"]["fired"][code]
        assert row["n_flagged"] == 0
        assert row["inert_on_this_corpus"] is True
        assert row["n_rows_the_quantity_was_measurable_on"] > 0, (
            f"{code} is reported inert with nothing measured, which is an absence of "
            "evidence rather than a criterion that did not fire"
        )
        assert row["max_observed"] is not None
        assert f"{row['max_observed']:.4f}" in row["note"]


def test_the_ceiling_is_the_population_over_the_budget(receipt):
    """An oracle finds every conflict it has room for, so lift saturates at n/budget."""
    rep = receipt["reproduction"]
    ceiling = receipt["ceiling"]
    assert ceiling["max_findable_at_budget"] == min(rep["budget"], rep["n_conflicts"])
    assert ceiling["lift"] == pytest.approx(rep["n_population"] / rep["budget"])
    assert ceiling["lift"] > rep["lift_point"], "the queue cannot beat an oracle"
    assert ceiling["headroom_between_threshold_and_perfection"] == pytest.approx(
        ceiling["lift"] - ceiling["threshold"]
    )


def test_a_random_ordering_scores_one(receipt):
    """The floor. A lift framework that cannot score a shuffle at 1.0 measures nothing."""
    control = receipt["random_ordering_control"]
    assert control["abs_error"] < 0.01, (
        f"random orderings mean {control['mean_lift']}, which is not 1.0, so the lift "
        "statistic itself is biased and no number computed with it can be read"
    )
    assert control["p5"] < 1.0 < control["p95"]


def test_a_saturated_target_is_not_reported_as_a_pass(receipt):
    """The trap this analysis would otherwise walk into.

    When the queue finds every conflict inside the budget, lift equals n_population /
    budget whatever the conflict count was, and the interval around a constant is narrow.
    Printing PASSED there would put the strongest verdict in the file on the least
    information. Saturation gets its own outcome.
    """
    saturated = [
        (name, block)
        for name, block in receipt["targets"].items()
        if block.get("measurable") and block.get("saturated")
    ]
    for name, block in saturated:
        assert block["verdict"] == "NOT_INFORMATIVE", (
            f"{name} found every conflict inside the budget and is reported as "
            f"{block['verdict']}"
        )
        assert block["lift_point"] == pytest.approx(receipt["ceiling"]["lift"])
        assert block["saturation_note"]


def test_the_model_independent_target_is_measured_and_named(receipt):
    """The comparison the whole file exists to publish.

    Two of the three criteria are computed without the model: the fitted offset and the
    flat-row fraction. Restricting the target to them removes the loop that runs from the
    model's own probability into the definition of a find.
    """
    block = receipt["targets"]["model_independent_only"]
    assert block["measurable"], block.get("not_measurable_reason")
    assert set(block["criteria"]) == {"STALE_CATALOGUE_FREQ", "DEAD_CAPTURE"}
    assert block["n_conflicts"] > 0
    lo, hi = block["lift_ci95"]
    assert lo < block["lift_point"] < hi


def test_the_firing_restriction_carries_the_same_numbers_under_a_truthful_name(receipt):
    """`model_independent_only` names two criteria and one of them fires on nothing.

    Dropping the inert criterion from the target cannot move a single number, because it
    contributed no conflict. That is the point: the row exists so a reader is not told a
    two-criterion restriction was measured when the data supports one. If the two rows ever
    disagree, the inert criterion started firing and the prose around both is stale.
    """
    named = receipt["targets"]["model_independent_only"]
    firing = receipt["targets"]["model_independent_and_firing"]
    assert set(firing["criteria"]) <= set(named["criteria"])
    assert firing["n_conflicts"] == named["n_conflicts"]
    assert firing["lift_point"] == pytest.approx(named["lift_point"])
    assert firing["lift_ci95"] == named["lift_ci95"]
    assert str(len(firing["criteria"])) in receipt["targets_note"]


def test_it_does_not_claim_the_loop_is_closed(receipt):
    """The sentence that keeps this honest has to be in the receipt, not only in a docstring.

    Restricting the target to the two model-free criteria removes one loop and leaves
    another: the score still weights those two quantities at 0.35 and 0.15.
    """
    text = receipt["what_this_does_not_establish"]
    assert "generalises" in text
    assert "0.35" in text and "0.15" in text


def test_it_reads_no_snapshot(receipt):
    """A judge without the 4 GB snapshot has to be able to run this."""
    assert receipt["source"]["needs_the_snapshot"] is False
    assert receipt["source"]["receipt"] == "artifacts/QUEUE_RECEIPT.json"


def test_the_random_control_is_produced_by_the_function_it_is_checking(receipt):
    """The floor check has to be able to fail.

    The first version computed ``found / expected`` inline, where ``expected`` is the mean
    of ``found`` under a uniform shuffle, so its answer was 1.0 by identity. It returned 1.0
    with the queue reversed, with every conflict flag inverted, and with ``compute_lift``
    replaced by a function that raises. A control invariant under the framework being broken
    is a measurement of the random number generator, and it was sold as the floor the whole
    comparison rests on.

    Two properties make it a check again: every permutation's lift comes back from the
    shipped ``compute_lift``, and the permutations differ from each other. If every shuffle
    found the same number of conflicts inside the budget, the shuffle is not shuffling.
    """
    control = receipt["random_ordering_control"]
    assert control["computed_by"] == "pipeline.tracetriage.queue.compute_lift"
    counts = control["distinct_conflict_counts_at_budget"]
    assert len(counts) > 1, (
        f"every one of {control['n_permutations']} shuffles found {counts} conflicts "
        "inside the budget, so the permutations are not distinct populations"
    )
    assert control["abs_error"] < 0.01


def test_the_permutation_test_answers_the_question_the_bootstrap_does_not(receipt):
    """How often does a random ordering match the shipped queue.

    The bootstrap interval says how far the lift moves when the population is resampled.
    It does not say whether an ordering that knows nothing could have produced the same
    result, which is the question circularity raises. The permutation p-value does, without
    the threshold and without the bootstrap.
    """
    control = receipt["random_ordering_control"]
    n = control["n_permutations"]
    at_or_above = control["n_permutations_at_or_above_observed"]
    assert 0 <= at_or_above <= n
    assert control["p_value_permutation"] == pytest.approx(
        round((1 + at_or_above) / (1 + n), 6)
    )
    assert control["observed_lift"] == pytest.approx(
        receipt["reproduction"]["lift_point"]
    )
    assert control["p5"] < 1.0 < control["p95"]


def _min_informative_headroom(receipt) -> float:
    """The headroom threshold the receipt was written against, read back from it.

    Recovered from the narrowest split marked informative and the widest marked not, so
    the assertion cannot pass by importing the same constant the script decided with.
    """
    ok = [
        b["headroom_between_threshold_and_perfection"]
        for b in receipt["ceilings_by_split"].values()
        if b["measurable"] and b["informative"]
    ]
    bad = [
        b["headroom_between_threshold_and_perfection"]
        for b in receipt["ceilings_by_split"].values()
        if b["measurable"] and not b["informative"]
    ]
    if not bad:
        return min(ok) if ok else 0.0
    assert max(bad) < min(ok), "the informative flag is not a threshold on headroom"
    return min(ok)


def test_every_split_gets_a_ceiling_not_only_the_one_that_is_reproduced(receipt):
    """The bound belongs where the scale is narrowest, not only where the analysis runs.

    This file reproduces the chronological split because that is the only ordering the
    receipt carries row by row, and for a while it published a ceiling for that split
    alone. The split that most needs one is cold_combined: 76 observations, 20 conflicts,
    budget 50, so every possible ordering including a perfect oracle caps at 1.520 against
    a 1.500 threshold. Reading that split's NOT_ESTABLISHED as a finding about
    generalisation, on a scale 0.02 wide, reports the budget rather than the queue.
    """
    ceilings = receipt["ceilings_by_split"]
    assert len(ceilings) >= 2
    floor = _min_informative_headroom(receipt)
    for name, block in ceilings.items():
        if not block["measurable"]:
            assert block["not_measurable_reason"]
            continue
        expected = min(block["budget"], block["n_conflicts"]) / (
            block["budget"] * block["n_conflicts"] / block["n_population"]
        )
        assert block["ceiling"] == pytest.approx(expected), name
        assert block["headroom_between_threshold_and_perfection"] == pytest.approx(
            block["ceiling"] - block["threshold"]
        )
        if block["published_lift_point"] is not None:
            assert (
                block["published_lift_point"] <= block["ceiling"] + 1e-9
            ), f"{name} publishes a lift above its own ceiling"
        assert block["informative"] is (
            block["headroom_between_threshold_and_perfection"] >= floor
        ), name


def test_a_split_whose_oracle_barely_clears_the_bar_is_marked_not_informative(receipt):
    """The specific case, named rather than left to the general rule above."""
    narrow = [
        (name, block)
        for name, block in receipt["ceilings_by_split"].items()
        if block["measurable"] and not block["informative"]
    ]
    assert narrow, (
        "no split is marked uninformative. If the corpus changed so that every split has "
        "room between its threshold and a perfect oracle, that is good news and this test "
        "should be deleted with the reason recorded, not weakened"
    )
    for name, block in narrow:
        assert block["ceiling"] < block["threshold"] + 0.10, name
        assert "oracle" in block["note"]
        assert f"{block['ceiling']:.3f}" in block["note"]


def test_the_union_label_is_not_used_when_there_is_no_station_interval(script):
    """min(1.35, nan) is 1.35, so a missing station interval vanishes into a union.

    ``compute_lift`` returns [nan, nan] when the station bootstrap falls below its minimum
    surviving resamples. Taking min and max across the two intervals silently discards it,
    publishes the narrower episode-only interval, and labels it the union of two, which is
    how a NOT_ESTABLISHED becomes a PASSED with nobody touching a threshold.
    ``measure_gate6_split`` checks the station verdict and relabels; this file did not.
    """
    ranked = [
        {
            "obs_id": i,
            "episode_key": f"{i % 3}:2:{i}",
            "reasons": ["STALE_CATALOGUE_FREQ"] if i < 6 else ["NO_REASON"],
        }
        for i in range(30)
    ]

    real = script._lift
    calls = {"n": 0}

    def fake_lift(entries, flags, budget, *, group):
        out = real(entries, flags, budget, group=group)
        if group == "station":
            calls["n"] += 1
            return {
                **out,
                "verdict": "NOT_MEASURABLE",
                "lift_ci95": [float("nan"), float("nan")],
                "not_measurable_reason": "too few surviving resamples",
            }
        return out

    script._lift = fake_lift
    try:
        block = script._target(ranked, ("STALE_CATALOGUE_FREQ",), 10)
    finally:
        script._lift = real

    assert calls["n"] == 1
    assert block["governing_interval"] == "episode_only"
    assert block["lift_ci95_station"] is None
    assert block["station_interval_note"]
    assert all(v == v for v in block["lift_ci95"]), "a nan reached the governing interval"


def test_the_shipped_receipt_governs_on_the_union(receipt):
    """The branch above is the failure case. On this data both intervals exist."""
    for name, block in receipt["targets"].items():
        if not block.get("measurable"):
            continue
        if block["governing_interval"] == "union_of_episode_and_station":
            assert block["lift_ci95_station"] is not None, name
            assert block["station_interval_note"] is None, name
        else:
            assert block["lift_ci95_station"] is None, name
            assert block["station_interval_note"], name
