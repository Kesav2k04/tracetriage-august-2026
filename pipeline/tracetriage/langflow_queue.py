"""The head of the review queue as a LangFlow node.

One component per module, for the reason spelled out in
``pipeline/tracetriage/langflow_grounding.py``: LangFlow executes a component's stored source
on load and resolves *the* Component subclass it finds, so three classes in one file resolve
to whichever comes first. This file holds definitions and imports and nothing else.
"""

from __future__ import annotations

import json
from typing import Any

from langflow.custom import Component
from langflow.io import IntInput, Output
from langflow.schema.message import Message

from pipeline.tracetriage.langchain_tools import handlers


class TraceTriageQueueTop(Component):
    """The head of the review queue, as the console publishes it."""

    display_name = "TraceTriage queue"
    description = (
        "The top of the review-value queue over SatNOGS observations, each row with the "
        "criterion that raised it."
    )
    documentation = "https://github.com/Kesav2k04/tracetriage-august-2026"
    icon = "list"
    name = "TraceTriageQueueTop"

    inputs = [
        IntInput(
            name="limit",
            display_name="Rows",
            info="How many ranked rows to return.",
            value=5,
        ),
    ]
    outputs = [
        Output(display_name="Queue", name="queue", method="top"),
    ]

    def top(self) -> Message:
        result: dict[str, Any] = handlers()["queue_top"](limit=int(self.limit or 5))
        self.status = f"{result['returned']} of {result['available']} rows"
        return Message(text=json.dumps(result, indent=1))
