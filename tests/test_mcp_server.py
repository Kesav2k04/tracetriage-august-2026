"""The evidence server, driven through its own transport (unit E3).

Calling the handler functions directly would test the tools and not the server. A client
speaks newline-delimited JSON-RPC on a pipe, so most of these run the real
``initialize`` / ``tools/list`` / ``tools/call`` sequence through :func:`serve` with string
buffers, which is the same code path a subprocess client takes.

The properties worth pinning are the ones a client cannot check for itself: that no tool
writes, that no answer needs the network, that a failure comes back as a named reason rather
than as an empty result that reads like an answer, and that a tool cannot be persuaded to
return a quarter of a megabyte.
"""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.mcp_server import (
    MAX_QUEUE_LIMIT,
    PROTOCOL_VERSION,
    SERVER_NAME,
    TOOLS,
    ToolError,
    handle,
    serve,
    tool_check_claim,
    tool_gate_status,
    tool_observation,
    tool_queue_top,
    tool_receipt,
)

REPO = Path(__file__).resolve().parents[1]
_SERVER = REPO / "scripts" / "mcp_server.py"
_REGISTRATION = REPO / ".bob" / "mcp.json"
_SPECIFICATION = REPO / ".bob" / "TOOL_SPECS.md"

#: The two ways this file could stop being read-only.
_NETWORK_WRITES = frozenset({"post", "put", "patch", "delete", "request", "stream"})
_DISK_WRITES = frozenset({"write_text", "write_bytes", "unlink", "mkdir", "rmdir"})


def _call(name: str, arguments: dict | None = None) -> dict:
    """One tools/call through the handler, with the payload decoded."""
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    assert response is not None
    result = response["result"]
    return {
        "isError": result["isError"],
        "payload": json.loads(result["content"][0]["text"]),
    }


def _drive(requests: list[dict]) -> list[dict]:
    """Run a whole conversation through the transport, as a client would."""
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    assert serve(stdin=stdin, stdout=stdout) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The protocol
# ---------------------------------------------------------------------------


def test_the_handshake_and_the_tool_list_come_back_over_the_transport():
    responses = _drive(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )
    # The notification gets no response, which is what makes it a notification.
    assert [r["id"] for r in responses] == [1, 2]
    assert responses[0]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert responses[0]["result"]["capabilities"]["tools"] == {}

    listed = {t["name"] for t in responses[1]["result"]["tools"]}
    assert listed == set(TOOLS)
    for tool in responses[1]["result"]["tools"]:
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"
        # A schema that accepts anything is not a schema. Every tool closes its object.
        assert tool["inputSchema"]["additionalProperties"] is False


def test_a_malformed_line_is_a_parse_error_and_the_server_keeps_going():
    stdin = io.StringIO('not json\n{"jsonrpc": "2.0", "id": 7, "method": "tools/list"}\n')
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 7, "one bad frame must not end the session"


def test_an_unimplemented_method_is_a_protocol_error_not_a_tool_result():
    response = handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert response is not None
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Every failure has a named reason
# ---------------------------------------------------------------------------


def test_an_unknown_tool_is_a_tool_error_with_a_reason():
    out = _call("does_not_exist")
    assert out["isError"] is True
    assert out["payload"]["reason"] == "UNKNOWN_TOOL"


def test_an_unknown_observation_is_a_reason_and_not_an_empty_payload():
    for name in ("observation", "check_claim"):
        arguments = {"observation_id": 1}
        if name == "check_claim":
            arguments["text"] = "anything"
        out = _call(name, arguments)
        assert out["isError"] is True, name
        assert out["payload"]["reason"] == "UNKNOWN_OBSERVATION", name


def test_bad_arguments_are_named_rather_than_raised():
    assert _call("queue_top", {"limit": 0})["payload"]["reason"] == "BAD_LIMIT"
    assert _call("queue_top", {"limit": "ten"})["payload"]["reason"] == "BAD_LIMIT"
    assert _call("check_claim", {"observation_id": 1, "text": "  "})["payload"][
        "reason"
    ] == "EMPTY_CLAIM"
    assert _call("queue_top", {"nonsense": 1})["payload"]["reason"] == "BAD_ARGUMENTS"


def test_a_receipt_name_cannot_escape_the_artifacts_directory():
    for bad in ("../pyproject.toml", "sub/dir.json", "..\\secrets.json"):
        out = _call("receipt", {"name": bad})
        assert out["isError"] is True, bad
        assert out["payload"]["reason"] == "BAD_RECEIPT_NAME", bad
    out = _call("receipt", {"name": "NOT_A_RECEIPT.json"})
    assert out["payload"]["reason"] == "UNKNOWN_RECEIPT"


# ---------------------------------------------------------------------------
# The answers come from the receipts
# ---------------------------------------------------------------------------


def test_the_queue_comes_back_in_rank_order_and_capped():
    out = tool_queue_top(3)
    assert [e["rank"] for e in out["entries"]] == [1, 2, 3]
    assert out["capped_at"] is None
    big = tool_queue_top(MAX_QUEUE_LIMIT + 25)
    assert big["returned"] <= MAX_QUEUE_LIMIT
    assert big["capped_at"] == MAX_QUEUE_LIMIT, (
        "a client that asks for everything has to be told it did not get everything"
    )


def test_an_observation_carries_its_packet_and_the_note_that_shipped():
    obs_id = tool_queue_top(1)["entries"][0]["obs_id"]
    out = tool_observation(obs_id)
    assert out["observation_id"] == obs_id
    assert len(out["evidence_packet_sha256"]) == 64
    for field in ("network_label", "model_probability", "queue_rank", "fitted_offset_hz"):
        assert field in out["evidence_packet"]
    note = out["note"]
    assert note is not None
    assert note["source"] in {"generated", "deterministic"}
    if note["source"] == "generated":
        assert note["refused_codes"] == []


def test_check_claim_agrees_with_the_checker_that_ships_the_notes():
    """The tool has to be the checker, not a second implementation of it."""
    obs_id = tool_queue_top(1)["entries"][0]["obs_id"]
    packet_fields = tool_observation(obs_id)["evidence_packet"]

    grounded = (
        f"The network label is {packet_fields['network_label']} and the model probability "
        f"is {packet_fields['model_probability']}. Look along the predicted corridor."
    )
    assert tool_check_claim(obs_id, grounded)["verdict"] == "GROUNDED"

    invented = "The corridor sits 987654 Hz from the catalogue centre."
    refused = tool_check_claim(obs_id, invented)
    assert refused["verdict"] == "REFUSED"
    assert "UNGROUNDED_NUMBER" in refused["codes"]
    assert refused["violations"], "a refusal has to say what was wrong with it"


def test_the_gate_status_is_the_receipt_and_not_a_typed_tally():
    out = tool_gate_status()
    assert out["n_gates"] == len(out["gates"])
    met = sum(1 for g in out["gates"] if g["verdict"] in {"PASSED", "PRE_PASSED"})
    assert out["n_met"] == met, (
        "the count and the verdicts come from the same receipt, so a disagreement means "
        "one of them was typed"
    )


def test_a_receipt_summary_is_a_summary():
    out = tool_receipt("QUEUE_RECEIPT.json")
    assert out["bytes"] > 100_000, "the point of this tool is that the file is large"
    rendered = len(json.dumps(out))
    assert rendered < 8_000, f"the summary rendered to {rendered} characters"
    assert out["collection_sizes"]["queue"] > 100
    assert out["path"] == "artifacts/QUEUE_RECEIPT.json"


def test_a_missing_evidence_file_is_a_named_reason(monkeypatch, tmp_path):
    """An empty answer would read as a measurement, so absence has to be a reason code."""
    import scripts.mcp_server as server

    monkeypatch.setattr(server, "_DATA", tmp_path)
    with pytest.raises(ToolError) as caught:
        server.tool_queue_top(1)
    assert caught.value.code == "EVIDENCE_FILE_MISSING"


# ---------------------------------------------------------------------------
# Read-only, and offline
# ---------------------------------------------------------------------------


def test_the_server_holds_no_write_verb_and_no_network_import():
    """The capability claim, checked against the source rather than the documentation."""
    tree = ast.parse(_SERVER.read_text(encoding="utf-8"), filename=str(_SERVER))
    imports: set[str] = set()
    writes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif (
            # Both kinds of write: to the network, and to disk. A read-only server does
            # neither, and naming them together keeps the failure message readable.
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _NETWORK_WRITES | _DISK_WRITES
        ):
            writes.append(f"line {node.lineno}: .{node.func.attr}()")

    assert not writes, f"the read-only server writes: {writes}"
    offenders = sorted(
        m for m in imports if m.split(".")[0] in {"httpx", "requests", "socket", "urllib"}
    )
    assert not offenders, f"the offline server imports {offenders}"
    # It must reach the checker, or check_claim would be a second implementation.
    assert any("explain" in m for m in imports), sorted(imports)
    assert not any("granite" in m for m in imports), (
        "the server must not import the module that can POST"
    )


def test_every_tool_has_a_handler_and_a_closed_schema():
    for name, spec in TOOLS.items():
        assert callable(spec["handler"]), name
        assert spec["schema"]["additionalProperties"] is False, name
        required = spec["schema"].get("required", [])
        properties = spec["schema"]["properties"]
        for field in required:
            assert field in properties, f"{name} requires {field} and does not declare it"


def test_the_server_answers_under_an_interpreter_with_no_installed_packages():
    """The dependency claim, run rather than argued.

    ``.bob/mcp.json`` tells a reader that any Python 3.11 or newer answers this server,
    which is only true if the import closure is standard library and this repository. The
    ``-S`` flag drops site-packages and ``-E`` drops the ambient environment, so if anything
    outside the standard library had crept into the closure the handshake would raise here
    while still passing every other test in this file.
    """
    conversation = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        + "\n"
    )
    finished = subprocess.run(
        [sys.executable, "-S", "-E", str(_SERVER)],
        input=conversation,
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    responses = [json.loads(line) for line in finished.stdout.splitlines() if line.strip()]
    assert responses[0]["result"]["serverInfo"]["name"] == SERVER_NAME
    assert {t["name"] for t in responses[1]["result"]["tools"]} == set(TOOLS)


# ---------------------------------------------------------------------------
# The registration and the specification are claims about this server
# ---------------------------------------------------------------------------


def _tracked(path: Path) -> bool:
    """Whether git publishes this path. Staged counts, because the index is what ships."""
    finished = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path.relative_to(REPO).as_posix())],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return finished.returncode == 0


def test_the_registration_names_the_server_that_exists():
    """A config pointing at a module nobody wrote is worse than no config.

    This is the failure the first version of this file had: the registration named
    ``tracetriage.mcp_server``, which never existed, so an agent that trusted it got an
    import error and a reader who trusted it got a false impression of what was built.
    """
    registered = json.loads(_REGISTRATION.read_text(encoding="utf-8"))["mcpServers"]
    assert len(registered) == 1, f"one server is registered, found {sorted(registered)}"
    name, spec = next(iter(registered.items()))
    assert name == SERVER_NAME, (
        f"the config calls it {name!r} and the server calls itself {SERVER_NAME!r}"
    )

    scripts = [arg for arg in spec["args"] if arg.endswith(".py")]
    assert len(scripts) == 1, spec["args"]
    assert (REPO / scripts[0]).resolve() == _SERVER, scripts
    assert _tracked(REPO / scripts[0]), "an unpublished server cannot be launched by a judge"

    # An interpreter named by absolute path resolves on exactly one machine, and this file
    # is public. A bare name is what a reader on another platform can satisfy.
    command = spec["command"]
    assert "/" not in command and "\\" not in command, (
        f"{command!r} is a path from one machine, so the registration is broken for "
        f"everyone else who reads it"
    )


def test_the_registration_declares_no_environment_the_server_ignores():
    """Checked in both directions, because either half alone permits a false statement.

    A declared variable the server never reads tells a reader the behaviour is
    configurable when it is not. A variable the server reads and the config omits leaves
    the launch depending on whatever the client happened to export.
    """
    spec = next(iter(json.loads(_REGISTRATION.read_text(encoding="utf-8"))["mcpServers"].values()))
    source = _SERVER.read_text(encoding="utf-8")
    declared = set(spec.get("env", {}))
    for key in declared:
        assert key in source, f"the config declares {key} and the server never reads it"

    reader = r"(?:environ\[|environ\.get\(|getenv\()[\"']([A-Z_]+)"
    read_by_the_server = set(re.findall(reader, source))
    assert read_by_the_server <= declared, (
        f"the server reads {sorted(read_by_the_server - declared)} and the registration "
        f"does not declare it"
    )


def _specification_sections() -> dict[str, list[str]]:
    """The backticked tool names under each level-two heading of the specification."""
    sections: dict[str, list[str]] = {}
    heading = None
    for line in _SPECIFICATION.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            sections[heading] = []
        elif line.startswith("### ") and heading is not None:
            found = re.findall(r"`([^`]+)`", line)
            sections[heading].extend(found)
    return sections


def test_the_specification_lists_the_tools_the_server_advertises():
    sections = _specification_sections()
    implemented = set(sections["Implemented tools"])
    assert implemented == set(TOOLS), (
        f"the specification documents {sorted(implemented)} and the server advertises "
        f"{sorted(TOOLS)}"
    )


def test_a_tool_the_specification_calls_unimplemented_is_not_implemented():
    """The other direction of the same drift, which is the one that ages badly.

    If one of the planned tools is ever built, this fails until it moves out of the
    section that tells a reader it does not exist.
    """
    planned = set(_specification_sections()["Specified and not implemented"])
    assert planned, "the section exists to record what was specified and not built"
    assert not planned & set(TOOLS), sorted(planned & set(TOOLS))


def test_every_path_the_specification_cites_exists_and_is_published():
    """It names scripts as the thing that did each unbuilt tool's job, so they have to be
    there. A citation to a file a reader cannot open is the same defect as a missing tool.
    """
    text = _SPECIFICATION.read_text(encoding="utf-8")
    candidates = {
        token
        for token in re.findall(r"`([^`]+)`", text)
        if "/" in token and " " not in token and not token.startswith("http")
    }
    assert len(candidates) >= 8, f"the extractor found {len(candidates)} paths, so it broke"
    missing = [c for c in sorted(candidates) if not (REPO / c).exists()]
    unpublished = [c for c in sorted(candidates) if (REPO / c).exists() and not _tracked(REPO / c)]
    assert not missing, f"the specification cites paths that do not exist: {missing}"
    assert not unpublished, f"the specification cites paths git does not publish: {unpublished}"
