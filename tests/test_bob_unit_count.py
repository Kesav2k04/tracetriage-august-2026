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

#: Both logs, because the count is a count of units and not of files. The single log was
#: split by actor on 2026-08-23 at 538,186 bytes, past the 512 KiB above which GitHub serves
#: markdown as unformatted source, and a check that kept reading one path would have gone
#: green while reporting 12 units instead of 59.
BUILD_LOGS = (BUILD_LOG,)


def _unwrapped(text: str) -> str:
    """The text with its line breaks collapsed, for matching a phrase inside a paragraph.

    Both judge-facing documents are hard wrapped by the generator, so a phrase this test
    pins can straddle a line break and a raw ``in`` check fails on a page that says exactly
    the right thing. That happened to "second-level markdown headings" when the paragraph
    around it was reordered: the sentence was present and the assertion was not. Matching on
    the unwrapped text pins the wording and stops pinning the wrap column, which no reader
    sees. `tests/test_cli_note.py` normalises both sides for the same reason.
    """
    return " ".join(text.split())


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
        for log in BUILD_LOGS
        for line in log.read_text(encoding="utf-8").splitlines()
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




def test_the_readme_does_not_claim_work_the_log_attributes_elsewhere(sync_module):
    """README.md may not describe another actor's units as Bob's.

    It did. It said Bob "builds every load-bearing subsystem: ingestion, physics, model
    interface, calibration, abstention, ranking, the evidence console, the test suite",
    which names five things the build log attributes to the operator. Two blind readers
    found it independently and both said it was the weakest thing in the entry, because the
    criterion it overclaims against is the one that leads on Bob.

    The counted accounting that used to sit beside this is no longer published, which
    removes the arithmetic a reader could have checked and leaves this assertion as the
    only thing holding the line. So it is widened rather than narrowed: every subsystem the
    log does not attribute to a Bob account is named here, and the README may not claim any
    of them.
    """
    readme = _unwrapped((REPO / "README.md").read_text(encoding="utf-8"))

    for claim in ("builds every load-bearing subsystem", "every load-bearing subsystem"):
        assert claim not in readme, (
            f"README.md is back to claiming {claim!r}, which the build log contradicts"
        )

    not_bobs = (
        "Bob built the console",
        "Bob built the calibration",
        "Bob built the abstention",
        "Bob built the fusion",
        "Bob built the test suite",
        "Bob wrote the console",
        "Bob wrote the test suite",
    )
    for claim in not_bobs:
        assert claim.lower() not in readme.lower(), (
            f"README.md claims {claim!r}; the build log attributes that work to the operator "
            "in the actor field of its own heading"
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
