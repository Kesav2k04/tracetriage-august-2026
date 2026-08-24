"""Re-read every gate 3 pool axis with the reader that cannot invent a value.

    .venv/Scripts/python.exe scripts/audit_pool_axes.py            # rebuild, needs the snapshot
    .venv/Scripts/python.exe scripts/audit_pool_axes.py --check    # arithmetic only, offline

Why this exists
---------------
``parse_waterfall``'s default is ``label_reader="ocr"``, which is easyocr, and every number in
``artifacts/GATE3_POOL.json`` came through it. The deployed endpoint passes ``"auto"``, which
prefers the template matcher in ``glyph_axis`` and falls back to easyocr only when the matcher
reads too few labels. So the same observation can get two different frequency axes depending on
which surface a reader asks, and on 2026-08-24 one did: posting observation 14745990 to
``/api/live/`` returned UNCORRECTED at 9.40 sigma where the committed pool holds UNRESOLVED at
2.64, because the endpoint read 123.7624 Hz/px and the pool holds 1,157.0248.

Reading the tick labels off that image settles which is right. They run -30 to +30 kHz across
823 pixels, so 60 kHz spans about 485 px, which is 123.76 Hz/px. At 1,157 Hz/px the same span
would occupy 52 px. The committed axis is wrong by 9.35x and the pool's verdict for that
observation follows from it.

``docs/CLAIM_REGISTER.md`` already records the two halves of this: easyocr read the centre tick
of 14736773 as 562 where the value is 0, and over a 500-image sweep the template matcher never
produced a label set that was not an arithmetic progression, so its failure is a missing label
and never a wrong one. The reader that can be wrong is the one every committed number came
through. This counts how far that goes and what it does to the gate.

What it decides, and what it does not
-------------------------------------
A disagreement is not by itself a verdict on which reader is right. The tolerance is deliberate:
anything inside 1 percent is treated as the same axis, because the two readers fit through
different tick centres and a sub-pixel difference is not a disagreement about the image. What
the audit does establish is the size of the exposure, and whether gate 3's published rate
survives the worst reading of it. Both robustness scenarios are reported whether they clear the
threshold or not.

The rebuild needs the stage-1 snapshot, because it re-reads the images. ``--check`` recomputes
the gate arithmetic from the committed artifact and needs nothing but the repository, so the
half of this that can be verified in a clean clone is verified there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

ARTIFACTS = REPO / "artifacts"
POOL = ARTIFACTS / "GATE3_POOL.json"
RECEIPT = ARTIFACTS / "GATE3_RECEIPT.json"
OUT = ARTIFACTS / "AXIS_READER_AUDIT.json"

#: Inside this, the two readers are reading the same axis. Outside it, they are not.
TOLERANCE = 0.01

#: Where the snapshot's waterfall PNGs live. The environment variable is the same one the rest
#: of the pipeline reads, pointing at the pages directory; the images sit beside it.
ENV_PAGES = "TRACETRIAGE_PAGES_DIR"


def _images_dir() -> Path | None:
    pages = os.environ.get(ENV_PAGES)
    if not pages:
        return None
    candidate = Path(pages).parent / "waterfalls"
    return candidate if candidate.is_dir() else None


def _lower_bound(k: int, n: int, confidence: float = 0.95) -> float:
    """Clopper-Pearson one-sided lower bound, which is the estimator gate 3 published.

    Reimplemented here rather than imported so this file can be read on its own, and checked
    against the receipt's own figure on every run: `_gate3_effect` recomputes the published
    rate and bound from the receipt's rows and raises if either disagrees. A robustness number
    from a different estimator than the one it is compared against says nothing.
    """
    if n <= 0:
        raise ValueError("no scored observations")
    if k <= 0:
        return 0.0
    if k == n:
        return float((1 - confidence) ** (1 / n))
    from scipy.stats import beta  # noqa: PLC0415 - kept out of the offline import path

    return float(beta.ppf(1 - confidence, k, n - k + 1))


def _scored_rows(receipt: dict) -> list[dict]:
    return [
        row
        for row in receipt["observations"]
        if (row.get("null_calibration") or {}).get("discriminates") is not None
    ]


def _gate3_effect(disputed: set[int]) -> dict:
    """What the disagreement does to the published rate, under two readings of it."""
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    scored = _scored_rows(receipt)
    discriminating = [r for r in scored if r["null_calibration"]["discriminates"]]
    n, k = len(scored), len(discriminating)

    published_rate = receipt["discriminating_rate"]
    published_bound = receipt["rate_lower_bound_95"]
    if abs(k / n - published_rate) > 1e-9:
        raise SystemExit(
            f"recomputed rate {k / n} does not match the receipt's {published_rate}. "
            "The rows and the summary disagree, so neither can be used as a baseline."
        )
    if abs(_lower_bound(k, n) - published_bound) > 1e-6:
        raise SystemExit(
            f"recomputed bound {_lower_bound(k, n)} does not match the receipt's "
            f"{published_bound}. This audit's estimator is not the receipt's."
        )

    hit = [r for r in scored if r["obs_id"] in disputed]
    hit_discriminating = [r for r in hit if r["null_calibration"]["discriminates"]]
    threshold = receipt["threshold"]

    dropped_k = k - len(hit_discriminating)
    dropped_n = n - len(hit)
    missed_k = k - len(hit_discriminating)

    scenarios = {
        "as_published": {"discriminating": k, "scored": n},
        "disputed_rows_dropped": {"discriminating": dropped_k, "scored": dropped_n},
        "disputed_rows_counted_as_misses": {"discriminating": missed_k, "scored": n},
    }
    for s in scenarios.values():
        s["rate"] = s["discriminating"] / s["scored"]
        s["rate_lower_bound_95"] = _lower_bound(s["discriminating"], s["scored"])
        s["clears_threshold"] = s["rate_lower_bound_95"] >= threshold

    return {
        "threshold": threshold,
        "published_rate": published_rate,
        "published_rate_lower_bound_95": published_bound,
        "scored_rows_with_a_disputed_axis": len(hit),
        "of_those_currently_discriminating": len(hit_discriminating),
        "disputed_scored_obs_ids": sorted(r["obs_id"] for r in hit),
        "scenarios": scenarios,
        # Generated from the counts above rather than written beside them. An earlier draft
        # typed "seven of the eight" and "both scenarios clear the threshold" into this field,
        # which would have gone stale the first time a rebuild moved either number while every
        # digest still matched.
        "reading": _reading(scenarios, len(hit), len(hit_discriminating), threshold),
    }


def _reading(scenarios: dict, hit: int, hit_discriminating: int, threshold: float) -> str:
    """Say what the scenarios show, in words derived from the scenarios."""
    already_failing = hit - hit_discriminating
    robustness = {
        name: s for name, s in scenarios.items() if name != "as_published"
    }
    clearing = [name for name, s in robustness.items() if s["clears_threshold"]]
    direction = (
        f"{already_failing} of the {hit} disputed rows already fail to discriminate, so a "
        "wrong axis was costing the gate rather than inflating it."
        if already_failing > hit_discriminating
        else f"{hit_discriminating} of the {hit} disputed rows currently discriminate, so the "
        "disagreement could be holding the rate up rather than down."
    )
    if len(clearing) == len(robustness):
        verdict = (
            f"Every robustness scenario clears {threshold}, the lowest at "
            f"{min(s['rate_lower_bound_95'] for s in robustness.values()):.4f}."
        )
    elif clearing:
        failing = sorted(set(robustness) - set(clearing))
        verdict = (
            f"{', '.join(failing)} does not clear {threshold}, so the published rate is not "
            "robust to the whole of this disagreement and the gate needs re-running with the "
            "axes corrected."
        )
    else:
        verdict = (
            f"No robustness scenario clears {threshold}. The published rate does not survive "
            "this disagreement and gate 3 has to be re-run with the axes corrected."
        )
    return (
        f"{direction} {verdict} Neither scenario is offered as the result: the published rate "
        "is the result, and these bound what the disagreement could do to it."
    )


def rebuild() -> int:
    images = _images_dir()
    if images is None:
        print(
            f"the stage-1 snapshot is not configured, so the axes cannot be re-read. "
            f"Set {ENV_PAGES} to the snapshot's pages directory.",
        )
        return 0

    from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: PLC0415

    pool = json.loads(POOL.read_text(encoding="utf-8"))
    rows = [r for r in pool["observations"] if r.get("hz_per_px")]

    disagreements: list[dict] = []
    agrees = could_not_read = 0
    reasons: dict[str, int] = {}
    fingerprint = hashlib.sha256()

    for row in rows:
        obs_id = row["obs_id"]
        image = images / f"waterfall_{obs_id}.png"
        if not image.is_file():
            could_not_read += 1
            reasons["the image is not in the snapshot"] = (
                reasons.get("the image is not in the snapshot", 0) + 1
            )
            continue
        geom = parse_waterfall(
            image.read_bytes(),
            observation_id=obs_id,
            pass_duration_s=row.get("pass_duration_s"),
            rx_freq_hz=row.get("rx_freq_hz"),
            label_reader="glyph",
        )
        glyph = geom.hz_per_px
        if glyph is None:
            could_not_read += 1
            reason = geom.degraded or "the template matcher read too few labels"
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        fingerprint.update(f"{obs_id}:{glyph!r}\n".encode())
        ratio = glyph / row["hz_per_px"]
        if abs(ratio - 1.0) <= TOLERANCE:
            agrees += 1
            continue
        disagreements.append(
            {
                "obs_id": obs_id,
                "pool_hz_per_px": row["hz_per_px"],
                "glyph_hz_per_px": glyph,
                "ratio": ratio,
                "glyph_confidence": geom.derivation_confidence,
                "pool_verdict": row.get("verdict"),
                "pool_sigma_curved": row.get("sigma_curved"),
                "station_name": row.get("station_name"),
            }
        )

    disagreements.sort(key=lambda d: d["obs_id"])
    disputed = {d["obs_id"] for d in disagreements}
    payload = {
        "schema": "tracetriage/axis-reader-audit",
        "schema_version": 1,
        "generated_by": "scripts/audit_pool_axes.py",
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot": pool.get("snapshot"),
        "question": (
            "The pool's frequency axes were read by easyocr. Read again by the model-free "
            "template matcher, how many differ, and what does that do to gate 3?"
        ),
        "method": (
            "For every pool row that carries an hz_per_px, parse the same image with "
            "label_reader='glyph' and compare. Agreement is a ratio within "
            f"{TOLERANCE:.0%}, because the two readers fit through different tick centres and "
            "a sub-pixel difference is not a disagreement about the image. A row the matcher "
            "cannot read is counted as neither: its documented failure is a missing label, "
            "which is not evidence about the committed value."
        ),
        "tolerance": TOLERANCE,
        "counts": {
            "pool_rows": len(pool["observations"]),
            "rows_with_an_axis": len(rows),
            "agree": agrees,
            "disagree": len(disagreements),
            "could_not_read": could_not_read,
            "could_not_read_by_reason": reasons,
        },
        "readings_fingerprint_sha256": fingerprint.hexdigest(),
        "disagreements": disagreements,
        "gate3_effect": _gate3_effect(disputed),
        "worked_example": {
            "obs_id": 14745990,
            "pool_hz_per_px": 1157.0247933884298,
            "glyph_hz_per_px": 123.76237623762377,
            "image_width_px": 823,
            "tick_labels_khz": [-30, -20, -10, 0, 10, 20, 30],
            "reading": (
                "The labels span 60 kHz. At 123.76 Hz/px that is 485 px of an 823 px image, "
                "which is what the picture shows. At 1,157 Hz/px it would be 52 px. The live "
                "endpoint returns UNCORRECTED at 9.40 sigma on this observation and the "
                "committed pool holds UNRESOLVED at 2.64."
            ),
        },
    }
    OUT.write_text(
        json.dumps(payload, indent=1) + "\n",
        encoding="utf-8",
        # Without this, write_text translates on Windows and the receipt lands as CRLF. Git
        # stores it as LF, so a sha256 taken of the file here is a value no clone reproduces,
        # and the freshness check ends up comparing one against the other.
        newline="\n",
    )
    counts = payload["counts"]
    print(
        f"{OUT.relative_to(REPO)}: {counts['agree']} agree, {counts['disagree']} disagree, "
        f"{counts['could_not_read']} could not be read, of {counts['rows_with_an_axis']} rows"
    )
    return 0


def check() -> int:
    """Recompute the gate arithmetic from the committed artifact. Needs no snapshot."""
    if not OUT.is_file():
        print(f"{OUT.relative_to(REPO)} is missing. Run this script without --check.")
        return 1
    committed = json.loads(OUT.read_text(encoding="utf-8"))
    disputed = {d["obs_id"] for d in committed["disagreements"]}
    if len(disputed) != committed["counts"]["disagree"]:
        print(
            f"the artifact says {committed['counts']['disagree']} disagreements and lists "
            f"{len(disputed)}"
        )
        return 1
    fresh = _gate3_effect(disputed)
    if fresh != committed["gate3_effect"]:
        print("the committed gate3_effect is not what the receipt and this list produce now")
        return 1
    print(
        f"gate3_effect reproduces: {fresh['scored_rows_with_a_disputed_axis']} disputed of the "
        f"scored set, every scenario clears "
        f"{fresh['threshold']}: "
        + ", ".join(
            f"{name} {s['rate_lower_bound_95']:.4f}"
            for name, s in fresh["scenarios"].items()
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="recompute the gate arithmetic from the committed artifact")
    args = parser.parse_args()
    return check() if args.check else rebuild()


if __name__ == "__main__":
    raise SystemExit(main())
