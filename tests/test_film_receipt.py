"""The film's receipt, and whether it describes the film that is actually committed.

`artifacts/FILM_RECEIPT.json` is written by `presentation/scripts/report-table.ts` from
`presentation/src`, so every field in it is derived rather than typed. That makes one class
of error impossible and leaves two open, and those two are what this module is about.

The first is arithmetic that does not close: a composition whose frame count is not the sum
of its beats, or claim counts that do not add up to the total. A generated file can be
internally wrong and still be generated.

The second is a receipt that has drifted from the tree it describes. The digests are checked
against the rendered files by `scripts/check_receipt_digests.py`, which is a standing gate.
What is not checked there is everything else the receipt names: the artifacts the film reads
from, the byte counts, and the duration that `presentation/REPORT.md` and `FOR_JUDGES.md`
both quote. A receipt whose `reads` list points at a file nobody publishes would sail
through a digest audit.

The duration also carries a rule from outside this repository. The competition caps a
presentation at three minutes, and the film is the artifact that cap applies to, so the
bound is asserted here against the receipt rather than left in a comment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "FILM_RECEIPT.json"

#: The competition's ceiling, in seconds. From the Official Rules: "a publicly accessible
#: demo or presentation video (maximum 3 minutes)".
RULES_CEILING_SECONDS = 180


@pytest.fixture(scope="module")
def film() -> dict:
    """The committed receipt, or a skip that says why there is none."""
    if not RECEIPT.exists():
        pytest.skip(
            "artifacts/FILM_RECEIPT.json does not exist in this checkout. It is written by "
            "`npm run report` in presentation/, which scripts/gate.py runs with --check."
        )
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_composition_adds_up(film: dict) -> None:
    """A generated file can still be internally wrong."""
    composition = film["composition"]
    beats = film["beats"]

    assert composition["beats"] == len(beats)
    assert composition["frames"] == sum(beat["frames"] for beat in beats), (
        "the composition's frame count is not the sum of its beats, so one of the two was "
        "computed from something else"
    )
    assert composition["seconds"] == pytest.approx(
        composition["frames"] / composition["fps"], abs=0.001
    )
    for beat in beats:
        assert beat["frames"] > 0, f"{beat['name']} has no frames"
        assert beat["seconds"] == pytest.approx(
            beat["frames"] / composition["fps"], abs=0.001
        )
    assert len({beat["name"] for beat in beats}) == len(beats), "two beats share a name"


def test_the_film_fits_the_ceiling_the_rules_set(film: dict) -> None:
    """Three minutes is the rule, and the film is what it applies to."""
    seconds = film["composition"]["seconds"]
    assert seconds <= RULES_CEILING_SECONDS, (
        f"the film runs {seconds} seconds against a {RULES_CEILING_SECONDS} second "
        "ceiling in the Official Rules"
    )
    # A film that has collapsed to nothing would also satisfy the line above.
    assert seconds > 60, f"the film is {seconds} seconds, which is not a presentation"


def test_the_claim_counts_are_one_partition_of_the_same_set(film: dict) -> None:
    """Drawn plus read-only has to be the total, and per-file has to be the same total."""
    claims = film["claims"]
    assert claims["drawn"] + claims["read_but_not_drawn"] == claims["total"]
    assert sum(claims["per_file"].values()) == claims["total"], (
        "the per-file breakdown and the total disagree, so one of them counts something "
        "the other does not"
    )
    assert claims["drawn"] > 0
    assert set(claims["per_file"]) == set(film["reads"]), (
        "the files the claims come from and the files the receipt says it reads are "
        "different sets"
    )


def test_every_file_the_film_reads_is_here(film: dict) -> None:
    """A `reads` list is a claim about the tree, and the digest audit does not check it."""
    missing = [rel for rel in film["reads"] if not (REPO / rel).is_file()]
    assert missing == [], f"the film reads files that are not in this checkout: {missing}"
    assert film["reads"] == sorted(film["reads"]), "the reads list is not sorted"


@pytest.mark.parametrize("kind", ["render", "poster"])
def test_the_rendered_files_are_the_size_the_receipt_records(film: dict, kind: str) -> None:
    """Byte count and digest shape. The digest itself is a standing gate of its own.

    `scripts/check_receipt_digests.py` compares `sha256` against the file. What it cannot
    catch is a digest that is not a digest, or a byte count copied from the other file, and
    both would make the receipt look complete.
    """
    entry = film[kind]
    if entry is None:
        pytest.skip(f"this checkout holds no {kind}; the receipt records null rather than 0")

    path = REPO / entry["path"]
    if not path.is_file():
        pytest.skip(f"{entry['path']} is not in this checkout")

    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]), entry["sha256"]
    assert entry["bytes"] == path.stat().st_size, (
        f"{entry['path']} is {path.stat().st_size} bytes and the receipt says "
        f"{entry['bytes']}"
    )


def test_the_report_and_the_receipt_describe_the_same_film(film: dict) -> None:
    """The document a reader opens, against the receipt a gate checks.

    `presentation/REPORT.md` is regenerated in the same pass that writes this receipt, but
    only its claim table is: the prose around it is written by hand and names the frame
    count and the duration. This is the check that the hand-written half did not stay behind
    when the film changed.
    """
    report = REPO / "presentation" / "REPORT.md"
    if not report.is_file():
        pytest.skip("presentation/REPORT.md is not in this checkout")

    text = report.read_text(encoding="utf-8")
    frames = film["composition"]["frames"]
    assert str(frames) in text, (
        f"REPORT.md never names {frames} frames, so its prose is describing a different "
        "cut of the film than the receipt does"
    )
    # `:g` rather than int(), because 30 fps does not guarantee a whole number of seconds
    # and truncating here while the generated page rounds would put two durations in the
    # tree that disagree by a second.
    seconds = f"{film['composition']['seconds']:g}"
    assert f"{seconds} second" in text, (
        f"REPORT.md never says {seconds} second, which is what the receipt computes from "
        "the beat list"
    )


def test_the_reports_beat_table_names_the_windows_the_receipt_computes(film: dict) -> None:
    """Every row of the hand-written beat table, against the beat list.

    The test above catches the total moving. It cannot catch a beat inside the film
    getting longer while the total stays put, and it cannot catch what actually happened
    when the narration went in: six of the eight beats were retimed at once, and the
    table went on printing the old windows beside prose that was still correct.

    So each row's frame window is recomputed from the receipt's own beat list and looked
    for in the document. A retimed beat now fails here rather than leaving a reader with
    a timecode that points at the wrong card.
    """
    report = REPO / "presentation" / "REPORT.md"
    if not report.is_file():
        pytest.skip("presentation/REPORT.md is not in this checkout")

    text = report.read_text(encoding="utf-8")
    fps = film["composition"]["fps"]
    start = 0
    missing = []
    for beat in film["beats"]:
        end = start + beat["frames"] - 1
        window = f"{start} to {end}"
        span = f"{start / fps:.1f} to {(end + 1) / fps:.1f}"
        if window not in text:
            missing.append(f"{beat['name']}: frames {window!r}")
        if span not in text:
            missing.append(f"{beat['name']}: seconds {span!r}")
        start = end + 1

    assert not missing, (
        "REPORT.md's beat table does not name these windows, so it is describing a "
        "different cut: " + "; ".join(missing)
    )


def test_what_it_does_not_measure_is_stated_rather_than_implied(film: dict) -> None:
    """Every receipt here carries its own limits, and an empty list is not a limit."""
    limits = film["what_this_does_not_measure"]
    assert len(limits) >= 3
    for line in limits:
        assert line.strip().endswith("."), line
        assert len(line) > 40, f"a limit this short is a label, not a limit: {line}"
