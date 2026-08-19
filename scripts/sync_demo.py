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
import textwrap

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
_cold6 = _g6["per_split"]["cold_station"]
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
            "This snapshot holds "
            f"{_n_obs():,} observations and only "
            f"{_n_decisive():,} carry a decisive human verdict. TraceTriage decides which "
            "of the rest are worth a reviewer's next hour, and every number it shows you "
            "comes from a receipt you can open."
        ),
        "cites": "artifacts/DATASET_MANIFEST.json",
    },
    {
        "id": 2,
        "beat": "The measurement, running",
        "seconds": 22,
        "screen": (
            "The plate's reveal plays. The fitted corridor arrives among six null "
            "corridors built from the same observation's own Doppler values."
        ),
        "says": (
            "That curve is not drawn on. A matched filter fits it to the image, and the "
            "faint ones are nulls: this observation's own Doppler values shuffled in time, "
            "so they keep every frequency and the whole swing and lose only the order. The "
            f"fit beats all {_dist['n_nulls']} of them. "
            f"{_dist['n_at_least']} nulls reach it, and the exact p is "
            f"{_dist['p_value']:.3f}."
        ),
        "cites": "artifacts/HERO_NULLS.json",
    },
    {
        "id": 3,
        "beat": "One flow: four instruments, one clock",
        "seconds": 28,
        "screen": (
            "One observation page. Scrub the pass. The waterfall with its corridor, a "
            "polar sky track, a ground track with the horizon circle, and elevation and "
            "Doppler against time all move together."
        ),
        "says": (
            "This is one pass on one clock. Scrub it and the Doppler zero crossing lands "
            "at the instant elevation peaks and the range is shortest, because both come "
            "from the same propagated orbit rather than from two drawings made to agree. "
            "A reviewer checks the physics against the image without leaving the row."
        ),
        "cites": None,
    },
    {
        "id": 4,
        "beat": "The model, and what it is not allowed to say",
        "seconds": 22,
        "screen": (
            "The reviewer note on the same observation, then the provenance page's "
            "refusal counts."
        ),
        "says": (
            "A local IBM Granite model writes the first sentence from a closed packet of "
            "printed fields, and a checker refuses any sentence carrying a number that "
            f"packet does not contain. It refused {explain['counts']['refused']} of "
            f"{explain['counts']['decided_by_the_checker']} drafts, and the refusals ship "
            "on the page beside the notes. A generator you never see refusing is a "
            "generator you cannot trust."
        ),
        "cites": "artifacts/EXPLAIN_RECEIPT.json",
    },
    {
        "id": 5,
        "beat": "The product: the queue reorder",
        "seconds": 30,
        "screen": (
            "The queue page. Sort by review value, then toggle to the random-order control "
            "at the same budget. The conflict count moves."
        ),
        "says": (
            "Here is the whole point. Give a reviewer a fixed budget of "
            f"{_chron6['n_queue_examined']} observations. Ranked by review value the queue "
            f"puts {_chron6['n_queue_conflicts']} conflicts in front of them where random "
            f"ordering expects {_chron6['n_random_conflicts']:.1f}. That is "
            f"{_chron6['lift_point']:.2f} times as many findings for the same hour. On the "
            "cold-station split, where every station is one the model never trained on, it "
            f"is {_cold6['lift_point']:.2f} times, with an interval from "
            f"{_cold6['lift_ci95'][0]:.2f} up, clear of the threshold."
        ),
        "cites": "artifacts/QUEUE_RECEIPT.json",
    },
    {
        "id": 6,
        "beat": "And here is what it does not establish",
        "seconds": 28,
        "screen": "The kill gate table, whole, with the three inconclusive rows in view.",
        "says": (
            "Six gates were set before any of this was built, and this is the part most "
            "demos cut. The interval on that lift runs from "
            f"{_chron6['lift_ci95'][0]:.2f} to {_chron6['lift_ci95'][1]:.2f}, which "
            f"straddles the threshold, so it reads {_g6['verdict']} rather than passed. "
            "The corridor gate has only "
            f"{gate3['observations_testable']} testable observations, all three "
            f"discriminate, and three of three still bound the rate at "
            f"{gate3['rate_lower_bound_95']:.3f} against a {gate3['threshold']:.2f} bar. "
            "Retrieval over similar passes beats chance until you forbid the query's own "
            f"ground station, and then the margin is {_pre_cold['margin']:.4f} with an "
            "interval that spans zero."
        ),
        "cites": "artifacts/QUEUE_RECEIPT.json, artifacts/GATE3_RECEIPT.json, "
        "artifacts/PRECEDENT_RECEIPT.json",
    },
    {
        "id": 7,
        "beat": "Why you can check every word of that",
        "seconds": 16,
        "screen": (
            "The provenance page, then the claim register scrolling under the cursor, then "
            "the sign-off receipt."
        ),
        "says": (
            "Every number you have heard is generated from a committed receipt and carries "
            "a row in a register that a test compares against its artifact, so changing one "
            "of them turns the suite red. That is the submission: not a claim that it works, "
            "but a build you can check."
        ),
        "cites": None,
    },
]


def _bullet(text: str) -> str:
    """One list item, wrapped once. A bullet whose text depends on the shot list cannot be
    hand-wrapped: the wrap goes ragged the first time a shot is renumbered."""
    return textwrap.fill(text, width=88, initial_indent="- ", subsequent_indent="  ")


def _shot_where(fragment: str) -> dict:
    """The shot whose beat contains a phrase, or a refusal.

    Two notes below name a shot by number. They were typed, the running order changed in
    D12b, and both went silently wrong: the caveat bullet said shot 3 showed the
    inconclusive verdict early when shot 6 shows it late, and the recording note pointed the
    scrub instruction at the model shot. A number typed beside a list that can be reordered
    is a number that will be wrong, so both are looked up.
    """
    found = [s for s in SHOTS if fragment in s["beat"].lower()]
    if len(found) != 1:
        raise SystemExit(
            f"{len(found)} shots have {fragment!r} in their beat, and the notes name one. "
            "Either the running order changed or two shots now describe the same thing."
        )
    return found[0]


_NUMBER_WORDS = {
    14: "fourteen",
    16: "sixteen",
    22: "twenty-two",
    28: "twenty-eight",
    30: "thirty",
}


def _spell(seconds: int) -> str:
    """Seconds as a word in prose, as a digit when the word is not on hand."""
    return _NUMBER_WORDS.get(seconds, str(seconds))


_CAVEAT_SHOT = _shot_where("does not establish")
_PRODUCT_SHOT = _shot_where("queue reorder")
_INSTRUMENT_SHOT = _shot_where("four instruments")


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
        _bullet(
            f"No passed gate that is not passed. Shot {_CAVEAT_SHOT['id']} gives the "
            f"inconclusive verdicts {_spell(_CAVEAT_SHOT['seconds'])} seconds, straight "
            f"after the product in shot {_PRODUCT_SHOT['id']}, because a demo that hides "
            "them and a console that publishes them are not the same submission. The first "
            "cut put them before the product and it read as a project that had not worked."
        ),
        "",
        "## Recording notes",
        "",
        "- Capture the deployed console at https://tracetriage.vercel.app rather than a dev",
        "  server, so what is recorded is what a judge opens.",
        "- The plate's reveal is CSS `stroke-dashoffset` against `pathLength=1` and costs no",
        "  client JavaScript, so it replays on reload rather than needing a scripted trigger.",
        _bullet(
            f"Shot {_INSTRUMENT_SHOT['id']} needs the scrub handle moved by hand at a "
            "readable speed. The instruments are driven by one time value, so a fast drag "
            "reads as a glitch rather than as agreement."
        ),
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
