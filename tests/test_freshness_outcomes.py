"""The freshness check has three outcomes, and a missing snapshot is not a failure.

The defect this pins. `scripts/check_artifact_freshness.py` rebuilds every committed
artifact from the snapshot and diffs it, and the snapshot is 20 GB, lives outside the
repository and is named by TRACETRIAGE_PAGES_DIR. With the variable unset,
`scripts/build_splits.py` refuses by design, and the checker reported
`[FAIL] the builder itself does not run`. Nothing was stale. The snapshot was simply not
configured in that environment, and the row it produced in `scripts/gate.py` was a red
cross for a question nobody could ask there.

So the three outcomes are asserted separately, because collapsing any two of them is the
defect: a snapshot that is absent must not read as an artifact that is wrong, and a builder
that genuinely crashed must not read as a snapshot that is absent. The second half is the
one that is easy to get wrong in the fixing direction, and `test_a_real_crash_still_fails`
is what stops the third outcome from swallowing every failure the check exists to find.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / "scripts" / "check_artifact_freshness.py"
GATE = REPO / "scripts" / "gate.py"
PY = REPO / ".venv" / "Scripts" / "python.exe"

#: The refusal, as the builder actually prints it. Copied from a real run rather than
#: paraphrased: the classifier reads this text, so a fixture that reads plausibly but is
#: not what the builder emits would test the classifier against fiction.
_REAL_REFUSAL = """Building splits with seed=42 ...
Traceback (most recent call last):
  File "scripts\\build_splits.py", line 85, in main
    pages_dir = args.pages_dir or _default_pages_dir()
pipeline.tracetriage.splits.SplitsPathNotConfigured: no pages directory was given. Pass \
pages_dir (the CLI flag is --pages-dir) or set TRACETRIAGE_PAGES_DIR to the snapshot's \
pages folder."""

#: A real crash, from the same builder pointed at a directory with no pages in it. It is
#: the shape the third outcome must not absorb.
_REAL_CRASH = """Building splits with seed=42 ...
Traceback (most recent call last):
  File "pipeline\\tracetriage\\splits.py", line 482, in _build_chronological_split
    "train_time_start": sorted_rows[0]["start_iso"],
IndexError: list index out of range"""

_NEEDS_VENV = pytest.mark.skipif(
    not PY.exists(),
    reason=(
        "the checker spawns every builder with .venv/Scripts/python.exe by name and "
        "refuses without it, so on a checkout with no Windows venv these two would be "
        "measuring the refusal rather than the outcome"
    ),
)


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("check_artifact_freshness", CHECKER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(pages_dir: str | None) -> subprocess.CompletedProcess:
    """The checker, with TRACETRIAGE_PAGES_DIR set to something or removed outright."""
    env = {k: v for k, v in os.environ.items() if k != "TRACETRIAGE_PAGES_DIR"}
    if pages_dir is not None:
        env["TRACETRIAGE_PAGES_DIR"] = pages_dir
    return subprocess.run(  # noqa: S603  (fixed argv, no shell)
        [str(PY), str(CHECKER)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_the_three_outcomes_are_three(checker, monkeypatch):
    """A builder either ran, refused for want of the snapshot, or crashed.

    The environment is set explicitly here because it is part of the contract, not context.
    An unconfigured verdict requires the variable to be genuinely absent, so a test that
    inherited whatever the developer happened to export would pass or fail by accident.
    """
    monkeypatch.delenv("TRACETRIAGE_PAGES_DIR", raising=False)
    assert checker._builder_outcome(0, "") == checker.RAN
    assert checker._builder_outcome(1, _REAL_REFUSAL) == checker.NOT_CONFIGURED
    assert checker._builder_outcome(1, _REAL_CRASH) == checker.CRASHED


def test_a_variable_set_to_a_bad_path_is_a_failure_and_not_a_skip(checker, monkeypatch):
    """The fourth outcome, and the one that bit.

    `_default_pages_dir` raises the same `SplitsPathNotConfigured` whether the variable is
    absent or set to something that is not a directory, and both messages carry the class
    name and the variable name. A classifier reading only the traceback therefore called a
    typo "not measurable here", exited 0, and left the freshness check disabled with the gate
    still green. That is worse than the defect the skip was added to fix.

    Set means asked. An operator who supplies an address has asked for a measurement, and a
    bad address is a failure.
    """
    monkeypatch.setenv("TRACETRIAGE_PAGES_DIR", "/d/definitely-not-here-xyz")
    assert checker._builder_outcome(1, _REAL_REFUSAL) == checker.CRASHED

    # Empty and whitespace are not addresses, so they are still absent.
    for blank in ("", "   "):
        monkeypatch.setenv("TRACETRIAGE_PAGES_DIR", blank)
        assert checker._builder_outcome(1, _REAL_REFUSAL) == checker.NOT_CONFIGURED


def test_a_crash_with_nothing_to_say_is_still_a_crash(checker):
    """No output is the least informative failure and the one most likely to be misread.

    A classifier that decided by absence would call a killed process "not configured",
    which is how a real defect earns a green tick.
    """
    assert checker._builder_outcome(1, "") == checker.CRASHED
    assert checker._builder_outcome(137, "Killed") == checker.CRASHED


def test_naming_the_variable_alone_does_not_buy_a_skip(checker):
    """Both the exception class and the variable have to be in the output.

    The builder prints the variable's name in its own `--help` and in its startup banner,
    so a scanner looking for the name alone would grant an unconfigured verdict to any
    crash that happened to echo the usage text.
    """
    banner = (
        "Building splits with seed=42 ...\n"
        "  Pages dir:  from TRACETRIAGE_PAGES_DIR\n"
        "ZeroDivisionError: division by zero"
    )
    assert checker._builder_outcome(1, banner) == checker.CRASHED


#: What a skip is allowed to be waiting for, and nothing else. A `[SKIP]` line has to name
#: the thing that would let the builder run, or a reader cannot act on it and cannot tell a
#: designed refusal from a swallowed error. Three entries, one per input a clone legitimately
#: lacks: the 20 GB snapshot, addressed by the variable; the trained model, which
#: `artifacts/**/*` excludes; and the OCR backend, which the offline replay leaves out of its
#: install because easyocr pulls torch. Every one of the three was found by a clean clone
#: reporting it as a stale artifact. A fourth entry is a deliberate act rather than a
#: formality: it means a new class of input is missing from a clone, and the question to ask
#: first is whether the repository should be publishing it.
#:
#: The model-absent branch is not exercised from here, and that is stated rather than left
#: to be discovered. This machine has the pickle, and the only ways to hide it from a
#: subprocess are to move a file the repository does not track, which leaves the tree broken
#: if the test is interrupted, or to add an environment variable to the checker that exists
#: for the test. Both cost more than they buy: the run that finds a regression here is
#: `scripts/clean_clone_check.py`, which builds an environment that genuinely lacks the file,
#: and `artifacts/CLEAN_CLONE_TRANSCRIPT.json` carries its output. It found this defect.
_WHAT_A_SKIP_MAY_BE_WAITING_FOR = (
    "TRACETRIAGE_PAGES_DIR",
    "artifacts/hoglr_model.pkl",
    "OCR backend",
)


@_NEEDS_VENV
def test_a_missing_snapshot_skips_and_costs_nothing():
    """Exit 0, a [SKIP] line per builder that cannot start, each naming what it needs.

    The count is not pinned to one any more. It was, and that encoded "exactly one builder
    needs the snapshot", which held until a satellite-name exporter was added beside the
    split builder. Two correct skips then failed a test whose point was that a skip is not
    a failure.

    The assertion then required every skip to name `TRACETRIAGE_PAGES_DIR`, which encoded
    the next assumption: that the snapshot is the only thing a clone can be missing. It is
    not. `artifacts/hoglr_model.pkl` is excluded by `artifacts/**/*`, the triage slice reads
    it rather than training one, and without it the slice writes a receipt whose
    `model_checksum` is null and fails its own schema. On a fresh clone that printed [FAIL]
    and this test failed on a builder behaving correctly. So what is required is that each
    skip names something from a short, explicit list of things a clone can legitimately lack.
    """
    finished = _run(None)
    out = finished.stdout or ""
    assert finished.returncode == 0, out + (finished.stderr or "")
    skips = [line for line in out.splitlines() if line.startswith("[SKIP]")]
    assert skips, out
    for skip in skips:
        assert any(need in skip for need in _WHAT_A_SKIP_MAY_BE_WAITING_FOR), skip
    assert "[FAIL]" not in out, out
    # "nothing it owns" rather than "nothing here". The old wording said "nothing here is
    # stale", which was true of the whole run only while the script returned at the first
    # builder that could not start. Now that it keeps going, the other builders do run and
    # can find real staleness, so a skip may only speak for the artifacts that skipped
    # builder owns.
    assert "nothing it owns is known to be stale" in out, out


@_NEEDS_VENV
def test_a_skipped_builder_does_not_make_the_run_evidence_of_nothing():
    """A skip has to say what it did compare, and a run that compared nothing must fail.

    This is the assertion the old shape could not carry. The script used to return at the
    first builder that needed the absent snapshot, and that builder ran first, so on every
    machine without the 20 GB snapshot it exited 0 having compared nothing. "Nothing was
    stale" and "nothing was checked" are different sentences, and only one is evidence.
    """
    finished = _run(None)
    out = finished.stdout or ""
    assert finished.returncode == 0, out

    compared = [line for line in out.splitlines() if line.startswith("compared ")]
    assert len(compared) == 1, out
    count = int(compared[0].split()[1].rstrip(":"))
    assert count > 0, (
        "the run reported a pass without comparing anything, which is the defect this "
        f"shape exists to prevent: {out}"
    )
    assert "not compared here" in out, (
        "the skipped builders' artifacts are not named, so a reader cannot tell what "
        f"this run does not cover: {out}"
    )


@_NEEDS_VENV
def test_a_real_crash_still_fails(checker, tmp_path):
    """A configured path with no pages in it is a builder crash, and it must still fail.

    This is the half of the fix that can quietly undo the check. The variable is set, so
    a builder gets past its own refusal and then falls over on an empty table, and that is
    a defect rather than an environment.

    The assertion deliberately names no builder. It used to require the split builder's own
    row, which held only while that builder ran first. A satellite-name exporter was added
    ahead of it, so with a bad path the exporter failed first, the split builder never ran,
    and this test failed while the behaviour it guards was correct. What matters is that a
    configured-but-wrong path produces a failing row, whichever builder gets there first,
    so that is what is checked.

    It also required no `[SKIP]` anywhere in the run, and that was too strong. It held only
    while the snapshot was the one thing a builder could be missing. An environment without
    the OCR extra skips the hero-nulls exporter for a reason that has nothing to do with the
    path under test, so a clean clone failed this test on correct behaviour. What the bad
    path must not do is earn a skip *of its own*: a skip naming the variable would mean the
    checker read "set to a directory with nothing in it" as "not set at all", which is the
    defect this test exists for. So the run must produce a failing row and no skip that
    names the variable.
    """
    finished = _run(str(tmp_path))
    out = (finished.stdout or "") + (finished.stderr or "")
    assert finished.returncode == 1, out
    crashed = [
        line
        for line in out.splitlines()
        if line.startswith("[FAIL]") and "does not run" in line
    ]
    assert crashed, (
        "a configured path with no pages in it produced no crashing builder, so either "
        f"every builder now tolerates an empty snapshot or the row text changed: {out}"
    )
    misread_as_unset = [
        line
        for line in out.splitlines()
        if line.startswith(checker.SKIP_PREFIX) and "TRACETRIAGE_PAGES_DIR" in line
    ]
    assert not misread_as_unset, (
        "the variable is set, to a directory with no pages in it, and a builder skipped "
        f"saying the variable is not set: {misread_as_unset}"
    )


def test_the_gate_looks_for_the_string_the_checker_prints(checker):
    """The two ends of the coupling, compared.

    The gate cannot read an exit code for this, because the skip is not a failure and exits
    0, so it matches on the printed prefix. That makes the prefix an interface between two
    files with nothing to hold it together, and a rename at one end would silently turn
    every skip back into a FAIL row: the exact defect, restored, with both files reading
    correctly on their own.
    """
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    in_gate = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "_FRESHNESS_SKIP" for t in node.targets
        )
        and isinstance(node.value, ast.Constant)
    ]
    assert in_gate == [checker.SKIP_PREFIX], (
        f"scripts/gate.py looks for {in_gate} and the checker prints "
        f"{checker.SKIP_PREFIX!r}"
    )


def test_the_gate_omits_the_row_instead_of_scoring_it():
    """The skip branch must not append to `results`, and the other branch must.

    Counted green it would hide a stale artifact; counted red it manufactures the
    regression this whole change removes. Omitted, the tally at the end of the gate stays
    the number of checks that were actually performed, which is what `n/m` claims to be.
    """
    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    branches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "not_configured"
    ]
    assert len(branches) == 1, "the freshness branch in scripts/gate.py has moved"
    branch = branches[0]

    def appends(body: list[ast.stmt]) -> int:
        return sum(
            1
            for statement in body
            for node in ast.walk(statement)
            if isinstance(node, ast.Attribute)
            and node.attr == "append"
            and isinstance(node.value, ast.Name)
            and node.value.id == "results"
        )

    assert appends(branch.body) == 0, "the omitted row is being scored after all"
    assert appends(branch.orelse) == 1, "the measured row stopped being scored"


def test_the_omitted_row_reads_as_omitted_to_the_tool_that_parses_it():
    """`scripts/mcp_server.py` turns the gate's output into rows, and OMITTED is one.

    The gate prints `[ -- ]` for a check it could not ask, and that server already keeps
    such a row out of both counts. Asserted here because the freshness row is now the
    second thing in this repository that can print one, and the first was a special case
    nobody had generalised.
    """
    spec = importlib.util.spec_from_file_location(
        "mcp_server", REPO / "scripts" / "mcp_server.py"
    )
    assert spec and spec.loader
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)

    printed = (
        "  [PASS] lint\n"
        "  [ -- ] artifacts match their builders  omitted: the split builder needs the "
        "snapshot, and TRACETRIAGE_PAGES_DIR is not set to it here.\n"
        "\n1/1 standing gates pass\n"
    )
    summary = server.summarise_gate_output(printed, 0)
    assert summary["n_omitted"] == 1, summary
    assert summary["n_fail"] == 0, summary
    assert summary["n_pass"] == 1, summary
