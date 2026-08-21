"""The six read-only evidence tools as a LangFlow toolkit node.

One component per module, for the reason spelled out in
``pipeline/tracetriage/langflow_grounding.py``: LangFlow executes a component's stored source
on load and resolves *the* Component subclass it finds, so three classes in one file resolve
to whichever comes first. This file holds definitions and imports and nothing else.
"""

from __future__ import annotations

from typing import Any

from langflow.custom import Component
from langflow.io import Output

from pipeline.tracetriage.langchain_tools import tools


class TraceTriageEvidenceTools(Component):
    """The six read-only evidence tools, for an agent node to bind.

    The same ``StructuredTool`` objects ``pipeline/tracetriage/langchain_tools.py`` builds,
    which are the same handlers the MCP server registered. What is not offered here is what
    is not offered there: ``run_acceptance``, which writes a build, and the five live tools,
    which each spend a volunteer network's bandwidth. Both are reachable over MCP, where a
    person approves the call.
    """

    display_name = "TraceTriage evidence tools"
    description = (
        "Six read-only tools over this project's committed receipts: the queue, one "
        "observation, the gate status, a named receipt, and the grounding checker."
    )
    documentation = "https://github.com/Kesav2k04/tracetriage-august-2026"
    icon = "hammer"
    name = "TraceTriageEvidenceTools"

    inputs: list[Any] = []
    # ``types=["Tool"]`` is load-bearing rather than metadata. LangFlow validates an edge by
    # comparing the source output's declared types against the target input's
    # ``input_types``, and the agent node's tools handle accepts ``["Tool"]``. Without the
    # declaration the return annotation is all LangFlow has, ``list[Any]`` infers nothing,
    # and building the graph fails with "Edge between TraceTriage evidence tools and Agent
    # has invalid handles", which names the edge and not the missing annotation.
    outputs = [
        Output(
            display_name="Tools",
            name="tools",
            method="build_tools",
            types=["Tool"],
        ),
    ]

    def build_tools(self) -> list[Any]:
        built = tools()
        self.status = ", ".join(tool.name for tool in built)
        return built
