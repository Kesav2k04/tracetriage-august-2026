"""The two grounding checkers decide the same thing, and the answer key still checks.

There are two implementations of one rule set. `pipeline/tracetriage/explain.py` is the one
the pipeline ran, and `apps/web/lib/grounding.ts` is a port of it, because the console is a
static export and a reader who edits a digit in a note has to see the refusal in the browser
with no server to ask.

Two implementations of the same rules drift, and the drift is invisible: each one passes its
own tests. `apps/web/public/data/grounding_golden.json` is the shared answer key. The
TypeScript suite replays every row through the port. This file holds the Python end, and it
asks five questions the TypeScript suite cannot:

Is the key what the current Python source decides? `--check` regenerates it in memory and
compares bytes, so a rule changed here and not there fails at once.

Does the key say which checker produced it? A stale digest is how an answer key outlives the
code it describes.

Does it hold rows in both directions? 799 refusals and no grounded rows would let a port that
refuses everything pass every replay.

Is every code the checker can emit covered somewhere? A rule added in Python with no row in
the key and no test in the port is a rule the port does not have, and nothing else would say
so.

And can a reader reach it? The port sat finished, with a full suite around it, and no page
imported it. Every sentence written about editing a digit in the browser was true of the
tests and of nothing anybody could open.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "apps" / "web" / "public" / "data" / "grounding_golden.json"
GENERATOR = REPO / "scripts" / "export_grounding_golden.py"
CHECKER = REPO / "pipeline" / "tracetriage" / "explain.py"
PORT = REPO / "apps" / "web" / "lib" / "grounding.ts"
PORT_TESTS = REPO / "apps" / "web" / "tests" / "grounding.test.ts"

#: The one code the answer key does not exercise, and the reason. Every draft in the key is
#: a reviewer note or an adversarial edit of one, and none is over the character limit, so
#: nothing in the corpus can produce this. It is covered instead by a named case in the
#: port's own suite, which this file requires below. The exemption carries its reason here
#: so it cannot outlive it.
UNEXERCISED_BY_THE_KEY = {"TOO_LONG"}


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _emitted_codes() -> set[str]:
    """Every violation code the Python checker can put in a verdict.

    Read out of the source rather than typed, because a list of codes maintained by hand
    beside a checker that grows is a list that stops being the codes.
    """
    source = CHECKER.read_text(encoding="utf-8")
    flagged = set(re.findall(r'flag\(\s*"([A-Z_]+)"', source))
    dicts = set(re.findall(r'"code":\s*"([A-Z_]+)"', source))
    emitted = flagged | dicts
    assert len(emitted) >= 8, sorted(emitted)
    return emitted


def _codes_in(payload: dict) -> set[str]:
    return {v["code"] for row in payload["rows"] for v in row["violations"]}


def test_the_answer_key_is_what_the_current_python_checker_decides():
    """The generator's own `--check`, run as a subprocess so the comparison is on bytes."""
    proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_answer_key_names_the_checker_that_produced_it(golden):
    """A digest of the file, so an edit to the checker invalidates the key immediately."""
    import hashlib

    digest = hashlib.sha256(CHECKER.read_bytes()).hexdigest()
    assert golden["checker"] == "pipeline/tracetriage/explain.py"
    assert golden["checker_sha256"] == digest, (
        "the answer key was generated from a different version of the checker. Run "
        "scripts/export_grounding_golden.py."
    )


def test_the_answer_key_holds_rows_in_both_directions(golden):
    """A key of refusals only is passed by a port that refuses everything."""
    refused = [row for row in golden["rows"] if not row["ok"]]
    grounded = [row for row in golden["rows"] if row["ok"]]
    assert len(golden["rows"]) == golden["n_rows"]
    assert len(refused) >= 100, f"only {len(refused)} refusals"
    assert len(grounded) >= 100, (
        f"only {len(grounded)} grounded rows. A checker that refuses everything catches "
        f"every invention and is useless, and this is the half of the key that says so."
    )


def test_the_answer_key_records_what_it_could_not_cover(golden):
    """A shrinking observation set is how a parity check quietly stops checking."""
    assert golden["n_observations"] >= 20, golden["n_observations"]
    assert len(golden["observations"]) == golden["n_observations"]
    for skip in golden["skipped"]:
        assert skip["reason"] in {"no queue entry", "no fit"}, skip


def test_every_code_the_checker_can_emit_is_named_in_the_port():
    """The direction that ages badly: a rule added in Python and never ported."""
    port = PORT.read_text(encoding="utf-8")
    missing = sorted(code for code in _emitted_codes() if code not in port)
    assert not missing, (
        f"the Python checker can emit {missing} and apps/web/lib/grounding.ts does not "
        f"name it, so the browser would accept a draft the pipeline refused"
    )


def test_every_code_is_covered_by_the_key_or_by_a_named_case_in_the_port(golden):
    """The exemption is one code, and it has to be exercised somewhere."""
    emitted = _emitted_codes()
    covered = _codes_in(golden)
    uncovered = emitted - covered
    assert uncovered == UNEXERCISED_BY_THE_KEY, (
        f"the answer key exercises {sorted(covered)} and the checker can emit "
        f"{sorted(emitted)}. Anything uncovered has to be either in the key or in the "
        f"exemption above with the reason it cannot be."
    )
    port_tests = PORT_TESTS.read_text(encoding="utf-8")
    for code in UNEXERCISED_BY_THE_KEY:
        assert code in port_tests, (
            f"{code} is exempt from the answer key and is not tested in "
            f"apps/web/tests/grounding.test.ts either, so nothing checks it at all"
        )


def test_the_key_carries_the_packet_each_row_was_checked_against(golden):
    """A verdict with no packet is a verdict a reader cannot re-derive."""
    packets = {int(p["obs_id"]) for p in golden["packets"]}
    assert packets == set(golden["observations"])
    for packet in golden["packets"]:
        assert packet["text"].count("\n") >= 20, packet["obs_id"]
        assert " : " in packet["text"]
    for row in golden["rows"]:
        assert int(row["obs_id"]) in packets, row["obs_id"]


def test_the_violations_carry_the_literal_structurally(golden):
    """A consumer that splits a message to recover a value is one edit from silence."""
    numeric = [
        v
        for row in golden["rows"]
        for v in row["violations"]
        if v["code"] in {"UNGROUNDED_NUMBER", "MISLOCATED_TIME_CLAIM"}
    ]
    assert numeric, "no numeric violation in the key"
    for violation in numeric:
        assert violation.get("literal"), violation
        assert "unit" in violation, violation


def test_the_console_actually_runs_the_port():
    """A checker nobody can reach is a test fixture, not a feature.

    The port existed for a while with a full suite around it and no page importing it, which
    is the state this catches: every claim about a reader being able to edit a digit and
    watch the refusal was true of the tests and of nothing a reader can open.
    """
    component = REPO / "apps" / "web" / "components" / "ClaimChecker.tsx"
    page = REPO / "apps" / "web" / "app" / "observation" / "[id]" / "page.tsx"
    assert component.exists(), component
    source = component.read_text(encoding="utf-8")
    assert source.startswith('"use client"'), (
        "the checker runs in the browser or it runs nowhere: this console is a static "
        "export and there is no server to ask"
    )
    for symbol in ("buildPacket", "verifyNote", "@/lib/grounding"):
        assert symbol in source, symbol
    assert "ClaimChecker" in page.read_text(encoding="utf-8"), (
        "apps/web/components/ClaimChecker.tsx is not on the observation page"
    )
