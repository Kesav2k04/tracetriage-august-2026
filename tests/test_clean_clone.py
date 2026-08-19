"""The clean-clone transcript, and the counts it publishes.

The transcript is the answer to "can a judge reproduce this", so a wrong number in it is
worse than a wrong number almost anywhere else: it is a claim about reproducibility that a
reader has no way to check without doing the whole run themselves.

Its suite counts have been wrong twice, both times for the same reason in different clothes.
First they were empty, because the summary line was suppressed and the parser read the tail.
Then they were numbers scraped out of a failing test's own output, which happened to quote
the previous run's counts back, so both columns published 1116 and 30 and matched neither
suite. The tests here feed the parser the shapes that produced each defect.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_TRANSCRIPT = _REPO / "artifacts" / "CLEAN_CLONE_TRANSCRIPT.json"


def _load():
    path = _REPO / "scripts" / "clean_clone_check.py"
    spec = importlib.util.spec_from_file_location("clean_clone_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["clean_clone_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def clone_check():
    return _load()


@pytest.fixture(scope="module")
def transcript() -> dict:
    assert _TRANSCRIPT.exists(), "artifacts/CLEAN_CLONE_TRANSCRIPT.json is missing."
    return json.loads(_TRANSCRIPT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The counts parser
# ---------------------------------------------------------------------------


def test_the_counts_come_from_the_summary_line(clone_check) -> None:
    out = (
        "........................                                             [100%]\n"
        "\n"
        "1232 passed, 6 skipped, 4 deselected, 5 warnings in 227.13s (0:03:47)\n"
    )
    counts = clone_check._pytest_counts(out)
    assert counts["passed"] == 1232
    assert counts["skipped"] == 6
    assert counts["deselected"] == 4
    assert "failed" not in counts


def test_a_failing_test_that_quotes_a_count_does_not_become_the_count(clone_check) -> None:
    """The defect, exactly as it occurred.

    `tests/test_for_judges.py` failed, its assertion printed the committed judges' page, and
    that page carries the sentence "1116 passed, 30 skipped, from the clean clone". The
    parser took the first match in the whole output and published 1116 and 30 as this run's
    numbers, in both columns, matching neither of the two suites that had just run.
    """
    out = (
        "FAILED tests/test_for_judges.py::test_the_committed_page_is_what_the_receipts\n"
        "E   AssertionError: page == generated\n"
        "E     offline suite 1116 passed, 30 skipped, from the clean clone\n"
        "\n"
        "2 failed, 1227 passed, 6 skipped, 4 deselected in 231.33s (0:03:51)\n"
    )
    counts = clone_check._pytest_counts(out)
    assert counts["passed"] == 1227
    assert counts["failed"] == 2
    assert counts["skipped"] == 6
    assert counts["passed"] != 1116


def test_output_with_no_summary_line_says_so_rather_than_guessing(clone_check) -> None:
    """An unparsed run is a named absence, not a run with no tests."""
    out = "collected 0 items\nsome warning text\nand more text with 99 passed in prose\n"
    counts = clone_check._pytest_counts(out)
    assert counts["unparsed"] is True
    assert "why" in counts


def test_the_parser_takes_the_last_summary_when_a_log_holds_two(clone_check) -> None:
    """Two runs in one captured stream is a real shape, and the later one is this run."""
    out = (
        "10 passed in 1.00s\n"
        "...\n"
        "1232 passed, 6 skipped in 227.13s (0:03:47)\n"
    )
    assert clone_check._pytest_counts(out)["passed"] == 1232


def test_the_summary_line_is_published_beside_the_counts(clone_check) -> None:
    """A reader who disagrees with a parsed number can read the line it came from."""
    counts = clone_check._pytest_counts("1232 passed, 6 skipped in 227.13s (0:03:47)\n")
    assert counts["summary_line"] == "1232 passed, 6 skipped in 227.13s (0:03:47)"


# ---------------------------------------------------------------------------
# The committed transcript
# ---------------------------------------------------------------------------


def test_the_transcript_records_a_commit_that_exists(transcript: dict) -> None:
    import subprocess

    commit = transcript["source_commit"]
    kind = subprocess.run(
        ["git", "cat-file", "-t", commit], cwd=str(_REPO), capture_output=True, text=True
    ).stdout.strip()
    assert kind == "commit", f"the transcript names {commit}, which is not a commit here"


def test_the_two_suite_columns_are_measured_separately(transcript: dict) -> None:
    """Hiding the snapshot has to change something, or the second column measured nothing.

    Both columns reading identically is the shape the parser bug produced, and it is also
    what a run that never hid the snapshot would produce, so it is checked rather than
    assumed. The snapshot-bound tests skip when it is hidden, so the skip counts differ.
    """
    with_snapshot = transcript["suite_with_and_without_the_snapshot"]["with"]
    without = transcript["suite_with_and_without_the_snapshot"]["without"]
    assert not with_snapshot.get("unparsed"), with_snapshot
    assert not without.get("unparsed"), without
    assert without["skipped"] > with_snapshot.get("skipped", 0), (
        "hiding the snapshot skipped no additional tests, so either the hiding did not "
        "work or both columns came from the same run"
    )


def test_the_transcript_names_what_it_could_not_regenerate(transcript: dict) -> None:
    """The unit asked for the ones a clean clone cannot rebuild, named rather than failing."""
    bound = transcript["cannot_regenerate_without_the_snapshot"]
    assert bound, "no artifact is recorded as snapshot-bound, which cannot be right"
    for row in bound:
        assert row["artifact"] and row["builder"] and row["needs"]


def test_every_prerequisite_states_why_it_is_not_in_the_repository(transcript: dict) -> None:
    for row in transcript["prerequisites_not_in_the_repository"]:
        assert row["prerequisite"]
        assert len(row["why"]) > 40, row


def test_the_uv_cache_is_recorded_as_a_path_not_as_a_variable_name(transcript: dict) -> None:
    """The offline install depends on a cache, and which cache is the whole question.

    An earlier transcript recorded `UV_CACHE_DIR` or the words "uv's default location". The
    variable was unset, uv resolved to the user profile on C: while this project keeps its
    caches on D:, and the install failed on torch for a reason the transcript could not be
    read to discover.
    """
    caches = [
        row["uv_cache"]
        for row in transcript["prerequisites_not_in_the_repository"]
        if "uv_cache" in row
    ]
    assert caches, "no prerequisite records which uv cache the run resolved against"
    for cache in caches:
        assert cache["resolved"], cache
        assert "exists" in cache
