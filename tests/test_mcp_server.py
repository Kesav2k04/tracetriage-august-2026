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
_NETWORK_WRITES = frozenset({"post", "put", "patch", "delete", "request", "stream", "send"})

#: Every disk write reachable without an attribute this list does not name. The first
#: version had five entries and missed six writes that an AST walk sees plainly:
#: ``open(p, "w").write(x)``, ``os.remove``, ``shutil.rmtree``, ``Path.touch`` and
#: ``json.dump(d, f)``. Enumerating names is the weakness; the answer is to enumerate more
#: of them and to read ``open``'s mode, which is what the branch below does.
_DISK_WRITES = frozenset(
    {
        "write_text",
        "write_bytes",
        "writelines",
        "unlink",
        "mkdir",
        "rmdir",
        "touch",
        "remove",
        "removedirs",
        "rmtree",
        "replace",
        "rename",
        "dump",
        "write",
    }
)

#: ``.write`` is on that list because a file object has it, and the transport writes to a
#: stream, so exactly one receiver is exempt and the count of its call sites is asserted.
#: A second ``sink.write`` would fail the test, which is the point: the exemption is a
#: number, not a permission.
_STREAM_RECEIVER = "sink"
_STREAM_WRITE_SITES = 1

#: The transport moved to the package so that `tracetriage mcp-live` could reach a
#: dispatcher from an installed wheel, which does not ship `scripts/`. That took the one
#: exempt `sink.write` with it, and the scan below asserted a count of 1 against the server
#: file alone, so it failed rather than passing over an empty file: the exemption count is
#: what caught the writer leaving. The scan now reads both files, because a read-only claim
#: about a server that dispatches through another module is a claim about both of them.
_TRANSPORT = REPO / "pipeline" / "tracetriage" / "mcp_transport.py"


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


#: The tools the evidence server serves, spelled out rather than counted.
#:
#: A literal on purpose. Every other assertion here compares the server against its own
#: TOOLS dict, and `listed == set(TOOLS)` stays true whether a tool is added, dropped or
#: renamed, so nothing in this suite could say how many there are. README.md said five in
#: three places and seven in a fourth, three hundred lines apart, for weeks. A count that
#: appears in judge-facing prose needs an assertion that fails when the prose goes wrong,
#: and the only way to get one is to write the number down somewhere a test can read it.
_EVIDENCE_TOOLS = (
    "queue_top",
    "observation",
    "check_claim",
    "gate_status",
    "receipt",
    "queue_size",
    "run_acceptance",
)


def test_the_evidence_server_declares_exactly_seven_tools():
    assert len(TOOLS) == 7, (
        f"the evidence server declares {len(TOOLS)} tools: {sorted(TOOLS)}. Seven is "
        f"the number README.md and FOR_JUDGES.md publish, so a change here is a change "
        f"to both."
    )
    assert tuple(TOOLS) == _EVIDENCE_TOOLS


def test_the_tool_list_over_the_transport_is_those_seven_and_nothing_else():
    """The count as a client sees it, not as the module declares it.

    Separate from the assertion above because they can disagree: `tools/list` builds its
    payload from TOOLS, and a filter added there would leave the dict at seven and the
    served surface at six.
    """
    responses = _drive(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )
    listed = [tool["name"] for tool in responses[1]["result"]["tools"]]
    assert len(listed) == 7, f"the server listed {len(listed)} tools: {listed}"
    assert listed == list(_EVIDENCE_TOOLS)


def test_a_malformed_line_is_a_parse_error_and_the_server_keeps_going():
    stdin = io.StringIO('not json\n{"jsonrpc": "2.0", "id": 7, "method": "tools/list"}\n')
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["id"] == 7, "one bad frame must not end the session"


def test_an_unimplemented_method_is_a_protocol_error_not_a_tool_result():
    """A method this server does not speak is -32601, not an empty tool result.

    The example used to be `resources/list`, which this server now implements: the four
    kill-gate receipts are exposed as resources so a Bob session can mention one instead
    of calling a tool. `prompts/list` takes its place, because a server that advertises
    no prompts and answers `prompts/list` with an empty list is telling a client it has a
    capability it does not have.
    """
    response = handle({"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})
    assert response is not None
    assert response["error"]["code"] == -32601


def test_the_kill_gate_receipts_are_readable_as_resources():
    """`resources/list` answered -32601 for the whole build.

    That is the correct answer for a server with no resources and the wrong one for a
    server whose entire subject is receipts. A judge in Bob can now mention a gate
    rather than remembering which tool reports it.
    """
    listing = handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    assert listing is not None and "error" not in listing, listing
    uris = {entry["uri"] for entry in listing["result"]["resources"]}
    assert uris == {
        "receipt://GATE3",
        "receipt://GATE4",
        "receipt://GATE5",
        "receipt://GATE6",
    }, sorted(uris)

    for entry in listing["result"]["resources"]:
        assert entry["name"], entry
        assert entry["description"], f"{entry['uri']} has no description"

    read = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "receipt://GATE6"},
        }
    )
    assert read is not None and "error" not in read, read
    body = read["result"]["contents"][0]["text"]
    assert "gate 6" in body.lower()
    # The verdict is quoted from the receipt, so a resource cannot upgrade a gate.
    assert "NOT_ESTABLISHED" in body or "PASSED" in body or "FAILED" in body, body[:200]
    # Bounded. A resource that returns the whole 268 kB receipt is a resource that
    # fills an agent's context with one call.
    assert len(body) < 8_000, len(body)


def test_an_unknown_resource_is_a_named_refusal():
    read = handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": "receipt://GATE9"},
        }
    )
    assert read is not None
    assert "error" in read, read
    assert "GATE9" in json.dumps(read["error"]) or "unknown" in json.dumps(read["error"]).lower()


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
    assert _call("queue_top", {"limit": "ten"})["payload"]["reason"] == "BAD_ARGUMENTS"
    assert _call("check_claim", {"observation_id": 1, "text": "  "})["payload"][
        "reason"
    ] == "EMPTY_CLAIM"
    assert _call("queue_top", {"nonsense": 1})["payload"]["reason"] == "BAD_ARGUMENTS"
    assert _call("queue_top", {"limit": []})["payload"]["reason"] == "BAD_ARGUMENTS"
    # isinstance(True, int) is true in Python, so a bool clears a naive integer guard and
    # returns one row while the schema says integer.
    assert _call("queue_top", {"limit": True})["payload"]["reason"] == "BAD_ARGUMENTS"


def test_an_id_passed_as_a_string_is_a_named_reason_and_not_a_dead_session():
    """The likeliest mistake an agent makes, and it used to end the client's session.

    ``int("abc")`` raised ValueError inside the tool arm, which caught ToolError and
    TypeError only, so the exception left the read loop and the process died with no
    response written at all. Both tools that take an id are checked, and the session is
    proved alive afterwards by a following request in the same conversation.
    """
    for name, arguments in (
        ("observation", {"observation_id": "abc"}),
        ("check_claim", {"observation_id": "14746092", "text": "anything"}),
    ):
        out = _call(name, arguments)
        assert out["isError"] is True, name
        assert out["payload"]["reason"] == "BAD_ARGUMENTS", (name, out["payload"])


def test_a_receipt_name_cannot_escape_the_artifacts_directory():
    """Containment, tested with the form the blocklist let through.

    ``C:foo.json`` holds no separator and no parent reference, and on Windows it is
    drive-relative: it resolves against that drive's working directory, outside the
    repository. The old guard rejected three shapes of the same trick and missed it, which
    is what a blocklist does. It was also a crash primitive, because any readable non-JSON
    file at that path died in json.loads and took the session with it.
    """
    for bad in (
        "../pyproject.toml",
        "sub/dir.json",
        "..\\secrets.json",
        "C:foo.json",
        ".",
        "",
    ):
        out = _call("receipt", {"name": bad})
        assert out["isError"] is True, bad
        assert out["payload"]["reason"] in {"BAD_RECEIPT_NAME", "UNKNOWN_RECEIPT"}, bad
    out = _call("receipt", {"name": "NOT_A_RECEIPT.json"})
    assert out["payload"]["reason"] == "UNKNOWN_RECEIPT"


def test_a_directory_named_as_a_receipt_is_a_reason_and_not_a_crash():
    """`.` passed the old guard, existed, and raised PermissionError inside read_text."""
    out = _call("receipt", {"name": "."})
    assert out["isError"] is True
    assert out["payload"]["reason"] == "BAD_RECEIPT_NAME"


def test_a_list_rooted_receipt_summarises_to_something():
    """The empty answer that reads like a measurement, on the audit least able to afford it.

    artifacts/LEAKAGE_AUDIT.json is a JSON array. The dict-only summariser returned two
    empty objects with isError false, so a client asking about the leakage audit was told,
    in effect, that it holds nothing.
    """
    out = tool_receipt("LEAKAGE_AUDIT.json")
    assert out["root"] == "list"
    assert out["collection_sizes"]["<root>"] > 0
    assert out["scalars"].get("row_fields"), "a list of records has fields worth naming"


# ---------------------------------------------------------------------------
# The answers come from the receipts
# ---------------------------------------------------------------------------


def test_the_queue_comes_back_in_rank_order_and_bounded():
    out = tool_queue_top(3)
    assert [e["rank"] for e in out["entries"]] == [1, 2, 3]
    assert out["cap"] == MAX_QUEUE_LIMIT
    assert out["available"] > MAX_QUEUE_LIMIT, (
        "the cap is only meaningful if there is more queue than the cap"
    )
    assert tool_queue_top(MAX_QUEUE_LIMIT)["returned"] == MAX_QUEUE_LIMIT


def test_a_limit_above_the_advertised_maximum_is_refused_rather_than_truncated():
    """The schema and the handler have to agree about what is legal.

    The handler used to cap silently and disclose the cap afterwards, while the schema
    advertised maximum 50. A validating client therefore refused to send what this server
    accepted, so the two disagreed about the same call.
    """
    declared = TOOLS["queue_top"]["schema"]["properties"]["limit"]["maximum"]
    assert declared == MAX_QUEUE_LIMIT
    out = _call("queue_top", {"limit": declared + 1})
    assert out["isError"] is True
    assert out["payload"]["reason"] == "BAD_LIMIT"
    assert str(declared) in out["payload"]["detail"]


def test_the_queue_says_which_rows_the_other_tools_can_answer_about():
    """The failure a client hit roughly half the time, in the top fifty rows.

    The queue is the whole ranking; only observations the console ships imagery for have an
    evidence packet. Without the flag, a client walking queue_top into observation got
    UNKNOWN_OBSERVATION on most rows, and the refusal message pointed it back at queue_top.
    """
    out = tool_queue_top(MAX_QUEUE_LIMIT)
    flagged = [e for e in out["entries"] if e["has_evidence_packet"]]
    unflagged = [e for e in out["entries"] if not e["has_evidence_packet"]]
    assert out["with_evidence_packet"] == len(flagged)
    assert flagged and unflagged, (
        "both kinds have to be present or this proves nothing: "
        f"{len(flagged)} flagged, {len(unflagged)} not"
    )
    for entry in flagged:
        assert tool_observation(entry["obs_id"])["observation_id"] == entry["obs_id"]
    for entry in unflagged:
        with pytest.raises(ToolError) as caught:
            tool_observation(entry["obs_id"])
        assert caught.value.code == "UNKNOWN_OBSERVATION"


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


def _write_sites(tree: ast.AST) -> tuple[list[str], list[str]]:
    """Every network or disk write in the tree, and the stream writes exempted by name.

    Three shapes, because the first version of this scan saw only the first: an attribute
    call whose name is a write, ``open`` with a mode that writes, and ``.write`` on the one
    receiver that is a stream rather than a file.
    """
    writes: list[str] = []
    exempt: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            modes = [a for a in node.args[1:2] if isinstance(a, ast.Constant)]
            modes += [
                k.value
                for k in node.keywords
                if k.arg == "mode" and isinstance(k.value, ast.Constant)
            ]
            for mode in modes:
                if isinstance(mode.value, str) and set(mode.value) & set("wax+"):
                    writes.append(f"line {node.lineno}: open(..., {mode.value!r})")
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _NETWORK_WRITES | _DISK_WRITES:
            continue
        receiver = node.func.value
        if (
            node.func.attr == "write"
            and isinstance(receiver, ast.Name)
            and receiver.id == _STREAM_RECEIVER
        ):
            exempt.append(f"line {node.lineno}: {_STREAM_RECEIVER}.write()")
            continue
        writes.append(f"line {node.lineno}: .{node.func.attr}()")
    return writes, exempt


def test_the_server_holds_no_write_verb_and_no_network_import():
    """The capability claim, checked against the source rather than the documentation.

    Both files, because the server dispatches through the transport: a scan of the server
    alone would have said read-only about a file that hands every request to another one.
    """
    assert _TRANSPORT.exists(), f"{_TRANSPORT} is where the dispatcher lives"
    trees = {
        path: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in (_SERVER, _TRANSPORT)
    }
    imports: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    total_exempt: list[str] = []
    for path, tree in trees.items():
        writes, exempt = _write_sites(tree)
        assert not writes, f"{path.name} writes: {writes}"
        total_exempt.extend(exempt)
    assert len(total_exempt) == _STREAM_WRITE_SITES, (
        f"the stream exemption covers {_STREAM_WRITE_SITES} call site and these two files "
        f"have {len(total_exempt)}: {total_exempt}. Route every response through one writer "
        f"rather than widening the exemption."
    )
    offenders = sorted(
        m for m in imports if m.split(".")[0] in {"httpx", "requests", "socket", "urllib"}
    )
    assert not offenders, f"the offline server imports {offenders}"
    # It must reach the checker, or check_claim would be a second implementation.
    assert any("explain" in m for m in imports), sorted(imports)
    assert not any("granite" in m for m in imports), (
        "the server must not import the module that can POST"
    )


def test_the_write_scan_catches_each_shape_it_claims_to():
    """The scan's own coverage, because a list of names is only as good as its entries.

    Six of these were invisible to the first version, which enumerated five attribute
    names. A scan that passes over a write is worse than no scan, because it publishes the
    read-only claim as verified.
    """
    shapes = (
        'p.write_text("x")',
        'open(p, "w").write("x")',
        'f = open(p, mode="a")',
        "os.remove(p)",
        "shutil.rmtree(p)",
        "p.touch()",
        "json.dump(d, f)",
        "p.unlink()",
        "client.post(url)",
        'session.request("POST", url)',
        "other.write(x)",
    )
    for shape in shapes:
        found, _ = _write_sites(ast.parse(shape))
        assert found, f"the scan does not see {shape}"

    # And a read is not a write, or the scan would fail on this server's own source.
    for benign in ('p.read_text("utf-8")', "json.loads(t)", "sink.write(t)", "open(p)"):
        found, _ = _write_sites(ast.parse(benign))
        assert not found, f"the scan reports {benign} as a write"


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


def test_a_frame_that_is_not_an_object_is_an_invalid_request():
    """Four inputs that parse cleanly and then killed the loop.

    The parse-error branch only saw unparseable bytes. ``5``, ``null`` and a batch array
    are all valid JSON, so they reached ``request.get`` and raised AttributeError, which
    left the read loop and ended the client's session with no response written.
    """
    stdin = io.StringIO(
        "5\n"
        + "null\n"
        + '"a string"\n'
        + '{"jsonrpc": "2.0", "id": 9, "method": "tools/list"}\n'
    )
    stdout = io.StringIO()
    assert serve(stdin=stdin, stdout=stdout) == 0
    responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert [r["error"]["code"] for r in responses[:3]] == [-32600, -32600, -32600]
    assert responses[3]["id"] == 9, "the session has to survive all three"


def test_a_batch_is_answered_as_a_batch():
    """Batching is in JSON-RPC 2.0, so a server that dies on one is broken rather than plain.

    The reply to a batch is an array of the responses that are not notifications, and a
    batch of nothing but notifications gets no reply at all, which is what a client waits
    on.
    """
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = io.StringIO(
        json.dumps(batch)
        + "\n"
        + json.dumps([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
        + "\n"
        + json.dumps([])
        + "\n"
    )
    stdout = io.StringIO()
    assert serve(stdin=stdin, stdout=stdout) == 0
    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]

    assert isinstance(lines[0], list)
    assert [r["id"] for r in lines[0]] == [1, 2], "the notification takes no slot"
    # The all-notification batch produced no line at all, so the next line is the empty
    # batch's error rather than a second array.
    assert lines[1]["error"]["code"] == -32600


def test_a_tool_that_fails_for_an_unforeseen_reason_still_answers(monkeypatch):
    """The blanket clause, checked with a handler that raises something unclassified.

    Every specific exception can be caught once it is known. The property worth pinning is
    that an unknown one becomes a named reason instead of taking the transport down, since
    a stdio server's blast radius is the client's whole session.
    """
    import scripts.mcp_server as server

    def explode() -> dict:
        raise RuntimeError(f"unforeseen, in {REPO}")

    monkeypatch.setitem(server.TOOLS["gate_status"], "handler", explode)
    out = _call("gate_status")
    assert out["isError"] is True
    assert out["payload"]["reason"] == "TOOL_FAILED"
    assert "RuntimeError" in out["payload"]["detail"]
    assert str(REPO) not in out["payload"]["detail"], (
        "a message a client receives must not carry this host's filesystem path"
    )


def test_the_server_refuses_to_start_without_the_evidence_it_advertises(monkeypatch, tmp_path):
    """The docstring claimed this before it was true.

    What existed was a per-call reason code, which is weaker: a client that has completed a
    handshake and read a tool list has been told those tools work. With the data directory
    empty, initialize and tools/list both answered normally and all five tools were
    advertised.
    """
    import scripts.mcp_server as server

    monkeypatch.setattr(server, "_DATA", tmp_path)
    stdin = io.StringIO('{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}\n')
    stdout = io.StringIO()
    assert server.serve(stdin=stdin, stdout=stdout) == 2
    assert stdout.getvalue() == "", "a refusal to start answers nothing at all"
    assert sorted(server.missing_evidence()) == sorted(
        f"{n} (outside this checkout)" for n in server.REQUIRED_EVIDENCE
    )


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


#: What Bob's own registration must contain, and what each server may run without asking.
#:
#: This file used to register one server, the evidence one, and the live measurement
#: tools lived only in the root `.mcp.json`, which Bob never loads. So the project's whole
#: live path was invisible to the tool the prize is about: a judge opening Bob could read
#: receipts and could not measure anything. That is the defect this expectation closes.
_BOB_SERVERS = {
    "tracetriage-evidence": {
        "launcher": ".bob/run-evidence.cmd",
        "target": "scripts/mcp_server.py",
        "always_allow": {
            "queue_top",
            "queue_size",
            "observation",
            "check_claim",
            "gate_status",
            "receipt",
        },
    },
    "tracetriage-live": {
        "launcher": ".bob/run-live.cmd",
        "target": "pipeline/tracetriage/mcp_live.py",
        "always_allow": {
            "live_list_observations",
            "live_triage_observation",
            "live_check_claim",
        },
    },
}


def test_the_registration_names_the_servers_that_exist():
    """A config pointing at a module nobody wrote is worse than no config.

    Two failures are pinned here. The first version of this file named
    ``tracetriage.mcp_server``, which never existed, so an agent that trusted it got an
    import error. The second version named one server and left the live tools in a file
    Bob does not read, so the measurement path was unreachable from the tool this project
    is judged on.
    """
    registered = json.loads(_REGISTRATION.read_text(encoding="utf-8"))["mcpServers"]
    assert set(registered) == set(_BOB_SERVERS), sorted(registered)

    for name, spec in registered.items():
        expected = _BOB_SERVERS[name]

        # cmd plus a repository-relative launcher. The launcher exists because bare
        # `python` on Windows can resolve to the Store alias, which exits immediately and
        # looks inside Bob like a server that does not work.
        assert spec["command"] == "cmd", f"{name}: {spec['command']!r}"
        launcher = next(a for a in spec["args"] if a.endswith(".cmd"))
        path = REPO / launcher.replace("\\", "/")
        assert path.exists(), f"{name} launches {launcher}, which does not exist"
        assert _tracked(path), (
            f"{name} launches {launcher}, which git does not publish, so a judge who "
            f"clones this repository cannot start it"
        )

        # No absolute path anywhere in the invocation. This file is public and a drive
        # letter in it resolves on exactly one machine. `/c` is cmd's switch, not a path,
        # so the check is for a drive letter and for a POSIX root with a name after it.
        for token in [spec["command"], *spec["args"], spec.get("cwd", ".")]:
            assert not re.match(r"^[A-Za-z]:", token), f"{name}: {token!r} is absolute"
            assert not re.match(r"^/[A-Za-z]{2,}", token), f"{name}: {token!r} is absolute"

        # The launcher has to start the server this key names.
        body = path.read_text(encoding="utf-8")
        assert expected["target"].split("/")[-1].replace(".py", "") in body.replace(
            "\\", "/"
        ), f"{launcher} does not mention {expected['target']}"
        assert (REPO / expected["target"]).exists()
        assert _tracked(REPO / expected["target"])

        assert spec.get("cwd") == ".", (
            f"{name} must declare the repository root as its working directory: the "
            f"server resolves its evidence relative to it"
        )
        assert spec.get("disabled") is False, f"{name} is registered and disabled"
        assert isinstance(spec.get("timeout"), int) and spec["timeout"] > 0

        # `alwaysAllow` is a standing permission, so the list is checked in both
        # directions: nothing missing that the demo needs, nothing extra that spends a
        # volunteer network's bandwidth without being asked.
        assert set(spec.get("alwaysAllow", [])) == expected["always_allow"], (
            f"{name}: {sorted(spec.get('alwaysAllow', []))}"
        )

    # The evidence server's key is the name it calls itself.
    assert SERVER_NAME == "tracetriage-evidence", SERVER_NAME


def test_the_expensive_live_tools_are_not_auto_approved():
    """The two that spend somebody else's bandwidth have to ask.

    `live_rank_observations` measures up to ten observations and `live_station` up to
    eight, at two HTTP requests each, against an API run by volunteers. A standing
    permission for either is a standing permission to make twenty requests because an
    agent thought it would be useful.
    """
    registered = json.loads(_REGISTRATION.read_text(encoding="utf-8"))["mcpServers"]
    allowed = set(registered["tracetriage-live"].get("alwaysAllow", []))
    assert "live_rank_observations" not in allowed
    assert "live_station" not in allowed

    evidence = set(registered["tracetriage-evidence"].get("alwaysAllow", []))
    assert "run_acceptance" not in evidence, (
        "run_acceptance runs the full gate, which is minutes of CPU and a console build"
    )


def test_the_registration_has_no_comment_fields():
    """`$comment` is not in Bob's MCP schema.

    It was carrying two paragraphs of explanation that a schema-validating client would
    reject or ignore, in place of the fields that actually configure the launch. The
    explanation now lives in `.bob/TOOL_SPECS.md` and in the launchers, and the config
    holds only keys Bob reads.
    """
    raw = json.loads(_REGISTRATION.read_text(encoding="utf-8"))
    assert set(raw) == {"mcpServers"}, sorted(raw)
    allowed_keys = {
        "command",
        "args",
        "cwd",
        "env",
        "headers",
        "timeout",
        "alwaysAllow",
        "disabled",
        "url",
        "httpURL",
    }
    for name, spec in raw["mcpServers"].items():
        extra = set(spec) - allowed_keys
        assert not extra, f"{name} declares {sorted(extra)}, which Bob's schema does not list"


def test_the_project_registration_names_servers_that_exist():
    """`.mcp.json` is the file a client reads on clone, so it is a claim about both servers.

    Separate from `.bob/mcp.json`, which is Bob's own registration and is pinned to exactly
    one server by the test above. This one registers both, because a judge opening this
    repository should get the live tools as well as the receipts without editing anything.

    Two registration files can drift, which is why this exists: every server named here has to
    resolve to something that is tracked and startable, and its key has to be the name that
    server advertises about itself.
    """
    project = json.loads((REPO / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(project) == {"tracetriage-evidence", "tracetriage-live"}, sorted(project)

    for name, spec in project.items():
        command = spec["command"]
        assert "/" not in command and "\\" not in command, (
            f"{name}: {command!r} is a path from one machine and this file is public"
        )
        args = spec["args"]
        if "-m" in args:
            module = args[args.index("-m") + 1]
            target = REPO / Path(*module.split(".")).with_suffix(".py")
        else:
            scripts = [a for a in args if a.endswith(".py")]
            assert len(scripts) == 1, f"{name}: {args}"
            target = REPO / scripts[0]
        assert target.exists(), f"{name} launches {target}, which does not exist"
        assert _tracked(target), (
            f"{name} launches {target.name}, which is not tracked, so a judge who clones "
            f"this repository cannot start it"
        )

    # The names are what each server calls itself, not labels chosen here.
    assert project["tracetriage-evidence"]["args"][0].endswith("mcp_server.py")
    from pipeline.tracetriage import mcp_live

    assert project["tracetriage-live"]["args"][-1].endswith("mcp_live")
    assert mcp_live.SERVER_NAME == "tracetriage-live", mcp_live.SERVER_NAME
    assert SERVER_NAME == "tracetriage-evidence", SERVER_NAME

    # The live server's tools are namespaced, and that prefix is load-bearing rather than
    # decorative: it is what stops an agent reading a measurement taken now as one of the
    # numbers this project was scored on.
    assert all(t.startswith("live_") for t in mcp_live.TOOLS), sorted(mcp_live.TOOLS)
    assert not any(t.startswith("live_") for t in TOOLS), sorted(TOOLS)


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


def test_the_specification_lists_the_tools_both_servers_advertise():
    """One section per server, and each has to match that server's registry exactly.

    The specification described one server for the whole build. When the live server
    gained `live_check_claim` and `live_station`, the handlers existed and nothing
    advertised them: the registry was not updated and neither was this file, so two
    working tools were invisible to every client. Checking both directions per server is
    what makes that state fail.
    """
    from pipeline.tracetriage import mcp_live

    sections = _specification_sections()
    evidence = set(sections["Implemented: `tracetriage-evidence`"])
    live = set(sections["Implemented: `tracetriage-live`"])

    # `Resources` is a subsection of the evidence server and names URIs, not tools.
    evidence -= {"Resources"}

    assert evidence == set(TOOLS), (
        f"the specification documents {sorted(evidence)} for the evidence server and it "
        f"advertises {sorted(TOOLS)}"
    )
    assert live == set(mcp_live.TOOLS), (
        f"the specification documents {sorted(live)} for the live server and it "
        f"advertises {sorted(mcp_live.TOOLS)}"
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
    # A bare filename is a path claim too. Requiring a separator meant a cited
    # "vercel.json" was never checked for existence or for publication.
    suffixes = (".py", ".json", ".md", ".ts", ".tsx", ".yml", ".toml")
    # A JSON-RPC method name looks like a path and is not one. `resources/list` and
    # `resources/read` are methods this server answers, and requiring them to exist on
    # disk made a correct specification fail.
    methods = re.compile(r"^(?:resources|tools|prompts|completion|logging|receipt)/[a-z]+$")
    candidates = {
        token
        for token in re.findall(r"`([^`]+)`", text)
        if " " not in token
        and not token.startswith("http")
        and not methods.match(token)
        and ("/" in token or token.endswith(suffixes))
    }
    assert len(candidates) >= 8, f"the extractor found {len(candidates)} paths, so it broke"
    missing = [c for c in sorted(candidates) if not (REPO / c).exists()]
    unpublished = [c for c in sorted(candidates) if (REPO / c).exists() and not _tracked(REPO / c)]
    assert not missing, f"the specification cites paths that do not exist: {missing}"
    assert not unpublished, f"the specification cites paths git does not publish: {unpublished}"
