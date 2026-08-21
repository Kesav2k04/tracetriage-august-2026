"""The watsonx runner records one of three outcomes, and never invents the third.

`pipeline/tracetriage/watsonx.py` was finished code with no caller: no script, no test, no
receipt, and a module docstring claiming a runner and an `.env.example` entry that did not
exist. That is the defect these tests hold closed. A backend nothing calls is not an
integration, and the way this one could quietly become a false claim is narrow and specific:
a receipt whose `backend` field says watsonx over text a local model produced.

So the assertions are about the shape of the honesty rather than about a generation:

*With no credentials the outcome is NOT_CHECKED and the receipt says so.* Not a pass, not a
failure, and not an omission. `scripts/signoff.py` needed the same third column for the same
reason: a check that cannot run here and reports green is the same defect as one that fails
and reports green, one level up.

*NOT_CHECKED carries no generation and no checker verdict.* This is the one that would matter
if it broke. A skip block holding a `generation` key would let a reader believe a hosted model
answered.

*The environment variable names agree in three places.* The module says they live in one
place "because the runner, the tests and `.env.example` all have to agree about them", and
for weeks two of those three did not exist. This is that agreement, asserted.

*`--check` tolerates the outcome changing.* A machine with credentials and a machine without
produce two different true receipts. `--check` has to say which one is committed rather than
calling either wrong, so it is run here and its exit code is required to be 0 against the
committed file.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "WATSONX_RECEIPT.json"
RUNNER = REPO / "scripts" / "run_watsonx_check.py"


@pytest.fixture(scope="module")
def receipt() -> dict:
    if not RECEIPT.exists():
        pytest.fail(
            "artifacts/WATSONX_RECEIPT.json is missing. Run "
            "scripts/run_watsonx_check.py, which needs no credentials."
        )
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_runner_exists_and_the_module_is_no_longer_uncalled():
    assert RUNNER.is_file()
    source = (REPO / "pipeline" / "tracetriage" / "watsonx.py").read_text(
        encoding="utf-8"
    )
    assert "scripts/run_watsonx_check.py" in source, (
        "watsonx.py should name its runner, since the absence of one is what made it dead "
        "code for the whole build"
    )


def test_the_receipt_records_one_of_three_outcomes(receipt):
    assert receipt["attempt"]["outcome"] in {"RAN", "NOT_CHECKED", "FAILED"}
    assert receipt["backend"]["model_id"].startswith("ibm/granite")
    assert receipt["backend"]["module"] == "pipeline/tracetriage/watsonx.py"


def test_the_subject_is_a_real_observation_with_a_packet(receipt):
    """The prompt has to be built from something, and it names what."""
    obs_id = receipt["subject"]["observation_id"]
    queue = json.loads(
        (REPO / "apps" / "web" / "public" / "data" / "queue.json").read_text(
            encoding="utf-8"
        )
    )
    ranked = {int(entry["obs_id"]) for entry in queue["entries"]}
    assert obs_id in ranked, (
        f"{obs_id} is not in the shipped queue, so the receipt describes a prompt about an "
        f"observation this console does not rank"
    )
    assert receipt["subject"]["prompt_characters"] > 0
    assert len(receipt["subject"]["prompt_contract_sha256"]) == 64


def test_a_skip_carries_no_generation_and_no_verdict(receipt):
    """The one way this receipt could become a false claim."""
    attempt = receipt["attempt"]
    if attempt["outcome"] != "NOT_CHECKED":
        pytest.skip(f"this checkout recorded {attempt['outcome']}")
    assert "generation" not in attempt
    assert "checker" not in attempt
    assert attempt["reason"], "a skip has to say why"
    assert attempt["variables_set"] == [], (
        "NOT_CHECKED means no credential was present, so nothing should be listed as set"
    )


def test_a_completed_run_was_judged_by_the_same_checker(receipt):
    attempt = receipt["attempt"]
    if attempt["outcome"] != "RAN":
        pytest.skip(f"this checkout recorded {attempt['outcome']}")
    assert attempt["checker"]["verdict"] in {"GROUNDED", "REFUSED"}
    assert attempt["generation"]["backend"]
    assert "api_key" in attempt["credentials"]
    assert "set," in attempt["credentials"]["api_key"], (
        "a receipt may record that a key was present and its length, never the key"
    )


def test_the_variable_names_agree_in_three_places(receipt):
    """The module, `.env.example` and the receipt, and the runner by symbol not by literal.

    The runner imports `ENV_API_KEY` rather than spelling `WATSONX_API_KEY`, which is the
    stronger version of the same agreement: a rename in the module moves the runner with
    it and cannot leave a stale literal behind. So what is asserted about the runner is the
    import, and what is asserted about the other two is the name.
    """
    from pipeline.tracetriage.watsonx import ENV_API_KEY, ENV_PROJECT_ID, ENV_URL

    example = (REPO / ".env.example").read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for symbol in ("ENV_API_KEY", "ENV_PROJECT_ID", "ENV_URL"):
        assert symbol in runner, (
            f"the runner should import {symbol} from the module rather than repeating its "
            f"value, so a rename cannot leave a stale literal here"
        )
    for name in (ENV_API_KEY, ENV_PROJECT_ID, ENV_URL):
        assert f"{name}=" in example, f"{name} is not in .env.example"

    attempt = receipt["attempt"]
    if attempt["outcome"] == "NOT_CHECKED":
        assert attempt["variables_required"] == [ENV_API_KEY, ENV_PROJECT_ID]
        assert attempt["variable_optional"] == ENV_URL


def test_check_mode_agrees_with_the_committed_receipt():
    """Whatever this machine can do, the committed file has to describe it."""
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert completed.returncode == 0, (
        f"scripts/run_watsonx_check.py --check failed.\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
