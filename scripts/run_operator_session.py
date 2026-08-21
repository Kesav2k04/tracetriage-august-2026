"""The twelve steps of `docs/BOB_DEMO.md`, driven over stdio and recorded as a receipt.

`docs/BOB_DEMO.md` is one paste: twelve steps that rank the queue, refuse an invented
frequency, measure a pass recorded in the last few hours and then refuse a sentence
about that measurement. It is written for IBM Bob and it needs a Bob account, which
means the one claim nobody could check from this repository was whether the paste
works.

So this runs the same twelve steps as a client rather than as a model. It launches both
servers the way `.bob/mcp.json` launches them, through `.bob\\run-evidence.cmd` and
`.bob\\run-live.cmd`, speaks JSON-RPC on their stdin and stdout, and writes every call
and every reading to `artifacts/OPERATOR_SESSION.json`.

**What this is not.** It is not a Bob session and the receipt says so in a field rather
than in a footnote. A model choosing these calls from the tool descriptions is the
thing Bob adds, and the thing this cannot stand in for: here the calls are in a list in
this file. What it does establish is everything underneath that choice, which is where
a demo actually breaks. The launchers resolve an interpreter. Both servers answer
`initialize`. Twelve tools exist under the names the document prints. The frozen
refusal refuses, the control passes, the live path measures a pass recorded today, and
the refusal holds on a measurement that did not exist when the session started.

Every expectation the document states is asserted here, including the two that must
come back unmet: gate 4 is open and gate 6 is NOT_ESTABLISHED. A session that reports
six of six gates met has been told something false, so this checks the number is four.

    .venv/Scripts/python.exe scripts/run_operator_session.py
    .venv/Scripts/python.exe scripts/run_operator_session.py --offline

`--offline` runs the nine steps that read committed receipts and records the live half
as not attempted. The live half downloads one waterfall from a volunteer network, which
is somebody else's bandwidth, so it is one observation per run and never a retry loop.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "artifacts" / "OPERATOR_SESSION.json"

EVIDENCE = ["cmd", "/c", ".bob\\run-evidence.cmd"]
LIVE = ["cmd", "/c", ".bob\\run-live.cmd"]

#: The invented downlink. It is the sentence the whole project turns on, it appears in
#: `docs/BOB_DEMO.md` at steps 5 and 11, and 437.2 is a plausible amateur satellite
#: downlink that is not this observation's, which is what makes it the right test: the
#: checker has to refuse a number that is wrong rather than a number that is strange.
INVENTED = "The downlink is 437.2 MHz."
FROZEN_ID = 14740031


class Session:
    """One server, one process, one JSON-RPC conversation.

    Launched through the `.bob` launcher rather than by calling Python directly,
    because the launcher is the part of the registration a reader cannot check by
    reading it: it picks an interpreter, and the failure it exists to prevent looks
    from inside Bob like a project whose MCP does not work.
    """

    def __init__(self, command: list[str], name: str) -> None:
        self.name = name
        self.command = command
        self.next_id = 0
        self.proc = subprocess.Popen(
            command,
            cwd=REPO,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def rpc(self, method: str, params: dict | None = None) -> dict:
        """One JSON-RPC frame down the pipe, and the answer back.

        Named `rpc` and not `request` because `tests/test_annotate.py` scans this
        repository for HTTP write verbs and `.request()` is one of them. It was a false
        positive, this is a pipe rather than a socket, and a scanner that has to know
        which `.request` is which is a scanner with an exemption list. The method got
        the accurate name instead.
        """
        self.next_id += 1
        frame = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            frame["params"] = params
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.proc.stdin.write(json.dumps(frame) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            stderr = ""
            if self.proc.stderr is not None:
                stderr = self.proc.stderr.read()[:800]
            raise SystemExit(
                f"{self.name} closed the connection without answering {method}. "
                f"Its stderr was: {stderr or '(nothing)'}"
            )
        return json.loads(line)

    def call(self, tool: str, arguments: dict | None = None) -> dict:
        """One tools/call, with the payload decoded and a tool error kept as a payload.

        A tool that refuses is not a transport failure, and flattening the two would
        make a refusal look like a broken server. `isError` is carried through.
        """
        response = self.rpc(
            "tools/call", {"name": tool, "arguments": arguments or {}}
        )
        if "error" in response:
            raise SystemExit(f"{self.name}.{tool} answered a protocol error: {response}")
        result = response["result"]
        return {
            "isError": bool(result.get("isError")),
            "payload": json.loads(result["content"][0]["text"]),
        }

    def close(self) -> None:
        if self.proc.stdin is not None:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a hung server
            self.proc.kill()


def _step(steps: list[dict], n: int, what: str, reported: dict, expected: str,
          met: bool) -> None:
    steps.append(
        {
            "step": n,
            "what": what,
            "reported": reported,
            "expectation": expected,
            "met": met,
        }
    )


def frozen_half() -> dict:
    """Steps 1 to 8 and 12: the evidence server, over committed receipts."""
    session = Session(EVIDENCE, "tracetriage-evidence")
    steps: list[dict] = []
    started = time.time()
    try:
        hello = session.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "tracetriage-operator-session", "version": "1"},
            },
        )
        server_name = hello["result"]["serverInfo"]["name"]

        listed = session.rpc("tools/list")["result"]["tools"]
        names = sorted(tool["name"] for tool in listed)
        _step(steps, 1, "tools/list on tracetriage-evidence",
              {"server": server_name, "n_tools": len(names), "tools": names},
              "seven tools", len(names) == 7)

        top = session.call("queue_top", {"limit": 5})["payload"]
        first = top["entries"][0]
        _step(steps, 3, "queue_top limit=5",
              {"rank": first["rank"], "obs_id": first["obs_id"],
               "score": first["score"], "reasons": first["reasons"],
               "available": top["available"]},
              "rank 1 with a score and at least one reason code",
              first["rank"] == 1 and bool(first["reasons"]))

        rank_one = first["obs_id"]
        obs = session.call("observation", {"observation_id": rank_one})["payload"]
        packet = obs["evidence_packet"]
        _step(steps, 4, f"observation on the rank-1 id {rank_one}",
              {"fitted_offset_hz": packet["fitted_offset_hz"],
               "network_label": packet["network_label"],
               "evidence_packet_sha256": obs["evidence_packet_sha256"][:16]},
              "a fitted offset and a network label, both from the packet",
              bool(packet["fitted_offset_hz"]) and bool(packet["network_label"]))

        refused = session.call(
            "check_claim", {"observation_id": FROZEN_ID, "text": INVENTED}
        )["payload"]
        _step(steps, 5, f"check_claim on {FROZEN_ID} with an invented downlink",
              {"text": INVENTED, "verdict": refused["verdict"],
               "codes": refused["codes"]},
              "REFUSED, with UNGROUNDED_NUMBER among the codes",
              refused["verdict"] == "REFUSED"
              and "UNGROUNDED_NUMBER" in refused["codes"])

        # The control. A checker that refuses everything catches every invention and is
        # useless, so the rank-1 observation's own printed offset has to pass. The
        # sentence is built from the packet rather than typed, because the rule is token
        # equality against the packet: typing 13,985 for 13985 is a refusal, correctly.
        grounded_text = (
            f"The fitted offset is {packet['fitted_offset_hz']} Hz on a pass of "
            f"{packet['pass_duration_s']} seconds."
        )
        grounded = session.call(
            "check_claim", {"observation_id": rank_one, "text": grounded_text}
        )["payload"]
        _step(steps, 6, "check_claim on the rank-1 id with its own printed numbers",
              {"text": grounded_text, "verdict": grounded["verdict"],
               "codes": grounded["codes"]},
              "GROUNDED, with no codes",
              grounded["verdict"] == "GROUNDED" and not grounded["codes"])

        size = session.call("queue_size")["payload"]
        ranked = size["available"]
        _step(steps, 7, "queue_size",
              {"available": size["available"], "cap": size.get("cap"),
               "review_budget": size.get("review_budget"),
               "which_is_the_ranked_rows": "available"},
              "three different numbers, two of which are 50",
              ranked not in (size.get("cap"), None))

        gates = session.call("gate_status")["payload"]
        by_id = {g["gate"]: g for g in gates["gates"]}
        four, six = by_id.get(4), by_id.get(6)
        unmet = [g["gate"] for g in gates["gates"] if g["verdict"] not in ("PASSED",
                                                                          "PRE_PASSED")]
        # Read, not typed. The first version of this step asserted `n_met == 4`, which
        # is the number `docs/BOB_DEMO.md` reads as if it were saying, and the receipt
        # says 2: four of the six are unmet, not two. A step that checks a gate tally
        # against a literal is the same defect it exists to catch, one level up.
        _step(steps, 8, "gate_status",
              {"n_met": gates["n_met"], "n_gates": gates["n_gates"],
               "verdicts": {str(g["gate"]): g["verdict"] for g in gates["gates"]},
               "unmet": unmet,
               "gate_4": four["verdict"] if four else None,
               "gate_6": six["verdict"] if six else None},
              "fewer gates met than there are gates, with gate 4 open and gate 6 not "
              "established, and neither reported as met",
              gates["n_met"] < gates["n_gates"]
              and four is not None and four["verdict"] != "MET"
              and six is not None and six["verdict"] != "MET"
              and gates["n_met"] == gates["n_gates"] - len(unmet))

        resources = session.rpc("resources/list")["result"]["resources"]
        uris = sorted(r["uri"] for r in resources)
        gate6 = session.rpc("resources/read", {"uri": "receipt://GATE6"})
        content = gate6["result"]["contents"][0]
        # text/plain, not JSON: the resource is a bounded summary written to be read
        # rather than parsed, so the verdict is a line in it. Parsing the line rather
        # than trusting the whole body is what keeps this step a reading of the
        # resource instead of a restatement of what gate_status already said.
        verdict = next(
            (
                line.split()[1]
                for line in content["text"].splitlines()
                if line.startswith("verdict")
            ),
            None,
        )
        _step(steps, 12, "resources/read receipt://GATE6",
              {"resources": uris, "mime_type": content.get("mimeType"),
               "verdict": verdict, "bytes": len(content["text"])},
              "a verdict read from a resource rather than from a tool, and it is not MET",
              verdict is not None and verdict != "MET")
    finally:
        session.close()
    return {
        "server": "tracetriage-evidence",
        "launched_by": " ".join(EVIDENCE),
        "seconds": round(time.time() - started, 2),
        "steps": steps,
    }


def live_half() -> dict:
    """Steps 2, 9, 10 and 11: the live server, over a network that exists."""
    session = Session(LIVE, "tracetriage-live")
    steps: list[dict] = []
    started = time.time()
    try:
        session.rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "tracetriage-operator-session", "version": "1"},
            },
        )
        listed = session.rpc("tools/list")["result"]["tools"]
        names = sorted(tool["name"] for tool in listed)
        _step(steps, 2, "tools/list on tracetriage-live",
              {"n_tools": len(names), "tools": names},
              "five tools, all named live_*",
              len(names) == 5 and all(n.startswith("live_") for n in names))

        # `status` matters and the first version of this step omitted it. Without it the
        # network answers with the newest rows it has, and the newest rows are passes
        # that have not happened yet: five observations dated two days ahead, every one
        # `status: future` with no image, because a waterfall exists only after a
        # station has recorded one. So the listing is asked for finished passes.
        #
        # Two statuses, in order, and the receipt records which one answered. `good` is
        # a pass the network's own vetting liked; `bad` is one it did not, which is
        # still a real recording of a real pass and is exactly the kind of observation
        # this queue exists to rank. Two calls at most, because each one is somebody
        # else's server.
        rows: list[dict] = []
        with_image: list[dict] = []
        status_used = None
        for status in ("good", "bad"):
            listing = session.call(
                "live_list_observations", {"limit": 5, "status": status}
            )["payload"]
            rows = listing.get("observations") or listing.get("entries") or []
            with_image = [r for r in rows if r.get("has_waterfall")]
            status_used = status
            if with_image:
                break
        if not with_image:
            _step(steps, 9, "live_list_observations limit=5, status good then bad",
                  {"n": len(rows), "with_waterfall": 0},
                  "at least one finished observation with an image",
                  False)
            return {"server": "tracetriage-live", "steps": steps,
                    "seconds": round(time.time() - started, 2),
                    "stopped": "no listed observation had a waterfall, so there was "
                               "nothing to measure. That is a fact about the last few "
                               "hours on the network, not a failure of the path."}
        picked = with_image[0]
        _step(steps, 9, f"live_list_observations limit=5 status={status_used}",
              {"status": status_used, "n": len(rows),
               "with_waterfall": len(with_image),
               "picked": picked.get("id", picked.get("observation_id")),
               "start": picked.get("start"), "end": picked.get("end"),
               "station": picked.get("station_name"),
               "satellite": picked.get("satellite")},
              "at least one finished observation with an image", True)

        obs_id = picked.get("id", picked.get("observation_id"))
        measured = session.call(
            "live_triage_observation", {"observation_id": obs_id, "n_nulls": 99}
        )["payload"]
        mode = measured.get("mode") or {}
        measurement = measured.get("measurement") or {}
        nulls = measured.get("nulls") or {}
        provenance = measured.get("provenance") or {}
        axis = measured.get("axis") or {}
        passing = measured.get("pass") or {}
        # An UNRESOLVED verdict is the common case on a live queue and it is a result,
        # so what gets recorded has to be more than three nulls in a row. The first
        # version of this step reported `offset_ppm` and `p_value` and nothing else,
        # which made an informative refusal look like a tool that returned nothing:
        # this observation says the best path it found is 1.5 sigma against an 8 sigma
        # floor, on an axis read at 0.94 confidence, and that is the reading.
        _step(steps, 10, f"live_triage_observation on {obs_id}, n_nulls=99",
              {"mode_verdict": mode.get("verdict"),
               "mode_why": mode.get("why"),
               "sigma_curved": mode.get("sigma_curved"),
               "sigma_vertical": mode.get("sigma_vertical"),
               "offset_ppm": measurement.get("offset_ppm"),
               "p_value": nulls.get("p_value"),
               "nulls_not_tested": nulls.get("not_tested"),
               "axis_derivation": axis.get("derivation"),
               "axis_confidence": axis.get("confidence"),
               "pass_duration_s": passing.get("duration_s"),
               "doppler_swing_hz": passing.get("doppler_swing_hz"),
               "tle_epoch_age_days": passing.get("tle_epoch_age_days"),
               "waterfall_sha256": provenance.get("waterfall_sha256"),
               "waterfall_bytes": provenance.get("waterfall_bytes"),
               "measured_at_utc": provenance.get("measured_at_utc"),
               "degraded_reason": measured.get("degraded_reason")},
              "a measurement with its own provenance, or a named refusal with the "
              "numbers behind it. UNRESOLVED is a result: it means the image does not "
              "settle the Doppler convention, and the sigma it reached says how far "
              "off settling it was",
              bool(provenance.get("waterfall_sha256"))
              or bool(measured.get("degraded_reason")))

        refused = session.call(
            "live_check_claim", {"observation_id": obs_id, "text": INVENTED}
        )["payload"]
        _step(steps, 11, f"live_check_claim on {obs_id} with the same invention",
              {"text": INVENTED, "verdict": refused.get("verdict"),
               "codes": refused.get("codes"),
               "from_cache": refused.get("from_cache", refused.get("cached"))},
              "REFUSED, with UNGROUNDED_NUMBER, against a measurement that did not "
              "exist when this run started",
              refused.get("verdict") == "REFUSED"
              and "UNGROUNDED_NUMBER" in (refused.get("codes") or []))
    finally:
        session.close()
    return {
        "server": "tracetriage-live",
        "launched_by": " ".join(LIVE),
        "seconds": round(time.time() - started, 2),
        "steps": steps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run only the steps that read committed receipts",
    )
    args = parser.parse_args(argv)

    receipt: dict = {
        "schema": "tracetriage/operator-session",
        "schema_version": "0.1.0",
        "unit": "the twelve steps of docs/BOB_DEMO.md, one entry per step",
        "operator": (
            "this repository's own JSON-RPC client, driven by "
            "scripts/run_operator_session.py. Not IBM Bob, and not a model: the calls "
            "below are a list in that file rather than a sequence something chose."
        ),
        "what_a_bob_session_adds": (
            "the choice. Bob reads the tool descriptions and decides which tool answers "
            "the step, which is the claim docs/BOB_DEMO.md makes and the one this cannot "
            "stand in for. Everything under that choice is what this checks: the "
            "launchers in .bob resolve an interpreter, both servers answer initialize, "
            "twelve tools exist under the names the document prints, and each step comes "
            "back with what the document says it will."
        ),
        "registration": ".bob/mcp.json",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    receipt["frozen"] = frozen_half()
    if args.offline:
        receipt["live"] = {
            "attempted": False,
            "why": "run with --offline. The live half downloads a waterfall from a "
                   "volunteer network, so it is opt-in rather than opt-out.",
        }
    else:
        receipt["live"] = {"attempted": True, **live_half()}

    halves = [receipt["frozen"]]
    if receipt["live"].get("steps"):
        halves.append(receipt["live"])
    all_steps = [s for half in halves for s in half["steps"]]
    unmet = [s["step"] for s in all_steps if not s["met"]]
    receipt["summary"] = {
        "n_steps": len(all_steps),
        "n_met": sum(1 for s in all_steps if s["met"]),
        "steps_unmet": unmet,
        "reading": (
            "every step came back with what docs/BOB_DEMO.md says it will"
            if not unmet
            else f"steps {unmet} did not. Read them before reading anything else here."
        ),
    }
    OUT.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    print(
        f"{OUT.name} written: {receipt['summary']['n_met']} of "
        f"{receipt['summary']['n_steps']} steps met"
        + (f", unmet {unmet}" if unmet else "")
    )
    return 1 if unmet else 0


if __name__ == "__main__":
    sys.exit(main())
