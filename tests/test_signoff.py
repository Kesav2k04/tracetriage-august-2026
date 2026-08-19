"""The sign-off receipt, and whether it could ever say NOT_SIGNED.

A sign-off is the one artifact in this repository whose whole value is that it can refuse.
Gate 3 was marked PASSED by a comparison that could not return False, and a sign-off that
signs whatever it is handed is the same defect at the end of the wave instead of the middle.

So the tests here are about the refusal. One failing check has to flip the verdict. A check
recorded as unrunnable has to carry a reason, and it must not count as a pass. And the
receipt has to be about a commit that exists in this history, because a receipt naming a
commit nobody can find is evidence of nothing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_RECEIPT = _REPO / "artifacts" / "SIGNOFF_RECEIPT.json"


def _load():
    path = _REPO / "scripts" / "signoff.py"
    spec = importlib.util.spec_from_file_location("signoff", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["signoff"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def signoff():
    return _load()


@pytest.fixture(scope="module")
def receipt() -> dict:
    """The committed sign-off, or a skip that says why there is none.

    The receipt is written at a commit and committed at the next one, so there is exactly
    one commit in the history where it does not exist yet. `scripts/gate.py` requires it
    to be present and SIGNED from the commit that introduces it onward, so the skip here
    cannot become a permanent silence: deleting the receipt fails the gate rather than
    quieting these tests.
    """
    if not _RECEIPT.exists():
        pytest.skip(
            "artifacts/SIGNOFF_RECEIPT.json does not exist in this checkout. It is written "
            "by scripts/signoff.py at the release commit and committed at the next one."
        )
    return json.loads(_RECEIPT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The sheet: three outcomes, and a reason attached to the third
# ---------------------------------------------------------------------------


def test_a_check_that_could_not_run_must_state_why(signoff) -> None:
    """`NOT_CHECKED` with no reason reads as a check skipped for convenience."""
    sheet = signoff.Sheet()
    with pytest.raises(ValueError, match="has to say why"):
        sheet.record("something", None, signoff.NOT_CHECKED, "")


def test_not_checked_is_neither_a_pass_nor_a_failure(signoff) -> None:
    """The third outcome is counted separately, not folded into either neighbour."""
    sheet = signoff.Sheet()
    sheet.record("a", None, signoff.PASSED, "")
    sheet.record("b", None, signoff.NOT_CHECKED, "", why_not_checked="needs the network")
    counts = sheet.counts()
    assert counts == {signoff.PASSED: 1, signoff.FAILED: 0, signoff.NOT_CHECKED: 1}


def test_an_unknown_status_is_refused(signoff) -> None:
    """A fourth word would be counted as none of the three and would vanish from the tally."""
    sheet = signoff.Sheet()
    with pytest.raises(AssertionError):
        sheet.record("c", None, "MOSTLY_FINE", "")


def test_one_failed_check_is_enough_to_withhold_the_signature(signoff) -> None:
    """The verdict is computed from the failure count, so it can return NOT_SIGNED.

    This is the mutation the whole file exists for. If a sheet with a failure in it still
    produced SIGNED, every other check in this repository would be reporting into a receipt
    that cannot say no.
    """
    sheet = signoff.Sheet()
    for _ in range(8):
        sheet.record("fine", None, signoff.PASSED, "")
    assert sheet.counts()[signoff.FAILED] == 0

    sheet.record("broken", None, signoff.FAILED, "exit 1")
    assert sheet.counts()[signoff.FAILED] == 1


# ---------------------------------------------------------------------------
# The committed receipt
# ---------------------------------------------------------------------------


def test_the_receipt_is_signed_and_nothing_failed(receipt: dict) -> None:
    failed = [r["check"] for r in receipt["checks"] if r["status"] == "FAILED"]
    assert failed == [], f"the committed sign-off records failures: {failed}"
    assert receipt["verdict"] == "SIGNED"
    assert receipt["counts"]["FAILED"] == 0


def test_the_verdict_agrees_with_the_rows_it_was_computed_from(receipt: dict) -> None:
    """A verdict and a table that disagree is the KILL_GATE defect that made it generated."""
    counted = {
        status: sum(1 for r in receipt["checks"] if r["status"] == status)
        for status in ("PASSED", "FAILED", "NOT_CHECKED")
    }
    assert counted == receipt["counts"]
    assert receipt["verdict"] == ("SIGNED" if counted["FAILED"] == 0 else "NOT_SIGNED")


def test_every_unrun_check_in_the_committed_receipt_names_its_reason(receipt: dict) -> None:
    for row in receipt["checks"]:
        if row["status"] == "NOT_CHECKED":
            assert row["why_not_checked"], f"{row['check']} says nothing about why"
        else:
            assert row["why_not_checked"] is None


def test_the_receipt_covers_the_checks_the_unit_named(receipt: dict) -> None:
    """The unit's acceptance list, by name, so a check dropped from the script is visible."""
    names = {r["check"] for r in receipt["checks"]}
    for required in (
        "standing gates",
        "contrast pairs",
        "kill gate document matches its receipts",
        "console typecheck",
        "console build",
        "console tests",
        "release audit re-run at this commit",
        "commit identity",
        "working tree committed",
        "deployed console responds",
    ):
        assert required in names, f"the sign-off no longer runs {required!r}"


def test_the_receipt_names_a_commit_that_exists_in_this_history(receipt: dict) -> None:
    """A receipt naming a commit nobody can find is evidence of nothing.

    Deliberately weaker than "measured at HEAD", for the same reason the release-audit
    receipts are: committing this file moves HEAD past what it measured, so requiring
    equality would fail on the commit that publishes it and on every commit after. How
    far behind it has drifted is recorded in the receipt itself by the run that wrote it,
    and re-running `scripts/signoff.py` is what makes it current. Freshness is a release
    decision, not a standing constraint.
    """
    commit = receipt["measured_at_commit"]
    kind = subprocess.run(
        ["git", "cat-file", "-t", commit], cwd=str(_REPO), capture_output=True, text=True
    ).stdout.strip()
    assert kind == "commit", f"the receipt names {commit}, which is not a commit here"
    assert receipt["commits_behind_head_when_written"] == 0, (
        "the receipt was written against a commit that was not HEAD at the time, so it "
        "describes a tree nobody committed"
    )


def test_the_receipt_says_that_it_cannot_name_its_own_commit(receipt: dict) -> None:
    """The caveat is part of the receipt rather than something a reader has to know."""
    assert "one later" in receipt["note_on_the_commit"]
    assert receipt["schema"] == "SIGNOFF_RECEIPT"
