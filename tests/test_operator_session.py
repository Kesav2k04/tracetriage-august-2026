"""The recorded twelve-step session, and the document it is supposed to be a run of.

`docs/BOB_DEMO.md` prints twelve numbered steps and `scripts/run_operator_session.py`
runs them. Two files that describe one sequence drift, and the way they drift is the
cheap way: someone edits the prompt, the script keeps running the old steps, and the
receipt still says twelve of twelve.

So the test is the cross-check. Every step number in the document appears in the
receipt, the receipt claims no more steps than the document has, and each half is
attributed to the server that answered it. Plus the two readings that carry weight:
the frozen refusal came back REFUSED with `UNGROUNDED_NUMBER`, and the control came
back GROUNDED, because a checker that refuses everything would satisfy the first on
its own.

The offline half is re-run here rather than trusted. The live half is not: it downloads
a waterfall from a volunteer network, and a test suite that spends somebody else's
bandwidth on every run is a test suite that gets switched off.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "OPERATOR_SESSION.json"
DEMO = REPO / "docs" / "BOB_DEMO.md"


@pytest.fixture(scope="module")
def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def documented_steps() -> set[int]:
    """The step numbers in the fenced prompt block, read from the document."""
    text = DEMO.read_text(encoding="utf-8")
    block = text.split("## The prompt", 1)[1].split("```")[1]
    numbers = {int(m) for m in re.findall(r"^\s*(\d+)\.", block, re.M)}
    assert numbers, "no numbered steps found in the prompt block"
    return numbers


def _steps(receipt: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for half in ("frozen", "live"):
        for step in receipt[half].get("steps", []):
            out[step["step"]] = step
    return out


def test_the_document_and_the_receipt_describe_the_same_twelve_steps(
    receipt, documented_steps
):
    assert documented_steps == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}
    recorded = set(_steps(receipt))
    missing = sorted(documented_steps - recorded)
    invented = sorted(recorded - documented_steps)
    assert not missing, f"the document asks for steps {missing} and the receipt has none"
    assert not invented, f"the receipt records steps {invented} the document never asks for"


def test_every_recorded_step_met_its_own_expectation(receipt):
    unmet = [s["step"] for s in _steps(receipt).values() if not s["met"]]
    assert not unmet, f"steps {unmet} did not come back as the document says they will"
    assert receipt["summary"]["steps_unmet"] == []


def test_the_receipt_does_not_claim_to_be_a_bob_session(receipt):
    """The one thing this run cannot establish, said in a field rather than a footnote."""
    assert "Not IBM Bob" in receipt["operator"]
    assert "the choice" in receipt["what_a_bob_session_adds"]


def test_the_frozen_refusal_and_its_control_are_both_recorded(receipt):
    steps = _steps(receipt)
    refusal = steps[5]["reported"]
    assert refusal["verdict"] == "REFUSED"
    assert "UNGROUNDED_NUMBER" in refusal["codes"]
    control = steps[6]["reported"]
    assert control["verdict"] == "GROUNDED", (
        "a checker that refuses everything satisfies step 5 and is useless. Step 6 is "
        "the control and it has to pass."
    )
    assert control["codes"] == []


def test_the_gate_tally_is_read_and_not_asserted_to_a_literal(receipt):
    reported = _steps(receipt)[8]["reported"]
    assert reported["n_met"] < reported["n_gates"]
    assert reported["gate_4"] != "MET"
    assert reported["gate_6"] != "MET"
    # The count and the list have to agree, which is what caught this document saying
    # two gates were unmet when four are.
    assert reported["n_met"] == reported["n_gates"] - len(reported["unmet"])


def test_the_live_half_measured_a_pass_and_kept_its_provenance(receipt):
    live = receipt["live"]
    if not live.get("attempted") or not live.get("steps"):
        pytest.skip("the committed receipt was written with --offline")
    steps = _steps(receipt)
    measured = steps[10]["reported"]
    assert measured["waterfall_sha256"], "a measurement with no image digest is not one"
    assert measured["measured_at_utc"]
    # UNRESOLVED is a result and the reason is the payload. What is not acceptable is a
    # verdict with nothing behind it.
    if measured["mode_verdict"] == "UNRESOLVED":
        assert measured["mode_why"]
        assert measured["nulls_not_tested"]
    else:
        assert measured["offset_ppm"] is not None
    assert steps[11]["reported"]["verdict"] == "REFUSED"


def test_the_offline_half_still_runs(tmp_path):
    """Re-run the nine steps that read committed receipts, and check the exit code.

    Writes over the committed receipt, so it is restored afterwards: the live half is
    in the committed one and this run cannot reproduce it.
    """
    before = RECEIPT.read_bytes()
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "run_operator_session.py"), "--offline"],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        rerun = json.loads(RECEIPT.read_text(encoding="utf-8"))
        assert rerun["live"]["attempted"] is False
        assert rerun["summary"]["steps_unmet"] == []
    finally:
        RECEIPT.write_bytes(before)
