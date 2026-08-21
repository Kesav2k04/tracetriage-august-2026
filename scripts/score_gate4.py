"""Score the blinded gate 4 review, after verifying that the sample was fixed in advance.

    .venv/Scripts/python.exe scripts/score_gate4.py
    .venv/Scripts/python.exe scripts/score_gate4.py --bundle D:/tracetriage_gate4

Reads the responses a reviewer filled in, recomputes every commitment in
``artifacts/GATE4_WORKSHEET.json`` from the key that was written outside the repository, and
refuses to score anything if one of them fails. That check is the whole difference between a
blinded study and a claim of one: without it the mapping could have been chosen after the
answers were known.

Three numbers come out, and only the first is the gate:

* **the decisive rate**, with an exact interval, against the 80 percent threshold fixed
  before the build
* **intra-rater agreement** on the repeated items, which is the reviewer against themselves
  and bounds how much the first number can be trusted
* **agreement with the network's own label**, which is not the gate and is the more
  interesting number: it measures whether a blinded human reaches the same verdict SatNOGS
  published, on the same image, with that label hidden

Absence is a verdict here. With no responses the receipt says NOT_RUN, which is neither a
failure nor a pass, because a gate with two outcomes turns "nobody did the study" into
"the study failed" or, worse, into silence.

**Who reviewed is part of the measurement, so it is required rather than assumed.** The
bundle must carry a ``REVIEWER.json`` declaring what kind of reviewer answered, and this
refuses to score without one. Gate 4 is titled blinded *human* decidability: a reviewer that
is not a person measures something real about the sample and does not measure that, so a
non-human review is published as its own arm and the gate's own verdict stays ``NOT_RUN``.
No consumer of this receipt has to know about the distinction to avoid getting it wrong,
because the field they already read does not move.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_gate3 import rate_lower_bound, rate_upper_bound  # noqa: E402

MANIFEST = REPO / "artifacts" / "GATE4_WORKSHEET.json"
RECEIPT = REPO / "artifacts" / "GATE4_RECEIPT.json"

_COMMITTED = {"yes", "no"}
_ANSWERS = {
    "artifact_usable": {"yes", "no", "unsure"},
    "visible_signal": {"yes", "no", "unsure"},
    "target_consistent": {"yes", "no", "na", "unsure"},
}


class NotRun(Exception):
    """Nobody has answered. A third outcome, and not a failure of the gate."""


class ScoringError(Exception):
    """The study cannot be scored at all, which is not the same as scoring badly.

    Kept separate from :class:`NotRun` deliberately. An unfilled worksheet is a state of the
    world and the receipt records it as NOT_RUN. A commitment that does not verify, a
    response file from a different bundle, or an answer nobody can interpret are none of
    them states of the world: they mean the instrument cannot be trusted, so nothing is
    written and the exit code is non-zero. Folding them into NOT_RUN would let a tampered
    key produce a tidy receipt.
    """


#: Every field the declaration must carry, with what each one is for. A missing field is a
#: refusal: a decisive rate whose reviewer is unnamed is the one number in this project that
#: could be quietly produced by anything at all.
_REVIEWER_FIELDS = {
    "kind": "human or model. Gate 4 is titled human decidability and only one of these meets it.",
    "identity": "what actually answered, specifically enough to be doubted.",
    "procedure": "how the items were presented and in what order.",
    "independence": "what stopped one item's answer from being informed by another's.",
}
_REVIEWER_KINDS = {"human", "model"}


def read_reviewer(path: Path) -> dict[str, Any]:
    """Who answered, declared before the answers are read and refused if absent.

    This exists because of the shape of the mistake it prevents. Everything else in this
    file guards the sample: the commitment binds which images, in which order, with which
    digests, before anyone looks at them. None of that says who looked. A receipt carrying
    a decisive rate of 0.9 with an interval and an intra-rater figure reads as a study
    whoever produced it, and the one fact that decides whether it answers the gate as
    titled is the one fact nothing was recording.
    """
    if not path.exists():
        raise ScoringError(
            f"no reviewer declaration at {path}. Responses exist and nothing says who "
            f"produced them, so there is no honest way to publish a rate from them. Write "
            f"{path.name} with {sorted(_REVIEWER_FIELDS)}."
        )
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScoringError(f"{path} is not readable JSON: {exc}") from exc
    missing = [field for field in _REVIEWER_FIELDS if not str(declared.get(field) or "").strip()]
    if missing:
        raise ScoringError(
            f"{path.name} is missing {missing}. Each one is required: "
            + "; ".join(f"{k}: {v}" for k, v in _REVIEWER_FIELDS.items() if k in missing)
        )
    if declared["kind"] not in _REVIEWER_KINDS:
        raise ScoringError(
            f"{path.name} declares kind {declared['kind']!r} and this scorer knows "
            f"{sorted(_REVIEWER_KINDS)}. A kind it has no handling for must stop the run "
            f"rather than fall through to whichever branch happens to be first."
        )
    return declared


def read_responses(path: Path) -> list[dict[str, str]]:
    """Every row a reviewer actually answered, with the values checked against the form."""
    if not path.exists():
        raise NotRun(f"no responses at {path}")
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            answers = {
                field: (row.get(field) or "").strip().lower() for field in _ANSWERS
            }
            if not any(answers.values()):
                continue  # an untouched row is not an answer of "unsure"
            for field, allowed in _ANSWERS.items():
                if answers[field] not in allowed:
                    raise ScoringError(
                        f"line {line_number}: {field} is {answers[field]!r}, and the form "
                        f"allows {sorted(allowed)}. A value nobody can interpret must not be "
                        f"counted as a decision either way."
                    )
            rows.append(
                {
                    "item": (row.get("item") or "").strip(),
                    **answers,
                    # Optional and never validated against a set, because a reviewer's
                    # pace is a summary rather than a decision. A row from an older
                    # bundle has no such column and reads as an empty string.
                    "seconds": (row.get("seconds") or "").strip(),
                }
            )

    seen: dict[str, int] = {}
    for index, row in enumerate(rows, start=1):
        if row["item"] in seen:
            raise ScoringError(
                f"{row['item']} is answered twice, at rows {seen[row['item']]} and {index}. "
                f"Building a dict from the rows would keep the last one silently, and which of "
                f"two answers a reviewer meant is not a thing this script may decide."
            )
        seen[row["item"]] = index
    return rows


def _pace(rows: list[dict[str, str]]) -> dict[str, object]:
    """Seconds per item, if the reviewer's tool recorded them.

    What this is: one reviewer's time on one blinded plate, from the moment it appeared
    to the moment they committed an answer, in one sitting.

    What it is not, stated here because the README's open row is easy to close wrongly:
    it is not human minutes per confirmed finding. That number needs this pace and the
    share of opened observations that turn out to carry something, and the second factor
    belongs to the queue rather than to this gate. It is also not a rate anyone should
    extrapolate to an operator: a reviewer working through a fixed sample with a progress
    bar is not a volunteer deciding when to stop.

    Rows with no timing are counted and excluded rather than treated as zero, because a
    resumed session records an empty cell for the item that was on screen when the tab
    was closed, and folding those into a mean would make the reviewer look faster than
    they were.
    """
    values: list[float] = []
    without = 0
    for row in rows:
        raw = row.get("seconds", "")
        if not raw:
            without += 1
            continue
        try:
            values.append(float(raw))
        except ValueError:
            without += 1
    if not values:
        return {
            "recorded": 0,
            "without_timing": without,
            "reading": (
                "The response file carries no usable timing, which is what a bundle "
                "answered on paper or in an older build of the review page looks like. "
                "No pace is published rather than one inferred."
            ),
        }
    values.sort()
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    return {
        "recorded": len(values),
        "without_timing": without,
        "median_seconds": round(median, 1),
        "mean_seconds": round(sum(values) / len(values), 1),
        "fastest_seconds": round(values[0], 1),
        "slowest_seconds": round(values[-1], 1),
        "total_minutes": round(sum(values) / 60, 1),
        "reading": (
            "One reviewer's seconds per blinded plate, in one sitting, from the plate "
            "appearing to an answer being committed. This is an input to human minutes "
            "per confirmed finding and not that number: the missing factor is the share "
            "of opened observations that carry something, which the queue measures and "
            "this gate does not."
        ),
    }


def is_decisive(answer: dict[str, str]) -> bool:
    """The rule from the manifest, in code, and the manifest is what states it publicly."""
    if answer["artifact_usable"] not in _COMMITTED:
        return False
    if answer["artifact_usable"] == "no":
        return True
    return (
        answer["visible_signal"] in _COMMITTED or answer["target_consistent"] in _COMMITTED
    )


def verify_stimulus(key: dict[str, Any], images: Path) -> int:
    """Re-derive every image digest from disk, and refuse if one has changed.

    The first version of this took ``image_sha256`` from the key and hashed that, then blamed
    a mismatch on "the key was written after the manifest, or the image changed". The second
    of those was undetectable: every file in the bundle could be replaced and all the
    commitments would still verify, because nothing re-read the images. A commitment that
    binds the mapping and not the stimulus is half a preregistration, and the half it is
    missing is the one that says the reviewer saw the picture the sample committed to.
    """
    if not images.is_dir():
        raise ScoringError(
            f"no images at {images}, so what the reviewer saw cannot be checked against the "
            f"commitment. Keep the bundle until it has been scored: a study whose stimulus "
            f"has been deleted is not a study whose stimulus was verified."
        )
    checked = 0
    for row in key["items"]:
        path = images / row["image_name"]
        if not path.exists():
            raise ScoringError(f"{row['item']}: no image at {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != row["image_sha256"]:
            raise ScoringError(
                f"{row['item']}: the image on disk hashes to {actual[:12]} and the key "
                f"committed to {row['image_sha256'][:12]}. The stimulus changed after the "
                f"build, so nothing here can be scored."
            )
        checked += 1
    return checked


def verify_commitments(manifest: dict[str, Any], key: dict[str, Any], images: Path) -> int:
    """Recompute every commitment against the images on disk, and refuse on the first miss."""
    checked = verify_stimulus(key, images)
    committed = {row["item"]: row["commitment"] for row in manifest["commitments"]}
    revealed = {row["item"]: row for row in key["items"]}
    if set(committed) != set(revealed):
        raise ScoringError(
            f"the manifest commits to {len(committed)} items and the key reveals "
            f"{len(revealed)}: {sorted(set(committed) ^ set(revealed))[:5]}"
        )
    for item, expected in committed.items():
        row = revealed[item]
        actual = hashlib.sha256(
            f"{key['salt']}|{item}|{row['obs_id']}|{row['image_sha256']}".encode()
        ).hexdigest()
        if actual != expected:
            raise ScoringError(
                f"{item} does not match its commitment, and its image does match the digest "
                f"the key carries, so the key was written after the manifest rather than the "
                f"image being swapped. Nothing is scored from here."
            )
    return checked


def _agreement(pairs: list[tuple[dict[str, str], dict[str, str]]]) -> dict[str, Any]:
    """The reviewer against themselves, per axis and on all three at once."""
    per_axis = {}
    for field in _ANSWERS:
        same = sum(1 for a, b in pairs if a[field] == b[field])
        per_axis[field] = {
            "pairs": len(pairs),
            "identical": same,
            "rate": round(same / len(pairs), 4) if pairs else None,
        }
    all_three = sum(1 for a, b in pairs if all(a[f] == b[f] for f in _ANSWERS))
    return {
        "repeated_pairs_scored": len(pairs),
        "per_axis": per_axis,
        "identical_on_all_three_axes": all_three,
        "rate_identical_on_all_three_axes": (
            round(all_three / len(pairs), 4) if pairs else None
        ),
        "reading": (
            "A decisive rate cannot be trusted beyond the rate at which the same reviewer "
            "gives the same answer to the same image. Both are reported so the second can "
            "be read as a ceiling on the first."
        ),
    }


def _balance(items: list[str], key_by_item: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What the sample turned out to be, per class, over the observations that were scored.

    The manifest records what each class had available and what was requested. Neither says
    what the scored sample was, and a gate whose wording asks for a balanced sample should
    publish the balance rather than the intention.
    """
    counts: dict[str, int] = {}
    for item in items:
        label = key_by_item[item]["label"]
        counts[label] = counts.get(label, 0) + 1
    smallest = min(counts.values()) if counts else 0
    largest = max(counts.values()) if counts else 0
    return {
        "observations_per_class": dict(sorted(counts.items())),
        "balanced": bool(counts) and smallest == largest,
        "smallest_class": smallest,
        "largest_class": largest,
        "reading": (
            "Equal counts per class is what the gate's wording asks for. A source that holds "
            "fewer observations of one class than were requested cannot give it, which is why "
            "the availability is published beside this: an unbalanced sample with a stated "
            "reason is a measurement, and one without is a flaw."
        ),
    }


def _one_axis_against_the_label(
    answers: dict[str, dict[str, str]],
    key_by_item: dict[str, dict[str, Any]],
    axis: str,
    positive: str,
) -> dict[str, Any]:
    """Agreement between one answer axis and the network's own label.

    ``positive`` is the answer value that means the network's `with-signal`. Everything else
    the reviewer committed to means `without-signal`, including `na` on target_consistent,
    which is what a reviewer writes when there is no trace in the frame to judge. `unsure` is
    excluded and counted, because there is no human verdict on that plate to compare.
    """
    scored = 0
    agreed = 0
    excluded_unknown_label = 0
    excluded_unsure = 0
    confusion: dict[str, dict[str, int]] = {}
    committed = _COMMITTED | ({"na"} if axis == "target_consistent" else set())
    for item, answer in answers.items():
        label = key_by_item[item]["label"]
        if label not in {"with-signal", "without-signal"}:
            excluded_unknown_label += 1
            continue
        if answer[axis] not in committed:
            excluded_unsure += 1
            continue
        scored += 1
        human = "with-signal" if answer[axis] == positive else "without-signal"
        confusion.setdefault(label, {}).setdefault(human, 0)
        confusion[label][human] += 1
        if human == label:
            agreed += 1
    return {
        "axis": axis,
        "items_scored": scored,
        "agreed_with_the_network_label": agreed,
        "rate": round(agreed / scored, 4) if scored else None,
        "items_excluded_unknown_label": excluded_unknown_label,
        "items_excluded_reviewer_unsure": excluded_unsure,
        "confusion_network_label_to_human": confusion,
    }


def _label_agreement(
    answers: dict[str, dict[str, str]], key_by_item: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Not the gate. Whether a blinded human reached the network's own verdict.

    Two rates, on two axes, because the first version published one and it was the wrong
    one. `visible_signal` asks whether anything is above the noise anywhere in the frame.
    The network's `waterfall_status` says whether the observation shows the target. A fixed
    local carrier is a yes to the first and a no to the second, so every plate carrying one
    counts as a disagreement by construction and the rate reads as label error when part of
    it is the two axes not asking the same question. `target_consistent` is the axis that
    asks a narrower question than the network label rather than the same one: it wants a
    smooth curve drifting across frequency, and a short packet burst near zero offset is a
    real pass that answers no. So the two axes miss the network's question in opposite
    directions, both are published with their confusion matrices, and neither is named the
    right one. Neither decides the gate.
    """
    signal = _one_axis_against_the_label(answers, key_by_item, "visible_signal", "yes")
    target = _one_axis_against_the_label(answers, key_by_item, "target_consistent", "yes")
    return {
        "neither_axis_asks_the_network_question": (
            "and they miss it in opposite directions, which is why both are here rather "
            "than one being named the right one. visible_signal is too broad: it counts a "
            "fixed local carrier or an interference burst as a signal, and the network "
            "label does not. target_consistent is too narrow: it asks for a smooth curve "
            "drifting across frequency, and a short packet burst parked near zero offset "
            "is a real pass that answers no. Read `by_axis` with the confusion matrices, "
            "not either rate on its own."
        ),
        "by_axis": {"visible_signal": signal, "target_consistent": target},
        # Kept at the top level under the names they have always had, because the console,
        # the sync scripts and the tests read them. They are the visible_signal pair: the
        # looser comparison, and the one whose limitation is stated above.
        "items_scored": signal["items_scored"],
        "agreed_with_the_network_label": signal["agreed_with_the_network_label"],
        "rate": signal["rate"],
        "items_excluded_unknown_label": signal["items_excluded_unknown_label"],
        "items_excluded_reviewer_unsure": signal["items_excluded_reviewer_unsure"],
        "confusion_network_label_to_human": signal["confusion_network_label_to_human"],
        "reading": (
            "This is not gate 4 and it does not decide it. It is the measurement that would "
            "say whether the silver labels this project trains against are what a careful "
            "human sees in the same image with the label hidden. The top-level rate here is "
            "the visible_signal axis, which is the looser of the two: it asks whether "
            "anything is above the noise anywhere in the frame, while the network label says "
            "whether the observation shows the target, so a fixed local carrier disagrees by "
            "construction. The other axis is not the fix: target_consistent asks for a "
            "drifting curve, so a packet burst that is a real pass answers no, and it agrees "
            "with the network on fewer. Both are in `by_axis` with their confusion matrices "
            "and neither is the network's question. Two exclusions, both counted rather than "
            "described: items the network left unknown, because there is nothing to agree "
            "with, and items the reviewer answered unsure on, because there is no human "
            "verdict to compare. The second conditions the rate on the reviewer's own "
            "confidence, which is the direction that flatters it, so the excluded count "
            "belongs beside the rate."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", type=Path, default=Path("D:/tracetriage_gate4"))
    ap.add_argument("--responses", type=Path, default=None)
    ap.add_argument("--key", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--out", type=Path, default=RECEIPT)
    ap.add_argument(
        "--reviewer",
        type=Path,
        default=None,
        help="the reviewer declaration. Defaults to REVIEWER.json in the bundle.",
    )
    args = ap.parse_args(argv)

    responses_path = args.responses or (args.bundle / "responses.csv")
    key_path = args.key or (args.bundle / "KEY_do_not_open_until_scored.json")

    if not args.manifest.exists():
        raise SystemExit(
            f"{args.manifest} is missing, so there is no preregistration to score against. "
            f"Run scripts/build_gate4_worksheet.py first."
        )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    payload: dict[str, Any] = {
        "schema": "GATE4_RECEIPT",
        "schema_version": 1,
        "gate": 4,
        "unit": "E6",
        "threshold": manifest["threshold"],
        "decisive_rule": manifest["decisive_rule"],
        "verdict_rule": manifest["verdict_rule"],
        "ci_method": manifest["ci_method"],
        "worksheet": {
            "source": manifest["source"],
            "seed": manifest["seed"],
            "items": manifest["items"],
            "unique_observations": manifest["unique_observations"],
            "repeated_observations": manifest["repeated_observations"],
            "per_class_requested": manifest["per_class_requested"],
            "observations_available_per_class": manifest[
                "observations_available_per_class"
            ],
            "salt_source": manifest["salt_source"],
            "what_this_sample_size_can_establish": manifest[
                "what_this_sample_size_can_establish"
            ],
        },
    }

    reviewer_path = args.reviewer or (args.bundle / "REVIEWER.json")
    try:
        rows = read_responses(responses_path)  # ScoringError from here is not NOT_RUN
        if rows:
            # Read after the responses and before anything is scored. Before the responses
            # it would refuse an unfilled bundle for the wrong reason, which would report a
            # study nobody has run as an instrument failure.
            reviewer = read_reviewer(reviewer_path)
        if not rows:
            raise NotRun(
                f"{responses_path} has no answered rows. The worksheet exists and nobody has "
                f"filled it in."
            )
        if not key_path.exists():
            raise NotRun(f"no key at {key_path}, so no review has been scored from it")
        try:
            key = json.loads(key_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            # Neither NotRun nor a bare traceback: by the taxonomy above, a key that cannot
            # be parsed is an instrument failure and has to refuse rather than crash.
            raise ScoringError(f"{key_path} is not readable JSON: {exc}") from exc
    except ScoringError as exc:
        # A value nobody can interpret is an instrument failure, not an unfilled worksheet.
        raise SystemExit(f"refusing to score: {exc}") from exc
    except (NotRun, FileNotFoundError) as exc:
        payload |= {
            "verdict": "NOT_RUN",
            "why": str(exc),
            "reading": (
                "NOT_RUN is a third outcome and it is not a failure. The instrument exists, "
                "its sample is committed, and the review has not been carried out. Folding "
                "this into FAILED would manufacture a measurement, and folding it into "
                "silence would hide that the gate is still open."
            ),
        }
        args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        print(f"gate 4: NOT_RUN ({exc})")
        print(f"wrote {args.out}")
        return 0

    # Outside the NOT_RUN branch on purpose: a commitment that does not verify must not
    # produce a receipt at all.
    try:
        images_verified = verify_commitments(manifest, key, args.bundle / "images")
    except ScoringError as exc:
        raise SystemExit(f"refusing to score: {exc}") from exc

    key_by_item = {row["item"]: row for row in key["items"]}
    answers = {row["item"]: row for row in rows}
    unknown_items = sorted(set(answers) - set(key_by_item))
    if unknown_items:
        raise SystemExit(
            f"the responses name items the worksheet does not: {unknown_items[:5]}. "
            f"Refusing to score a file that came from a different bundle."
        )

    # One observation, two items: the pair is the intra-rater measurement, and the first
    # occurrence is the one that counts towards the gate, so a reviewer cannot be scored
    # twice on the same image.
    by_observation: dict[int, list[str]] = {}
    for item in sorted(answers):
        by_observation.setdefault(key_by_item[item]["obs_id"], []).append(item)
    first_occurrences = [items[0] for items in by_observation.values()]
    pairs = [
        (answers[items[0]], answers[items[1]])
        for items in by_observation.values()
        if len(items) > 1
    ]

    decisive = [item for item in first_occurrences if is_decisive(answers[item])]
    trials = len(first_occurrences)
    successes = len(decisive)
    rate = successes / trials
    lower = rate_lower_bound(successes, trials)
    upper = rate_upper_bound(successes, trials)
    threshold = manifest["threshold"]

    if lower is not None and lower >= threshold:
        verdict = "PASSED"
    elif upper is not None and upper < threshold:
        verdict = "FAILED"
    else:
        verdict = "NOT_ESTABLISHED"

    stats: dict[str, Any] = {
        "verdict": verdict,
        "observations_scored": trials,
        "decisive": successes,
        "rate": round(rate, 4),
        "rate_lower_bound_95": None if lower is None else round(lower, 4),
        "rate_upper_bound_95": None if upper is None else round(upper, 4),
        "not_decisive_items": sorted(set(first_occurrences) - set(decisive)),
        "sample_balance": _balance(first_occurrences, key_by_item),
        "stimulus": {
            "images_rehashed_from_disk": images_verified,
            "reading": (
                "Every image was hashed from the bundle and compared against the digest the "
                "commitment was taken over, before any response was read. So the sample, its "
                "order and the pictures themselves are all bound by the same commitment."
            ),
        },
        "intra_rater": _agreement(pairs),
        "reviewer_pace": _pace(rows),
        "network_label_agreement": _label_agreement(
            {item: answers[item] for item in first_occurrences}, key_by_item
        ),
        "reveal": {
            "salt": key["salt"],
            "items": [
                {
                    "item": row["item"],
                    "obs_id": row["obs_id"],
                    "label": row["label"],
                    "image_sha256": row["image_sha256"],
                    "pixel_sha256": row.get("pixel_sha256"),
                }
                for row in key["items"]
            ],
            "reading": (
                "Recompute sha256(salt | item | obs_id | image_sha256) for any item and "
                "compare it against artifacts/GATE4_WORKSHEET.json. Every one was verified "
                "before a single response was read."
            ),
        },
        "per_item": [
            {
                "item": item,
                "decisive": is_decisive(answers[item]),
                **{field: answers[item][field] for field in _ANSWERS},
            }
            for item in sorted(answers)
        ],
    }

    # Where the numbers go depends on who produced them, and the gate's own field does not
    # move for a reviewer the gate is not about. A human review lands in the receipt at the
    # top level, where every consumer already reads it. A review by anything else lands in
    # `arm`, and `verdict` stays NOT_RUN with a `why` that says a review exists: so
    # `sync_kill_gate.py`, the console's gate summary and the MCP `gate_status` tool keep
    # reporting gate 4 as OPEN without knowing this distinction exists. That is deliberate.
    # The alternative is a flag every consumer has to remember to check, and the one that
    # forgets publishes a model's answers as a person's.
    stats["reviewer"] = reviewer
    if reviewer["kind"] == "human":
        payload |= stats
    else:
        payload |= {
            "verdict": "NOT_RUN",
            "why": (
                f"the review was carried out and not by a person: {reviewer['identity']}. "
                f"Gate 4 is titled blinded human decidability, so this does not meet it. "
                f"The review and every number from it are in `arm` below."
            ),
            "reading": (
                "NOT_RUN here means the human arm is still open, not that nothing was "
                "measured. What `arm` establishes is that the sample supports a decisive "
                "judgment by the reviewer named in it, on images bound by the same "
                "commitment, with the network's label and every model output hidden. What "
                "it cannot establish is the gate as written, because the reviewer is the "
                "instrument the gate names and this one is not that instrument."
            ),
            "arm": stats,
        }
    args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    print(f"gate 4: {verdict} (reviewer kind: {reviewer['kind']})")
    print(f"  {successes}/{trials} decisive, rate {rate:.3f}, 95% [{lower:.3f}, {upper:.3f}]")
    if reviewer["kind"] != "human":
        print("  gate 4 itself stays NOT_RUN: the reviewer is not a person")
    intra = stats["intra_rater"]
    print(
        f"  intra-rater: {intra['identical_on_all_three_axes']}/"
        f"{intra['repeated_pairs_scored']} pairs identical on all three axes"
    )
    label = stats["network_label_agreement"]
    print(
        f"  agreement with the network label: {label['agreed_with_the_network_label']}/"
        f"{label['items_scored']}"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
