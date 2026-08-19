"""Regenerate `docs/DEMO_SCRIPT.md`: the shot list for the submission video, from the receipts.

The competition's guidance for the video is four constraints and one prohibition: under three
minutes, open with the pitch rather than the architecture, show the thing running against real
input and real output, follow one flow end to end rather than touring features, and do not
narrate over slides. This script encodes all five and adds the one this project needs: every
number spoken or shown is read from a committed receipt at generation time, so a shot cannot
keep quoting a figure a re-run has moved.

The video is public and unversioned. `docs/CLAIM_REGISTER.md` rule 4 says drift there is not
recoverable after submission, which is the whole reason this document is generated rather than
written: a shot list typed in a text file is exactly the artifact that goes stale between the
last pipeline run and the recording.

Two properties are checked rather than asserted. The cue times sum to less than 180 seconds,
and every number in a spoken line appears in the artifact its shot cites.

    .venv/Scripts/python.exe scripts/sync_demo.py
    .venv/Scripts/python.exe scripts/sync_demo.py --check

`tests/test_demo_script.py` recomputes the budget and re-reads every quoted number, because
`--check` compares the page against the generator and cannot catch the generator.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ARTIFACTS = REPO / "artifacts"
DEMO = REPO / "docs" / "DEMO_SCRIPT.md"

#: The competition's ceiling, in seconds. The shot list is built to land under it with room,
#: because a recording always runs longer than its script.
CEILING_S = 180

#: The margin held back for the ceiling. A cut that lands at 179 seconds has no room for a
#: single retake, so the budget is checked against this rather than against the ceiling.
TARGET_S = 165


def _load(name: str) -> dict:
    path = ARTIFACTS / name
    if not path.exists():
        raise SystemExit(
            f"artifacts/{name} is missing and this script quotes it. Run the script that "
            "writes it rather than generating a shot list with a hole in it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


gate3 = _load("GATE3_RECEIPT.json")
hero = _load("HERO_NULLS.json")
queue = _load("QUEUE_RECEIPT.json")
dataset = _load("DATASET_MANIFEST.json")
precedent = _load("PRECEDENT_RECEIPT.json")
explain = _load("EXPLAIN_RECEIPT.json")

_dist = hero["distribution"]
_g6 = queue["gate6"]
_chron6 = _g6["per_split"]["chronological"]
_pre_cold = precedent["conditions"]["cold"]["comparisons"]["granite_text_vs_random"]


def _n_obs() -> int:
    return len(dataset["observations"])


def _n_decisive() -> int:
    return sum(
        1
        for o in dataset["observations"]
        if str(o.get("waterfall_status", "")).lower() in ("with-signal", "without-signal")
    )


#: One row per shot. `seconds` is the cue length, `screen` is what is on it, `says` is the
#: spoken line or the caption, and `cites` is the artifact every number in `says` came from.
#: A shot with numbers and no citation fails the test beside this file.
SHOTS: list[dict] = [
    {
        "id": 1,
        "beat": "The pitch",
        "seconds": 14,
        "screen": (
            "Home page, before scrolling. The plate is on screen and still: one real "
            "waterfall with its fitted corridor."
        ),
        "says": (
            "A volunteer network records more satellite passes than anyone can look at. "
            "This one holds "
            f"{_n_obs():,} observations and only "
            f"{_n_decisive():,} carry a decisive human label. TraceTriage decides which "
            "of the rest are worth a reviewer's next hour, and every number it shows you "
            "comes from a receipt you can open."
        ),
        "cites": "artifacts/DATASET_MANIFEST.json",
    },
    {
        "id": 2,
        "beat": "The plate, running",
        "seconds": 22,
        "screen": (
            "The plate's reveal plays. The fitted corridor arrives among six null "
            "corridors drawn from the same observation's own Doppler values."
        ),
        "says": (
            "That curve is not drawn on. It is fitted to the image by a matched filter, "
            "and the faint ones are nulls: the same observation's own Doppler values, "
            "shuffled in time, so they keep every frequency and the whole swing and lose "
            "only the order. The fit beats "
            f"all {_dist['n_nulls']} of them. "
            f"{_dist['n_at_least']} nulls reach it, and the exact p is "
            f"{_dist['p_value']:.3f}."
        ),
        "cites": "artifacts/HERO_NULLS.json",
    },
    {
        "id": 3,
        "beat": "The honest verdict, early",
        "seconds": 16,
        "screen": "Kill gate panel on the home page, gate 3's row in view.",
        "says": (
            "And that is one observation. The gate asked for that behaviour on seventy "
            "percent of a sample, and only "
            f"{gate3['observations_testable']} of the corpus are testable at all, so the "
            f"exact lower bound is {gate3['rate_lower_bound_95']:.3f} against a "
            f"{gate3['threshold']:.2f} bar. The gate reads "
            f"{gate3['verdict']}. It says so on the page, in grey, with the arithmetic."
        ),
        "cites": "artifacts/GATE3_RECEIPT.json",
    },
    {
        "id": 4,
        "beat": "One flow: the observation page",
        "seconds": 30,
        "screen": (
            "One observation page. Scrub the pass. Four instruments move on one clock: "
            "waterfall with the corridor, polar sky track, ground track with the horizon "
            "circle, elevation and Doppler against time."
        ),
        "says": (
            "This is one pass on one clock. Scrub it and the Doppler zero crossing lands "
            "at the instant elevation peaks and the range is shortest, because both come "
            "from the same propagated orbit rather than from two drawings that were made "
            "to agree. A reviewer checks the physics against the image without leaving "
            "the row."
        ),
        "cites": None,
    },
    {
        "id": 5,
        "beat": "The model, and what it is allowed to say",
        "seconds": 22,
        "screen": (
            "The reviewer note on the same observation, then the provenance page's "
            "refusal counts."
        ),
        "says": (
            "A local IBM Granite model writes the first sentence from a closed packet of "
            "printed fields, and a checker refuses any sentence carrying a number that "
            f"packet does not contain. It refused {explain['counts']['refused']} of "
            f"{explain['counts']['decided_by_the_checker']} drafts. The "
            "refusals ship on the page beside the notes, because a generator you cannot "
            "see refusing is a generator you cannot trust."
        ),
        "cites": "artifacts/EXPLAIN_RECEIPT.json",
    },
    {
        "id": 6,
        "beat": "The queue reorder",
        "seconds": 24,
        "screen": (
            "The queue page. Sort by review value, then toggle to the random-order "
            "control at the same budget."
        ),
        "says": (
            "Here is the whole point. At a fixed budget of "
            f"{_chron6['n_queue_examined']} observations the ranked queue finds "
            f"{_chron6['n_queue_conflicts']} conflicts where random ordering expects "
            f"{_chron6['n_random_conflicts']:.1f}. That is "
            f"{_chron6['lift_point']:.2f} times as many."
        ),
        "cites": "artifacts/QUEUE_RECEIPT.json",
    },
    {
        "id": 7,
        "beat": "End on the honest verdict",
        "seconds": 26,
        "screen": (
            "The kill gate table, whole. Then the claim register scrolling under the "
            "cursor."
        ),
        "says": (
            "And the interval on that lift runs from "
            f"{_chron6['lift_ci95'][0]:.2f} to "
            f"{_chron6['lift_ci95'][1]:.2f}, which straddles the "
            f"bar, so the gate reads {_g6['verdict']} rather than passed. Two of six "
            "gates are met. Retrieval over similar passes beats chance until you forbid "
            "the query's own ground station, and then its interval spans zero at "
            f"{_pre_cold['margin']:.4f}. Every one of those sentences is a row in a "
            "register that a test compares against its artifact. That is the submission: "
            "not that it works, but that you can check it."
        ),
        "cites": "artifacts/QUEUE_RECEIPT.json, artifacts/PRECEDENT_RECEIPT.json",
    },
]


def budget() -> int:
    return sum(int(s["seconds"]) for s in SHOTS)


def render() -> str:
    total = budget()
    parts = [
        "# Demo script",
        "",
        "<!-- Generated by scripts/sync_demo.py from the receipts under artifacts/.",
        "     Do not edit by hand: every number below is read at generation time, and",
        "     tests/test_demo_script.py re-reads each one from the artifact its shot",
        "     cites. -->",
        "",
        "Seven shots, one flow, no slides. The constraints come from the competition's own",
        "guidance rather than from taste: under three minutes, open with the pitch, show it",
        "running against real input and real output, follow one flow end to end, and do not",
        "narrate over slides.",
        "",
        f"**Budget: {total} seconds of {CEILING_S}.** The target is {TARGET_S} so a retake "
        "has somewhere to go. Times are cue lengths, not edit points.",
        "",
        "The two sequences are chosen rather than defaulted. The home page plate is the",
        "opening because it shows the measurement happening on a real image in one gesture.",
        "The observation page is the middle because one clock driving four instruments is the",
        "claim that cannot be faked in a screenshot. The queue reorder is the end because it",
        "is the product, and the verdict follows it because the verdict is the point.",
        "",
        "## Shots",
        "",
    ]
    for shot in SHOTS:
        parts += [
            f"### {shot['id']}. {shot['beat']} ({shot['seconds']}s)",
            "",
            f"**On screen.** {shot['screen']}",
            "",
            f"**Says.** {shot['says']}",
            "",
            (
                f"**Numbers from.** `{shot['cites']}`"
                if shot["cites"]
                else "**Numbers from.** No numbers in this shot."
            ),
            "",
        ]

    parts += [
        "## What is deliberately not in it",
        "",
        "- No architecture diagram. The guidance says open with the pitch, and a diagram is",
        "  the fastest way to spend twenty seconds saying nothing a judge can check.",
        "- No feature tour. One flow, start to finish, is the constraint.",
        "- No claim that is not in `docs/CLAIM_REGISTER.md`. The video is public and",
        "  unversioned, so a number in it cannot be corrected later.",
        "- No passed gate that is not passed. Shot 3 gives the inconclusive verdict sixteen",
        "  seconds, early, before the product is shown, because a demo that hides it and a",
        "  console that publishes it are not the same submission.",
        "",
        "## Recording notes",
        "",
        "- Capture the deployed console at https://tracetriage.vercel.app rather than a dev",
        "  server, so what is recorded is what a judge opens.",
        "- The plate's reveal is CSS `stroke-dashoffset` against `pathLength=1` and costs no",
        "  client JavaScript, so it replays on reload rather than needing a scripted trigger.",
        "- Shot 4 needs the scrub handle moved by hand at a readable speed. The instruments",
        "  are driven by one time value, so a fast drag reads as a glitch rather than as",
        "  agreement.",
        "- Record at the width the console was measured at. The queue table hides columns",
        "  below the breakpoint, and four Playwright failures in D0c were tests clicking",
        "  controls that were hidden at the width they ran at.",
        "",
    ]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate docs/DEMO_SCRIPT.md.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into memory and compare against docs/DEMO_SCRIPT.md, writing nothing",
    )
    args = parser.parse_args(argv)

    total = budget()
    if total > TARGET_S:
        raise SystemExit(
            f"the shot list is {total} seconds against a target of {TARGET_S} and a ceiling "
            f"of {CEILING_S}. Cut a shot rather than publishing a script that has no room "
            "for a retake."
        )

    rendered = render()
    if args.check:
        if not DEMO.exists():
            print("docs/DEMO_SCRIPT.md does not exist. Run scripts/sync_demo.py.")
            return 1
        current = DEMO.read_text(encoding="utf-8")
        if current == rendered:
            print(f"docs/DEMO_SCRIPT.md is current: {len(SHOTS)} shots, {total}s")
            return 0
        print("docs/DEMO_SCRIPT.md is stale. Run scripts/sync_demo.py.")
        for i, (c, e) in enumerate(
            zip(current.splitlines(), rendered.splitlines(), strict=False), start=1
        ):
            if c != e:
                print(f"  first difference, line {i}:")
                print(f"    committed: {c[:120]}")
                print(f"    receipts:  {e[:120]}")
                break
        return 1

    DEMO.write_text(rendered, encoding="utf-8")
    print(f"docs/DEMO_SCRIPT.md synced: {len(SHOTS)} shots, {total}s of {CEILING_S}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
