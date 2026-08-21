"""The grounding checker as a LangFlow node.

One component per module, and that is a hard requirement rather than tidiness. LangFlow
serialises a custom component by storing its source in the flow JSON and executing that
source when the flow is loaded, then resolving *the* Component subclass it finds there. A
module holding three of them resolves to whichever one it finds first, so an agent flow
asking for the tools node got the grounding node instead and failed with "Attribute
build_tools not found in TraceTriageGroundingCheck", which names the attribute and not the
cause. One class per file makes that resolution unambiguous.

For the same reason this file holds definitions and imports and nothing else: no calls at
module scope and no ``if __name__`` block. The first version of this integration defined its
components inside the build script, so the stored source was the whole script including the
line that ran the flow, and loading the flow re-ran the builder, which re-loaded the flow.
LangFlow reported it as ``ValueError(Error creating class(...))`` nested some hundreds deep.

Nothing here reimplements anything. Every component calls the same function object
``scripts/mcp_server.py`` registered, reached through
``pipeline.tracetriage.langchain_tools``, whose identity is asserted per tool in
``tests/test_langchain_tools.py``. This node is therefore the same checker that decides
whether this project's own notes ship, not a second copy of its rules.

``pipeline/tracetriage/langflow_components.py`` re-exports all three for a human reader.
"""

from __future__ import annotations

import json
from typing import Any

from langflow.custom import Component
from langflow.io import IntInput, MessageTextInput, Output
from langflow.schema.message import Message

from pipeline.tracetriage.langchain_tools import handlers


def _rank_one() -> int:
    """The observation this node defaults to.

    Rank 1 of the shipped queue, resolved at call time rather than written down, so a flow
    committed today cannot end up asking about an observation the console has since stopped
    ranking. Only rows the console marks as carrying an evidence packet are eligible,
    because ``check_claim`` refuses an id it holds no packet for, and a default that
    triggered a refusal would look like the checker working when it is the flow being wrong.
    """
    top = handlers()["queue_top"](limit=50)
    for entry in top["entries"]:
        if entry.get("has_evidence_packet"):
            return int(entry["obs_id"])
    raise ValueError(
        "no ranked observation carries an evidence packet. "
        "Run scripts/build_console_data.py."
    )


class TraceTriageGroundingCheck(Component):
    """Put one sentence about one observation through the grounding checker.

    The node this integration exists for. An agent, a person or another flow can hand it a
    claim, and it comes back GROUNDED or REFUSED with the violation codes, decided against
    that observation's own measured fields. No model is involved and no request leaves the
    machine.
    """

    display_name = "TraceTriage grounding check"
    description = (
        "Verify a sentence about a SatNOGS observation against that observation's own "
        "measured fields. Returns GROUNDED or REFUSED with the violation codes."
    )
    documentation = "https://github.com/Kesav2k04/tracetriage-august-2026"
    icon = "shield"
    name = "TraceTriageGroundingCheck"

    inputs = [
        MessageTextInput(
            name="claim",
            display_name="Claim",
            info="The sentence to check, in plain English.",
            required=True,
        ),
        IntInput(
            name="observation_id",
            display_name="Observation id",
            info=(
                "The SatNOGS observation the claim is about. Leave at 0 to use rank 1 of "
                "the shipped review queue."
            ),
            value=0,
        ),
    ]
    outputs = [
        Output(display_name="Verdict", name="verdict", method="check"),
    ]

    def check(self) -> Message:
        claim = str(self.claim or "").strip()
        if not claim:
            # The checker raises EMPTY_CLAIM for this, and a flow that surfaced a traceback
            # would tell a reader the integration is broken rather than that the input was.
            return Message(text="REFUSED EMPTY_CLAIM: nothing was submitted to check.")
        requested = int(self.observation_id or 0)
        obs_id = requested if requested > 0 else _rank_one()
        result: dict[str, Any] = handlers()["check_claim"](
            observation_id=obs_id, text=claim
        )
        self.status = f"{result['verdict']} {result['codes']}"
        return Message(text=json.dumps(result, indent=1))
