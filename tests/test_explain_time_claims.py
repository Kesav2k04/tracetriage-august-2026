"""Where a note tells a reviewer to look, and what happens when a card has no fit.

Two defects, one root cause: a closed world of numbers was mistaken for a closed world
of statements.

The first. Observation 14744250 shipped a Granite draft reading "focus on the waterfall
image around the 284-second mark, where the signal should be strongest at an elevation
of approximately 37 degrees". Both numbers are in the evidence packet: 284 is
``pass_duration_s`` and 37 is ``max_elevation_deg``. The grounding checker passed it and
the console published it. That pass has ``closest_approach_fraction`` 0.0, so its
strongest moment is the first sample of the recording and the note sent a reviewer to
the last one. Token membership blessed a sentence that was backwards.

The second. :func:`build_packet` read the corridor block with ``.get(name, 0.0)``, so a
card with no fit produced a packet asserting a fitted offset of 0 Hz, a half width of
0 Hz, a peak elevation of 0 degrees and closest approach at the first sample. The
console export refused the same absence and rendered the card as degraded. Two
exporters disagreeing about what a missing measurement means is how a default becomes a
published number, and the packet builder was the one that lied.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.tracetriage.explain import (
    TIME_TOLERANCE_FLOOR_S,
    TIME_TOLERANCE_FRACTION,
    MeasurementMissing,
    build_packet,
    deterministic_note,
    time_claim_violations,
    verify_note,
)

REPO = Path(__file__).resolve().parents[1]
_DATA = REPO / "apps" / "web" / "public" / "data"

#: The observation the rule was written for: closest approach at the first sample.
ONE_SIDED_OBS = 14744250

#: The sentence that shipped. Kept verbatim, because a paraphrase would not prove that
#: the checker used to accept this exact text.
SHIPPED_DRAFT = (
    "The observed receiver frequency of 387174755 Hz does not align with the NORAD "
    "catalogue's expected frequency for ID 46487. To confirm, focus on the waterfall "
    "image around the 284-second mark, where the signal should be strongest at an "
    "elevation of approximately 37 degrees."
)


def _cards_and_entries() -> tuple[dict[int, dict], dict[int, dict]]:
    cards = json.loads((_DATA / "cards.json").read_text(encoding="utf-8"))["cards"]
    entries = json.loads((_DATA / "queue.json").read_text(encoding="utf-8"))["entries"]
    return (
        {int(c["obs_id"]): c for c in cards},
        {int(e["obs_id"]): e for e in entries},
    )


@pytest.fixture(scope="module")
def one_sided_packet():
    cards, entries = _cards_and_entries()
    card = cards.get(ONE_SIDED_OBS)
    entry = entries.get(ONE_SIDED_OBS)
    if card is None or entry is None:
        pytest.skip(f"observation {ONE_SIDED_OBS} is not in the shipped console data")
    packet = build_packet(card, entry)
    assert packet.exact["closest_approach_fraction"] == pytest.approx(0.0), (
        "this fixture is the pass whose closest approach is the first sample. If that "
        "changed, the test below is measuring something else."
    )
    return packet


@pytest.fixture(scope="module")
def packets():
    cards, entries = _cards_and_entries()
    out = []
    for obs_id, card in cards.items():
        if obs_id in entries:
            try:
                out.append(build_packet(card, entries[obs_id]))
            except MeasurementMissing:
                continue
    assert out, "no shipped card carries a fit"
    return out


# ---------------------------------------------------------------------------
# The time claim
# ---------------------------------------------------------------------------


def test_the_duration_used_as_a_clock_time_is_refused(one_sided_packet):
    """The exact defect: every number grounded, the statement still false."""
    result = verify_note(SHIPPED_DRAFT, one_sided_packet)

    assert not result.ok
    assert "MISLOCATED_TIME_CLAIM" in result.codes
    # Not by way of an ungrounded number. Both numbers are in the packet, which is why
    # the old checker passed this, and a fix that worked by refusing 284 as ungrounded
    # would be refusing a fact.
    assert "UNGROUNDED_NUMBER" not in result.codes


def test_the_violation_says_where_closest_approach_actually_is(one_sided_packet):
    detail = time_claim_violations(SHIPPED_DRAFT, one_sided_packet)[0]["detail"]

    assert "284 s" in detail
    assert "closest approach is at 0 s" in detail
    assert "fraction 0.00" in detail


def test_a_time_at_closest_approach_is_allowed(packets):
    """The rule must not refuse the position the packet does support."""
    packet = next(
        p
        for p in packets
        if 0.4 <= p.exact["closest_approach_fraction"] <= 0.6
        and p.exact["pass_duration_s"] > 120
    )
    tca_s = (
        packet.exact["closest_approach_fraction"] * packet.exact["pass_duration_s"]
    )
    draft = (
        f"The corridor is worth a look. Focus on the waterfall image around the "
        f"{tca_s:.0f}-second mark, where the pass reaches closest approach."
    )

    assert time_claim_violations(draft, packet) == []


def test_a_duration_is_not_a_position(one_sided_packet):
    """"The pass lasted 284 seconds" points nowhere and stays legal."""
    draft = (
        "The recording runs for 284 seconds and the corridor sits inside its half "
        "width. Look at the corridor."
    )

    assert time_claim_violations(draft, one_sided_packet) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "Look at the end of the pass for the strongest signal.",
        "The carrier should be clearest late in the pass.",
        "Look halfway through the recording for the carrier.",
        "Look at the middle of the pass duration for the carrier.",
    ],
)
def test_a_worded_position_is_checked_against_the_geometry(phrase, one_sided_packet):
    """No number at all, and still a claim about where to look."""
    codes = {v["code"] for v in time_claim_violations(phrase, one_sided_packet)}

    assert codes == {"MISLOCATED_TIME_CLAIM"}


def test_the_wording_that_matches_the_geometry_is_kept(one_sided_packet):
    """Closest approach at 0.0 makes "the start of the pass" the true statement."""
    draft = "The signal should be strongest at the start of the pass."

    assert time_claim_violations(draft, one_sided_packet) == []


def test_a_fraction_of_the_pass_is_checked_too(one_sided_packet):
    wrong = "Peak elevation was 37.1 degrees at 0.50 of the pass."
    right = "Peak elevation was 37.1 degrees at 0.00 of the pass."

    assert {v["code"] for v in time_claim_violations(wrong, one_sided_packet)} == {
        "MISLOCATED_TIME_CLAIM"
    }
    assert time_claim_violations(right, one_sided_packet) == []


def test_the_tolerance_is_a_tenth_of_the_recording(packets):
    """The policy is quoted rather than restated, and it has a floor."""
    packet = next(p for p in packets if p.exact["pass_duration_s"] > 200)
    duration = packet.exact["pass_duration_s"]
    tca_s = packet.exact["closest_approach_fraction"] * duration
    tolerance = max(TIME_TOLERANCE_FRACTION * duration, TIME_TOLERANCE_FLOOR_S)

    inside = f"Look at the {tca_s + tolerance * 0.5:.0f}-second mark."
    outside = f"Look at the {tca_s + tolerance * 2:.0f}-second mark."

    assert time_claim_violations(inside, packet) == []
    assert {v["code"] for v in time_claim_violations(outside, packet)} == {
        "MISLOCATED_TIME_CLAIM"
    }


def test_the_deterministic_template_survives_its_own_rule(packets):
    """The template writes closest approach as a fraction, so this rule reads it.

    A rule that refuses the fallback note would take the console's last honest option
    away on every card, which is worse than the defect it closes.
    """
    for packet in packets:
        note = deterministic_note(packet)
        assert time_claim_violations(note, packet) == [], (
            f"the template's own sentence fails the time rule on {packet.obs_id}"
        )


def test_no_shipped_note_points_at_the_wrong_time():
    """The published console, checked end to end rather than by construction."""
    cards, entries = _cards_and_entries()
    notes = json.loads((_DATA / "notes.json").read_text(encoding="utf-8"))["notes"]

    for record in notes:
        obs_id = int(record["obs_id"])
        if obs_id not in entries or obs_id not in cards:
            continue
        try:
            packet = build_packet(cards[obs_id], entries[obs_id])
        except MeasurementMissing:
            continue
        assert time_claim_violations(record["note"], packet) == [], (
            f"observation {obs_id} ships a note that points at a time its geometry "
            f"does not support: {record['note']!r}"
        )


# ---------------------------------------------------------------------------
# The missing fit
# ---------------------------------------------------------------------------


def test_a_card_with_no_fit_refuses_to_become_a_packet():
    cards, entries = _cards_and_entries()
    obs_id = next(iter(entries))
    card = dict(cards[obs_id])
    card["corridor"] = None

    with pytest.raises(MeasurementMissing) as raised:
        build_packet(card, entries[obs_id])

    message = str(raised.value)
    assert "fitted_offset_hz" in message
    assert "0.0" in message or "0 Hz" in message


@pytest.mark.parametrize(
    "field",
    [
        "fitted_offset_hz",
        "fitted_offset_ppm",
        "tca_frac",
        "max_elevation_deg",
        "half_width_hz",
        "sigma_curved",
        "sigma_vertical",
    ],
)
def test_each_corridor_field_is_required_on_its_own(field):
    """One field at a time, because a partial fit is the shape that slips through."""
    cards, entries = _cards_and_entries()
    obs_id = next(
        oid for oid, c in cards.items() if oid in entries and (c.get("corridor") or {})
    )
    card = json.loads(json.dumps(cards[obs_id]))
    card["corridor"].pop(field)

    with pytest.raises(MeasurementMissing) as raised:
        build_packet(card, entries[obs_id])
    assert field in str(raised.value)


def test_zero_is_still_a_measurement_when_it_was_measured():
    """A fit that really is 0.0 Hz is not a missing fit.

    The guard checks for absence, not for falsiness. An offset that fits at exactly
    zero is a legitimate and interesting result, and a truthiness test would have
    thrown it away along with the missing ones.
    """
    cards, entries = _cards_and_entries()
    obs_id = next(
        oid for oid, c in cards.items() if oid in entries and (c.get("corridor") or {})
    )
    card = json.loads(json.dumps(cards[obs_id]))
    card["corridor"]["fitted_offset_hz"] = 0.0

    packet = build_packet(card, entries[obs_id])
    assert packet.exact["fitted_offset_hz"] == 0.0
    assert packet.printed["fitted_offset_hz"] == "0"
