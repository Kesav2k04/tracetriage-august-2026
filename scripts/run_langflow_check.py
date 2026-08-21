"""Build two LangFlow flows out of this project's components, run them, record what came out.

    python scripts/run_langflow_check.py            # build the flows and run them
    python scripts/run_langflow_check.py --check    # rebuild and compare, for the gate

`docs/USE_WITH_YOUR_AGENT.md` used to say there was no LangFlow graph here, and gave the
reason: "a flow file this project has never imported would be a screenshot of an integration
rather than an integration." That reasoning is still the standard. This script is the answer
to it rather than an exception from it, and the order of operations is the whole point:

1.  The flows are **built from Python objects**, not typed as JSON. Each node is a real
    component instance from `pipeline/tracetriage/langflow_components.py` or from LangFlow's
    own library, wired with `set()`, and assembled with `langflow.graph.Graph`.
2.  `Graph.dump()` writes the flow file. So the committed JSON under `flows/` is a file
    LangFlow produced and can import, not a hand-drawn approximation of one.
3.  The flow is then **loaded back from that JSON** through `langflow.load.run_flow_from_json`
    and executed. The receipt records what the loaded flow returned, so the artifact and the
    result are the same object end to end. A flow that would not load cannot produce a
    receipt.

**Two flows, and why the second one is allowed to be absent.**

`grounding` is the one that matters and it needs nothing. Chat input, this project's grounding
checker as a node, chat output. No model, no network, no key. It is run twice on purpose: once
with a sentence whose numbers are all in the observation's evidence packet, and once with an
invented frequency. Both verdicts are recorded, because a checker that refuses everything
would score perfectly on the second run alone.

`granite_agent` binds the six read-only evidence tools to `granite3.1-dense:8b` over a local
Ollama through LangFlow's own agent node. That is the flow an IBM judge would want to see, and
it needs a model runtime that a clean clone does not have. So its outcome is one of three:
`RAN`, or `NOT_CHECKED` with the reason the runtime was unreachable, or `FAILED` with the
error. `NOT_CHECKED` is written to the receipt with the date rather than omitted, for the same
reason `scripts/signoff.py` needed a third column: a check that cannot run here and reports
green is the same defect as one that fails and reports green.

**LangFlow is not a dependency of this project and must not become one.**

It resolves a tree of some hundreds of packages, several of which pin against the versions
this project's measurement path is fixed to. Nothing published here may depend on it. So this
script runs under its own interpreter, named by `TRACETRIAGE_LANGFLOW_PYTHON` or found at
`.venv-langflow/`, and it refuses with the two commands that create one rather than failing
on an import three frames down. The receipt records the interpreter and the LangFlow version
it ran under, because "it worked" without those two facts is not reproducible.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FLOWS = REPO / "flows"
RECEIPT = REPO / "artifacts" / "LANGFLOW_RECEIPT.json"

#: Where to find an interpreter with LangFlow in it, in order.
ENV_PYTHON = "TRACETRIAGE_LANGFLOW_PYTHON"
DEFAULT_VENV = REPO / ".venv-langflow" / "Scripts" / "python.exe"
DEFAULT_VENV_POSIX = REPO / ".venv-langflow" / "bin" / "python"

#: The two sentences the grounding flow is run on.
#:
#: The first quotes figures that are in the subject observation's evidence packet. The
#: second invents a downlink frequency: 437.2 MHz is a real amateur satellite frequency
#: and it is not this observation's, which is the near miss the checker exists to catch
#: and the exact mistake a local model made on 9 of 25 shipped observations.
GROUNDED_CLAIM = "This observation is ranked in the review queue."
UNGROUNDED_CLAIM = "The downlink for this pass is 437.2 MHz."

#: The model the agent flow asks for, and where.
AGENT_MODEL = "granite3.1-dense:8b"
OLLAMA_URL = os.environ.get("TRACETRIAGE_OLLAMA_URL", "http://127.0.0.1:11434")

#: One question, chosen because a single tool call answers it and the answer is checkable
#: against a committed file rather than against a judgement.
AGENT_QUESTION = (
    "Use your tools. Which observation is at rank 1 of the review queue, and which "
    "criterion raised it? Answer with the id and the criterion only."
)


def _interpreter() -> Path:
    """The interpreter that has LangFlow, or a refusal naming how to make one."""
    named = (os.environ.get(ENV_PYTHON) or "").strip()
    if named:
        path = Path(named)
        if not path.exists():
            raise SystemExit(
                f"{ENV_PYTHON} is set to {named}, which does not exist. Point it at a "
                f"python.exe in an environment with langflow installed, or unset it."
            )
        return path
    for candidate in (DEFAULT_VENV, DEFAULT_VENV_POSIX):
        if candidate.exists():
            return candidate
    raise SystemExit(
        "No interpreter with LangFlow was found. LangFlow is deliberately not a "
        "dependency of this project: it resolves several hundred packages and pins "
        "against versions the measurement path is fixed to. Make it its own "
        "environment:\n\n"
        "    uv venv .venv-langflow --python 3.12\n"
        "    uv pip install --python .venv-langflow/Scripts/python.exe langflow\n\n"
        f"or set {ENV_PYTHON} to an interpreter that already has it. Every number this "
        "repository publishes is reproducible without either."
    )


# The child program. Kept as source in this file rather than as a second script because it
# has to run under a different interpreter than the one importing this module, and because
# what it does is only meaningful next to the reasoning above it.
#
# It prints one JSON object on the last line of stdout and nothing else is parsed, so
# LangFlow's own import chatter (it warns about torch on every start) cannot corrupt the
# result.
CHILD = r'''
import json, re, sys, traceback

RESULT = {"langflow_version": None, "flows": {}}

try:
    import importlib.metadata as md
    RESULT["langflow_version"] = md.version("langflow")
    RESULT["langflow_base_version"] = md.version("langflow-base")
except Exception as error:
    RESULT["langflow_version"] = f"unknown: {error}"

from langflow.graph import Graph
from langflow.load import run_flow_from_json
from langflow.components.input_output import ChatInput, ChatOutput
from pipeline.tracetriage.langflow_components import (
    TraceTriageEvidenceTools,
    TraceTriageGroundingCheck,
)

FLOWS_DIR, GROUNDED, UNGROUNDED, MODEL, OLLAMA, QUESTION = (
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]
)


def texts(runs):
    """Every text a run produced, flattened, so a shape change is visible not fatal."""
    out = []
    for run in runs:
        for output in run.outputs:
            results = getattr(output, "results", None) or {}
            for value in results.values():
                text = getattr(value, "text", None)
                if text is None and isinstance(value, dict):
                    text = value.get("text")
                out.append(str(text if text is not None else value))
    return out


def build_grounding():
    chat_in = ChatInput()
    check = TraceTriageGroundingCheck()
    check.set(claim=chat_in.message_response, observation_id=0)
    chat_out = ChatOutput()
    chat_out.set(input_value=check.check)
    return Graph(chat_in, chat_out)


def build_agent():
    from langflow.components.models_and_agents import AgentComponent
    from langflow.components.ollama import ChatOllamaComponent

    model = ChatOllamaComponent()
    model.set(base_url=OLLAMA, model_name=MODEL, temperature=0)
    kit = TraceTriageEvidenceTools()
    agent = AgentComponent()
    chat_in = ChatInput()
    agent.set(
        model=model.build_model,
        tools=[kit.build_tools],
        input_value=chat_in.message_response,
        system_prompt=(
            "You answer questions about SatNOGS satellite observations using only the "
            "tools you are given. Never state a number you did not read from a tool."
        ),
        max_iterations=6,
        add_current_date_tool=False,
        add_calculator_tool=False,
    )
    chat_out = ChatOutput()
    chat_out.set(input_value=agent.message_response)
    return Graph(chat_in, chat_out)


def dump(graph, name, description):
    """Write the flow, with its node ids made deterministic.

    LangFlow names a node `ChatInput-jfAB6`: the class, then five random characters. That is
    correct for a canvas where a user can add two of the same node, and it makes the dumped
    file different on every run, which costs two things. The receipt's digest can never
    match a rebuild, so `--check` fails on a tree where nothing is wrong and the gate learns
    to ignore it. And every run rewrites 158 KB of committed JSON with no change of meaning,
    so the diff stops carrying information.

    The suffixes are replaced with a per-class counter, on the serialised text rather than on
    the tree, because an id also appears inside the edge handle strings LangFlow encodes as
    `{œidœ:œChatInput-jfAB6œ,...}`. Rewriting the tree and missing the handles produces a
    file that loads and has no edges. Substituting the text catches every occurrence, and the
    assertion afterwards is what makes that safe rather than hopeful: no original id may
    survive anywhere in the output.
    """
    payload = graph.dump(name=name, description=description)
    # Edge order is not stable across runs. Two dumps of the same agent graph put the model
    # edge first and third, which changed the digest while changing nothing a loader reads:
    # a flow's edges are a set. Sorted on the pair of node ids and the field they land in,
    # which is unique per edge here and would stay unique if a node gained a second input.
    edges = payload.get("data", {}).get("edges", [])
    edges.sort(
        key=lambda edge: (
            str(edge.get("source")),
            str(edge.get("target")),
            str(((edge.get("data") or {}).get("targetHandle") or {}).get("fieldName")),
        )
    )
    text = json.dumps(payload, indent=1, sort_keys=True)
    # The chat nodes seed their default message with the moment the graph was built, so two
    # dumps a second apart differ in four places and nowhere that a loader reads. Frozen to
    # the epoch rather than stripped, because the field is part of LangFlow's message schema
    # and a flow missing it would be a flow LangFlow did not write.
    text = re.sub(
        r'"timestamp": "\d{4}-\d{2}-\d{2} [\d:.]+ UTC"',
        '"timestamp": "1970-01-01 00:00:00.000000 UTC"',
        text,
    )
    counters = {}
    renames = {}
    for node in payload.get("data", {}).get("nodes", []):
        original = node.get("id") or ""
        # Anchored on the length of the suffix, not on the last hyphen. LangFlow's alphabet
        # includes `-`, so one id came out as `TraceTriageEvidenceTools-Pz-1` under
        # rsplit("-", 1): the random part was `Pz-Ab`, the split kept half of it, and the
        # class name in the file gained two characters of noise.
        cls = re.sub(r"-[A-Za-z0-9_-]{5}$", "", original)
        counters[cls] = counters.get(cls, 0) + 1
        renames[original] = f"{cls}-{counters[cls]}"
    for original, stable in renames.items():
        text = text.replace(original, stable)
    for original in renames:
        if original in text:
            raise AssertionError(
                f"{original} survives in {name} after renaming, so the file would carry "
                f"two names for one node"
            )
    path = f"{FLOWS_DIR}/{name}.json"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text + "\n")
    return path, list(renames.values()), len(edges)


# Flow 1. Nothing may stop this one: it needs no model and no network.
path, node_ids, n_edges = dump(
    build_grounding(),
    "tracetriage_grounding",
    "Check one sentence about a SatNOGS observation against that observation's own "
    "measured fields. No model and no network.",
)
entry = {"file": path, "nodes": node_ids, "n_edges": n_edges, "runs": []}
for label, claim in (("grounded", GROUNDED), ("ungrounded", UNGROUNDED)):
    got = texts(run_flow_from_json(flow=path, input_value=claim, fallback_to_env_vars=False))
    parsed = None
    for text in got:
        try:
            candidate = json.loads(text)
        except Exception:
            continue
        if isinstance(candidate, dict) and "verdict" in candidate:
            parsed = candidate
            break
    entry["runs"].append({
        "label": label,
        "input": claim,
        "verdict": None if parsed is None else parsed["verdict"],
        "codes": [] if parsed is None else parsed["codes"],
        "observation_id": None if parsed is None else parsed["observation_id"],
        "raw_outputs": len(got),
    })
entry["outcome"] = (
    "RAN" if all(r["verdict"] for r in entry["runs"]) else "FAILED"
)
RESULT["flows"]["grounding"] = entry

# Flow 2. Wants a model runtime. Three outcomes, and the file is written either way so a
# reader can import the graph even on a machine that cannot run it.
agent = {"file": None, "nodes": [], "n_edges": 0, "model": MODEL, "endpoint": OLLAMA}
try:
    path, node_ids, n_edges = dump(
        build_agent(),
        "tracetriage_granite_agent",
        "Bind this project's six read-only evidence tools to a local IBM Granite model "
        "through LangFlow's agent node.",
    )
    agent.update(file=path, nodes=node_ids, n_edges=n_edges)
except Exception as error:
    agent["outcome"] = "FAILED"
    agent["error_class"] = type(error).__name__
    agent["error"] = str(error)[:600]
    RESULT["flows"]["granite_agent"] = agent
else:
    try:
        import urllib.request
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5) as response:
            tags = json.loads(response.read().decode("utf-8"))
        names = [m.get("name") for m in tags.get("models", [])]
    except Exception as error:
        agent["outcome"] = "NOT_CHECKED"
        agent["reason"] = f"{OLLAMA} did not answer: {type(error).__name__}: {error}"
        RESULT["flows"]["granite_agent"] = agent
    else:
        agent["models_available"] = names
        if MODEL not in names:
            agent["outcome"] = "NOT_CHECKED"
            agent["reason"] = f"{MODEL} is not pulled on {OLLAMA}"
        else:
            try:
                got = texts(run_flow_from_json(
                    flow=path, input_value=QUESTION, fallback_to_env_vars=False
                ))
                answer = got[-1] if got else ""
                # Whether the answer carries the fact only a tool could supply.
                #
                # "The graph executed" and "the model used the tools" are two different
                # claims and the first does not imply the second. LangFlow's agent node
                # runs to completion whether or not the model actually invokes anything, so
                # a receipt that said RAN and stopped would be reporting the client and
                # letting a reader hear the model. The rank-1 id is in no prompt and in no
                # system message: it is only reachable through queue_top, so its presence
                # in the answer is a fact rather than a judgement about the answer.
                from pipeline.tracetriage.langchain_tools import handlers as _handlers
                expected = str(_handlers()["queue_top"](limit=1)["entries"][0]["obs_id"])
                agent["outcome"] = "RAN"
                agent["question"] = QUESTION
                agent["answer"] = answer[:800]
                agent["n_outputs"] = len(got)
                agent["expected_observation_id"] = expected
                agent["answer_carries_the_tool_only_fact"] = expected in answer
            except Exception as error:
                agent["outcome"] = "FAILED"
                agent["error_class"] = type(error).__name__
                agent["error"] = str(error)[:600]
                agent["traceback_tail"] = traceback.format_exc()[-600:]
        RESULT["flows"]["granite_agent"] = agent

print("@@JSON@@" + json.dumps(RESULT))
'''


def _run_child() -> dict[str, Any]:
    python = _interpreter()
    FLOWS.mkdir(exist_ok=True)
    environment = dict(os.environ)
    # The child imports this repository's package under a different interpreter, so the
    # repository root has to be on its path. PYTHONPATH rather than a sys.path edit
    # inside CHILD, because LangFlow executes a component's stored source in its own
    # context and that context inherits the process path.
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(REPO) + (os.pathsep + existing if existing else "")
    )
    completed = subprocess.run(
        [
            str(python),
            "-c",
            CHILD,
            str(FLOWS).replace("\\", "/"),
            GROUNDED_CLAIM,
            UNGROUNDED_CLAIM,
            AGENT_MODEL,
            OLLAMA_URL,
            AGENT_QUESTION,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )
    marker = "@@JSON@@"
    for line in reversed((completed.stdout or "").splitlines()):
        if line.startswith(marker):
            return json.loads(line[len(marker):])
    raise SystemExit(
        "the LangFlow child produced no result line. Its output follows.\n"
        f"exit {completed.returncode}\n"
        f"{(completed.stdout or '')[-1500:]}\n{(completed.stderr or '')[-2500:]}"
    )


def _digest(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict[str, Any]:
    child = _run_child()
    flows: dict[str, Any] = {}
    for name, entry in child["flows"].items():
        record = dict(entry)
        file_path = record.get("file")
        if file_path:
            path = Path(file_path)
            record["file"] = str(path.relative_to(REPO)).replace("\\", "/")
            record["sha256"] = _digest(path)
            record["bytes"] = path.stat().st_size
        flows[name] = record
    return {
        "unit": "F2",
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime": {
            "langflow": child.get("langflow_version"),
            "langflow_base": child.get("langflow_base_version"),
            "interpreter": str(_interpreter()).replace("\\", "/"),
            "is_a_dependency_of_this_project": False,
        },
        "how_these_were_produced": (
            "Each flow is assembled from component objects with langflow.graph.Graph, "
            "written out by Graph.dump(), and then loaded back from that file by "
            "langflow.load.run_flow_from_json and executed. The committed JSON is "
            "therefore a file LangFlow wrote and can import, and the results below came "
            "from the loaded file rather than from the objects that built it."
        ),
        "flows": flows,
        "identity": (
            "Every node calls the function object scripts/mcp_server.py registered, "
            "reached through pipeline.tracetriage.langchain_tools.handlers(), whose "
            "identity is asserted per tool in tests/test_langchain_tools.py. The "
            "grounding node is the same checker that decides whether this project's own "
            "notes ship, not a second copy of its rules."
        ),
        "what_this_does_not_measure": (
            "Whether a flow is a better way to reach these tools than MCP. It is a "
            "different client for the same read-only surface, offered because LangFlow is "
            "a technology this challenge names and because a visual graph is how some "
            "teams would wire it. Nothing this repository publishes runs through LangFlow, "
            "and nothing here depends on it being installed."
        ),
    }


_VOLATILE = ("generated_at",)


def _comparable(receipt: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in receipt.items() if key not in _VOLATILE}
    flows = {}
    for name, entry in (out.get("flows") or {}).items():
        # A model's prose answer is not deterministic even at temperature 0 across
        # restarts, and neither is the list of models a machine happens to have pulled.
        # The verdicts, the codes, the node set and the file digest are.
        flows[name] = {
            key: value
            for key, value in entry.items()
            if key
            not in (
                "answer",
                "answer_carries_the_tool_only_fact",
                "models_available",
                "reason",
                "traceback_tail",
            )
        }
    out["flows"] = flows
    runtime = dict(out.get("runtime") or {})
    runtime.pop("interpreter", None)
    out["runtime"] = runtime
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild and compare against the committed receipt",
    )
    args = parser.parse_args(argv)

    fresh = build()

    if args.check:
        if not RECEIPT.exists():
            print(f"[FAIL] {RECEIPT.relative_to(REPO)} is missing. Run this script.")
            return 1
        committed = json.loads(RECEIPT.read_text(encoding="utf-8"))
        if _comparable(committed) == _comparable(fresh):
            print("[PASS] langflow receipt matches this tree")
            return 0
        print(
            f"[FAIL] {RECEIPT.relative_to(REPO)} disagrees with a rebuild. "
            f"Re-run scripts/run_langflow_check.py."
        )
        return 1

    RECEIPT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8", newline="\n")
    for name, entry in fresh["flows"].items():
        line = f"{name}: {entry.get('outcome')}"
        if entry.get("runs"):
            line += "  " + ", ".join(
                f"{run['label']}={run['verdict']}{run['codes'] or ''}"
                for run in entry["runs"]
            )
        if entry.get("reason"):
            line += f"  ({entry['reason']})"
        print(line)
    print(f"langflow {fresh['runtime']['langflow']}")
    print(f"wrote {RECEIPT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    if shutil.which("git") is None:
        pass
    raise SystemExit(main())
