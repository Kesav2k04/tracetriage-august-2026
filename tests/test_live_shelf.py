"""The frozen shelf says what it is, and every entry is what it says.

The shelf exists so the live page cannot fail in front of a reader when a cold serverless
start meets a slow volunteer API. That convenience is also the risk: a shelf is a set of
numbers on a page with no visible clock, and the one thing it must never become is a set
of measurements a reader takes for live ones.

So three properties are pinned here, and each one is a way the shelf could quietly stop
being honest.

Every entry started after the snapshot closed. That is the whole claim: nothing here was
available to any model in this repository when it was fitted. An entry from inside the
corpus would still measure correctly and would prove nothing.

Every entry carries the provenance a reader would need to redo it: when it was measured,
the hash of the image it was measured from, and the elements used.

The receipt and the shelf agree, including about the failures. Six entries on a page and
a receipt that only mentions six attempts would hide the refusal rate of the method,
which for UNRESOLVED alone is most of a real queue.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SHELF = REPO / "apps" / "web" / "public" / "data" / "live_shelf.json"
RECEIPT = REPO / "artifacts" / "LIVE_SHELF_RECEIPT.json"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def shelf() -> dict:
    return json.loads(SHELF.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_generator_agrees_with_what_is_committed():
    """`--check` measures nothing, so this is safe in the offline suite."""
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_live_shelf.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_shelf_is_big_enough_to_be_a_shelf(shelf):
    assert shelf["n_observations"] >= 5, (
        "fewer than five and a judge sees a sample rather than a shelf"
    )


def test_every_entry_is_from_after_the_snapshot_closed(shelf):
    cutoff = _parse(shelf["snapshot_cutoff_utc"])
    for entry in shelf["observations"]:
        start = entry["observation"]["start"]
        assert _parse(start) > cutoff, (
            f"observation {entry['observation']['id']} started at {start}, which is "
            f"inside the corpus this project was built on"
        )


def test_every_entry_carries_the_provenance_to_redo_it(shelf):
    for entry in shelf["observations"]:
        provenance = entry["provenance"]
        for field in (
            "measured_at_utc",
            "waterfall_url",
            "waterfall_sha256",
            "tle1",
            "tle2",
        ):
            assert provenance.get(field), (
                f"observation {entry['observation']['id']} has no {field}, so a reader "
                f"cannot check the number against anything"
            )
        assert len(provenance["waterfall_sha256"]) == 64


def test_a_measurement_with_no_verdict_cannot_reach_the_shelf(shelf):
    """UNRESOLVED is a verdict. An absent one is a broken entry."""
    for entry in shelf["observations"]:
        verdict = entry["mode"]["verdict"]
        assert verdict in ("UNCORRECTED", "CORRECTED", "UNRESOLVED"), verdict


def test_an_unresolved_entry_reports_no_offset_and_no_p_value(shelf):
    """The one way a shelf could publish a number it did not measure."""
    for entry in shelf["observations"]:
        if entry["mode"]["verdict"] != "UNRESOLVED":
            continue
        assert entry["measurement"]["offset_ppm"] is None
        assert entry["nulls"]["p_value"] is None
        assert entry["nulls"]["not_tested"], (
            "an untested null needs the reason it was not tested, or the absence reads "
            "as a missing field rather than as a decision"
        )


def test_the_receipt_publishes_every_attempt_not_only_the_shelf(shelf, receipt):
    counts = receipt["counts"]
    assert counts["measured"] == shelf["n_observations"]
    assert len(receipt["attempts"]) >= counts["measured"]
    assert counts["listed"] == len(receipt["attempts"])
    # The interesting number: how many of the recent captures the method could settle.
    assert counts["decisive"] + counts["unresolved"] == counts["measured"]


def test_the_shelf_and_the_receipt_name_the_same_observations(shelf, receipt):
    on_shelf = {int(e["observation"]["id"]) for e in shelf["observations"]}
    measured = {
        int(a["observation_id"]) for a in receipt["attempts"] if a["outcome"] == "MEASURED"
    }
    assert on_shelf == measured


def test_the_shelf_names_the_function_that_produced_it(shelf):
    assert shelf["engine"]["function"] == "pipeline.tracetriage.live.triage", (
        "the shelf's claim is that a button and a fresh measurement differ only in when "
        "they were taken, which is only true while both call this"
    )
