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
            rows.append({"item": (row.get("item") or "").strip(), **answers})

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


def _label_agreement(
    answers: dict[str, dict[str, str]], key_by_item: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Not the gate. Whether a blinded human reached the network's own verdict."""
    scored = 0
    agreed = 0
    excluded_unknown_label = 0
    excluded_unsure = 0
    confusion: dict[str, dict[str, int]] = {}
    for item, answer in answers.items():
        label = key_by_item[item]["label"]
        if label not in {"with-signal", "without-signal"}:
            excluded_unknown_label += 1
            continue
        if answer["visible_signal"] not in _COMMITTED:
            excluded_unsure += 1
            continue
        scored += 1
        human = "with-signal" if answer["visible_signal"] == "yes" else "without-signal"
        confusion.setdefault(label, {}).setdefault(human, 0)
        confusion[label][human] += 1
        if human == label:
            agreed += 1
    return {
        "items_scored": scored,
        "agreed_with_the_network_label": agreed,
        "rate": round(agreed / scored, 4) if scored else None,
        "items_excluded_unknown_label": excluded_unknown_label,
        "items_excluded_reviewer_unsure": excluded_unsure,
        "confusion_network_label_to_human": confusion,
        "reading": (
            "This is not gate 4 and it does not decide it. It is the measurement that would "
            "say whether the silver labels this project trains against are what a careful "
            "human sees in the same image with the label hidden. Two exclusions, both "
            "counted above rather than described: items the network left unknown, because "
            "there is nothing to agree with, and items where the reviewer answered unsure on "
            "visible_signal, because there is no human verdict to compare. The second "
            "conditions this rate on the reviewer's own confidence, which is the direction "
            "that flatters it, so the excluded count belongs beside the rate."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", type=Path, default=Path("D:/tracetriage_gate4"))
    ap.add_argument("--responses", type=Path, default=None)
    ap.add_argument("--key", type=Path, default=None)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--out", type=Path, default=RECEIPT)
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

    try:
        rows = read_responses(responses_path)  # ScoringError from here is not NOT_RUN
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

    payload |= {
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
    args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    print(f"gate 4: {verdict}")
    print(f"  {successes}/{trials} decisive, rate {rate:.3f}, 95% [{lower:.3f}, {upper:.3f}]")
    intra = payload["intra_rater"]
    print(
        f"  intra-rater: {intra['identical_on_all_three_axes']}/"
        f"{intra['repeated_pairs_scored']} pairs identical on all three axes"
    )
    label = payload["network_label_agreement"]
    print(
        f"  agreement with the network label: {label['agreed_with_the_network_label']}/"
        f"{label['items_scored']}"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
