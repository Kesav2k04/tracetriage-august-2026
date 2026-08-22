"""FOR_JUDGES.md is generated, and these are the ways it could still lie.

The page exists because a judge reads one file. That makes it the file most worth keeping
honest and the one least likely to be re-derived by hand, so it is generated from the
receipts and this module holds the generator to three things: the committed page is what the
current receipts produce, every path it cites is a path a reader can open, and the two
numbers it chooses between are the conservative ones.

``--check`` is run as a subprocess rather than imported, because the generator reads the
receipts at import time and a test that imported it would measure this process's copy.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_PAGE = REPO / "FOR_JUDGES.md"
_GENERATOR = REPO / "scripts" / "sync_for_judges.py"
_TRANSCRIPT = REPO / "artifacts" / "CLEAN_CLONE_TRANSCRIPT.json"


@pytest.fixture(scope="module")
def page() -> str:
    if not _PAGE.exists():
        pytest.skip("FOR_JUDGES.md has not been generated")
    return _PAGE.read_text(encoding="utf-8")


def _tracked(path: Path) -> bool:
    """Whether git publishes this path. Staged counts, because the index is what ships."""
    finished = subprocess.run(
        ["git", "ls-files", "--error-unmatch", path.relative_to(REPO).as_posix()],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return finished.returncode == 0


def test_the_page_exists_and_git_publishes_it():
    """No skip in this one, deliberately.

    Every other test here skips when the page is absent, so a page that was never generated
    and never committed read as five passes. Absence has to be a failure somewhere or it
    folds into the same outcome as correctness, and the page is the file a judge is most
    likely to open.
    """
    assert _PAGE.exists(), "FOR_JUDGES.md is missing. Run scripts/sync_for_judges.py."
    assert _PAGE.stat().st_size > 2000, "the page is too short to be the page"
    assert _tracked(_PAGE), (
        "FOR_JUDGES.md is not published by git, so it resolves here and 404s on GitHub. "
        "That is the bob_sessions failure with the subject moved one level up."
    )
    assert _tracked(_GENERATOR), "the generator has to be published beside what it generates"


def test_the_committed_page_is_what_the_receipts_produce():
    """The whole point of generating it. A hand edit anywhere fails here."""
    if not _PAGE.exists():
        pytest.skip("FOR_JUDGES.md has not been generated")
    finished = subprocess.run(
        [sys.executable, str(_GENERATOR), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr


def test_every_path_the_page_cites_exists_and_is_published(page: str):
    """A judge following a path has to arrive somewhere.

    Existence is not enough: an untracked file resolves on this machine and 404s on GitHub,
    which is the failure the README had with an empty directory it described as holding
    exported histories.
    """
    # A bare filename is a path claim too, so the extractor takes a known suffix as well
    # as a separator. Requiring a separator let a cited "vercel.json" through unchecked.
    # Two exclusions, each with its reason. `.venv/` is built by the Setup section rather
    # than published, so requiring git to track it would be requiring the wrong thing.
    # `apps/web/node_modules` is cited precisely because the clean-clone run had to borrow
    # it, and a published node_modules would be the defect: the page discloses an unpublished
    # directory on purpose, and this test exists to catch a path a judge cannot reach, not a
    # path the page already says is absent.
    unpublished_on_purpose = (".venv/", "apps/web/node_modules")
    suffixes = (".py", ".json", ".md", ".ts", ".tsx", ".yml", ".toml")
    # Top-level entries this repository actually has. A slash alone does not make a token a
    # path: the page names `ibm/granite-3-8b-instruct`, which is the model id watsonx serves
    # Granite under, and reading it as a path sent this test looking for an `ibm/` directory
    # that has never existed. Requiring the first segment to be something in the tree keeps
    # every real path claim in scope and drops the identifiers that merely contain a slash.
    top_level = {entry.name for entry in REPO.iterdir()}

    def _is_a_path_claim(token: str) -> bool:
        if token.endswith(suffixes):
            return True
        return "/" in token and token.split("/", 1)[0] in top_level

    candidates = {
        token
        for token in re.findall(r"`([^`]+)`", page)
        if " " not in token
        and not token.startswith(("http", "-", *unpublished_on_purpose))
        and _is_a_path_claim(token)
    }
    assert len(candidates) >= 10, f"the extractor found {len(candidates)} paths, so it broke"

    # A pytest node id is a path plus a selector. Splitting on `::` rather than excluding
    # the token, because the file half is still a path claim and the selector half is a
    # claim of its own: the page names a specific test, and a reader who runs it and gets
    # "no tests ran" has been sent somewhere as surely as by a missing file.
    files = {c.split("::", 1)[0] for c in candidates}
    nodes = {c for c in candidates if "::" in c}
    missing = sorted(c for c in files if not (REPO / c).exists())
    unpublished = sorted(c for c in files if (REPO / c).exists() and not _tracked(REPO / c))
    assert not missing, f"the page cites paths that do not exist: {missing}"
    assert not unpublished, f"the page cites paths git does not publish: {unpublished}"

    unfound = []
    for node in sorted(nodes):
        rel, selector = node.split("::", 1)
        name = selector.split("::")[-1].split("[", 1)[0]
        body = (REPO / rel).read_text(encoding="utf-8")
        if f"def {name}(" not in body and f"class {name}" not in body:
            unfound.append(node)
    assert not unfound, f"the page names tests that are not in the files it names: {unfound}"


def test_the_test_count_is_the_one_a_judge_can_reproduce(page: str):
    """Two counts exist and the page has to quote the smaller claim.

    The clean-clone run measures the offline suite twice: once with the snapshot directory
    present, which only this machine has, and once with it hidden, which is a judge's case.
    Quoting the warm column would inflate the number by exactly the tests a judge cannot
    run, so the choice of column is pinned here rather than left to whoever edits next.
    """
    if not _TRANSCRIPT.exists():
        pytest.skip("no clean-clone transcript in this checkout")
    both = json.loads(_TRANSCRIPT.read_text(encoding="utf-8"))[
        "suite_with_and_without_the_snapshot"
    ]
    judges_case = both["without"]
    if judges_case.get("unparsed"):
        pytest.skip("the transcript's hidden-snapshot pass was not parsed")
    quoted = re.search(r"(\d+) passed, (\d+) skipped", page)
    assert quoted, "the page no longer states a test count"
    assert int(quoted.group(1)) == judges_case["passed"], (
        f"the page quotes {quoted.group(1)} passed and the judge's column of the "
        f"transcript says {judges_case['passed']}"
    )
    assert int(quoted.group(2)) == judges_case["skipped"]


def test_the_tally_in_the_page_is_the_one_the_console_published(page: str):
    """What this catches, stated precisely, because an earlier version overclaimed.

    It does not independently recompute the tally. The generator and any recomputation here
    would both call ``build_gate_summary``, so a wrong function produces the same wrong
    number on both sides and proves nothing. Two things it does catch, both of which have
    happened to generated text in this repository: a rendering mistake, where the right
    numbers are printed in the wrong slots, and a disagreement between the page and
    ``provenance.json``, which is a committed file written by a different script on a
    different run, so the page cannot quietly describe a different gate state from the one
    the console shows a reader.
    """
    published = json.loads(
        (REPO / "apps" / "web" / "public" / "data" / "provenance.json").read_text(
            encoding="utf-8"
        )
    )["gate_summary"]
    verdicts = [g["verdict"] for g in published["gates"]]

    # The page is wrapped after interpolation, so the width of a value decides where the
    # line breaks. Normalising whitespace once is what makes the pattern stable.
    #
    # The clauses after "declared before the build," are the ones that have a member, and a
    # category that empties drops out of the sentence rather than rendering as "0 were never
    # run". This asserted all three unconditionally until gate 4 was answered, at which point
    # the generator correctly stopped saying "and 0 were never run" and the test failed for
    # the project succeeding. Each clause is now checked if it is there and required to be
    # absent if its count is zero, which is the property that actually matters.
    flat = " ".join(page.split())
    stated = re.search(r"Of the (\d+) kill gates declared before the build, ([^.]+)\.", flat)
    assert stated, "the page's gate tally sentence no longer parses"
    assert int(stated.group(1)) == published["n_gates"]

    clauses = stated.group(2)
    for count, pattern in (
        (published["n_met"], r"(\d+) (?:was|were) met"),
        (verdicts.count("NOT_ESTABLISHED"), r"(\d+) came back inconclusive"),
        (verdicts.count("OPEN"), r"(\d+) (?:was|were) never run"),
    ):
        found = re.search(pattern, clauses)
        if count:
            assert found, f"the tally omits {pattern!r} while {count} gates are in it"
            assert int(found.group(1)) == count
        else:
            assert not found, (
                f"the tally states {pattern!r} while no gate is in that category, which "
                f"renders as a count of zero in a sentence nobody re-reads"
            )

    # A rendering swap, where the right numbers land in the wrong slots, is only detectable
    # while the numbers differ. That was true when the tally read 6, 2, 3 and 1; with gate 4
    # answered it reads 6, 3, 3 and the two middle slots are equal, so the check reports that
    # it cannot tell them apart rather than passing and implying it could. A test that
    # silently loses its power is worse than one that says so.
    present = [c for c in (published["n_met"], verdicts.count("NOT_ESTABLISHED"),
                           verdicts.count("OPEN")) if c]
    if len(set(present)) != len(present):
        pytest.skip(
            f"two tally counts are equal in this state ({present}), so a rendering swap "
            f"between those slots is undetectable here. The per-clause pairing above still "
            f"holds; this specific check does not apply."
        )


def test_the_page_says_what_was_not_measured(page: str):
    """A submission page that lists only wins is the failure mode this project avoids.

    Not a style check: each of these is a specific published negative, and a page that
    dropped them while keeping the wins would read better and be worse.
    """
    # "OPEN" was in this list and came out when gate 4 was answered. It was standing in for
    # "a gate that produced no number is named as such", and there is no longer such a gate,
    # so requiring the word would require the page to describe a state that ended. What
    # replaced it is the section that explains every gate that is still not met, which is
    # the negative a reader actually needs and which cannot empty while a gate is unmet.
    for required in (
        "not reproducible",
        "NOT_ESTABLISHED",
        "Why the gates that are not met are not met",
        "does not claim",
    ):
        assert required in page, f"the page no longer mentions {required!r}"
