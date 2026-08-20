"""Export what the Python grounding checker decides, so the TypeScript port can be held to it.

The console is a static export. A judge who wants to change one digit in a reviewer note and
watch the checker refuse it needs the checker in the browser, so `apps/web/lib/grounding.ts`
is a port of `pipeline/tracetriage/explain.py`. A port is worth nothing on its own: two
implementations of the same rules drift, and the drift is invisible because each one passes
its own tests.

This writes the shared answer key. For every shipped observation that has a queue entry and
a fit, it runs the Python checker over a fixed list of drafts and records what it decided:
the codes, and every violation with its detail, literal and unit. `apps/web/tests/
grounding.test.ts` replays each row through the TypeScript checker and requires the same
answer. `tests/test_grounding_parity.py` regenerates this file from the current Python source
and requires the same bytes. Change either checker without changing the other and one of
those two tests fails.

The draft list is five sets, and the last one is the reason this script exists rather than
just reusing the pipeline's own measurement set:

  - `adversarial_drafts(packet)`: the pipeline's own set, each labelled with the code it must
    produce.
  - `control_drafts(packet)`: drafts that break no rule. Without these a checker that refused
    everything would look perfect.
  - the deterministic template, which every packet must pass.
  - the note actually shipped for that observation.
  - drafts written here, aimed at the two rules whose Python and JavaScript spellings differ
    most: the time-position rule, whose detail strings are formatted with `.0f` and `.2f`
    where Python rounds half to even and `toFixed` rounds half away from zero, and the unit
    transforms, whose regular expression carries a word boundary that behaves differently
    around a percent sign. Several of them are expected to be grounded rather than refused,
    because a port that refuses too much is as wrong as one that refuses too little and only
    the grounded rows can catch it.

    .venv/Scripts/python.exe scripts/export_grounding_golden.py
    .venv/Scripts/python.exe scripts/export_grounding_golden.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pipeline.tracetriage.explain import (  # noqa: E402
    EvidencePacket,
    MeasurementMissing,
    adversarial_drafts,
    build_packet,
    control_drafts,
    deterministic_note,
    verify_note,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "apps" / "web" / "public" / "data"
CHECKER = REPO / "pipeline" / "tracetriage" / "explain.py"
GOLDEN = DATA / "grounding_golden.json"


def _load(name: str) -> dict[str, Any]:
    path = DATA / name
    if not path.exists():
        raise SystemExit(
            f"{path} is missing and this script reads it. Run "
            f"scripts/build_console_data.py rather than exporting an answer key with a "
            f"hole in it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: pathlib.Path) -> str:
    """The checker's own digest, over bytes, so a newline translation cannot hide a change."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hand_written_drafts(packet: EvidencePacket) -> tuple[tuple[str, str], ...]:
    """Drafts aimed at the time rule and the unit transforms, as (name, draft).

    Written against a packet rather than typed as constants, because the interesting cases
    are all built out of that observation's own numbers: a duration offered as a position, a
    frequency converted correctly, a percentage of a field the transform is not scoped to.

    What each row is expected to produce is not written down here. It is whatever the Python
    checker says, which is the point of an answer key: a hand-written expectation would make
    this file a second opinion instead of a record. `tests/test_grounding_parity.py` asserts
    the properties that must hold across the set, which is where a claim about these drafts
    belongs.
    """
    duration = packet.exact["pass_duration_s"]
    frac = packet.exact["closest_approach_fraction"]
    tca_s = frac * duration
    offset = packet.exact["fitted_offset_hz"]
    sigma = packet.exact["sigma_curved"]
    hz_per_px = packet.exact["hz_per_pixel"]
    half_width = packet.exact["corridor_half_width_hz"]
    rx_hz = packet.exact["receiver_frequency_hz"]
    prob = packet.exact["model_probability"]
    score = packet.exact["queue_score"]
    # Correct megahertz for this receiver, spelled the way the control draft spells it.
    mhz = f"{rx_hz / 1e6:.2f}".rstrip("0").rstrip(".")
    # A fraction of the pass at the far end from closest approach, so the claim is wrong on
    # every observation rather than only on the ones whose approach is early.
    far_frac = 0.0 if frac >= 0.5 else 1.0

    return (
        # ---- the time rule -----------------------------------------------------------
        # The defect this rule closes: the recorded length of the pass offered as the place
        # to look. Every number is in the packet and the sentence points at the wrong end.
        (
            "time-duration-as-mark",
            f"Look around the {duration:.0f}-second mark, where the trace should be "
            f"strongest along the corridor.",
        ),
        (
            "time-duration-as-t",
            f"At t = {duration:.0f} s the corridor is at its narrowest. Look there for a "
            f"drifting line.",
        ),
        (
            "time-duration-seconds-into",
            f"The corridor crosses the catalogue centre {duration:.0f} seconds into the "
            f"pass.",
        ),
        (
            "time-fraction-far-end",
            f"The strongest part of the recording sits at {far_frac:.2f} of the pass. Look "
            f"there first.",
        ),
        (
            "time-word-late",
            "The trace should be strongest late in the pass. Look along the corridor there.",
        ),
        (
            "time-word-early",
            "The trace should be strongest early in the pass. Look along the corridor "
            "there.",
        ),
        (
            "time-word-halfway",
            "Look halfway through the recording, along the predicted corridor, for a faint "
            "drifting line.",
        ),
        (
            "time-word-end",
            "The best evidence sits at the end of the pass. Look along the corridor there.",
        ),
        # The three negative controls for the same rule. A time rule that refuses the
        # position it was built to allow, or that reads a duration as a position, is worse
        # than no rule: it would refuse the deterministic template on every card.
        (
            "time-at-closest-approach",
            f"The corridor is easiest to read at {frac:.2f} of the pass. Look along the "
            f"predicted centre there.",
        ),
        (
            "time-seconds-at-closest-approach",
            f"Look about {tca_s:.0f} seconds into the pass, along the predicted corridor, "
            f"for a faint line.",
        ),
        (
            "time-duration-stated-as-duration",
            f"The recording runs {duration:.0f} seconds and the corridor sits "
            f"{offset:.0f} Hz from the catalogue centre. Look along the predicted centre.",
        ),
        # ---- the unit transforms -----------------------------------------------------
        # A percentage of a field the percentage transform is not scoped to. Dividing or
        # multiplying any number by a hundred would otherwise let a sigma justify a
        # probability.
        (
            "unit-percent-borrowed-by-sigma",
            f"The curved fit scores {sigma * 100:.1f}% against the vertical line. Look "
            f"along the corridor.",
        ),
        # A megahertz conversion of a field that does not end in _hz, which is the scoping
        # the transform list carries.
        (
            "unit-mhz-borrowed-by-pixel-scale",
            f"The axis reads {hz_per_px / 1e6:.6f} MHz per pixel across the image.",
        ),
        # The false downlink this whole unit exists for. On observation 14740031 the
        # receiver is at 436400000 Hz, so this is the acceptance case from the handover.
        (
            "unit-false-mhz-downlink",
            "The downlink sits at 437.2 MHz, so the corridor is drawn there.",
        ),
        # ---- transforms that must be accepted ----------------------------------------
        # Each of these is a correct conversion, and each one exercises a piece of the unit
        # reader that a port would plausibly get wrong: the kilohertz branch, the alphabetic
        # spelling, the percent sign whose word boundary made the transform unreachable, the
        # spelled-out "percent", the thousands separator, and the explicit plus sign.
        (
            "unit-khz-of-half-width",
            f"The corridor half width is {half_width / 1e3:.1f} kHz either side of the "
            f"predicted centre.",
        ),
        (
            "unit-megahertz-spelled-out",
            f"The pass was received at {mhz} megahertz, which is where the corridor is "
            f"drawn.",
        ),
        (
            "unit-percent-of-probability",
            f"The model probability is {prob * 100:.1f}% for this pass, and the label "
            f"disagrees.",
        ),
        (
            "unit-percent-word-of-probability",
            f"The model reads {prob * 100:.4f} percent for this pass, and the label "
            f"disagrees.",
        ),
        (
            "unit-percent-of-queue-score",
            f"The queue score is {score * 100:.1f}% and the label disagrees with the model.",
        ),
        (
            "unit-comma-grouped-frequency",
            f"The pass was received at {int(rx_hz):,} Hz, which is where the corridor is "
            f"drawn.",
        ),
        (
            "unit-signed-offset",
            f"The corridor sits {offset:+.0f} Hz from the catalogue centre. Look along the "
            f"predicted centre.",
        ),
    )


def rows_for(packet: EvidencePacket, shipped: str | None) -> list[dict[str, Any]]:
    """Every draft/observation pair for one packet, with the checker's answer."""
    out: list[dict[str, Any]] = []

    def add(kind: str, name: str, expects: str | None, draft: str) -> None:
        verdict = verify_note(draft, packet)
        out.append(
            {
                "obs_id": packet.obs_id,
                "kind": kind,
                "name": name,
                "expects": expects,
                "draft": draft,
                "ok": verdict.ok,
                "codes": verdict.codes,
                "violations": verdict.violations,
            }
        )

    for index, (draft, code) in enumerate(adversarial_drafts(packet)):
        add("adversarial", str(index), code, draft)
    for index, draft in enumerate(control_drafts(packet)):
        add("control", str(index), None, draft)
    add("deterministic", "template", None, deterministic_note(packet))
    if shipped is not None:
        add("shipped", "notes.json", None, shipped)
    for name, draft in hand_written_drafts(packet):
        add("handwritten", name, None, draft)
    return out


def packet_record(packet: EvidencePacket) -> dict[str, Any]:
    """The packet itself, so a formatting difference is caught where it happens.

    Every refusal depends on `printed`, because the token set is read out of the rendered
    text. A port that formatted one field to the wrong precision would show up in the rows as
    a handful of drafts disagreeing, several observations away from the cause. Carrying the
    text and both maps means the failing assertion names the field.
    """
    return {
        "obs_id": packet.obs_id,
        "printed": dict(packet.printed),
        "exact": dict(packet.exact),
        "vocabulary": sorted(packet.vocabulary),
        "text": packet.as_text(),
    }


def build_payload() -> dict[str, Any]:
    """The whole answer key, in a fixed order so two runs write the same bytes."""
    cards = {card["obs_id"]: card for card in _load("cards.json")["cards"]}
    entries = {entry["obs_id"]: entry for entry in _load("queue.json")["entries"]}
    notes = {note["obs_id"]: note for note in _load("notes.json")["notes"]}

    rows: list[dict[str, Any]] = []
    packets: list[dict[str, Any]] = []
    observations: list[int] = []
    skipped: list[dict[str, str]] = []
    for obs_id in sorted(cards):
        entry = entries.get(obs_id)
        if entry is None:
            skipped.append({"obs_id": str(obs_id), "reason": "no queue entry"})
            continue
        try:
            packet = build_packet(cards[obs_id], entry)
        except MeasurementMissing:
            # The same refusal the console makes: a card with no fit has no packet, so there
            # is nothing to hold the two checkers to. Recorded rather than dropped, because a
            # shrinking observation set is how a parity check quietly stops checking.
            skipped.append({"obs_id": str(obs_id), "reason": "no fit"})
            continue
        observations.append(obs_id)
        packets.append(packet_record(packet))
        note = notes.get(obs_id)
        rows.extend(rows_for(packet, note["note"] if note else None))

    return {
        "purpose": (
            "What pipeline/tracetriage/explain.py decides about each draft. Replayed by "
            "apps/web/tests/grounding.test.ts against the TypeScript port and regenerated "
            "by tests/test_grounding_parity.py against the Python source."
        ),
        "checker": "pipeline/tracetriage/explain.py",
        "checker_sha256": _digest(CHECKER),
        "generator": "scripts/export_grounding_golden.py",
        "n_observations": len(observations),
        "n_rows": len(rows),
        "observations": observations,
        "skipped": skipped,
        "packets": packets,
        "rows": rows,
    }


def render() -> str:
    return json.dumps(build_payload(), indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "regenerate into memory and compare against the committed file, writing nothing"
        ),
    )
    args = parser.parse_args(argv)

    rendered = render()
    payload = json.loads(rendered)
    if args.check:
        if not GOLDEN.exists():
            print(f"{GOLDEN} does not exist. Run scripts/export_grounding_golden.py.")
            return 1
        if GOLDEN.read_text(encoding="utf-8") == rendered:
            print(
                f"{GOLDEN.name} is current: {payload['n_rows']} rows over "
                f"{payload['n_observations']} observations, checker "
                f"{payload['checker_sha256'][:12]}"
            )
            return 0
        print(f"{GOLDEN.name} is stale. Run scripts/export_grounding_golden.py.")
        return 1

    GOLDEN.write_text(rendered, encoding="utf-8")
    print(
        f"{GOLDEN.name} written: {payload['n_rows']} rows over "
        f"{payload['n_observations']} observations, checker "
        f"{payload['checker_sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
