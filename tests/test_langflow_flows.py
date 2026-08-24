"""The committed LangFlow flows are files LangFlow wrote, and the receipt describes them.

Everything here runs offline and none of it imports LangFlow, which is deliberate twice
over. LangFlow is not a dependency of this project: it resolves several hundred packages and
pins against versions the measurement path is fixed to, so a clean clone must be able to run
the whole suite without it. And a structural check of the committed artifact is a different
question from whether the runner works. The runner proves itself by running, and its receipt
is what these tests read.

What is checked, and why each one is here rather than assumed:

*The receipt's digest is the file's digest.* A flow JSON and a receipt describing it are two
files that can disagree, and the one a reader opens is the JSON. If they drift, every claim
made about what the flow returned is a claim about a file nobody has.

*The grounding flow's two runs came back with opposite verdicts.* A checker that refuses
everything scores perfectly on the adversarial arm alone, so the pair is the measurement. If
both runs ever read REFUSED, the receipt is describing a broken checker and not a working
one.

*Every custom node's stored source names exactly one Component subclass.* This is the defect
that cost an hour: LangFlow stores a component's source in the flow and resolves *the*
Component subclass it finds on load, so a module holding three of them binds the wrong one.
The failure was `AttributeError: Attribute build_tools not found in
TraceTriageGroundingCheck`, which names the attribute and not the cause, and it only appeared
in the second flow. Counting class definitions in the stored source catches it in the first.

*No stored source calls anything at module scope.* An earlier version defined the components
inside the build script, so the stored source was the whole script including the line that
ran the flow: loading the flow re-ran the builder, which re-loaded the flow, some hundreds
deep. A module that only defines things can be executed any number of times.

*The agent flow's claim matches what it returned.* The receipt may say the graph ran and must
not thereby imply the model used the tools. The rank-1 observation id is in no prompt, so its
presence in the answer is a fact; the boolean recording that is checked against the answer
text rather than trusted.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "LANGFLOW_RECEIPT.json"
FLOWS = REPO / "flows"

#: The three components this project defines, by class name.
OURS = {
    "TraceTriageGroundingCheck",
    "TraceTriageQueueTop",
    "TraceTriageEvidenceTools",
}


@pytest.fixture(scope="module")
def receipt() -> dict:
    if not RECEIPT.exists():
        pytest.fail(
            "artifacts/LANGFLOW_RECEIPT.json is missing. Run "
            "scripts/run_langflow_check.py, which needs .venv-langflow."
        )
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_receipt_names_both_flows(receipt):
    assert set(receipt["flows"]) == {"grounding", "granite_agent"}, (
        "the receipt should describe exactly the two flows the runner builds"
    )


def test_langflow_is_not_a_dependency_of_this_project(receipt):
    """The claim, and the thing that would make it false.

    Read from the dependency tables rather than as a substring of the file. The first
    version searched the whole of `pyproject.toml` for the word, which fired the moment the
    wheel target grew an `exclude` keeping the LangFlow components out of the wheel: a
    comment explaining why LangFlow is not shipped read to that check exactly like a
    declaration that it is required.
    """
    assert receipt["runtime"]["is_a_dependency_of_this_project"] is False

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    requirements.extend(data.get("build-system", {}).get("requires", []))
    for group in data.get("dependency-groups", {}).values():
        requirements.extend(r for r in group if isinstance(r, str))

    assert requirements, "no requirements were read, so this check measured nothing"
    offenders = [r for r in requirements if "langflow" in r.lower()]
    assert offenders == [], (
        f"langflow is declared as a requirement: {offenders}. It resolves several hundred "
        "packages and pins against versions the measurement path is fixed to, and the "
        "receipt claims it is not a dependency."
    )


def test_every_flow_file_matches_the_digest_the_receipt_recorded(receipt):
    checked = 0
    for name, entry in receipt["flows"].items():
        if not entry.get("file"):
            continue
        path = REPO / entry["file"]
        assert path.is_file(), f"{name} names {entry['file']}, which is not in the tree"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == entry["sha256"], (
            f"{entry['file']} hashes to {digest[:12]} and the receipt recorded "
            f"{entry['sha256'][:12]}. Re-run scripts/run_langflow_check.py."
        )
        assert path.stat().st_size == entry["bytes"]
        checked += 1
    assert checked == 2, f"only {checked} flow files were compared, expected 2"


def test_every_flow_file_is_a_langflow_graph(receipt):
    for entry in receipt["flows"].values():
        if not entry.get("file"):
            continue
        payload = json.loads((REPO / entry["file"]).read_text(encoding="utf-8"))
        assert set(payload) >= {"data", "name", "description"}
        nodes = payload["data"]["nodes"]
        assert [node["id"] for node in nodes] == entry["nodes"], (
            "the receipt's node list should be the flow's own, in order"
        )
        assert len(payload["data"]["edges"]) == entry["n_edges"]


def _stored_sources(path: Path) -> dict[str, str]:
    """Each node's stored component source, by node id, for our own components only."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for node in payload["data"]["nodes"]:
        template = ((node.get("data") or {}).get("node") or {}).get("template") or {}
        code = (template.get("code") or {}).get("value")
        if not isinstance(code, str):
            continue
        if any(name in code for name in OURS):
            out[node["id"]] = code
    return out


def test_each_stored_source_defines_exactly_one_component(receipt):
    """The defect: three classes in one module bound the wrong one on load."""
    seen = 0
    for entry in receipt["flows"].values():
        if not entry.get("file"):
            continue
        for node_id, code in _stored_sources(REPO / entry["file"]).items():
            classes = re.findall(r"^class\s+(\w+)\(Component\)", code, flags=re.M)
            assert len(classes) == 1, (
                f"{node_id} stores a source defining {classes}. LangFlow resolves *the* "
                f"Component subclass it finds, so more than one binds whichever comes "
                f"first: that is how an agent flow asking for the tools node got the "
                f"grounding node and failed with 'Attribute build_tools not found in "
                f"TraceTriageGroundingCheck'."
            )
            assert classes[0] in OURS
            seen += 1
    assert seen >= 2, f"only {seen} of this project's nodes were found across both flows"


def test_no_stored_source_runs_anything_at_import(receipt):
    """A stored source is executed on load, so a call at module scope is a loop."""
    for entry in receipt["flows"].values():
        if not entry.get("file"):
            continue
        for node_id, code in _stored_sources(REPO / entry["file"]).items():
            assert "__main__" not in code, (
                f"{node_id}'s stored source has an __main__ block. LangFlow executes this "
                f"source every time the flow loads."
            )
            for line in code.splitlines():
                if not line or line[0] in " \t#":
                    continue
                assert not re.match(r"^\w[\w.]*\(", line), (
                    f"{node_id}'s stored source calls {line.strip()[:40]!r} at module "
                    f"scope, and that source runs on every load."
                )


def test_the_grounding_flow_returned_opposite_verdicts(receipt):
    grounding = receipt["flows"]["grounding"]
    assert grounding["outcome"] == "RAN", (
        "the grounding flow needs no model and no network, so any other outcome is a "
        "defect rather than an environment"
    )
    verdicts = {run["label"]: run for run in grounding["runs"]}
    assert set(verdicts) == {"grounded", "ungrounded"}
    assert verdicts["grounded"]["verdict"] == "GROUNDED"
    assert verdicts["grounded"]["codes"] == []
    assert verdicts["ungrounded"]["verdict"] == "REFUSED"
    assert "UNGROUNDED_NUMBER" in verdicts["ungrounded"]["codes"]
    assert (
        verdicts["grounded"]["observation_id"]
        == verdicts["ungrounded"]["observation_id"]
    ), "both runs should be about the same observation, or the pair is not a comparison"


def test_the_agent_flow_records_one_of_three_outcomes(receipt):
    agent = receipt["flows"]["granite_agent"]
    assert agent["outcome"] in {"RAN", "NOT_CHECKED", "FAILED"}
    if agent["outcome"] == "NOT_CHECKED":
        assert agent.get("reason"), "a skip has to say why, or it is a silent pass"
    if agent["outcome"] == "FAILED":
        assert agent.get("error_class")


def test_the_agent_flows_tool_use_claim_is_checked_against_its_answer(receipt):
    """"The graph ran" and "the model used the tools" are different claims."""
    agent = receipt["flows"]["granite_agent"]
    if agent["outcome"] != "RAN":
        pytest.skip(f"the agent flow did not run here: {agent['outcome']}")
    expected = agent["expected_observation_id"]
    carried = agent["answer_carries_the_tool_only_fact"]
    assert carried == (expected in agent["answer"]), (
        "the boolean should be what the answer text says, not a separate opinion about it"
    )


def test_the_flows_directory_holds_nothing_that_did_not_come_from_a_run(receipt):
    """A flow file with no receipt entry is the screenshot this integration refuses."""
    on_disk = {path.name for path in FLOWS.glob("*.json")}
    described = {
        Path(entry["file"]).name
        for entry in receipt["flows"].values()
        if entry.get("file")
    }
    assert on_disk == described, (
        f"flows/ holds {sorted(on_disk - described)} that the receipt does not describe. A "
        f"flow file this project has never run is exactly what docs/USE_WITH_YOUR_AGENT.md "
        f"declines to ship."
    )


def _checker():
    """Import the runner's comparison helper without importing LangFlow.

    `run_langflow_check.py` shells out to a separate interpreter for every LangFlow call, so
    the module itself imports under the project venv. That is what lets the exemption below
    be tested from the offline suite, which is where a rule about when a gate may go quiet
    belongs.
    """
    path = REPO / "scripts" / "run_langflow_check.py"
    spec = importlib.util.spec_from_file_location("run_langflow_check_for_tests", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._model_runtime_absent


def _pair() -> tuple[dict, dict]:
    """A committed receipt that reached a model, and the rebuild a machine without one gets.

    Shaped from the real receipt rather than invented: the keys that vanish when the runtime
    is unreachable are the four the runner names, and everything else survives because it is
    built from Python objects.
    """
    committed = {
        "schema": "LANGFLOW_RECEIPT",
        "runtime": {"langflow": "1.7.2"},
        "flows": {
            "grounding": {
                "file": "flows/tracetriage_grounding.json",
                "sha256": "a" * 64,
                "outcome": "RAN",
                "runs": [{"label": "clean", "verdict": "PASSED"}],
            },
            "granite_agent": {
                "file": "flows/tracetriage_granite_agent.json",
                "sha256": "b" * 64,
                "nodes": ["ChatInput-1", "AgentComponent-1"],
                "n_edges": 4,
                "model": "granite3.1-dense:8b",
                "endpoint": "http://127.0.0.1:11434",
                "outcome": "RAN",
                "question": "Which observation is at rank 1?",
                "n_outputs": 1,
                "expected_observation_id": "14746092",
            },
        },
    }
    fresh = json.loads(json.dumps(committed))
    agent = fresh["flows"]["granite_agent"]
    agent["outcome"] = "NOT_CHECKED"
    for key in ("question", "n_outputs", "expected_observation_id"):
        del agent[key]
    return committed, fresh


def test_a_missing_model_runtime_is_not_reported_as_a_disagreement():
    """The case the exemption exists for, so its absence would be caught here first."""
    committed, fresh = _pair()
    assert _checker()(committed, fresh), (
        "a clean clone with no Ollama rebuilds granite_agent as NOT_CHECKED, and calling "
        "that a FAIL manufactures a regression out of a precondition the runner declares "
        "optional"
    )


@pytest.mark.parametrize(
    "mutate,why",
    [
        (
            lambda fresh: fresh["flows"]["granite_agent"].__setitem__("outcome", "FAILED"),
            "a model that answered wrongly or threw is measured and wrong",
        ),
        (
            lambda fresh: fresh["flows"]["granite_agent"].__setitem__("sha256", "c" * 64),
            "the flow file moved, which needs no runtime to notice",
        ),
        (
            lambda fresh: fresh["flows"]["granite_agent"].__setitem__("nodes", ["ChatInput-1"]),
            "the node set is built from Python objects and does not depend on the model",
        ),
        (
            lambda fresh: fresh["flows"]["granite_agent"].__setitem__("n_edges", 3),
            "the wiring changed",
        ),
        (
            lambda fresh: fresh["flows"]["granite_agent"].__setitem__("model", "llama3:8b"),
            "the flow is pointed at a different model than the receipt records",
        ),
        (
            lambda fresh: fresh["flows"]["grounding"]["runs"][0].__setitem__(
                "verdict", "REFUSED"
            ),
            "the grounding flow needs no runtime, so any move in it is real",
        ),
        (
            lambda fresh: fresh["flows"].__delitem__("grounding"),
            "a flow stopped being described at all",
        ),
        (
            lambda fresh: fresh["runtime"].__setitem__("langflow", "1.0.0"),
            "the LangFlow version the receipt was written under changed",
        ),
    ],
)
def test_the_exemption_covers_nothing_but_the_absent_runtime(mutate, why):
    """Eight ways the rebuild can be genuinely wrong, none of which may go quiet.

    An exemption is only as good as what it refuses. This is the half that keeps
    `[NOT CHECKED]` from becoming a second name for green.
    """
    committed, fresh = _pair()
    mutate(fresh)
    assert not _checker()(committed, fresh), f"should stay a FAIL: {why}"


def test_a_receipt_that_never_ran_cannot_claim_the_exemption():
    """NOT_CHECKED on both sides is equality, and equality is the PASS branch, not this one.

    Written because the shape that would hide a real regression is a receipt committed while
    the runtime happened to be down: if that were exempt too, the gate could never go red on
    this row again.
    """
    committed, fresh = _pair()
    committed["flows"]["granite_agent"]["outcome"] = "NOT_CHECKED"
    assert not _checker()(committed, fresh)
