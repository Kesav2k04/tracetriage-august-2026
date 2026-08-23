"""Per-row corridor residuals, a bounded frequency-offset fit, and null controls.

This module answers kill gate 3 as the plan states it: does the expected
corridor intersect a visible target-like trace? Unit A7 answered a different
question, comparing the width of a matched-filter kernel against the width of
the corridor, which is a comparison of two constants and cannot fail. What the
gate needs is a position measurement, and no artifact in the repository stored
one. A3's ``summary.json`` records matched-filter sigma scores and a single
frequency offset per observation, both of which describe the trace's shape and
its best-fit location, not its deviation from the prediction row by row.

Three facts drive the design.

**The absolute downlink frequency is not known.** A3 measured its three
uncorrected traces sitting 14.0, 7.1 and 7.1 kHz off the predicted curve
(``curved_offset_hz``: -13,985.1 Hz, +7,148.9 Hz, +7,148.9 Hz). On the 436.400 MHz
downlink all three carry, that is 32.0, 16.4 and 16.4 parts per million, which is
an ordinary figure for a cubesat oscillator, and the SatNOGS transmitter frequency
a station tunes to is community-maintained and can be stale. The smaller two read
2.4 and 1.8 kHz here until 2026-08-23, which is ``vertical_column_offset_hz``, the
offset of the hypothesis those three observations reject. So a constant frequency offset has to be
fitted per observation rather than assumed to be zero. Unit A7 left
``freq_offset_hz`` at its ``0.0`` default, which is why the corridor it checked
sat 3.7 kHz away from the trace it was supposed to contain.

**A freely fitted offset destroys the measurement.** A3 searched the offset over
the whole plot width, ``np.arange(-n_cols, n_cols)``, which for observation
14740031 is plus or minus 76.9 kHz against a Doppler swing of 16.6 kHz. An
offset range 9.3 times the signal lets the curve land almost anywhere, so the
resulting sigma establishes that the energy follows the curve's shape and says
nothing about where the curve belongs. Here the offset is bounded in parts per
million of the actual downlink frequency, so the bound scales with band instead
of being a single Hz constant that is reasonable at 400 MHz and far too loose at
137 MHz.

**A threshold with no control is not evidence.** Even bounded, the offset is a
free parameter, so the honest question is not "does the corridor hit the trace"
but "does it hit more often than a corridor that should not fit at all". Every
fit is therefore repeated against null controls, and the gate reports the true
corridor's hit rate beside theirs. If the controls hit as often, the physics has
no discriminating power on this data and the gate has failed regardless of the
absolute number.

Time reversal **is** used as a control, and an earlier version of this module
dropped it on an argument that inverted its own premise. The premise is right:
A3 established that a Doppler curve is near odd-symmetric about closest
approach. If D is odd about closest approach then D(1-f) = -D(f), so time
reversal is the sign flip. That is why the two errors cancel when applied
together and why no visual check can find them, and it is exactly why each one
applied alone produces a maximally wrong curve. The old paragraph read "the
pair cancels" as "each one alone still fits", which is the opposite conclusion.
Measured on the three shipped observations, the reversal lands at or below the
maximum of 200 scrambled corridors, so it is the strongest null available and
the one that most directly tests AXIS_SIGN_CONVENTION. The scrambled controls
break the monotone S shape while preserving the value distribution, the scaled
controls hold the shape and vary only magnitude, and the reversal holds both
and flips only the sign.

All thresholds are module constants, fixed before any observation was scored,
and stated in ``THRESHOLD_RATIONALE`` so a reader can see they were not tuned to
produce a pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .physics import (
    AXIS_SIGN_CONVENTION,
    AXIS_SIGN_MEASURABLE_RATIO,
    PEAK_DOPPLER_SLOPE_HZ_PER_S,
    Corridor,
    corridor_columns,
    visible_rows,
)

__all__ = [
    "CorridorFit",
    "max_coherent_jump_px",
    "second_trace_evidence",
    "NullCalibration",
    "NullControlResult",
    "GateThresholds",
    "THRESHOLD_RATIONALE",
    "DEFAULT_THRESHOLDS",
    "EDGE_MARGIN_PX",
    "normalised_rows",
    "smooth_columns",
    "path_score",
    "px_to_offset_hz",
    "fit_offset",
    "measure_residuals",
    "fit_corridor",
    "calibrate_against_nulls",
    "run_null_controls",
    "scramble_corridor",
    "scale_corridor",
    "flatten_corridor",
    "invert_corridor",
    "measure_axis_sign",
]


# ---------------------------------------------------------------------------
# Constants shared with the A3 investigation
# ---------------------------------------------------------------------------

# Pixels trimmed from each side of the crop before scoring. Matches
# scripts/a3_doppler_investigation.py so residuals here are comparable to the
# sigma scores there. The plot border itself is bright and would win any scan.
EDGE_MARGIN_PX: int = 4

#: Smallest per-row spread the normalisation will divide by, in grey levels.
#:
#: One grey level. Measured on the stage-1 snapshot, a row's MAD is either exactly 0
#: or at least 2.471, so any floor inside that gap leaves every row with variation
#: untouched while stopping a flat row from being amplified. The previous value, 1e-6,
#: turned flat rows into matched-filter responses of up to 8.6e6. See
#: :func:`normalised_rows`.
MAD_FLOOR: float = 1.0


@dataclass(frozen=True)
class GateThresholds:
    """Every threshold gate 3 depends on, in one inspectable object.

    Fixed before scoring. Changing one of these changes a published number, so
    a caller that overrides a value has to say so in its receipt.
    """

    # Robust z above the per-row background for a pixel to count as a detection.
    z_min: float = 4.0

    # Minimum fraction of image rows carrying a detection before an observation
    # is considered measurable at all. Below this the result is a named
    # degraded state, not a failure.
    min_detect_frac: float = 0.30

    # Fraction of detected rows that must fall inside the corridor for the
    # observation to count as a corridor hit.
    coverage_threshold: float = 0.70

    # Bound on the fitted constant frequency offset, in parts per million of the
    # downlink frequency.
    offset_ppm_limit: float = 50.0

    # Matched-filter kernel width in pixels, for the offset fit.
    filter_width: int = 3

    # Half-width in pixels of the per-row search window around the fitted curve,
    # expressed as a multiple of the corridor half-width.
    search_window_factor: float = 2.0

    # Scrambled corridors drawn per observation to build the null distribution.
    n_nulls: int = 200

    # One-sided empirical p-value at or below which the true corridor is called
    # discriminating against its nulls. Necessary and very weak: a physically
    # inverted corridor reaches the same 0 of 200 on two of the three shipped
    # observations, because scrambled paths collapse into noise and anything
    # smooth beats them. It is retained as a floor, not as the evidence.
    p_value_max: float = 0.05

    # Minimum separation between the true sigma and the best null, expressed in
    # standard deviations of that observation's own null sigma distribution.
    # Scale-free by construction, so it cannot be tuned by rescaling sigma, and
    # it is calibrated on the nulls rather than on the true values.
    margin_null_sd_min: float = 5.0

    # Swing multipliers for the scaled-swing controls. 1.0 is excluded because
    # that is the truth. These hold smoothness fixed and vary only magnitude.
    swing_scale_factors: tuple[float, ...] = (0.25, 0.5, 2.0, 4.0)

    # Minimum predicted Doppler swing before a corridor counts as having a shape
    # worth testing. Matches MIN_PREDICTED_SWING_HZ in
    # scripts/a3_doppler_investigation.py, which refuses a verdict below it.
    min_swing_hz: float = 3_000.0

    # When the fitted offset saturates its own bound, the search may not have
    # found the true optimum. True excludes the observation from the gate rather
    # than only flagging it.
    exclude_at_bound: bool = True

    # Seed for the scrambled null control.
    seed: int = 42


DEFAULT_THRESHOLDS = GateThresholds()

THRESHOLD_RATIONALE: dict[str, str] = {
    "margin_null_sd_min": (
        "5.0 standard deviations of the observation's own null sigma distribution, "
        "above the best of those nulls. Five sigma is the conventional discovery "
        "floor in physics and is fixed here before rescoring. It is stated in null "
        "standard deviations rather than in raw sigma so the bar cannot be cleared "
        "by rescaling, and so it is calibrated on the wrong corridors rather than "
        "on the right ones. Why it was added: p_value_max alone is cleared by a "
        "corridor with the frequency axis inverted, which reaches 0 of 200 and "
        "p = 0.005 while beating its best null by about 3 null standard deviations. "
        "The three shipped observations clear the same bar by 120 to 200."
    ),
    "z_min": (
        "4.0 robust z, the same detection floor scripts/a3_doppler_investigation.py "
        "uses in visible_track, so a pixel called a detection here would have been "
        "called one there."
    ),
    "min_detect_frac": (
        "0.30 of rows. A trace is not visible for a whole pass; it fades at low "
        "elevation at both ends. A3 scored 39 rows on observation 14740031. Below "
        "this fraction the observation is reported as not measurable rather than as "
        "a corridor miss, because those are different findings."
    ),
    "coverage_threshold": (
        "0.70 of detected rows inside the corridor. Mirrors the plan's own gate-3 "
        "figure, applied per observation to rows so that the gate across "
        "observations and the gate within one observation use the same bar."
    ),
    "offset_ppm_limit": (
        "50 ppm of the downlink frequency. Covers an ordinary cubesat oscillator "
        "error plus a stale SatNOGS transmitter frequency, and it is stated in ppm "
        "so the bound scales with band. At 400 MHz this is about 20 kHz, close to "
        "the existing FREQ_OFFSET_SEARCH_HZ constant; at 137 MHz it is 6.9 kHz, "
        "where that constant would have been 146 ppm and would have let the curve "
        "land anywhere."
    ),
    "search_window_factor": (
        "2.0 times the corridor half-width. The per-row search has to be wider "
        "than the corridor or a row outside the corridor could never be detected "
        "and the coverage figure would be one by construction, which is the exact "
        "defect this module exists to remove."
    ),
    "n_nulls": (
        "200 scrambled corridors per observation. Enough for an empirical p-value "
        "to resolve 0.005, which is finer than the 0.05 the gate reads, and cheap "
        "because the offset search shifts precomputed columns rather than "
        "recomputing the curve."
    ),
    "swing_scale_factors": (
        "0.25, 0.5, 2 and 4 times the predicted swing. Each is as smooth and as "
        "monotone as the prediction, so together they separate 'the physics "
        "predicted the right swing' from 'a bright smooth path exists somewhere'."
    ),
    "min_swing_hz": (
        "3,000 Hz of predicted swing before a corridor counts as having a testable "
        "shape. The same figure A3 uses in MIN_PREDICTED_SWING_HZ, and for the same "
        "reason: permuting nearly-equal values gives nearly the same path, so truth "
        "and null both collapse toward noise and a p-value can turn significant on "
        "pixel quantisation. Only span > 0 was checked before, which would have let "
        "a grazing low-elevation pass through as testable."
    ),
    "exclude_at_bound": (
        "True. A fit that saturates its own ppm bound may not have found the true "
        "optimum, so its sigma is a lower bound and the observation is excluded "
        "rather than merely flagged. None of the three scored observations saturates "
        "(+32.0, -16.4, -16.4 ppm against 50), so this changes nothing today and "
        "closes a silent path at snapshot scale."
    ),
    "p_value_max": (
        "0.05 one-sided. The true corridor must beat at least 95 percent of "
        "corridors built by permuting its own Doppler samples in time. Both get "
        "the same bounded offset search, so neither is advantaged by the free "
        "parameter."
    ),
}


# ---------------------------------------------------------------------------
# Image preparation, matching A3
# ---------------------------------------------------------------------------


def normalised_rows(rgb: np.ndarray, crop_box: Any) -> np.ndarray:
    """Per-row robust z-scores over the spectrogram interior.

    Each row is normalised on its own, which removes the vertical brightness
    gradient that changing slant range puts into every pass. Nothing is
    normalised along time, because that would erase a stationary carrier, and a
    stationary carrier is what the corrected hypothesis predicts.

    **On the divisor floor.** This used to be ``np.maximum(mad, 1e-6)``, which reads
    like a guard against division by zero and is not one. A perfectly flat row has
    MAD exactly 0, so that floor multiplied its deviations by a million, and the
    matched filter then reported sigma values up to 8.6e6 on 14 of 716 decisive
    observations. A sigma of eight million in units of the null spread does not mean
    an overwhelming detection; it means the row had no spread to measure against.

    Measured on the stage-1 snapshot, the MAD of a row is either exactly 0.0 or at
    least 2.471, with nothing in between: 2.471 is the smallest non-zero value the
    8-bit luminance quantisation can produce after the 1.4826 scaling. So a floor
    anywhere in (0, 2.471) leaves every row with any variation bit-identical, and
    ``MAD_FLOOR = 1.0`` is one grey level, chosen inside that gap on a physical
    argument rather than to fit the data. Gate 3's three measured observations have a
    minimum row MAD of 2.471, so their receipt is unchanged by construction, and
    ``tests/test_corridor_fit.py`` pins that.

    A flat row now normalises to exactly zero, which is the honest reading: no
    variation means no evidence of a trace either way.
    :func:`flat_row_fraction` reports how much of an image is affected, because a
    waterfall with a sixth of its rows dead is a data-quality finding in itself.
    """
    x0 = crop_box.x0 + EDGE_MARGIN_PX
    x1 = crop_box.x1 - EDGE_MARGIN_PX
    y0 = crop_box.y0 + EDGE_MARGIN_PX
    y1 = crop_box.y1 - EDGE_MARGIN_PX
    lum = rgb[y0:y1, x0:x1].astype(np.float32).mean(axis=2)
    med = np.median(lum, axis=1, keepdims=True)
    mad = np.median(np.abs(lum - med), axis=1, keepdims=True) * 1.4826
    return (lum - med) / np.maximum(mad, MAD_FLOOR)


def flat_row_fraction(rgb: np.ndarray, crop_box: Any) -> dict[str, Any]:
    """Fraction of spectrogram rows with no luminance variation at all.

    A flat row is dead capture time: the receiver produced a constant value for that
    instant across the whole band. It carries no evidence about a trace, and before
    the divisor floor was fixed it produced the largest matched-filter responses in
    the corpus. Reported as a feature so the model can use "this capture is partly
    dead" rather than being handed a spurious detection from it.
    """
    x0 = crop_box.x0 + EDGE_MARGIN_PX
    x1 = crop_box.x1 - EDGE_MARGIN_PX
    y0 = crop_box.y0 + EDGE_MARGIN_PX
    y1 = crop_box.y1 - EDGE_MARGIN_PX
    lum = rgb[y0:y1, x0:x1].astype(np.float32).mean(axis=2)
    med = np.median(lum, axis=1, keepdims=True)
    mad = (np.median(np.abs(lum - med), axis=1) * 1.4826).astype(float)
    n_rows = int(mad.size)
    n_flat = int((mad <= 0.0).sum())
    return {
        "n_rows": n_rows,
        "n_flat_rows": n_flat,
        "flat_row_frac": (n_flat / n_rows) if n_rows else None,
        "min_row_mad": float(mad.min()) if n_rows else None,
    }


def max_coherent_jump_px(
    hz_per_px: float,
    seconds_per_row: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> float:
    """Largest row-to-row frequency step a real satellite trace can take, in pixels.

    A second trace in the same waterfall is another satellite, so it obeys the same
    physics as the first: its frequency can only move as fast as Doppler allows. The
    bound is the peak Doppler slope already derived for the TLE staleness threshold,
    ``PEAK_DOPPLER_SLOPE_HZ_PER_S``, converted into this image's pixels by its own Hz
    per pixel and its own seconds per row. Half the matched-filter width is added
    because the smoothing can move a peak by that much on its own.

    This is what separates a second trace from interference. A carrier that jumps
    further than this between adjacent rows is not following an orbit, so counting it
    as a trace would report every burst of noise as a second satellite.
    """
    if hz_per_px <= 0.0 or seconds_per_row <= 0.0:
        raise ValueError(
            "hz_per_px and seconds_per_row must both be positive to convert a "
            f"Doppler slope into pixels. Got {hz_per_px} and {seconds_per_row}."
        )
    slope_px_per_row = (PEAK_DOPPLER_SLOPE_HZ_PER_S * seconds_per_row) / hz_per_px
    return slope_px_per_row + thresholds.filter_width / 2.0


def second_trace_evidence(
    rgb: np.ndarray,
    crop_box: Any,
    *,
    window_px: float,
    max_jump_px: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """Evidence that a second satellite is transmitting inside the same waterfall.

    Nothing in this pipeline counted traces. One corridor is fitted, one path is
    scored, and a second carrier was averaged into the background that the first is
    measured against, so an image with two satellites in it read as an image with one
    satellite and noisier surroundings. That is a silent success. It matters here and
    not only in the abstract: the corridor question is whether the trace in the image
    follows the target's predicted Doppler, and a second trace gives a reviewer a
    second curve that the first can be confused with.

    Every threshold is one this module already uses, so there is no second definition
    of signal:

    * ``thresholds.z_min`` decides that a pixel is a detection, the same bar the
      corridor fit uses.
    * ``window_px`` is the caller's per-row search window, normally
      ``thresholds.search_window_factor`` times the corridor half-width in pixels. A
      maximum inside that window is the trace the fitter is already following, so the
      second peak is taken outside it.
    * ``thresholds.min_detect_frac`` is the share of rows a trace must appear in
      before it counts as a trace at all, which is the bar the primary has to clear.
    * ``max_jump_px`` comes from :func:`max_coherent_jump_px`, which is Doppler
      physics rather than a tuned number.
    * ``MIN_VISIBLE_ROWS`` is the floor below which a fraction is noise with a
      denominator.

    The denominator is rows where the primary is itself detected, not every row. A row
    with no primary has no second peak to speak of, and dividing by every row would
    let a mostly empty image dilute a real second trace out of the result.

    Returns a dict, matching :func:`flat_row_fraction`, and carries ``reason`` set to
    ``MULTIPLE_TRACES_SUSPECTED`` when the evidence clears both bars and ``None`` when
    it does not. ``measurable`` is False when the image cannot support the question at
    all, with ``why_not`` naming the bar it failed, because an unmeasurable image and a
    clean image are different answers and must not share one word.
    """
    if window_px < 0.0 or max_jump_px <= 0.0:
        raise ValueError(
            "window_px must be non-negative and max_jump_px positive. Got "
            f"{window_px} and {max_jump_px}."
        )

    z = smooth_columns(normalised_rows(rgb, crop_box), thresholds.filter_width)
    n_rows, n_cols = z.shape

    unmeasurable: dict[str, Any] = {
        "measurable": False,
        "why_not": None,
        "n_rows": n_rows,
        "n_rows_primary_detected": 0,
        "n_rows_second_detected": 0,
        "second_frac_of_primary_rows": None,
        "median_jump_px": None,
        "max_jump_px_allowed": max_jump_px,
        "coherent": None,
        "reason": None,
    }

    if n_rows < MIN_VISIBLE_ROWS:
        unmeasurable["why_not"] = "TOO_FEW_ROWS"
        return unmeasurable
    # Two peaks need somewhere to sit. A plot narrower than two exclusion windows
    # cannot hold a separated pair, so the question is unanswerable rather than
    # answered no.
    if n_cols < 2 * window_px + 2:
        unmeasurable["why_not"] = "PLOT_TOO_NARROW"
        return unmeasurable

    primary_col = np.argmax(z, axis=1)
    primary_z = z[np.arange(n_rows), primary_col]
    lit = primary_z >= thresholds.z_min
    n_primary = int(lit.sum())
    if n_primary < MIN_VISIBLE_ROWS:
        unmeasurable["why_not"] = "TOO_FEW_DETECTED_ROWS"
        unmeasurable["n_rows_primary_detected"] = n_primary
        return unmeasurable

    # Blank out the fitter's own search window around the primary and take what is
    # left. Anything inside that window is the same trace, by this pipeline's own
    # definition of the same trace.
    cols = np.arange(n_cols)[None, :]
    outside = np.abs(cols - primary_col[:, None]) > window_px
    masked = np.where(outside, z, -np.inf)
    second_col = np.argmax(masked, axis=1)
    second_z = masked[np.arange(n_rows), second_col]

    qualifies = lit & np.isfinite(second_z) & (second_z >= thresholds.z_min)
    n_second = int(qualifies.sum())
    frac = n_second / n_primary

    # Coherence, over the qualifying rows in row order: how far the second peak moves
    # per row it travels. A gap between qualifying rows is divided out rather than
    # ignored, because a trace that reappears twenty rows later has had twenty rows in
    # which to move and must not be charged for one jump.
    rows_q = np.flatnonzero(qualifies)
    median_jump: float | None = None
    if rows_q.size >= 2:
        d_col = np.abs(np.diff(second_col[rows_q]).astype(float))
        d_row = np.diff(rows_q).astype(float)
        median_jump = float(np.median(d_col / d_row))

    coherent = median_jump is not None and median_jump <= max_jump_px
    reason = (
        "MULTIPLE_TRACES_SUSPECTED"
        if coherent and frac >= thresholds.min_detect_frac
        else None
    )

    return {
        "measurable": True,
        "why_not": None,
        "n_rows": n_rows,
        "n_rows_primary_detected": n_primary,
        "n_rows_second_detected": n_second,
        "second_frac_of_primary_rows": frac,
        "median_jump_px": median_jump,
        "max_jump_px_allowed": max_jump_px,
        "coherent": coherent,
        "reason": reason,
    }


def smooth_columns(z: np.ndarray, width: int) -> np.ndarray:
    """Box-average along frequency, matching a trace a few pixels wide."""
    if width <= 1:
        return z
    pad = width // 2
    padded = np.pad(z, ((0, 0), (pad, pad)), mode="edge")
    out = np.empty_like(z)
    for i in range(z.shape[1]):
        out[:, i] = padded[:, i:i + width].mean(axis=1)
    return out


# SPACE-S4: fewest visible rows a fit is allowed to run on. A window almost
# entirely below the horizon has no pass in it to measure, and a detect_frac over a
# handful of rows is noise with a denominator. Eight matches the IMAGE_TOO_SMALL
# floor above, so the same minimum applies whether rows are missing because the
# image is small or because the satellite had not risen.
#
# Inert on both corpora as of this commit: the worst window in the 150-record
# working corpus is 16.60 percent below the horizon, which leaves 1284 of 1540 rows,
# and no observation comes within two orders of magnitude of this floor. It exists
# so that a future corpus with a badly scheduled window degrades with a named reason
# instead of publishing a detect_frac over four rows.
MIN_VISIBLE_ROWS: int = 8


def path_score(
    zs: np.ndarray,
    cols: np.ndarray,
    min_valid: float = 0.8,
    row_mask: np.ndarray | None = None,
) -> float:
    """Mean normalised intensity along one path through the image.

    NaN when the path leaves the plot for more than 20 percent of the pass,
    because a shorter path is a noisier statistic and would win a scan for the
    wrong reason.

    ``row_mask`` is an optional per-row boolean of rows that may carry signal at
    all; rows outside it are excluded from the mean. ``min_valid`` is then measured
    against the masked rows rather than the whole image, because a horizon mask is
    not the path leaving the plot and must not be charged as if it were. Callers
    scoring several curves on one image must pass the SAME mask to each: see
    :func:`physics.visible_rows`.
    """
    in_plot = (cols >= 0) & (cols < zs.shape[1])
    if row_mask is None:
        usable = in_plot
        denom = in_plot.size
    else:
        usable = in_plot & row_mask
        denom = int(row_mask.sum())
    if denom == 0:
        return float("nan")
    if usable.sum() / denom < min_valid:
        return float("nan")
    rows = np.arange(zs.shape[0])
    return float(zs[rows[usable], cols[usable]].mean())


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorridorFit:
    """The outcome of fitting one corridor to one waterfall.

    ``degraded`` is not None when the measurement could not be made. A degraded
    result is not a corridor miss. Folding the two together manufactures
    failures, so callers must branch on it.
    """

    obs_id: int | None
    corridor_type: str                    # "uncorrected" or "corrected"
    degraded: str | None

    fitted_offset_hz: float | None
    fitted_offset_ppm: float | None
    offset_bound_hz: float | None
    offset_at_bound: bool                 # True when the fit hit its own limit

    rows_total: int
    rows_detected: int
    # Rows excluded because the satellite was below the station's horizon floor.
    # detect_frac is measured against rows_total minus this, because a masked row
    # was never a chance to detect and charging it as a miss would penalise the
    # corridor for the schedule of the observation window.
    rows_masked_below_horizon: int
    detect_frac: float

    residual_p50_hz: float | None
    residual_p95_hz: float | None
    residual_max_hz: float | None
    residuals_hz: list[float] = field(default_factory=list)

    half_width_hz: float | None = None
    coverage: float | None = None          # detected rows inside the corridor
    corridor_hit: bool | None = None
    sigma_at_fit: float | None = None

    def summary(self) -> dict[str, Any]:
        """Receipt-shaped view, without the full residual series."""
        return {
            "obs_id": self.obs_id,
            "corridor_type": self.corridor_type,
            "degraded": self.degraded,
            "fitted_offset_hz": self.fitted_offset_hz,
            "fitted_offset_ppm": self.fitted_offset_ppm,
            "offset_bound_hz": self.offset_bound_hz,
            "offset_at_bound": self.offset_at_bound,
            "rows_total": self.rows_total,
            "rows_detected": self.rows_detected,
            "rows_masked_below_horizon": self.rows_masked_below_horizon,
            "detect_frac": self.detect_frac,
            "residual_p50_hz": self.residual_p50_hz,
            "residual_p95_hz": self.residual_p95_hz,
            "residual_max_hz": self.residual_max_hz,
            "half_width_hz": self.half_width_hz,
            "coverage": self.coverage,
            "corridor_hit": self.corridor_hit,
            "sigma_at_fit": self.sigma_at_fit,
        }


@dataclass(frozen=True)
class NullControlResult:
    """One null control's fit, for comparison against the true corridor."""

    name: str
    rationale: str
    fit: CorridorFit


# ---------------------------------------------------------------------------
# The bounded offset fit
# ---------------------------------------------------------------------------


def fit_offset(
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    rx_freq_hz: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> tuple[float | None, float | None, bool, float]:
    """Fit one constant frequency offset, bounded in ppm of the downlink.

    Returns ``(offset_hz, sigma_at_fit, at_bound, bound_hz)``. ``offset_hz`` is
    None when no candidate offset kept the path inside the plot.

    The estimator is the same matched filter A3 used and the search range is the
    difference in intent: bounded here, unbounded there.

    SPACE-S8: the sigmas are NOT comparable across the two, and an earlier version of
    this docstring said they were. ``_pixel_sigma_scale`` normalises against the median
    and MAD of the whole ``zs`` array; A3 normalised per column band. Measured on the
    seven decisive observations, stored ``sigma_curved`` over the sigma this returns:

        14740031  25.10 / 2.024 = 12.4x       14746118   7.27 / 5.091 =  1.43x
        14745664  15.14 / 1.539 =  9.84x      14746055  21.01 / 2.921 =  7.20x
        14745929  15.94 / 1.652 =  9.65x      14746048   1.71 / 1.966 =  0.87x
                                              14745602  12.03 / 3.044 =  3.95x

    The ratio is not a constant, so there is no conversion between the two scales, and
    the direction of a comparison can invert: on 14740031 the upstream VERTICAL sigma of
    2.83 exceeds this module's CURVED sigma of 2.024, which reads as a straight line
    beating the Doppler curve and is the opposite of what both artifacts found. Compare
    a sigma only against another sigma from the same estimator, which is what
    ``calibrate_against_nulls`` does.
    """
    bound_hz = thresholds.offset_ppm_limit * rx_freq_hz / 1e6
    bound_px = int(math.floor(bound_hz / hz_per_px))
    smoothed = smooth_columns(zs, thresholds.filter_width)
    origin = centre_px - EDGE_MARGIN_PX
    row_mask = visible_rows(corridor, int(zs.shape[0]))

    best_sigma, best_off_px = _best_over_offsets(
        smoothed, zs, corridor, hz_per_px, origin, bound_px, row_mask=row_mask
    )
    if best_off_px is None:
        return None, None, False, bound_hz

    at_bound = abs(best_off_px) >= bound_px
    return float(px_to_offset_hz(best_off_px, hz_per_px)), float(best_sigma), at_bound, bound_hz


def px_to_offset_hz(off_px: float, hz_per_px: float) -> float:
    """Convert a column displacement to the ``freq_offset_hz`` that produces it.

    ``corridor_columns`` maps Hz to columns through ``AXIS_SIGN_CONVENTION``, so a
    column shift and the Hz offset that causes it differ in sign. Searching in
    column space and handing the winner back as ``off_px * hz_per_px`` is how the
    first version of this module went wrong: the offset was re-applied to the
    opposite side of the axis, which on observation 14740031 displaced the curve
    by twice the fitted 113 px and detected nothing at all. Every conversion goes
    through this function so the sign is stated once.
    """
    return off_px * hz_per_px / AXIS_SIGN_CONVENTION


def _base_columns(
    corridor: Corridor, hz_per_px: float, origin: float, n_rows: int
) -> np.ndarray:
    return corridor_columns(
        corridor,
        hz_per_px=hz_per_px,
        centre_px=origin,
        image_height=n_rows,
        freq_offset_hz=0.0,
    )


def measurable_rows(zs: np.ndarray) -> np.ndarray:
    """Rows that carry any variation at all, as a per-row boolean.

    `normalised_rows` divides by `max(mad, MAD_FLOOR)`, and a row with no variation has
    `lum == med` everywhere, so it comes out exactly zero across its whole width. Testing
    for that exactly is not a tolerance choice: it is the arithmetic the normaliser
    guarantees for a dead row and for nothing else.

    A dead row is dead capture time. It carries no evidence about a trace, so it belongs
    in neither the path score nor the scale the path score is divided by.
    """
    return np.any(zs != 0.0, axis=1)


def _pixel_sigma_scale(
    zs: np.ndarray, rows: np.ndarray | None = None
) -> tuple[float, float]:
    """The image's own pixel scale, over the rows the score is taken from.

    `spread` used to end in ``or 1e-9``, which reads as a guard against dividing by zero
    and is not one. An image more than half of whose rows are dead has a `zs` more than
    half exact zeros, so its median absolute deviation is exactly 0, the ``or`` swapped in
    1e-9, and sigmas came out around 1e10: measured at 3.09e10 on obs 14745697 in the
    first run over E16's pool. It never fired on A3's three observations because none of
    them has a dead row.

    Returning 0.0 instead lets the caller say the scale could not be taken, which is what
    is true. A sigma of thirty billion is not an overwhelming detection, it is a
    denominator that vanished.

    `rows` is the same mask the path score uses. Measuring the numerator over one row set
    and the denominator over another is not a sigma at all, and that is what this did.
    """
    block = zs if rows is None else zs[rows]
    if block.size == 0:
        return 0.0, 0.0
    finite = block[np.isfinite(block)]
    if finite.size == 0:
        return 0.0, 0.0
    baseline = float(np.median(finite))
    spread = float(np.median(np.abs(finite - baseline)) * 1.4826)
    return baseline, spread


def offset_sweep(
    smoothed: np.ndarray,
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    origin: float,
    bound_px: int,
    row_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Matched-filter sigma at every whole-pixel offset inside the bound.

    This is the quantity :func:`_best_over_offsets` used to compute and discard all but
    the maximum of. It is published because it is the most direct evidence available that
    the corridor is on the trace rather than near it: the detection rises to a peak at the
    fitted offset and falls away either side, and a reader can watch that happen instead
    of being handed one number.

    Returning it as the primitive, with the argmax as a wrapper, means the peak of the
    published curve *is* the fitted offset by construction. Computing the two separately
    would be two implementations of one quantity, free to drift apart.

    Offsets that score non-finitely are dropped from both arrays rather than filled, so
    the two stay aligned and nothing invents a value for an offset that was not scored.
    """
    n_rows = zs.shape[0]
    base = _base_columns(corridor, hz_per_px, origin, n_rows)

    # The score and the scale it is divided by must come from the same rows. A dead row
    # scores nothing and must not be in the estimate either; an invisible row is already
    # excluded from the score by `row_mask` and used to be counted in the scale.
    live = measurable_rows(zs)
    scored_rows = live if row_mask is None else (row_mask & live)
    baseline, spread = _pixel_sigma_scale(zs, scored_rows)
    if spread <= 0.0:
        empty = np.empty(0, dtype=int), np.empty(0, dtype=float)
        return empty

    offs: list[int] = []
    sigs: list[float] = []
    for off_px in range(-bound_px, bound_px + 1):
        cols = np.rint(base + off_px).astype(int)
        s = path_score(smoothed, cols, row_mask=scored_rows)
        if math.isnan(s):
            continue
        offs.append(off_px)
        sigs.append((s - baseline) / spread)
    return np.asarray(offs, dtype=int), np.asarray(sigs, dtype=float)


def _best_over_offsets(
    smoothed: np.ndarray,
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    origin: float,
    bound_px: int,
    row_mask: np.ndarray | None = None,
) -> tuple[float, int | None]:
    """Best path sigma over every whole-pixel offset inside the bound.

    The argmax of :func:`offset_sweep`, and nothing else. Keeping it that thin is the
    point: the console publishes the sweep so a reader can see the detection rise to a
    peak and fall away, and if the peak were computed by a second loop the curve on
    screen could disagree with the number beside it.
    """
    offsets, sigmas = offset_sweep(
        smoothed, zs, corridor, hz_per_px, origin, bound_px, row_mask=row_mask
    )
    if offsets.size == 0:
        # Either no measurable row under the mask, or no offset scored finitely. There is
        # no sigma to report, and NaN reaches the caller's existing refusal path.
        return float("nan"), None

    best = int(np.argmax(sigmas))
    best_sigma = float(sigmas[best])
    best_off_px: int | None = int(offsets[best])
    return best_sigma, best_off_px


@dataclass(frozen=True)
class NullCalibration:
    """The true corridor's path sigma against a distribution of wrong corridors.

    This is the gate-3 statistic. A raw sigma cannot be read on its own, because
    the offset is a fitted parameter and any curve gets to slide to its best
    position. What carries evidence is the margin over curves that should not fit
    at all, measured under identical rules.
    """

    n_nulls: int
    true_sigma: float | None
    null_sigmas: list[float]
    null_median: float | None
    null_p95: float | None
    null_max: float | None
    # Count of nulls scoring at least the true corridor. Reported alongside the
    # p-value because "0 of 200" is plainer than "0.005".
    n_at_least: int | None
    # One-sided empirical p-value with the conventional +1 correction, so it can
    # never be exactly zero on a finite sample. Its floor is 1/(n+1).
    p_value: float | None
    # Margin of the true sigma over the single best null. Preferred over a
    # MAD-scaled z: scrambled paths all land in noise and their MAD collapses
    # towards zero, which inflated an earlier z_over_nulls to 188 and made a
    # sound result look like a reporting error.
    margin_over_best_null: float | None
    # Sigma of the same curve with its swing scaled, holding smoothness fixed.
    # Answers the objection that the test only rewards any smooth path.
    scaled_swing_sigmas: dict[str, float] = field(default_factory=dict)
    beats_scaled_swing: bool | None = None
    # True when the fitted offset saturated its bound, so the sigma is a lower
    # bound on the achievable fit rather than the best one.
    offset_at_bound: bool | None = None
    corridor_span_hz: float | None = None
    # Standard deviation of the null sigma distribution, and the margin measured
    # in those units. The raw margin cannot be compared across observations,
    # because each one has its own noise scale; this can.
    null_sigma_sd: float | None = None
    margin_in_null_sd: float | None = None
    # The same curve reversed in time, which for an odd-symmetric Doppler curve is
    # the sign flip. The one control that directly tests AXIS_SIGN_CONVENTION.
    reversed_sigma: float | None = None
    beats_reversed: bool | None = None
    # max |D(f) + D(1-f)| over the pass, as a fraction of the swing. Zero for a
    # perfectly odd-symmetric curve. Published so the premise the reversal control
    # rests on is measured per observation rather than asserted once in a comment.
    odd_symmetry_residual_frac: float | None = None
    discriminates: bool | None = None
    # Why no nulls were built, when `n_nulls` is 0. Four separate conditions end
    # here and they do not mean the same thing: a corrected capture is vacuous by
    # construction, a grazing pass is untestable, and a failed offset search is a
    # measurement failure. A caller that reads only `n_nulls == 0` cannot tell a
    # refusal from a breakage, so each branch names itself.
    not_tested_reason: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "n_nulls": self.n_nulls,
            "true_sigma": self.true_sigma,
            "null_median": self.null_median,
            "null_p95": self.null_p95,
            "null_max": self.null_max,
            "n_at_least": self.n_at_least,
            "p_value": self.p_value,
            "margin_over_best_null": self.margin_over_best_null,
            "scaled_swing_sigmas": self.scaled_swing_sigmas,
            "beats_scaled_swing": self.beats_scaled_swing,
            "offset_at_bound": self.offset_at_bound,
            "corridor_span_hz": self.corridor_span_hz,
            "null_sigma_sd": self.null_sigma_sd,
            "margin_in_null_sd": self.margin_in_null_sd,
            "reversed_sigma": self.reversed_sigma,
            "beats_reversed": self.beats_reversed,
            "odd_symmetry_residual_frac": self.odd_symmetry_residual_frac,
            "discriminates": self.discriminates,
            # Why there is no p-value, when there is none. Every caller that shows a
            # human an absent p-value already names the reason; this summary is what
            # the gate receipt publishes, and it used to be the one that did not.
            "not_tested_reason": self.not_tested_reason,
        }


def scoring_setup(
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    rx_freq_hz: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> tuple[np.ndarray, float, int, np.ndarray]:
    """The four things every scored curve in one observation must share.

    The smoothed image, the column origin, the offset bound in pixels, and the horizon
    row mask. Extracted from :func:`calibrate_against_nulls` so that anything publishing
    the sweep gets the geometry the gate scored rather than its own reconstruction of it.
    A second copy with a different filter width, or a mask derived from a null's corridor
    instead of the true one, would produce a curve peaking somewhere the receipt does not,
    and neither would look wrong on its own.

    SPACE-S4: the horizon mask belongs to the observation window, so it is built once from
    the true corridor and handed to every curve. Letting each null derive its own would
    score the nulls on more rows than the truth, because the null builders carry no
    elevation series, and a margin measured over two different row sets is not a margin.
    """
    bound_hz = thresholds.offset_ppm_limit * rx_freq_hz / 1e6
    bound_px = int(math.floor(bound_hz / hz_per_px))
    smoothed = smooth_columns(zs, thresholds.filter_width)
    origin = centre_px - EDGE_MARGIN_PX
    row_mask = visible_rows(corridor, int(zs.shape[0]))
    return smoothed, origin, bound_px, row_mask


def published_sweep(
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    rx_freq_hz: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> tuple[np.ndarray, np.ndarray]:
    """The offset sweep for one observation, in the geometry the gate used.

    Offsets in whole pixels and matched-filter sigma at each. The console draws this so a
    reader can watch the detection rise to a peak at the fitted offset and fall away
    either side, which is the most direct evidence available that the corridor is on the
    trace rather than merely near it.

    Returns two empty arrays when there is nothing to sweep, for the same reason
    :func:`offset_sweep` does: a flat line of zeros would render as "measured, and nothing
    is there", which is a different claim from "this could not be measured".
    """
    smoothed, origin, bound_px, row_mask = scoring_setup(
        zs, corridor, hz_per_px, centre_px, rx_freq_hz, thresholds
    )
    return offset_sweep(
        smoothed, zs, corridor, hz_per_px, origin, bound_px, row_mask=row_mask
    )


def calibrate_against_nulls(
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    rx_freq_hz: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> NullCalibration:
    """Score the true corridor against N scrambled corridors, same rules.

    Each null permutes the Doppler samples in time, so it keeps every frequency
    value and the whole swing while destroying the monotone S shape. Each null
    gets the same bounded offset search the true corridor gets, so neither is
    advantaged by the free parameter.
    """
    smoothed, origin, bound_px, row_mask = scoring_setup(
        zs, corridor, hz_per_px, centre_px, rx_freq_hz, thresholds
    )

    def _empty(sig: float | None, reason: str) -> NullCalibration:
        return NullCalibration(
            n_nulls=0, true_sigma=sig, null_sigmas=[], null_median=None,
            null_p95=None, null_max=None, n_at_least=None, p_value=None,
            margin_over_best_null=None, not_tested_reason=reason,
        )

    true_sigma, true_off = _best_over_offsets(
        smoothed, zs, corridor, hz_per_px, origin, bound_px, row_mask=row_mask
    )
    if true_off is None:
        # A NaN sigma here means the image had no measurable row under the visibility
        # mask, which is a different refusal from failing to find an offset and is
        # reported as one.
        if isinstance(true_sigma, float) and math.isnan(true_sigma):
            return _empty(None, "no_measurable_rows")
        return _empty(None, "no_offset_fit")

    span = float(np.ptp(np.asarray(corridor.doppler_hz, dtype=float)))
    if span <= 0.0:
        # A flat corridor has no shape to scramble, so every null reproduces it
        # and the comparison is vacuous by construction rather than informative.
        # Measured: on the four CORRECTED observations the corrected corridor is
        # identically 0 Hz across the whole pass, and true and null sigmas agreed
        # to every decimal place. physics.py sets corrected.doppler_hz to zeros
        # unconditionally, so this branch only ever catches corrected corridors.
        return _empty(float(true_sigma), "flat_corridor")

    if span < thresholds.min_swing_hz:
        # A small swing cannot distinguish one shape from another: a permutation
        # of nearly-equal values is nearly the same path, so truth and null both
        # collapse toward noise and a p-value can come out significant on pixel
        # quantisation alone. A3 refuses a verdict below the same 3 kHz for the
        # same reason. Only `span > 0` was checked before, which let a grazing
        # low-elevation pass through as testable.
        return _empty(float(true_sigma), "swing_below_floor")

    sigmas: list[float] = []
    for i in range(thresholds.n_nulls):
        null_c = scramble_corridor(corridor, thresholds.seed + i)
        s, off = _best_over_offsets(
            smoothed, zs, null_c, hz_per_px, origin, bound_px, row_mask=row_mask
        )
        if off is not None and math.isfinite(s):
            sigmas.append(float(s))

    if not sigmas:
        return _empty(float(true_sigma), "no_null_scored")

    # Scaled-swing controls hold the curve's smoothness and its sign structure
    # fixed and change only the magnitude of the predicted Doppler. A test that
    # any smooth path would win scores these as highly as the truth. A test that
    # the predicted swing itself is right does not.
    scaled: dict[str, float] = {}
    for factor in thresholds.swing_scale_factors:
        s, off = _best_over_offsets(
            smoothed, zs, scale_corridor(corridor, factor),
            hz_per_px, origin, bound_px, row_mask=row_mask,
        )
        if off is not None and math.isfinite(s):
            scaled[f"{factor:g}x"] = float(s)

    # SPACE-B5: the reversal control, restored. One extra scored fit.
    rev_sigma: float | None = None
    s_rev, off_rev = _best_over_offsets(
        smoothed, zs, reverse_corridor(corridor), hz_per_px, origin, bound_px,
        row_mask=row_mask,
    )
    if off_rev is not None and math.isfinite(s_rev):
        rev_sigma = float(s_rev)

    arr = np.asarray(sigmas)
    at_least = int((arr >= true_sigma).sum())
    p_value = (at_least + 1) / (len(arr) + 1)
    null_max = float(arr.max())
    beats_scaled = (
        all(true_sigma > v for v in scaled.values()) if scaled else None
    )

    # A fit that saturates its own bound may not have found the true optimum, so
    # the sigma is a lower bound rather than the best available. This was computed
    # in fit_offset and then never consulted anywhere, which is a silent choice.
    # Now it is an explicit one.
    at_bound = abs(true_off) >= bound_px

    # SPACE-B4: the margin is what separates truth from an inverted corridor, and
    # it was computed, published and left out of the decision. In null standard
    # deviations so it is comparable across observations. A null distribution with
    # no spread leaves the margin unmeasurable, and unmeasurable is not a pass.
    null_sd = float(arr.std(ddof=1)) if arr.size > 1 else None
    margin_raw = float(true_sigma) - float(null_max)
    margin_sd = (
        margin_raw / null_sd if null_sd is not None and null_sd > 0.0 else None
    )

    # The true corridor must beat its own reversal. For an odd-symmetric curve the
    # reversal is the sign flip, so an inverted corridor fails here: its reversal
    # is the truth, which outscores it.
    beats_rev = None if rev_sigma is None else bool(float(true_sigma) > rev_sigma)

    return NullCalibration(
        n_nulls=len(arr),
        true_sigma=float(true_sigma),
        null_sigmas=sigmas,
        null_median=float(np.median(arr)),
        null_p95=float(np.percentile(arr, 95)),
        null_max=null_max,
        n_at_least=at_least,
        p_value=float(p_value),
        margin_over_best_null=margin_raw,
        scaled_swing_sigmas=scaled,
        beats_scaled_swing=beats_scaled,
        offset_at_bound=at_bound,
        corridor_span_hz=span,
        null_sigma_sd=null_sd,
        margin_in_null_sd=margin_sd,
        reversed_sigma=rev_sigma,
        beats_reversed=beats_rev,
        odd_symmetry_residual_frac=odd_symmetry_residual_frac(corridor),
        discriminates=bool(
            p_value <= thresholds.p_value_max
            # The two criteria the inversion fails. Both are required to be
            # measured and clear, not merely "not False": a criterion that cannot
            # be evaluated cannot contribute evidence.
            and margin_sd is not None
            and margin_sd >= thresholds.margin_null_sd_min
            and beats_rev is True
            and (beats_scaled is not False)
            and not (at_bound and thresholds.exclude_at_bound)
        ),
    )


def measure_residuals(
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    offset_hz: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-row signed residual between the detected trace and the fitted curve.

    Returns ``(rows, residual_hz)`` for rows carrying a detection. A row counts
    as a detection when the brightest pixel inside its search window clears
    ``z_min``. The window is wider than the corridor on purpose, so a row whose
    trace sits outside the corridor is still detected and still measured, which
    is what lets coverage come out below one.
    """
    smoothed = smooth_columns(zs, thresholds.filter_width)
    n_rows, n_cols = zs.shape

    origin = centre_px - EDGE_MARGIN_PX
    predicted = corridor_columns(
        corridor,
        hz_per_px=hz_per_px,
        centre_px=origin,
        image_height=n_rows,
        freq_offset_hz=offset_hz,
    )

    half_px = corridor.half_width_hz / hz_per_px
    window_px = max(2.0, thresholds.search_window_factor * half_px)

    # SPACE-S4: a row below the local horizon cannot hold a trace, so the brightest
    # pixel in its window is noise. Detecting there inflates rows_detected and pulls
    # a spurious residual into the percentiles.
    visible = visible_rows(corridor, n_rows)

    rows_out: list[int] = []
    resid_out: list[float] = []
    for r in range(n_rows):
        if not visible[r]:
            continue
        lo = int(math.floor(predicted[r] - window_px))
        hi = int(math.ceil(predicted[r] + window_px)) + 1
        lo_c = max(0, lo)
        hi_c = min(n_cols, hi)
        if hi_c - lo_c < 2:
            continue
        seg = smoothed[r, lo_c:hi_c]
        if not np.any(np.isfinite(seg)):
            continue
        k = int(np.nanargmax(seg))
        if not np.isfinite(seg[k]) or seg[k] < thresholds.z_min:
            continue
        detected_col = lo_c + k
        rows_out.append(r)
        resid_out.append(float((detected_col - predicted[r]) * hz_per_px))

    return np.asarray(rows_out, dtype=int), np.asarray(resid_out, dtype=float)


def fit_corridor(
    zs: np.ndarray,
    corridor: Corridor | None,
    corridor_type: str,
    hz_per_px: float | None,
    centre_px: float | None,
    rx_freq_hz: float | None,
    obs_id: int | None = None,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> CorridorFit:
    """Fit a corridor to a waterfall and measure whether it contains the trace.

    Every failure path returns a named ``degraded`` value rather than a False
    ``corridor_hit``, because "could not measure" and "measured a miss" are
    different findings and merging them invents regressions.
    """
    def _degraded(reason: str) -> CorridorFit:
        return CorridorFit(
            obs_id=obs_id,
            corridor_type=corridor_type,
            degraded=reason,
            fitted_offset_hz=None,
            fitted_offset_ppm=None,
            offset_bound_hz=None,
            offset_at_bound=False,
            rows_total=int(zs.shape[0]) if zs is not None and zs.ndim == 2 else 0,
            rows_detected=0,
            rows_masked_below_horizon=0,
            detect_frac=0.0,
            residual_p50_hz=None,
            residual_p95_hz=None,
            residual_max_hz=None,
        )

    if corridor is None:
        return _degraded("NO_CORRIDOR")
    if hz_per_px is None:
        return _degraded("NO_HZ_PER_PX")
    if centre_px is None:
        return _degraded("NO_CENTRE_PX")
    if rx_freq_hz is None:
        return _degraded("NO_RX_FREQ")
    if zs is None or zs.ndim != 2 or zs.shape[0] < 8 or zs.shape[1] < 8:
        return _degraded("IMAGE_TOO_SMALL")

    offset_hz, sigma, at_bound, bound_hz = fit_offset(
        zs, corridor, hz_per_px, centre_px, rx_freq_hz, thresholds
    )
    if offset_hz is None:
        return _degraded("CORRIDOR_LEFT_PLOT")

    rows, resid = measure_residuals(
        zs, corridor, hz_per_px, centre_px, offset_hz, thresholds
    )

    n_rows = int(zs.shape[0])
    # SPACE-S4: measure the detected fraction against the rows that could have held
    # a trace. Using the full image height instead would push a window that opens
    # below the horizon towards TRACE_NOT_MEASURABLE for a reason that has nothing
    # to do with the trace.
    n_visible = int(visible_rows(corridor, n_rows).sum())
    n_masked = n_rows - n_visible
    if n_visible < MIN_VISIBLE_ROWS:
        return _degraded("MOSTLY_BELOW_HORIZON")
    detect_frac = len(rows) / n_visible if n_visible else 0.0

    if len(rows) == 0 or detect_frac < thresholds.min_detect_frac:
        out = _degraded("TRACE_NOT_MEASURABLE")
        return CorridorFit(
            obs_id=out.obs_id,
            corridor_type=out.corridor_type,
            degraded=out.degraded,
            fitted_offset_hz=offset_hz,
            fitted_offset_ppm=offset_hz / rx_freq_hz * 1e6,
            offset_bound_hz=bound_hz,
            offset_at_bound=at_bound,
            rows_total=n_rows,
            rows_detected=len(rows),
            rows_masked_below_horizon=n_masked,
            detect_frac=detect_frac,
            residual_p50_hz=None,
            residual_p95_hz=None,
            residual_max_hz=None,
            half_width_hz=corridor.half_width_hz,
            sigma_at_fit=sigma,
        )

    a = np.abs(resid)
    inside = a <= corridor.half_width_hz
    coverage = float(inside.mean())

    return CorridorFit(
        obs_id=obs_id,
        corridor_type=corridor_type,
        degraded=None,
        fitted_offset_hz=offset_hz,
        fitted_offset_ppm=offset_hz / rx_freq_hz * 1e6,
        offset_bound_hz=bound_hz,
        offset_at_bound=at_bound,
        rows_total=n_rows,
        rows_detected=len(rows),
        rows_masked_below_horizon=n_masked,
        detect_frac=detect_frac,
        residual_p50_hz=float(np.percentile(a, 50)),
        residual_p95_hz=float(np.percentile(a, 95)),
        residual_max_hz=float(a.max()),
        residuals_hz=[float(v) for v in resid],
        half_width_hz=corridor.half_width_hz,
        coverage=coverage,
        corridor_hit=bool(coverage >= thresholds.coverage_threshold),
        sigma_at_fit=sigma,
    )


# ---------------------------------------------------------------------------
# Null controls
# ---------------------------------------------------------------------------


def invert_corridor(corridor: Corridor) -> Corridor:
    """Mirror the Doppler about zero, which is the opposite axis sign.

    ``corridor_columns`` multiplies by AXIS_SIGN_CONVENTION on its way to pixels, so
    negating the Doppler here draws the curve the other renderer convention would
    produce. Same window, same swing, same smoothness: only the direction changes.
    """
    return Corridor(
        fracs=list(corridor.fracs),
        doppler_hz=[-float(v) for v in corridor.doppler_hz],
        half_width_hz=corridor.half_width_hz,
        max_elevation_deg=corridor.max_elevation_deg,
        tca_frac=corridor.tca_frac,
        elevation_deg=list(corridor.elevation_deg),
    )


def measure_axis_sign(
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    rx_freq_hz: float,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """Re-measure the frequency axis direction from this image.

    SPACE-S5: AXIS_SIGN_CONVENTION is a property of the client that rendered the
    waterfall, and it is applied as one global constant measured on 3 observations
    from 2 client families. This scores the shipped convention against its mirror
    under identical rules, so an observation from a renderer nobody measured either
    confirms the constant or shows up in the receipt disagreeing with it.

    Returns a block that always states whether the measurement could be made.
    ``measurable`` is False when the corridor has too little swing for the two signs
    to differ, which is every corrected corridor: a flat line mirrors onto itself, so
    the argmax there is noise. A3 took that argmax anyway and it came out +1 on two of
    four corrected observations, which is how an unmeasurable quantity gets published
    as a measurement.
    """
    bound_hz = thresholds.offset_ppm_limit * rx_freq_hz / 1e6
    bound_px = int(math.floor(bound_hz / hz_per_px))
    smoothed = smooth_columns(zs, thresholds.filter_width)
    origin = centre_px - EDGE_MARGIN_PX
    row_mask = visible_rows(corridor, int(zs.shape[0]))

    span = float(np.ptp(np.asarray(corridor.doppler_hz, dtype=float)))
    out: dict[str, Any] = {
        "axis_sign_applied": AXIS_SIGN_CONVENTION,
        "corridor_span_hz": span,
        "sigma_as_shipped": None,
        "sigma_mirrored": None,
        "ratio": None,
        "measurable": False,
        "sign_implied": None,
        "agrees_with_constant": None,
        "not_measurable_reason": None,
    }

    if span < thresholds.min_swing_hz:
        out["not_measurable_reason"] = (
            f"corridor swing {span:.0f} Hz is below the {thresholds.min_swing_hz:.0f} "
            "Hz floor, so the mirrored curve is nearly the same path and the two "
            "signs cannot be told apart"
        )
        return out

    shipped, off_shipped = _best_over_offsets(
        smoothed, zs, corridor, hz_per_px, origin, bound_px, row_mask=row_mask
    )
    mirrored, off_mirrored = _best_over_offsets(
        smoothed, zs, invert_corridor(corridor), hz_per_px, origin, bound_px,
        row_mask=row_mask,
    )
    if off_shipped is None or off_mirrored is None:
        out["not_measurable_reason"] = (
            "one of the two orientations has no admissible offset inside the bound, "
            "so the pair was not scored under the same rules"
        )
        return out

    out["sigma_as_shipped"] = float(shipped)
    out["sigma_mirrored"] = float(mirrored)

    # Both sigmas can be negative (a path darker than the image median), so the ratio
    # is taken over the distance from zero of the better one to the worse one and only
    # when the winner is positive. A ratio of two negatives is not a strength.
    better, worse = max(shipped, mirrored), min(shipped, mirrored)
    if better <= 0.0:
        out["not_measurable_reason"] = (
            f"neither orientation scores above the image baseline (best "
            f"{better:.3f} sigma), so there is no trace here to orient"
        )
        return out
    ratio = better / worse if worse > 0.0 else float("inf")
    out["ratio"] = None if ratio == float("inf") else float(ratio)

    if ratio < AXIS_SIGN_MEASURABLE_RATIO:
        out["not_measurable_reason"] = (
            f"the two orientations score within {ratio:.2f}x of each other, under the "
            f"{AXIS_SIGN_MEASURABLE_RATIO:.1f}x separation this treats as decisive"
        )
        return out

    out["measurable"] = True
    out["sign_implied"] = (
        AXIS_SIGN_CONVENTION if shipped >= mirrored else -AXIS_SIGN_CONVENTION
    )
    out["agrees_with_constant"] = bool(out["sign_implied"] == AXIS_SIGN_CONVENTION)
    return out


def scramble_corridor(corridor: Corridor, seed: int = 42) -> Corridor:
    """Permute the Doppler samples in time, keeping their value distribution.

    This breaks the monotone S shape while leaving the total swing and every
    individual frequency value untouched. It is the control time reversal cannot
    be, because A3 showed a Doppler curve is near odd-symmetric about closest
    approach and a reversed curve therefore still fits.
    """
    rng = np.random.default_rng(seed)
    vals = np.asarray(corridor.doppler_hz, dtype=float).copy()
    rng.shuffle(vals)
    return Corridor(
        fracs=list(corridor.fracs),
        doppler_hz=[float(v) for v in vals],
        half_width_hz=corridor.half_width_hz,
        max_elevation_deg=corridor.max_elevation_deg,
        tca_frac=corridor.tca_frac,
        # SPACE-S4: the window's elevation series, carried through unchanged and
        # unreversed. A null is a wrong curve over the SAME observation window, so it
        # must be masked on the same rows. run_null_controls fits these through
        # fit_corridor, which derives the mask from the corridor it is handed, so
        # dropping this would score a control over more rows than the truth.
        elevation_deg=list(corridor.elevation_deg),
    )


def scale_corridor(corridor: Corridor, factor: float) -> Corridor:
    """Scale the Doppler magnitude, holding the curve's shape and sign fixed.

    A scaled curve is exactly as smooth and exactly as monotone as the truth, so
    it isolates whether the predicted swing magnitude is doing work. If a half
    swing and a double swing score as well as the prediction, the measurement is
    detecting a smooth bright path rather than confirming the physics.
    """
    return Corridor(
        fracs=list(corridor.fracs),
        doppler_hz=[float(v) * factor for v in corridor.doppler_hz],
        half_width_hz=corridor.half_width_hz,
        max_elevation_deg=corridor.max_elevation_deg,
        tca_frac=corridor.tca_frac,
        # SPACE-S4: the window's elevation series, carried through unchanged and
        # unreversed. A null is a wrong curve over the SAME observation window, so it
        # must be masked on the same rows. run_null_controls fits these through
        # fit_corridor, which derives the mask from the corridor it is handed, so
        # dropping this would score a control over more rows than the truth.
        elevation_deg=list(corridor.elevation_deg),
    )


def reverse_corridor(corridor: Corridor) -> Corridor:
    """Reverse the Doppler samples in time, holding the fracs grid fixed.

    For a curve that is odd-symmetric about closest approach this is the sign
    flip, which makes it the strongest available null and the only control that
    tests the frequency axis sign directly. Shape, smoothness, swing and value
    distribution are all preserved exactly; only the direction changes.
    """
    return Corridor(
        fracs=list(corridor.fracs),
        doppler_hz=[float(v) for v in reversed(list(corridor.doppler_hz))],
        half_width_hz=corridor.half_width_hz,
        max_elevation_deg=corridor.max_elevation_deg,
        tca_frac=corridor.tca_frac,
        # SPACE-S4: the window's elevation series, carried through unchanged and
        # unreversed. A null is a wrong curve over the SAME observation window, so it
        # must be masked on the same rows. run_null_controls fits these through
        # fit_corridor, which derives the mask from the corridor it is handed, so
        # dropping this would score a control over more rows than the truth.
        elevation_deg=list(corridor.elevation_deg),
    )


def odd_symmetry_residual_frac(corridor: Corridor) -> float | None:
    """max |D(f) + D(1-f)| over the pass, as a fraction of the swing.

    The reversal control is only the sign flip to the extent that the curve is
    odd-symmetric about closest approach, so the degree of that symmetry is a
    measured quantity, not a standing assumption. Returns None for a corridor
    with no swing, where the ratio is undefined rather than zero.
    """
    d = np.asarray(corridor.doppler_hz, dtype=float)
    if d.size < 2:
        return None
    swing = float(np.ptp(d))
    if swing <= 0.0:
        return None
    resid = float(np.abs(d + d[::-1]).max())
    return resid / swing


def flatten_corridor(corridor: Corridor) -> Corridor:
    """Zero the Doppler, leaving a vertical line free to translate.

    This is the corrected hypothesis expressed as a null for the uncorrected
    one. A trace that scores as well against a flat line as against the curve
    carries no Doppler information.
    """
    return Corridor(
        fracs=list(corridor.fracs),
        doppler_hz=[0.0 for _ in corridor.doppler_hz],
        half_width_hz=corridor.half_width_hz,
        max_elevation_deg=corridor.max_elevation_deg,
        tca_frac=corridor.tca_frac,
        # SPACE-S4: the window's elevation series, carried through unchanged and
        # unreversed. A null is a wrong curve over the SAME observation window, so it
        # must be masked on the same rows. run_null_controls fits these through
        # fit_corridor, which derives the mask from the corridor it is handed, so
        # dropping this would score a control over more rows than the truth.
        elevation_deg=list(corridor.elevation_deg),
    )


def run_null_controls(
    zs: np.ndarray,
    corridor: Corridor,
    corridor_type: str,
    hz_per_px: float,
    centre_px: float,
    rx_freq_hz: float,
    obs_id: int | None = None,
    donor_corridor: Corridor | None = None,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> list[NullControlResult]:
    """Fit deliberately wrong corridors under identical rules.

    The true corridor's coverage only means something beside these. If a
    scrambled curve or a flat line covers the trace as well, the corridor's hit
    is not evidence that the physics predicted anything.
    """
    controls: list[tuple[str, str, Corridor]] = [
        (
            "scrambled",
            "Doppler samples permuted in time, same values and same total swing, "
            "monotone shape destroyed. Immune to the odd-symmetry problem that "
            "makes time reversal a weak null.",
            scramble_corridor(corridor, thresholds.seed),
        ),
    ]

    # The flat null only means something against an uncorrected corridor. A
    # corrected corridor is already near-vertical, so zeroing its Doppler
    # reproduces almost the same path and the control ties the truth by
    # construction. Measured before this guard: obs 14745602, a CORRECTED pass,
    # scored coverage 1.000 for both the true corridor and the flat null, which
    # reads as "the physics has no discriminating power" and is really "the
    # control was the same corridor".
    if corridor_type.startswith("uncorrected"):
        controls.append((
            "flat",
            "Zero Doppler, a vertical line free to translate. Tests whether the "
            "curve's shape is doing any work. Only applied to uncorrected "
            "corridors, because a corrected corridor is already near-vertical and "
            "this control would duplicate it.",
            flatten_corridor(corridor),
        ))
    if donor_corridor is not None:
        controls.append((
            "mismatched",
            "A different observation's pass geometry, so a real curve of the "
            "wrong shape and swing for this image.",
            Corridor(
                fracs=list(donor_corridor.fracs),
                doppler_hz=list(donor_corridor.doppler_hz),
                half_width_hz=corridor.half_width_hz,
                max_elevation_deg=donor_corridor.max_elevation_deg,
                tca_frac=donor_corridor.tca_frac,
                # THIS window's elevation, not the donor's. The control borrows the
                # donor's curve shape; the rows that can hold a trace belong to the
                # image being scored.
                elevation_deg=list(corridor.elevation_deg),
            ),
        ))

    out: list[NullControlResult] = []
    for name, rationale, c in controls:
        out.append(NullControlResult(
            name=name,
            rationale=rationale,
            fit=fit_corridor(
                zs,
                c,
                f"{corridor_type}:{name}",
                hz_per_px,
                centre_px,
                rx_freq_hz,
                obs_id=obs_id,
                thresholds=thresholds,
            ),
        ))
    return out
