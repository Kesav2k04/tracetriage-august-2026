"""The LangChain adapter offers the MCP server's tools, and not copies of them.

An adapter is the cheapest place in a repository to grow a second implementation. Someone
needs `check_claim` to accept a slightly different argument, writes it here because this file
is small and the server is not, and the project now refuses different sentences depending on
which client asked. Nothing in a build catches that: both sides pass their own tests.

So the assertion is identity. `handlers()[name] is TOOLS[name]["handler"]`, per tool, for
every tool offered. Not "the same behaviour", not "the same output on a fixture": the same
function object, which is the only version of the claim that cannot drift.

The rest of this file covers what identity does not: that the adapter passes arguments
through in the shape the handlers take, that the schema an agent validates against is the
MCP schema rather than an inference from `**kwargs`, and that the two tools which spend
somebody else's time or bandwidth are not offered.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from mcp_server import TOOLS  # noqa: E402

from pipeline.tracetriage import langchain_tools as adapter  # noqa: E402

RECEIPT = REPO / "artifacts" / "LANGCHAIN_RECEIPT.json"

langchain_core = pytest.importorskip(
    "langchain_core",
    reason=(
        "langchain-core is an optional extra. Every number this repository publishes is "
        "reproducible without it, and this file is the check that skips."
    ),
)


@pytest.fixture(scope="module")
def built() -> dict:
    return {tool.name: tool for tool in adapter.tools()}


def test_every_offered_tool_is_the_mcp_server_s_own_callable():
    """The whole point of the module, asserted on object identity."""
    bound = adapter.handlers()
    assert set(bound) == set(adapter.OFFERED)
    for name, handler in bound.items():
        assert handler is TOOLS[name]["handler"], (
            f"{name} in the LangChain adapter is not the same function the MCP server "
            f"registered, so the two clients can disagree about what this tool does"
        )


def test_the_adapter_offers_nothing_the_server_does_not_register():
    unknown = sorted(set(adapter.OFFERED) - set(TOOLS))
    assert not unknown, unknown


def test_the_tools_that_cost_something_are_withheld_with_a_reason():
    """A cost is a reason to withhold. An unexplained absence is a reason to wonder."""
    assert "run_acceptance" in TOOLS
    assert "run_acceptance" not in adapter.OFFERED
    assert adapter.WITHHELD["run_acceptance"]
    for name, why in adapter.WITHHELD.items():
        assert name in TOOLS, name
        assert len(why) > 20, (name, why)


def test_each_tool_carries_the_mcp_schema_rather_than_an_inferred_one(built):
    """Inferred from `**kwargs`, every tool would advertise no arguments at all."""
    assert set(built) == set(adapter.OFFERED)
    for name, tool in built.items():
        assert isinstance(tool.args_schema, dict), name
        expected = TOOLS[name]["schema"]
        assert tool.args_schema["type"] == expected["type"]
        assert set(tool.args_schema.get("properties", {})) == set(
            expected.get("properties", {})
        ), name
        assert tool.description == TOOLS[name]["description"], name


def test_a_tool_that_takes_no_arguments_can_be_called_with_none(built):
    """The defect the first version had, in the two places it had it."""
    for name in ("queue_size", "gate_status"):
        payload = json.loads(built[name].invoke({}))
        assert payload, name


def test_a_tool_that_takes_arguments_receives_them(built):
    payload = json.loads(built["queue_top"].invoke({"limit": 3}))
    assert len(payload["entries"]) == 3
    assert payload["available"] > len(payload["entries"])


def test_the_grounding_checker_refuses_through_the_adapter(built):
    """The one call that matters, on the observation the handover names."""
    refused = json.loads(
        built["check_claim"].invoke(
            {"observation_id": 14740031, "text": "The downlink is 437.2 MHz."}
        )
    )
    assert refused["verdict"] == "REFUSED"
    assert "UNGROUNDED_NUMBER" in refused["codes"]


def test_the_adapter_returns_json_rather_than_a_python_repr(built):
    """A dict rendered by repr is single-quoted, which a model will then reproduce."""
    text = built["queue_size"].invoke({})
    assert text.lstrip().startswith("{")
    assert "'" not in text.splitlines()[1]
    json.loads(text)


def test_the_receipt_is_what_the_adapter_currently_produces():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_langchain_check.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_receipt_records_the_callable_behind_each_tool():
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert payload["n_offered"] == len(adapter.OFFERED)
    assert payload["source_of_truth"] == "scripts/mcp_server.py TOOLS"
    for entry in payload["offered"]:
        # `mcp_server.tool_check_claim`, not `langchain_tools.something`. The module in the
        # recorded name is what says the adapter did not bring its own implementation.
        assert entry["callable"].startswith("mcp_server."), entry
    exercised = payload["exercised"]
    assert exercised, "the committed receipt was written without langchain installed"
    assert exercised["refusal_through_the_adapter"]["verdict"] == "REFUSED"
