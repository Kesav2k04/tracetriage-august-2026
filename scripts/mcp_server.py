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

The four measured kill gates are also published as MCP **resources**, ``receipt://GATE3``
through ``receipt://GATE6``, so a client that offers an ``@``-mention can pull a gate's
verdict and its receipt's scalars into a conversation without a tool call. Both resource
methods answered ``-32601`` until an IBM Bob operator tried it.

Five hard properties, each of which is a test in ``tests/test_mcp_server.py``.

**Read-only.** No tool writes, and the import closure of this file reaches no HTTP write
verb and no annotation store. One stated exception, because a claim with a hidden exception
is worth less than a narrower one: ``run_acceptance`` spawns ``scripts/gate.py``, which
calls every generator with ``--check`` and therefore rewrites no receipt, but which does run
``npm run build`` and so writes ``apps/web/.next``. That tool is read-only with respect to
SatNOGS and to every committed measurement, and it is not read-only with respect to the
working tree. It is the one tool left out of ``alwaysAllow`` in ``.bob/mcp.json``.

**Offline.** Every answer comes from a committed file. This file makes no network call, and
the server refuses to start if a file it advertises is missing rather than returning an empty
result that reads like an answer. ``run_acceptance`` is offline too but for a different
reason: it runs the offline test selection and the console build, neither of which reaches
out, rather than being a read of a committed file.

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
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage import mcp_transport as _transport  # noqa: E402
from pipeline.tracetriage.explain import (  # noqa: E402
    MeasurementMissing,
    build_packet,
    verify_note,
)
from pipeline.tracetriage.mcp_transport import (  # noqa: E402
    ToolError,
)
from pipeline.tracetriage.mcp_transport import handle as _handle  # noqa: E402
from pipeline.tracetriage.mcp_transport import serve as _serve  # noqa: E402

_DATA = REPO / "apps" / "web" / "public" / "data"
_ARTIFACTS = REPO / "artifacts"

def _data_dir() -> Path:
    """Read at call time rather than captured, so a test can redirect it."""
    return _DATA


#: The protocol version the transport answers with. Re-exported rather than redeclared:
#: two copies of a version string is one of them going stale, and this server's tests
#: assert the handshake against this name.
PROTOCOL_VERSION = _transport.PROTOCOL_VERSION

#: What a client is told this server is for, in the initialize response.
INSTRUCTIONS = (
    "Read-only evidence from a physics-conditioned SatNOGS review queue. Every value "
    "is copied from a committed receipt. check_claim is the tool worth knowing about: "
    "it tells you whether a sentence you wrote about an observation is supported by "
    "that observation's own measured fields. For a sentence about an observation you "
    "measured just now rather than one from this checkout, use live_check_claim on the "
    "tracetriage-live server: check_claim answers UNKNOWN_OBSERVATION for an id that is "
    "not in the committed data, and that is correct rather than a gap. The four measured "
    "kill gates are also readable as resources, receipt://GATE3 to receipt://GATE6. "
    "NOT_ESTABLISHED and OPEN are verdicts, not gaps to fill in: do not report either as "
    "met."
)


SERVER_NAME = "tracetriage-evidence"
SERVER_VERSION = "1.0.0"

#: A queue of four hundred entries answered in full would fill a context window with rows
#: nobody reads. Fifty is the review budget the queue was scored against, so it is the
#: largest answer that corresponds to a decision anyone made.
MAX_QUEUE_LIMIT = 50
DEFAULT_QUEUE_LIMIT = 10


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
    """Every observation an agent can ask about, which is every card with a fit.

    Cards shipped with a named degrade have no corridor and therefore no packet. They
    are absent from this map rather than present with zeros, so a tool that answers
    from it cannot report an unmeasured observation as measured. :func:`_unmeasured`
    carries the reason so the tool can say which of the two it is.
    """
    cards = _load(_data_dir() / "cards.json")["cards"]
    entries = _load(_data_dir() / "queue.json")["entries"]
    by_id = {int(e["obs_id"]): e for e in entries}
    out: dict[int, Any] = {}
    for c in cards:
        obs_id = int(c["obs_id"])
        if obs_id not in by_id:
            continue
        try:
            out[obs_id] = build_packet(c, by_id[obs_id])
        except MeasurementMissing:
            continue
    return out


def _unmeasured() -> dict[int, str]:
    """Shipped observations with no fit, mapped to the reason the console prints."""
    cards = _load(_data_dir() / "cards.json")["cards"]
    return {
        int(c["obs_id"]): str(c.get("degraded") or "no corridor fit was recorded")
        for c in cards
        if not (c.get("corridor") or {}).get("fitted_offset_hz")
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
            f"Three counts here are different numbers and answering the wrong one is the "
            f"mistake this string exists to stop. `available` is how many observations the "
            f"queue ranks in total, which is the answer to 'how long is the queue'. `cap` "
            f"is the most rows one call may return ({MAX_QUEUE_LIMIT}) and is a property of "
            f"this tool, not of the queue. `review_budget.n_observations` is the budget the "
            f"ranking was scored against and happens to equal the cap, which is exactly why "
            f"it gets misread. `returned` is how many rows are in this response. Use "
            f"queue_size if the total is all you want. "
            f"Rank is the order a reviewer should spend a fixed budget in. A row with "
            f"has_evidence_packet false is ranked but carries no imagery in this checkout, "
            f"so observation and check_claim refuse it. The queue's headline lift over "
            f"random is NOT_ESTABLISHED against its 1.5x threshold: the point estimate is "
            f"above it and the interval contains it. See gate_status."
        ),
    }


def tool_queue_size() -> dict[str, Any]:
    """The three counts `queue_top` reports, with nothing else to confuse them with.

    An agent asked how many rows the queue ranks answered 50, which is the review budget
    and the per-call cap, not the queue length. It had read `queue_top`'s payload correctly
    and picked the wrong field out of it. A caller that wants only the total should not have
    to fetch fifty rows and then choose between three integers, and asking for 407 rows was
    refused with BAD_LIMIT, which reads like the number is unavailable.
    """
    queue = _load(_data_dir() / "queue.json")
    return {
        "available": len(queue["entries"]),
        "cap": MAX_QUEUE_LIMIT,
        "review_budget": queue["review_budget"],
        "reading": (
            "`available` is the queue length: how many observations the ranking covers. "
            "`cap` is how many rows queue_top will return in one call. "
            "`review_budget.n_observations` is the fixed budget the ranking was scored "
            "against. If the question was how many ranked rows there are, the answer is "
            "`available`."
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


# ---------------------------------------------------------------------------
# The acceptance gate, as a tool
# ---------------------------------------------------------------------------

#: Where the standing gates live, and the interpreter they were written for. `gate.py`
#: hardcodes `.venv/Scripts/python.exe` for the checks it spawns, so running it under a
#: different interpreter would report on an environment nobody uses.
_GATE = REPO / "scripts" / "gate.py"
_GATE_PY = REPO / ".venv" / "Scripts" / "python.exe"

#: How long one acceptance run may take. `gate.py` runs the offline suite, ruff, three npm
#: commands and nine `--check` regenerations, and the measured wall time on the build machine
#: is minutes rather than seconds. A tool that hangs a client forever is worse than one that
#: says it ran out of time, so the cap is stated and the timeout is a named reason.
GATE_TIMEOUT_S = 900

#: `gate.py` prints one line per check in exactly this shape. Parsed rather than re-derived,
#: because re-deriving the verdicts here would be a second acceptance script.
_GATE_LINE = re.compile(r"^\s*\[(PASS|FAIL| -- )\]\s+(.+?)(?:\s\s+(.*))?$")
# Anchored on the count and not on the end of the line. The gate's tally now appends how
# many rows it could not ask and why, and `$` here would have returned None for exactly the
# runs where that suffix exists, reporting no tally at all on a machine missing a
# precondition. The suffix is kept, because it is the half of the line that says the count
# is over the rows that ran.
_GATE_TALLY = re.compile(r"^(\d+)/(\d+) standing gates pass.*", re.M)


def summarise_gate_output(stdout: str, returncode: int) -> dict[str, Any]:
    """`gate.py`'s printed report as structured rows, and nothing else from it.

    Bounded on purpose: the gate's own output carries the tail of a pytest run and of three
    npm commands, and returning all of it would spend a client's context on lines it did not
    ask for. What comes back is the verdict per check and the tally, which is what "do the
    standing gates pass" actually means.

    An omitted row (`[ -- ]`) is kept as OMITTED rather than folded into either side. The
    gate prints one when a check cannot be asked in the current context, and a "could not
    measure" counted as a failure manufactures a regression.
    """
    checks: list[dict[str, str]] = []
    for line in stdout.splitlines():
        found = _GATE_LINE.match(line)
        if not found:
            continue
        verdict, name, detail = found.groups()
        checks.append(
            {
                "check": name.strip(),
                "verdict": {"PASS": "PASS", "FAIL": "FAIL", " -- ": "OMITTED"}[verdict],
                "detail": (detail or "").strip(),
            }
        )
    tally = _GATE_TALLY.search(stdout)
    return {
        "exit_code": returncode,
        "all_gates_pass": returncode == 0,
        "n_pass": sum(1 for c in checks if c["verdict"] == "PASS"),
        "n_fail": sum(1 for c in checks if c["verdict"] == "FAIL"),
        "n_omitted": sum(1 for c in checks if c["verdict"] == "OMITTED"),
        "reported_tally": tally.group(0) if tally else None,
        "checks": checks,
    }


def tool_run_acceptance() -> dict[str, Any]:
    """Run this repository's own standing gates and report the verdict per check.

    The one tool here that computes rather than reads. It exists because "are the standing
    gates green" is the question an agent operating this repository asks first, and the
    honest answer is a run rather than a receipt: a receipt says what was true when someone
    last ran it.

    Read-only with one stated exception, because a claim with a hidden exception is worse
    than a narrower claim. Nothing in this file writes. `gate.py` calls every generator with
    `--check`, so no receipt under `artifacts/` is rewritten. What it does do is run
    `npm run build` in `apps/web`, and that writes the console's build output under
    `apps/web/.next`. So this tool is read-only with respect to SatNOGS and to every
    committed measurement, and it is not read-only with respect to the working tree. It is
    the one tool left out of `alwaysAllow` in `.bob/mcp.json` for that reason.
    """
    if not _GATE_PY.exists():
        raise ToolError(
            "NO_INTERPRETER",
            f"{_relative(_GATE_PY)} is not in this checkout, and scripts/gate.py spawns "
            f"every check with it by name. Create the environment first "
            f"(py -m venv .venv, then .venv\\Scripts\\python.exe -m pip install -e "
            f'".[full,dev]"). Reporting a gate result from a different interpreter would '
            f"describe an environment nobody runs.",
        )
    try:
        finished = subprocess.run(  # noqa: S603
            [str(_GATE_PY), str(_GATE)],
            cwd=REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GATE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(
            "GATE_TIMED_OUT",
            f"scripts/gate.py did not finish within {GATE_TIMEOUT_S} s. A partial gate is "
            f"not a verdict, so nothing is reported. Run it in a terminal to see where it "
            f"stopped: {_relative(_GATE_PY)} scripts/gate.py",
        ) from exc

    summary = summarise_gate_output(finished.stdout or "", finished.returncode)
    if not summary["checks"]:
        raise ToolError(
            "GATE_UNREADABLE",
            f"scripts/gate.py exited {finished.returncode} and printed no check line this "
            f"tool could read, so there is no verdict to report. An empty pass would be the "
            f"worst answer available here. Last stderr line: "
            f"{(finished.stderr or '').strip().splitlines()[-1:] or ['(none)']}",
        )
    summary["command"] = f"{_relative(_GATE_PY)} scripts/gate.py"
    summary["reading"] = (
        "One row per standing gate, as scripts/gate.py printed it. all_gates_pass is that "
        "script's own exit code and not a tally computed here. OMITTED is a check the gate "
        "declined to ask in this context and is neither a pass nor a failure. This tool "
        "runs the gate rather than reading a receipt, so it also writes apps/web/.next by "
        "way of the console build; nothing under artifacts/ is rewritten, because every "
        "generator the gate calls runs with --check."
    )
    return summary


# ---------------------------------------------------------------------------
# The gate receipts, as readable resources
# ---------------------------------------------------------------------------


def _gate_rows() -> list[dict[str, Any]]:
    return _load(_data_dir() / "provenance.json")["gate_summary"]["gates"]


def gate_resource_text(gate: int) -> str:
    """One gate as a short block: its title, its verdict, and its receipt's scalars.

    Bounded for the same reason `receipt` is bounded. GATE6's own receipt is 250 kB and a
    client that `@`-mentioned it would spend its context on bootstrap draws.

    Everything here is read from the receipt or from the gate summary. Nothing is typed,
    including the verdict, so this cannot be the place a `NOT_ESTABLISHED` quietly becomes
    something else.
    """
    rows = {int(row["gate"]): row for row in _gate_rows()}
    row = rows.get(gate)
    if row is None:
        raise ToolError(
            "UNKNOWN_GATE",
            f"gate {gate} is not one of the {len(rows)} this project defines: "
            f"{sorted(rows)}.",
        )
    lines = [
        f"gate {row['gate']}: {row['title']}",
        f"verdict   {row['verdict']}",
        f"decided in {row['decided_in']}",
    ]
    decided_in = str(row["decided_in"])
    if decided_in.startswith("artifacts/") and decided_in.endswith(".json"):
        summary = tool_receipt(Path(decided_in).name)
        lines.append(f"receipt   {summary['path']}  {summary['bytes']} bytes")
        for key, value in summary["scalars"].items():
            lines.append(f"  {key}: {value}")
        for key, size in summary["collection_sizes"].items():
            lines.append(f"  {key}: {size} entries")
    else:
        lines.append(
            f"receipt   none. This gate was decided in {decided_in}, which is a document "
            f"rather than a generated receipt."
        )
    lines.append(
        "reading   NOT_ESTABLISHED is a measurement that came back inconclusive: not a "
        "pass, not a failure. OPEN is a study that was never run. Neither may be reported "
        "as met."
    )
    return "\n".join(lines)


def _gate_resource(gate: int) -> dict[str, Any]:
    return {
        "name": f"GATE{gate}",
        "description": (
            f"Kill gate {gate}: its title, its verdict and the scalar summary of the "
            f"receipt it was decided in. Bounded, never the whole receipt."
        ),
        "mimeType": "text/plain",
        "handler": lambda gate=gate: gate_resource_text(gate),
    }


#: The four gates this project decided by measurement. Gates 1 and 2 were pre-passed in
#: `docs/KILL_GATE.md` and have no receipt, so a URI for them would resolve to a document
#: this server does not publish and `gate_status` already reports them.
RESOURCE_GATES = (3, 4, 5, 6)

RESOURCES: dict[str, dict[str, Any]] = {
    f"receipt://GATE{gate}": _gate_resource(gate) for gate in RESOURCE_GATES
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
    "queue_size": {
        "handler": tool_queue_size,
        "description": (
            "How many observations the queue ranks in total, named apart from the per-call "
            "cap and the review budget. Ask this rather than queue_top when the total is "
            "the whole question: the three numbers are different and two of them are 50."
        ),
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "run_acceptance": {
        "handler": tool_run_acceptance,
        "description": (
            "Run this repository's standing gates (scripts/gate.py) and report the verdict "
            "per check plus the tally. The one tool here that computes rather than reads, "
            "so it takes minutes, and the one that is not read-only with respect to the "
            "working tree: the gate builds the console. Nothing under artifacts/ is "
            "rewritten, because every generator the gate calls runs with --check."
        ),
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
}


# ---------------------------------------------------------------------------
# The transport
# ---------------------------------------------------------------------------


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
    """Which advertised evidence files are absent, as repository-relative paths.

    One entry per file, because a caller that wants to act on this needs the list rather
    than a sentence. The sentence is `_offline_preflight`'s job.
    """
    return [
        _relative(_data_dir() / name)
        for name in REQUIRED_EVIDENCE
        if not (_data_dir() / name).exists()
    ]


def _offline_preflight() -> list[str]:
    """This server's own precondition, with its own remedy attached.

    `serve` takes a preflight because the live server has a different one to state: it
    advertises no committed file, and what it needs is an import that may not be installed.
    The remedy belongs to the check rather than to the printer, or the offline server's
    "run build_console_data.py" would appear under whichever server failed to start.
    """
    absent = missing_evidence()
    if not absent:
        return []
    return [
        ", ".join(absent)
        + " is missing (run scripts/build_console_data.py and scripts/run_explanations.py)"
    ]


# ---------------------------------------------------------------------------
# The transport, which this file no longer implements
# ---------------------------------------------------------------------------
#
# `handle` and `serve` moved to `pipeline/tracetriage/mcp_transport.py` so that the live
# server can speak the same JSON-RPC without a second copy of the batch handling, the
# notification rule and the six named error paths, each of which is here because an input
# ended a session once. The move was forced by packaging: an install of this package
# ships the package and not `scripts/`, so a dispatcher living here could not be reached
# by an installed entry point.
#
# What did NOT move is anything that makes this server this server. The tool registry, the
# handlers, the evidence preflight and the identity below are all still local, and the
# read-only and offline claims are claims about THIS file's imports and call sites, which
# `tests/test_mcp_server.py` still scans. The transport is scanned as well now, because a
# writer that moved out of the scanned file would otherwise have left the scan passing over
# nothing.


def handle(request: Any) -> dict[str, Any] | None:
    """This server's registry, over the shared transport."""
    return _handle(request, TOOLS, {"name": SERVER_NAME, "version": SERVER_VERSION},
                   INSTRUCTIONS, RESOURCES)


def serve(stdin: Any = None, stdout: Any = None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout.

    Refuses to start when an advertised evidence file is missing, because a client that has
    completed a handshake and read a tool list has been told those tools work.
    """
    return _serve(
        stdin=stdin,
        stdout=stdout,
        tools=TOOLS,
        server_info={"name": SERVER_NAME, "version": SERVER_VERSION},
        instructions=INSTRUCTIONS,
        preflight=_offline_preflight,
        resources=RESOURCES,
    )


if __name__ == "__main__":
    raise SystemExit(serve())
