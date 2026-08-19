"""The agent loop and the paired study, tested where a demonstration would look identical (E7).

An agent that answers 22 of 24 questions is indistinguishable, from its output alone, from one
that answered them from a model's memory. So the properties tested here are the ones that make
the number mean something: that the control arm was asked the same questions, that the grading
is mechanical, that a question the tools cannot answer is caught before it is blamed on the
policy, that the loop records what it could not parse instead of retrying until something works,
and that the receipt is reproducible from the frozen runs without a model anywhere.

Everything except the two llm-marked tests runs offline with no model and no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from run_agent_study import (  # noqa: E402
    _binomial_tail,
    _leaves,
    build_tasks,
    grade,
    normalise,
    summarise,
    verify_answerable,
)

from pipeline.tracetriage.agent import (  # noqa: E402
    MAX_STEPS,
    EvidenceClient,
    is_grounded,
    numbers_in,
    parse_action,
    run_task,
    tool_menu,
    unwrap,
)

FIXTURE = REPO / "tests" / "fixtures" / "agent_runs.json"
RECEIPT = REPO / "artifacts" / "AGENT_RECEIPT.json"
STUDY = REPO / "scripts" / "run_agent_study.py"


@pytest.fixture(scope="module")
def frozen() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def receipt() -> dict[str, Any]:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


class ScriptedPolicy:
    """A policy that says exactly what a test needs it to say, in order."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "{}"


class FakeClient:
    """The transport, without the subprocess. Counts calls so a repeat can be proved."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.tools = [
            {
                "name": name,
                "description": f"{name} does something.",
                "inputSchema": {"properties": {"x": {}}, "required": []},
            }
            for name in ("queue_top", "observation", "check_claim", "gate_status", "receipt")
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results = results or {}

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        payload = self.results.get(name, {"value": 42})
        return {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def test_an_answer_on_the_first_reply_calls_no_tools():
    policy = ScriptedPolicy(['{"answer": "42"}'])
    run = run_task({"id": "t", "question": "q"}, policy, FakeClient())
    assert run.answer == "42"
    assert run.tools_called == []
    assert run.stopped_because == "answered"


def test_a_reply_with_no_json_is_recorded_and_the_loop_continues():
    """A policy that writes prose is a measurement, not an exception."""
    policy = ScriptedPolicy(["I think it is probably fine", '{"answer": "7"}'])
    run = run_task({"id": "t", "question": "q"}, policy, FakeClient())
    assert run.answer == "7"
    assert [step.error for step in run.steps] == ["no JSON object in the reply", None]
    assert "could not be parsed" in policy.prompts[1]


def test_the_same_call_twice_is_named_and_the_server_is_not_paid_twice():
    """The loop this policy actually falls into, and the reason the receipt counts repeats."""
    client = FakeClient()
    policy = ScriptedPolicy(
        [
            '{"tool": "gate_status", "arguments": {}}',
            '{"tool": "gate_status", "arguments": {}}',
            '{"answer": "2"}',
        ]
    )
    run = run_task({"id": "t", "question": "q"}, policy, client)
    assert run.answer == "2"
    assert len(client.calls) == 1, "the repeated call reached the server"
    assert run.tools_called == ["gate_status", "gate_status"], (
        "a repeat still counts as a call the policy made, or the receipt would understate it"
    )
    assert run.steps[1].error is not None and "repeated call" in run.steps[1].error


def test_a_malformed_tool_call_does_not_crash_the_run():
    policy = ScriptedPolicy(
        ['{"tool": "queue_top"}', '{"tool": 5, "arguments": {}}', '{"answer": "x"}']
    )
    run = run_task({"id": "t", "question": "q"}, policy, FakeClient())
    assert run.answer == "x"
    assert sum(1 for step in run.steps if step.error and "malformed" in step.error) == 2


def test_the_step_cap_stops_the_loop_and_says_so():
    policy = ScriptedPolicy(
        [
            json.dumps({"tool": "queue_top", "arguments": {"limit": i}})
            for i in range(1, MAX_STEPS + 1)
        ]
    )
    run = run_task({"id": "t", "question": "q"}, policy, FakeClient())
    assert run.answer is None
    assert run.stopped_because == "step cap"
    assert len(run.steps) == MAX_STEPS


def test_the_control_arm_gets_one_step_and_no_tools():
    policy = ScriptedPolicy(['{"answer": "unknown"}'])
    run = run_task({"id": "t", "question": "q"}, policy, None)
    assert run.arm == "control"
    assert run.answer == "unknown"
    assert len(run.steps) == 1
    # The control prompt must not describe tools at all: an arm that is told the tools exist
    # and then refused them is a different condition from an arm that never had them.
    assert "queue_top" not in policy.prompts[0]
    assert "{{" not in policy.prompts[0], "the prompt template was not formatted"


def test_the_two_arms_are_asked_the_same_question(frozen):
    """The pairing is the design, so a control arm asked something else is the whole study."""
    by_arm: dict[str, dict[str, str]] = {"tools": {}, "control": {}}
    for run in frozen["runs"]:
        by_arm[run["arm"]][run["task_id"]] = run["question"]
    assert set(by_arm["tools"]) == set(by_arm["control"])
    for task_id, question in by_arm["tools"].items():
        assert by_arm["control"][task_id] == question


# ---------------------------------------------------------------------------
# The parts a grade depends on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"answer": "7"}', {"answer": "7"}),
        ('Sure! {"answer": "7"} hope that helps', {"answer": "7"}),
        ('```json\n{"answer": "7"}\n```', {"answer": "7"}),
        ('{"answer": "7"} {"answer": "8"}', {"answer": "7"}),
        ("{not json}", None),
        ("no object at all", None),
        ("[1, 2, 3]", None),
    ],
)
def test_parse_action_reads_the_first_object_or_nothing(raw, expected):
    assert parse_action(raw) == expected


def test_numbers_are_compared_as_claims_rather_than_as_strings():
    assert numbers_in("0.50 and 0.5") == ["0.5", "0.5"]
    assert numbers_in("offset 6904 Hz") == ["6904"]
    assert numbers_in("none here") == []


def test_grounding_names_the_numbers_that_were_not_read():
    results = [{"fitted_offset_hz": "6904"}]
    ok, missing = is_grounded("The offset is 6904 Hz.", results)
    assert ok and missing == []
    ok, missing = is_grounded("The offset is 6905 Hz.", results)
    assert not ok and missing == ["6905"]


def test_unwrap_reads_the_protocols_own_error_shape():
    ok_result = {"content": [{"type": "text", "text": '{"a": 1}'}], "isError": False}
    assert unwrap(ok_result) == (False, {"a": 1})
    refused = {"content": [{"type": "text", "text": '{"reason": "BAD_ARGUMENTS"}'}],
               "isError": True}
    assert unwrap(refused) == (True, {"reason": "BAD_ARGUMENTS"})
    assert unwrap({"__error__": {"code": -32600}}) == (True, {"code": -32600})


def test_normalise_accepts_a_full_stop_and_a_case_but_not_a_different_number():
    assert normalise("REFUSED.") == normalise("refused")
    assert normalise("0.880") == normalise("0.88")
    assert normalise("0.88") != normalise("0.879634")
    assert normalise(None) == ""


def test_the_menu_is_ordered_so_two_runs_get_the_same_prompt():
    client = FakeClient()
    first = tool_menu(client.tools)
    client.tools.reverse()
    assert tool_menu(client.tools) == first


def test_the_binomial_tail_is_the_number_the_paired_test_needs():
    assert _binomial_tail(0, 10) == pytest.approx(1.0)
    assert _binomial_tail(10, 10) == pytest.approx(0.5**10)
    assert _binomial_tail(20, 20) == pytest.approx(0.5**20)
    assert _binomial_tail(1, 1) == pytest.approx(0.5)
    # Symmetry: P(X >= k) + P(X <= k-1) = 1, and P(X <= k-1) = P(X >= n-k+1) at p = 0.5.
    assert _binomial_tail(6, 10) + _binomial_tail(5, 10) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The study's own preconditions
# ---------------------------------------------------------------------------


def test_every_question_can_be_answered_from_one_tool_call():
    """The check that stops a question the tools cannot serve being blamed on the policy.

    One was: the receipt tool publishes top-level scalars and collection sizes, so "how many
    drafts did the checker refuse" had no answer in any tool output, and the model's wrong reply
    would have counted against the loop rather than against the question set.
    """
    tasks = build_tasks()
    with EvidenceClient() as client:
        proofs = verify_answerable(tasks, client)
    assert len(proofs) == len(tasks)
    assert all(proof["expected_is_a_value_in_the_result"] for proof in proofs)


def test_a_question_the_tools_cannot_answer_is_refused():
    """The same check, mutated, so a pass above is not a pass over an empty condition."""
    tasks = build_tasks()
    impossible = dict(tasks[0])
    impossible["expected"] = "a value no tool will ever return"
    with EvidenceClient() as client, pytest.raises(SystemExit) as caught:
        verify_answerable([impossible], client)
    assert "no policy could answer it" in str(caught.value)


def test_the_ground_truth_is_the_data_the_console_ships(frozen):
    """The task set is rebuilt here and has to agree with what the fixture was graded against."""
    tasks = {task["id"]: task for task in build_tasks()}
    frozen_tasks = {task["id"]: task for task in frozen["tasks"]}
    assert set(tasks) == set(frozen_tasks)
    for task_id, task in tasks.items():
        assert task["expected"] == frozen_tasks[task_id]["expected"], task_id


def test_the_leaf_walk_does_not_match_a_substring():
    """A count of 14 must not be found inside an observation id, or an unanswerable question
    would pass the answerability check."""
    payload = {"obs_id": 14746092, "rows": [{"n": 3}]}
    values = {normalise(leaf) for leaf in _leaves(payload)}
    assert "3" in values
    assert "14" not in values


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------


def test_the_committed_receipt_is_what_the_frozen_runs_produce():
    """No model, no network: the receipt has to be reproducible from what is committed."""
    finished = subprocess.run(
        [sys.executable, str(STUDY), "--out", str(REPO / "artifacts" / "_agent_check.json")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    written = REPO / "artifacts" / "_agent_check.json"
    try:
        assert finished.returncode == 0, finished.stdout + finished.stderr
        assert json.loads(written.read_text(encoding="utf-8")) == json.loads(
            RECEIPT.read_text(encoding="utf-8")
        ), "the committed receipt is not what the committed fixture grades to"
    finally:
        written.unlink(missing_ok=True)


def test_the_receipt_names_the_fixture_it_was_published_from(receipt):
    import hashlib

    assert receipt["frozen_runs_sha256"] == hashlib.sha256(FIXTURE.read_bytes()).hexdigest()


def test_the_paired_counts_partition_the_tasks(receipt):
    paired = receipt["paired"]
    total = (
        paired["both_correct"]
        + paired["neither_correct"]
        + len(paired["tools_only"])
        + len(paired["control_only"])
    )
    assert total == paired["tasks"] == receipt["tasks"]
    assert paired["discordant_pairs"] == len(paired["tools_only"]) + len(paired["control_only"])


def test_the_arm_rates_are_what_the_per_run_rows_say(receipt):
    """The summary has to be recomputable from the rows, or it is a second source of truth."""
    for arm in ("tools", "control"):
        rows = [row for row in receipt["per_run"] if row["arm"] == arm]
        assert receipt["arms"][arm]["correct"]["trials"] == len(rows)
        assert receipt["arms"][arm]["correct"]["successes"] == sum(
            1 for row in rows if row["correct"]
        )
        assert receipt["arms"][arm]["grounded"]["successes"] == sum(
            1 for row in rows if row["grounded"]
        )


def test_a_control_answer_with_an_invented_number_is_not_grounded(receipt):
    """The measurement that separates declining from guessing.

    The control declined most questions and guessed a few. A guess that happens to be right is
    still a guess, and this is where the receipt says so, so the control's success count cannot
    be read as evidence the model knew.
    """
    control = [row for row in receipt["per_run"] if row["arm"] == "control"]
    ungrounded = [row for row in control if not row["grounded"]]
    assert ungrounded, "no control answer invented a number, which would be a surprising study"
    for row in ungrounded:
        assert row["ungrounded_numbers"], row["task_id"]


def test_the_wrong_answers_are_split_by_whether_it_ever_fetched_the_value(receipt):
    """Two failures, two shapes, and the receipt has to keep them apart."""
    tools = receipt["arms"]["tools"]
    wrong = [row for row in receipt["per_run"] if row["arm"] == "tools" and not row["correct"]]
    assert sorted(row["task_id"] for row in wrong) == sorted(
        tools["wrong_with_the_answer_in_front_of_it"] + tools["wrong_and_never_fetched_it"]
    )
    for task_id in tools["wrong_with_the_answer_in_front_of_it"]:
        row = next(r for r in wrong if r["task_id"] == task_id)
        assert row["answer_was_in_what_it_read"] is True
    for task_id in tools["wrong_and_never_fetched_it"]:
        row = next(r for r in wrong if r["task_id"] == task_id)
        assert row["answer_was_in_what_it_read"] is False


def test_the_receipt_states_what_the_study_does_not_measure(receipt):
    text = " ".join(receipt["what_this_does_not_measure"]).lower()
    assert "useful" in text
    assert "one model" in text or "different model" in text


def test_the_summary_recomputes_from_the_frozen_runs(frozen, receipt):
    """Grade the fixture again here, rather than trusting the published summary."""
    tasks = {task["id"]: task for task in frozen["tasks"]}
    graded = [grade(run, tasks[run["task_id"]]) for run in frozen["runs"]]
    again = summarise(graded, frozen["tasks"])
    assert again["arms"]["tools"]["correct"] == receipt["arms"]["tools"]["correct"]
    assert again["paired"]["exact_p_one_sided"] == receipt["paired"]["exact_p_one_sided"]


# ---------------------------------------------------------------------------
# The transport, against the real server, with no model
# ---------------------------------------------------------------------------


def test_the_client_speaks_to_the_real_server():
    from mcp_server import TOOLS

    with EvidenceClient() as client:
        assert sorted(tool["name"] for tool in client.tools) == sorted(TOOLS)
        refused, payload = unwrap(client.call_tool("gate_status", {}))
        assert not refused
        assert payload["n_gates"] >= 6
        refused, payload = unwrap(client.call_tool("observation", {"observation_id": "x"}))
        assert refused and payload["reason"] == "BAD_ARGUMENTS"


# ---------------------------------------------------------------------------
# The live path, skipped without a runtime
# ---------------------------------------------------------------------------


# Both markers, on purpose. conftest blocks sockets for any test without the network marker,
# so an llm-marked test that lacks it can only ever skip, even with a model running on
# loopback: the guard fires before the runtime is reached. The offline gate excludes network,
# ocr and llm, so marking this pair does not put it back into that run.
@pytest.mark.llm
@pytest.mark.network
def test_one_question_end_to_end_against_the_local_model():
    from pipeline.tracetriage.granite import generate

    tasks = {task["id"]: task for task in build_tasks()}
    task = tasks["gate-6-verdict"]
    with EvidenceClient() as client:
        run = run_task(task, lambda prompt: generate(prompt, max_tokens=200), client)
    assert run.tools_called, "the policy answered without calling anything"
    assert run.answer is not None
