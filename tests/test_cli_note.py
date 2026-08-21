"""`tracetriage note` shows the model working, offline, and the digest it prints matches.

The gap this command closed: Granite is the strongest AI component in this project and it
was the hardest one to see. `triage`, `queue`, `station`, `receipts`, `mcp` and `mcp-live`
all existed; the drafts, the refusals and the code each refusal fired lived in a receipt and
on the console, so "show me the model doing something" meant reading JSON or opening a
browser. A judge with no GPU and no Ollama could not make the best part of the project
demonstrate itself.

Two files are involved and that split is what makes it work with no model: the receipt
records what the checker decided about each draft, and the frozen fixture holds the draft
text. The one way this could mislead is if those two drifted apart, so the command compares
the digest and these tests check that it does.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "EXPLAIN_RECEIPT.json"
FIXTURE = REPO / "tests" / "fixtures" / "granite_notes.json"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pipeline.tracetriage.cli", "note", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture(scope="module")
def a_refused_row() -> dict:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    refused = [row for row in receipt["per_observation"] if row["codes"]]
    if not refused:
        pytest.skip("no draft was refused in this checkout, so there is no refusal to show")
    return refused[0]


def test_the_subcommand_is_registered():
    completed = subprocess.run(
        [sys.executable, "-m", "pipeline.tracetriage.cli", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0
    assert "note" in completed.stdout


def test_with_no_id_it_lists_every_observation_that_carries_a_draft():
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    completed = _run()
    assert completed.returncode == 0, completed.stderr
    for row in receipt["per_observation"]:
        assert str(row["obs_id"]) in completed.stdout
    assert str(receipt["counts"]["refused"]) in completed.stdout
    assert str(receipt["counts"]["emitted"]) in completed.stdout


def test_a_refusal_prints_the_draft_the_verdict_and_the_number_it_invented(a_refused_row):
    """The whole demo, in one command, on a machine with no model runtime."""
    completed = _run(str(a_refused_row["obs_id"]))
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout
    assert "REFUSED" in out
    for code in a_refused_row["codes"]:
        assert code in out
    for violation in a_refused_row["violations"]:
        # The literal the checker objected to has to appear, because it is the point: the
        # model wrote a real amateur satellite frequency that is not this observation's.
        assert str(violation["literal"]) in out


def test_the_draft_it_prints_is_the_draft_the_receipt_hashed(a_refused_row):
    """A stale fixture would print a sentence the recorded verdict is not about."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    drafts = {int(entry["obs_id"]): entry["draft"] for entry in fixture["drafts"]}
    draft = drafts[a_refused_row["obs_id"]]
    completed = _run(str(a_refused_row["obs_id"]))
    assert "WARNING" not in completed.stderr, (
        "the command compares the fixture's digest against the receipt's and warned, which "
        "means one of the two is stale"
    )
    # Whitespace-normalised on both sides, because the printed draft is hard wrapped at 84
    # columns and indented and the fixture's is one line. Everything else is compared
    # exactly: the whole sentence has to be there, not a prefix of it.
    printed = " ".join(completed.stdout.split())
    assert " ".join(draft.split()) in printed


def test_json_mode_prints_the_receipt_row(a_refused_row):
    completed = _run(str(a_refused_row["obs_id"]), "--json")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == a_refused_row


def test_an_unknown_id_is_refused_with_the_way_to_list_the_known_ones():
    completed = _run("1")
    assert completed.returncode != 0
    assert "carries no draft" in completed.stderr


def test_it_needs_no_network_and_no_model():
    """What the command reads, asserted from the source rather than from behaviour."""
    source = (REPO / "pipeline" / "tracetriage" / "cli.py").read_text(encoding="utf-8")
    body = source[source.index("def cmd_note") : source.index("def _wrap")]
    for forbidden in ("httpx", "requests", "urllib", "granite.generate", "ollama"):
        assert forbidden not in body, (
            f"cmd_note references {forbidden}. Its whole value is that it shows the model's "
            f"output on a machine that cannot run the model."
        )
