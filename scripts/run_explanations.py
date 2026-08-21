"""Freeze a generated reviewer note per card, check it, publish what survives (unit E1).

Two modes, and the split between them is the point.

    .venv/Scripts/python.exe scripts/run_explanations.py --freeze --repeats 3
    .venv/Scripts/python.exe scripts/run_explanations.py

``--freeze`` needs the local model. It generates one draft per card, writes them to
``tests/fixtures/granite_notes.json``, and then generates the same drafts again
``--repeats`` times to measure how much a re-run disagrees with what was frozen.

The default mode needs no model and no network. It reads the frozen drafts, rebuilds each
evidence packet from the committed console data, refuses to judge a draft whose packet has
changed underneath it, checks every draft, and writes ``artifacts/EXPLAIN_RECEIPT.json``
and ``apps/web/public/data/notes.json``. Run twice it produces identical bytes.

Why the freeze exists. Generation is not reproducible, and the first version of this
script assumed it was. Same prompt, same weights, temperature zero, fixed seed: thirty-six
percent of drafts differed when the prompts were repeated inside one process and fifty-six
percent differed in a fresh process after a model reload, with about one repeat in nine
crossing the checker's accept or refuse decision. One freeze produced no differences over
seventy-five repeats, which is why the instability has to be measured rather than assumed
in either direction. A console that renders text nobody can reproduce cannot be audited,
so the text a reviewer sees is committed and the disagreement rate is published beside it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.explain import (  # noqa: E402
    ALLOWED_TRANSFORMS,
    PROMPT_VERSION,
    EvidencePacket,
    MeasurementMissing,
    adversarial_drafts,
    build_packet,
    build_prompt,
    control_drafts,
    deterministic_note,
    prompt_contract_sha256,
    verify_note,
)

_DATA = REPO / "apps" / "web" / "public" / "data"
_RECEIPT = REPO / "artifacts" / "EXPLAIN_RECEIPT.json"
_NOTES = _DATA / "notes.json"
_FIXTURE = REPO / "tests" / "fixtures" / "granite_notes.json"


def _commit_stamp() -> str:
    """HEAD's commit date, recorded once when the drafts are frozen.

    Not for a published receipt. This was in EXPLAIN_RECEIPT.json on the reasoning that a
    commit date does not churn between two runs, which is true and not enough: it churns
    once per commit, so every commit after a publish left the committed receipt disagreeing
    with what the publisher produced. A clean clone found it, because a clone is always at a
    later commit than the publish. The receipt now carries digests of the committed inputs
    instead, which are a stronger provenance claim and a stable one, and the freeze record
    keeps this stamp because a freeze is a one-time event rather than a derived file.
    """
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip() or "unknown"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _packets() -> list[EvidencePacket]:
    """One packet per card that carries a fit.

    A card with no corridor is shipped on purpose: the console names the reason it
    could not be measured and draws no overlay. There is nothing for a note to be
    grounded in, so it gets no packet and no draft. Counted rather than dropped
    silently, because "no note here" and "the note was refused" are different
    findings and the receipt prints both.
    """
    cards = json.loads((_DATA / "cards.json").read_text(encoding="utf-8"))["cards"]
    entries = json.loads((_DATA / "queue.json").read_text(encoding="utf-8"))["entries"]
    by_id = {int(e["obs_id"]): e for e in entries}
    out: list[EvidencePacket] = []
    for card in cards:
        obs_id = int(card["obs_id"])
        if obs_id not in by_id:
            continue
        try:
            out.append(build_packet(card, by_id[obs_id]))
        except MeasurementMissing:
            _UNMEASURED.append(obs_id)
    return out


#: Observations the last call to :func:`_packets` refused to build a packet for.
_UNMEASURED: list[int] = []


def _checker_sensitivity(packets: list[EvidencePacket]) -> dict[str, Any]:
    """Both directions, over every observation, because one of them alone is misleading.

    Two things changed here after review. The measurement ran against the first card only,
    which made it depend on the console's card ordering rather than on the checker. And the
    headline was a refusal count: a checker that refused every adversarial draft for the
    wrong reason scored a perfect detection rate, with the mismatch recorded in a field
    beside it that nobody would read. Detection now means the expected code fired, and the
    looser number is published under its own name so both stay visible.
    """
    expected_fired = 0
    refused_at_all = 0
    adversarial = 0
    misattributed: list[dict[str, Any]] = []
    for packet in packets:
        for draft, expected in adversarial_drafts(packet):
            adversarial += 1
            result = verify_note(draft, packet)
            if result.ok:
                misattributed.append(
                    {"obs_id": packet.obs_id, "expected": expected, "reported": "accepted"}
                )
                continue
            refused_at_all += 1
            if expected in result.codes:
                expected_fired += 1
            else:
                misattributed.append(
                    {
                        "obs_id": packet.obs_id,
                        "expected": expected,
                        "reported": result.codes,
                    }
                )

    controls = 0
    refused_controls: list[dict[str, Any]] = []
    for packet in packets:
        for draft in control_drafts(packet):
            controls += 1
            result = verify_note(draft, packet)
            if not result.ok:
                refused_controls.append(
                    {
                        "obs_id": packet.obs_id,
                        "draft_prefix": draft[:60],
                        "codes": result.codes,
                    }
                )

    # Named for what they count. The earlier names said "drafts", and 525 is 21 drafts
    # checked against each of 25 packets: a judge opening explain.py counts seventeen
    # packet-independent cases and four built from the packet, so a headline of 525 drafts
    # overstated the suite by a factor of twenty-five. The per-observation counts are
    # published beside the totals so neither number can be read as the other.
    per_observation = len(adversarial_drafts(packets[0])) if packets else 0
    controls_per_observation = len(control_drafts(packets[0])) if packets else 0
    return {
        "observations_measured": len(packets),
        "adversarial_drafts_per_observation": per_observation,
        "adversarial_checks": adversarial,
        "refused_for_any_reason": refused_at_all,
        "caught_for_the_expected_reason": expected_fired,
        "detection_rate": round(expected_fired / adversarial, 4) if adversarial else None,
        "refusal_rate_over_adversarial": (
            round(refused_at_all / adversarial, 4) if adversarial else None
        ),
        "misattributed": misattributed,
        "control_drafts_per_observation": controls_per_observation,
        "control_checks": controls,
        "control_refused": len(refused_controls),
        "false_refusal_rate": (
            round(len(refused_controls) / controls, 4) if controls else None
        ),
        "control_refusals": refused_controls,
        "reading": (
            "A check is one draft against one observation's packet, so the totals are "
            "the per-observation counts times the observations measured. A detection rate "
            "of 1.0 means nothing on its own: a checker that refuses every draft scores "
            "it. The false-refusal rate over drafts that break no rule is the other half. "
            "Detection here requires the expected code and not merely a refusal, so "
            "refusing everything for one reason would show as a gap between "
            "detection_rate and refusal_rate_over_adversarial."
        ),
    }


def _frequency_near_misses(
    rows: list[dict[str, Any]], packets: list[EvidencePacket]
) -> dict[str, Any]:
    """How many refusals were a plausible but wrong downlink frequency.

    Worth counting separately rather than leaving inside a total. A number invented from
    nowhere is a nuisance; a number that is a real amateur satellite frequency within a few
    percent of this observation's is the failure that would have put the wrong band in front
    of a reviewer who had no way to tell.

    Two conditions, and the second one was missing. The value has to be within five percent
    of the observation's own receiver frequency in megahertz, and the draft has to have
    written it as a frequency. Without the unit check this counted any ungrounded literal in
    a numeric window: an invented sigma of 440 was published as a written_mhz of 440.0 with
    an error of 3510 kHz, under a docstring claiming the window excluded unrelated integers.
    The unit is now carried on the violation itself rather than parsed back out of a message.
    """
    by_id = {p.obs_id: p for p in packets}
    hits: list[dict[str, Any]] = []
    skipped_no_unit = 0
    for row in rows:
        packet = by_id.get(row["obs_id"])
        if packet is None:
            continue
        true_mhz = packet.exact["receiver_frequency_hz"] / 1e6
        if not true_mhz:
            continue
        for violation in row.get("violations", []):
            if violation["code"] != "UNGROUNDED_NUMBER":
                continue
            try:
                value = float(str(violation.get("literal", "")).replace(",", ""))
            except ValueError:
                continue
            if abs(value - true_mhz) / true_mhz > 0.05:
                continue
            if violation.get("unit") != "mhz":
                skipped_no_unit += 1
                continue
            hits.append(
                {
                    "obs_id": row["obs_id"],
                    "written_mhz": value,
                    "actual_mhz": round(true_mhz, 3),
                    "error_khz": round((value - true_mhz) * 1000.0, 1),
                }
            )
    return {
        "definition": (
            "An ungrounded number written in megahertz, within five percent of the "
            "observation's own receiver frequency in megahertz, so a wrong downlink rather "
            "than an arbitrary value that happens to fall in the same numeric range. "
            "Within five percent is also what makes each one dangerous: the invented value "
            "sits in the same band as the real downlink, so nothing about it looks wrong "
            "to a reader. The bands themselves are not classified here and no claim is made "
            "about them: an earlier draft of this project's README called all nine amateur "
            "satellite frequencies, and four of them are not, being 137 MHz meteorological "
            "downlinks and 401 MHz records."
        ),
        "occurrences": len(hits),
        "observations_affected": len({h["obs_id"] for h in hits}),
        "of_observations": len(rows),
        "in_range_but_not_written_as_a_frequency": skipped_no_unit,
        "cases": hits,
    }


# ---------------------------------------------------------------------------
# --freeze: the only mode that needs the model
# ---------------------------------------------------------------------------


def freeze(repeats: int, endpoint: str | None) -> int:
    from pipeline.tracetriage.granite import (
        MAX_TOKENS,
        MODEL,
        SEED,
        ModelUnavailable,
        generate,
        model_identity,
    )

    kwargs: dict[str, Any] = {"endpoint": endpoint} if endpoint else {}
    packets = _packets()
    try:
        identity = model_identity(**kwargs).as_dict()
    except ModelUnavailable as exc:
        print(f"cannot freeze without the model: {exc}", file=sys.stderr)
        return 2

    print(f"freezing {len(packets)} drafts from {identity['name']}")
    drafts: list[dict[str, Any]] = []
    for packet in packets:
        text = generate(build_prompt(packet), **kwargs)
        drafts.append(
            {
                "obs_id": packet.obs_id,
                "packet_sha256": packet.sha256(),
                "draft": text,
                "draft_sha256": _sha(text),
            }
        )
        print(f"  {packet.obs_id} {len(text):4d} chars")

    within: dict[str, Any] = {
        "repeats": 0,
        "note": "not measured in this freeze; pass --repeats to measure it",
    }
    if repeats > 0:
        frozen = {d["obs_id"]: d for d in drafts}
        changed_per_pass: list[int] = []
        verdict_flips: list[dict[str, Any]] = []
        for pass_index in range(repeats):
            changed = 0
            for packet in packets:
                text = generate(build_prompt(packet), **kwargs)
                if _sha(text) == frozen[packet.obs_id]["draft_sha256"]:
                    continue
                changed += 1
                was = verify_note(frozen[packet.obs_id]["draft"], packet).ok
                now = verify_note(text, packet).ok
                if was != now:
                    verdict_flips.append(
                        {
                            "obs_id": packet.obs_id,
                            "pass": pass_index + 1,
                            "frozen_verdict": "EMITTED" if was else "REFUSED",
                            "repeat_verdict": "EMITTED" if now else "REFUSED",
                        }
                    )
            changed_per_pass.append(changed)
            print(f"  repeat {pass_index + 1}: {changed}/{len(packets)} drafts differed")

        total = repeats * len(packets)
        within = {
            "repeats": repeats,
            "observations": len(packets),
            "drafts_compared": total,
            "drafts_that_differed": sum(changed_per_pass),
            "per_pass_differing": changed_per_pass,
            "text_disagreement_rate": round(sum(changed_per_pass) / total, 4),
            "verdict_flips": verdict_flips,
            "verdict_flip_rate": round(len(verdict_flips) / total, 4),
            "reading": (
                "Temperature is zero and the seed is fixed, so a prompt repeated inside "
                "the same process with the model already resident was expected to return "
                "identical text. It does not, and this is the rate at which it does not, "
                "measured without a process boundary so the reload is not the explanation."
            ),
        }

    _FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    _FIXTURE.write_text(
        json.dumps(
            {
                "frozen_at_commit": _commit_stamp(),
                "model": identity,
                "generation": {
                    "model_name": MODEL,
                    "seed": SEED,
                    "temperature": 0.0,
                    "max_tokens": MAX_TOKENS,
                    "prompt_version": PROMPT_VERSION,
                    "prompt_contract_sha256": prompt_contract_sha256(),
                },
                "stability": {
                    "within_process": within,
                    "across_processes": {
                        "passes": [],
                        "note": (
                            "Appended by --measure-drift, one record per invocation, "
                            "because a process boundary is the thing being measured and "
                            "a loop inside one process cannot cross it."
                        ),
                    },
                },
                "drafts": drafts,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {_FIXTURE.relative_to(REPO)}")
    return 0


# ---------------------------------------------------------------------------
# --measure-drift: one cross-process pass, appended to the fixture
# ---------------------------------------------------------------------------


def measure_drift(endpoint: str | None, unload: bool) -> int:
    """Generate the frozen prompts again in a fresh process and record the disagreement.

    A loop inside one invocation cannot measure this. The frozen text was produced by an
    earlier process, and the observation that started this measurement was two consecutive
    invocations of the old runner disagreeing on eight of twenty-five drafts, which a
    within-process repeat could not reproduce. ``--unload`` asks the runtime to drop the
    model first, so the pass also covers a reload rather than only a warm cache.
    """
    from pipeline.tracetriage.granite import (
        MODEL,
        ModelUnavailable,
        generate,
        model_identity,
    )

    if not _FIXTURE.exists():
        print("nothing frozen to compare against", file=sys.stderr)
        return 2
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    frozen = {int(d["obs_id"]): d for d in fixture["drafts"]}
    kwargs: dict[str, Any] = {"endpoint": endpoint} if endpoint else {}

    unloaded = None
    if unload:
        # The runtime's own command, not another request, so this script keeps exactly one
        # HTTP write verb between it and the model.
        proc = subprocess.run(
            ["ollama", "stop", MODEL], capture_output=True, text=True, check=False
        )
        unloaded = proc.returncode == 0

    try:
        identity = model_identity(**kwargs).as_dict()
    except ModelUnavailable as exc:
        print(f"cannot measure drift without the model: {exc}", file=sys.stderr)
        return 2
    if identity["digest"] != fixture["model"]["digest"]:
        print(
            "the installed model is not the one these drafts were frozen from, so a "
            "difference would measure the swap and not the runtime.",
            file=sys.stderr,
        )
        return 3

    packets = [p for p in _packets() if p.obs_id in frozen]
    differed: list[dict[str, Any]] = []
    for packet in packets:
        text = generate(build_prompt(packet), **kwargs)
        if _sha(text) == frozen[packet.obs_id]["draft_sha256"]:
            continue
        was = verify_note(frozen[packet.obs_id]["draft"], packet).ok
        now = verify_note(text, packet).ok
        differed.append(
            {
                "obs_id": packet.obs_id,
                "frozen_verdict": "EMITTED" if was else "REFUSED",
                "repeat_verdict": "EMITTED" if now else "REFUSED",
                "verdict_flipped": was != now,
            }
        )

    record = {
        "pass": len(fixture["stability"]["across_processes"]["passes"]) + 1,
        "model_unloaded_first": unloaded,
        "drafts_compared": len(packets),
        "drafts_that_differed": len(differed),
        "verdict_flips": sum(1 for d in differed if d["verdict_flipped"]),
        "differences": differed,
    }
    fixture["stability"]["across_processes"]["passes"].append(record)

    passes = fixture["stability"]["across_processes"]["passes"]
    compared = sum(p["drafts_compared"] for p in passes)
    fixture["stability"]["across_processes"] |= {
        "passes_recorded": len(passes),
        "drafts_compared": compared,
        "drafts_that_differed": sum(p["drafts_that_differed"] for p in passes),
        "verdict_flips": sum(p["verdict_flips"] for p in passes),
        "text_disagreement_rate": round(
            sum(p["drafts_that_differed"] for p in passes) / compared, 4
        )
        if compared
        else None,
        "verdict_flip_rate": round(sum(p["verdict_flips"] for p in passes) / compared, 4)
        if compared
        else None,
    }
    _FIXTURE.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        f"pass {record['pass']}: {record['drafts_that_differed']}"
        f"/{record['drafts_compared']} drafts differed, {record['verdict_flips']} crossed "
        f"the checker's decision (model unloaded first: {unloaded})"
    )
    return 0


# ---------------------------------------------------------------------------
# Default: check the frozen drafts, with no model and no network
# ---------------------------------------------------------------------------


def publish() -> int:
    if not _FIXTURE.exists():
        print(
            f"{_FIXTURE.relative_to(REPO)} is missing. Run with --freeze on a machine "
            f"with the model installed.",
            file=sys.stderr,
        )
        return 2

    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    frozen = {int(d["obs_id"]): d for d in fixture["drafts"]}
    packets = _packets()

    if fixture["generation"]["prompt_contract_sha256"] != prompt_contract_sha256():
        print(
            "the prompt contract has changed since these drafts were frozen, so they are "
            "answers to a different question. Re-freeze before publishing.",
            file=sys.stderr,
        )
        return 3

    rows: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for packet in packets:
        fallback = deterministic_note(packet)
        record = frozen.get(packet.obs_id)
        row: dict[str, Any] = {
            "obs_id": packet.obs_id,
            "packet_sha256": packet.sha256(),
            "packet_fields": len(packet.printed),
        }

        if record is None:
            row |= {"verdict": "NOT_FROZEN", "violations": [], "shipped": "deterministic"}
            why = "NO_FROZEN_DRAFT"
        elif record["packet_sha256"] != packet.sha256():
            # The facts moved under a frozen sentence. Checking it against the new packet
            # would report on a note nobody generated, so it is retired, not judged.
            row |= {
                "verdict": "PACKET_CHANGED",
                "violations": [],
                "shipped": "deterministic",
            }
            why = "FROZEN_DRAFT_IS_STALE"
        else:
            # Recomputed, not copied. The packet digest and the prompt digest are both
            # checked above, and copying this one made the fixture's own text editable
            # without detection: change the draft, leave the digest, and the new sentence
            # is verified and published while the receipt cites the digest of the old one.
            actual = _sha(record["draft"])
            if actual != record["draft_sha256"]:
                print(
                    f"observation {packet.obs_id}: the frozen draft does not match its "
                    f"recorded digest. The fixture has been edited by hand; re-freeze.",
                    file=sys.stderr,
                )
                return 4
            result = verify_note(record["draft"], packet)
            row |= {
                "verdict": "EMITTED" if result.ok else "REFUSED",
                "violations": result.violations,
                "codes": result.codes,
                "draft_chars": len(record["draft"]),
                "draft_sha256": actual,
                "shipped": "generated" if result.ok else "deterministic",
            }
            notes.append(
                {
                    "obs_id": packet.obs_id,
                    "note": record["draft"] if result.ok else fallback,
                    "source": "generated" if result.ok else "deterministic",
                    "refused_codes": [] if result.ok else result.codes,
                    "why": None if result.ok else "GROUNDING_CHECK_REFUSED",
                }
            )
            rows.append(row)
            continue

        notes.append(
            {
                "obs_id": packet.obs_id,
                "note": fallback,
                "source": "deterministic",
                "refused_codes": [],
                "why": why,
            }
        )
        rows.append(row)

    emitted = sum(1 for r in rows if r["verdict"] == "EMITTED")
    refused = sum(1 for r in rows if r["verdict"] == "REFUSED")
    decided = emitted + refused
    by_code: dict[str, int] = {}
    for row in rows:
        for code in row.get("codes", []) or []:
            by_code[code] = by_code.get(code, 0) + 1

    receipt = {
        # Provenance by content rather than by clock: the receipt is a pure function of the
        # frozen drafts and the prompt contract, both committed, so two runs of the
        # publisher at any two commits produce identical bytes.
        "frozen_drafts_sha256": _sha(_FIXTURE.read_text(encoding="utf-8")),
        "unit": "E1",
        "model": fixture["model"],
        "generation": fixture["generation"]
        | {"allowed_transforms": list(ALLOWED_TRANSFORMS)},
        "drafts_frozen_at_commit": fixture["frozen_at_commit"],
        "counts": {
            "observations": len(rows),
            # Cards the console ships with a named degrade instead of a fit. They are
            # not refusals: the checker never saw a sentence about them, because the
            # packet builder will not invent a 0 Hz offset to write one from.
            "cards_without_a_fit": sorted(set(_UNMEASURED)),
            "n_cards_without_a_fit": len(set(_UNMEASURED)),
            "decided_by_the_checker": decided,
            "emitted": emitted,
            "refused": refused,
            "refusal_rate": round(refused / decided, 4) if decided else None,
            "violations_by_code": dict(sorted(by_code.items())),
        },
        "hallucinated_downlink_frequency": _frequency_near_misses(rows, packets),
        "run_to_run_stability": fixture["stability"],
        "checker_sensitivity": _checker_sensitivity(packets),
        "per_observation": rows,
        "what_this_does_not_measure": (
            "Whether a note that passed the checker is useful. Grounding is a property of "
            "the numbers in a sentence, not of the sentence being worth reading, and "
            "nothing here asks a reviewer. Kill gate 4's blinded study is the instrument "
            "for that and it is still OPEN."
        ),
    }

    _RECEIPT.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8", newline="\n")
    _NOTES.write_text(
        json.dumps(
            {
                "drafts_frozen_at_commit": receipt["drafts_frozen_at_commit"],
                "model": fixture["model"],
                "prompt_version": fixture["generation"]["prompt_version"],
                "notes": notes,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    sens = receipt["checker_sensitivity"]
    freq = receipt["hallucinated_downlink_frequency"]
    tail = f" ({100 * refused / decided:.0f}% refusal)" if decided else ""
    print(f"{len(rows)} observations: {emitted} emitted, {refused} refused{tail}")
    print(
        f"checker: {sens['caught_for_the_expected_reason']}/{sens['adversarial_checks']} "
        f"adversarial checks caught for the right reason, {sens['control_refused']}"
        f"/{sens['control_checks']} clean checks refused"
    )
    print(
        f"wrong downlink frequency written in {freq['observations_affected']} of "
        f"{freq['of_observations']} observations"
    )
    print(f"wrote {_RECEIPT.relative_to(REPO)} and {_NOTES.relative_to(REPO)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--freeze",
        action="store_true",
        help="Generate and commit fresh drafts. Needs the local model.",
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=0,
        help="With --freeze, extra passes used to measure run-to-run disagreement.",
    )
    ap.add_argument(
        "--measure-drift",
        action="store_true",
        help="Regenerate the frozen prompts in this process and record the disagreement.",
    )
    ap.add_argument(
        "--unload",
        action="store_true",
        help="With --measure-drift, ask the runtime to drop the model first.",
    )
    ap.add_argument(
        "--endpoint",
        default=None,
        help="Model runtime base URL. Refused unless it resolves to loopback.",
    )
    args = ap.parse_args(argv)

    if not _packets():
        print("no card has a queue entry; nothing to explain", file=sys.stderr)
        return 1
    if args.freeze:
        return freeze(args.repeats, args.endpoint)
    if args.measure_drift:
        return measure_drift(args.endpoint, args.unload)
    return publish()


if __name__ == "__main__":
    raise SystemExit(main())
