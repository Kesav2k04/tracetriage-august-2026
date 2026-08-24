"""Why each kill gate landed where it did, and the exact condition that would move it.

Some of the six kill gates are not met, and a reader is entitled to ask whether that is a
fact about the project or a fact about the measurement. "The interval was wide" is a plea.
This computes the answer instead, one gate at a time, from receipts that are already
committed, and it refuses to finish if any unmet gate comes out without a named binding
constraint.

The finding it exists to publish is about gate 6. Its verdict is not decided by the queue.
Define, per split:

    ceiling = the lift a perfect oracle scores at that split's budget
    room    = ceiling - threshold, the whole distance the measurement has to land in
    width   = the width of the published 95% interval

On all four measurable splits, ``width <= room`` predicts the verdict exactly: the one
split where the interval fits inside the room is the one split that passed, and on two of
the three that did not, the interval's upper bound **is** the ceiling, meaning the
resampling cannot produce a higher number however good the ranking is. A gate whose
interval is truncated by the arithmetic of its own split is not measuring the ranker.

What this is not. It is not a re-litigation of a verdict and it moves nothing: every
verdict here is read from the receipt that decided it, and this script writes no verdict of
its own. Every closure condition here is exact except one, which is an extrapolation, and
they are labelled ``exact`` and ``extrapolated`` so the difference cannot be lost by
quoting. The extrapolation is deliberately given the counterexample that limits it:
``cold_transmitter`` has 95 observations against ``chronological``'s 87 and still fails, so
interval width is not a function of split size alone, and any required-n computed by
holding the observed width fixed is an estimate rather than a promise.

Usage::

    .venv/Scripts/python.exe scripts/run_gate_power.py
    .venv/Scripts/python.exe scripts/run_gate_power.py --check
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts"
OUT = ARTIFACTS / "GATE_POWER_RECEIPT.json"

#: A gate is met when its verdict is one of these. PRE_PASSED is a feasibility check
#: answered before the build rather than a result, and it is counted as met because that is
#: how every other surface counts it, not because the two mean the same thing.
MET = frozenset({"PASSED", "PRE_PASSED"})

#: Gate 6's threshold, and gate 3's. Both are read from their receipts rather than typed
#: here; these names exist so a reader can see which receipt field is the bar.
_GATE6_THRESHOLD_FIELD = "threshold"


def _shown(path: Path) -> str:
    """The path as a reader of this repository would write it, or absolute if it is not in one.

    ``relative_to`` raises when the target sits outside the tree, which happens whenever a
    test points ``OUT`` at a temporary directory. A message-formatting call that can raise
    turns a clean non-zero exit into a traceback, so the failure it was reporting becomes
    unreadable.
    """
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _load(name: str) -> dict[str, Any]:
    path = ARTIFACTS / name
    if not path.exists():
        raise SystemExit(
            f"{_shown(path)} is missing, so there is nothing to explain. "
            f"This script reads receipts and computes none of the measurements itself."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def smallest_n_clearing(threshold: float, confidence: float = 0.95) -> int:
    """The fewest trials whose exact one-sided lower bound clears ``threshold`` at k = n.

    At a perfect observed rate the Clopper-Pearson one-sided lower bound is
    ``alpha ** (1 / n)``, so this inverts that rather than searching. It answers the only
    question a 3-of-3 result leaves open: how many more of the same would have been enough.
    """
    alpha = 1.0 - confidence
    if not 0.0 < threshold < 1.0:
        raise ValueError(f"threshold must sit strictly inside (0, 1), got {threshold}")
    return math.ceil(math.log(alpha) / math.log(threshold))


def smallest_k_clearing(trials: int, threshold: float, confidence: float = 0.95) -> int | None:
    """The fewest successes out of ``trials`` whose exact lower bound clears ``threshold``.

    The companion to `smallest_n_clearing`, and the one gate 3 actually needs. That
    function answers "how many perfect trials would be enough", which is the right
    question only while the observed rate is perfect. Once it is not, the sample size
    stops being the constraint and the rate becomes it, and a reader told the gate needs
    9 episodes when the corpus already holds 68 has been pointed at the wrong lever.

    Same estimator as `scripts/run_gate3.py::rate_lower_bound`, so the number this returns
    and the bound the receipt published are the same arithmetic. Returns None when no k
    clears, which cannot happen for a threshold under one but is not worth asserting away.
    """
    if trials <= 0:
        return None
    alpha = 1.0 - confidence
    from scipy.stats import beta

    for k in range(1, trials + 1):
        if k == trials:
            bound = alpha ** (1.0 / trials)
        else:
            bound = float(beta.ppf(alpha, k, trials - k + 1))
        if bound >= threshold:
            return k
    return None


def exact_lower_bound(successes: int, trials: int, confidence: float = 0.95) -> float | None:
    """One value of the same estimator, for reporting the rung below the one that clears."""
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    alpha = 1.0 - confidence
    if successes == 0:
        return 0.0
    if successes == trials:
        return float(alpha ** (1.0 / trials))
    from scipy.stats import beta

    return float(beta.ppf(alpha, successes, trials - successes + 1))


def _grouped_rate_closure(
    *,
    groups: int,
    grouped_hits: int | None,
    grouped_bound: float | None,
    need_k: int,
    below: float | None,
    needed: int,
    threshold: float,
    bound: float,
) -> dict[str, Any]:
    """The closure for a gate whose episode count is sufficient and whose rate is not.

    Kept out of `_gate3` so the two states that share the PASSED_UNGROUPED_ONLY verdict
    read as two things. `not_a_shortfall` is the honest kind: there is no count to add.
    """
    return {
        "kind": "not_a_shortfall",
        "frozen_by_pre_registration": False,
        "required_n": needed,
        "have_n": groups,
        "shortfall": 0,
        "required_discriminating_groups": need_k,
        "have_discriminating_groups": grouped_hits,
        "statement": (
            f"Not more episodes. This corpus has {groups} independent (station, date) "
            f"episodes, which already exceeds the {needed} all-discriminating episodes "
            f"that would clear a {threshold} bar on their own, and {grouped_hits} of the "
            f"{groups} discriminate on every capture, putting the grouped bound at "
            f"{grouped_bound:.3f}. Clearing {threshold} at {groups} episodes takes "
            f"{need_k} of them"
            + (f", and at {need_k - 1} the bound is {below:.3f}" if below is not None else "")
            + f". The observation-level bound clears {threshold} at {bound:.3f}; the "
            f"pre-registration's rule is to group, so the observation-level pass is "
            f"reported and not "
            f"claimed."
        ),
        "what_it_would_take": (
            "Episodes in which every capture discriminates, not more episodes. A hundred "
            "more passes over the same receiver on the same night is one episode measured "
            "a hundred times, and the pre-registered statistic counts an episode with one "
            "failure among twenty the same as one with twenty, so it is stricter than the "
            "gate's own wording and it decides."
        ),
    }


def _gate3(receipt: dict[str, Any]) -> dict[str, Any]:
    """What is actually holding gate 3 open, which is not always the same thing.

    This used to assert one state: short of testable observations, perfect on the ones it
    had. That was true of three of three and is not a property of the gate. A rate below
    the bar is not a sample-size shortfall, and saying it is would tell a reader the gate
    is an afternoon of vetting away from closing when no amount of vetting would close it.
    """
    threshold = receipt["threshold"]
    testable = receipt["observations_testable"]
    not_testable = receipt["observations_not_testable"]
    scored = receipt.get("observations_scored", testable)
    rate = receipt["discriminating_rate"]
    bound = receipt["rate_lower_bound_95"]
    hits = round(rate * scored) if scored else 0
    needed = smallest_n_clearing(threshold)
    verdict = receipt["verdict"]
    met = verdict in MET
    grouping = receipt.get("entity_grouping") or {}

    perfect = scored > 0 and hits == scored
    counted = (
        "Every testable observation discriminates"
        if perfect
        else f"{hits} of {scored} testable observations discriminate"
    )

    if met:
        constraint = None
        closure = {
            "kind": "closed",
            "frozen_by_pre_registration": False,
            "required_n": needed,
            "have_n": testable,
            "shortfall": 0,
            "statement": "Nothing. The gate is met.",
            "what_it_would_take": "Nothing further: the interval clears the threshold.",
        }
        why = (
            f"{counted}, and the exact one-sided 95% lower bound is {bound:.4f} against a "
            f"{threshold} bar, so the interval clears it and the verdict follows the "
            f"interval rather than the point estimate."
        )
    elif verdict == "PASSED_UNGROUPED_ONLY":
        # Two different states wear this verdict, and telling them apart is the whole job
        # of this branch. If the episode count is small enough that no achievable rate
        # clears the bar, the count binds. If the count is already past that point, the
        # rate binds and offering a count is pointing at the wrong lever. This used to
        # report the count in both cases, publishing `required_n` = 9 beside `have_n` = 68
        # and a shortfall of 0; an outside judge read that cell as a claim that 9 episodes
        # had all discriminated.
        groups = grouping.get("groups_scored")
        grouped_rate = grouping.get("grouped_discriminating_rate")
        grouped_bound = grouping.get("grouped_rate_lower_bound_95")
        grouped_hits = (
            round(grouped_rate * groups)
            if grouped_rate is not None and groups is not None
            else None
        )
        need_k = smallest_k_clearing(groups, threshold) if groups else None
        below = exact_lower_bound(need_k - 1, groups) if need_k and need_k > 1 else None
        if need_k is None:
            # No number of all-discriminating episodes clears the bar at this count, so
            # the count is what binds and more episodes is the honest answer.
            constraint = "independent_episodes"
            closure = {
                "kind": "exact",
                "frozen_by_pre_registration": False,
                "required_n": needed,
                "have_n": groups if groups is not None else testable,
                "shortfall": max(0, needed - (groups or 0)),
                "statement": (
                    f"{needed} independent (station, date) episodes, all discriminating. "
                    f"At the {groups} this corpus has, no rate over them clears "
                    f"{threshold}: even all {groups} discriminating leaves the bound at "
                    f"{exact_lower_bound(groups, groups):.3f}. The observation-level bound "
                    f"already clears {threshold} at {bound:.3f}; the pre-registration's rule is "
                    f"to "
                    f"group, so the observation-level pass is reported and not claimed."
                ),
                "what_it_would_take": (
                    "Observations from more stations and more nights, not more "
                    "observations. A hundred more passes over the same receiver on the "
                    "same night is one episode measured a hundred times."
                ),
            }
        else:
            constraint = "grouped_rate_below_the_bar"
            closure = _grouped_rate_closure(
                groups=groups,
                grouped_hits=grouped_hits,
                grouped_bound=grouped_bound,
                need_k=need_k,
                below=below,
                needed=needed,
                threshold=threshold,
                bound=bound,
            )
        why = (
            f"{counted}, and the observation-level bound of {bound:.4f} clears the "
            f"{threshold} bar while the grouped bound over {groups} independent episodes "
            f"does not. Observations from one receiver on one night share that receiver's "
            f"local-oscillator error, so they are one systematic offset measured many "
            f"times rather than many independent confirmations."
        )
    elif rate >= threshold:
        constraint = "testable_sample_size"
        closure = {
            "kind": "exact",
            "frozen_by_pre_registration": False,
            "required_n": needed,
            "have_n": testable,
            "shortfall": max(0, needed - testable),
            "statement": (
                f"{needed} testable observations, all discriminating. "
                f"0.05 ** (1/{needed}) = {0.05 ** (1 / needed):.4f}, which is the first n "
                f"whose exact bound clears {threshold}; at n = {needed - 1} it is "
                f"{0.05 ** (1 / (needed - 1)):.4f} and does not. That is "
                f"{max(0, needed - testable)} more than this corpus has vetted, and they "
                f"have to be passes carrying a measurable narrowband trace."
            ),
            "what_it_would_take": (
                "Blinded vetting of more observations from the snapshot already on disk. "
                "The vetting has to be blind to the corridor result, or the rate it "
                "produces is a rate about the vetter."
            ),
        }
        why = (
            f"{counted}, out of {testable}. The rate is {rate * 100:.0f}%, above the "
            f"{threshold * 100:.0f}% bar, and the exact one-sided 95% lower bound is "
            f"{bound:.4f}, which is below it, so the rate cannot be established at this "
            f"sample size however cleanly each observation behaves. The other "
            f"{not_testable} decisive observations have a corridor that is identically "
            f"0 Hz across the whole pass, so it predicts no shape and a null built from it "
            f"reproduces it exactly. There is nothing to test, which is a property of the "
            f"capture convention rather than a shortage of effort."
        )
    else:
        # The one state the original could not express. A rate below the bar is a
        # measurement, not a shortage, and more observations of the same kind move it
        # towards the same answer.
        constraint = "measured_rate_below_the_bar"
        closure = {
            "kind": "not_a_shortfall",
            "frozen_by_pre_registration": False,
            "required_n": needed,
            "have_n": testable,
            "shortfall": 0,
            "statement": (
                f"Nothing countable. The rate itself is {rate * 100:.0f}%, below the "
                f"{threshold * 100:.0f}% bar, before any interval is taken. More "
                f"observations narrow the interval around a number that is already under "
                f"the threshold."
            ),
            "what_it_would_take": (
                "A better corridor or a better presence statistic, not a larger pool. "
                "This is the outcome the gate was written to be able to return."
            ),
        }
        why = (
            f"{counted}, a rate of {rate * 100:.0f}% against a {threshold * 100:.0f}% bar. "
            f"The point estimate is below the threshold before any interval is taken, so "
            f"this is a measurement rather than a sample-size result: the pool was fixed "
            f"in docs/E16_PREREGISTRATION.md before the run, and the corridor did not land "
            f"on the trace often enough."
        )

    return {
        "gate": 3,
        "title": "Corridor intersects a visible trace",
        "verdict": verdict,
        "met": met,
        "binding_constraint": constraint,
        # The denominator has to be the one the bound was computed on. This printed
        # `testable` (303) beside a bound computed from `scored` (289), and 224 of 303 has a
        # one-sided lower bound of 0.694, which fails the 0.7 bar the same sentence quotes.
        # Both numbers are real and the pairing was not, so both are named here.
        "bound_by_in_one_line": (
            f"{scored} of {testable} testable observations scored, {hits} discriminating. "
            f"The exact bound is {bound:.3f} against a {threshold} bar."
        ),
        "measured": {
            "threshold": threshold,
            "observations_testable": testable,
            "observations_not_testable": not_testable,
            "observations_scored": scored,
            "discriminating": hits,
            "discriminating_rate": rate,
            "rate_lower_bound_95": bound,
            "grouped_rate_lower_bound_95": grouping.get("grouped_rate_lower_bound_95"),
            "groups_scored": grouping.get("groups_scored"),
        },
        "why_it_landed_here": why,
        "closure": closure,
    }


def _gate4(receipt: dict[str, Any]) -> dict[str, Any]:
    """Gate 4 is the one unmet gate that is not short of anything except a reviewer."""
    verdict = receipt["verdict"]
    met = verdict in MET
    arm = receipt.get("arm")
    reviewer = receipt.get("reviewer") or (arm or {}).get("reviewer") or {}
    return {
        "gate": 4,
        "title": "Blinded human decidability",
        "verdict": verdict,
        "met": met,
        "binding_constraint": None if met else "no_human_reviewer",
        "bound_by_in_one_line": (
            "Answered." if met else "No person has answered the worksheet. Nothing else is missing."
        ),
        "measured": {
            "reviewer_kind": reviewer.get("kind"),
            "rate": receipt.get("rate", (arm or {}).get("rate")),
            "observations_scored": receipt.get(
                "observations_scored", (arm or {}).get("observations_scored")
            ),
            "the_rate_is_the_gate": "reviewer" in receipt,
        },
        "why_it_landed_here": (
            (
                "A person answered the committed worksheet, so the gate is decided by the "
                "reviewer it names."
            )
            if met
            else (
                "Nothing here is short of data. The instrument is built, the sample and "
                "its order are committed as one salted sha256 per item, and the sizing was "
                "chosen so a true rate of 0.90 would clear the bar. What is missing is a "
                "person, and a review by anything else is published as an arm rather than "
                "folded into the gate."
            )
        ),
        "closure": {
            "kind": "exact",
            "frozen_by_pre_registration": False,
            "statement": (
                "Already closed."
                if met
                else (
                    "One person answers the 72 committed items. No new data, no model, no "
                    "code change. scripts/score_gate4.py refuses to publish a rate without "
                    "a reviewer declaration naming who produced it."
                )
            ),
            "what_it_would_take": (
                "Done." if met else "About half an hour at apps/web/public/gate4/review.html."
            ),
        },
    }


def _gate5(fusion: dict[str, Any]) -> dict[str, Any]:
    """Gate 5's margin points the right way and its interval is wider than the margin."""
    split = fusion["gate5"]["per_split"]["chronological"]
    margin = split["margin"]
    low, high = split["ci95"]
    n = split["n_observations"]
    lower_arm = margin - low
    # The interval narrows as 1/sqrt(n) under the usual assumption, so the n at which the
    # lower arm is no longer wider than the margin scales as the square of their ratio.
    required = math.ceil(n * (lower_arm / margin) ** 2) if margin > 0 else None
    return {
        "gate": 5,
        "title": "Physics beats image-only on Brier",
        "verdict": fusion["gate5"]["verdict"],
        "met": fusion["gate5"]["verdict"] in MET,
        "binding_constraint": "test_set_size",
        "bound_by_in_one_line": (
            f"{n} test observations. The interval's lower arm is "
            f"{lower_arm / margin:.2f} times the margin it has to clear."
        ),
        "measured": {
            "margin": margin,
            "ci95": [low, high],
            "n_observations": n,
            "lower_arm": lower_arm,
            "lower_arm_over_margin": lower_arm / margin if margin else None,
            "challenger_brier": split["challenger_brier"],
            "reference_brier": split["reference_brier"],
        },
        "why_it_landed_here": (
            f"The physics arm is ahead by {margin:.5f} and the interval's lower arm is "
            f"{lower_arm:.5f}, which is {lower_arm / margin:.2f} times the margin it has to "
            f"clear. On {n} test observations an effect this size is not separable from "
            f"zero. The direction is right on both the point estimate and the median of the "
            f"resamples; the evidence simply does not exclude a tie."
        ),
        "closure": {
            "kind": "extrapolated",
            "frozen_by_pre_registration": True,
            "required_n": required,
            "have_n": n,
            "statement": (
                f"About {required} test observations at the same margin, against the {n} "
                f"this split has. That is {required / n:.1f} times the chronological test "
                f"set."
            ),
            "assumptions": (
                "That the margin holds at the larger n and that the interval narrows as "
                "1/sqrt(n). Neither is guaranteed, which is why this is labelled "
                "extrapolated and every other closure here is not."
            ),
            "what_it_would_take": (
                "A larger snapshot. It is also the one closure this project must not "
                "pursue: the chronological split was fixed before the result was seen, and "
                "growing a test set after reading its verdict is the thing pre-registration "
                "exists to prevent. Recorded as the reason it stays open rather than as "
                "work outstanding."
            ),
        },
    }


def _gate6_rooms(circularity: dict[str, Any]) -> list[dict[str, Any]]:
    """Per split: the room the verdict had to land in, against the interval it produced."""
    rooms = []
    for name, split in sorted(circularity["ceilings_by_split"].items()):
        if not split.get("measurable"):
            rooms.append(
                {
                    "split": name,
                    "measurable": False,
                    "reason": split.get("not_measurable_reason"),
                }
            )
            continue
        low, high = split["published_lift_ci95"]
        ceiling = split["ceiling"]
        room = split["headroom_between_threshold_and_perfection"]
        width = high - low
        rooms.append(
            {
                "split": name,
                "measurable": True,
                "n_population": split["n_population"],
                "budget": split["budget"],
                "ceiling": ceiling,
                "threshold": split["threshold"],
                "room_above_the_threshold": room,
                "published_lift_point": split["published_lift_point"],
                "published_lift_ci95": [low, high],
                "interval_width": width,
                "interval_fits_in_the_room": width <= room,
                "upper_bound_is_the_ceiling": abs(high - ceiling) < 1e-9,
                "verdict": split["published_verdict"],
                "passed": split["published_verdict"] in MET,
            }
        )
    return rooms


def _gate6(queue: dict[str, Any], circularity: dict[str, Any]) -> dict[str, Any]:
    rooms = _gate6_rooms(circularity)
    measurable = [r for r in rooms if r["measurable"]]
    rule_holds = all(r["interval_fits_in_the_room"] == r["passed"] for r in measurable)
    truncated = [r["split"] for r in measurable if r["upper_bound_is_the_ceiling"]]
    chron = next(r for r in measurable if r["split"] == "chronological")
    passed = [r for r in measurable if r["passed"]]
    return {
        "gate": 6,
        "title": "Queue lift over random",
        "verdict": queue["gate6"]["verdict"],
        "met": queue["gate6"]["verdict"] in MET,
        "binding_constraint": "split_population_at_a_fixed_budget",
        "bound_by_in_one_line": (
            f"{chron['n_population']} observations at a budget of {chron['budget']} "
            f"cap every ordering at {chron['ceiling']:.3f}x, leaving "
            f"{chron['room_above_the_threshold']:.3f} of room for an interval "
            f"{chron['interval_width']:.3f} wide."
        ),
        "measured": {
            "decided_on": "chronological",
            "n_population": chron["n_population"],
            "budget": chron["budget"],
            "ceiling": chron["ceiling"],
            "room_above_the_threshold": chron["room_above_the_threshold"],
            "interval_width": chron["interval_width"],
            "upper_bound_is_the_ceiling": chron["upper_bound_is_the_ceiling"],
        },
        "why_it_landed_here": (
            f"The measurement is wider than the space it had to land in. At a budget of "
            f"{chron['budget']} over {chron['n_population']} observations a perfect oracle "
            f"caps at {chron['ceiling']:.3f}, so the whole distance between the "
            f"{chron['threshold']} threshold and perfection is "
            f"{chron['room_above_the_threshold']:.3f}, and the published interval is "
            f"{chron['interval_width']:.3f} wide. The interval's upper bound is the ceiling "
            f"itself: no resampling of this split can return a number above it, however "
            f"good the ranking is."
        ),
        "the_room_rule": {
            "statement": (
                "On every measurable split, whether the interval fits inside the room "
                "above the threshold predicts the verdict."
            ),
            "holds_on_every_measurable_split": rule_holds,
            "n_splits_checked": len(measurable),
            "splits_whose_interval_is_truncated_by_the_ceiling": truncated,
            "per_split": rooms,
            "reading": (
                "One variable, no exceptions on the four splits that can be measured. The "
                "split with room passed and the three without it did not. That makes gate "
                "6's verdict a fact about how much room each split gave the measurement "
                "before it is a fact about the ranker, and it is the reason the "
                "cold-station result is reported beside the pre-registered one rather than "
                "instead of it."
            ),
        },
        "closure": {
            "kind": "exact",
            "frozen_by_pre_registration": True,
            "statement": (
                f"A split whose room exceeds the interval it produces. "
                f"{', '.join(r['split'] for r in passed) or 'None'} already does: room "
                f"{passed[0]['room_above_the_threshold']:.3f} against an interval "
                f"{passed[0]['interval_width']:.3f} wide, and it passed at "
                f"{passed[0]['published_lift_point']:.3f}."
                if passed
                else "A split whose room exceeds the interval it produces. None does."
            ),
            "counterexample_to_the_obvious_extrapolation": (
                "Multiplying the population is not sufficient and this corpus proves it: "
                "cold_transmitter holds 95 observations against chronological's 87 and "
                "still fails, because its interval came back wider too. Interval width is "
                "not a function of split size alone, so no required-n is published here."
            ),
            "what_it_would_take": (
                "A larger snapshot, and the same objection applies as to gate 5: the "
                "chronological split and the budget of 50 were both fixed before any "
                "result was seen. Recorded as the reason it stays open rather than as work "
                "outstanding."
            ),
        },
    }


#: How each binding constraint reads in the summary paragraph. A constraint with no entry
#: here stops the run rather than being summarised as something vague, because the whole
#: point of this receipt is that no unmet gate goes unexplained.
_SHORTFALL_IN_A_PHRASE = {
    "testable_sample_size": "short of testable observations, and the shortfall is a count",
    "independent_episodes": (
        "short of independent station-nights rather than of observations, which is not a "
        "shortfall more of the same passes can close"
    ),
    "grouped_rate_below_the_bar": (
        "not short of anything: it holds more independent station-nights than a perfect "
        "run would need, and the rate over them came in under the bar"
    ),
    "measured_rate_below_the_bar": (
        "not short of anything: its rate came in under the bar, which is a measurement "
        "and not a sample size"
    ),
    "no_human_reviewer": "short of a reviewer and nothing else",
    "test_set_size": "short of test rows",
    "split_population_at_a_fixed_budget": "short of test rows",
}

_COUNT_WORD = {
    0: "no",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
}


def _count(n: int) -> str:
    """A small number as a word, because the paragraph reads as prose."""
    return _COUNT_WORD.get(n, str(n))


def _gate_list(gates: list[dict[str, Any]]) -> str:
    """``gate 5`` or ``gates 5 and 6``, in the receipt's own gate order."""
    numbers = [str(g["gate"]) for g in gates]
    noun = "gate" if len(numbers) == 1 else "gates"
    if len(numbers) == 1:
        return f"{noun} {numbers[0]}"
    return f"{noun} {', '.join(numbers[:-1])} and {numbers[-1]}"


def _reading(gates: list[dict[str, Any]]) -> str:
    """The summary paragraph, derived from the gates rather than typed beside them.

    This sentence named a count, a gate and a shortfall, and every one of those moves
    when a verdict does. It said "four constraints, three of them exact, gate 4 is short
    of a reviewer" for a while after a person answered gate 4 and it passed, which is the
    exact failure this whole receipt exists to catch elsewhere.
    """
    unmet = [g for g in gates if not g["met"]]
    if not unmet:
        return (
            "Every gate is met. The closure conditions below are kept because they say "
            "what each gate was up against, not because anything is outstanding."
        )

    unnamed = sorted(
        {
            str(g["binding_constraint"])
            for g in unmet
            if g["binding_constraint"] not in _SHORTFALL_IN_A_PHRASE
        }
    )
    if unnamed:
        raise SystemExit(
            "these binding constraints have no phrase in _SHORTFALL_IN_A_PHRASE, so the "
            f"reading paragraph would have to skip them: {unnamed}"
        )

    exact = [g for g in unmet if g["closure"]["kind"] == "exact"]
    frozen = [g for g in unmet if g["closure"]["frozen_by_pre_registration"]]
    movable = [g for g in unmet if not g["closure"]["frozen_by_pre_registration"]]

    noun = "constraint" if len(unmet) == 1 else "constraints"
    parts = [f"{_count(len(unmet)).capitalize()} {noun}, {_count(len(exact))} of them exact."]
    for gate in movable:
        phrase = _SHORTFALL_IN_A_PHRASE[gate["binding_constraint"]]
        parts.append(f"Gate {gate['gate']} is {phrase}.")

    if frozen:
        phrases = {_SHORTFALL_IN_A_PHRASE[g["binding_constraint"]] for g in frozen}
        subject = _gate_list(frozen)
        both = "both are" if len(frozen) == 2 else ("it is" if len(frozen) == 1 else "all are")
        if len(phrases) == 1:
            verb = "is" if len(frozen) == 1 else "are"
            opening = f"{subject.capitalize()} {verb} {phrases.pop()}"
        else:
            opening = ", ".join(
                f"gate {g['gate']} is {_SHORTFALL_IN_A_PHRASE[g['binding_constraint']]}"
                for g in frozen
            ).capitalize()
        parts.append(
            f"{opening}, and {both} the one kind of shortfall this project is not allowed "
            "to fix, because the splits and the budget were fixed before the results were "
            "read and growing them afterwards is what pre-registration exists to prevent. "
            f"That is why {'it is' if len(frozen) == 1 else 'they are'} recorded as "
            f"{'a reason' if len(frozen) == 1 else 'reasons'} rather than as work "
            "outstanding."
        )

    return " ".join(parts)


def build() -> dict[str, Any]:
    queue = _load("QUEUE_RECEIPT.json")
    fusion = _load("FUSION_RECEIPT.json")
    circularity = _load("CIRCULARITY_RECEIPT.json")
    gates: list[dict[str, Any]] = [
        {
            "gate": 1,
            "title": "Dataset volume and entity spread",
            "verdict": "PRE_PASSED",
            "met": True,
            "binding_constraint": None,
            "why_it_landed_here": (
                "A feasibility check answered before any pipeline code was written."
            ),
            "closure": {
                "kind": "exact",
                "frozen_by_pre_registration": False,
                "statement": "Met.",
            },
        },
        {
            "gate": 2,
            "title": "Metadata coverage for the corridor",
            "verdict": "PRE_PASSED",
            "met": True,
            "binding_constraint": None,
            "why_it_landed_here": (
                "A feasibility check answered before any pipeline code was written."
            ),
            "closure": {
                "kind": "exact",
                "frozen_by_pre_registration": False,
                "statement": "Met.",
            },
        },
        _gate3(_load("GATE3_RECEIPT.json")),
        _gate4(_load("GATE4_RECEIPT.json")),
        _gate5(fusion),
        _gate6(queue, circularity),
    ]
    unmet = [g for g in gates if not g["met"]]
    unexplained = [g["gate"] for g in unmet if not g["binding_constraint"]]
    return {
        "schema": "GATE_POWER_RECEIPT",
        "schema_version": 1,
        "unit": (
            "why each kill gate landed where it did, and the exact condition that would move it"
        ),
        "generated_by": "scripts/run_gate_power.py",
        "generated_at": datetime.now(UTC).isoformat(),
        "question": (
            "Of the gates that are not met, which are facts about the project and which "
            "are facts about the measurement?"
        ),
        "reads": [
            "artifacts/GATE3_RECEIPT.json",
            "artifacts/GATE4_RECEIPT.json",
            "artifacts/FUSION_RECEIPT.json",
            "artifacts/QUEUE_RECEIPT.json",
            "artifacts/CIRCULARITY_RECEIPT.json",
        ],
        "writes_no_verdict": (
            "Every verdict here is read from the receipt that decided it. This script "
            "explains gates and moves none of them."
        ),
        "n_gates": len(gates),
        "n_met": sum(1 for g in gates if g["met"]),
        "n_unmet": len(unmet),
        "every_unmet_gate_has_a_named_constraint": not unexplained,
        "unmet_without_a_constraint": unexplained,
        "gates": gates,
        "reading": _reading(gates),
    }


def _comparable(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload minus the field that changes on every run."""
    return {k: v for k, v in payload.items() if k != "generated_at"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help=(
            "recompute into memory and compare against the committed receipt, exiting "
            "non-zero on any difference without writing"
        ),
    )
    args = ap.parse_args(argv)
    fresh = build()

    if args.check:
        if not OUT.exists():
            print(f"{_shown(OUT)} is absent. Run this script without --check.")
            return 1
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        if _comparable(committed) != _comparable(fresh):
            print(
                f"{_shown(OUT)} is stale against the receipts it explains. "
                f"Run scripts/run_gate_power.py."
            )
            return 1
        print(f"gate power current: {fresh['n_unmet']} unmet, every one with a named constraint")
        return 0

    if not fresh["every_unmet_gate_has_a_named_constraint"]:
        raise SystemExit(
            f"gates {fresh['unmet_without_a_constraint']} are unmet and this script has no "
            f"binding constraint for them. An unexplained gate is the one thing this "
            f"receipt exists to make impossible, so it refuses to write."
        )

    OUT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {_shown(OUT)}")
    print(f"  {fresh['n_met']} met, {fresh['n_unmet']} unmet, all constrained")
    for gate in fresh["gates"]:
        if not gate["met"]:
            print(f"  gate {gate['gate']}: {gate['binding_constraint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
