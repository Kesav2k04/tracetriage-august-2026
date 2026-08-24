"""Judge-facing prose, checked against the receipts it quotes.

Every generated document here has a ``--check`` that fails on drift, and every one of them
protects only the region between its markers. Fourteen commits on 2026-08-24 corrected
eleven published claims and every single one sat outside a marked region: a gate described
as open after a person had answered it, a film's byte count from a superseded render, an
install line naming an extra that pulls 4.5 GB the judged path does not need. Two outside
reviewers independently ranked "reconcile the prose with the receipts and add a drift test"
as the highest-value work left. This is that test.

**What it is and is not.** It does not read prose. Each rule names a quantity, a pattern
deciding whether a line is talking about that quantity, the shape the value takes in prose,
and the receipt field the value comes from. A line in scope carrying a value of the right
shape has to carry the right one. A line in scope with no value is not a finding, because
plenty of sentences mention the film without giving its size.

**The value is never typed here.** It is read from the receipt at test time, so this file
cannot be the thing that goes stale. A rule whose receipt field disappears fails loudly
rather than passing vacuously.

**Exemptions are named and counted.** A line that deliberately quotes a superseded number
in order to say it was superseded is a legitimate exception, and there are a few. Each
carries the file, enough of the line to find it, and a reason.
``test_no_exemption_is_unused`` fails when one stops matching, which is how an exemption
that outlived its reason gets removed rather than accumulating.

Dated logs are out of scope as a class. ``docs/BOB_BUILD_LOG.md`` and
``docs/OPERATOR_BUILD_LOG.md`` record what was true on a date, and editing an entry to
match today would destroy the thing they exist to be.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts"

#: Dated records. Their entries are true as of their date and must not be edited to match
#: the present. Excluded by name rather than by a heuristic, so adding one is a decision.
_DATED_LOGS = {
    "docs/BOB_BUILD_LOG.md",
    "docs/OPERATOR_BUILD_LOG.md",
    # A pre-registration is a commitment frozen before the measurement, and its whole
    # value is that it was not edited afterwards. E16's "All 3 discriminated" describes
    # the 24-observation sample it was written about, not the 289 that followed.
    "docs/E16_PREREGISTRATION.md",
    "docs/C2_PREREGISTRATION.md",
    "apps/web/public/data/C2_PREREGISTRATION.md",
}

#: Line prefixes that make a line a record of a withdrawn claim rather than a claim.
#: `docs/CLAIM_REGISTER.md` keeps retracted rows on purpose, with the number that was
#: wrong in them, which is the opposite of drift: the register is the evidence that the
#: claim was withdrawn. Handled as a class rather than as an allowlist entry, because
#: there will be more retractions and each one is not a decision to make again.
_HISTORICAL_LINE = ("| Retracted:", "| Withdrawn:", "**Retracted", "*Written while")


def _scanned() -> list[Path]:
    """Tracked markdown a judge can read, minus the dated logs and the test fixtures."""
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    keep = []
    for raw in out.splitlines():
        rel = raw.strip()
        if not rel or rel in _DATED_LOGS:
            continue
        if rel.startswith("internal_docs/") or rel.startswith("tests/"):
            continue
        keep.append(REPO / rel)
    return keep


def _receipt(name: str) -> dict:
    path = ARTIFACTS / name
    if not path.exists():
        pytest.skip(f"artifacts/{name} is absent, so its rules cannot be checked")
    return json.loads(path.read_text(encoding="utf-8"))


def _dig(doc: dict, path: str):
    node = doc
    for part in path.split("."):
        assert isinstance(node, dict) and part in node, (
            f"{path} is not in the receipt any more, so the rule reading it is checking "
            f"nothing. Fix the rule rather than deleting it."
        )
        node = node[part]
    return node


def _digits(text: str) -> str:
    """A number as prose writes it, reduced to its digits, so 11,034,834 == 11034834."""
    return text.replace(",", "").replace("_", "")


@dataclass(frozen=True)
class Rule:
    what: str
    subject: str
    shape: str
    value: str
    why: str

    def scope(self, line: str) -> bool:
        return re.search(self.subject, line, re.IGNORECASE) is not None

    def found(self, line: str) -> list[str]:
        """Every match, with alternation groups flattened to the one that matched.

        ``re.findall`` returns a tuple per match once the pattern has more than one group,
        and the groups that did not participate are empty strings. Taking ``m[0]``
        unconditionally silently dropped every match from a later alternative.
        """
        out: list[str] = []
        for m in re.findall(self.shape, line):
            if isinstance(m, str):
                out.append(m)
            else:
                out.extend(part for part in m if part)
        return out


#: (relative path, a substring of the line, why that line is allowed to differ)
_ALLOWED: tuple[tuple[str, str, str], ...] = (
    # There were three. The first named the sentence rather than the line carrying the
    # numbers, so it matched nothing once the sentence wrapped, and it was redundant with
    # the entry below in any case. `test_no_exemption_is_unused` caught it on the first
    # run this file was executed, which is the whole reason that test exists.
    (
        "presentation/REPORT.md",
        "Not by a byte-identical re-render",
        "names the claim it replaced, for the same reason.",
    ),
    (
        "presentation/REPORT.md",
        "3,540 frames, 4,850,926 bytes, a 275,349-byte poster",
        "the three superseded film numbers, on the line that says they came from the "
        "silent cut. This line is what the paragraph exists for.",
    ),
    (
        "presentation/REPORT.md",
        "is the eight extra frames the retry",
        "the render log prints 4268/4260 because the font-handle retry re-renders a "
        "group. The sentence exists to say the film is 4260 and that ffprobe agrees.",
    ),
)


def _allowed(rel: str, line: str) -> str | None:
    for path, needle, reason in _ALLOWED:
        if rel == path and needle in line:
            return reason
    return None


def _rules() -> list[Rule]:
    film = _receipt("FILM_RECEIPT.json")
    gate3 = _receipt("GATE3_RECEIPT.json")
    grouped = gate3["entity_grouping"]

    render_bytes = _dig(film, "render.bytes")
    poster_bytes = _dig(film, "poster.bytes")
    frames = _dig(film, "composition.frames")
    scored = gate3["observations_scored"]
    hits = round(gate3["discriminating_rate"] * scored)
    groups = grouped["groups_scored"]
    grouped_hits = round(grouped["grouped_discriminating_rate"] * groups)

    return [
        Rule(
            what="the film's size in bytes",
            # `size=` catches the pasted ffprobe block, which is where this went wrong
            # once: it read size=11108910, a number matching neither the film nor the
            # silent cut, and no rule phrased around the word "bytes" would see it.
            subject=r"tracetriage-film\.mp4|the film[^.]{0,60}bytes|"
            r"bytes[^.]{0,30}the film|^size=\d+",
            shape=r"\b\d{1,3}(?:,\d{3}){2,}\b|\b\d{8}\b",
            value=f"{render_bytes:,}",
            why="the byte count published for the file a judge downloads",
        ),
        Rule(
            what="the poster frame's size in bytes",
            # Scoped to the film's poster. Bare "poster" also matched the home page's
            # explainer clip in docs/CLAIM_REGISTER.md, which has its own poster and its
            # own receipt, and reported that as drift.
            subject=r"tracetriage-film-poster|poster frame is|"
            r"poster[^.]{0,40}film|film[^.]{0,40}poster",
            # The lookarounds stop this matching 034,834 inside 11,034,834, which reported
            # the film's own correct byte count as a wrong poster size.
            shape=r"(?<![,\d])\d{3},\d{3}(?![,\d])",
            value=f"{poster_bytes:,}",
            why="the poster is the still a judge sees before pressing play",
        ),
        Rule(
            what="the film's frame count",
            # `Rendered N/M` is its own case. The stale transcript said "Rendered
            # 3544/3540" on a line holding neither the word "frames" nor the word "film",
            # so every phrasing-based subject walked past the most quotable number in it.
            subject=r"(?:composition|film|rendered)[^.]{0,80}frames|frames[^.]{0,40}"
            r"(?:composition|film)|^Rendered \d+/\d+|nb_frames=",
            # Only the denominator of `Rendered N/M`. The numerator is legitimately higher
            # than the film's length whenever the font-handle retry re-renders a group, so
            # checking it would fail on a correct transcript.
            shape=r"^Rendered \d+/(\d{4})|nb_frames=(\d{4})|\b(\d{4})\b(?![/\d])",
            value=str(frames),
            why="the frame count is what fixes the film's length",
        ),
        Rule(
            what="gate 3's scored observations",
            subject=r"gate 3|corridor (?:intersects|lands)",
            # The scored count is the second number in "224 of 289 testable", not the
            # first. Reading the first reported the discriminating count as drift.
            #
            # One to three digits, not three. The sentence that was wrong for weeks said
            # "3 of 3 discriminated", and a three-digit shape cannot see a single-digit
            # claim. A rule that only matches numbers of the size it expects to be right
            # is blind to exactly the drift worth catching.
            shape=r"\d{1,3} of (\d{1,3}) (?:testable|discriminat)|(\d{1,3}) observations "
            r"scored",
            value=str(scored),
            why="the denominator gate 3's bound was computed on",
        ),
        Rule(
            what="gate 3's discriminating observations",
            subject=r"gate 3|corridor (?:intersects|lands)|discriminat",
            # "discriminating" or "discriminated", not "discriminate". The grouped
            # sentence says "32 of the 68 discriminate on every capture", and a looser
            # stem read its 68 as an observation count and reported the correct sentence
            # as drift. The grouped numbers have their own two rules below.
            shape=r"\b(\d{1,3}) discriminat(?:ing|ed)\b",
            value=str(hits),
            why="the numerator gate 3's bound was computed on",
        ),
        Rule(
            what="gate 3's independent episode count",
            subject=r"independent \(station, date\) episodes|station-nights|"
            r"independent episodes",
            shape=r"\b(\d{2}) (?:independent|episodes|station-nights)",
            value=str(groups),
            why="the grouped denominator, which is what the pre-registered plan decides on",
        ),
        Rule(
            what="gate 3's discriminating episode count",
            subject=r"discriminate on every capture",
            shape=r"\b(\d{2}) of the \d{2}\b",
            value=str(grouped_hits),
            why="the grouped numerator",
        ),
    ]


@pytest.fixture(scope="module")
def rules() -> list[Rule]:
    return _rules()


def _findings(
    paths: list[Path], rules: list[Rule], root: Path = REPO
) -> list[tuple[str, str]]:
    """Every line in scope that carries a value of the right shape and the wrong one.

    Returns (rule name, message) so a caller can check which rule fired, not just that
    something did. Taking the root as an argument is what lets the self-test below run the
    real engine over planted files instead of a copy of its logic.
    """
    out: list[tuple[str, str]] = []
    for path in paths:
        rel = path.relative_to(root).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(_HISTORICAL_LINE):
                continue
            for rule in rules:
                if not rule.scope(line):
                    continue
                seen = [s for s in rule.found(line) if s]
                if not seen:
                    continue
                wrong = [s for s in seen if _digits(s) != _digits(rule.value)]
                if not wrong or _allowed(rel, line):
                    continue
                out.append(
                    (
                        rule.what,
                        f"{rel}:{n} gives {', '.join(sorted(set(wrong)))} for {rule.what}, "
                        f"which the receipt says is {rule.value}. ({rule.why})",
                    )
                )
    return out


def test_no_judge_facing_document_quotes_a_superseded_number(rules: list[Rule]) -> None:
    findings = [message for _, message in _findings(_scanned(), rules)]
    assert not findings, "prose disagrees with the receipts it quotes:\n  " + "\n  ".join(
        findings
    )


def test_every_rule_is_actually_exercised(rules: list[Rule]) -> None:
    """A rule matching nothing would not have caught its own defect.

    The failure this prevents is a subject pattern tightened until the test passes. Every
    rule has to find its quantity stated correctly somewhere, or it is decoration.
    """
    unmatched = []
    files = _scanned()
    for rule in rules:
        hits = 0
        for path in files:
            for line in path.read_text(encoding="utf-8").splitlines():
                if rule.scope(line) and any(
                    _digits(s) == _digits(rule.value) for s in rule.found(line) if s
                ):
                    hits += 1
        if hits == 0:
            unmatched.append(f"{rule.what}: expected {rule.value}, matched no line")
    assert not unmatched, (
        "these rules never see their quantity stated correctly, so they are not checking "
        "anything:\n  " + "\n  ".join(unmatched)
    )


def test_no_exemption_is_unused() -> None:
    """An exemption that stops matching has outlived its reason and should go."""
    stale = []
    for rel, needle, reason in _ALLOWED:
        path = REPO / rel
        if not path.exists() or needle not in path.read_text(encoding="utf-8"):
            stale.append(f"{rel}: {needle!r} ({reason})")
    assert not stale, (
        "these exemptions no longer match anything. Delete them rather than leaving a "
        "permission nobody needs:\n  " + "\n  ".join(stale)
    )


#: Two sentences per rule, written the way the real documents write them: one carrying a
#: wrong number and one carrying whatever the receipt says, with `{v}` standing in for the
#: value so this table cannot hardcode it either. Keyed on the rule's `what`, so a rule
#: added without a planted pair fails `test_every_rule_fires_on_planted_drift` rather than
#: joining the suite unproven.
_PLANTED: dict[str, tuple[str, str]] = {
    "the film's size in bytes": (
        "The film, `presentation/out/tracetriage-film.mp4`, is 12,345,678 bytes.",
        "The film, `presentation/out/tracetriage-film.mp4`, is {v} bytes.",
    ),
    "the poster frame's size in bytes": (
        "The poster frame is 999,111 bytes.",
        "The poster frame is {v} bytes.",
    ),
    "the film's frame count": (
        "The film composition is 1234 frames long.",
        "The film composition is {v} frames long.",
    ),
    "gate 3's scored observations": (
        "Gate 3 scored 224 of 301 testable observations.",
        "Gate 3 scored 224 of {v} testable observations.",
    ),
    "gate 3's discriminating observations": (
        "Gate 3 counted 999 discriminating captures.",
        "Gate 3 counted {v} discriminating captures.",
    ),
    "gate 3's independent episode count": (
        "The corpus holds 12 independent (station, date) episodes.",
        "The corpus holds {v} independent (station, date) episodes.",
    ),
    "gate 3's discriminating episode count": (
        "Of those, 11 of the 68 discriminate on every capture.",
        "Of those, {v} of the 68 discriminate on every capture.",
    ),
}


def test_every_rule_fires_on_planted_drift(rules: list[Rule], tmp_path: Path) -> None:
    """A drift test that passes on a clean tree has proved nothing about itself.

    Each rule gets a sentence written the way the documents write it, with the wrong
    number, and has to be the rule that fires on it. Without this, tightening a subject
    pattern until the suite goes green is indistinguishable from fixing a document, and
    that is how a check ends up guarding nothing.
    """
    missing = [r.what for r in rules if r.what not in _PLANTED]
    assert not missing, (
        f"these rules have no planted case, so nothing shows they can fire: {missing}"
    )

    for rule in rules:
        wrong, _ = _PLANTED[rule.what]
        planted = tmp_path / "planted.md"
        planted.write_text(wrong + "\n", encoding="utf-8")
        fired = {what for what, _ in _findings([planted], rules, root=tmp_path)}
        assert rule.what in fired, (
            f"{rule.what} did not fire on {wrong!r}. Either the subject pattern no longer "
            f"matches how the documents write it, or the shape does not match how the "
            f"number is written. A rule that cannot fire is worse than no rule, because "
            f"the suite reports it as coverage."
        )


def test_a_correct_sentence_is_not_a_finding(rules: list[Rule], tmp_path: Path) -> None:
    """The other half. A rule that fires on everything is also useless.

    Each planted sentence is repaired to carry the receipt's own value, and nothing may
    fire. This is what stops a rule from being written so loosely that every document
    mentioning the subject becomes a finding.
    """
    for rule in rules:
        _, template = _PLANTED[rule.what]
        repaired = template.format(v=rule.value)
        page = tmp_path / "repaired.md"
        page.write_text(repaired + "\n", encoding="utf-8")
        fired = [
            m for what, m in _findings([page], rules, root=tmp_path) if what == rule.what
        ]
        assert not fired, (
            f"{rule.what} still fires after the number is corrected to {rule.value}:"
            f"\n  {repaired}\n  {fired}"
        )


#: Lines that were committed and published, taken verbatim from `presentation/REPORT.md` at
#: commit 202dc85, each with the quantity a rule has to see in it. This is the only
#: evidence that the engine catches drift that actually happens rather than drift invented
#: to suit its patterns, and every one of them survived a `--check` on a generated region,
#: a full offline suite and a green CI run.
_SHIPPED_DRIFT: tuple[tuple[str, str], ...] = (
    (
        "Then gate 3, which asked whether that corridor lands on a visible trace: 3 of 3 "
        "discriminated, a 95% lower bound of 0.37 against a threshold of 0.70, NOT "
        "ESTABLISHED.",
        "gate 3's discriminating observations",
    ),
    ("Rendered 3544/3540", "the film's frame count"),
    (
        "Output 4,850,926 bytes, which is 4.63 MiB. The poster frame is 275,349 bytes.",
        "the poster frame's size in bytes",
    ),
    ("size=11108910", "the film's size in bytes"),
    (
        "| `presentation/out/tracetriage-film.mp4` | The film. 11,108,910 bytes, 142.06 s, "
        "1920x1080, 30 fps, h264 video and AAC narration, 48 kHz stereo. |",
        "the film's size in bytes",
    ),
)


def test_it_catches_the_drift_that_actually_shipped(
    rules: list[Rule], tmp_path: Path
) -> None:
    """The regression that matters: five published lines, and the rule each one needs.

    A synthetic planted case proves a rule can fire. It does not prove the rule matches
    how this repository writes the number, which is the thing that went wrong: a pasted
    ffprobe block, a render log, a table cell and a sentence, four different shapes for one
    quantity. Every entry below is a line a reader could have read on the deployed site or
    in the repository.
    """
    for line, expected in _SHIPPED_DRIFT:
        page = tmp_path / "shipped.md"
        page.write_text(line + "\n", encoding="utf-8")
        fired = {what for what, _ in _findings([page], rules, root=tmp_path)}
        assert expected in fired, (
            f"the rule for {expected!r} no longer catches a line that shipped:\n"
            f"  {line}\n"
            f"  rules that did fire: {sorted(fired) or 'none'}"
        )


def test_the_exemption_list_stays_small() -> None:
    """Two today. A drift test whose allowlist grows is a drift test being defeated."""
    assert len(_ALLOWED) <= 6, (
        f"{len(_ALLOWED)} exemptions. Each is a line allowed to disagree with a receipt; "
        f"past a handful the test documents drift rather than catching it."
    )
