"""docs/KILL_GATE.md must equal what its generator renders from the receipts.

Two properties are asserted here, and the second is the one that was missing.

1. No drift. The committed document equals `sync_kill_gate.render()` applied to it, so
   a receipt that moves without the document being re-synced fails the suite.

2. Idempotence. The first generator was a one-shot text fixup: it replaced one exact
   hardcoded old string per row and asserted that string was present, so its second run
   died on `AssertionError: gate 5 summary row not found`. It also appended a correction
   paragraph on every run. Meanwhile the document said the sections "are now generated
   from the receipt by scripts/sync_kill_gate.py, so the next re-run cannot leave them
   behind", and the Wave D prompt told the next builder to re-run it after any pipeline
   re-run. Both were false. `test_render_is_idempotent` fails against that version.

These run offline: the receipts are committed artifacts and the document is tracked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.sync_kill_gate import DOC, REPO, render

ARTIFACTS = REPO / "artifacts"


@pytest.fixture(scope="module")
def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _receipt(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))


def test_document_is_in_sync_with_the_receipts(doc: str):
    """The committed file is what the receipts say it should be."""
    assert render(doc) == doc, (
        "docs/KILL_GATE.md has drifted from the receipts. Run "
        ".venv/Scripts/python.exe scripts/sync_kill_gate.py"
    )


def test_render_is_idempotent(doc: str):
    """Rendering twice writes the same bytes. The old generator could not run twice."""
    once = render(doc)
    twice = render(once)
    assert once == twice


def test_generated_gate3_row_matches_its_receipt(doc: str):
    g3 = _receipt("GATE3_RECEIPT.json")
    row = next(line for line in doc.splitlines() if line.startswith("| 3 |"))
    assert g3["verdict"] in row
    assert f"{g3['rate_lower_bound_95']:.3f}" in row
    # The row must carry the bound, not only the point estimate. A row that quoted
    # 100% alone is what let this gate read PASSED.
    assert "0.368" in row
    assert row.count("|") == 5


def test_generated_gate5_and_gate6_rows_match_their_receipts(doc: str):
    fusion = _receipt("FUSION_RECEIPT.json")
    queue = _receipt("QUEUE_RECEIPT.json")
    g5 = fusion["gate5"]["per_split"]["chronological"]
    chron = queue["gate6"]["per_split"]["chronological"]

    row5 = next(line for line in doc.splitlines() if line.startswith("| 5 |"))
    assert f"+{g5['margin']:.5f}" in row5
    assert f"{g5['n_observations']} test observations" in row5

    row6 = next(line for line in doc.splitlines() if line.startswith("| 6 |"))
    assert f"{chron['lift_point']:.3f}" in row6
    assert f"[{chron['lift_ci95'][0]:.3f}, {chron['lift_ci95'][1]:.3f}]" in row6


def test_gate6_sample_size_is_not_gate5s(doc: str):
    """87 and 88 are two populations, and the document once quoted 88 for both."""
    queue = _receipt("QUEUE_RECEIPT.json")
    fusion = _receipt("FUSION_RECEIPT.json")
    decisive6 = {s["split"]: s for s in queue["per_split_summaries"]}["chronological"][
        "n_test_decisive"
    ]
    n5 = fusion["gate5"]["per_split"]["chronological"]["n_observations"]
    assert decisive6 != n5, "the fixture no longer distinguishes the two counts"

    row6 = next(line for line in doc.splitlines() if line.startswith("| 6 |"))
    assert f"{decisive6} decisive test observations" in row6
    assert f"{n5} decisive test observations" not in row6


def test_a_moved_receipt_value_fails_the_sync(doc: str, tmp_path: Path):
    """The drift check can fail. A test that cannot fail is not a check."""
    mutated = doc.replace("Point lift 1.582", "Point lift 9.999")
    assert mutated != doc, "the fixture no longer contains the value being mutated"
    assert render(mutated) != mutated
