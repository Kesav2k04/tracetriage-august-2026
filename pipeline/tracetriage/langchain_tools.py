"""The project's evidence tools, as LangChain tools, and the reason this is not a rewrite.

TraceTriage already exposes its evidence over MCP: `scripts/mcp_server.py` answers seven
tools on stdio and `pipeline/tracetriage/mcp_live.py` answers five more that measure. That
covers a Bob session, a Cursor session and anything else that speaks the protocol. It does
not cover a LangChain agent, because LangChain wants Python callables with a JSON schema and
a docstring, not a subprocess speaking JSON-RPC.

So this module adapts. What it does not do is reimplement:

    every tool here calls the same function object the MCP server registered.

That is asserted rather than asserted about. `receipt()` records the fully qualified name of
each wrapped callable and `tests/test_langchain_tools.py` checks each one is the identical
object in `scripts.mcp_server.TOOLS`, so a second implementation of `check_claim` with
slightly different rules cannot appear here without failing. Two code paths that answer the
same question are the defect this project has spent the most time on: the grounding checker
is deliberately two implementations and it costs an answer key of 1,275 recorded decisions
to keep them honest. Nothing else gets to be two implementations for free.

Three things are deliberately absent.

No model. `tools()` returns tools; binding them to a chat model is the caller's business,
so this module needs no LLM dependency and works with Granite over Ollama, with watsonx, or
with anything else LangChain can talk to. `docs/USE_WITH_YOUR_AGENT.md` has the six lines
that bind them to a local Granite.

No writes. Every tool here reads a committed receipt. `run_acceptance` is not wrapped: it
runs the repository's gate and writes a build, which is a reasonable thing for an operator to
run and an unreasonable thing to hand an agent that decides for itself when to call it.

No live tools. `live_triage_observation` downloads a waterfall from a volunteer network. An
agent that decides to retry is an agent spending somebody else's bandwidth, and the MCP
registration marks those tools as ones that ask first. The same reasoning applies here, and
the honest version of it is that they are not offered rather than that they are offered with
a warning.

`langchain-core` is an optional extra, like `chromadb` and `easyocr`. A clean clone without it
installs, runs the suite and reproduces every published number; the tests here skip and say
so, which is the same trade the vector index makes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[2]

#: The tools offered to an agent, and the two that are not.
#:
#: `run_acceptance` writes and takes minutes. The five `live_*` tools spend a volunteer
#: network's bandwidth. Both are reachable over MCP, where a human approves each call.
OFFERED = (
    "queue_top",
    "queue_size",
    "observation",
    "check_claim",
    "gate_status",
    "receipt",
)
WITHHELD = {
    "run_acceptance": (
        "runs the repository's gate, writes the console build, and takes minutes of CPU"
    ),
}


class LangChainMissing(ImportError):
    """Raised with the install line rather than a bare ImportError from three frames down."""


def _registry() -> dict[str, dict[str, Any]]:
    """The MCP server's own tool table.

    Imported by path because `scripts/` is not a package: the same insert the other
    generators do, kept in one place so the sys.path edit is visible rather than repeated.
    """
    scripts = str(REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from mcp_server import TOOLS  # noqa: PLC0415

    return TOOLS


def _require_langchain() -> Any:
    try:
        from langchain_core.tools import StructuredTool  # noqa: PLC0415
    except ImportError as error:  # pragma: no cover - exercised by the skip in the tests
        raise LangChainMissing(
            "langchain-core is not installed. It is an optional extra of this project: "
            "`pip install -e .[agent]`. Every number this repository publishes is "
            "reproducible without it."
        ) from error
    return StructuredTool


def handlers() -> dict[str, Callable[..., Any]]:
    """The callable behind each offered tool, by name.

    Exported so a caller can check identity against `scripts.mcp_server.TOOLS` without
    importing langchain at all, which is what makes the parity test cheap.
    """
    registry = _registry()
    missing = [name for name in OFFERED if name not in registry]
    if missing:
        raise KeyError(
            f"{missing} are offered here and the MCP server does not register them. One of "
            f"the two lists is wrong, and this is not the place to guess which."
        )
    return {name: registry[name]["handler"] for name in OFFERED}


def tools() -> list[Any]:
    """One LangChain `StructuredTool` per offered tool.

    The description handed to the model is the MCP description, unedited. A tool that
    describes itself differently to two clients is a tool that gets called for different
    reasons by each of them, and the reason it gets called is the only thing a description
    controls.
    """
    StructuredTool = _require_langchain()
    registry = _registry()
    built: list[Any] = []
    for name in OFFERED:
        spec = registry[name]
        handler = spec["handler"]

        def call(_handler: Callable[..., Any] = handler, **kwargs: Any) -> str:
            # Keyword arguments, expanded. The MCP transport hands each handler a single
            # arguments dict and unpacks it there; these handlers take named parameters,
            # so passing the dict itself raised "takes 0 positional arguments" on the two
            # tools that take none. One layer of unpacking, in the one place that adapts.
            #
            # JSON out, not a dict: an agent's transcript is text, and a dict rendered by
            # repr puts single quotes around every key, which is not JSON and is the kind
            # of thing a model then reproduces as if it were.
            return json.dumps(_handler(**kwargs), indent=1, sort_keys=True)

        # `from_function` insists on a docstring when it is given a JSON schema dict, even
        # with an explicit description, so the two are set from one string rather than left
        # to disagree.
        call.__doc__ = spec["description"]

        built.append(
            StructuredTool.from_function(
                func=call,
                name=name,
                # The MCP schema, handed over unchanged. langchain-core accepts a JSON
                # schema dict here, so the argument contract a Bob session validates
                # against and the one a LangChain agent validates against are the same
                # object rather than two descriptions of one intent. Inferring the schema
                # from `call(**kwargs)` instead would have advertised no arguments at all,
                # which is how an agent ends up never passing `limit`.
                args_schema=spec["schema"],
            )
        )
    return built


def receipt() -> dict[str, Any]:
    """What was wrapped, what was withheld, and the identity claim, as a receipt.

    `scripts/run_langchain_check.py` writes this to `artifacts/LANGCHAIN_RECEIPT.json`.
    """
    registry = _registry()
    bound = handlers()
    return {
        "schema": "tracetriage/langchain",
        "schema_version": "0.1.0",
        "unit": "the project's evidence tools, adapted to LangChain",
        "adapter": "pipeline/tracetriage/langchain_tools.py",
        "source_of_truth": "scripts/mcp_server.py TOOLS",
        "n_offered": len(OFFERED),
        "n_registered_by_the_mcp_server": len(registry),
        "offered": [
            {
                "name": name,
                "callable": f"{bound[name].__module__}.{bound[name].__qualname__}",
                "description": registry[name]["description"],
            }
            for name in OFFERED
        ],
        "withheld": [
            {"name": name, "why": why} for name, why in sorted(WITHHELD.items())
        ],
        "live_tools_not_offered": {
            "n": 5,
            "why": (
                "each downloads a waterfall from a volunteer network. They are reachable "
                "over MCP, where a human approves the call."
            ),
        },
        "reading": (
            "Every tool listed above calls the function object the MCP server registered, "
            "not a copy of it. tests/test_langchain_tools.py asserts identity per tool, so "
            "a second implementation of the grounding checker cannot appear behind this "
            "adapter."
        ),
    }
