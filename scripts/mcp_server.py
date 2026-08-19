"""A read-only Model Context Protocol server over the committed evidence (unit E3).

    .venv/Scripts/python.exe scripts/mcp_server.py

Speaks JSON-RPC 2.0 on stdin and stdout, which is what an MCP stdio transport is. There is
no SDK dependency: the three methods a client needs are ``initialize``, ``tools/list`` and
``tools/call``, and implementing them against the standard library keeps this project's
offline install claim intact. A server that added a package to be a server would have made
the clean-clone reproduction depend on a registry.

Why this exists. Everything this project measured is in files under ``artifacts/`` and
``apps/web/public/data/``, and reading them means knowing which file holds which number.
Exposing them as tools means any agent can ask the questions directly, including the one
question this project is actually about:

    check_claim(observation_id, "the corridor sits 6.9 MHz from the catalogue centre")

which returns the grounding checker's verdict on that sentence. An agent writing about an
observation can have its own prose checked against the evidence packet before a human sees
it, using the same checker that refused fourteen of twenty-five of the model's own drafts.

Five hard properties, each of which is a test in ``tests/test_mcp_server.py``.

**Read-only.** No tool writes, and the import closure of this file reaches no HTTP write
verb and no annotation store.

**Offline.** Every answer comes from a committed file. There is no network call, and the
server refuses to start if a file it advertises is missing rather than returning an empty
result that reads like an answer.

**No invented numbers.** Values are copied from the receipts, never recomputed here. A
second implementation of a published number is a second thing to keep in step.

**Every error is a named reason.** A tool call that cannot be answered returns
``isError`` with a reason code, not an empty payload.

**Bounded output.** ``queue_top`` caps its limit and ``receipt`` returns a summary rather
than a 250 kilobyte file, because a tool that floods a context window is a tool nobody can
use twice.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.explain import build_packet, verify_note  # noqa: E402

_DATA = REPO / "apps" / "web" / "public" / "data"
_ARTIFACTS = REPO / "artifacts"

def _data_dir() -> Path:
    """Read at call time rather than captured, so a test can redirect it."""
    return _DATA


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "tracetriage-evidence"
SERVER_VERSION = "1.0.0"

#: A queue of 407 entries answered in full would fill a context window with rows nobody
#: reads. Twenty-five is the number of cards the console ships.
MAX_QUEUE_LIMIT = 50
DEFAULT_QUEUE_LIMIT = 10


class ToolError(Exception):
    """A tool call that cannot be answered, carrying the reason code it failed with."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _relative(path: Path) -> str:
    """The path as a reader would type it, or the whole path if it is outside the repo.

    ``relative_to`` raises for a path that is not under the repository, which is exactly the
    case a test that redirects the data directory produces, so the error message has to
    survive it rather than turn a named reason into a traceback.
    """
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ToolError(
            "EVIDENCE_FILE_MISSING",
            f"{_relative(path)} is not in this checkout. Run the pipeline scripts that "
            f"write it; an empty answer would read as a measurement.",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _packets() -> dict[int, Any]:
    cards = _load(_data_dir() / "cards.json")["cards"]
    entries = _load(_data_dir() / "queue.json")["entries"]
    by_id = {int(e["obs_id"]): e for e in entries}
    return {
        int(c["obs_id"]): build_packet(c, by_id[int(c["obs_id"])])
        for c in cards
        if int(c["obs_id"]) in by_id
    }


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------


def tool_queue_top(limit: int = DEFAULT_QUEUE_LIMIT) -> dict[str, Any]:
    """The top of the review queue, in rank order, with the reason each row was flagged."""
    if not isinstance(limit, int) or limit < 1:
        raise ToolError("BAD_LIMIT", f"limit must be a positive integer, got {limit!r}")
    capped = min(limit, MAX_QUEUE_LIMIT)
    queue = _load(_data_dir() / "queue.json")
    rows = sorted(queue["entries"], key=lambda e: e["rank"])[:capped]
    return {
        "review_budget": queue["review_budget"],
        "returned": len(rows),
        "capped_at": MAX_QUEUE_LIMIT if limit > MAX_QUEUE_LIMIT else None,
        "entries": [
            {
                "obs_id": r["obs_id"],
                "rank": r["rank"],
                "score": r["score"],
                "reasons": r["reasons"],
                "is_conflict": r["is_conflict"],
                "network_label": r["waterfall_status"],
                "model_probability": r["model_prob"],
            }
            for r in rows
        ],
        "reading": (
            "Rank is the order a reviewer should spend a fixed budget in. The queue's "
            "headline lift over random is NOT_ESTABLISHED against its 1.5x threshold: the "
            "point estimate is above it and the interval contains it. See gate_status."
        ),
    }


def tool_observation(observation_id: int) -> dict[str, Any]:
    """Every field a note about this observation is allowed to use, and the note itself."""
    packets = _packets()
    packet = packets.get(int(observation_id))
    if packet is None:
        raise ToolError(
            "UNKNOWN_OBSERVATION",
            f"{observation_id} is not one of the {len(packets)} observations this "
            f"checkout carries imagery and a queue row for. Try queue_top.",
        )
    notes = {int(n["obs_id"]): n for n in _load(_data_dir() / "notes.json")["notes"]}
    note = notes.get(int(observation_id))
    return {
        "observation_id": packet.obs_id,
        "evidence_packet": packet.printed,
        "evidence_packet_sha256": packet.sha256(),
        "note": None
        if note is None
        else {
            "text": note["note"],
            "source": note["source"],
            "refused_codes": note["refused_codes"],
            "why": note["why"],
        },
        "reading": (
            "evidence_packet is the closed world a generated note may draw on. A note "
            "whose source is deterministic means a generated draft was refused or never "
            "existed, and refused_codes says which."
        ),
    }


def tool_check_claim(observation_id: int, text: str) -> dict[str, Any]:
    """Run the grounding checker over a sentence about one observation.

    The tool this server exists for. Any agent writing prose about an observation can have
    it checked against the same evidence packet, by the same code, that decides whether this
    project's own generated notes ship.
    """
    if not isinstance(text, str) or not text.strip():
        raise ToolError("EMPTY_CLAIM", "text must be a non-empty string")
    packets = _packets()
    packet = packets.get(int(observation_id))
    if packet is None:
        raise ToolError(
            "UNKNOWN_OBSERVATION",
            f"{observation_id} is not one of the {len(packets)} observations this "
            f"checkout carries a packet for.",
        )
    result = verify_note(text, packet)
    return {
        "observation_id": packet.obs_id,
        "verdict": "GROUNDED" if result.ok else "REFUSED",
        "codes": result.codes,
        "violations": result.violations,
        "reading": (
            "GROUNDED means every number in the text appears in this observation's "
            "evidence packet, in the unit it was written in, and the text asserts nothing "
            "the permission contract forbids. It does not mean the text is useful."
        ),
    }


def tool_gate_status() -> dict[str, Any]:
    """The six kill gates and their verdicts, read from the console's provenance payload."""
    summary = _load(_data_dir() / "provenance.json")["gate_summary"]
    return {
        "gates": summary["gates"],
        "n_gates": summary["n_gates"],
        "n_met": summary["n_met"],
        "note": summary["note"],
        "reading": (
            "Met counts a gate that passed or pre-passed. NOT_ESTABLISHED is a measurement "
            "that came back inconclusive, not a failure and not a pass. OPEN is a study "
            "that was never run."
        ),
    }


def tool_receipt(name: str) -> dict[str, Any]:
    """A receipt's scalar summary. Never the whole file.

    Receipts run to a quarter of a megabyte. Returning one would spend a client's whole
    context on rows it did not ask for, so this returns the top-level keys that are not
    arrays, plus the length of each array, plus the path to read in full.
    """
    if not isinstance(name, str) or "/" in name or "\\" in name or ".." in name:
        raise ToolError(
            "BAD_RECEIPT_NAME",
            f"{name!r} is not a bare filename under artifacts/. Use one of "
            f"{sorted(p.name for p in _ARTIFACTS.glob('*.json'))}.",
        )
    path = _ARTIFACTS / name
    if not path.exists():
        raise ToolError(
            "UNKNOWN_RECEIPT",
            f"{name!r} is not in artifacts/. Available: "
            f"{sorted(p.name for p in _ARTIFACTS.glob('*.json'))}.",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    scalars: dict[str, Any] = {}
    lengths: dict[str, int] = {}
    for key, value in data.items() if isinstance(data, dict) else []:
        if isinstance(value, list | dict):
            lengths[key] = len(value)
        else:
            scalars[key] = value
    return {
        "receipt": name,
        "bytes": path.stat().st_size,
        "path": f"artifacts/{name}",
        "scalars": scalars,
        "collection_sizes": lengths,
    }


TOOLS: dict[str, dict[str, Any]] = {
    "queue_top": {
        "handler": tool_queue_top,
        "description": (
            "The top of the physics-conditioned review queue, in rank order, with the "
            "reason code that flagged each observation."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_QUEUE_LIMIT,
                    "description": f"How many rows. Capped at {MAX_QUEUE_LIMIT}.",
                }
            },
            "additionalProperties": False,
        },
    },
    "observation": {
        "handler": tool_observation,
        "description": (
            "Every measured field for one observation, and the reviewer note that shipped "
            "for it, including whether a generated draft was refused and why."
        ),
        "schema": {
            "type": "object",
            "properties": {"observation_id": {"type": "integer"}},
            "required": ["observation_id"],
            "additionalProperties": False,
        },
    },
    "check_claim": {
        "handler": tool_check_claim,
        "description": (
            "Check a sentence about one observation against its evidence packet. Returns "
            "GROUNDED or REFUSED with a violation code per problem. This is the same "
            "checker that decides whether this project's own generated notes ship."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "integer"},
                "text": {"type": "string"},
            },
            "required": ["observation_id", "text"],
            "additionalProperties": False,
        },
    },
    "gate_status": {
        "handler": tool_gate_status,
        "description": (
            "The kill gates and their verdicts, each read from the receipt rather than "
            "typed here, because a tally in a description is a number that can go stale."
        ),
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "receipt": {
        "handler": tool_receipt,
        "description": (
            "The scalar summary of one receipt under artifacts/, with the size of each "
            "collection it holds. Never the whole file."
        ),
        "schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# The transport
# ---------------------------------------------------------------------------


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC request to one response, or None for a notification."""
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Read-only evidence from a physics-conditioned SatNOGS review queue. "
                "Every value is copied from a committed receipt. check_claim is the tool "
                "worth knowing about: it tells you whether a sentence you wrote about an "
                "observation is supported by that observation's own measured fields."
            ),
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
                for name, spec in TOOLS.items()
            ]
        }
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        spec = TOOLS.get(name)
        if spec is None:
            return _error_result(
                request_id,
                "UNKNOWN_TOOL",
                f"{name!r} is not a tool. Available: {sorted(TOOLS)}.",
            )
        try:
            payload = spec["handler"](**arguments)
        except ToolError as exc:
            return _error_result(request_id, exc.code, str(exc))
        except TypeError as exc:
            return _error_result(request_id, "BAD_ARGUMENTS", str(exc))
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


def serve(stdin: Any = None, stdout: Any = None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sink.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"parse error: {exc}"},
                    }
                )
                + "\n"
            )
            sink.flush()
            continue
        response = handle(request)
        if response is not None:
            sink.write(json.dumps(response) + "\n")
            sink.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
