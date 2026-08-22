"""The Bob unit count is a count of units, not of markdown headings.

The defect this pins. `scripts/sync_for_judges.py` derived the number of Bob build-log
entries with ``line.startswith("## ")`` minus two structural titles. That counts
"## A3. Doppler correction status resolver" and "## Operator-side hardening", which are
undated narrative sections, and it skips every unit written at "### " depth, which is
where all ten Bob-account units live. It reported 60. Ten units carry a Bob account in
their heading and 46 carry an operator or a review wave. The published number was
therefore neither figure: it was the number of second-level headings in one file, quoted
in the paragraph a judge reads to score Best Technical Use of IBM Bob.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_LOG = REPO / "docs" / "BOB_BUILD_LOG.md"


@pytest.fixture(scope="module")
def sync_module():
    # The generator imports its sibling scripts by name, the way it is run from the
    # repository root. Without the path entry the fixture fails on an import that
    # works perfectly in the command this test exists to protect.
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "sync_for_judges", REPO / "scripts" / "sync_for_judges.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _headings() -> list[str]:
    return [
        line
        for line in BUILD_LOG.read_text(encoding="utf-8").splitlines()
        if re.match(r"^#{2,3}\s", line)
    ]


def test_every_counted_unit_has_a_date_and_a_bob_account(sync_module):
    bob, _ = sync_module._build_log_units()
    counted = set(bob)
    assert counted, "no Bob-account unit was found, so the regex has stopped matching"

    for line in _headings():
        match = sync_module._BUILD_LOG_UNIT_RE.match(line)
        if match and match.group("unit") in counted:
            actor = match.group("actor").strip()
            assert sync_module._BOB_ACCOUNT_RE.match(actor), (
                f"{line!r} was counted as a Bob unit but its actor field says {actor!r}"
            )


def test_the_operator_side_unit_is_not_counted_as_bob(sync_module):
    """A0b says "Operator side, no Bob account" in its own heading."""
    bob, operator = sync_module._build_log_units()

    assert "A0b" not in bob
    assert "A0b" in operator
    # A0b-INT is a different unit: an integration review that did run in Bob.
    assert "A0b-INT" in bob


def test_the_review_waves_are_not_counted_as_bob(sync_module):
    """Wave D and Wave E ran from Cursor and Claude Code, not from a Bob account."""
    bob, operator = sync_module._build_log_units()

    for unit in ("D13", "D15", "E1", "E8"):
        assert unit not in bob, f"{unit} was authored operator-side"
    assert len(operator) >= 40


def test_a_structural_or_undated_heading_is_counted_as_neither(sync_module):
    bob, operator = sync_module._build_log_units()
    counted = set(bob) | set(operator)

    for title in ("A3", "C2", "C5", "C7"):
        # These sections exist in the file as undated narrative titles. A unit id in a
        # heading is not enough: the count needs a date and an actor.
        assert title not in counted, (
            f"{title} is an undated section title and must not be counted as a unit"
        )
    assert "## Format" not in counted
    assert "## Entries" not in counted


def test_the_template_line_is_not_a_unit(sync_module):
    """The Format section shows the heading shape and must not count as a unit."""
    template = "### <date IST> | <account #> | <unit id>: <title>"
    assert template in BUILD_LOG.read_text(encoding="utf-8")
    assert sync_module._BUILD_LOG_UNIT_RE.match(template) is None


def test_the_published_number_is_the_bob_unit_count(sync_module):
    """FOR_JUDGES carries the number the counter produces, not a typed one."""
    published = (REPO / "FOR_JUDGES.md").read_text(encoding="utf-8")
    bob, operator = sync_module._build_log_units()

    assert f"{len(bob)} dated Bob-account units" in published
    assert f"A further {len(operator)} dated" in published
    # Every counted unit id is named, so the number cannot be checked without the list.
    for unit in bob:
        assert unit in published, f"unit {unit} is counted but not named for the judge"


def test_the_old_heading_count_is_still_reported_as_the_correction(sync_module):
    """The move from 60 to 10 carries its cause with it."""
    published = (REPO / "FOR_JUDGES.md").read_text(encoding="utf-8")

    assert str(sync_module._OLD_HEADING_COUNT) in published
    assert "second-level markdown headings" in published
def test_the_readme_says_the_same_thing_as_the_log(sync_module):
    """The two judge-facing documents cannot disagree about who built what.

    They did. `FOR_JUDGES.md` carried the counted accounting while `README.md` said Bob
    "builds every load-bearing subsystem: ingestion, physics, model interface, calibration,
    abstention, ranking, the evidence console, the test suite", which names five things the
    log attributes to the operator. Two blind readers found it independently and both said it
    was the weakest thing in the entry, because the criterion it overclaims against is the one
    that leads on Bob. Only `FOR_JUDGES.md` was checked, so only `FOR_JUDGES.md` stayed true.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    bob, operator = sync_module._build_log_units()

    assert f"{len(bob)} dated" in readme, (
        "README.md does not state the counted number of Bob units, so it can drift from the "
        "log again"
    )
    assert f"A further {len(operator)} dated" in readme
    for unit in bob:
        assert unit in readme, f"unit {unit} is counted but not named in README.md"
    for claim in ("builds every load-bearing subsystem", "every load-bearing subsystem"):
        assert claim not in readme, (
            f"README.md is back to claiming {claim!r}, which the build log contradicts: the "
            "console, the calibration and abstention blocks and the fusion ladder are "
            "operator-side in the actor field of their own headings"
        )


def test_the_readme_and_the_spec_agree_on_how_many_tools_exist():
    """The count of built tools is read from the specification, not typed twice.

    README said five built and five unbuilt, `FOR_JUDGES.md` said twelve and four, and the
    specification says twelve and four. A reader who checks one document against the other
    finds a contradiction before they find a tool.
    """
    import re

    spec = (REPO / ".bob" / "TOOL_SPECS.md").read_text(encoding="utf-8")
    head, _, tail = spec.partition("## Specified and not implemented")
    assert tail, ".bob/TOOL_SPECS.md no longer separates the built tools from the unbuilt ones"

    built = len(re.findall(r"^### `[a-z_]+`", head, flags=re.MULTILINE))
    unbuilt = len(re.findall(r"^### `[a-z_]+`", tail, flags=re.MULTILINE))
    assert built and unbuilt, f"read {built} built and {unbuilt} unbuilt tool headings"

    # Each document is held to its own wording rather than to an either-or, because a check
    # that accepts either phrase passes when one document carries both numbers and the other
    # carries none, which is the shape of the defect this is here for.
    expected = {
        "README.md": (f"{built} tools that exist", f"{unbuilt} that were specified and were not"),
        "FOR_JUDGES.md": (f"the {built} that", f"{unbuilt} that were specified and were not"),
    }
    for document, (built_phrase, unbuilt_phrase) in expected.items():
        text = (REPO / document).read_text(encoding="utf-8")
        assert built_phrase in text, (
            f"{document} does not say {built_phrase!r}, so it does not state the {built} tools "
            "the specification implements"
        )
        assert unbuilt_phrase in text, (
            f"{document} does not say {unbuilt_phrase!r}, so it does not state the {unbuilt} "
            "tools that were specified and not built"
        )
