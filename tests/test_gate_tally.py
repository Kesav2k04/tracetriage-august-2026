"""The standing-gate tally is a published number, so it has to say what it counted.

`scripts/gate.py` prints one line at the end, `scripts/signoff.py` keeps that line as the
`detail` of its "standing gates" row, and `artifacts/SIGNOFF_RECEIPT.json` publishes it.
The gate counts rows it could actually ask: a check whose precondition is absent is
omitted rather than failed, because a FAIL there would manufacture a regression on every
clean clone. That is right, and it had one consequence nobody had written down. The
omission moved the denominator too, so the published receipt read `30/30 standing gates
pass` on a machine where the same script prints `32/32`, and nothing in the receipt said a
row had been dropped. An outside reviewer found the discrepancy by comparing three commits
and the count of `results.append` in the source.

These tests hold the disclosure in place: the count is stated, it fits inside what the
sign-off keeps, no future omission can bypass the counter, and the one consumer that
parses the line still matches it.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE_SRC = REPO / "scripts" / "gate.py"
SIGNOFF_SRC = REPO / "scripts" / "signoff.py"


def _load(name: str, path: Path):
    """Execute a script by path, without publishing it under an importable name.

    `sys.modules[name] = module` here cost an hour. `tests/test_langchain_tools.py`
    asserts that the adapter offers the MCP server's own function objects, by identity,
    and it reaches the server with `from mcp_server import TOOLS` off `scripts/` on the
    path. Registering a freshly executed copy under that key handed it a second module
    whose functions were equal and not identical, so its assertion failed with two
    addresses for `tool_queue_top`. It failed only in a whole-suite run, and only when
    this file ran first, which is the worst shape a failure can have. Nothing here needs
    the module to be importable, so nothing here registers one.
    """
    spec = importlib.util.spec_from_file_location(f"_gate_tally_{name}", path)
    assert spec and spec.loader
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load("gate", GATE_SRC)


def _omit_call_labels() -> list[str]:
    """Every literal label `gate.py` passes to `omit`, read out of the source.

    Read rather than listed, so a row added later is covered without editing this file.
    Non-literal arguments (a loop variable, a sliced reason) are skipped here and covered
    by the length test's synthetic worst case instead.
    """
    tree = ast.parse(GATE_SRC.read_text(encoding="utf-8"))
    labels: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "omit"):
            continue
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            value = node.args[1].value
            if isinstance(value, str):
                labels.append(value)
    return labels


def test_no_omission_adds_no_suffix(gate):
    """A complete run must not carry a sentence about omissions it did not have."""
    line = gate.tally_line(32, 32, [])
    assert line == "32/32 standing gates pass"
    assert "omitted" not in line


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 9])
def test_every_omission_count_reaches_the_line(gate, count):
    """The number is the disclosure. It is stated whether or not the names fit."""
    line = gate.tally_line(30, 30, [f"check {i}" for i in range(count)])
    assert line.startswith("30/30 standing gates pass, ")
    assert f", {count} row" in line
    assert "omitted for a missing precondition" in line
    # Singular and plural, because "1 rows omitted" in a published receipt is the kind of
    # detail that makes a reader distrust the number next to it.
    assert (" 1 row " in line) == (count == 1)


def test_the_line_fits_what_the_signoff_keeps(gate):
    """Every real combination of omissions has to survive the receipt's truncation.

    `signoff.py` slices the line it keeps. A tally longer than that slice reaches the
    published receipt as half a sentence, and the half that would be cut is the half that
    says the count is incomplete.
    """
    labels = _omit_call_labels()
    assert labels, "gate.py should route its omitted rows through omit()"
    for size in range(1, len(labels) + 1):
        for combination in itertools.combinations(labels, size):
            line = gate.tally_line(32 - size, 32 - size, list(combination))
            assert len(line) <= gate._SIGNOFF_DETAIL_CAP, (len(line), line)


def test_the_cap_is_the_number_the_signoff_actually_truncates_to(gate):
    """Two files, one constant. Held together here rather than by a comment.

    The cap is a guess about another script's behaviour, and a guess that drifts is worse
    than no cap: the tally would be trimmed to fit a limit that had moved, and the trimming
    would happen in the receipt rather than here.
    """
    source = SIGNOFF_SRC.read_text(encoding="utf-8")
    found = re.search(r"def _last_useful_line.*?\[:(\d+)\]", source, re.S)
    assert found, "signoff.py no longer truncates in _last_useful_line"
    assert int(found.group(1)) == gate._SIGNOFF_DETAIL_CAP


def test_no_omitted_row_bypasses_the_counter():
    """An omission printed with a bare `print` is invisible to the tally.

    This is the regression that matters. The four omitted rows were each printed by hand
    for months, and the tally could not have known about them. A fifth added the same way
    would silently restore the defect, and every other test here would still pass.
    """
    tree = ast.parse(GATE_SRC.read_text(encoding="utf-8"))
    omit_def = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "omit"
    )
    inside_omit = {id(n) for n in ast.walk(omit_def)}

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "print" or id(node) in inside_omit:
            continue
        printed = "".join(
            part.value
            for arg in node.args
            for part in ([arg] if isinstance(arg, ast.Constant) else getattr(arg, "values", []))
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
        if "[ -- ]" in printed:
            offenders.append(node.lineno)
    assert not offenders, (
        "these lines print an omitted row without recording it, so the tally cannot "
        f"disclose it: {offenders}. Call omit(omitted, name, reason) instead."
    )


def test_the_film_precondition_omits_both_of_its_rows():
    """One precondition, two checks. The count has to be two.

    `presentation/node_modules` gates both the vitest run and the report `--check`, and the
    absent-directory branch used to print a single row naming only the first. The tally was
    then short by one on every clean clone, which is the same defect one level down.
    """
    source = GATE_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source)
    labels = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "film_checks":
            labels = [
                element.elts[0].value
                for element in node.value.elts
                if isinstance(element, ast.Tuple)
            ]
    assert len(labels) == 2, labels
    assert "for label, _argv in film_checks:" in source


def test_the_parser_that_reads_this_line_still_reads_it(gate):
    """The tally has one machine consumer, and its pattern was anchored to end of line.

    `scripts/mcp_server.py` returns the tally to an agent asking whether the gates pass.
    With `$` on the end it matched only the runs with nothing omitted, so the runs that
    most needed the count would have reported no tally at all.
    """
    server = _load("mcp_server", REPO / "scripts" / "mcp_server.py")
    for omitted in ([], ["artifacts match their builders"]):
        line = gate.tally_line(31, 31, list(omitted))
        found = server._GATE_TALLY.search(f"  [PASS] lint\n\n{line}\n")
        assert found, line
        assert found.group(0) == line
        assert found.group(1) == "31" and found.group(2) == "31"
