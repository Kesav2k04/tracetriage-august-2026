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

#: A queue of four hundred entries answered in full would fill a context window with rows
#: nobody reads. Fifty is the review budget the queue was scored against, so it is the
#: largest answer that corresponds to a decision anyone made.
MAX_QUEUE_LIMIT = 50
DEFAULT_QUEUE_LIMIT = 10


class ToolError(Exception):
    """A tool call that cannot be answered, carrying the reason code it failed with."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _relative(path: Path) -> str:
    """The path as a reader would type it, and never an absolute path from this host.

    ``relative_to`` raises for a path that is not under the repository, which is what a
    redirected data directory produces, so this has to survive it rather than turn a named
    reason into a traceback. The fallback used to be the whole path, which put a host
    filesystem path into a message a client receives.
    """
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return f"{path.name} (outside this checkout)"


def _as_int(value: Any, field: str) -> int:
    """An integer argument, or a named reason instead of a traceback.

    ``int(value)`` raised ValueError on the likeliest mistake an agent makes, passing an id
    as a string, and that exception escaped the tool arm and killed the session. A bool is
    refused too: ``isinstance(True, int)`` is true in Python and the schema says integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        # The hint is built from the value, because a fixed example belongs to whichever
        # field it was written for and reads as noise under every other one.
        digits = isinstance(value, str) and value.strip().lstrip("-").isdigit()
        hint = f" Pass {value.strip()} rather than {value!r}." if digits else ""
        raise ToolError(
            "BAD_ARGUMENTS",
            f"{field} must be an integer and not {type(value).__name__} {value!r}.{hint}",
        )
    return value


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
    """The top of the review queue, in rank order, with the reason each row was flagged.

    Each row says whether the other tools can answer about it. The queue is the whole
    ranking and only the observations the console ships imagery for have an evidence packet,
    so roughly half the top fifty had no packet while the refusal message pointed the client
    back here. A flag per row costs one field and removes the round trip.
    """
    limit = _as_int(limit, "limit")
    if limit < 1:
        raise ToolError("BAD_LIMIT", f"limit must be at least 1, got {limit}.")
    if limit > MAX_QUEUE_LIMIT:
        raise ToolError(
            "BAD_LIMIT",
            f"limit must be at most {MAX_QUEUE_LIMIT}, which is what the schema advertises "
            f"and what the review budget was scored against. Asked for {limit}.",
        )
    queue = _load(_data_dir() / "queue.json")
    with_packets = {int(c["obs_id"]) for c in _load(_data_dir() / "cards.json")["cards"]}
    rows = sorted(queue["entries"], key=lambda e: e["rank"])[:limit]
    return {
        "review_budget": queue["review_budget"],
        "returned": len(rows),
        "available": len(queue["entries"]),
        "cap": MAX_QUEUE_LIMIT,
        "with_evidence_packet": sum(1 for r in rows if int(r["obs_id"]) in with_packets),
        "entries": [
            {
                "obs_id": r["obs_id"],
                "rank": r["rank"],
                "score": r["score"],
                "reasons": r["reasons"],
                "is_conflict": r["is_conflict"],
                "network_label": r["waterfall_status"],
                "model_probability": r["model_prob"],
                "has_evidence_packet": int(r["obs_id"]) in with_packets,
            }
            for r in rows
        ],
        "reading": (
            "Rank is the order a reviewer should spend a fixed budget in. A row with "
            "has_evidence_packet false is ranked but carries no imagery in this checkout, "
            "so observation and check_claim refuse it. The queue's headline lift over "
            "random is NOT_ESTABLISHED against its 1.5x threshold: the point estimate is "
            "above it and the interval contains it. See gate_status."
        ),
    }


def tool_observation(observation_id: int) -> dict[str, Any]:
    """Every field a note about this observation is allowed to use, and the note itself."""
    observation_id = _as_int(observation_id, "observation_id")
    packets = _packets()
    packet = packets.get(observation_id)
    if packet is None:
        raise ToolError(
            "UNKNOWN_OBSERVATION",
            f"{observation_id} is not one of the {len(packets)} observations this "
            f"checkout carries imagery and a queue row for. queue_top marks every row "
            f"with has_evidence_packet, and only those ids answer here.",
        )
    notes = {int(n["obs_id"]): n for n in _load(_data_dir() / "notes.json")["notes"]}
    note = notes.get(observation_id)
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
    observation_id = _as_int(observation_id, "observation_id")
    packets = _packets()
    packet = packets.get(observation_id)
    if packet is None:
        raise ToolError(
            "UNKNOWN_OBSERVATION",
            f"{observation_id} is not one of the {len(packets)} observations this "
            f"checkout carries a packet for. queue_top marks every row with "
            f"has_evidence_packet, and only those ids answer here.",
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
    # Containment, not a blocklist. The blocklist rejected a separator and a parent
    # reference and let "C:foo.json" through, which is drive-relative on Windows and
    # resolves outside the repository entirely. Asking where the path actually landed is
    # the only version of this check that does not need a list of tricks.
    if not isinstance(name, str) or not name or name != Path(name).name:
        raise ToolError(
            "BAD_RECEIPT_NAME",
            f"{name!r} is not a bare filename under artifacts/. Use one of "
            f"{sorted(p.name for p in _ARTIFACTS.glob('*.json'))}.",
        )
    path = _ARTIFACTS / name
    if path.resolve().parent != _ARTIFACTS.resolve():
        raise ToolError(
            "BAD_RECEIPT_NAME",
            f"{name!r} resolves outside artifacts/, so it is not a receipt this server "
            f"publishes.",
        )
    if not path.exists():
        raise ToolError(
            "UNKNOWN_RECEIPT",
            f"{name!r} is not in artifacts/. Available: "
            f"{sorted(p.name for p in _ARTIFACTS.glob('*.json'))}.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError(
            "UNSUMMARISABLE_RECEIPT",
            f"artifacts/{name} could not be read as JSON: {type(exc).__name__}. A summary "
            f"of nothing would read as a receipt with no contents.",
        ) from exc

    scalars: dict[str, Any] = {}
    lengths: dict[str, int] = {}
    if isinstance(data, dict):
        root = "object"
        for key, value in data.items():
            if isinstance(value, list | dict):
                lengths[key] = len(value)
            else:
                scalars[key] = value
    elif isinstance(data, list):
        # artifacts/LEAKAGE_AUDIT.json is list-rooted, and the dict-only version of this
        # returned two empty objects with isError false: the empty answer that reads like a
        # measurement, on the audit least able to afford one.
        root = "list"
        lengths["<root>"] = len(data)
        row_fields = sorted({k for row in data if isinstance(row, dict) for k in row})
        if row_fields:
            scalars["row_fields"] = row_fields
    else:
        raise ToolError(
            "UNSUMMARISABLE_RECEIPT",
            f"artifacts/{name} holds a bare {type(data).__name__} at its root, which has "
            f"no fields and no collections to report.",
        )
    return {
        "receipt": name,
        "bytes": path.stat().st_size,
        "path": f"artifacts/{name}",
        "root": root,
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
                    "description": f"How many rows, at most {MAX_QUEUE_LIMIT}. More than "
                    f"that is refused rather than silently truncated, so a validating "
                    f"client and this handler agree about what is legal.",
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


def _scrubbed(exc: Exception) -> str:
    """An exception message with this checkout's path removed.

    Exceptions from the filesystem carry absolute paths, and this message goes to a client.

    Split and join rather than ``str.replace``, because the read-only scan in
    ``tests/test_mcp_server.py`` counts ``replace`` as a filesystem move, and a scan with an
    exception for one receiver is a scan with a hole. One awkward line here is cheaper than
    that.
    """
    return f"{type(exc).__name__}: {'<repo>'.join(str(exc).split(str(REPO)))}"


def _invalid_request(detail: str, request_id: Any = None) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32600, "message": f"invalid request: {detail}"},
    }


def handle(request: Any) -> dict[str, Any] | None:
    """One JSON-RPC request to one response, or None for a notification.

    A frame that is not an object gets an invalid-request error rather than an
    AttributeError. Parsing succeeded for ``5``, ``null`` and a batch array, so the parse
    error branch never saw them and ``.get`` on a list ended the session.
    """
    if not isinstance(request, dict):
        return _invalid_request(f"a JSON-RPC request is an object, got {type(request).__name__}")
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


#: The files every advertised tool needs. Checked once at startup, because a server that
#: answers tools/list and then fails every call has told the client it can do something it
#: cannot.
REQUIRED_EVIDENCE = (
    "queue.json",
    "cards.json",
    "notes.json",
    "provenance.json",
)


def missing_evidence() -> list[str]:
    """Which advertised evidence files are absent, as repository-relative paths."""
    return [
        _relative(_data_dir() / name)
        for name in REQUIRED_EVIDENCE
        if not (_data_dir() / name).exists()
    ]


def serve(stdin: Any = None, stdout: Any = None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout.

    Refuses to start when an advertised evidence file is missing. The docstring at the top
    of this file claimed that behaviour before it existed: what was implemented was a
    per-call reason code, which is weaker, because a client that has completed a handshake
    and read a tool list has been told those tools work.
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout

    absent = missing_evidence()
    if absent:
        print(
            "tracetriage-evidence cannot start: "
            + ", ".join(absent)
            + " is missing. Run scripts/build_console_data.py and "
            "scripts/run_explanations.py; answering with an empty payload would read as a "
            "measurement.",
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
            replies = [r for r in (handle(item) for item in request) if r is not None]
            if replies:
                _write(sink, replies)
            continue

        response = handle(request)
        if response is not None:
            _write(sink, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
