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

import math

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
    measure_residuals,
    px_to_offset_hz,
    scale_corridor,
    scramble_corridor,
)
from pipeline.tracetriage.physics import (
    AXIS_SIGN_CONVENTION,
    Corridor,
    corridor_columns,
)

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
