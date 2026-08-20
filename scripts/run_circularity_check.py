"""How much of the queue's lift is guaranteed by the way the queue was built.

The ranking score and the definition of a conflict are not independent. The score is

    0.40 x disagreement + 0.35 x safe offset magnitude + 0.15 x flat-row fraction
    + 0.10 x ensemble uncertainty

and the three conflict criteria threshold the first three of those same quantities:
`MODEL_LABEL_DISAGREE` thresholds the model probability, `STALE_CATALOGUE_FREQ` thresholds
the fitted offset, `DEAD_CAPTURE` thresholds the flat-row fraction. Ninety percent of the
score's weight sits on quantities the definition names. Seventy-five percent sits on
quantities a conflict in this corpus is actually defined from, because `DEAD_CAPTURE` fires
on nothing here, and the two figures are published separately rather than folded together.
A ranking built that way beats a random ordering partly by construction, and the part that
is true by construction is not evidence.

Nothing here weakens gate 6 or restates it. It bounds it, with five quantities the queue
receipt does not carry:

1. **The ceiling, on every split.** At a budget of 50 over a population of 87 holding 22
   conflicts, an oracle that knew every answer would find all 22, which is a lift of 1.740.
   The gate asked for 1.5. The whole space between the threshold and perfection is 0.24
   wide, which is the most useful thing a reader can know about the 1.582 that came back.
   Every split gets the same treatment, because `cold_combined` caps at 1.520 against a
   1.500 bar: a perfect oracle scores 1.52 there, so that split's NOT_ESTABLISHED is a
   fact about its budget and is marked not informative rather than read as a result.
2. **Where the lift comes from.** The same ordering is scored against each criterion on its
   own, so a reader can see whether the result rests on the model's disagreement or on the
   measurements the model plays no part in.
3. **The model-independent case.** `STALE_CATALOGUE_FREQ` and `DEAD_CAPTURE` are computed
   from the fitted offset and the image. The model does not enter either one. On this
   corpus only the first of the two fires, so that restriction reduces to one criterion and
   this file says so instead of describing two. It does not remove the loop that runs from
   the score's weights into that signal, and it says that too rather than implying a clean
   test exists.
4. **A permutation test.** Two thousand seeded shuffles of the same population, each scored
   by `compute_lift`, the function gate 6 itself is measured with. It answers "could this
   ordering have come from nothing" without the bootstrap and without the threshold.
5. **A random-ordering floor.** The mean of those same 2000 lifts has to land on 1.0. An
   earlier version computed that mean inline and returned 1.0 by identity: it was invariant
   under reversing the queue, under inverting every conflict flag, and under `compute_lift`
   being replaced by a function that raises. Routing it through the shipped function is
   what makes it a check rather than a measurement of the random number generator.

Reads `artifacts/QUEUE_RECEIPT.json` and nothing else: no snapshot, no network, no model.
The first thing it does is reproduce the published lift from that file alone, and it refuses
to write anything if the reproduction misses.

    .venv/Scripts/python.exe scripts/run_circularity_check.py

Writes `artifacts/CIRCULARITY_RECEIPT.json`. Idempotent apart from `generated_at`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import random
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.queue import (  # noqa: E402
    CONFLICT_CRITERIA,
    compute_lift,
)

QUEUE_RECEIPT = REPO / "artifacts" / "QUEUE_RECEIPT.json"
OUT = REPO / "artifacts" / "CIRCULARITY_RECEIPT.json"

SPLIT = "chronological"
SEED = 42
N_BOOT = 4000
N_PERMUTATIONS = 2000
#: Bootstrap draws inside each permutation of the random control. The control reads
#: only each permutation's point lift, so this is the smallest value `compute_lift`
#: will accept rather than a 4000-draw interval computed 2000 times and thrown away.
N_BOOT_CONTROL = 20
#: How much room a split needs between the threshold and a perfect oracle before a
#: verdict on it says anything about the ordering. Below this the outcome is decided
#: by the budget: `cold_combined` caps at 1.520 against a 1.500 bar, so every possible
#: ordering, oracle included, lands inside 0.02 of the threshold.
_MIN_INFORMATIVE_HEADROOM = 0.10
THRESHOLD = 1.5

#: Which score weight each criterion's defining quantity carries. The weights are the ones
#: in `composite_score`, fixed before any of this was measured. Written here as a map rather
#: than read from the function, because the function returns a number and the pairing between
#: a criterion and the weight of the signal it thresholds is the finding.
SHARED_SIGNALS: dict[str, dict[str, Any]] = {
    "MODEL_LABEL_DISAGREE": {
        "thresholds": "model_prob",
        "score_signal": "disagreement",
        "score_weight": 0.40,
        "uses_the_model": True,
    },
    "STALE_CATALOGUE_FREQ": {
        "thresholds": "fitted_offset_ppm",
        "score_signal": "offset_safe",
        "score_weight": 0.35,
        "uses_the_model": False,
    },
    "DEAD_CAPTURE": {
        "thresholds": "flat_row_frac",
        "score_signal": "flat_row_frac",
        "score_weight": 0.15,
        "uses_the_model": False,
    },
}

#: The one weighted signal no criterion thresholds.
UNSHARED_SIGNAL = {"score_signal": "ensemble_uncertainty", "score_weight": 0.10}

#: The status values that make an observation decidable. Gate 6 runs on these.
_DECISIVE = ("with-signal", "without-signal")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decisive(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("waterfall_status") in _DECISIVE]


def _station_of(episode_key: str) -> str:
    """The ground station out of an episode key, which is `station:norad:revolution`.

    The receipt carries no station field per entry, and the interval the gate governs on is
    the union of an episode-grouped and a station-clustered bootstrap. Taking the station
    from the key rather than dropping the second grouping, because a narrower interval
    obtained by using fewer groupings would flatter this analysis against the gate it bounds.
    """
    return episode_key.split(":", 1)[0]


def _lift(
    ranked: list[dict[str, Any]],
    flags: dict[int, bool],
    budget: int,
    *,
    group: str,
) -> dict[str, Any]:
    ids = [e["obs_id"] for e in ranked]
    if group == "episode":
        groups = {e["obs_id"]: e["episode_key"] for e in ranked}
    else:
        groups = {e["obs_id"]: _station_of(e["episode_key"]) for e in ranked}
    return compute_lift(
        ids, flags, groups, budget, n_boot=N_BOOT, seed=SEED, threshold=THRESHOLD
    ).to_dict()


def _target(
    ranked: list[dict[str, Any]],
    criteria: tuple[str, ...],
    budget: int,
) -> dict[str, Any]:
    """One conflict definition, scored against the shipped ordering.

    The ordering is never recomputed. Only what counts as a find changes, which is the
    comparison the question asks for: the same queue, judged against a narrower target.
    """
    flags = {
        e["obs_id"]: bool(set(e.get("reasons") or []) & set(criteria)) for e in ranked
    }
    n_conflicts = sum(1 for v in flags.values() if v)
    episode = _lift(ranked, flags, budget, group="episode")
    station = _lift(ranked, flags, budget, group="station")

    measurable = episode.get("verdict") != "NOT_MEASURABLE" and n_conflicts > 0
    if not measurable:
        return {
            "criteria": list(criteria),
            "measurable": False,
            "not_measurable_reason": (
                f"{n_conflicts} observations in this population satisfy "
                f"{', '.join(criteria)}, so random expects none and the ratio has no "
                "denominator. Not a result about the queue."
            ),
            "n_conflicts": n_conflicts,
            "lift_point": None,
            "lift_ci95": None,
            "verdict": "NOT_MEASURABLE",
        }

    # Union of the two groupings, the same rule gate 6 governs on, so this analysis cannot
    # look better than the gate by quietly using the narrower of the two intervals.
    #
    # The station bootstrap has its own way of failing: below `min_effective` surviving
    # resamples `compute_lift` returns [nan, nan], and min(1.35, nan) is 1.35 while
    # max(1.74, nan) is 1.74, so a nan interval would vanish into the union and this file
    # would publish the narrower episode-only interval under a label saying it was the
    # union of two. That is exactly how a NOT_ESTABLISHED becomes a PASSED without anyone
    # touching a threshold. `measure_gate6_split` has the third branch; this had two.
    station_measurable = station.get("verdict") != "NOT_MEASURABLE"
    if station_measurable:
        lo = min(episode["lift_ci95"][0], station["lift_ci95"][0])
        hi = max(episode["lift_ci95"][1], station["lift_ci95"][1])
        governing = "union_of_episode_and_station"
        station_ci = station["lift_ci95"]
        station_note = None
    else:
        lo, hi = episode["lift_ci95"]
        governing = "episode_only"
        station_ci = None
        station_note = station.get("not_measurable_reason") or (
            "The station-clustered bootstrap on this target did not produce enough "
            "surviving resamples to form an interval."
        )
    point = episode["lift_point"]
    if lo > THRESHOLD:
        verdict, direction = "PASSED", "above_threshold"
    elif hi < THRESHOLD:
        verdict, direction = "FAILED", "below_threshold"
    else:
        verdict, direction = "NOT_ESTABLISHED", "spans_threshold"

    # Saturation, and why it gets its own outcome rather than a pass.
    #
    # When the queue finds every conflict the population holds, lift is
    # n_conflicts / (budget x n_conflicts / n_population), which cancels to
    # n_population / budget no matter how many conflicts there were. Three finds and
    # thirty finds both score 1.740 here. The interval around that constant is narrow
    # because the statistic is a constant, not because the ordering was measured well,
    # and a PASSED printed from it would be the strongest-looking verdict in this file
    # sitting on the least information.
    n_at_budget = episode["n_queue_conflicts"]
    saturated = n_conflicts > 0 and n_at_budget == n_conflicts
    if saturated:
        verdict, direction = "NOT_INFORMATIVE", "saturated"

    return {
        "criteria": list(criteria),
        "measurable": True,
        "not_measurable_reason": None,
        "saturated": saturated,
        "saturation_note": (
            f"The queue found all {n_conflicts} of them inside the budget, so this lift is "
            f"n_population / budget = {len(ranked) / budget:.3f} whatever the count had "
            "been. It says the finds are near the top and says nothing about how near, and "
            "no verdict about the 1.5 threshold can be read off it."
            if saturated
            else None
        ),
        "n_conflicts": n_conflicts,
        "n_at_budget": episode["n_queue_conflicts"],
        "random_expected": episode["n_random_conflicts"],
        "lift_point": point,
        "lift_ci95": [lo, hi],
        "lift_ci95_episode": episode["lift_ci95"],
        "lift_ci95_station": station_ci,
        "station_interval_note": station_note,
        "governing_interval": governing,
        "n_boot_effective": episode.get("n_boot_effective"),
        "direction": direction,
        "verdict": verdict,
    }


def _random_control(
    ranked: list[dict[str, Any]],
    flags: dict[int, bool],
    budget: int,
    observed_lift: float,
) -> dict[str, Any]:
    """Seeded random orderings of the same population, scored by the shipped framework.

    The first version of this computed ``found / expected`` inline, where ``expected`` is
    the exact mean of ``found`` under a uniform shuffle. Its answer was 1.0 by identity. It
    returned 1.0 with the queue reversed, with every conflict flag inverted, and with
    ``compute_lift`` replaced by a function that raises, so it could not have failed for any
    defect in the thing it was described as checking. It measured the random number
    generator.

    This one shuffles the population and hands each permutation to ``compute_lift``, the
    same function gate 6 is measured with, so a defect in the ranking, the grouping or the
    ratio moves this number. It reads only ``lift_point`` from each permutation, so the
    per-permutation bootstrap is set to the smallest ``compute_lift`` will run rather than
    repeating a 4000-draw interval 2000 times for a figure that is discarded.

    The permutation p-value is the second thing it buys: the share of random orderings that
    match or beat the shipped queue. That is a direct answer to "could this ordering have
    come from nothing", computed without the bootstrap and without the threshold.
    """
    ids = [e["obs_id"] for e in ranked]
    groups = {e["obs_id"]: e["episode_key"] for e in ranked}
    rng = random.Random(SEED)
    lifts: list[float] = []
    at_budget: list[int] = []
    for _ in range(N_PERMUTATIONS):
        shuffled = ids[:]
        rng.shuffle(shuffled)
        drawn = compute_lift(
            shuffled,
            flags,
            groups,
            budget,
            n_boot=N_BOOT_CONTROL,
            seed=SEED,
            threshold=THRESHOLD,
        )
        lifts.append(float(drawn.lift_point))
        at_budget.append(int(drawn.n_queue_conflicts))
    lifts.sort()
    mean = sum(lifts) / len(lifts)
    n_at_least = sum(1 for v in lifts if v >= observed_lift - 1e-12)
    return {
        "computed_by": "pipeline.tracetriage.queue.compute_lift",
        "n_permutations": N_PERMUTATIONS,
        "n_boot_per_permutation": N_BOOT_CONTROL,
        "seed": SEED,
        "mean_lift": round(mean, 6),
        "p5": round(lifts[int(0.05 * len(lifts))], 6),
        "p95": round(lifts[int(0.95 * len(lifts)) - 1], 6),
        "expected_mean": 1.0,
        "abs_error": round(abs(mean - 1.0), 6),
        "distinct_conflict_counts_at_budget": sorted(set(at_budget)),
        "observed_lift": observed_lift,
        "n_permutations_at_or_above_observed": n_at_least,
        "p_value_permutation": round((1 + n_at_least) / (1 + N_PERMUTATIONS), 6),
        "reading": (
            f"{n_at_least} of {N_PERMUTATIONS} random orderings of the same population "
            f"found as many conflicts inside the budget as the shipped queue did, so a "
            f"permutation p-value of "
            f"{(1 + n_at_least) / (1 + N_PERMUTATIONS):.4f}, which is the smallest this "
            f"test can report at {N_PERMUTATIONS} permutations. The mean of the same "
            f"{N_PERMUTATIONS} lifts is {mean:.4f} against an expected 1.0, which is the "
            "floor check: every number in this file is produced by the function that "
            "returned it."
        ),
    }


def _ceilings_by_split(per_split: dict[str, Any]) -> dict[str, Any]:
    """The ceiling on every split, not just the one this file reproduces.

    The ceiling is the highest lift any ordering can reach: an oracle finds every conflict
    it has budget for, so it is min(budget, conflicts) / (budget x conflicts / population).
    Each split publishes those three counts, so all four can be bounded from the receipt
    even though only the chronological ordering is in it row by row.

    This matters most where nobody thought to look. `cold_combined` has 76 observations, 20
    conflicts and a budget of 50, which caps every possible ordering at 1.520 against a
    threshold of 1.500. A perfect oracle scores 1.52 there. Reporting that split's
    NOT_ESTABLISHED as a finding about generalisation, without saying the scale it was
    measured on is 0.02 wide, would be reporting the budget rather than the queue.
    """
    out: dict[str, Any] = {}
    for name, split in sorted(per_split.items()):
        replay = split.get("replay_episode") or {}
        n_pop = replay.get("n_population")
        n_conf = replay.get("n_total_conflicts")
        budget = replay.get("budget")
        if not all(isinstance(v, int) and v > 0 for v in (n_pop, n_conf, budget)):
            out[name] = {
                "measurable": False,
                "not_measurable_reason": (
                    f"This split published no replay population, so its ceiling cannot be "
                    f"computed. Got n_population={n_pop!r}, n_total_conflicts={n_conf!r}, "
                    f"budget={budget!r}."
                ),
            }
            continue
        expected = budget * n_conf / n_pop
        ceiling = min(budget, n_conf) / expected
        headroom = ceiling - THRESHOLD
        out[name] = {
            "measurable": True,
            "not_measurable_reason": None,
            "n_population": n_pop,
            "n_conflicts": n_conf,
            "budget": budget,
            "ceiling": ceiling,
            "threshold": THRESHOLD,
            "headroom_between_threshold_and_perfection": headroom,
            "published_lift_point": split.get("lift_point"),
            "published_lift_ci95": split.get("lift_ci95"),
            "published_verdict": split.get("verdict"),
            "informative": headroom >= _MIN_INFORMATIVE_HEADROOM,
            "note": (
                f"An oracle scores {ceiling:.3f}x here against a {THRESHOLD}x bar, so the "
                f"whole scale this split's verdict is read on is {headroom:.3f} wide. A "
                f"verdict of {split.get('verdict')!r} on a scale that narrow is a fact "
                f"about the budget more than about the ordering."
                if headroom < _MIN_INFORMATIVE_HEADROOM
                else (
                    f"An oracle scores {ceiling:.3f}x here against a {THRESHOLD}x bar, so "
                    f"there is {headroom:.3f} of room between the threshold and perfection "
                    f"for the measurement to land in."
                )
            ),
        }
    return out


def build() -> dict[str, Any]:
    receipt = json.loads(QUEUE_RECEIPT.read_text(encoding="utf-8"))
    entries = receipt["queue"]
    ranked = sorted(_decisive(entries), key=lambda e: e["rank"])
    published = receipt["gate6"]["per_split"][SPLIT]
    budget = int(published["n_queue_examined"])

    flags_all = {e["obs_id"]: bool(e["is_conflict"]) for e in ranked}
    n_conflicts = sum(1 for v in flags_all.values() if v)
    n_at_budget = sum(1 for e in ranked[:budget] if flags_all[e["obs_id"]])
    expected = budget * n_conflicts / len(ranked)
    reproduced = n_at_budget / expected

    # The reproduction is a precondition, not a result. If this file cannot recover the
    # published number from the receipt alone, nothing below it is about the same queue.
    matches = (
        abs(reproduced - published["lift_point"]) < 1e-9
        and n_at_budget == published["n_queue_conflicts"]
        and len(ranked) == published["replay_episode"]["n_population"]
    )
    if not matches:
        raise SystemExit(
            "this analysis cannot reproduce the published lift from the queue receipt "
            f"alone: it computes {reproduced!r} over {len(ranked)} observations against a "
            f"published {published['lift_point']!r} over "
            f"{published['replay_episode']['n_population']}. Either the receipt changed "
            "shape or the population is not the one gate 6 was measured on, and in both "
            "cases the numbers below would be about a different thing."
        )

    # The ceiling. An oracle finds every conflict it has budget for, and no ordering of any
    # kind can beat it, so this is the top of the scale the 1.5 threshold was set against.
    max_findable = min(budget, n_conflicts)
    ceiling = max_findable / expected

    model_dependent = tuple(
        k for k, v in SHARED_SIGNALS.items() if v["uses_the_model"]
    )
    model_independent = tuple(
        k for k, v in SHARED_SIGNALS.items() if not v["uses_the_model"]
    )
    all_criteria = tuple(c["reason_code"] for c in CONFLICT_CRITERIA)
    if set(all_criteria) != set(SHARED_SIGNALS):
        raise SystemExit(
            "the conflict criteria in pipeline/tracetriage/queue.py are "
            f"{sorted(all_criteria)} and this analysis maps {sorted(SHARED_SIGNALS)} of "
            "them to score weights. A criterion with no mapping would be silently left "
            "out of the shared-signal accounting, which is the accounting this file is for."
        )

    shared_weight = sum(v["score_weight"] for v in SHARED_SIGNALS.values())

    # Which criteria actually fired. A criterion published in the definition and firing on
    # nothing carries its score weight into the "shared" total while contributing no
    # realised conflict, so the two totals are different numbers and both are published.
    # On this corpus DEAD_CAPTURE fires zero times: the highest flat_row_frac in the queue
    # is 0.1371 against a 0.15 threshold. Every sentence of the form "the two criteria the
    # model does not enter" was describing one criterion, so the prose below is generated
    # from these counts rather than written from the definition.
    fired = {
        row["reason_code"]: row
        for row in receipt["conflict_definition"].get("criteria_fired", [])
    }
    if set(fired) != set(SHARED_SIGNALS):
        raise SystemExit(
            "the queue receipt reports firing counts for "
            f"{sorted(fired)} and this analysis maps {sorted(SHARED_SIGNALS)}. Without a "
            "count per criterion there is no way to tell an active criterion from an inert "
            "one, and the weight accounting below would silently credit both."
        )
    active = tuple(k for k in SHARED_SIGNALS if fired[k]["n_flagged"] > 0)
    inert = tuple(k for k in SHARED_SIGNALS if fired[k]["n_flagged"] == 0)
    active_weight = sum(SHARED_SIGNALS[k]["score_weight"] for k in active)
    model_independent_active = tuple(
        k for k in model_independent if fired[k]["n_flagged"] > 0
    )

    return {
        "schema": "tracetriage/circularity/v1",
        "schema_version": "1.0.0",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "question": (
            "How much of gate 6's lift is guaranteed by the queue being ranked on the "
            "same quantities the conflict criteria threshold?"
        ),
        "source": {
            "receipt": "artifacts/QUEUE_RECEIPT.json",
            "sha256": _sha256(QUEUE_RECEIPT),
            "split": SPLIT,
            "needs_the_snapshot": False,
        },
        "reproduction": {
            "n_population": len(ranked),
            "n_conflicts": n_conflicts,
            "budget": budget,
            "n_at_budget": n_at_budget,
            "random_expected": expected,
            "lift_point": reproduced,
            "published_lift_point": published["lift_point"],
            "matches_the_queue_receipt": True,
        },
        "shared_signals": {
            "criteria": SHARED_SIGNALS,
            "unshared": UNSHARED_SIGNAL,
            "fired": fired,
            "active": list(active),
            "inert": list(inert),
            "score_weight_on_quantities_the_definition_names": round(shared_weight, 2),
            "score_weight_on_quantities_a_realised_conflict_is_defined_from": round(
                active_weight, 2
            ),
            "score_weight_independent_of_the_target": round(1.0 - shared_weight, 2),
            "reading": (
                "Every criterion's defining quantity is also a weighted term in the score, "
                "so no restriction of the target makes this measurement independent of its "
                "own construction. What the restrictions below separate is the model's "
                "contribution, not the score's. Two weights are published because they are "
                f"different numbers: {shared_weight:.2f} of the score sits on quantities "
                f"the definition names, and {active_weight:.2f} sits on quantities a "
                f"conflict in this corpus is actually defined from. The gap is "
                + (
                    "zero, because every criterion fired."
                    if not inert
                    else (
                        ", ".join(inert)
                        + ", which fires on nothing here. "
                        + " ".join(fired[k]["note"] for k in inert)
                    )
                )
            ),
        },
        "ceiling": {
            "max_findable_at_budget": max_findable,
            "lift": ceiling,
            "threshold": THRESHOLD,
            "headroom_between_threshold_and_perfection": ceiling - THRESHOLD,
            "queue_share_of_the_ceiling": n_at_budget / max_findable,
            "reading": (
                f"A budget of {budget} over {len(ranked)} observations holding "
                f"{n_conflicts} conflicts caps any ordering at {ceiling:.3f}x. The gate "
                f"asked for {THRESHOLD}x, so the entire distance between the bar and a "
                f"perfect oracle is {ceiling - THRESHOLD:.3f}. The queue found "
                f"{n_at_budget} of the {max_findable} an oracle would have."
            ),
        },
        "ceilings_by_split": _ceilings_by_split(receipt["gate6"]["per_split"]),
        "targets": {
            "all_three_criteria": _target(ranked, all_criteria, budget),
            "model_dependent_only": _target(ranked, model_dependent, budget),
            "model_independent_only": _target(ranked, model_independent, budget),
            "model_independent_and_firing": _target(
                ranked, model_independent_active, budget
            ),
        },
        "targets_note": (
            f"`model_independent_only` names {len(model_independent)} criteria and "
            f"measures {len(model_independent_active)}, because "
            + (
                "all of them fire on this corpus."
                if len(model_independent_active) == len(model_independent)
                else (
                    ", ".join(k for k in model_independent if k not in model_independent_active)
                    + " fires on nothing here. `model_independent_and_firing` is the same "
                    "restriction with the inert criteria dropped from the name, so the two "
                    "rows carry identical numbers and only one of them can be misread."
                )
            )
        ),
        "random_ordering_control": _random_control(
            ranked, flags_all, budget, reproduced
        ),
        "what_this_does_not_establish": (
            "That the queue generalises. Restricting the target to the criteria the model "
            "does not enter removes one loop and leaves another: on this corpus that "
            f"restriction reduces to {' and '.join(model_independent_active)} alone, whose "
            "defining quantity the score weights at "
            f"{sum(SHARED_SIGNALS[k]['score_weight'] for k in model_independent_active):.2f}. "
            + (
                ""
                if len(model_independent_active) == len(model_independent)
                else (
                    "The other model-independent criterion, "
                    + ", ".join(
                        k for k in model_independent if k not in model_independent_active
                    )
                    + ", fires on nothing in this corpus, so a reader following its 0.15 "
                    "weight is following a loop that does not exist in the data. "
                )
            )
            + "The honest reading is that this measurement is a check on internal "
            "consistency and on the size of the space the gate was set in, not an "
            "independent test of the ranking."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="recompute and compare against the committed receipt, ignoring generated_at",
    )
    args = ap.parse_args(argv)

    fresh = build()

    if args.check:
        if not OUT.exists():
            print(f"{OUT.relative_to(REPO)} is absent. Run this script without --check.")
            return 1
        committed = json.loads(OUT.read_text(encoding="utf-8"))
        a = {k: v for k, v in fresh.items() if k != "generated_at"}
        b = {k: v for k, v in committed.items() if k != "generated_at"}
        if a == b:
            print("CIRCULARITY_RECEIPT.json matches the queue receipt")
            return 0
        differing = sorted(k for k in a if a.get(k) != b.get(k))
        print("CIRCULARITY_RECEIPT.json is stale. Run scripts/run_circularity_check.py.")
        print(f"  fields that differ: {differing}")
        return 1

    OUT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
    t = fresh["targets"]
    print(f"{OUT.relative_to(REPO)} written")
    print(
        f"  reproduced the published lift: {fresh['reproduction']['lift_point']:.4f} "
        f"over {fresh['reproduction']['n_population']} observations"
    )
    print(
        f"  ceiling at this budget: {fresh['ceiling']['lift']:.3f}x, "
        f"threshold {THRESHOLD}x"
    )
    for name, block in t.items():
        if block["measurable"]:
            lo, hi = block["lift_ci95"]
            print(
                f"  {name}: {block['lift_point']:.3f}x [{lo:.3f}, {hi:.3f}] "
                f"{block['verdict']} over {block['n_conflicts']} conflicts"
            )
        else:
            print(f"  {name}: not measurable, {block['not_measurable_reason']}")
    print(
        f"  random-ordering control: mean {fresh['random_ordering_control']['mean_lift']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
