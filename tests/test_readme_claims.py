"""Every repository path the README names must exist and carry something.

The defect this exists for: `README.md` stated that `bob_sessions/` "holds exported task
histories and screenshots with secrets removed". The directory contained one file,
`.gitkeep`, and git does not publish empty directories, so on GitHub the sentence pointed
at nothing at all. It sat inside the section answering a mandatory submission requirement
and two lines under the words "Bob's work is recorded, not asserted".

`tests/test_claim_drift.py` could not catch it. That test compares numbers against their
receipts, and this was not a number: it was an existence claim, which no check covered.
For a project whose whole argument is that its claims are checkable, the reachable
counter-example is worse than a wrong number, because a reader who finds one stops
believing the others.

So: extract every backticked repository path from the README, and require each one to
exist and to be non-trivial. A directory whose only content is `.gitkeep` counts as empty,
because that is precisely the case that shipped.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: A backticked token that looks like a path this repository should contain: it has a
#: slash or a known extension, and no spaces. URLs, shell commands and glob patterns are
#: excluded because they are not claims about the tree.
_PATH_RE = re.compile(r"`([A-Za-z0-9_./\-]+)`")

_EXTENSIONS = {
    ".py", ".md", ".json", ".ts", ".tsx", ".toml", ".yml", ".yaml", ".png", ".webp",
    ".mp4", ".jsonl", ".pkl", ".txt", ".schema.json",
}

#: Tokens that are backticked in the README and are not repository paths. Each carries
#: its reason, because an exemption with no reason outlives its reason.
_NOT_A_PATH: dict[str, str] = {
    "pytest": "a command",
    "npm": "a command",
    "uv": "a command",
    "ruff": "a command",
    "python": "a command",
    "git": "a command",
    "next": "a command",
    "npx": "a command",
    "with-signal": "a SatNOGS label value",
    "without-signal": "a SatNOGS label value",
    "unknown": "a SatNOGS label value",
    "doppler-correction-per-sec": "a client metadata field name",
    "rigctl-port": "a client metadata field name",
    "samp-rate-rx": "a client metadata field name",
    "rx-freq": "a client metadata field name",
    "waterfall_status": "an API field name",
    "transmitter_downlink_drift": "an API field name",
    "transmitter_invert": "an API field name",
    "max_altitude": "an API field name",
    "NOT_ESTABLISHED": "a verdict value",
    "PRE_PASSED": "a verdict value",
    "OPEN": "a verdict value",
    "UNMEASURED": "a table marker",
    "/api/health/": "a URL path on the deployment; the file is api/health.py",
    "provenance.json": (
        "the file as the deployment serves it, at /data/provenance.json; the tracked copy "
        "is apps/web/public/data/provenance.json and is named in full elsewhere"
    ),
}


#: An image the README embeds, in either markdown or the HTML form GitHub also renders.
#: A broken image is a worse existence claim than a broken path: it renders as a torn icon
#: on the page a judge lands on first, and no backtick check sees it, because an embed is
#: not a backticked token.
_IMAGE_RE = re.compile(r'!\[[^\]]*\]\(([^)\s]+)\)|<img[^>]*\ssrc="([^"]+)"')


def _readme_images() -> list[str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    out: list[str] = []
    for markdown, html in _IMAGE_RE.findall(text):
        token = markdown or html
        if token.startswith(("http://", "https://", "data:")):
            continue
        out.append(token.lstrip("./"))
    return sorted(set(out))


#: Paths the README names that git is not supposed to publish, each with its reason. The
#: interpreter is built by the Setup section rather than committed, so requiring git to
#: track it would be requiring the wrong thing, and requiring it to exist would fail on
#: whichever platform the reader is not on.
_BUILT_NOT_PUBLISHED = (".venv/", "apps/web/node_modules")


def _readme_paths() -> list[str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    out: list[str] = []
    for token in _PATH_RE.findall(text):
        if token in _NOT_A_PATH or token.startswith(("http", "-", "--")):
            continue
        if token.startswith(_BUILT_NOT_PUBLISHED):
            continue
        looks_like_path = "/" in token or Path(token).suffix in _EXTENSIONS
        if not looks_like_path:
            continue
        # A trailing slash is how the README writes a directory.
        out.append(token)
    return sorted(set(out))


def _tracked(rel: str) -> list[str]:
    """What git publishes at this path. The filesystem is not the question here.

    The whole rationale for this test is what a reader finds on GitHub, and the first
    version answered a different question: it walked the local directory. A directory full
    of gitignored files passed, which is the same failure as the one it was written for.
    `media/` is ignored, so naming it in the README would have been green here and invisible
    to every reader.
    """
    out = subprocess.run(
        ["git", "ls-files", "--", rel.rstrip("/")],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def _is_empty(path: Path) -> bool:
    """Empty for the purpose of a README claim.

    A directory holding only `.gitkeep` is empty: git will not publish it, so a reader
    following the reference finds nothing. A zero-byte file is empty for the same reason.
    """
    if path.is_dir():
        real = [p for p in path.iterdir() if p.name != ".gitkeep"]
        return not real
    return path.stat().st_size == 0


def test_the_readme_names_at_least_a_dozen_paths():
    """Guard against the extractor silently matching nothing.

    Without this, deleting the pattern or breaking the regex would make every assertion
    below pass over an empty list, which is the failure mode this project has hit before:
    a check that cannot fail because it compares nothing.
    """
    paths = _readme_paths()
    assert len(paths) >= 12, f"only {len(paths)} paths extracted from the README: {paths}"


@pytest.mark.parametrize("rel", _readme_paths())
def test_every_path_the_readme_names_exists_and_is_not_empty(rel: str):
    target = REPO / rel
    assert target.exists(), (
        f"README.md names {rel!r} and it does not exist. Either create it or stop "
        "naming it: a reader who follows the reference finds nothing, and an existence "
        "claim is as checkable as a number."
    )
    assert not _is_empty(target), (
        f"README.md names {rel!r} and it is empty. A directory holding only .gitkeep is "
        "not published by git at all, so the sentence pointing at it is false on GitHub "
        "even though the path exists locally."
    )
    assert _tracked(rel), (
        f"README.md names {rel!r} and git publishes nothing there. It exists on this "
        "machine and is ignored or unstaged, so a reader following the reference on GitHub "
        "finds nothing, which is the case this test exists for."
    )


def test_the_readme_embeds_the_figures_the_finding_rests_on():
    """A README with no image asks a judge to take the central finding on prose.

    The corrected and uncorrected cases are visually obvious and were invisible in this
    file for the whole build: the two overlays sat in `artifacts/` being cited by a table
    row. This asserts they are embedded, so removing them is a decision someone has to
    make rather than something that happens.
    """
    images = _readme_images()
    assert len(images) >= 2, f"the README embeds {len(images)} images: {images}"


@pytest.mark.parametrize("rel", _readme_images())
def test_every_image_the_readme_embeds_is_published(rel: str):
    target = REPO / rel
    assert target.exists(), (
        f"README.md embeds {rel!r} and it does not exist, so the page renders a broken "
        "image where the evidence should be."
    )
    assert not _is_empty(target), f"README.md embeds {rel!r} and it is a zero-byte file."
    assert _tracked(rel), (
        f"README.md embeds {rel!r} and git publishes nothing there, so the image resolves "
        "on this machine and nowhere else."
    )


@pytest.mark.parametrize("rel", _readme_images())
def test_every_embedded_image_carries_alt_text(rel: str):
    """An image with no alt text is unreadable to a screen reader and to a broken link.

    The overlays carry the finding, so their description is content rather than decoration.
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    if f"]({rel})" in text or f"](./{rel})" in text:
        markdown_alts = re.findall(r"!\[([^\]]*)\]\(" + re.escape(rel) + r"\)", text)
        assert any(alt.strip() for alt in markdown_alts), f"{rel} is embedded with empty alt text"
        return
    tag = next(
        (m for m in re.findall(r"<img[^>]*>", text) if f'src="{rel}"' in m),
        None,
    )
    assert tag is not None, f"{rel} was extracted as an image and no tag carries it"
    alt = re.search(r'alt="([^"]*)"', tag)
    assert alt and alt.group(1).strip(), f"{rel} is embedded with no alt attribute"


#: The README's own table of MCP surfaces, one row per server, keyed by the server name it
#: backticks in the first cell. Parsed rather than quoted, because the claim under test is
#: about the row a reader sees and not about a string kept here.
def _mcp_rows() -> dict[str, str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    rows: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*`(tracetriage-[a-z]+)`\s*\|", line)
        if m:
            rows[m.group(1)] = line
    return rows


def test_the_readme_names_the_tools_that_are_actually_auto_approved():
    """`alwaysAllow` is a standing permission, so a wrong list here is a wrong statement
    about what an agent may do to somebody else's API without being asked.

    The defect: the row for `tracetriage-live` listed all five tools and said "The first
    three are the ones in `alwaysAllow`", which named `live_rank_observations`, the one tool
    `tests/test_mcp_server.py::test_the_expensive_live_tools_are_not_auto_approved` exists
    to keep out of that list, and omitted `live_check_claim`, which is in it. The judges'
    page could not carry the same error, because `scripts/sync_for_judges.py` reads the list
    out of `.bob/mcp.json`. This table is written by hand, so nothing compared it.

    The assertion is on the clause that mentions `alwaysAllow`, not on the whole cell: a row
    is free to name a withheld tool and say it is withheld, which is what both rows do, and
    a check that read the whole cell could not tell that apart from claiming it is allowed.
    """
    registered = json.loads((REPO / ".bob" / "mcp.json").read_text(encoding="utf-8"))
    rows = _mcp_rows()
    assert set(rows) == set(registered["mcpServers"]), sorted(rows)

    for server, spec in registered["mcpServers"].items():
        allowed = set(spec.get("alwaysAllow", []))
        assert allowed, f"{server} auto-approves nothing, so this test proves nothing"

        row = rows[server]
        # Clause boundaries are a semicolon or a full stop followed by a space. A bare full
        # stop would split `.bob/mcp.json` in half, which is a path and not a sentence.
        clauses = [c for c in re.split(r";|\.\s", row) if "alwaysAllow" in c]
        assert clauses, (
            f"the README row for {server} does not mention alwaysAllow at all, so a reader "
            "cannot tell which of its tools an agent may call without being asked"
        )
        claim = " ".join(clauses)
        named = set(re.findall(r"`([a-z_]+)`", claim))

        missing = allowed - named
        assert not missing, (
            f"{server}: .bob/mcp.json auto-approves {sorted(missing)} and the README's "
            f"alwaysAllow clause does not name them: {claim.strip()!r}"
        )
        extra = named - allowed
        assert not extra, (
            f"{server}: the README's alwaysAllow clause names {sorted(extra)}, which "
            f".bob/mcp.json does not auto-approve: {claim.strip()!r}"
        )


#: The sections the challenge's submission requirements name for the repository README.
#: Typed here rather than read from a receipt, because the requirement comes from outside
#: this repository and nothing in the tree could be its source of truth. The two published
#: lists disagree: the Official Rules name three ("Problem statement, AI/technical approach,
#: Solution description") and the challenge page names five. This is the superset, so
#: satisfying it satisfies both, which is the same rule the submission uses everywhere else
#: the two documents differ.
_REQUIRED_SECTIONS = (
    "## Problem statement",
    "## Solution description",
    "## AI approach and architecture",
    "## Selected challenge theme",
    "## How IBM Bob was used",
)

#: How much prose a section needs before it counts as answering anything. Low on purpose:
#: the check is against an empty or stub section, not a judgement about depth.
_MIN_SECTION_CHARS = 200


def _sections(text: str) -> dict[str, str]:
    """Every `## ` heading mapped to the text under it, up to the next `## `."""
    out: dict[str, str] = {}
    current = None
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                out[current] = "\n".join(body)
            current = line.rstrip()
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        out[current] = "\n".join(body)
    return out


def _shortfalls(text: str) -> tuple[list[str], dict[str, int]]:
    """Which required sections are absent, and which are present but nearly empty.

    Split out from the test so the test can be shown to fire. A check that reads one file
    and asserts it is fine has no failing case anyone has seen, which this session spent a
    while learning the hard way.
    """
    found = _sections(text)
    missing = [name for name in _REQUIRED_SECTIONS if name not in found]
    thin = {
        name: len(found[name].strip())
        for name in _REQUIRED_SECTIONS
        if name in found and len(found[name].strip()) < _MIN_SECTION_CHARS
    }
    return missing, thin


def test_the_section_check_fires_on_a_readme_that_would_fail_the_requirement():
    """The self-proof: a renamed heading and an emptied section are both caught.

    The first case is the realistic one. "How IBM Bob was used" is the section a tidy-up
    would most plausibly reword, and the requirement quotes it.
    """
    good = (REPO / "README.md").read_text(encoding="utf-8")
    assert _shortfalls(good) == ([], {}), "the real README should have no shortfall"

    renamed = good.replace("## How IBM Bob was used", "## Building this with Bob")
    missing, _ = _shortfalls(renamed)
    assert missing == ["## How IBM Bob was used"], missing

    lines = good.splitlines()
    start = lines.index("## Problem statement")
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")
    )
    emptied = "\n".join(lines[: start + 1] + ["", "TBD.", ""] + lines[end:])
    missing, thin = _shortfalls(emptied)
    assert not missing, missing
    assert "## Problem statement" in thin, thin


def test_the_readme_carries_every_section_the_submission_requires():
    """The eligibility requirement a rename would break in silence.

    Requirement 3 of the entry is a public repository with a README containing these
    sections. Nothing else in this suite reads a heading, so until this test the entry
    rested on nobody rewording one, and a heading is exactly what gets reworded while
    tidying. The cost of getting it wrong is not a red test, it is a submission judged
    against a section a reader could not find.

    Presence is not enough, so each one also has to carry prose. A heading over nothing
    satisfies a substring search and answers no requirement.
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    missing, thin = _shortfalls(text)
    assert not missing, (
        f"README.md is missing sections the submission requires: {missing}. The headings "
        f"it does have: {sorted(_sections(text))}"
    )
    assert not thin, (
        f"these required sections exist but carry almost nothing, so they answer the "
        f"requirement in name only: {thin}"
    )


def test_the_required_sections_appear_in_the_order_a_reader_needs_them():
    """Problem before solution, solution before architecture.

    Not a stated requirement, which is why this asserts only the two orderings that would
    read as wrong to anyone: a solution described before the problem it answers, and an
    architecture given before the solution it implements. Everything else about the order
    is a choice, and this test does not have an opinion about it.
    """
    text = (REPO / "README.md").read_text(encoding="utf-8")
    at = {name: text.index(name) for name in _REQUIRED_SECTIONS if name in text}
    assert at.get("## Problem statement", -1) < at.get("## Solution description", -1), at
    assert (
        at.get("## Solution description", -1) < at.get("## AI approach and architecture", -1)
    ), at
