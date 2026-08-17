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
uncorrected traces sitting 14.0, 2.4 and 1.8 kHz off the predicted curve. At
400 MHz, 14 kHz is 35 parts per million, which is an ordinary figure for a
cubesat oscillator, and the SatNOGS transmitter frequency a station tunes to is
community-maintained and can be stale. So a constant frequency offset has to be
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

Time reversal is deliberately **not** used as a control. A3 established that a
Doppler curve is near odd-symmetric about closest approach, so reversing time
and flipping the frequency sign are errors that cancel and score well. A
reversed curve is a weak null for exactly the reason A3 documented. The
controls used instead break the monotone S shape while preserving the value
distribution, or borrow a genuinely different pass geometry.

All thresholds are module constants, fixed before any observation was scored,
and stated in ``THRESHOLD_RATIONALE`` so a reader can see they were not tuned to
produce a pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pipeline.tracetriage.physics import (
    AXIS_SIGN_CONVENTION,
    Corridor,
    corridor_columns,
)

__all__ = [
    "CorridorFit",
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
    # discriminating against its nulls.
    p_value_max: float = 0.05

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


def path_score(zs: np.ndarray, cols: np.ndarray, min_valid: float = 0.8) -> float:
    """Mean normalised intensity along one path through the image.

    NaN when the path leaves the plot for more than 20 percent of the pass,
    because a shorter path is a noisier statistic and would win a scan for the
    wrong reason.
    """
    rows = np.arange(zs.shape[0])
    valid = (cols >= 0) & (cols < zs.shape[1])
    if valid.mean() < min_valid:
        return float("nan")
    return float(zs[rows[valid], cols[valid]].mean())


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

    The estimator is the same matched filter A3 used, so the numbers stay
    comparable. The difference is the search range: bounded here, unbounded
    there.
    """
    bound_hz = thresholds.offset_ppm_limit * rx_freq_hz / 1e6
    bound_px = int(math.floor(bound_hz / hz_per_px))
    smoothed = smooth_columns(zs, thresholds.filter_width)
    origin = centre_px - EDGE_MARGIN_PX

    best_sigma, best_off_px = _best_over_offsets(
        smoothed, zs, corridor, hz_per_px, origin, bound_px
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


def _pixel_sigma_scale(zs: np.ndarray) -> tuple[float, float]:
    finite = zs[np.isfinite(zs)]
    baseline = float(np.median(finite))
    spread = float(np.median(np.abs(finite - baseline)) * 1.4826) or 1e-9
    return baseline, spread


def _best_over_offsets(
    smoothed: np.ndarray,
    zs: np.ndarray,
    corridor: Corridor,
    hz_per_px: float,
    origin: float,
    bound_px: int,
) -> tuple[float, int | None]:
    """Best path sigma over every whole-pixel offset inside the bound.

    The base columns are computed once and shifted in column space, which is
    equivalent to re-calling ``corridor_columns`` per offset and about two orders
    of magnitude cheaper. That speed is what makes a 200-sample null
    distribution affordable per observation.
    """
    n_rows = zs.shape[0]
    base = _base_columns(corridor, hz_per_px, origin, n_rows)
    baseline, spread = _pixel_sigma_scale(zs)

    best_sigma = -np.inf
    best_off_px: int | None = None
    for off_px in range(-bound_px, bound_px + 1):
        cols = np.rint(base + off_px).astype(int)
        s = path_score(smoothed, cols)
        if math.isnan(s):
            continue
        sigma = (s - baseline) / spread
        if sigma > best_sigma:
            best_sigma = sigma
            best_off_px = off_px
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
    discriminates: bool | None = None

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
            "discriminates": self.discriminates,
        }


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
    bound_hz = thresholds.offset_ppm_limit * rx_freq_hz / 1e6
    bound_px = int(math.floor(bound_hz / hz_per_px))
    smoothed = smooth_columns(zs, thresholds.filter_width)
    origin = centre_px - EDGE_MARGIN_PX

    true_sigma, true_off = _best_over_offsets(
        smoothed, zs, corridor, hz_per_px, origin, bound_px
    )
    if true_off is None:
        return NullCalibration(0, None, [], None, None, None, None, None)

    def _empty(sig: float | None) -> NullCalibration:
        return NullCalibration(
            n_nulls=0, true_sigma=sig, null_sigmas=[], null_median=None,
            null_p95=None, null_max=None, n_at_least=None, p_value=None,
            margin_over_best_null=None,
        )

    span = float(np.ptp(np.asarray(corridor.doppler_hz, dtype=float)))
    if span <= 0.0:
        # A flat corridor has no shape to scramble, so every null reproduces it
        # and the comparison is vacuous by construction rather than informative.
        # Measured: on the four CORRECTED observations the corrected corridor is
        # identically 0 Hz across the whole pass, and true and null sigmas agreed
        # to every decimal place. physics.py sets corrected.doppler_hz to zeros
        # unconditionally, so this branch only ever catches corrected corridors.
        return _empty(float(true_sigma))

    if span < thresholds.min_swing_hz:
        # A small swing cannot distinguish one shape from another: a permutation
        # of nearly-equal values is nearly the same path, so truth and null both
        # collapse toward noise and a p-value can come out significant on pixel
        # quantisation alone. A3 refuses a verdict below the same 3 kHz for the
        # same reason. Only `span > 0` was checked before, which let a grazing
        # low-elevation pass through as testable.
        return _empty(float(true_sigma))

    sigmas: list[float] = []
    for i in range(thresholds.n_nulls):
        null_c = scramble_corridor(corridor, thresholds.seed + i)
        s, off = _best_over_offsets(
            smoothed, zs, null_c, hz_per_px, origin, bound_px
        )
        if off is not None and math.isfinite(s):
            sigmas.append(float(s))

    if not sigmas:
        return _empty(float(true_sigma))

    # Scaled-swing controls hold the curve's smoothness and its sign structure
    # fixed and change only the magnitude of the predicted Doppler. A test that
    # any smooth path would win scores these as highly as the truth. A test that
    # the predicted swing itself is right does not.
    scaled: dict[str, float] = {}
    for factor in thresholds.swing_scale_factors:
        s, off = _best_over_offsets(
            smoothed, zs, scale_corridor(corridor, factor),
            hz_per_px, origin, bound_px,
        )
        if off is not None and math.isfinite(s):
            scaled[f"{factor:g}x"] = float(s)

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

    return NullCalibration(
        n_nulls=len(arr),
        true_sigma=float(true_sigma),
        null_sigmas=sigmas,
        null_median=float(np.median(arr)),
        null_p95=float(np.percentile(arr, 95)),
        null_max=null_max,
        n_at_least=at_least,
        p_value=float(p_value),
        margin_over_best_null=float(true_sigma - null_max),
        scaled_swing_sigmas=scaled,
        beats_scaled_swing=beats_scaled,
        offset_at_bound=at_bound,
        corridor_span_hz=span,
        discriminates=bool(
            p_value <= thresholds.p_value_max
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

    rows_out: list[int] = []
    resid_out: list[float] = []
    for r in range(n_rows):
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
    detect_frac = len(rows) / n_rows if n_rows else 0.0

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
    )


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
