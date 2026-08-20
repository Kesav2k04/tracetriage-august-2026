"""Which of the two shapes does the energy in this waterfall follow?

A SatNOGS capture is either Doppler-corrected at the ground station, in which case a
carrier draws a near-vertical line, or it is not, in which case it draws the pass's
whole Doppler S-curve. Everything downstream depends on which: the corridor a fit
slides is a different curve in the two cases, and `corridor_fit.calibrate_against_nulls`
refuses to build nulls for the corrected one at all, because a flat corridor has no
shape to scramble.

This module holds the measurement that decides it, moved here verbatim from
`scripts/a3_doppler_investigation.py` so that code shipped in the wheel can ask the
question. Gate 3 reads the answer from A3's annotation file, which is fine for a frozen
corpus and useless for an observation recorded an hour ago: nobody annotates those. So
`live.py` measures it, with the same rule and the same thresholds.

**Two deliberate non-unifications.** `normalised_rows` is NOT imported here and this
module does not compute `zs`. A3 divides by `max(mad, 1e-6)`, which
`corridor_fit.normalised_rows` records as a defect: a flat row has MAD exactly 0, so
that floor multiplied its deviations by a million and the filter reported sigmas up to
8.6e6 on 14 of 716 decisive observations. corridor_fit floors at one grey level instead.
A3's receipt was measured with the old floor and replaying it must reproduce it, so the
caller passes `zs` in and owns which normalisation produced it. A3 keeps its own; the
live path uses corridor_fit's.

`smooth_columns` and `path_score` ARE imported, because they were checked line by line
against A3's copies first: `smooth_columns` is identical apart from the leading
underscore, and `path_score` at `row_mask=None` computes the same mean over the same
indices with the same NaN rule. Nothing here passes a row mask, so the horizon masking
corridor_fit added does not reach this scan.
"""

from __future__ import annotations

import math

import numpy as np

from .corridor_fit import EDGE_MARGIN_PX, path_score, smooth_columns

# Both hypotheses are scored as whole paths through the image and compared on a
# null measured from the image itself. The scan is repeated at three matched
# filter widths and a verdict is only accepted when all three agree.
FILTER_WIDTHS = [1, 3, 5]
PRIMARY_WIDTH = 3

# A path has to stand this far above the spread of all vertical paths before it
# counts as a signal at all, and one hypothesis has to lead the other by this
# margin before either is called.
SIGMA_MIN = 8.0
SIGMA_MARGIN = 3.0

# Below this the two shapes are not distinguishable: a corrected capture and an
# uncorrected one would draw nearly the same line.
MIN_PREDICTED_SWING_HZ = 3000.0

__all__ = [
    "EDGE_MARGIN_PX",
    "FILTER_WIDTHS",
    "MIN_PREDICTED_SWING_HZ",
    "PRIMARY_WIDTH",
    "SIGMA_MARGIN",
    "SIGMA_MIN",
    "matched_filter",
    "predicted_swing_hz",
    "verdict_from_scores",
]


def matched_filter(
    zs: np.ndarray,
    centre_px: float,
    hz_per_px: float,
    curve_fracs: list[float],
    curve_hz: list[float],
) -> dict:
    """Ask which shape the energy in this image actually follows.

    Two families of paths are scanned over the same set of horizontal offsets:
    a vertical line, which is what a Doppler-corrected capture leaves, and the
    predicted Doppler curve, which is what an uncorrected one leaves. Each is
    scored as mean normalised intensity along the path.

    Scoring whole paths rather than detecting a peak per row matters here. An
    earlier version averaged blocks of rows before taking the brightest column,
    which quietly favoured one answer: near closest approach a real Doppler
    trace crosses roughly a dozen columns within one block, so averaging smears
    it away, while a stationary carrier survives untouched. A method that can
    only see one of the two hypotheses cannot be used to choose between them.

    The null is measured, not assumed: the spread of the vertical scores across
    every column gives the scale that both families are reported in.
    """
    n_rows, n_cols = zs.shape

    # Row 0 is the top of the image, and the top of a SatNOGS waterfall is the
    # END of the pass. Read off the axis of observation 14740031: the tick
    # labelled 200 s sits at y=258 and the one labelled 50 s at y=1228, evenly
    # spaced, so elapsed time runs bottom to top.
    row_fracs = 1.0 - (np.arange(n_rows) + 0.5) / n_rows
    predicted_hz = np.interp(row_fracs, np.asarray(curve_fracs), np.asarray(curve_hz))
    predicted_px = predicted_hz / hz_per_px

    # The sign relating a Doppler shift to a direction on the frequency axis is
    # scanned rather than assumed. Assuming it once already hid a defect: the
    # time axis was inverted too, and for a curve that is near odd-symmetric
    # about closest approach the two errors cancel exactly, so the fit looked
    # excellent while both halves were wrong.
    out: dict = {}
    for width in FILTER_WIDTHS:
        smoothed = smooth_columns(zs, width)

        vertical = np.array([
            path_score(smoothed, np.full(n_rows, c, dtype=int)) for c in range(n_cols)
        ])
        finite = vertical[np.isfinite(vertical)]
        baseline = float(np.median(finite))
        spread = float(np.median(np.abs(finite - baseline)) * 1.4826) or 1e-9

        best_v = int(np.nanargmax(vertical))
        sigma_v = (vertical[best_v] - baseline) / spread

        offsets = np.arange(-n_cols, n_cols, 1)
        origin = centre_px - EDGE_MARGIN_PX
        by_sign: dict[int, tuple[float, int | None]] = {}
        for sign in (1, -1):
            curved = np.array([
                path_score(smoothed, np.rint(origin + sign * predicted_px + o).astype(int))
                for o in offsets
            ])
            if np.all(np.isnan(curved)):
                by_sign[sign] = (float("nan"), None)
            else:
                best_c = int(np.nanargmax(curved))
                by_sign[sign] = (
                    float((curved[best_c] - baseline) / spread),
                    int(offsets[best_c]),
                )

        def rank(s: int, table: dict = by_sign) -> float:
            v = table[s][0]
            return -1e9 if math.isnan(v) else v

        best_sign = max(by_sign, key=rank)
        sigma_c, best_offset = by_sign[best_sign]

        out[width] = {
            "sigma_vertical": float(sigma_v),
            "sigma_curved": float(sigma_c),
            "frequency_axis_sign": int(best_sign),
            "sigma_curved_by_sign": {str(s): by_sign[s][0] for s in (1, -1)},
            "vertical_column_offset_hz": float((best_v - origin) * hz_per_px),
            "curved_offset_hz": (
                float(best_offset * hz_per_px) if best_offset is not None else None
            ),
        }
    return out


def verdict_from_scores(scores: dict, predicted_swing_hz: float) -> tuple[str, str, dict]:
    """Decide, or refuse to. UNRESOLVED is a real outcome here, not a failure.

    A verdict needs three things: a signal at all, one hypothesis clearly ahead
    of the other, and the same call at every filter width. Any of those missing
    and the image does not settle the question.
    """
    primary = scores[PRIMARY_WIDTH]
    sv, sc = primary["sigma_vertical"], primary["sigma_curved"]

    summary = {
        "sigma_vertical": sv,
        "sigma_curved": sc,
        "frequency_axis_sign": primary["frequency_axis_sign"],
        "sigma_curved_by_sign": primary["sigma_curved_by_sign"],
        "vertical_column_offset_hz": primary["vertical_column_offset_hz"],
        "curved_offset_hz": primary["curved_offset_hz"],
        "predicted_swing_hz": predicted_swing_hz,
        "per_width": scores,
    }

    if predicted_swing_hz < MIN_PREDICTED_SWING_HZ:
        return (
            "UNRESOLVED",
            f"predicted swing is only {predicted_swing_hz:,.0f} Hz, too small to "
            f"tell the two shapes apart",
            summary,
        )

    best = max([s for s in (sv, sc) if not math.isnan(s)], default=float("nan"))
    if math.isnan(best) or best < SIGMA_MIN:
        return (
            "UNRESOLVED",
            f"no signal stands out: best path is {best:.1f} sigma against a "
            f"{SIGMA_MIN:.0f} sigma floor",
            summary,
        )

    def call(entry: dict) -> str:
        a, b = entry["sigma_vertical"], entry["sigma_curved"]
        if math.isnan(a) or math.isnan(b):
            return "UNRESOLVED"
        if b - a >= SIGMA_MARGIN:
            return "UNCORRECTED"
        if a - b >= SIGMA_MARGIN:
            return "CORRECTED"
        return "UNRESOLVED"

    calls = {w: call(scores[w]) for w in FILTER_WIDTHS}
    if len(set(calls.values())) > 1:
        detail = ", ".join(f"width {w} -> {v}" for w, v in calls.items())
        return "UNRESOLVED", f"filter widths disagree ({detail})", summary

    verdict = calls[PRIMARY_WIDTH]
    if verdict == "UNCORRECTED":
        reason = (
            f"energy follows the predicted Doppler curve: {sc:.1f} sigma against "
            f"{sv:.1f} for the best vertical line"
        )
    elif verdict == "CORRECTED":
        reason = (
            f"energy follows a vertical line {primary['vertical_column_offset_hz']:+,.0f} Hz "
            f"off axis zero: {sv:.1f} sigma against {sc:.1f} for the predicted curve"
        )
    else:
        reason = (
            f"neither shape leads: vertical {sv:.1f} sigma, curved {sc:.1f} sigma, "
            f"inside the {SIGMA_MARGIN:.0f} sigma margin"
        )
    return verdict, reason, summary


def predicted_swing_hz(curve_hz: list[float]) -> float:
    """The swing `verdict_from_scores` compares against its floor.

    The 5th to 95th percentile rather than the full range, so one propagation outlier
    at the horizon cannot make a grazing pass look testable. Lifted out of A3's
    `analyse` because the live path needs the same number and computing it a second way
    is how two thresholds that read the same start disagreeing.
    """
    if not curve_hz:
        return 0.0
    arr = np.asarray(curve_hz, dtype=float)
    return float(np.percentile(arr, 95) - np.percentile(arr, 5))
