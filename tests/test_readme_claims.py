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
}


def _readme_paths() -> list[str]:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    out: list[str] = []
    for token in _PATH_RE.findall(text):
        if token in _NOT_A_PATH or token.startswith(("http", "-", "--")):
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
