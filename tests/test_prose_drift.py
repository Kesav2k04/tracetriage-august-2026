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
cannot be the thing that goes stale, and every rule carries the receipt and the field it
came from in its ``source``. ``test_every_rule_names_where_its_value_came_from`` resolves
each plain path against the receipt on disk; three of the fifteen rules derive their value
by arithmetic and say so in the same string. A rule whose receipt field disappears fails
loudly rather than passing vacuously.

**Fifteen rules.** Ten quantities (the film's bytes, its poster's bytes, its frame count,
the number of receipts it reads, gate 3's scored and discriminating observations, its
episode count and discriminating episodes, its bound and the bar that bound is read
against) and the verdict in each of the five hand-written gate headings.

**Exemptions are load-bearing or they are gone.** The table is empty today, which is a
measurement. Three exemptions lived in it, each written while a rule was still loose, each
naming a real line that deliberately quotes a superseded number. Running the engine over
those exact lines with the table emptied produced zero findings: every one had fallen out of
scope when the subjects were tightened, and each was reading as load-bearing while
suppressing nothing. The old test asked only whether the needle still appeared in the file,
which is how they survived. ``test_every_exemption_suppresses_a_real_finding`` now requires
each one to show the finding it removes.

**Two planted wordings per rule, not one.** Every rule has to fire on a wrong value in two
unlike sentences and stay silent when both are repaired. This exists because of an attack an
outside reviewer named against the single-pair version: narrow a subject until it matches
only the literal current phrasing, say "224 of 289 testable observations", and the planted
test still passes, the exercise test still passes, and a future "223 of 289" walks through.
One rule is template-bound and says so in the table.

Dated logs are out of scope as a class. ``docs/BOB_BUILD_LOG.md`` records what was true on a date, and editing an entry to
match today would destroy the thing they exist to be. The two pre-registrations are out for
the same reason and a stronger one.

**What was declined, and what replaced it.** Both extensions were implemented and run over
the tree before being accepted, because an untested idea about coverage is what put the
eleven wrong claims in these documents.

*Verdict words, loosely scoped: declined.* One rule per gate scoped on ``gate N`` and shaped
on the verdict tokens produced 29 findings over this tree, none of them drift, and four of
its six rules never saw their own verdict stated correctly anywhere. A verdict is a state
with a history these documents deliberately keep (``Gate 3 was PASSED until 2026-08-18``),
one line often names two gates and both their verdicts, and the prose spells them
``PRE-PASSED`` and ``NOT ESTABLISHED`` where the receipt underscores them. Telling a
superseded verdict from a wrong one needs tense, which is reading prose. *Anchored to a
heading: built.* Ten heading lines, no false positives, and gate 3's heading is excluded
because it is generated between comment markers and its own ``--check`` guards it.

*A bare decimal for the bound: declined.* The phrase "95% lower bound" names eight different
quantities here: gate 3's rate, gate 4's rate, pool A's rate, three hypothetical sample
sizes, a four-seed bootstrap spread, and the rung below the closure. Scoped on the phrase it
needs about ten exemptions, and each one is a line where real drift would then pass. *The
bound and its bar as one ordered phrase: built.* "bound of X against a Y" is the sentence
that shipped wrong, publishing the grouped 0.37 as the gate's own bound, and it is the only
place the pair appears outside a generated region.

**Measured against the tree as published.** Pointed at every tracked markdown file from the
commit before the corrections, the engine returns eight findings across seven quantities,
all of them in ``presentation/REPORT.md``. Those documents passed a full offline suite, a
green CI run and a ``--check`` on every generated region at that commit.
``test_it_would_have_found_the_drift_in_the_documents_as_published`` is that run, so the
claim is a test rather than a sentence.
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


#: Counts these documents spell out. Prose writes "ten committed JSON files" where the
#: receipt holds 10, and a rule reading only digits cannot see that sentence at all.
_SPELLED = {
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}


def _digits(text: str) -> str:
    """One value reduced to a comparable form, whatever shape the prose gave it.

    11,034,834 == 11034834 == 11_034_834, "ten" == 10, and PRE-PASSED == PRE_PASSED ==
    "PRE PASSED". Every one of those pairs is the same claim written by a different hand:
    the receipts underscore what a heading hyphenates and what a sentence spaces.
    """
    bare = text.strip().replace(",", "").replace("_", "").replace("-", "")
    return _SPELLED.get(bare.lower(), bare.replace(" ", "")).upper()


@dataclass(frozen=True)
class Rule:
    what: str
    subject: str
    shape: str
    value: str
    #: The receipt and the field the value came from, as a string a reader can follow.
    #: The value is still read at test time by ``_rules``; this is what makes the claim
    #: "nothing here is hardcoded" checkable rather than asserted, and
    #: ``test_every_rule_names_where_its_value_came_from`` reads the receipt back through
    #: it. A derived value says so, with the arithmetic.
    source: str
    why: str

    def scope(self, line: str) -> bool:
        return re.search(self.subject, line, re.IGNORECASE) is not None

    def disagrees(self, written: str) -> bool:
        """Whether one matched string contradicts the receipt.

        Counts compare on their canonical form. A fraction compares at the precision the
        prose chose: a bound of 0.7309344186327931 is written 0.731 in one document and
        0.73 in another, and both are the same claim. Rounding the receipt to the written
        precision accepts both and still rejects the 0.37 that shipped.
        """
        if "." in self.value and "." in written:
            places = len(written.partition(".")[2])
            return round(float(self.value), places) != round(float(written), places)
        return _digits(written) != _digits(self.value)

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
#:
#: Empty, and that is a measurement rather than an omission. Three exemptions lived here,
#: each written while a rule was still loose, and each naming a real line in
#: `presentation/REPORT.md` that deliberately quotes a superseded number. Running the engine
#: over those exact lines with the table emptied produced zero findings: every one of them
#: had stopped being in scope when the subjects were tightened, so all three were suppressing
#: nothing while reading as load-bearing. The old test asked only whether the needle still
#: existed, which is why they survived. `test_every_exemption_suppresses_a_real_finding` now
#: fails on the first exemption that cannot show the finding it removes.
_ALLOWED: tuple[tuple[str, str, str], ...] = ()


def _allowed(rel: str, line: str) -> str | None:
    for path, needle, reason in _ALLOWED:
        if rel == path and needle in line:
            return reason
    return None


def _rules() -> list[Rule]:
    film = _receipt("FILM_RECEIPT.json")
    gate3 = _receipt("GATE3_RECEIPT.json")
    grouped = gate3["entity_grouping"]
    power = _receipt("GATE_POWER_RECEIPT.json")
    verdicts = {g["gate"]: g["verdict"] for g in power["gates"]}

    render_bytes = _dig(film, "render.bytes")
    poster_bytes = _dig(film, "poster.bytes")
    frames = _dig(film, "composition.frames")
    scored = gate3["observations_scored"]
    hits = round(gate3["discriminating_rate"] * scored)
    groups = grouped["groups_scored"]
    grouped_hits = round(grouped["grouped_discriminating_rate"] * groups)
    reads = len(film["reads"])

    # Five of the six gate headings in `docs/KILL_GATE.md` are written by hand. Gate 3's is
    # generated between comment markers and its `--check` already refuses to let it drift,
    # so it is not covered here and does not need to be. Anchoring on the heading is the
    # whole design: a rule scanning every occurrence of a verdict token produced 29 findings
    # over this tree, none of them drift, because these documents deliberately keep
    # superseded verdicts with their dates and one line often names two gates. Anchored to a
    # heading it is 10 lines and no false positives, measured.
    heading_rules = [
        Rule(
            what=f"gate {gate}'s verdict in its heading",
            subject=rf"^#{{2,4}}\s+Gate {gate}\b",
            # A space after the delimiter, not `\s*`. Without it the hyphen inside
            # `PRE-PASSED` is itself a delimiter, so the rule read a correct heading as
            # carrying a second verdict of `PASSED` and reported it as drift.
            shape=r"[-\u2014:,]\s+(PRE[- _]?PASSED|PASSED[- _]UNGROUPED[- _]ONLY|"
            r"NOT[- _]ESTABLISHED|NOT[- _]RUN|PASSED|FAILED)\b",
            value=verdicts[gate],
            source=f"GATE_POWER_RECEIPT.json gates[{gate}].verdict",
            why="the heading is the first thing a reader takes from the section",
        )
        for gate in (1, 2, 4, 5, 6)
    ]

    return heading_rules + [
        Rule(
            what="the film's size in bytes",
            # `size=` catches the pasted ffprobe block, which is where this went wrong
            # once: it read size=11108910, a number matching neither the film nor the
            # silent cut, and no rule phrased around the word "bytes" would see it.
            subject=r"tracetriage-film\.mp4|the film[^.]{0,60}bytes|"
            r"bytes[^.]{0,30}the film|^size=\d+",
            shape=r"\b\d{1,3}(?:,\d{3}){2,}\b|\b\d{8}\b",
            value=f"{render_bytes:,}",
            source="FILM_RECEIPT.json render.bytes",
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
            source="FILM_RECEIPT.json poster.bytes",
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
            source="FILM_RECEIPT.json composition.frames",
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
            source="GATE3_RECEIPT.json observations_scored",
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
            source="GATE3_RECEIPT.json round(discriminating_rate * observations_scored)",
            why="the numerator gate 3's bound was computed on",
        ),
        Rule(
            what="gate 3's independent episode count",
            subject=r"independent \(station, date\) episodes|station-nights|"
            r"independent episodes",
            shape=r"\b(\d{2}) (?:independent|episodes|station-nights)",
            value=str(groups),
            source="GATE3_RECEIPT.json entity_grouping.groups_scored",
            why="the grouped denominator, which is what the pre-registered plan decides on",
        ),
        Rule(
            what="gate 3's discriminating episode count",
            subject=r"discriminate on every capture",
            shape=r"\b(\d{2}) of the \d{2}\b",
            value=str(grouped_hits),
            source=(
                "GATE3_RECEIPT.json round(entity_grouping.grouped_discriminating_rate"
                " * entity_grouping.groups_scored)"
            ),
            why="the grouped numerator",
        ),
        Rule(
            what="the number of receipts the film is built from",
            # An outside reviewer picked this one out of the candidates, and it earns the
            # place: the count was published as eight, then nine, while the receipt held
            # ten. It is a reproducibility claim, it has one clean source, and the two
            # lines carrying it are written in different hands (a digit and a word).
            subject=r"committed JSON|receipts? (?:it |the film )?reads|"
            r"reads[^|]{0,30}receipt",
            shape=r"\b(seven|eight|nine|ten|eleven|twelve|\d{1,2})\s+"
            r"(?:committed )?(?:JSON|receipt)",
            value=str(reads),
            source="FILM_RECEIPT.json len(reads)",
            why="the film's reproducibility claim is the list of receipts it reads",
        ),
        Rule(
            what="gate 3's bound in the sentence that states its bar",
            # The pair, not a bare decimal. "95% lower bound" names eight different
            # quantities across these documents, so a decimal matcher scoped on the phrase
            # is a false-positive machine. Requiring the bound and the bar in one ordered
            # phrase leaves exactly the sentence that shipped wrong: `a 95% lower bound of
            # 0.37 against a threshold of 0.70` published the grouped figure as the gate's.
            subject=r"bound of 0\.\d",
            shape=r"(?<!grouped )bound of (0\.\d{2,4})[^|]{0,30}?against a",
            value=repr(gate3["rate_lower_bound_95"]),
            source="GATE3_RECEIPT.json rate_lower_bound_95",
            why="the number the gate's verdict turns on, next to the bar it is read against",
        ),
        Rule(
            what="the bar gate 3's bound is read against",
            subject=r"bound of 0\.\d",
            shape=r"bound of 0\.\d{2,4}[^|]{0,30}?against a (?:threshold of )?(0\.\d{1,2})",
            value=repr(gate3["threshold"]),
            source="GATE3_RECEIPT.json threshold",
            why="a bound means nothing without the bar, and the bar is pre-registered",
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
                wrong = [s for s in seen if rule.disagrees(s)]
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


#: Rules whose only subject was `presentation/REPORT.md`, a working document that is no
#: longer in the tree. They are kept rather than deleted because the quantities are still
#: real and a document could state them again, and they are named here rather than let
#: through by a zero-hit tolerance, because a rule that quietly stops checking is the
#: defect this file exists to prevent. The set is exact in both directions: a rule that
#: regains a subject has to leave this list, and a rule that loses one has to join it.
_NO_SUBJECT_IN_THE_TREE = frozenset(
    {
        "the film's size in bytes",
        "the poster frame's size in bytes",
        "gate 3's bound in the sentence that states its bar",
        "the bar gate 3's bound is read against",
    }
)


def test_every_rule_is_actually_exercised(rules: list[Rule]) -> None:
    """A rule matching nothing would not have caught its own defect.

    The failure this prevents is a subject pattern tightened until the test passes. Every
    rule has to find its quantity stated correctly somewhere, or it is decoration, and the
    exceptions are enumerated rather than tolerated by a count.
    """
    unmatched = set()
    files = _scanned()
    for rule in rules:
        hits = 0
        for path in files:
            for line in path.read_text(encoding="utf-8").splitlines():
                if rule.scope(line) and any(
                    not rule.disagrees(s) for s in rule.found(line) if s
                ):
                    hits += 1
        if hits == 0:
            unmatched.add(rule.what)
    assert unmatched == _NO_SUBJECT_IN_THE_TREE, (
        "the set of rules with no subject in the tree is not the recorded one.\n"
        f"  newly checking nothing: {sorted(unmatched - _NO_SUBJECT_IN_THE_TREE)}\n"
        f"  has a subject again: {sorted(_NO_SUBJECT_IN_THE_TREE - unmatched)}"
    )


def test_every_exemption_suppresses_a_real_finding(
    rules: list[Rule], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exemption has to show the finding it removes.

    The version before this one asked only whether the needle still appeared in the file.
    An outside reviewer pointed out that this proves nothing, and measuring settled it:
    all three exemptions in the table at the time suppressed zero findings. Each had been
    written while a rule was still loose, and each kept reading as load-bearing after the
    subject that needed it was tightened. They are gone, and this is the test that would
    have caught them.

    The line is written back under its own relative path, because the exemption is keyed on
    that path and a copy under another name would not be exempt.
    """
    for rel, needle, reason in _ALLOWED:
        path = REPO / rel
        assert path.exists(), f"{rel} no longer exists ({reason})"
        matching = [
            line for line in path.read_text(encoding="utf-8").splitlines() if needle in line
        ]
        assert matching, f"{rel}: {needle!r} matches no line ({reason})"

        page = tmp_path / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("\n".join(matching) + "\n", encoding="utf-8")

        assert not _findings([page], rules, root=tmp_path), (
            f"{rel}: {needle!r} is exempt and still reports a finding, which means the "
            f"exemption is not doing what it says"
        )
        monkeypatch.setitem(globals(), "_ALLOWED", ())
        try:
            without = _findings([page], rules, root=tmp_path)
        finally:
            monkeypatch.undo()
        assert without, (
            f"{rel}: {needle!r} suppresses nothing. Delete it rather than leaving a "
            f"permission nobody needs ({reason})"
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
    "the number of receipts the film is built from": (
        "The film is built from eight committed JSON files.",
        "The film is built from {v} committed JSON files.",
    ),
    "gate 3's bound in the sentence that states its bar": (
        "Gate 3 reached a 95% lower bound of 0.11 against a threshold of 0.70.",
        "Gate 3 reached a 95% lower bound of {v} against a threshold of 0.70.",
    ),
    "the bar gate 3's bound is read against": (
        "Gate 3 reached a lower bound of 0.731 against a threshold of 0.55.",
        "Gate 3 reached a lower bound of 0.731 against a threshold of {v}.",
    ),
}

#: The five heading rules differ only in the gate number, so their planted pairs are built
#: rather than typed. Five near-identical hand-written entries is a table that drifts.
#: `FAILED` is the wrong value for all five, which is what makes one wrong sentence enough.
for _gate in (1, 2, 4, 5, 6):
    _PLANTED[f"gate {_gate}'s verdict in its heading"] = (
        f"## Gate {_gate}: the section title \u2014 FAILED on the evidence",
        f"## Gate {_gate}: the section title \u2014 {{v}} on the evidence",
    )


#: A second sentence per rule, deliberately written the way the documents *do not* write it
#: today: a different subject branch, a different delimiter, a pasted tool line instead of
#: prose. This table exists because of one attack an outside reviewer named against the
#: version with a single planted pair. Narrow a subject until it matches only the literal
#: current phrasing, say "224 of 289 testable observations", and the planted-drift test still
#: passes, the exercise test still passes, and a future "223 of 289" walks straight through.
#: A rule has to fire on two unlike wordings of its own quantity, or it is a template.
#:
#: One rule is template-bound and says so: the grouped numerator only ever appears in
#: "N of the 68 discriminate on every capture", so its second wording is the same phrase with
#: a different lead-in. Naming that is better than pretending otherwise.
_PLANTED_REPHRASED: dict[str, tuple[str, str]] = {
    "the film's size in bytes": ("size=99999999", "size={v}"),
    "the poster frame's size in bytes": (
        "`presentation/out/tracetriage-film-poster.jpg` weighs 111,222 bytes.",
        "`presentation/out/tracetriage-film-poster.jpg` weighs {v} bytes.",
    ),
    "the film's frame count": ("nb_frames=1234", "nb_frames={v}"),
    "gate 3's scored observations": (
        "Gate 3: 301 observations scored under the pre-registered plan.",
        "Gate 3: {v} observations scored under the pre-registered plan.",
    ),
    "gate 3's discriminating observations": (
        "The corridor lands on a visible trace in 111 discriminated captures.",
        "The corridor lands on a visible trace in {v} discriminated captures.",
    ),
    "gate 3's independent episode count": (
        "Those observations span 44 station-nights.",
        "Those observations span {v} station-nights.",
    ),
    "gate 3's discriminating episode count": (
        "Only 21 of the 68 discriminate on every capture.",
        "Only {v} of the 68 discriminate on every capture.",
    ),
    "the number of receipts the film is built from": (
        "It reads 9 receipts and draws nothing from outside them.",
        "It reads {v} receipts and draws nothing from outside them.",
    ),
    "gate 3's bound in the sentence that states its bar": (
        "The exact one-sided lower bound of 0.55 against a 0.7 bar.",
        "The exact one-sided lower bound of {v} against a 0.7 bar.",
    ),
    "the bar gate 3's bound is read against": (
        "An exact lower bound of 0.731 against a 0.5 bar.",
        "An exact lower bound of 0.731 against a {v} bar.",
    ),
}

for _gate in (1, 2, 4, 5, 6):
    _PLANTED_REPHRASED[f"gate {_gate}'s verdict in its heading"] = (
        f"### Gate {_gate}, revisited, FAILED after review",
        f"### Gate {_gate}, revisited, {{v}} after review",
    )


def _planted_pairs(what: str) -> tuple[tuple[str, str], ...]:
    """Every planted pair for one rule, across both tables."""
    return tuple(
        table[what] for table in (_PLANTED, _PLANTED_REPHRASED) if what in table
    )


def test_every_rule_fires_on_planted_drift(rules: list[Rule], tmp_path: Path) -> None:
    """A drift test that passes on a clean tree has proved nothing about itself.

    Each rule gets a sentence written the way the documents write it, with the wrong
    number, and has to be the rule that fires on it. Without this, tightening a subject
    pattern until the suite goes green is indistinguishable from fixing a document, and
    that is how a check ends up guarding nothing.
    """
    missing = [
        r.what
        for r in rules
        if r.what not in _PLANTED or r.what not in _PLANTED_REPHRASED
    ]
    assert not missing, (
        f"these rules lack a planted case in one of the two tables, so nothing shows they "
        f"can fire on more than one wording: {missing}"
    )

    for rule in rules:
        for wrong, _ in _planted_pairs(rule.what):
            planted = tmp_path / "planted.md"
            planted.write_text(wrong + "\n", encoding="utf-8")
            fired = {what for what, _ in _findings([planted], rules, root=tmp_path)}
            assert rule.what in fired, (
                f"{rule.what} did not fire on {wrong!r}. Either the subject pattern no "
                f"longer matches how the documents write it, or the shape does not match "
                f"how the number is written. A rule that cannot fire is worse than no "
                f"rule, because the suite reports it as coverage."
            )


def test_a_correct_sentence_is_not_a_finding(rules: list[Rule], tmp_path: Path) -> None:
    """The other half. A rule that fires on everything is also useless.

    Each planted sentence is repaired to carry the receipt's own value, and nothing may
    fire. This is what stops a rule from being written so loosely that every document
    mentioning the subject becomes a finding.
    """
    for rule in rules:
        for _, template in _planted_pairs(rule.what):
            repaired = template.format(v=rule.value)
            page = tmp_path / "repaired.md"
            page.write_text(repaired + "\n", encoding="utf-8")
            fired = [
                m
                for what, m in _findings([page], rules, root=tmp_path)
                if what == rule.what
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
    """None today. A drift test whose allowlist grows is a drift test being defeated."""
    assert len(_ALLOWED) <= 6, (
        f"{len(_ALLOWED)} exemptions. Each is a line allowed to disagree with a receipt; "
        f"past a handful the test documents drift rather than catching it."
    )


def test_every_rule_names_where_its_value_came_from(rules: list[Rule]) -> None:
    """"Nothing here is hardcoded" is a claim, so it is read back through the source field.

    Before this the rules read their values from receipts and the ``Rule`` object kept no
    record of which field, so the claim rested on the reader believing ``_rules``. An outside
    reviewer said as much. Now every rule carries the receipt and the path, three of the
    fifteen say in the same string that the value is derived and how, and this test resolves
    every plain path against the receipt on disk.
    """
    for rule in rules:
        name, _, path = rule.source.partition(" ")
        assert name.endswith(".json"), f"{rule.what}: {rule.source!r} names no receipt"
        assert (ARTIFACTS / name).exists(), f"{rule.what}: artifacts/{name} is absent"
        assert path, f"{rule.what}: {rule.source!r} names a receipt but no field"

        bracket = re.fullmatch(r"gates\[(\d)\]\.verdict", path)
        if bracket:
            gates = _receipt(name)["gates"]
            got = next(g["verdict"] for g in gates if g["gate"] == int(bracket.group(1)))
            assert _digits(str(got)) == _digits(rule.value), (rule.what, got, rule.value)
            continue

        if path.startswith(("len(", "round(")):
            # Derived, and the arithmetic is written in the source string. The value itself
            # is still checked by every other test in this file; what cannot be asserted
            # here is a one-line lookup that does not exist.
            inner = path[path.index("(") + 1 : path.rindex(")")]
            assert inner, f"{rule.what}: {rule.source!r} derives from nothing"
            continue

        assert _digits(str(_dig(_receipt(name), path))) == _digits(rule.value), (
            f"{rule.what}: artifacts/{name} {path} does not hold {rule.value!r}"
        )


#: What the engine finds when it is pointed at the documents as they were actually published,
#: at the commit before the corrections. Encoded rather than asserted in a comment: the
#: earlier version of this file claimed "six findings on three documents" in prose, an
#: outside reviewer went looking for the check behind it, and there was none. Measured at 15
#: rules: eight findings, all in one document. A rule added later may raise the count, so the
#: number is a floor, but the document and the seven quantities are exact.
_AS_PUBLISHED_COMMIT = "202dc85"
_AS_PUBLISHED_FLOOR = 8
_AS_PUBLISHED_DOCUMENT = "presentation/REPORT.md"
_AS_PUBLISHED_QUANTITIES = frozenset(
    {
        "the film's size in bytes",
        "the poster frame's size in bytes",
        "the film's frame count",
        "gate 3's scored observations",
        "gate 3's discriminating observations",
        "the number of receipts the film is built from",
        "gate 3's bound in the sentence that states its bar",
    }
)


def test_it_would_have_found_the_drift_in_the_documents_as_published(
    rules: list[Rule], tmp_path: Path
) -> None:
    """The whole engine, against the whole tree, as a judge could have read it.

    ``test_it_catches_the_drift_that_actually_shipped`` feeds it five lines somebody chose.
    This one takes every tracked markdown file out of the pre-fix commit, runs the real
    scan over all of them, and requires the findings. The difference matters: a hand-picked
    line proves a pattern matches a string, and a whole-tree run proves the engine would
    have found the drift without anyone knowing where to look.

    Every one of these documents passed a full offline suite, a green CI run and a
    ``--check`` on each of its generated regions at that commit.
    """
    have = subprocess.run(
        ["git", "cat-file", "-e", f"{_AS_PUBLISHED_COMMIT}^{{commit}}"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if have.returncode != 0:
        pytest.skip(
            f"{_AS_PUBLISHED_COMMIT} is not in this clone, so the as-published tree cannot "
            f"be read. A shallow clone is the usual reason."
        )

    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", _AS_PUBLISHED_COMMIT],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout.split()

    pages = []
    for rel in listing:
        if not rel.endswith(".md") or rel in _DATED_LOGS:
            continue
        if rel.startswith(("internal_docs/", "tests/")):
            continue
        blob = subprocess.run(
            ["git", "show", f"{_AS_PUBLISHED_COMMIT}:{rel}"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        page = tmp_path / rel
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(blob, encoding="utf-8")
        pages.append(page)

    assert len(pages) > 20, f"only {len(pages)} documents came out of the tree"

    findings = _findings(pages, rules, root=tmp_path)
    quantities = {what for what, _ in findings}
    documents = {message.split(":")[0] for _, message in findings}

    assert len(findings) >= _AS_PUBLISHED_FLOOR, (
        f"{len(findings)} findings against the tree as published, expected at least "
        f"{_AS_PUBLISHED_FLOOR}. The rules have been narrowed to the point where they no "
        f"longer see drift that a judge could have read:\n  "
        + "\n  ".join(m for _, m in findings)
    )
    assert _AS_PUBLISHED_DOCUMENT in documents, sorted(documents)
    assert quantities >= _AS_PUBLISHED_QUANTITIES, sorted(
        _AS_PUBLISHED_QUANTITIES - quantities
    )
