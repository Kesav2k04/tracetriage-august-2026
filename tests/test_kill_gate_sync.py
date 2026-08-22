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


def _pool_receipt(pool_name, scored=10, rate=1.0, bound=0.7411, verdict="PASSED"):
    """The fields `_gate3_pools` reads, and nothing else."""
    r = {
        "observations_scored": scored,
        "discriminating_rate": rate,
        "rate_lower_bound_95": bound,
        "verdict": verdict,
        "threshold": 0.70,
    }
    if pool_name is not None:
        r["pool"] = {"name": pool_name}
    return r


def test_the_pool_row_is_labelled_by_the_receipt_not_by_position():
    """The defect this table shipped with on its first render.

    The label was hardcoded to pool B. Against the A3 receipt that was actually in the
    tree it printed "B, pre-registered" over observations the corridor selected, so the
    one document that exists to keep the two pools apart merged them in its own table.
    """
    from scripts.sync_kill_gate import _gate3_pools

    a3 = _gate3_pools(_pool_receipt("a3", scored=3, rate=1.0, bound=0.3684,
                               verdict="NOT_ESTABLISHED"), None)
    table = a3.split("\n\n")[0]
    assert "pre-registered" not in table, (
        "the A3 receipt is being labelled as the pre-registered pool. Only the table "
        "rows are checked: the prose below may say the pre-registered pools are unscored"
    )
    assert "A3's decisive set" in a3

    b = _gate3_pools(_pool_receipt("pool_b"), None)
    assert "**B, pre-registered**" in b

    a = _gate3_pools(_pool_receipt("pool_a"), None)
    assert "A, corridor-selected" in a
    assert "**B, pre-registered**" not in a, (
        "a pool A receipt must never be rendered as the pool that decides the gate"
    )


def test_an_unscored_comparison_reads_as_not_run_rather_than_as_zero():
    """A blank row that looks like a measurement is worse than no row."""
    from scripts.sync_kill_gate import _gate3_pools

    out = _gate3_pools(_pool_receipt("pool_b"), None)
    assert "| A, corridor-selected | not run |" in out
    assert "| A, corridor-selected | 0 |" not in out


def test_the_gap_between_the_pools_is_reported_when_both_have_run():
    """The number the comparison exists for.

    Publishing both rates and leaving the reader to subtract them is how a selection
    effect goes unnoticed. E16 section 5 asks for the comparison, so the size of it is
    stated.
    """
    from scripts.sync_kill_gate import _gate3_pools

    out = _gate3_pools(
        _pool_receipt("pool_b", scored=100, rate=0.55, bound=0.4600, verdict="FAILED"),
        _pool_receipt("pool_a", scored=100, rate=0.95, bound=0.9000, verdict="PASSED"),
    )
    assert "+40 percentage points" in out, (
        "a 55% pre-registered rate beside a 95% corridor-selected one is a 40 point "
        "selection effect, and the table has to say so"
    )


def test_only_pool_b_is_ever_called_the_gate():
    """No rendering of this table may present pool A's rate as the gate's."""
    from scripts.sync_kill_gate import _gate3_pools

    out = _gate3_pools(
        _pool_receipt("pool_b", scored=40, rate=0.60, bound=0.4700, verdict="FAILED"),
        _pool_receipt("pool_a", scored=40, rate=1.0, bound=0.9284, verdict="PASSED"),
    )
    assert "Only pool B decides the gate" in out
    assert "circularity" in out
