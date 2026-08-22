"""Tests for the gate-3 corridor fit.

The unit these replace, A7, shipped no tests at all, and its corridor check was
``trace_half_width_hz < half_w`` where both sides were constants. Nothing in a
suite can fail when a check cannot fail, so the tests that matter most here are
the falsifiability ones: a trace deliberately placed outside the corridor has to
come back as a miss, and a curve scrambled out of shape has to score below the
truth. Everything is synthetic, so no image, no network and no snapshot is
needed.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from pipeline.tracetriage.corridor_fit import (
    DEFAULT_THRESHOLDS,
    EDGE_MARGIN_PX,
    GateThresholds,
    calibrate_against_nulls,
    fit_corridor,
    fit_offset,
    flatten_corridor,
    invert_corridor,
    measure_axis_sign,
    measure_residuals,
    odd_symmetry_residual_frac,
    path_score,
    px_to_offset_hz,
    reverse_corridor,
    scale_corridor,
    scramble_corridor,
)
from pipeline.tracetriage.physics import (
    AXIS_SIGN_CONVENTION,
    AXIS_SIGN_MEASURABLE_RATIO,
    Corridor,
    corridor_columns,
    visible_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

N_ROWS = 400
N_COLS = 300
HZ_PER_PX = 100.0
CENTRE_PX = 150.0 + EDGE_MARGIN_PX      # so origin inside zs lands at 150
RX_FREQ_HZ = 400_000_000.0


def s_curve(swing_hz: float = 8_000.0, n: int = 64) -> Corridor:
    """A monotone descending Doppler curve, the shape a real pass produces."""
    fracs = [i / (n - 1) for i in range(n)]
    # cos over the pass gives the classic S: steep through closest approach.
    doppler = [swing_hz * math.cos(math.pi * f) for f in fracs]
    return Corridor(
        fracs=fracs,
        doppler_hz=doppler,
        half_width_hz=2_000.0,
        max_elevation_deg=45.0,
        tca_frac=0.5,
    )


def paint(
    corridor: Corridor,
    offset_hz: float = 0.0,
    amplitude: float = 30.0,
    width_px: int = 3,
    seed: int = 7,
) -> np.ndarray:
    """Build a noisy z array with a bright trace along the corridor."""
    rng = np.random.default_rng(seed)
    zs = rng.normal(0.0, 1.0, size=(N_ROWS, N_COLS)).astype(np.float32)
    cols = corridor_columns(
        corridor,
        hz_per_px=HZ_PER_PX,
        centre_px=CENTRE_PX - EDGE_MARGIN_PX,
        image_height=N_ROWS,
        freq_offset_hz=offset_hz,
    )
    half = width_px // 2
    for r in range(N_ROWS):
        c = int(round(cols[r]))
        for d in range(-half, half + 1):
            cc = c + d
            if 0 <= cc < N_COLS:
                zs[r, cc] += amplitude
    return zs


# ---------------------------------------------------------------------------
# The sign convention, which is where the first version of this module broke
# ---------------------------------------------------------------------------


def test_px_to_offset_hz_round_trips_through_corridor_columns():
    """A column shift converted to Hz must reproduce that same column shift.

    fit_offset searches in column space and reports Hz. If the conversion drops
    AXIS_SIGN_CONVENTION, the offset is re-applied to the opposite side of the
    axis. That defect displaced the curve by twice the fitted offset and detected
    nothing, while every intermediate number still looked plausible.
    """
    c = s_curve()
    base = corridor_columns(
        c, hz_per_px=HZ_PER_PX, centre_px=100.0, image_height=N_ROWS,
        freq_offset_hz=0.0,
    )
    for off_px in (-40, -7, 3, 25):
        off_hz = px_to_offset_hz(off_px, HZ_PER_PX)
        shifted = corridor_columns(
            c, hz_per_px=HZ_PER_PX, centre_px=100.0, image_height=N_ROWS,
            freq_offset_hz=off_hz,
        )
        assert np.allclose(shifted - base, off_px), (
            f"offset of {off_px} px round-tripped to {shifted[0] - base[0]:.2f} px"
        )


def test_offset_conversion_is_not_the_naive_product():
    """Guard the sign explicitly, so a well-meaning simplification fails here."""
    assert AXIS_SIGN_CONVENTION == -1
    assert px_to_offset_hz(10, HZ_PER_PX) == pytest.approx(-1000.0)


# ---------------------------------------------------------------------------
# Falsifiability: the property A7's check did not have
# ---------------------------------------------------------------------------


def test_trace_on_the_curve_is_a_hit():
    c = s_curve()
    zs = paint(c, offset_hz=0.0)
    fit = fit_corridor(zs, c, "uncorrected", HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert fit.degraded is None
    assert fit.corridor_hit is True
    assert fit.coverage == pytest.approx(1.0, abs=0.05)


def test_trace_far_outside_the_corridor_is_a_miss():
    """The test A7 could not fail.

    The trace is painted 8 kHz off the curve, four times the 2 kHz corridor
    half-width, and inside the 50 ppm offset bound the fit cannot follow it far
    enough to call it contained.
    """
    c = s_curve()
    # Paint the trace displaced, then measure residuals against the UNSHIFTED
    # curve, which is what a wrong corridor placement looks like.
    zs = paint(c, offset_hz=px_to_offset_hz(80, HZ_PER_PX))
    rows, resid = measure_residuals(
        zs, c, HZ_PER_PX, CENTRE_PX, offset_hz=0.0,
    )

    # Two outcomes are honest here and one is not. Either nothing was detected
    # inside the window, or what was detected sits outside the corridor. What
    # must never happen is a confident containment claim, so the assertion is
    # written against that rather than against whichever branch happens to run.
    # An earlier version of this test ended in a bare `assert True` on the
    # no-detection branch, which is the branch this data actually takes, so it
    # asserted nothing and passed against A7's constant-residual defect.
    covered = (
        0.0 if len(rows) == 0
        else float((np.abs(resid) <= c.half_width_hz).mean())
    )
    assert covered < DEFAULT_THRESHOLDS.coverage_threshold, (
        f"a trace 8 kHz off a 2 kHz corridor reported {covered:.2f} coverage"
    )

    # And the same image, measured against the correctly placed curve, is a hit.
    # Without this pair the test above could pass by never detecting anything.
    planted = px_to_offset_hz(80, HZ_PER_PX)
    rows_ok, resid_ok = measure_residuals(
        zs, c, HZ_PER_PX, CENTRE_PX, offset_hz=planted,
    )
    assert len(rows_ok) > 0, "the planted trace was not detectable at all"
    assert float((np.abs(resid_ok) <= c.half_width_hz).mean()) > 0.9


def test_coverage_falls_as_the_trace_moves_off_the_curve():
    """Coverage has to respond to position. A constant cannot do this."""
    c = s_curve()
    seen: list[float] = []
    for off_px in (0, 12, 24, 40):
        zs = paint(c, offset_hz=px_to_offset_hz(off_px, HZ_PER_PX))
        _, resid = measure_residuals(zs, c, HZ_PER_PX, CENTRE_PX, offset_hz=0.0)
        if len(resid) == 0:
            seen.append(0.0)
            continue
        seen.append(float((np.abs(resid) <= c.half_width_hz).mean()))
    assert seen[0] > seen[-1], f"coverage did not fall with displacement: {seen}"


# ---------------------------------------------------------------------------
# The bounded offset fit
# ---------------------------------------------------------------------------


def test_fit_recovers_a_planted_offset():
    c = s_curve()
    planted_px = 30
    planted_hz = px_to_offset_hz(planted_px, HZ_PER_PX)
    zs = paint(c, offset_hz=planted_hz)
    got_hz, sigma, at_bound, bound_hz = fit_offset(
        zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
    )
    assert got_hz is not None
    assert got_hz == pytest.approx(planted_hz, abs=2 * HZ_PER_PX)
    assert not at_bound
    assert sigma is not None and sigma > 0


def test_offset_bound_is_ppm_of_the_downlink_and_scales_with_band():
    """A Hz constant tuned at 400 MHz is far too loose at 137 MHz."""
    c = s_curve()
    zs = paint(c)
    _, _, _, bound_400 = fit_offset(zs, c, HZ_PER_PX, CENTRE_PX, 400e6)
    _, _, _, bound_137 = fit_offset(zs, c, HZ_PER_PX, CENTRE_PX, 137e6)
    assert bound_400 == pytest.approx(50.0 * 400e6 / 1e6)
    assert bound_137 == pytest.approx(50.0 * 137e6 / 1e6)
    assert bound_137 < bound_400


def test_offset_beyond_the_bound_is_not_chased():
    """A trace outside the physical bound must not be captured by sliding."""
    c = s_curve()
    # 50 ppm of 400 MHz is 20 kHz, which is 200 px at 100 Hz/px. Plant 400 px.
    zs = paint(c, offset_hz=px_to_offset_hz(400, HZ_PER_PX))
    got_hz, _, at_bound, bound_hz = fit_offset(
        zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
    )
    if got_hz is not None:
        assert abs(got_hz) <= bound_hz + HZ_PER_PX


# ---------------------------------------------------------------------------
# Null calibration
# ---------------------------------------------------------------------------


def test_true_curve_beats_scrambled_nulls():
    c = s_curve()
    zs = paint(c, offset_hz=0.0)
    cal = calibrate_against_nulls(
        zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
        thresholds=GateThresholds(n_nulls=40),
    )
    assert cal.true_sigma is not None
    assert cal.null_max is not None
    assert cal.true_sigma > cal.null_max
    assert cal.n_at_least == 0
    assert cal.discriminates is True


def test_noise_only_image_does_not_discriminate():
    """No trace means no pass. The gate must not reward an empty image."""
    rng = np.random.default_rng(3)
    zs = rng.normal(0.0, 1.0, size=(N_ROWS, N_COLS)).astype(np.float32)
    cal = calibrate_against_nulls(
        zs, s_curve(), HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
        thresholds=GateThresholds(n_nulls=40),
    )
    assert cal.discriminates is False


def test_scaled_swing_scores_below_the_true_swing():
    """Separates "the right swing" from "any smooth bright path"."""
    c = s_curve()
    zs = paint(c, offset_hz=0.0)
    cal = calibrate_against_nulls(
        zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
        thresholds=GateThresholds(n_nulls=20),
    )
    assert cal.scaled_swing_sigmas
    assert cal.beats_scaled_swing is True
    for name, v in cal.scaled_swing_sigmas.items():
        assert cal.true_sigma > v, f"scaled swing {name} matched the true swing"


def test_flat_corridor_is_reported_as_unscorable_not_as_a_pass():
    """A corrected corridor is identically 0 Hz, so it predicts no shape.

    Every null built by permuting zeros reproduces the corridor exactly, so the
    comparison is vacuous. It must come back with no p-value rather than a
    perfect one, because a tie between truth and null is the signature of a
    control that is the truth.
    """
    c = flatten_corridor(s_curve())
    assert max(abs(v) for v in c.doppler_hz) == 0.0
    zs = paint(s_curve(), offset_hz=0.0)
    cal = calibrate_against_nulls(zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert cal.p_value is None
    assert cal.discriminates is None
    assert cal.n_nulls == 0


def test_scramble_preserves_values_and_destroys_order():
    c = s_curve()
    s = scramble_corridor(c, seed=1)
    assert sorted(s.doppler_hz) == pytest.approx(sorted(c.doppler_hz))
    assert s.doppler_hz != c.doppler_hz
    assert s.half_width_hz == c.half_width_hz


def test_scramble_is_deterministic_for_a_seed():
    a = scramble_corridor(s_curve(), seed=11)
    b = scramble_corridor(s_curve(), seed=11)
    assert a.doppler_hz == b.doppler_hz


def test_scale_preserves_shape_and_changes_magnitude():
    c = s_curve()
    d = scale_corridor(c, 2.0)
    assert np.allclose(np.asarray(d.doppler_hz), 2.0 * np.asarray(c.doppler_hz))
    # Monotone structure is untouched, so smoothness is held fixed.
    assert np.all(np.sign(np.diff(d.doppler_hz)) == np.sign(np.diff(c.doppler_hz)))


# ---------------------------------------------------------------------------
# Degraded states stay distinct from failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"corridor": None}, "NO_CORRIDOR"),
        ({"hz_per_px": None}, "NO_HZ_PER_PX"),
        ({"centre_px": None}, "NO_CENTRE_PX"),
        ({"rx_freq_hz": None}, "NO_RX_FREQ"),
    ],
)
def test_missing_inputs_are_named_degraded_states(kwargs, expected):
    """Never a False corridor_hit. "Could not measure" is not "measured a miss"."""
    c = s_curve()
    zs = paint(c)
    args = {
        "corridor": c, "hz_per_px": HZ_PER_PX,
        "centre_px": CENTRE_PX, "rx_freq_hz": RX_FREQ_HZ,
    }
    args.update(kwargs)
    fit = fit_corridor(
        zs,
        args["corridor"],
        "uncorrected",
        args["hz_per_px"],
        args["centre_px"],
        args["rx_freq_hz"],
    )
    assert fit.degraded == expected
    assert fit.corridor_hit is None


def test_tiny_image_is_degraded():
    fit = fit_corridor(
        np.zeros((4, 4), dtype=np.float32), s_curve(), "uncorrected",
        HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
    )
    assert fit.degraded == "IMAGE_TOO_SMALL"


def test_small_swing_is_not_testable():
    """A tiny swing cannot distinguish shapes, so it must not be scored.

    Permuting nearly-equal values gives nearly the same path, so truth and null
    both collapse toward noise and a p-value can turn significant on pixel
    quantisation alone. A3 refuses a verdict below the same 3 kHz. Only
    ``span > 0`` was checked before this guard, which would have let a grazing
    low-elevation pass through as testable.
    """
    tiny = s_curve(swing_hz=400.0)          # 800 Hz peak to peak, under 3 kHz
    zs = paint(tiny, offset_hz=0.0)
    cal = calibrate_against_nulls(
        zs, tiny, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
        thresholds=GateThresholds(n_nulls=20),
    )
    assert cal.p_value is None
    assert cal.discriminates is None


def test_swing_just_above_the_floor_is_testable():
    """The floor must not exclude a genuine pass, so pin both sides of it."""
    ok = s_curve(swing_hz=2_000.0)          # 4 kHz peak to peak, over 3 kHz
    zs = paint(ok, offset_hz=0.0)
    cal = calibrate_against_nulls(
        zs, ok, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
        thresholds=GateThresholds(n_nulls=20),
    )
    assert cal.p_value is not None
    assert cal.discriminates is True


def test_a_fit_that_saturates_its_bound_does_not_discriminate():
    """A saturated fit may not have found the optimum, so it is excluded.

    ``offset_at_bound`` was computed and stored but consulted nowhere, which made
    the choice silent.

    Saturation has to be constructed rather than assumed. A tight bound alone
    does not force it: the search takes the argmax inside its window, and with no
    signal in reach that argmax lands on interior noise, not on the edge. So the
    trace is planted just OUTSIDE the bound, close enough that the smoothed
    kernel at the edge still touches it, which makes the edge the genuine
    optimum.
    """
    c = s_curve()
    tight = GateThresholds(n_nulls=20, offset_ppm_limit=1.0)
    bound_px = int((tight.offset_ppm_limit * RX_FREQ_HZ / 1e6) / HZ_PER_PX)
    zs = paint(c, offset_hz=px_to_offset_hz(bound_px + 2, HZ_PER_PX))
    cal = calibrate_against_nulls(
        zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ, thresholds=tight,
    )
    assert cal.offset_at_bound is True, (
        f"expected the fit to saturate a {bound_px} px bound"
    )
    assert cal.discriminates is False


def test_a3_offset_relates_by_exactly_minus_one_not_by_identity():
    """A3's stored offset and ours differ by a fixed factor of -1, by construction.

    A3's ``curved_offset_hz`` is a raw column-shift-to-Hz conversion with no sign
    compensation. Ours is the ``freq_offset_hz`` that ``corridor_columns``
    expects, so it carries ``AXIS_SIGN_CONVENTION``. The magnitudes agreeing to
    six significant figures is a real cross-check between two separately written
    estimators, but the numbers are never equal including sign, and describing
    them as reproducing each other invites someone to "fix" one of them.
    """
    for off_px in (5, -17, 113):
        a3_style = off_px * HZ_PER_PX
        ours = px_to_offset_hz(off_px, HZ_PER_PX)
        assert ours == pytest.approx(-a3_style)
        assert abs(ours) == pytest.approx(abs(a3_style))


def test_thresholds_are_the_documented_values():
    """These numbers are published, so a silent edit has to fail a test."""
    t = DEFAULT_THRESHOLDS
    assert t.z_min == 4.0
    assert t.min_detect_frac == 0.30
    assert t.coverage_threshold == 0.70
    assert t.offset_ppm_limit == 50.0
    assert t.n_nulls == 200
    assert t.p_value_max == 0.05
    assert t.margin_null_sd_min == 5.0
    assert t.seed == 42
    assert t.swing_scale_factors == (0.25, 0.5, 2.0, 4.0)
    assert t.min_swing_hz == 3_000.0
    assert t.exclude_at_bound is True


class TestMadFloor:
    """The divisor floor in ``normalised_rows``.

    A row with no luminance variation has MAD exactly 0. The floor used to be 1e-6,
    which looks like a division-by-zero guard and is not one: it multiplied a flat
    row's deviations by a million, and the matched filter then reported sigma up to
    8.6e6 on 14 of 716 decisive observations. Eight million in units of the null
    spread is not an overwhelming detection; it is a row with no spread.
    """

    def _crop(self, w: int, h: int):
        from pipeline.tracetriage.waterfall import Box

        return Box(x0=0, y0=0, x1=w, y1=h)

    def test_a_flat_row_normalises_to_zero_not_to_a_million(self) -> None:
        from pipeline.tracetriage.corridor_fit import EDGE_MARGIN_PX, normalised_rows

        h, w = 20, 40
        rgb = np.zeros((h, w, 3), dtype=np.uint8)
        rgb[:] = 100  # every row perfectly flat
        zs = normalised_rows(rgb, self._crop(w, h))
        assert zs.shape == (h - 2 * EDGE_MARGIN_PX, w - 2 * EDGE_MARGIN_PX)
        assert np.abs(zs).max() == 0.0, (
            f"a flat image must normalise to exactly zero, got max |z| = {np.abs(zs).max()}"
        )

    def test_a_row_with_variation_is_unaffected_by_the_floor(self) -> None:
        """The safety argument for the change.

        Measured on the snapshot, a row's MAD is either 0 or at least 2.471, so a floor
        of 1.0 sits inside that gap and cannot alter any row that has variation. This
        checks the arithmetic directly: with MAD well above the floor, the z-scores are
        what the unfloored formula gives.
        """
        from pipeline.tracetriage.corridor_fit import MAD_FLOOR, normalised_rows

        h, w = 20, 40
        rng = np.random.default_rng(0)
        lum = rng.integers(40, 220, size=(h, w)).astype(np.uint8)
        rgb = np.repeat(lum[:, :, None], 3, axis=2)
        zs = normalised_rows(rgb, self._crop(w, h))

        inner = lum[4:-4, 4:-4].astype(np.float32)
        med = np.median(inner, axis=1, keepdims=True)
        mad = np.median(np.abs(inner - med), axis=1, keepdims=True) * 1.4826
        assert mad.min() > MAD_FLOOR, "test data must exceed the floor for this to mean anything"
        assert np.allclose(zs, (inner - med) / mad), (
            "the floor must be inert on rows that have variation"
        )

    def test_the_floor_sits_inside_the_measured_gap(self) -> None:
        """0 < MAD_FLOOR < 2.471, the smallest non-zero MAD 8-bit luminance can give."""
        from pipeline.tracetriage.corridor_fit import MAD_FLOOR

        smallest_nonzero_mad = (5.0 / 3.0) * 1.4826  # one quantisation step, scaled
        assert 0.0 < MAD_FLOOR < smallest_nonzero_mad

    def test_flat_rows_are_counted_and_reported(self) -> None:
        from pipeline.tracetriage.corridor_fit import flat_row_fraction

        h, w = 20, 40
        rng = np.random.default_rng(1)
        lum = rng.integers(40, 220, size=(h, w)).astype(np.uint8)
        lum[6:9, :] = 77  # three flat rows inside the crop
        rgb = np.repeat(lum[:, :, None], 3, axis=2)
        stats = flat_row_fraction(rgb, self._crop(w, h))
        assert stats["n_flat_rows"] == 3
        assert stats["n_rows"] == h - 8
        assert stats["flat_row_frac"] == pytest.approx(3 / (h - 8))
        assert stats["min_row_mad"] == 0.0


# ---------------------------------------------------------------------------
# SPACE-B4 and SPACE-B5: the criteria that separate the physics from its own
# sign errors, and which were computed and then left out of the decision.
# ---------------------------------------------------------------------------


class TestWrongSignCorridorsDoNotDiscriminate:
    """A corridor with the frequency axis inverted must not pass gate 3.

    It used to clear the published criterion. The permutation null is weak, so
    scrambled paths collapse into noise around sigma 0.4 to 0.6 and anything smooth
    beats them: measured on the real waterfalls, the inverted corridor reached
    0 of 200 and p = 0.005 on two of the three shipped observations. What separates
    truth from the inversion is the margin over the best null, which was reported and
    not used, and the reversal control, which had been dropped on a false premise.
    """

    def _cal(self, corridor, painted, thresholds=DEFAULT_THRESHOLDS):
        return calibrate_against_nulls(
            painted, corridor, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ, thresholds
        )

    def test_the_true_corridor_clears_the_margin_floor_by_a_wide_margin(self):
        c = s_curve()
        cal = self._cal(c, paint(c))
        assert cal.discriminates is True
        assert cal.null_sigma_sd is not None and cal.null_sigma_sd > 0.0
        assert cal.margin_in_null_sd is not None
        assert cal.margin_in_null_sd >= DEFAULT_THRESHOLDS.margin_null_sd_min, (
            f"true corridor margin is {cal.margin_in_null_sd:.1f} null sd, under the "
            f"{DEFAULT_THRESHOLDS.margin_null_sd_min} floor"
        )

    def test_an_inverted_corridor_does_not_discriminate(self):
        """On the real data this variant reached p = 0.005 and 0 of 200 nulls."""
        c = s_curve()
        painted = paint(c)
        d = [-v for v in c.doppler_hz]
        cal = self._cal(replace(c, doppler_hz=d), painted)
        assert cal.discriminates is False
        assert cal.beats_reversed is False, (
            "the reversal of an inverted corridor is the truth, which outscores it"
        )

    def test_a_time_reversed_corridor_does_not_discriminate(self):
        c = s_curve()
        cal = self._cal(reverse_corridor(c), paint(c))
        assert cal.discriminates is False
        assert cal.beats_reversed is False

    def test_the_true_corridor_beats_its_own_reversal(self):
        c = s_curve()
        cal = self._cal(c, paint(c))
        assert cal.beats_reversed is True
        assert cal.reversed_sigma is not None
        assert cal.true_sigma > cal.reversed_sigma

    def test_a_significant_p_value_alone_no_longer_passes_the_gate(self):
        """Isolate the margin criterion: raise the floor and nothing else.

        The p-value stays at its 1/201 floor while the gate goes to False, which is
        the whole point of the finding. A criterion that never changes the outcome is
        not a criterion.
        """
        c = s_curve()
        painted = paint(c)
        strict = replace(DEFAULT_THRESHOLDS, margin_null_sd_min=1e9)
        cal = self._cal(c, painted, strict)
        assert cal.p_value <= DEFAULT_THRESHOLDS.p_value_max
        assert cal.discriminates is False

    def test_an_unmeasurable_margin_is_not_a_pass(self):
        """One null gives no spread, so the margin has no scale to be measured in.

        Unmeasurable is not a pass. The field reports None rather than a number that
        would read as a measurement.
        """
        c = s_curve()
        thin = replace(DEFAULT_THRESHOLDS, n_nulls=1)
        cal = self._cal(c, paint(c), thin)
        assert cal.null_sigma_sd is None
        assert cal.margin_in_null_sd is None
        assert cal.discriminates is False


class TestOddSymmetryPremise:
    """The reversal control is the sign flip only to the extent the curve is odd.

    That premise was stated in a comment and used to justify dropping the control.
    It is now measured per observation and published in the receipt. On the three
    shipped observations the residual is 0.11, 1.35 and 1.59 percent of swing.
    """

    def test_reversal_of_an_odd_symmetric_curve_equals_the_sign_flip(self):
        c = s_curve()
        rev = reverse_corridor(c)
        flipped = [-v for v in c.doppler_hz]
        assert np.allclose(rev.doppler_hz, flipped, atol=1e-9), (
            "for a curve odd about closest approach, D(1-f) = -D(f), so reversing "
            "time and flipping the sign are the same operation"
        )

    def test_residual_is_near_zero_for_an_odd_curve(self):
        assert odd_symmetry_residual_frac(s_curve()) < 1e-9

    def test_residual_is_large_for_a_curve_that_is_not_odd(self):
        c = s_curve()
        # A monotone ramp is even less odd-symmetric than a real pass: D(f) + D(1-f)
        # is constant and equal to the swing itself.
        ramp = [8_000.0 * f for f in c.fracs]
        resid = odd_symmetry_residual_frac(replace(c, doppler_hz=ramp))
        assert resid is not None and resid > 0.9

    def test_residual_is_none_when_there_is_no_swing(self):
        """Undefined rather than zero: a flat corridor has no swing to divide by."""
        assert odd_symmetry_residual_frac(flatten_corridor(s_curve())) is None

    def test_reversal_preserves_the_value_distribution_exactly(self):
        c = s_curve()
        rev = reverse_corridor(c)
        assert sorted(rev.doppler_hz) == sorted(c.doppler_hz)
        assert rev.fracs == c.fracs
        assert rev.half_width_hz == c.half_width_hz


# ---------------------------------------------------------------------------
# SPACE-S4: a row below the local horizon cannot hold a trace
#
# The scorer used to average every row of the image, including rows where the
# satellite had not risen. Those rows are noise by geometry, not by chance, and
# they entered path_score, rows_detected, the residual percentiles and the
# detect_frac denominator. SkyPlot.tsx already broke its path at negative
# elevation rather than clamping it; the scorer now agrees with the plot.
# ---------------------------------------------------------------------------

BELOW_START_FRAC = 0.25


def s_curve_below_horizon(
    below_frac: float = BELOW_START_FRAC, n: int = 64, floor_deg: float = -8.0
) -> Corridor:
    """An s_curve whose window opens below the station's horizon.

    Deliberately asymmetric: only the START of the pass is below the horizon, so
    a mask applied to the wrong end of the image fails a test rather than passing
    one by symmetry. The start of the pass is the BOTTOM of the waterfall.
    """
    c = s_curve(n=n)
    els: list[float] = []
    for f in c.fracs:
        if f < below_frac:
            els.append(floor_deg * (1.0 - f / below_frac))
        else:
            els.append(45.0 * (f - below_frac) / (1.0 - below_frac))
    return replace(c, elevation_deg=els)


def paint_band(
    corridor: Corridor,
    row_lo: int,
    row_hi: int,
    amplitude: float = 30.0,
    seed: int = 11,
) -> np.ndarray:
    """Noise everywhere, a bright trace on the corridor only inside [lo, hi)."""
    rng = np.random.default_rng(seed)
    zs = rng.normal(0.0, 1.0, size=(N_ROWS, N_COLS)).astype(np.float32)
    cols = corridor_columns(
        corridor, hz_per_px=HZ_PER_PX, centre_px=CENTRE_PX - EDGE_MARGIN_PX,
        image_height=N_ROWS, freq_offset_hz=0.0,
    )
    for r in range(row_lo, row_hi):
        c = int(round(cols[r]))
        for d in (-1, 0, 1):
            if 0 <= c + d < N_COLS:
                zs[r, c + d] += amplitude
    return zs


def _corridor_cols(corridor: Corridor) -> np.ndarray:
    return np.rint(
        corridor_columns(
            corridor, hz_per_px=HZ_PER_PX, centre_px=CENTRE_PX - EDGE_MARGIN_PX,
            image_height=N_ROWS, freq_offset_hz=0.0,
        )
    ).astype(int)


def test_the_horizon_mask_lands_on_the_rows_the_pass_starts_on():
    """Row 0 is the END of the pass, so a late-rising pass masks the BOTTOM rows.

    Two definitions of the row-to-fraction map are two chances to mask the wrong
    end of the image, and an inverted mask is invisible in every summary statistic:
    the count of masked rows comes out identical either way.
    """
    c = s_curve_below_horizon()
    mask = visible_rows(c, N_ROWS)
    hidden = np.flatnonzero(~mask)
    assert hidden.size > 0
    # Contiguous, and at the high-index end of the image.
    assert hidden.max() == N_ROWS - 1, (
        f"the mask reaches row {hidden.max()} of {N_ROWS - 1}, so it is on the "
        "wrong end of the image: the pass starts at the BOTTOM"
    )
    assert np.array_equal(hidden, np.arange(hidden.min(), N_ROWS))
    assert hidden.size == pytest.approx(BELOW_START_FRAC * N_ROWS, abs=2)


def test_a_corridor_without_an_elevation_series_masks_nothing():
    """A missing field must not read as "no signal anywhere".

    Marking every row invisible would be the arithmetically tidy answer and would
    silently zero the whole measurement, so the absent series means "cannot mask"
    and the reported count of masked rows stays zero.
    """
    c = s_curve()
    assert c.elevation_deg == []
    assert visible_rows(c, N_ROWS).all()
    fit = fit_corridor(zs_full := paint(c), c, "uncorrected", HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert fit.degraded is None
    assert fit.rows_masked_below_horizon == 0
    assert fit.detect_frac == pytest.approx(fit.rows_detected / zs_full.shape[0])


def test_path_score_ignores_intensity_below_the_horizon():
    """The defect, measured: brightness on rows that cannot hold a trace scores.

    The trace here is painted ONLY across the below-horizon band, which is what
    an interfering carrier or a hot pixel column looks like. Unmasked, it lifts
    the path score; masked, the path sees only the noise it should.
    """
    c = s_curve_below_horizon()
    mask = visible_rows(c, N_ROWS)
    hidden = np.flatnonzero(~mask)
    zs = paint_band(c, int(hidden.min()), N_ROWS)
    cols = _corridor_cols(c)

    unmasked = path_score(zs, cols)
    masked = path_score(zs, cols, row_mask=mask)
    assert unmasked > 5.0, f"the fixture painted nothing detectable: {unmasked}"
    assert abs(masked) < 0.5, f"masked rows still reach the score: {masked}"
    assert unmasked > 10 * abs(masked)


def test_the_horizon_mask_is_not_charged_as_the_path_leaving_the_plot():
    """min_valid is measured over the masked rows, not the whole image.

    Charging a horizon mask against the same 80 percent budget that catches a
    corridor running off the edge would turn every window that opens low into a
    NaN, which is a way to make a fix look like a regression. The fixture puts the
    only out-of-plot columns on rows that are masked anyway.
    """
    c = s_curve_below_horizon()
    mask = visible_rows(c, N_ROWS)
    zs = paint(c)
    cols = _corridor_cols(c)
    cols[~mask] = -5                      # off the left edge, on masked rows only

    assert math.isnan(path_score(zs, cols)), (
        "the fixture is not exercising the min_valid path"
    )
    scored = path_score(zs, cols, row_mask=mask)
    assert not math.isnan(scored), "a horizon mask was charged as leaving the plot"
    assert scored > 5.0


def test_measure_residuals_does_not_detect_below_the_horizon():
    """A bright row under the horizon is noise, however bright it is."""
    c = s_curve_below_horizon()
    hidden = np.flatnonzero(~visible_rows(c, N_ROWS))
    lo = int(hidden.min())
    zs = paint_band(c, lo, N_ROWS)

    rows, _ = measure_residuals(zs, c, HZ_PER_PX, CENTRE_PX, offset_hz=0.0)
    assert not set(rows.tolist()) & set(hidden.tolist()), (
        "rows below the horizon carry detections"
    )

    # The premise of the test: the same paint IS detectable without the mask, so
    # the assertion above is about the mask and not about the fixture being dim.
    bare = replace(c, elevation_deg=[])
    rows_bare, _ = measure_residuals(zs, bare, HZ_PER_PX, CENTRE_PX, offset_hz=0.0)
    assert set(rows_bare.tolist()) & set(hidden.tolist()), (
        "the fixture painted nothing the detector can find"
    )


def test_detect_frac_is_measured_over_the_rows_that_could_hold_a_trace():
    """The denominator is the visible rows, and the masked count is published.

    Dividing by the image height instead would drive a window that opens low
    towards TRACE_NOT_MEASURABLE for a reason with nothing to do with the trace,
    and there would be no field in the receipt to tell a reader that happened.
    """
    c = s_curve_below_horizon()
    zs = paint(c)
    fit = fit_corridor(zs, c, "uncorrected", HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)

    assert fit.degraded is None
    assert fit.rows_masked_below_horizon > 0
    assert fit.rows_total == N_ROWS
    n_visible = fit.rows_total - fit.rows_masked_below_horizon
    assert fit.detect_frac == pytest.approx(fit.rows_detected / n_visible)
    assert fit.detect_frac > fit.rows_detected / fit.rows_total, (
        "detect_frac still divides by the image height"
    )
    assert "rows_masked_below_horizon" in fit.summary()


def test_a_window_almost_entirely_below_the_horizon_degrades_with_a_name():
    """Too few visible rows is "could not measure", not a detect_frac of 0.02."""
    c = s_curve()
    els = [-20.0] * len(c.fracs)
    els[-1] = 30.0                        # a sliver at the very start of the pass
    fit = fit_corridor(
        paint(c), replace(c, elevation_deg=els), "uncorrected",
        HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ,
    )
    assert fit.degraded == "MOSTLY_BELOW_HORIZON"
    assert fit.corridor_hit is None


def test_every_null_is_scored_on_the_same_rows_as_the_truth():
    """The mask belongs to the window, so truth and nulls share one of them.

    Deriving it per corridor inside the scorer would hand every null the whole
    image, because the null builders carry no Doppler curve of their own making
    and nothing forces them to carry an elevation series either. A margin measured
    over two different row sets is not a margin. This is the fairness property, and
    it cannot be checked by reading the sigmas: both versions produce plausible
    numbers.
    """
    import pipeline.tracetriage.corridor_fit as cf

    c = s_curve_below_horizon()
    zs = paint(c)
    seen: set[bytes] = set()
    real = cf.path_score

    def recording(zs_, cols_, min_valid=0.8, row_mask=None):
        seen.add(b"NONE" if row_mask is None else np.asarray(row_mask).tobytes())
        return real(zs_, cols_, min_valid, row_mask)

    thresholds = replace(DEFAULT_THRESHOLDS, n_nulls=3, offset_ppm_limit=2.0)
    original, cf.path_score = cf.path_score, recording
    try:
        cal = calibrate_against_nulls(
            zs, c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ, thresholds
        )
    finally:
        cf.path_score = original

    assert cal.true_sigma is not None
    assert len(seen) == 1, f"{len(seen)} different row masks were scored"
    only = next(iter(seen))
    assert only != b"NONE", "the nulls were scored with no mask at all"
    assert not np.frombuffer(only, dtype=bool).all(), (
        "the fixture masks nothing, so this test cannot fail"
    )


def test_the_null_builders_carry_the_window_elevation():
    """Same window, different curve: the elevation series survives unchanged."""
    c = s_curve_below_horizon()
    for name, null in (
        ("scrambled", scramble_corridor(c, 1)),
        ("scaled", scale_corridor(c, 2.0)),
        ("reversed", reverse_corridor(c)),
        ("flat", flatten_corridor(c)),
    ):
        assert null.elevation_deg == c.elevation_deg, f"{name} lost the elevation"
        assert null.doppler_hz != [] and len(null.doppler_hz) == len(c.doppler_hz)


def test_the_shipped_gate3_receipt_reports_its_masked_rows():
    """A receipt written by the older scorer cannot pass as current.

    Presence, not a value: the field is zero on every observation the gate scores
    today (all seven decisive windows are above the horizon throughout), and that
    zero is a measurement rather than a default.
    """
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "GATE3_RECEIPT.json").read_text(encoding="utf-8")
    )
    fits = []
    for obs in receipt["observations"]:
        if obs.get("fit"):
            fits.append(obs["fit"])
        for control in obs.get("null_controls") or []:
            if control.get("fit"):
                fits.append(control["fit"])
    assert fits, "the receipt carries no fits, so this test checks nothing"
    for f in fits:
        assert "rows_masked_below_horizon" in f, (
            f"obs {f.get('obs_id')} was scored before the horizon mask existed"
        )
        assert isinstance(f["rows_masked_below_horizon"], int)
        assert 0 <= f["rows_masked_below_horizon"] <= (f["rows_total"] or 0)


# ---------------------------------------------------------------------------
# SPACE-S5: the axis sign is the renderer's property, so it gets re-measured
# ---------------------------------------------------------------------------


def test_measure_axis_sign_recovers_the_shipped_convention():
    """A trace on the corridor confirms the sign the constant asserts."""
    c = s_curve()
    m = measure_axis_sign(paint(c), c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert m["measurable"] is True
    assert m["sign_implied"] == AXIS_SIGN_CONVENTION
    assert m["agrees_with_constant"] is True
    assert m["ratio"] > AXIS_SIGN_MEASURABLE_RATIO
    assert m["not_measurable_reason"] is None


def test_measure_axis_sign_can_disagree_with_the_constant():
    """The property that makes the measurement worth publishing.

    A check that can only confirm is not a check. Here the trace is painted along
    the mirrored curve, which is what a client that flipped its frequency axis
    would produce, and the measurement has to report the other sign rather than
    the constant it was handed.
    """
    c = s_curve()
    m = measure_axis_sign(paint(invert_corridor(c)), c, HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert m["measurable"] is True
    assert m["sign_implied"] == -AXIS_SIGN_CONVENTION
    assert m["agrees_with_constant"] is False


def test_a_flat_corridor_cannot_orient_the_axis():
    """A corrected corridor mirrors onto itself, so its argmax is noise.

    A3 published a per-observation sign for the corrected passes anyway, and it
    came out +1 on two of the four. That is an unmeasurable quantity reported as a
    measurement; this returns a named reason instead.
    """
    c = s_curve()
    m = measure_axis_sign(paint(c), flatten_corridor(c), HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert m["measurable"] is False
    assert m["sign_implied"] is None
    assert m["agrees_with_constant"] is None
    assert "swing" in m["not_measurable_reason"]


def test_an_image_with_no_trace_cannot_orient_the_axis():
    """Two orientations of noise score the same, and a tie is not a measurement."""
    rng = np.random.default_rng(3)
    noise = rng.normal(0.0, 1.0, size=(N_ROWS, N_COLS)).astype(np.float32)
    m = measure_axis_sign(noise, s_curve(), HZ_PER_PX, CENTRE_PX, RX_FREQ_HZ)
    assert m["measurable"] is False
    assert m["not_measurable_reason"]
    assert m["sigma_as_shipped"] is not None, (
        "both orientations must still be reported, so a reader can see the tie"
    )


def test_inverting_a_corridor_changes_only_the_direction():
    """Same swing, same window, opposite sign: the control has to be comparable."""
    c = s_curve_below_horizon()
    inv = invert_corridor(c)
    assert np.ptp(inv.doppler_hz) == pytest.approx(np.ptp(c.doppler_hz))
    assert inv.doppler_hz == [-v for v in c.doppler_hz]
    assert inv.fracs == c.fracs
    assert inv.elevation_deg == c.elevation_deg
    assert inv.half_width_hz == c.half_width_hz

# ---------------------------------------------------------------------------
# SPACE-S8: two sigmas, two normalisations, no conversion between them
# ---------------------------------------------------------------------------


def test_the_receipt_states_that_the_two_sigma_scales_are_not_comparable():
    """The docstring used to claim they were, and the direction can invert.

    A3 normalised per column band; this module normalises against the median and MAD of
    the whole image. On obs 14740031 A3's vertical sigma of 2.83 exceeds this module's
    curved sigma of 2.02, so a reader comparing the artifacts concludes a straight line
    beats the Doppler curve, which is the opposite of what both found.
    """
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "GATE3_RECEIPT.json").read_text(encoding="utf-8")
    )
    ratios = []
    for obs in receipt["observations"]:
        ref = obs["a3_reference"]
        assert "sigma_comparability" in ref, (
            f"obs {obs['obs_id']} publishes two sigma scales and no statement that they "
            "are different statistics"
        )
        assert "Not comparable" in ref["sigma_comparability"]
        if ref["sigma_scale_ratio_to_fit"] is not None:
            ratios.append(ref["sigma_scale_ratio_to_fit"])

    assert len(ratios) >= 7, f"only {len(ratios)} observations carry the ratio"
    assert max(ratios) / min(ratios) > 5.0, (
        "the two sigma scales now differ by a near-constant factor across observations, "
        f"spread {min(ratios):.2f} to {max(ratios):.2f}. If the normalisation was "
        "deliberately made comparable, the comparability statement in corridor_fit.py, "
        "docs/KILL_GATE.md and the receipt has to be rewritten rather than this "
        "threshold relaxed."
    )


def test_the_two_sigmas_in_the_receipt_come_from_where_they_say():
    """The fit sigma and the null calibration's true sigma are one measurement.

    They are the same estimator on the same image, so they must agree exactly. A3's
    numbers sit in a different block for the same reason they carry a warning.
    """
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "GATE3_RECEIPT.json").read_text(encoding="utf-8")
    )
    checked = 0
    for obs in receipt["observations"]:
        fit_sigma = (obs.get("fit") or {}).get("sigma_at_fit")
        true_sigma = (obs.get("null_calibration") or {}).get("true_sigma")
        if fit_sigma is None or true_sigma is None:
            continue
        checked += 1
        assert fit_sigma == pytest.approx(true_sigma, rel=1e-9), (
            f"obs {obs['obs_id']}: the fit sigma and the null calibration's true sigma "
            "disagree, so one of them is not the estimator it claims to be"
        )
    assert checked >= 7


# --------------------------------------------------------------------------------------
# The image-level divisor, which collapsed once the row-level one was fixed.
# --------------------------------------------------------------------------------------


def test_a_mostly_dead_image_has_no_scale_rather_than_a_tiny_one():
    """`spread = ... or 1e-9` turned a vanished denominator into a huge sigma.

    Fixing the row divisor made a dead row normalise to exactly zero, which is right, and
    that pushed the degeneracy here: an image more than half dead has a `zs` more than
    half exact zeros, so its median absolute deviation is exactly 0 and Python's `or`
    swapped in 1e-9. Measured on the first run over E16's pool, obs 14745697 came back at
    sigma 3.09e10 with a null median of 1.57e10.

    A3's three observations have no dead rows, so nothing caught it for the whole life of
    the gate.
    """
    from pipeline.tracetriage.corridor_fit import _pixel_sigma_scale

    zs = np.zeros((100, 200), dtype=np.float32)
    zs[:20] = np.random.default_rng(0).normal(size=(20, 200))

    _, spread_all = _pixel_sigma_scale(zs)
    assert spread_all == 0.0, (
        "80 dead rows out of 100 give an image-wide MAD of exactly zero, and the point "
        "is that this returns it rather than substituting 1e-9"
    )

    live = np.zeros(100, dtype=bool)
    live[:20] = True
    _, spread_live = _pixel_sigma_scale(zs, live)
    assert spread_live > 0.1, (
        "measured over the rows that carry anything, the scale is an ordinary number"
    )


def test_measurable_rows_finds_exactly_the_dead_ones():
    """A dead row is exactly zero across its width, which is arithmetic, not a tolerance."""
    from pipeline.tracetriage.corridor_fit import measurable_rows

    zs = np.zeros((6, 50), dtype=np.float32)
    zs[1, 10] = 0.001
    zs[3] = np.random.default_rng(1).normal(size=50)
    assert measurable_rows(zs).tolist() == [False, True, False, True, False, False]


def test_a_score_and_its_scale_come_from_the_same_rows():
    """The numerator excluded masked rows and the denominator did not.

    `_best_over_offsets` passed `row_mask` to `path_score` and computed the scale over
    the whole image, so the sigma it returned was a ratio of two quantities measured over
    different row sets. With half the image dead and the visible half clean, the two
    differ by orders of magnitude.
    """
    from pipeline.tracetriage.corridor_fit import _pixel_sigma_scale

    rng = np.random.default_rng(2)
    zs = np.zeros((80, 300), dtype=np.float32)
    zs[40:] = rng.normal(size=(40, 300))

    visible = np.zeros(80, dtype=bool)
    visible[40:] = True

    _, whole = _pixel_sigma_scale(zs)
    _, masked = _pixel_sigma_scale(zs, visible)
    assert masked > 0.1
    # At exactly half dead the whole-image MAD is not identically zero, it is a rounding
    # artifact four orders of magnitude below the real scale. That is the point: the
    # sigma it divides is inflated by the same factor, so the failure is graded rather
    # than a clean crash, and a graded failure is the kind nobody notices.
    assert masked / max(whole, 1e-12) > 1000.0, (
        f"the unmasked scale is {whole:.3g} against a real {masked:.3g}. Any sigma "
        f"divided by the first is inflated by their ratio"
    )


def test_an_image_with_no_measurable_row_refuses_instead_of_returning_a_number():
    """No scale means no sigma. NaN reaches the caller's refusal path."""
    import math

    from pipeline.tracetriage.corridor_fit import _best_over_offsets, _pixel_sigma_scale

    zs = np.zeros((60, 200), dtype=np.float32)
    _, spread = _pixel_sigma_scale(zs, np.ones(60, dtype=bool))
    assert spread == 0.0

    from pipeline.tracetriage.physics import Corridor

    corridor = Corridor(
        fracs=[i / 59 for i in range(60)],
        doppler_hz=[1000.0 * math.cos(i / 10) for i in range(60)],
        half_width_hz=500.0,
        elevation_deg=[45.0] * 60,
        max_elevation_deg=45.0,
        tca_frac=0.5,
    )
    sigma, off = _best_over_offsets(
        zs, zs, corridor, 10.0, 100.0, 3, row_mask=np.ones(60, dtype=bool)
    )
    assert off is None
    assert math.isnan(sigma), (
        "a dead image must not come back with a finite sigma of any size"
    )


class TestTheOffsetSweep:
    """The curve the console publishes, and the fit that has to be its peak.

    `_best_over_offsets` used to run its own comparison loop over the offsets. Publishing
    the sweep beside a separately computed fitted offset would be two implementations of
    one quantity, free to drift apart, which is the class of defect this file exists to
    catch. So the sweep is the primitive and the fit is its argmax, and these are the
    properties that says.
    """

    def _scene(self, offset_hz: float = 1_200.0):
        from pipeline.tracetriage.corridor_fit import smooth_columns

        corridor = s_curve()
        zs = paint(corridor, offset_hz=offset_hz)
        return zs, corridor, smooth_columns(zs, DEFAULT_THRESHOLDS.filter_width)

    def test_the_fitted_offset_is_the_peak_of_the_published_sweep(self):
        from pipeline.tracetriage.corridor_fit import _best_over_offsets, offset_sweep

        zs, corridor, smoothed = self._scene()
        origin = N_COLS / 2 - EDGE_MARGIN_PX
        args = (smoothed, zs, corridor, HZ_PER_PX, origin, 60)

        offsets, sigmas = offset_sweep(*args)
        sigma, off = _best_over_offsets(*args)

        assert offsets.size > 0, "the sweep scored nothing, so this test checked nothing"
        peak = int(np.argmax(sigmas))
        assert off == int(offsets[peak]), (
            f"the fit says {off} and the published curve peaks at {offsets[peak]}. "
            "These are the same quantity and must not be able to differ."
        )
        assert sigma == float(sigmas[peak])

    def test_the_sweep_is_a_curve_and_not_a_plateau(self):
        """A detection that did not rise to a peak would not be evidence of anything."""
        from pipeline.tracetriage.corridor_fit import offset_sweep

        zs, corridor, smoothed = self._scene()
        origin = N_COLS / 2 - EDGE_MARGIN_PX
        _, sigmas = offset_sweep(smoothed, zs, corridor, HZ_PER_PX, origin, 60)
        assert float(sigmas.max()) > float(np.median(sigmas)) + 3.0, (
            "the peak does not stand out of its own sweep, so the curve carries no "
            "information about where the trace is"
        )

    def test_the_sweep_covers_the_bound_and_stays_aligned(self):
        """A truncated curve would read as a detection near an edge."""
        from pipeline.tracetriage.corridor_fit import offset_sweep

        zs, corridor, smoothed = self._scene()
        origin = N_COLS / 2 - EDGE_MARGIN_PX
        offsets, sigmas = offset_sweep(smoothed, zs, corridor, HZ_PER_PX, origin, 60)
        assert offsets.size == sigmas.size, "the two arrays fell out of alignment"
        assert offsets.min() >= -60
        assert offsets.max() <= 60
        assert np.all(np.diff(offsets) > 0), "offsets must increase, or a plot lies"

    def test_a_dead_image_produces_no_sweep_rather_than_a_flat_one(self):
        """Zero spread is the divisor collapse this module spent a session on.

        A flat curve of zeros would render as "measured, and nothing is there". No curve
        is the honest output, and it is what reaches the caller's refusal path.
        """
        from pipeline.tracetriage.corridor_fit import _best_over_offsets, offset_sweep

        corridor = s_curve()
        zs = np.zeros((64, N_COLS), dtype=np.float32)
        origin = N_COLS / 2 - EDGE_MARGIN_PX
        offsets, sigmas = offset_sweep(zs, zs, corridor, HZ_PER_PX, origin, 60)
        assert offsets.size == 0
        assert sigmas.size == 0
        sigma, off = _best_over_offsets(zs, zs, corridor, HZ_PER_PX, origin, 60)
        assert off is None
        assert math.isnan(sigma)
