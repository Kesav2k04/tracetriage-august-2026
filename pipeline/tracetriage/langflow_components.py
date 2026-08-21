"""This project's evidence tools as LangFlow components, and why they are three files.

``docs/USE_WITH_YOUR_AGENT.md`` said, correctly, that "a flow file this project has never
imported would be a screenshot of an integration rather than an integration". That sentence
is the standard this integration has to clear, so it is written to be executed rather than
displayed: ``scripts/run_langflow_check.py`` builds a graph out of these classes, dumps the
graph to the flow JSON under ``flows/``, then loads that JSON back through LangFlow's own
runner and records what came out in ``artifacts/LANGFLOW_RECEIPT.json``. A flow that has
never run does not get committed, because the receipt is what makes the file worth reading.

This module only re-exports, and the reason each class lives in its own file is a defect that
was measured rather than anticipated. LangFlow serialises a custom component by storing its
source in the flow JSON and executing that source on load, then resolving *the* Component
subclass it finds there. All three classes started in this file, the grounding flow worked,
and the agent flow failed with ``AttributeError: Attribute build_tools not found in
TraceTriageGroundingCheck``: the loader had found the first class in the module and bound it
to the tools node. One class per file makes that resolution unambiguous.

Two other rules the three modules follow.

*Definitions and imports only.* No calls at module scope, no ``if __name__`` block. The first
version defined the components inside the build script, so the stored source was the whole
script including the line that ran the flow, and loading the flow re-ran the builder, which
re-loaded the flow. LangFlow reported it as ``ValueError(Error creating class(...))`` nested
some hundreds deep. A module that only defines things can be executed any number of times.

*Nothing is reimplemented.* Every component calls the same function object
``scripts/mcp_server.py`` registered, reached through
``pipeline.tracetriage.langchain_tools.handlers()``, which asserts that identity per tool.
``check_claim`` in a LangFlow node is therefore the same grounding checker that decides
whether this project's own notes ship, and not a second copy of the rules that could drift
from it. Two implementations of one question is the defect this repository has spent the most
time on.
"""

from __future__ import annotations

from pipeline.tracetriage.langflow_grounding import TraceTriageGroundingCheck
from pipeline.tracetriage.langflow_queue import TraceTriageQueueTop
from pipeline.tracetriage.langflow_tools import TraceTriageEvidenceTools

__all__ = [
    "TraceTriageEvidenceTools",
    "TraceTriageGroundingCheck",
    "TraceTriageQueueTop",
]
