"""Export the null corridors gate 3 actually scored, as drawable pixel paths.

The console's opening frame draws the predicted Doppler corridor over a real
waterfall, then draws the null corridors it was measured against. That second half
is the part that carries the argument: a curve drawn on an image is a picture, and a
curve drawn next to two hundred curves that were built from the same frequency values
and could not fit is a measurement.

So the nulls on screen must be the nulls that were scored, not a decorative
approximation of them. This script re-runs the identical fit outside the scoring path
and refuses to write anything unless the distribution it reproduces matches
``artifacts/GATE3_RECEIPT.json`` exactly:

* ``n_nulls``, ``true_sigma``, ``null_median``, ``null_p95``, ``null_max``,
  ``n_at_least`` and ``p_value`` are each compared against the receipt.
* Any mismatch beyond 1e-9 raises. A drawing that cannot prove it is the measurement
  is worth less than no drawing.

Nothing here touches ``pipeline/tracetriage/corridor_fit.py``. It imports the same
functions the gate calls, in the same order, with the same thresholds and the same
seed sequence, which is why reproducing seven statistics is evidence rather than a
coincidence.

Which nulls get drawn: all 200 paths would be 200 polylines of 240 points, and it is
also more ink than a reader can see through. The written set is an even spread across
the sigma-sorted nulls plus the single best null, which is the one an honest drawing
cannot omit: it is the hardest case, and hiding it would make the frame a picture
again. Both facts are recorded in the artifact.

    .venv/Scripts/python.exe scripts/export_hero_nulls.py

Writes ``artifacts/HERO_NULLS.json``. ``scripts/build_console_data.py`` copies it into
the console export. ``tests/test_hero_nulls.py`` checks it against the receipt.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.tracetriage.corridor_fit import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    EDGE_MARGIN_PX,
    _base_columns,
    _best_over_offsets,
    normalised_rows,
    scramble_corridor,
    smooth_columns,
)
from pipeline.tracetriage.physics import (  # noqa: E402
    corridor_columns,
    corridor_for_obs,
    rx_freq_of,
    visible_rows,
)
from scripts.run_gate3 import _geometry_of, _load_raw_obs  # noqa: E402

logger = logging.getLogger("hero-nulls")

# Observation 14740031 is the subject. It is in gate 3's pool, it is one of the two
# named cards the console already ships, and its
# fitted offset is 13,985 Hz, which is 32 ppm and 113 pixels: large enough to see and
# invisible in the metadata, because the commanded receive frequency matches the
# catalogue exactly. Choosing it is a presentation decision and it is recorded here
# rather than left implicit.
DEFAULT_OBS = 14740031

TOLERANCE = 1e-9


def _row_subsample_scorer(n_rows: int) -> list[int]:
    """Rows of the scorer's array to draw, at roughly the card's density."""
    step = max(1, n_rows // 240)
    rows = list(range(0, n_rows, step))
    if rows[-1] != n_rows - 1:
        rows.append(n_rows - 1)
    return rows


def _scorer_columns(
    corridor: Any, hz_per_px: float, origin: float, n_rows: int, off_px: int
) -> np.ndarray:
    """The exact path `_best_over_offsets` walked, before pixel-centre rounding.

    The scorer scores `rint(base + off_px)`. The rounding is a property of reading
    an integer column out of an image, not of the corridor, so the polyline drawn
    is the unrounded series.
    """
    return _base_columns(corridor, hz_per_px, origin, n_rows) + off_px


def _to_card_space(cols: np.ndarray) -> np.ndarray:
    """Scorer columns into the coordinate space the shipped card already uses.

    Three spaces exist on one image and picking the wrong pair is silent. The
    source PNG is 836 x 1603. `parse_waterfall` crops the plot region to
    620 x 1540, which is the shipped webp and the viewBox every existing overlay
    shares. `normalised_rows` then trims `EDGE_MARGIN_PX` from each side of that
    crop, leaving the 1532 x 612 array the matched filter actually walked, and
    `_best_over_offsets` places its columns against `centre_px - EDGE_MARGIN_PX`.

    So the map from scorer space to card space is a translation by
    `EDGE_MARGIN_PX` on both axes, and nothing else. Measured on this observation,
    the two constructions agree to 0.176 px worst case and 0.152 px median, the
    residual being the half-row centring term `(row + 0.5) / height` evaluated over
    1532 rows against 1540. `_transform_residual` re-measures it every run and
    refuses to write above half a pixel.

    A first attempt at this passed the source PNG height, 1603, where the card uses
    the cropped 1540. The curves disagreed by 235.7 px, which is 29 kHz, larger than
    the entire 17.3 kHz Doppler swing being drawn. It was caught by checking rather
    than by looking, and it would not have looked obviously wrong on screen.
    """
    return cols + EDGE_MARGIN_PX


def _transform_residual(
    corridor: Any,
    hz_per_px: float,
    centre_px: float,
    crop_height: int,
    n_rows: int,
) -> float:
    """Largest disagreement, in pixels, between the scorer's path and the card's."""
    scorer = _to_card_space(
        _scorer_columns(corridor, hz_per_px, centre_px - EDGE_MARGIN_PX, n_rows, 0)
    )
    card = corridor_columns(
        corridor,
        hz_per_px=hz_per_px,
        centre_px=centre_px,
        image_height=crop_height,
        freq_offset_hz=0.0,
    )
    aligned = card[EDGE_MARGIN_PX : EDGE_MARGIN_PX + n_rows]
    n = min(len(scorer), len(aligned))
    return float(np.max(np.abs(scorer[:n] - aligned[:n])))


def _check(name: str, got: float | int | None, want: float | int | None) -> None:
    if got is None or want is None:
        if got is not want:
            raise ValueError(f"{name}: reproduced {got!r}, receipt has {want!r}")
        return
    if not math.isclose(float(got), float(want), rel_tol=TOLERANCE, abs_tol=TOLERANCE):
        raise ValueError(
            f"{name}: reproduced {got!r}, receipt has {want!r}. The export is not "
            f"drawing the nulls that were scored, so nothing was written."
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--obs", type=int, default=DEFAULT_OBS)
    ap.add_argument(
        "--snapshot", type=Path, default=Path("D:/tracetriage_data/snap-stage1")
    )
    ap.add_argument(
        "--receipt", type=Path, default=REPO_ROOT / "artifacts/GATE3_RECEIPT.json"
    )
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts/HERO_NULLS.json")
    ap.add_argument(
        "--draw",
        type=int,
        # Six, not thirty-two. This is a measured page-weight decision, not a taste
        # one: seven polylines of 257 points took the home document from 20.1 kB to
        # 40.2 kB gzipped, and sixteen nulls cost 63.3 kB. The default used to be 32
        # while the shipped artifact carried 6, so a bare rebuild silently tripled the
        # ink and the document weight, and nothing recorded which command had produced
        # the file on disk. The default is now the shipped decision.
        default=6,
        help="how many null paths to write; all 200 are scored either way",
    )
    ap.add_argument(
        "--decimals",
        type=int,
        # Zero, which is what the shipped artifact carries. The frame is 620 units
        # wide and renders near 700 CSS pixels, so one unit is 1.13 px and rounding
        # to whole units moves a point by at most 0.56 px, below anything a reader
        # can see. Integers also compress better, which is the whole reason the
        # precision is a parameter. The default was 1 while the artifact on disk was
        # written with 0, so a bare rebuild rewrote every coordinate in the file.
        default=0,
        help=(
            "column precision. The frame is 620 units wide and renders near 700 CSS "
            "pixels, so one whole unit is already below anything a reader can see, "
            "and the paths compress better for it."
        ),
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    row = next(
        (o for o in receipt["observations"] if o["obs_id"] == args.obs), None
    )
    if row is None:
        raise SystemExit(f"obs {args.obs} is not in {args.receipt}")
    if not row["testable"]:
        raise SystemExit(
            f"obs {args.obs} is not testable ({row['not_testable_reason']}), so it "
            f"has no null distribution to draw."
        )
    want = row["null_calibration"]

    raw = _load_raw_obs(args.snapshot, args.obs)
    if raw is None:
        raise SystemExit(f"obs {args.obs} is not in the snapshot at {args.snapshot}")

    img = args.snapshot / "waterfalls" / f"waterfall_{args.obs}.png"
    if not img.exists():
        raise SystemExit(f"waterfall missing: {img}")

    phys = corridor_for_obs(raw)
    if phys.degraded or phys.uncorrected is None:
        raise SystemExit(f"physics degraded: {phys.degraded}")
    rx_hz = rx_freq_of(raw)
    geom = _geometry_of(img, args.obs, rx_hz, phys.pass_duration_s or 200.0)
    if geom is None or geom.degraded is not None:
        raise SystemExit(f"geometry degraded: {getattr(geom, 'degraded', '?')}")

    from PIL import Image

    with Image.open(img) as im:
        rgb = np.asarray(im.convert("RGB"))
        source_size = (im.width, im.height)
    zs = normalised_rows(rgb, geom.crop_box)
    # The card ships the cropped plot region, not the source PNG, and its viewBox is
    # that crop. Everything drawn here is placed in that space.
    crop_w = geom.crop_box.x1 - geom.crop_box.x0
    crop_h = geom.crop_box.y1 - geom.crop_box.y0

    corridor = phys.uncorrected
    thresholds = DEFAULT_THRESHOLDS
    hz_per_px = geom.hz_per_px
    centre_px = geom.centre_px
    origin = centre_px - EDGE_MARGIN_PX
    bound_hz = thresholds.offset_ppm_limit * rx_hz / 1e6
    bound_px = int(math.floor(bound_hz / hz_per_px))
    smoothed = smooth_columns(zs, thresholds.filter_width)
    n_rows = zs.shape[0]
    # SPACE-S4: the same horizon mask the gate uses, built once from the true
    # corridor and applied to every curve. The panel has to be scored by the rules
    # the receipt was scored by, or the drawn nulls are not the measured ones. This
    # observation has no below-horizon rows, so the mask is all-True here and every
    # published sigma is unchanged; the agreement checks below prove it.
    row_mask = visible_rows(corridor, int(n_rows))

    true_sigma, true_off = _best_over_offsets(
        smoothed, zs, corridor, hz_per_px, origin, bound_px, row_mask=row_mask
    )
    if true_off is None:
        raise SystemExit("the true corridor has no admissible offset")

    nulls: list[dict[str, Any]] = []
    for i in range(thresholds.n_nulls):
        null_c = scramble_corridor(corridor, thresholds.seed + i)
        sigma, off = _best_over_offsets(
            smoothed, zs, null_c, hz_per_px, origin, bound_px, row_mask=row_mask
        )
        if off is not None and math.isfinite(sigma):
            nulls.append({"i": i, "sigma": float(sigma), "off_px": int(off),
                          "corridor": null_c})

    sigmas = np.asarray([n["sigma"] for n in nulls], dtype=float)
    n_at_least = int(np.sum(sigmas >= true_sigma))
    p_value = (n_at_least + 1) / (len(sigmas) + 1)

    # Seven independent statistics, each against the receipt. This is the whole
    # licence to call the drawn curves the measured ones.
    _check("n_nulls", len(sigmas), want["n_nulls"])
    _check("true_sigma", float(true_sigma), want["true_sigma"])
    _check("null_median", float(np.median(sigmas)), want["null_median"])
    _check("null_p95", float(np.percentile(sigmas, 95)), want["null_p95"])
    _check("null_max", float(np.max(sigmas)), want["null_max"])
    _check("n_at_least", n_at_least, want["n_at_least"])
    _check("p_value", p_value, want["p_value"])
    logger.info(
        "reproduced the receipt: sigma=%.6f median=%.6f p95=%.6f max=%.6f "
        "n_at_least=%d p=%.9f over %d nulls",
        true_sigma, float(np.median(sigmas)), float(np.percentile(sigmas, 95)),
        float(np.max(sigmas)), n_at_least, p_value, len(sigmas),
    )

    residual = _transform_residual(corridor, hz_per_px, centre_px, crop_h, n_rows)
    if residual > 0.5:
        raise ValueError(
            f"the scorer's path and the card's projection disagree by "
            f"{residual:.3f} px, so the drawn curve is not the scored one"
        )
    logger.info("scorer-to-card transform residual: %.4f px", residual)

    scorer_rows = _row_subsample_scorer(n_rows)
    # Card-space row for each drawn point: the same translation applied to x.
    rows = [r + EDGE_MARGIN_PX for r in scorer_rows]

    def _path(corr: Any, off_px: int) -> list[float]:
        cols = _to_card_space(
            _scorer_columns(corr, hz_per_px, origin, n_rows, off_px)
        )
        return [round(float(cols[r]), args.decimals) for r in scorer_rows]

    # An even spread across the sigma-sorted nulls, plus the best one. The spread is
    # what a reader should see; the best null is what an honest drawing cannot leave
    # out, because it is the closest any scrambled corridor came.
    order = sorted(range(len(nulls)), key=lambda k: nulls[k]["sigma"])
    n_draw = max(2, min(args.draw, len(order)))
    picks = {order[round(t * (len(order) - 1) / (n_draw - 1))] for t in range(n_draw)}
    best = max(range(len(nulls)), key=lambda k: nulls[k]["sigma"])
    picks.add(best)

    drawn = []
    for k in sorted(picks, key=lambda k: nulls[k]["sigma"]):
        n = nulls[k]
        drawn.append({
            "seed": thresholds.seed + n["i"],
            "sigma": round(n["sigma"], 6),
            "offset_px": n["off_px"],
            "is_best_null": k == best,
            "px": _path(n["corridor"], n["off_px"]),
        })

    out = {
        "obs_id": args.obs,
        "generated_by": "scripts/export_hero_nulls.py",
        "receipt": "artifacts/GATE3_RECEIPT.json",
        "verified_against_receipt": [
            "n_nulls", "true_sigma", "null_median", "null_p95", "null_max",
            "n_at_least", "p_value",
        ],
        "image": {
            "width": crop_w,
            "height": crop_h,
            "source_png": {"width": source_size[0], "height": source_size[1]},
            "crop_box": [
                geom.crop_box.x0, geom.crop_box.y0,
                geom.crop_box.x1, geom.crop_box.y1,
            ],
            "note": (
                "width and height are the cropped plot region, which is the image "
                "the console ships and the viewBox every overlay shares. The source "
                "PNG is larger and is not what these coordinates refer to."
            ),
        },
        "rows": rows,
        "true": {
            "sigma": round(float(true_sigma), 6),
            "offset_px": int(true_off),
            "px": _path(corridor, int(true_off)),
        },
        # The gate's own verdict fields, so the caption under the plate is generated
        # rather than typed. It said "all three testable observations discriminate"
        # and "the lower bound on three of three is 0.368" as literal prose, which
        # is the defect this project audits other people's documents for: a number
        # in a document that is not read from a receipt. SPACE-B4 proposes adding
        # margin_over_best_null to the `discriminates` criterion, which can drop an
        # observation, and that sentence would have quietly become false.
        "gate": {
            "verdict": receipt["verdict"],
            "threshold": receipt["threshold"],
            "observations_decisive": receipt["observations_decisive"],
            "observations_testable": receipt["observations_testable"],
            "observations_scored": receipt["observations_scored"],
            "observations_discriminating": sum(
                1
                for o in receipt["observations"]
                if o["null_calibration"]["discriminates"]
            ),
            "discriminating_rate": receipt["discriminating_rate"],
            "rate_lower_bound_95": receipt["rate_lower_bound_95"],
        },
        "transform_residual_px": round(residual, 6),
        "transform_note": (
            "Paths are the scorer's own columns translated by EDGE_MARGIN_PX on both "
            "axes into the card's coordinate space. The residual is the largest "
            "disagreement between that construction and the card's projection of the "
            "same corridor, and it comes from the half-row centring term evaluated "
            "over 1532 scorer rows against 1540 card rows. Above 0.5 px nothing is "
            "written."
        ),
        "distribution": {
            "n_nulls": len(sigmas),
            "median": round(float(np.median(sigmas)), 6),
            "p95": round(float(np.percentile(sigmas, 95)), 6),
            "max": round(float(np.max(sigmas)), 6),
            "n_at_least": n_at_least,
            "p_value": p_value,
            "margin_over_best_null": round(float(true_sigma - np.max(sigmas)), 6),
        },
        "drawn": drawn,
        "decimals": args.decimals,
        "selection_note": (
            f"All {len(sigmas)} nulls were scored. {len(drawn)} paths are written: an "
            f"even spread across the sigma-sorted distribution plus the single best "
            f"null, which is marked is_best_null and is included so the closest "
            f"scrambled corridor is on screen rather than filtered out."
        ),
        "method_note": (
            "Each null permutes the observation's own Doppler samples in time, which "
            "keeps every frequency value and the whole swing and destroys the "
            "monotone shape. Each null then gets the same bounded offset search the "
            "true corridor gets, so the free parameter advantages neither. The path "
            "written here is the base column series at the offset that search chose, "
            "before the rounding to integer pixel centres that reading the image "
            "requires."
        ),
        "axis_note": (
            "Columns are image pixels. Time runs bottom to top: row 0 is the end of "
            "the pass. The frequency axis runs against the Doppler sign."
        ),
    }

    args.out.write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    size_kb = args.out.stat().st_size / 1024
    logger.info("wrote %s (%d paths, %.1f kB)", args.out, len(drawn), size_kb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
