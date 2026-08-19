"""Grounded reviewer notes, and the checker that decides whether one may ship (unit E1).

A reviewer opening a card gets numbers. What they need is the sentence those numbers add
up to: what disagrees with what, where to look in the waterfall, and what would settle it.
That sentence is worth generating and it is exactly the kind of sentence a language model
will happily invent, so the generation is not the interesting part of this module. The
checker is.

**The evidence packet is a closed world.** :func:`build_packet` assembles every fact the
model is allowed to use out of the committed console data, prints each at a fixed
precision, and hands over nothing else. There is no retrieval step, no tool call, and no
image: the model sees a field list and is asked to write prose about it.

**Every number in the output has to trace back to that packet.** :func:`verify_note`
extracts each numeric token from the draft and requires it to be one of the packet's own
printed tokens, or to equal a packet value at the precision the draft printed it to. Three
conversions are allowed on top of that, each scoped to the fields it can apply to and
required to carry the unit it produces, and all three are named in
:data:`ALLOWED_TRANSFORMS` rather than left as special cases in the code. Anything else is
``UNGROUNDED_NUMBER`` and the draft is refused.

That check is what caught the failure this unit was worth building for: asked to write about
an observation received at 436490000 Hz, the model wrote 436.2, 437.215, 435.275 and
2401.975 MHz across different drafts, each a real amateur satellite frequency and none of
them this one.

Two earlier versions of the check were weaker than they read, and both are worth recording
because the code looked correct in each. The first accepted a literal that appeared anywhere
in the rendered packet, so a transposition of the fitted offset was grounded by the digits
inside the receiver frequency: 6490 passed against a true 6904. The second compared the
converted value without reading the unit, so an offset of 6904 Hz written as "6.9 MHz"
passed, an error of three orders of magnitude with no violation reported. Tokenising, and
requiring the unit, closes both, and :func:`adversarial_drafts` builds a case for each out
of the packet under test.

**Refusal is published, not retried.** When a draft fails any check the deterministic note
from :func:`deterministic_note` ships instead and the card says a generated note was
refused and why. A pipeline that silently regenerates until something passes has moved the
error rather than measured it, and the refusal rate is the most informative number this
unit produces.

**The checker is measured against drafts with known defects.**
:func:`adversarial_drafts` returns texts that each break at least the rule they are
labelled with, and :func:`control_drafts` returns texts that break none. Both are built per
packet, so the measurement runs over every observation rather than over whichever one came
first. A checker that catches every adversarial draft by refusing everything is
indistinguishable from a broken one, so both directions are reported: a detection rate over
the first set and a false-refusal rate over the second.

Nothing in this module's import closure can reach the network. The model call lives in
:mod:`pipeline.tracetriage.granite` and is imported by the runner, not by the verifier, so
the part that decides whether a note may be published has no capability to fetch anything
that would change its mind.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: Version of the prompt contract. Bumped when the instruction text changes, because a
#: note generated under different instructions is not comparable with one generated under
#: these, and the receipt records which.
PROMPT_VERSION = "e1.2"

#: The label vocabulary SatNOGS uses. A draft may name one only if the packet does.
LABEL_VALUES = ("with-signal", "without-signal", "unknown")

#: The derived forms a draft may write that the packet does not print, each bound to the
#: fields it applies to. Named here so they are rules rather than exceptions buried in a
#: branch, and scoped by field so the arithmetic cannot be borrowed by an unrelated value:
#: dividing any number by a million would let a frequency justify a sigma.
ALLOWED_TRANSFORMS = (
    "a frequency in hertz written as megahertz, for fields ending in _hz",
    "a frequency in hertz written as kilohertz, for fields ending in _hz",
    "a value on the unit interval written as a percentage, for the listed fields only",
)

#: Fields whose value is a probability or a fraction, so a percentage is the same number.
_UNIT_INTERVAL_FIELDS = frozenset(
    {
        "model_probability",
        "ensemble_uncertainty",
        "flat_row_fraction",
        "closest_approach_fraction",
        "queue_score",
        "axis_derivation_confidence",
    }
)

#: Claims outside what this system is permitted to state. The wording comes from the
#: permission contract: no confirmed identity, no decoded telemetry, no mission outcome,
#: no endorsement, and no instruction to act on the public network.
_OVERCLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bdecod(?:e|ed|es|ing)\b", "decoding"),
    (r"\btelemetry\b", "telemetry"),
    (r"\bprove[sn]?\b|\bproof\b", "proof"),
    (r"\bmission (?:success|failure)\b", "mission outcome"),
    (r"\bendorse[sd]?\b|\bendorsement\b", "endorsement"),
    (r"\bvote\b|\bvoting\b", "voting on the public network"),
    (r"\bupload\b|\bsubmit to\b|\breport to satnogs\b", "writing to the public network"),
    (r"\bwas heard\b|\bwas detected\b|\bis a detection\b", "an asserted detection"),
)

#: Absolutes a four-sentence note about one observation cannot support.
_ABSOLUTE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\balways\b", "always"),
    (r"\bnever\b", "never"),
    (r"\bimpossible\b", "impossible"),
    (r"\bguarantee[sd]?\b", "guarantee"),
    (r"\bcertainly\b|\bdefinitely\b|\bundoubtedly\b", "certainty"),
)

#: A note is for a reviewer, not a chat partner. Case matters for the first-person
#: pronoun and nowhere else, so it is checked separately rather than lower-cased with the
#: rest, where a bare "i" would match inside nothing and "I" would match everywhere.
_FIRST_PERSON_RE = re.compile(r"\bI\b|\bI'm\b|\bI've\b")
_VOICE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bmy\b|\bmine\b|\bwe think\b", "first person"),
    (r"\bas an ai\b|\blanguage model\b", "self-reference"),
    (r"https?://", "a URL"),
    (r"^#{1,6}\s", "a markdown heading"),
)

#: Upper bounds. Four sentences was the instruction; five is the tolerance before the note
#: stops being a note.
MAX_CHARS = 700
MAX_SENTENCES = 5

#: Words that turn the bare verb, the gerund or the noun into a proposed action rather than
#: an assertion. The contract forbids claiming a confirmed detection or identity. It does
#: not forbid telling a reviewer what would settle the question, which is the third thing
#: the prompt asks the note to cover, so a single pattern on the verb stem was broader than
#: the rule it implements: it refused "to confirm this, look for a signal" in eight of
#: twenty-five drafts. Seven assertive forms are in :data:`ADVERSARIAL_DRAFTS`.
_CONFIRM_ALLOWED_BEFORE = frozenset(
    {
        # modals and the infinitive marker: a proposed action
        "to", "would", "could", "might", "should", "cannot", "not",
        # the two verbs and one preposition that were observed introducing a nominalised
        # action in real drafts, and nothing beyond them. An earlier list also held "and",
        # "means", "requires", "before", "after" and "without", each of which admitted a
        # straightforward assertion: "the offset is large and confirms a catalogue drift",
        # "means confirmed mistuning", "requires confirmed identity", "after confirmation
        # of the pass". All four are now in ADVERSARIAL_DRAFTS.
        "by", "help", "helps", "involve", "involves",
    }
)

#: The indicative and the participle assert on their own, whatever precedes them, so the
#: preceding word is only consulted for the bare verb, the gerund and the noun.
_CONFIRM_ALWAYS_RE = re.compile(r"\bconfirms\b|\bconfirmed\b")
_CONFIRM_RE = re.compile(r"\bconfirm\b|\bconfirming\b|\bconfirmation\b")
_PRECEDING_WORD_RE = re.compile(r"(\w+)\W*$")

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_SENTENCE_RE = re.compile(r"[.!?](?:\s|$)")


@dataclass(frozen=True)
class EvidencePacket:
    """Every fact a note may use, and nothing else.

    ``printed`` is what the model is shown: field name to formatted value. ``exact`` keeps
    the unrounded values so the checker can accept a draft that printed one to fewer
    digits than the packet did.
    """

    obs_id: int
    printed: dict[str, str]
    exact: dict[str, float]
    vocabulary: frozenset[str]

    def as_text(self) -> str:
        width = max(len(k) for k in self.printed)
        return "\n".join(f"{k.ljust(width)} : {v}" for k, v in self.printed.items())

    def sha256(self) -> str:
        return hashlib.sha256(self.as_text().encode("utf-8")).hexdigest()


@dataclass
class Verification:
    """The checker's decision about one draft, with every reason it reached it."""

    ok: bool
    violations: list[dict[str, str]] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return sorted({v["code"] for v in self.violations})

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "violations": self.violations, "codes": self.codes}


def _fmt(value: float, places: int) -> str:
    return f"{value:.{places}f}"


def build_packet(card: dict[str, Any], entry: dict[str, Any]) -> EvidencePacket:
    """Assemble the closed world for one observation.

    ``card`` is an entry from the console's ``cards.json`` and ``entry`` is the matching
    row of ``queue.json``. Both are committed, so a note is reproducible from the
    repository without the snapshot.
    """
    if card["obs_id"] != entry["obs_id"]:
        raise ValueError(
            f"card {card['obs_id']} paired with queue entry {entry['obs_id']}. A note "
            f"assembled from two observations would be grounded in neither."
        )

    corridor = card.get("corridor") or {}
    start = datetime.fromisoformat(str(card["start"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(card["end"]).replace("Z", "+00:00"))
    duration_s = (end - start).total_seconds()

    exact: dict[str, float] = {
        "queue_rank": float(entry["rank"]),
        "queue_score": float(entry["score"]),
        "model_probability": float(entry["model_prob"]),
        "ensemble_uncertainty": float(entry["ensemble_uncertainty"]),
        "flat_row_fraction": float(entry["flat_row_frac"]),
        "pass_duration_s": duration_s,
        "max_elevation_deg": float(corridor.get("max_elevation_deg", 0.0)),
        "closest_approach_fraction": float(corridor.get("tca_frac", 0.0)),
        "fitted_offset_hz": float(corridor.get("fitted_offset_hz", 0.0)),
        "fitted_offset_ppm": float(corridor.get("fitted_offset_ppm", 0.0)),
        "corridor_half_width_hz": float(corridor.get("half_width_hz", 0.0)),
        "sigma_curved": float(corridor.get("sigma_curved", 0.0)),
        "sigma_vertical": float(corridor.get("sigma_vertical", 0.0)),
        "hz_per_pixel": float(card["hz_per_px"]),
        "seconds_per_pixel": float(card["seconds_per_px"]),
        "axis_derivation_confidence": float(card["derivation_confidence"]),
        "receiver_frequency_hz": float(card["rx_freq_hz"]),
        "norad_catalogue_id": float(card["norad_cat_id"]),
        "ground_station_id": float(card["ground_station"]),
        "observation_id": float(card["obs_id"]),
    }

    printed: dict[str, str] = {
        "observation_id": str(card["obs_id"]),
        "ground_station_id": str(card["ground_station"]),
        "ground_station_name": str(card["station_name"]),
        "norad_catalogue_id": str(card["norad_cat_id"]),
        "transmitter_mode": str(card["transmitter_mode"]),
        "receiver_frequency_hz": str(card["rx_freq_hz"]),
        "network_label": str(card["waterfall_status"]),
        "pass_duration_s": _fmt(duration_s, 0),
        "max_elevation_deg": _fmt(exact["max_elevation_deg"], 1),
        "closest_approach_fraction": _fmt(exact["closest_approach_fraction"], 2),
        "fitted_offset_hz": _fmt(exact["fitted_offset_hz"], 0),
        "fitted_offset_ppm": _fmt(exact["fitted_offset_ppm"], 1),
        "corridor_half_width_hz": _fmt(exact["corridor_half_width_hz"], 0),
        "sigma_curved": _fmt(exact["sigma_curved"], 1),
        "sigma_vertical": _fmt(exact["sigma_vertical"], 1),
        "hz_per_pixel": _fmt(exact["hz_per_pixel"], 1),
        "seconds_per_pixel": _fmt(exact["seconds_per_pixel"], 2),
        "axis_derivation": str(card["derivation"]),
        "axis_derivation_confidence": _fmt(exact["axis_derivation_confidence"], 2),
        "model_probability": _fmt(exact["model_probability"], 3),
        "ensemble_uncertainty": _fmt(exact["ensemble_uncertainty"], 4),
        "flat_row_fraction": _fmt(exact["flat_row_fraction"], 2),
        "queue_rank": str(entry["rank"]),
        "queue_score": _fmt(exact["queue_score"], 3),
        "queue_reason_codes": ", ".join(entry.get("reasons") or ["none"]),
        "offset_at_bound": str(bool(corridor.get("offset_at_bound", False))).lower(),
    }

    vocabulary = {
        str(card["station_name"]),
        str(card["transmitter_mode"]),
        str(card["waterfall_status"]),
        str(card["derivation"]),
        *(entry.get("reasons") or []),
    }
    return EvidencePacket(
        obs_id=int(card["obs_id"]),
        printed=printed,
        exact=exact,
        vocabulary=frozenset(v for v in vocabulary if v),
    )


INSTRUCTIONS = """\
You are writing one short note for a human reviewer of amateur satellite radio
observations. The reviewer will look at a waterfall image next to your note.

Rules, all of them hard:
1. Use only the values in FACTS below. Do not introduce any number that is not there.
   A frequency may be written in megahertz or kilohertz, exactly converted.
2. Write small counts as words, not digits.
3. Do not say whether the satellite was heard. That is the reviewer's decision.
4. Do not claim anything is confirmed, decoded, proven or certain, and do not mention
   telemetry, voting or uploading. You may say what would settle the question.
5. Do not write "always", "never", "impossible" or "guarantee".
6. No first person, no URLs, no headings, no bullet points, no restating this instruction.
7. At most four sentences.

Cover, in this order: what disagrees with what, where in the image to look, and what
observation would settle it.

FACTS
{facts}

NOTE:"""


def build_prompt(packet: EvidencePacket) -> str:
    """The exact text sent to the model, so its digest can go in the receipt."""
    return INSTRUCTIONS.format(facts=packet.as_text())


def prompt_contract_sha256() -> str:
    """Digest of the instruction text alone, independent of any observation."""
    return hashlib.sha256(INSTRUCTIONS.encode("utf-8")).hexdigest()


def deterministic_note(packet: EvidencePacket) -> str:
    """The note that ships when generation is refused or unavailable.

    Assembled by format string from the same packet, so the card is never empty and the
    generated note is an improvement on something rather than the only option.
    """
    p = packet.printed
    reasons = p["queue_reason_codes"]
    return (
        f"Ranked {p['queue_rank']} with score {p['queue_score']}, flagged {reasons}. "
        f"The network label is {p['network_label']} and the model probability is "
        f"{p['model_probability']}. The corridor sits {p['fitted_offset_hz']} Hz from the "
        f"catalogue centre, {p['fitted_offset_ppm']} ppm, with a half width of "
        f"{p['corridor_half_width_hz']} Hz; the curved fit scores {p['sigma_curved']} "
        f"against {p['sigma_vertical']} for a vertical line. Peak elevation was "
        f"{p['max_elevation_deg']} degrees at {p['closest_approach_fraction']} of the pass."
    )


def asserts_a_confirmation(lowered: str) -> str | None:
    """Return the offending phrase if a draft claims something is confirmed.

    A purpose clause ("to confirm this, look for ...") proposes work for the reviewer. An
    indicative ("this confirms a pass") states the thing the permission contract forbids
    stating. Two rules, because one was not enough: ``confirms`` and ``confirmed`` assert
    regardless of what precedes them, and only the bare verb, the gerund and the noun are
    worth reading context for.
    """
    always = _CONFIRM_ALWAYS_RE.search(lowered)
    if always:
        return always.group(0)
    for match in _CONFIRM_RE.finditer(lowered):
        before = _PRECEDING_WORD_RE.search(lowered[: match.start()])
        previous = before.group(1) if before else ""
        if previous in _CONFIRM_ALLOWED_BEFORE:
            continue
        return f"{previous} {match.group(0)}".strip()
    return None


def _packet_number_tokens(packet: EvidencePacket) -> frozenset[str]:
    """Every numeric token the packet prints, as a token and not as a substring.

    The distinction is the whole check. An earlier version accepted a literal if it
    appeared anywhere in the rendered packet, which meant ``6490`` was grounded by
    ``436490000`` and ``9000`` by ``2000`` under a value it had nothing to do with. A
    digit-transposition of the fitted offset passed with no violation at all, which is
    precisely the failure this module exists to catch. Tokenising first closes it: the
    tokens of ``436490000`` are ``436490000`` and nothing else.
    """
    return frozenset(_NUMBER_RE.findall(packet.as_text()))


def _unit_after(suffix: str) -> str | None:
    """The unit written immediately after a number, if it is one this checker knows.

    The alternation is split because a percent sign is not a word character, so a trailing
    word boundary never matched after it and the percentage transform was unreachable: a
    probability of 0.999999 written as "100%" was refused as ungrounded. Only the alphabetic
    units carry the boundary, which is where it is needed to stop "Hz" matching inside a
    word.
    """
    match = re.match(
        r"\s*(?:(MHz|megahertz|kHz|kilohertz|Hz|hertz)\b|(%)|(percent)\b)", suffix, re.I
    )
    if not match:
        return None
    unit = next(group for group in match.groups() if group).lower()
    return {"megahertz": "mhz", "kilohertz": "khz", "hertz": "hz", "percent": "%"}.get(
        unit, unit
    )


def _grounded_number(literal: str, suffix: str, packet: EvidencePacket) -> bool:
    """Is this numeric token traceable to the packet, in the unit the draft wrote it in?

    Three ways for a number to be grounded, in order of strength.

    First, it is one of the packet's own printed tokens. Token equality, not containment.

    Second, it equals a packet value at the precision the draft printed it to. A draft
    that writes ``6904`` for a stored ``6903.7166`` is quoting, not inventing.

    Third, it is one of the conversions in :data:`ALLOWED_TRANSFORMS`, and the draft wrote
    the unit that conversion produces. The unit is load-bearing: without it, dividing a
    frequency by a thousand grounded ``6.9 MHz`` for an offset of 6904 Hz, an error of
    three orders of magnitude with the checker satisfied.

    Sound but not tight, and worth being explicit about which. Every number this accepts
    equals a packet value at the precision the draft printed it to. It is not tight because
    a packet carries twenty numbers, so a one-digit integer can coincide with one of them
    by rounding, which is why instruction two asks for small counts as words.
    """
    if literal in _packet_number_tokens(packet):
        return True

    bare = literal.replace(",", "").lstrip("+")
    try:
        value = float(bare)
    except ValueError:
        return False
    places = len(bare.split(".")[1]) if "." in bare else 0
    target = round(value, places)
    unit = _unit_after(suffix)

    for name, exact in packet.exact.items():
        if round(exact, places) == target:
            return True
        if name.endswith("_hz"):
            if unit == "mhz" and round(exact / 1e6, places) == target:
                return True
            if unit == "khz" and round(exact / 1e3, places) == target:
                return True
        if name in _UNIT_INTERVAL_FIELDS and unit == "%" and (
            round(exact * 100.0, places) == target
        ):
            return True
    return False


def verify_note(text: str, packet: EvidencePacket) -> Verification:
    """Decide whether a draft may ship, and record every reason it may not.

    All checks run. Stopping at the first violation would make the receipt understate what
    a draft got wrong, and the distribution of violation codes is the thing that tells you
    whether the prompt or the model is the problem.
    """
    violations: list[dict[str, str]] = []

    def flag(code: str, detail: str) -> None:
        violations.append({"code": code, "detail": detail})

    stripped = text.strip()
    if not stripped:
        flag("EMPTY", "the draft is empty")
        return Verification(ok=False, violations=violations)

    if len(stripped) > MAX_CHARS:
        flag("TOO_LONG", f"{len(stripped)} characters, limit {MAX_CHARS}")

    sentences = len([m for m in _SENTENCE_RE.finditer(stripped)])
    if sentences > MAX_SENTENCES:
        flag("TOO_MANY_SENTENCES", f"{sentences} sentences, limit {MAX_SENTENCES}")

    for match in _NUMBER_RE.finditer(stripped):
        literal = match.group(0)
        suffix = stripped[match.end() : match.end() + 14]
        if not _grounded_number(literal, suffix, packet):
            unit = _unit_after(suffix)
            violations.append(
                {
                    "code": "UNGROUNDED_NUMBER",
                    "detail": f"{literal!r} is not in the evidence packet",
                    # Carried structurally rather than parsed back out of the message. A
                    # consumer that has to split a repr to recover the value it needs is
                    # one formatting change away from silently reporting nothing.
                    "literal": literal,
                    "unit": unit or "",
                }
            )

    for code in _CODE_RE.findall(stripped):
        if code not in packet.vocabulary and code not in packet.as_text():
            flag("UNGROUNDED_ENTITY", f"{code!r} is not in the evidence packet")

    # Only the hyphenated labels. "unknown" is also a SatNOGS label value and an ordinary
    # English word, and a substring test on it refused "the axis direction is unknown",
    # which breaks no rule. A false refusal that no control draft covers is invisible in
    # the receipt's false-refusal rate, which is the worst place for one to hide.
    for label in ("with-signal", "without-signal"):
        seen = re.search(rf"(?<![\w-]){re.escape(label)}(?![\w-])", stripped)
        if seen and label not in packet.as_text():
            flag("UNGROUNDED_ENTITY", f"label {label!r} is not this observation's")

    lowered = stripped.lower()
    claimed = asserts_a_confirmation(lowered)
    if claimed:
        flag("OVERCLAIM", f"asserts a confirmation: {claimed!r}")
    for pattern, name in _OVERCLAIM_PATTERNS:
        if re.search(pattern, lowered):
            flag("OVERCLAIM", f"mentions {name}")
    for pattern, name in _ABSOLUTE_PATTERNS:
        if re.search(pattern, lowered):
            flag("ABSOLUTE_CLAIM", f"says {name}")
    if _FIRST_PERSON_RE.search(stripped):
        flag("WRONG_VOICE", "uses first person")
    for pattern, name in _VOICE_PATTERNS:
        flags = re.MULTILINE if pattern.startswith("^") else 0
        if re.search(pattern, lowered, flags):
            flag("WRONG_VOICE", f"uses {name}")

    return Verification(ok=not violations, violations=violations)


#: Drafts that each break at least the rule they are labelled with, and no packet-dependent
#: rule. "At least": two of them break a second rule as well, because "confirms the
#: satellite was heard" is both an asserted confirmation and an asserted detection, and
#: "decoded and the telemetry read" trips both halves of the same prohibition. The label is
#: the code that must appear, not the only code that may.
#:
#: Four of these came from an adversarial review that broke the first version of the
#: confirmation rule, and three more from the review that broke the first version of the
#: number check. They are kept in the file rather than in a changelog because a bypass with
#: no test is a bypass that comes back.
ADVERSARIAL_DRAFTS: tuple[tuple[str, str], ...] = (
    (
        "The corridor sits 41234 Hz from the catalogue centre, which is a wide miss. "
        "Look at the upper third of the image.",
        "UNGROUNDED_NUMBER",
    ),
    (
        "The queue flagged this as STALE_CATALOGUE_FREQ_DRIFT. Look at the corridor.",
        "UNGROUNDED_ENTITY",
    ),
    (
        "This confirms the satellite was heard during the pass. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "The identity of the transmitter is confirmed by the offset. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "Confirming a pass here, the label disagrees with the model. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "The offset confirmed the catalogue drift. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "The downlink sits at 437.5 MHz, so the corridor is drawn there.",
        "UNGROUNDED_NUMBER",
    ),
    (
        "A vertical line at this offset always means the receiver was mistuned.",
        "ABSOLUTE_CLAIM",
    ),
    (
        "I think the corridor looks wrong here. Look at the middle of the image.",
        "WRONG_VOICE",
    ),
    (
        "See https://network.satnogs.org for the original waterfall.",
        "WRONG_VOICE",
    ),
    ("", "EMPTY"),
    (
        "One. Two. Three. Four. Five. Six. Seven.",
        "TOO_MANY_SENTENCES",
    ),
    (
        "The pass was decoded and the telemetry read cleanly. Look at the corridor.",
        "OVERCLAIM",
    ),
    # The four bypasses of the first confirmation rule. Each reached the reviewer's screen
    # with no violation because the word before "confirm" was on an allow list that had
    # grown by observation rather than by argument.
    (
        "The offset is large and confirms a catalogue drift. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "A vertical line at this offset means confirmed mistuning. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "After confirmation of the pass the label was corrected. Look at the corridor.",
        "OVERCLAIM",
    ),
    (
        "The drift requires confirmed identity of the transmitter. Look at the corridor.",
        "OVERCLAIM",
    ),
)


def adversarial_drafts(packet: EvidencePacket) -> tuple[tuple[str, str], ...]:
    """The full set, including the cases that only make sense against a given packet.

    The label case needs a label that is not this observation's, and the digit-transposition
    case needs a number built out of this observation's own values, so neither can be a
    module constant without silently depending on which observation happened to be first in
    the console's card order.
    """
    label = next(v for v in ("with-signal", "without-signal") if v not in packet.as_text())
    offset = int(round(packet.exact["fitted_offset_hz"]))
    transposed = _transposed_digits(offset)
    freq_mhz = packet.exact["receiver_frequency_hz"] / 1e6
    extra: tuple[tuple[str, str], ...] = (
        (
            f"The network label is {label}, which disagrees with the model.",
            "UNGROUNDED_ENTITY",
        ),
        # The bypass that made the number check worth rewriting: a transposition of the
        # fitted offset, which the old containment test accepted because the digits appear
        # inside the receiver frequency.
        (
            f"The corridor sits {transposed} Hz from the catalogue centre. "
            f"Look at the corridor.",
            "UNGROUNDED_NUMBER",
        ),
        # Right digits, wrong unit by three orders of magnitude.
        (
            f"The corridor sits {_not_a_packet_number(offset / 1000.0, 'MHz', packet)} MHz "
            f"from the catalogue centre. Look at the corridor.",
            "UNGROUNDED_NUMBER",
        ),
        # Right digits, wrong unit by six.
        (
            f"The pass was received at {_not_a_packet_number(freq_mhz, 'kHz', packet)} kHz. "
            f"Look at the corridor.",
            "UNGROUNDED_NUMBER",
        ),
    )
    return ADVERSARIAL_DRAFTS + extra


def _not_a_packet_number(value: float, unit: str, packet: EvidencePacket) -> str:
    """Format ``value`` so it is definitely not grounded, adding precision until it is not.

    A wrong-unit draft is only adversarial if the number in it is wrong. On one observation
    the offset divided by a thousand rounded to 2.0, which is also that packet's vertical
    sigma to one decimal place, so the draft was correctly accepted and the suite silently
    lost a case. Rather than choose a magic value, this adds decimal places until the
    checker no longer grounds it, and raises if it cannot, because a test fixture that
    cannot establish its own premise has to say so rather than pass.
    """
    for places in (1, 2, 3, 4, 5):
        text = f"{value:.{places}f}"
        if not _grounded_number(text, f" {unit}", packet):
            return text
    raise ValueError(
        f"{value} is grounded in observation {packet.obs_id}'s packet at every precision "
        f"tried, so it cannot be used as an ungrounded example."
    )


def _transposed_digits(value: int) -> int:
    """Swap the last two digits, or add a digit if that is a no-op.

    Used only to build an adversarial draft. It has to produce a number that is not the
    original and is not any other packet value, and swapping adjacent digits is the
    smallest edit a reader would never notice.
    """
    text = str(abs(value))
    if len(text) >= 2 and text[-1] != text[-2]:
        text = text[:-2] + text[-1] + text[-2]
    else:
        text = text + "7"
    return int(text)

#: Drafts that break nothing, written only from fields every packet carries. Without
#: these, a checker that refused every draft would score perfectly above.
CONTROL_DRAFTS: tuple[str, ...] = (
    "The label and the model disagree about this pass. Look along the predicted corridor "
    "in the middle of the image, where a real trace would sit. A second capture of the "
    "same satellite from another station would settle it.",
    "The curved fit and the vertical fit score differently, so the shape of whatever is "
    "there matters more than its strength. Look at the corridor near closest approach. A "
    "pass with a higher peak elevation would give a longer arc to judge.",
    "Nothing in the corridor stands out at this offset, and the label agrees. Look at the "
    "band either side of the predicted centre for a faint drifting line. A capture with a "
    "cleaner axis reading would tighten the corridor.",
    # "confirm" in a purpose clause rather than an assertion, which the first version of
    # the checker refused in eight of twenty-five drafts.
    "The fitted centre sits away from the catalogue value, so the corridor is offset. Look "
    "at the band either side of it. A pass at a higher peak elevation could confirm the "
    "drift.",
    "The label and the model disagree here. Look along the predicted corridor, and settle "
    "it by confirming whether a drifting line runs through it. A capture from a second "
    "station would help.",
)

#: The remaining control case has to carry a frequency, and the only correct frequency is
#: the one in the packet, so it is formatted from the packet rather than typed. Typing one
#: would have made this control pass or fail on which observation happened to be first.
_FREQUENCY_CONTROL = (
    "The label and the model disagree about this pass, which was received at {mhz} MHz. "
    "To confirm what is there, look along the predicted corridor near closest approach. A "
    "second capture from another station would settle it."
)


def control_drafts(packet: EvidencePacket) -> tuple[str, ...]:
    """Drafts that break no rule, for this packet.

    Without a set like this, a checker that refused everything would score a perfect
    detection rate over :data:`ADVERSARIAL_DRAFTS` and look correct.
    """
    mhz = f"{packet.exact['receiver_frequency_hz'] / 1e6:.2f}".rstrip("0").rstrip(".")
    return CONTROL_DRAFTS + (
        _FREQUENCY_CONTROL.format(mhz=mhz),
        # "unknown" is a label value and an ordinary word. A substring test on it refused
        # this draft, which breaks no rule, and no control covered the case so the receipt
        # reported a false-refusal rate of zero while the checker was refusing sentences.
        "The axis reading is uncertain here and the direction of the drift is unknown. Look "
        "along the predicted corridor for a line either side of centre. A capture with "
        "cleaner axis labels would settle it.",
    )
