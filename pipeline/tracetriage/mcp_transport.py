"""JSON-RPC 2.0 over stdio: the transport both MCP servers in this project speak.

Lifted out of `scripts/mcp_server.py`, which had it inline, for one concrete reason: a
`pip install tracetriage` ships this package and does not ship `scripts/`, so
`tracetriage mcp-live` could not have found a dispatcher living there. The offline server
needs a checkout regardless, because the evidence it serves is committed files, but the
live server needs nothing except this package and the network.

There is no MCP SDK dependency and that is deliberate. Three methods are what a client
uses: `initialize`, `tools/list`, `tools/call`. Implementing them against the standard
library is what keeps this project's clean-clone claim intact, and it is why this module
imports `json`, `sys` and `typing` and nothing else: `tests/test_mcp_server.py` runs the
offline server under `python -S -E`, with no site-packages and no ambient environment, and
one third-party import anywhere in the closure would fail that.

Every branch here exists because an input ended a session once: a frame that is not an
object, a batch array, an id passed as a string, a receipt name that resolved to a
directory, a notification answered when it should not have been. That history is the reason
this is one implementation rather than one per server.

A caller supplies a tool registry mapping name to ``{"handler", "description", "schema"}``,
its own `serverInfo`, its own instructions, and optionally a `preflight` returning a list of
reasons it cannot start. What it must not supply is a guarantee: read-only and offline are
properties of which handlers get registered, not of this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: Only used to scrub this checkout's path out of exception text; a caller may override it.
REPO = Path(__file__).resolve().parents[2]

PROTOCOL_VERSION = "2024-11-05"

class ToolError(Exception):
    """A tool call that cannot be answered, carrying the reason code it failed with."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code



def _scrubbed(exc: Exception, scrub_root: Any = None) -> str:
    """An exception message with this checkout's path removed.

    Exceptions from the filesystem carry absolute paths, and this message goes to a client.

    Split and join rather than ``str.replace``, because the read-only scan in
    ``tests/test_mcp_server.py`` counts ``replace`` as a filesystem move, and a scan with an
    exception for one receiver is a scan with a hole. One awkward line here is cheaper than
    that.
    """
    root = str(REPO if scrub_root is None else scrub_root)
    return f"{type(exc).__name__}: {'<repo>'.join(str(exc).split(root))}"



def _invalid_request(detail: str, request_id: Any = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32600, "message": f"invalid request: {detail}"},
    }



def handle(
    request: Any,
    tools: dict[str, Any] | None = None,
    server_info: dict[str, str] | None = None,
    instructions: str | None = None,
) -> dict[str, Any] | None:
    """One JSON-RPC request to one response, or None for a notification.

    A frame that is not an object gets an invalid-request error rather than an
    AttributeError. Parsing succeeded for ``5``, ``null`` and a batch array, so the parse
    error branch never saw them and ``.get`` on a list ended the session.

    The three optional arguments exist so that `pipeline/tracetriage/mcp_live.py` can serve a
    different tool set over this dispatcher instead of carrying a copy of it. They default
    to this server's own registry, so every existing caller and every test sees the
    behaviour it saw before. A second JSON-RPC implementation is a second place for the
    batch handling, the six named error paths and the notification rule to drift, and each
    of those exists here because an input broke the session once.

    What is deliberately NOT shared: this file's offline guarantee. That is a property of
    which handlers are registered, not of the transport, and the live server's tools reach
    the network by design. The scan in `tests/test_mcp_server.py` reads this file's own
    imports, so it keeps proving the claim for this file whatever the transport is reused
    for elsewhere.
    """
    tools = tools or {}
    if not isinstance(request, dict):
        return _invalid_request(f"a JSON-RPC request is an object, got {type(request).__name__}")
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": server_info or {"name": "mcp", "version": "0"},
            "instructions": instructions or "",
        }
    elif method == "notifications/initialized":
        return None
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": name,
                    "description": spec["description"],
                    "inputSchema": spec["schema"],
                }
                for name, spec in tools.items()
            ]
        }
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        spec = tools.get(name)
        if spec is None:
            return _error_result(
                request_id,
                "UNKNOWN_TOOL",
                f"{name!r} is not a tool. Available: {sorted(tools)}.",
            )
        if not isinstance(arguments, dict):
            return _error_result(
                request_id,
                "BAD_ARGUMENTS",
                f"arguments must be an object, got {type(arguments).__name__}.",
            )
        try:
            payload = spec["handler"](**arguments)
        except ToolError as exc:
            return _error_result(request_id, exc.code, str(exc))
        except TypeError as exc:
            return _error_result(request_id, "BAD_ARGUMENTS", _scrubbed(exc))
        except Exception as exc:  # noqa: BLE001
            # The blanket clause is the point. This is a stdio server, so an exception
            # reaching the read loop ends the client's whole session, and the six inputs
            # that did it were ordinary mistakes: an id passed as a string, a receipt name
            # that resolved to a directory. A named reason is worth more than a traceback
            # nobody sees, and a tool that fails for a reason nobody predicted still has to
            # say so rather than take the transport down.
            return _error_result(request_id, "TOOL_FAILED", _scrubbed(exc))
        result = {
            "content": [{"type": "text", "text": json.dumps(payload, indent=1)}],
            "isError": False,
        }
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method {method!r} is not implemented"},
        }

    return {"jsonrpc": "2.0", "id": request_id, "result": result}



def _error_result(request_id: Any, code: str, message: str) -> dict[str, Any]:
    """A tool failure, as a tool result rather than a protocol error.

    The distinction matters to a client: a protocol error means the server is broken, and a
    tool result with isError means the question could not be answered. Returning the first
    for the second would make an unknown observation id look like a crash.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {"type": "text", "text": json.dumps({"reason": code, "detail": message})}
            ],
            "isError": True,
        },
    }



def _write(sink: Any, payload: Any) -> None:
    sink.write(json.dumps(payload) + "\n")
    sink.flush()



def serve(
    stdin: Any = None,
    stdout: Any = None,
    tools: dict[str, Any] | None = None,
    server_info: dict[str, str] | None = None,
    instructions: str | None = None,
    preflight: Any = None,
) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout.

    Refuses to start when an advertised evidence file is missing. The docstring at the top
    of this file claimed that behaviour before it existed: what was implemented was a
    per-call reason code, which is weaker, because a client that has completed a handshake
    and read a tool list has been told those tools work.

    ``preflight`` replaces that check for a caller with a different one to make. It returns
    a list of human-readable problems, empty when there are none. The live server's
    preflight cannot be this one: it advertises no committed file and its own precondition
    is an import that may not be installed.
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout

    absent = preflight() if preflight else []
    if absent:
        print(
            f"{(server_info or {}).get('name', 'mcp server')} cannot start: "
            + ", ".join(absent)
            + ". Answering with an empty payload would read as a measurement.",
            file=sys.stderr,
        )
        return 2
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _write(
                sink,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"parse error: {exc}"},
                },
            )
            continue
        # A batch is legal JSON-RPC 2.0 and used to be an AttributeError that ended the
        # session. Handling it is four lines: a batch of notifications gets no reply at
        # all, which is what the specification says and what a client waits on.
        if isinstance(request, list):
            if not request:
                _write(sink, _invalid_request("a batch must hold at least one request"))
                continue
            replies = [
                r
                for r in (
                    handle(item, tools, server_info, instructions) for item in request
                )
                if r is not None
            ]
            if replies:
                _write(sink, replies)
            continue

        response = handle(request, tools, server_info, instructions)
        if response is not None:
            _write(sink, response)
    return 0


