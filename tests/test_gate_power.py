"""Every unmet gate must carry a reason, and the reason must be derivable without the script.

`artifacts/GATE_POWER_RECEIPT.json` answers the question a reader asks first: four of six
gates are not met, so is that a fact about the project or about the measurement. A receipt
that answered it by restating the script's own arithmetic would be worth nothing, so the
checks below recompute each closure condition from a different direction. The Clopper-Pearson
bound is recomputed out of `scipy.stats.beta` rather than out of the closed form the script
uses; the room rule is recomputed from the circularity receipt rather than read out of the
gate power receipt; and every verdict is compared against the receipt that decided it, because
the one thing this script must never do is move a gate while explaining it.

The defect this exists for, stated plainly: a submission with four unmet gates and no measured
account of why is indistinguishable from one that did not try. The account has to be as
checkable as the gates.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
from scipy.stats import beta

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts"
RECEIPT = ARTIFACTS / "GATE_POWER_RECEIPT.json"

#: Where each gate's verdict actually lives. The gate power receipt copies these and must
#: never disagree with them: an explanation that quietly restates a verdict is a second
#: source of truth for the one field this project cannot afford two of.
_VERDICT_SOURCE = {
    3: ("GATE3_RECEIPT.json", ("verdict",)),
    4: ("GATE4_RECEIPT.json", ("verdict",)),
    5: ("FUSION_RECEIPT.json", ("gate5", "verdict")),
    6: ("QUEUE_RECEIPT.json", ("gate6", "verdict")),
}


def _load_script():
    path = REPO / "scripts" / "run_gate_power.py"
    spec = importlib.util.spec_from_file_location("run_gate_power", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_gate_power"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture(scope="module")
def receipt() -> dict:
    if not RECEIPT.exists():
        pytest.skip("artifacts/GATE_POWER_RECEIPT.json is absent. Run scripts/run_gate_power.py.")
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _dig(payload: dict, path: tuple[str, ...]):
    for key in path:
        payload = payload[key]
    return payload


def _by_gate(receipt: dict, gate: int) -> dict:
    return next(g for g in receipt["gates"] if g["gate"] == gate)


# --------------------------------------------------------------------------------------
# The property the whole receipt exists for.
# --------------------------------------------------------------------------------------


def test_every_unmet_gate_carries_a_named_binding_constraint(receipt):
    """The claim on the tin. A gate with no reason is the failure mode being prevented."""
    unexplained = [
        g["gate"] for g in receipt["gates"] if not g["met"] and not g["binding_constraint"]
    ]
    assert not unexplained, (
        f"gates {unexplained} are unmet with no binding constraint named. Either work out "
        f"why or say that it is unknown, but not silence."
    )
    assert receipt["every_unmet_gate_has_a_named_constraint"] is True


def test_every_unmet_gate_carries_a_closure_condition(receipt):
    for gate in receipt["gates"]:
        if gate["met"]:
            continue
        closure = gate["closure"]
        # Three kinds, and the distinction the assertion protects is arithmetic against
        # projection. `not_a_shortfall` is the third: arithmetic, and the answer is that
        # there is no count to add. It was omitted here while no gate produced it, so the
        # first gate that did failed this test rather than the one checking its content.
        assert closure["kind"] in {"exact", "extrapolated", "not_a_shortfall"}, (
            f"gate {gate['gate']} closure is {closure['kind']!r}, and a reader has to be "
            f"able to tell an arithmetic result from a projection from a gate that is not "
            f"short of anything"
        )
        if closure["kind"] == "not_a_shortfall":
            assert closure["shortfall"] == 0, (
                f"gate {gate['gate']} says it is not short of anything and then reports a "
                f"shortfall of {closure['shortfall']}"
            )
        assert closure["statement"].strip()


def test_an_extrapolated_closure_states_its_assumptions(receipt):
    """An estimate that does not say what it assumes reads as a measurement."""
    for gate in receipt["gates"]:
        closure = gate["closure"]
        if closure.get("kind") != "extrapolated":
            continue
        assert closure.get("assumptions", "").strip(), (
            f"gate {gate['gate']} publishes an extrapolated required-n with no assumptions"
        )


def test_the_receipt_moves_no_verdict(receipt):
    """It explains gates. The moment it can change one, it is not an explanation."""
    for gate_number, (filename, path) in _VERDICT_SOURCE.items():
        source = json.loads((ARTIFACTS / filename).read_text(encoding="utf-8"))
        assert _by_gate(receipt, gate_number)["verdict"] == _dig(source, path), (
            f"gate {gate_number}'s verdict in GATE_POWER_RECEIPT disagrees with "
            f"{filename}, which is the file that decided it"
        )


def test_the_tally_is_the_gates_it_lists(receipt):
    assert receipt["n_gates"] == len(receipt["gates"]) == 6
    assert receipt["n_met"] == sum(1 for g in receipt["gates"] if g["met"])
    assert receipt["n_unmet"] == sum(1 for g in receipt["gates"] if not g["met"])
    assert receipt["n_met"] + receipt["n_unmet"] == receipt["n_gates"]


# --------------------------------------------------------------------------------------
# Gate 3: the exact bound, recomputed out of a different implementation.
# --------------------------------------------------------------------------------------


def test_the_closed_form_bound_matches_scipy(script):
    """`alpha ** (1/n)` is the Clopper-Pearson lower bound at k = n, and this proves it."""
    for n in range(1, 30):
        closed_form = 0.05 ** (1 / n)
        exact = beta.ppf(0.05, n, 1)
        assert closed_form == pytest.approx(exact, abs=1e-12), (
            f"at n={n} the closed form gives {closed_form} and the exact beta quantile "
            f"gives {exact}"
        )


@pytest.mark.parametrize("threshold", [0.5, 0.7, 0.8, 0.9, 0.95])
def test_smallest_n_clearing_is_the_smallest(script, threshold):
    """It must clear at n and fail at n-1, or it is not the smallest."""
    n = script.smallest_n_clearing(threshold)
    assert beta.ppf(0.05, n, 1) >= threshold
    assert n == 1 or beta.ppf(0.05, n - 1, 1) < threshold


def test_gate3_needs_nine_testable_observations(script, receipt):
    """The number a reader will quote, pinned so a refactor cannot drift it."""
    assert script.smallest_n_clearing(0.70) == 9
    gate3 = _by_gate(receipt, 3)
    if gate3["met"]:
        pytest.skip("gate 3 is met, so it has no shortfall to check")
    closure = gate3["closure"]
    assert closure["required_n"] == 9

    # What `have_n` counts depends on what the gate is short of, and the gate is not
    # always short of observations. This asserted `have_n == observations_testable`
    # unconditionally, which compared 68 episodes against 303 observations the first time
    # the gate came back short of independent station-nights instead.
    constraint = gate3["binding_constraint"]
    if constraint == "testable_sample_size":
        assert closure["have_n"] == gate3["measured"]["observations_testable"]
        assert closure["shortfall"] == closure["required_n"] - closure["have_n"]
    elif constraint == "independent_episodes":
        assert closure["have_n"] == gate3["measured"]["groups_scored"]
        assert closure["shortfall"] == max(
            0, closure["required_n"] - closure["have_n"]
        )
    elif constraint == "grouped_rate_below_the_bar":
        # The state this branch exists for: more independent episodes than a perfect run
        # would need, and a rate over them that is under the bar. Reported as a shortfall
        # of 9 against 68 once, which an outside judge read as a claim that 9 episodes had
        # all discriminated. So the two group counts are asserted, not just the kind.
        assert closure["kind"] == "not_a_shortfall"
        assert closure["shortfall"] == 0
        assert closure["have_n"] == gate3["measured"]["groups_scored"]
        need_k = closure["required_discriminating_groups"]
        have_k = closure["have_discriminating_groups"]
        assert isinstance(need_k, int) and isinstance(have_k, int)
        assert have_k < need_k <= closure["have_n"], (need_k, have_k, closure["have_n"])
        # The number quoted has to be the smallest that clears, or it is not the answer.
        threshold = gate3["measured"]["threshold"]
        assert script.exact_lower_bound(need_k, closure["have_n"]) >= threshold
        assert script.exact_lower_bound(need_k - 1, closure["have_n"]) < threshold
        # And the count it reports as observed has to reproduce the published bound.
        source = json.loads((ARTIFACTS / "GATE3_RECEIPT.json").read_text(encoding="utf-8"))
        grouping = source["entity_grouping"]
        assert have_k == round(
            grouping["grouped_discriminating_rate"] * grouping["groups_scored"]
        )
        assert script.exact_lower_bound(have_k, closure["have_n"]) == pytest.approx(
            grouping["grouped_rate_lower_bound_95"]
        )
        # The sentence must not offer a sample size as the lever.
        assert "Not more episodes" in closure["statement"]
    elif constraint == "measured_rate_below_the_bar":
        # Not a shortfall. More observations of the same kind move the interval towards
        # a number that is already under the bar.
        assert closure["kind"] == "not_a_shortfall"
        assert closure["shortfall"] == 0
    else:
        raise AssertionError(
            f"gate 3 reports binding constraint {constraint!r}, which this test does "
            f"not know how to check. Add the branch rather than widening the assertion."
        )


def test_gate3_reports_the_bound_its_own_receipt_carries(receipt):
    source = json.loads((ARTIFACTS / "GATE3_RECEIPT.json").read_text(encoding="utf-8"))
    measured = _by_gate(receipt, 3)["measured"]
    assert measured["rate_lower_bound_95"] == source["rate_lower_bound_95"]
    assert measured["observations_testable"] == source["observations_testable"]
    assert measured["threshold"] == source["threshold"]


# --------------------------------------------------------------------------------------
# Gate 6: the room rule, recomputed from the circularity receipt.
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rooms() -> list[dict]:
    """Room, width and verdict per split, computed here rather than read from the receipt."""
    circularity = json.loads((ARTIFACTS / "CIRCULARITY_RECEIPT.json").read_text(encoding="utf-8"))
    out = []
    for name, split in sorted(circularity["ceilings_by_split"].items()):
        if not split.get("measurable"):
            continue
        low, high = split["published_lift_ci95"]
        out.append(
            {
                "split": name,
                "room": split["ceiling"] - split["threshold"],
                "width": high - low,
                "passed": split["published_verdict"] == "PASSED",
                "upper_is_ceiling": abs(high - split["ceiling"]) < 1e-9,
            }
        )
    return out


def test_the_room_rule_predicts_every_measurable_split(rooms):
    """One variable, and it is not the ranker.

    If this ever fails, the rule has stopped holding and the paragraph the README and the
    console both build on it has to be rewritten rather than quietly left standing. That is
    the correct outcome: the finding is that the rule holds, so the test is the finding.
    """
    assert len(rooms) >= 4, f"only {len(rooms)} measurable splits; the rule needs a corpus"
    wrong = [r["split"] for r in rooms if (r["width"] <= r["room"]) != r["passed"]]
    assert not wrong, (
        f"the room rule mispredicts {wrong}. Whether the interval fits inside the room "
        f"above the threshold no longer tracks the verdict."
    )


def test_at_least_one_split_passed_and_at_least_one_did_not(rooms):
    """A rule with no variation in its outcome is not a rule."""
    assert any(r["passed"] for r in rooms), "no split passed, so the rule predicts a constant"
    assert any(not r["passed"] for r in rooms), "every split passed, same problem"


def test_the_receipt_agrees_with_the_independently_computed_rooms(receipt, rooms):
    published = {
        r["split"]: r for r in _by_gate(receipt, 6)["the_room_rule"]["per_split"] if r["measurable"]
    }
    assert set(published) == {r["split"] for r in rooms}
    for mine in rooms:
        theirs = published[mine["split"]]
        assert theirs["room_above_the_threshold"] == pytest.approx(mine["room"])
        assert theirs["interval_width"] == pytest.approx(mine["width"])
        assert theirs["interval_fits_in_the_room"] == (mine["width"] <= mine["room"])
        assert theirs["upper_bound_is_the_ceiling"] == mine["upper_is_ceiling"]


def test_a_truncated_interval_is_named_as_one(receipt, rooms):
    """Where the bootstrap's upper bound is the arithmetic ceiling, the receipt says so."""
    mine = {r["split"] for r in rooms if r["upper_is_ceiling"]}
    theirs = set(
        _by_gate(receipt, 6)["the_room_rule"]["splits_whose_interval_is_truncated_by_the_ceiling"]
    )
    assert mine == theirs
    assert mine, (
        "no split's interval is truncated by its ceiling, so the strongest sentence in "
        "the gate 6 explanation no longer has a case behind it"
    )


def test_gate6_publishes_the_counterexample_to_the_easy_extrapolation(receipt, rooms):
    """cold_transmitter is larger than chronological and still fails. Say so, or mislead."""
    by_name = {r["split"]: r for r in rooms}
    if "cold_transmitter" not in by_name or "chronological" not in by_name:
        pytest.skip("the two splits the caveat rests on are not both measurable")
    published = {
        r["split"]: r for r in _by_gate(receipt, 6)["the_room_rule"]["per_split"] if r["measurable"]
    }
    bigger = published["cold_transmitter"]["n_population"]
    smaller = published["chronological"]["n_population"]
    if not (bigger > smaller and not by_name["cold_transmitter"]["passed"]):
        pytest.skip("the counterexample no longer holds on this corpus")
    assert _by_gate(receipt, 6)["closure"]["counterexample_to_the_obvious_extrapolation"].strip(), (
        "a larger split that still fails is in this corpus and the receipt does not "
        "mention it, so its closure condition reads as though more rows would be enough"
    )


# --------------------------------------------------------------------------------------
# Gate 5: the extrapolation, recomputed.
# --------------------------------------------------------------------------------------


def test_gate5_required_n_scales_as_the_square_of_the_arm_over_the_margin(receipt):
    import math

    fusion = json.loads((ARTIFACTS / "FUSION_RECEIPT.json").read_text(encoding="utf-8"))
    split = fusion["gate5"]["per_split"]["chronological"]
    gate5 = _by_gate(receipt, 5)
    if gate5["met"]:
        pytest.skip("gate 5 is met")
    lower_arm = split["margin"] - split["ci95"][0]
    expected = math.ceil(split["n_observations"] * (lower_arm / split["margin"]) ** 2)
    assert gate5["closure"]["required_n"] == expected
    assert gate5["closure"]["have_n"] == split["n_observations"]
    assert gate5["closure"]["required_n"] > gate5["closure"]["have_n"], (
        "an extrapolated requirement below the sample already in hand would mean the gate "
        "should have cleared, which contradicts its own verdict"
    )


# --------------------------------------------------------------------------------------
# The script's own guards.
# --------------------------------------------------------------------------------------


def test_check_passes_against_the_committed_receipt(script):
    assert script.main(["--check"]) == 0


def test_check_fails_when_the_receipt_is_stale(script, tmp_path, monkeypatch):
    """--check has to be able to fail, or running it in the gate proves nothing."""
    stale = json.loads(RECEIPT.read_text(encoding="utf-8"))
    stale["n_unmet"] = 999
    target = tmp_path / "GATE_POWER_RECEIPT.json"
    target.write_text(json.dumps(stale, indent=1) + "\n", encoding="utf-8")
    monkeypatch.setattr(script, "OUT", target)
    assert script.main(["--check"]) == 1


def test_generated_at_alone_does_not_make_it_stale(script, tmp_path, monkeypatch):
    """Otherwise the gate fails on every clean checkout for no reason at all."""
    drifted = json.loads(RECEIPT.read_text(encoding="utf-8"))
    drifted["generated_at"] = "1999-01-01T00:00:00+00:00"
    target = tmp_path / "GATE_POWER_RECEIPT.json"
    target.write_text(json.dumps(drifted, indent=1) + "\n", encoding="utf-8")
    monkeypatch.setattr(script, "OUT", target)
    assert script.main(["--check"]) == 0


# --------------------------------------------------------------------------------------
# The summary paragraph, which is the part of this receipt most able to go stale.
# --------------------------------------------------------------------------------------


def test_the_reading_paragraph_names_only_gates_that_are_not_met(receipt):
    """It said "gate 4 is short of a reviewer" for a while after a person answered it.

    The sentence was typed beside the gates rather than derived from them, so a verdict
    moving left it describing a state the table two fields above already contradicted.
    """
    named = {int(n) for n in re.findall(r"[Gg]ates? ((?:\d+(?:, )?)+)", receipt["reading"])
             for n in re.findall(r"\d+", n)}
    named |= {
        int(n)
        for chunk in re.findall(r"[Gg]ates? [\d, ]+and (\d+)", receipt["reading"])
        for n in [chunk]
    }
    unmet = {g["gate"] for g in receipt["gates"] if not g["met"]}
    assert named <= unmet, f"the paragraph names gates that are met: {sorted(named - unmet)}"
    assert named == unmet, f"the paragraph is silent about {sorted(unmet - named)}"


def test_the_reading_paragraph_opens_with_the_counts_it_can_be_checked_against(receipt):
    words = {0: "no", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    unmet = [g for g in receipt["gates"] if not g["met"]]
    exact = [g for g in unmet if g["closure"]["kind"] == "exact"]
    if not unmet:
        assert receipt["reading"].startswith("Every gate is met")
        return
    noun = "constraint" if len(unmet) == 1 else "constraints"
    opening = f"{words[len(unmet)].capitalize()} {noun}, {words[len(exact)]} of them exact."
    assert receipt["reading"].startswith(opening), receipt["reading"][:120]


def test_the_reading_paragraph_follows_a_verdict_that_moves(script):
    """Flip a gate by hand and require the sentence to stop naming it.

    Without this the paragraph could be a constant that happens to be right today.
    """
    gates = script.build()["gates"]
    before = script._reading(gates)
    unmet = [g for g in gates if not g["met"]]
    assert unmet, "this checkout has no unmet gate to flip, so the test proves nothing"

    flipped = [dict(g) for g in gates]
    target = next(g for g in flipped if not g["met"])
    target["met"] = True
    after = script._reading(flipped)
    assert after != before
    assert f"Gate {target['gate']} is" not in after
    assert f"gate {target['gate']} is" not in after


def test_an_unnamed_binding_constraint_stops_the_run(script):
    """A new constraint has to be given words, not summarised as nothing."""
    gates = [
        {
            "gate": 9,
            "met": False,
            "binding_constraint": "something_nobody_has_described_yet",
            "closure": {"kind": "exact", "frozen_by_pre_registration": False},
        }
    ]
    with pytest.raises(SystemExit) as caught:
        script._reading(gates)
    assert "something_nobody_has_described_yet" in str(caught.value)


def test_every_closure_says_whether_pre_registration_freezes_it(receipt):
    """"Short of data" and "short of data we are not allowed to collect" are not the same.

    The distinction is what separates a reason from an excuse, so it is a field rather
    than a turn of phrase inside a paragraph.
    """
    for gate in receipt["gates"]:
        assert isinstance(gate["closure"]["frozen_by_pre_registration"], bool), gate["gate"]
    frozen = [g["gate"] for g in receipt["gates"] if g["closure"]["frozen_by_pre_registration"]]
    assert frozen == [5, 6], frozen


def test_exactly_one_closure_is_an_extrapolation(receipt):
    """Gate 5's own text says every other closure here is exact. This is that claim."""
    kinds = [g["closure"]["kind"] for g in receipt["gates"]]
    assert kinds.count("extrapolated") == 1, kinds
    extrapolated = next(g for g in receipt["gates"] if g["closure"]["kind"] == "extrapolated")
    assert extrapolated["gate"] == 5
    assert "every other closure here is not" in extrapolated["closure"]["assumptions"]


# --------------------------------------------------------------------------------------
# Gate 3's closure has four states. It used to have one.
# --------------------------------------------------------------------------------------


def _g3_receipt(verdict, scored, hits, bound, threshold=0.70, groups=None,
                grouped_bound=None, grouped_rate=None):
    """The fields `_gate3` reads, and nothing else."""
    return {
        "threshold": threshold,
        "verdict": verdict,
        "observations_testable": scored,
        "observations_not_testable": 4,
        "observations_scored": scored,
        "discriminating_rate": (hits / scored) if scored else 0.0,
        "rate_lower_bound_95": bound,
        "entity_grouping": {
            "groups_scored": groups,
            "grouped_rate_lower_bound_95": grouped_bound,
            "grouped_discriminating_rate": grouped_rate,
        },
    }


def test_a_met_gate_3_is_not_described_as_short_of_anything():
    """The state the original could not express at all.

    Every sentence in the first version assumed the gate was open and short of
    observations. A met gate would still have been published with a sample-size
    shortfall and a paragraph explaining why its rate could not be established.
    """
    from scripts.run_gate_power import _gate3

    g = _gate3(_g3_receipt("PASSED", scored=250, hits=230, bound=0.8790))
    assert g["met"] is True
    assert g["binding_constraint"] is None
    assert g["closure"]["shortfall"] == 0
    assert g["closure"]["kind"] == "closed"
    assert "cannot be established" not in g["why_it_landed_here"]


def test_a_rate_below_the_bar_is_not_called_a_sample_size_shortfall():
    """The dangerous misdescription, and the reason this was worth fixing before the run.

    A gate whose rate comes in under the threshold measured something. Calling that a
    shortage of observations tells a reader it is an afternoon of vetting from closing,
    and `_SHORTFALL_IN_A_PHRASE` renders it in exactly those words. No amount of vetting
    moves a rate that is already below the bar towards it.
    """
    from scripts.run_gate_power import _gate3

    g = _gate3(_g3_receipt("FAILED", scored=200, hits=90, bound=0.3900))
    assert g["met"] is False
    assert g["binding_constraint"] == "measured_rate_below_the_bar"
    assert g["closure"]["kind"] == "not_a_shortfall"
    assert g["closure"]["shortfall"] == 0
    assert "larger pool" in g["closure"]["what_it_would_take"]
    assert "measurement rather than a sample-size result" in g["why_it_landed_here"]


def test_clearing_on_observations_but_not_on_groups_is_its_own_constraint():
    """More of the same passes cannot close it, and the phrase has to say so."""
    from scripts.run_gate_power import _gate3

    g = _gate3(_g3_receipt(
        "PASSED_UNGROUPED_ONLY", scored=180, hits=175, bound=0.9500,
        groups=4, grouped_bound=0.4729,
    ))
    assert g["met"] is False
    # Four episodes is the state where the count really does bind: even 4 of 4 leaves the
    # bound at 0.05 ** (1/4) = 0.473, so no rate over four episodes clears a 0.7 bar.
    assert g["binding_constraint"] == "independent_episodes"
    assert g["closure"]["have_n"] == 4
    assert "more stations and more nights" in g["closure"]["what_it_would_take"]
    assert "no rate over them clears" in g["closure"]["statement"]


def test_a_sufficient_episode_count_with_a_short_rate_names_the_rate():
    """The other state behind the same verdict, and the one the real receipt is in.

    68 episodes is past the point where the count binds, so offering a count as the lever
    is pointing a reader at something they already have seven times over. This is the case
    an outside judge misread as a claim that 9 episodes had all discriminated.
    """
    from scripts.run_gate_power import _gate3

    g = _gate3(_g3_receipt(
        "PASSED_UNGROUPED_ONLY", scored=289, hits=224, bound=0.7309,
        groups=68, grouped_bound=0.3662, grouped_rate=32 / 68,
    ))
    assert g["met"] is False
    assert g["binding_constraint"] == "grouped_rate_below_the_bar"
    closure = g["closure"]
    assert closure["kind"] == "not_a_shortfall"
    assert closure["shortfall"] == 0
    assert closure["required_discriminating_groups"] == 55
    assert closure["have_discriminating_groups"] == 32
    assert closure["statement"].startswith("Not more episodes")
    assert "9 all-discriminating episodes" in closure["statement"]
    assert "not more episodes" in closure["what_it_would_take"]


def test_an_imperfect_rate_is_counted_rather_than_called_perfect():
    """"Every testable observation discriminates" was a hardcoded claim about the data.

    It was true of three of three. The first observation that does not discriminate makes
    it false, in a receipt whose whole purpose is that its sentences follow its numbers.
    """
    from scripts.run_gate_power import _gate3

    g = _gate3(_g3_receipt("NOT_ESTABLISHED", scored=10, hits=8, bound=0.4930))
    assert "8 of 10 testable observations discriminate" in g["why_it_landed_here"]
    assert "Every testable observation" not in g["why_it_landed_here"]

    perfect = _gate3(_g3_receipt("NOT_ESTABLISHED", scored=3, hits=3, bound=0.3684))
    assert "Every testable observation discriminates" in perfect["why_it_landed_here"]
    assert perfect["binding_constraint"] == "testable_sample_size"


def test_every_constraint_gate_3_can_name_has_a_phrase():
    """The reading paragraph raises on an unnamed constraint, so this must stay complete."""
    from scripts.run_gate_power import _SHORTFALL_IN_A_PHRASE, _gate3

    states = [
        _g3_receipt("PASSED", 250, 230, 0.8790),
        _g3_receipt("PASSED_UNGROUPED_ONLY", 180, 175, 0.95, groups=4,
                    grouped_bound=0.4729),
        _g3_receipt("NOT_ESTABLISHED", 3, 3, 0.3684),
        _g3_receipt("FAILED", 200, 90, 0.3900),
    ]
    named = {_gate3(r)["binding_constraint"] for r in states} - {None}
    missing = sorted(c for c in named if c not in _SHORTFALL_IN_A_PHRASE)
    assert not missing, (
        f"_gate3 can name {missing} and the reading paragraph has no phrase for them, so "
        f"scripts/run_gate_power.py would raise SystemExit on a real result"
    )
