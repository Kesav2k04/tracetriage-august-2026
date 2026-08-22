"""The two independent reviews, and whether they describe themselves correctly.

`docs/REVIEW_SPACE.md` and `docs/REVIEW_ENGINEERING.md` are the adversarial pre-ship
reviews. Both open with a count of what they found, and one of them was wrong: the
engineering review said ten SERIOUS while carrying eleven headings, which sat uncorrected
for four days and is logged in `docs/CLAIM_REGISTER.md` under C7h. A summary line that
undercounts a review's own findings is the same class of defect the reviews were
commissioned to find, so it is checked here rather than trusted.

The second property is the status block. A reader opening either file meets a list of
BLOCKING findings with no indication that the work answering them happened, which reads as
a shipped system with open defects. The block naming the build log is what prevents that
reading, so it is asserted rather than left to survive the next edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: The word each review uses for its own counts, and the file it is in.
_REVIEWS = {
    "docs/REVIEW_SPACE.md": {"BLOCKING": "5", "SERIOUS": "9", "MINOR": "11"},
    "docs/REVIEW_ENGINEERING.md": {
        "BLOCKING": "Three",
        "SERIOUS": "eleven",
        "MINOR": "thirteen",
    },
}

_WORDS = {
    "Three": 3,
    "eleven": 11,
    "thirteen": 13,
}


def _stated(word: str) -> int:
    return _WORDS[word] if word in _WORDS else int(word)


@pytest.mark.parametrize("rel", sorted(_REVIEWS))
def test_the_review_counts_its_own_findings_correctly(rel: str) -> None:
    """`grep -c` over the headings, against the number the file states."""
    text = (REPO / rel).read_text(encoding="utf-8")
    for severity, stated in _REVIEWS[rel].items():
        counted = len(re.findall(rf"^### \[{severity}\]", text, flags=re.MULTILINE))
        assert counted == _stated(stated), (
            f"{rel} states {stated} {severity} findings and carries {counted} headings"
        )
        assert stated in text, (
            f"{rel} no longer states its {severity} count in the words this test knows, "
            "so the count and the check have drifted apart"
        )


@pytest.mark.parametrize("rel", sorted(_REVIEWS))
def test_the_review_says_where_its_findings_were_answered(rel: str) -> None:
    """Without this block the file reads as a list of open defects."""
    text = (REPO / rel).read_text(encoding="utf-8")
    assert "What happened to these findings" in text, (
        f"{rel} has no status block, so a reader meets its BLOCKING findings with nothing "
        "saying the work that answers them exists"
    )
    assert "docs/BOB_BUILD_LOG.md" in text, (
        f"{rel} names no file where the answering work is recorded"
    )
    heading = text.index("## Findings")
    assert text.index("What happened to these findings") < heading, (
        f"{rel} puts its status block after the findings, where it is read second"
    )
