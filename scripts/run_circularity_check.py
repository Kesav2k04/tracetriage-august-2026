"""How much of the queue's lift is guaranteed by the way the queue was built.

The ranking score and the definition of a conflict are not independent. The score is

    0.40 x disagreement + 0.35 x safe offset magnitude + 0.15 x flat-row fraction
    + 0.10 x ensemble uncertainty

and the three conflict criteria threshold the first three of those same quantities:
`MODEL_LABEL_DISAGREE` thresholds the model probability, `STALE_CATALOGUE_FREQ` thresholds
the fitted offset, `DEAD_CAPTURE` thresholds the flat-row fraction. Ninety percent of the
score's weight sits on quantities the target is defined from. A ranking built that way beats
a random ordering by construction, and a number that is true by construction is not evidence.

Nothing here weakens gate 6 or restates it. It bounds it, with four quantities the queue
receipt does not carry:

1. **The ceiling.** At a budget of 50 over a population of 87 holding 22 conflicts, an
   oracle that knew every answer would find all 22, which is a lift of 1.740. The gate asked
   for 1.5. The whole space between the threshold and perfection is 0.24 wide, which is the
   most useful thing a reader can know about the 1.582 that came back.
2. **Where the lift comes from.** The same ordering is scored against each criterion on its
   own, so a reader can see whether the result rests on the model's disagreement or on the
   two measurements the model plays no part in.
3. **The model-independent case.** `STALE_CATALOGUE_FREQ` and `DEAD_CAPTURE` are computed
   from the fitted offset and the image. The model does not enter either one. Restricting
   the target to those two removes the loop that runs from the model's own probability into
   the definition of what counts as a find. It does not remove the loop that runs from the
   score's weights into those two signals, and this script says so rather than implying a
   clean test exists.
4. **A random-ordering control.** Seeded permutations of the same population against the
   same target, whose mean lift has to land on 1.0. A framework that cannot produce 1.0 for
   a random ordering cannot be trusted to produce 1.58 for a real one.

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
    lo = min(episode["lift_ci95"][0], station["lift_ci95"][0])
    hi = max(episode["lift_ci95"][1], station["lift_ci95"][1])
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
        "lift_ci95_station": station["lift_ci95"],
        "governing_interval": "union_of_episode_and_station",
        "n_boot_effective": episode.get("n_boot_effective"),
        "direction": direction,
        "verdict": verdict,
    }


def _random_control(
    ranked: list[dict[str, Any]],
    flags: dict[int, bool],
    budget: int,
) -> dict[str, Any]:
    """Seeded random orderings of the same population against the same target.

    The mean has to land on 1.0. This is the floor check the whole comparison rests on: a
    lift framework that scores a random ordering at anything else is measuring something
    other than what it names.
    """
    ids = [e["obs_id"] for e in ranked]
    total = sum(1 for oid in ids if flags.get(oid, False))
    expected = budget * total / len(ids)
    rng = random.Random(SEED)
    lifts: list[float] = []
    for _ in range(N_PERMUTATIONS):
        shuffled = ids[:]
        rng.shuffle(shuffled)
        found = sum(1 for oid in shuffled[:budget] if flags.get(oid, False))
        lifts.append(found / expected)
    lifts.sort()
    mean = sum(lifts) / len(lifts)
    return {
        "n_permutations": N_PERMUTATIONS,
        "seed": SEED,
        "mean_lift": round(mean, 6),
        "p5": round(lifts[int(0.05 * len(lifts))], 6),
        "p95": round(lifts[int(0.95 * len(lifts)) - 1], 6),
        "expected_mean": 1.0,
        "abs_error": round(abs(mean - 1.0), 6),
    }


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
            "score_weight_on_quantities_the_target_is_defined_from": round(
                shared_weight, 2
            ),
            "score_weight_independent_of_the_target": round(1.0 - shared_weight, 2),
            "reading": (
                "Every criterion's defining quantity is also a weighted term in the score, "
                "so no restriction of the target makes this measurement independent of its "
                "own construction. What the restrictions below separate is the model's "
                "contribution, not the score's."
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
        "targets": {
            "all_three_criteria": _target(ranked, all_criteria, budget),
            "model_dependent_only": _target(ranked, model_dependent, budget),
            "model_independent_only": _target(ranked, model_independent, budget),
        },
        "random_ordering_control": _random_control(ranked, flags_all, budget),
        "what_this_does_not_establish": (
            "That the queue generalises. Restricting the target to the two criteria the "
            "model does not enter removes one loop and leaves another: the score still "
            "weights the offset magnitude at 0.35 and the flat-row fraction at 0.15, and "
            "those are the quantities those two criteria threshold. The honest reading is "
            "that this measurement is a check on internal consistency and on the size of "
            "the space the gate was set in, not an independent test of the ranking."
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
