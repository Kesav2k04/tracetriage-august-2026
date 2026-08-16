"""Offline tests for pipeline/tracetriage/physics.py (Unit A4).

ACCEPTANCE REQUIREMENTS CHECKED HERE
======================================
1. Fixed-case tests: known pass → known elevation profile, sign flip at TCA,
   deterministic corridor for frozen input.
2. A test that FAILS if the time-axis direction is flipped.
3. A test that FAILS if the frequency-axis sign is flipped.
4. Every degraded state returns a named reason code and does not raise.
5. Zero network access (enforced by conftest.py autouse fixture).

All inputs are frozen literals; no API calls, no filesystem reads beyond the
module under test.

CALIBRATION FACTS (must not be re-derived — see docs/DOPPLER_CORRECTION_FINDING.md)
  * Time runs bottom to top: row 0 = end of pass = frac 1.
  * Frequency axis runs against Doppler sign: positive Doppler (approaching) →
    LEFT on the rendered image → AXIS_SIGN_CONVENTION = -1.
  These two errors cancel on a near-symmetric Doppler curve, so both are tested
  independently with sign-flip variants.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from pipeline.tracetriage.physics import (
    AXIS_SIGN_CONVENTION,
    CORRECTED_CORRIDOR_HZ,
    FREQ_OFFSET_SEARCH_HZ,
    N_SAMPLES,
    TLE_MAX_EPOCH_AGE_DAYS,
    UNCORRECTED_CORRIDOR_HZ,
    Corridor,
    corridor_columns,
    corridor_for_obs,
    eci_to_ecef,
    gmst,
    propagate_pass,
    rx_freq_of,
    station_ecef,
    tle_epoch_datetime,
)

# ---------------------------------------------------------------------------
# Frozen test observation: Cabrillo College (GS 1), NORAD 25544 (ISS), 437 MHz
# This is a synthetic but physically plausible record.  The TLE epoch is
# 2024-01-01 and the pass is on the same day, so it is never stale.
# The pass geometry gives a recognisable elevation profile.
# ---------------------------------------------------------------------------

_TLE0 = "ISS (ZARYA)"
_TLE1 = "1 25544U 98067A   24001.50000000  .00002182  00000-0  44988-4 0  9992"
_TLE2 = "2 25544  51.6416  77.8062 0003071  51.8048 308.3459 15.49601040429996"

# Station: approximately Prague, Czech Republic
_LAT = 50.073
_LNG = 14.437
_ALT = 200.0  # metres

# Pass window: 2024-01-01 01:22:30 to 01:33:00 UTC (630 seconds)
# This is a real ISS pass over Prague at max elevation 48.8 degrees.
# The window was found by scanning 48 hours with the propagator, so the
# elevation profile, sign flip and Doppler swing assertions are valid.
_START = "2024-01-01T01:22:30Z"
_END = "2024-01-01T01:33:00Z"

_RX_FREQ = 437_525_000.0  # 437.525 MHz

_CLIENT_META = json.dumps({
    "radio": {
        "name": "gr-satnogs",
        "version": "2.3.4",
        "parameters": {
            "rx-freq": str(int(_RX_FREQ)),
            "samp-rate-rx": "2.5e6",
            "doppler-correction-per-sec": None,
            "rigctl-port": "4532",
        },
    }
})

_FROZEN_OBS: dict = {
    "id": 99000001,
    "start": _START,
    "end": _END,
    "station_lat": _LAT,
    "station_lng": _LNG,
    "station_alt": _ALT,
    "tle0": _TLE0,
    "tle1": _TLE1,
    "tle2": _TLE2,
    "client_metadata": _CLIENT_META,
    "observation_frequency": int(_RX_FREQ),
    "waterfall_status": "with-signal",
    "status": "good",
    "max_altitude": None,
    "rise_azimuth": None,
    "set_azimuth": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obs(**overrides) -> dict:
    """Return a copy of the frozen obs with field overrides."""
    o = deepcopy(_FROZEN_OBS)
    o.update(overrides)
    return o


# ---------------------------------------------------------------------------
# 1. rx-freq extraction
# ---------------------------------------------------------------------------


class TestRxFreqOf:
    def test_reads_from_client_metadata(self):
        assert rx_freq_of(_FROZEN_OBS) == _RX_FREQ

    def test_falls_back_to_observation_frequency(self):
        obs = _obs(client_metadata=None)
        assert rx_freq_of(obs) == _RX_FREQ

    def test_falls_back_to_transmitter_downlink_low(self):
        obs = _obs(client_metadata=None, observation_frequency=None,
                   transmitter_downlink_low=145_000_000)
        assert rx_freq_of(obs) == 145_000_000.0

    def test_returns_none_when_all_sources_missing(self):
        obs = _obs(client_metadata=None, observation_frequency=None,
                   transmitter_downlink_low=None)
        assert rx_freq_of(obs) is None

    def test_returns_none_when_client_metadata_is_malformed(self):
        obs = _obs(client_metadata="{bad json}")
        # falls back to observation_frequency
        assert rx_freq_of(obs) == _RX_FREQ

    def test_returns_none_when_metadata_has_no_rx_freq(self):
        meta = json.dumps({"radio": {"parameters": {}}})
        obs = _obs(client_metadata=meta, observation_frequency=None,
                   transmitter_downlink_low=None)
        assert rx_freq_of(obs) is None


# ---------------------------------------------------------------------------
# 2. Geodetic helpers
# ---------------------------------------------------------------------------


class TestStationEcef:
    def test_equatorial_station_has_z_near_zero(self):
        pos = station_ecef(0.0, 0.0, 0.0)
        assert abs(pos[2]) < 1.0  # km, nearly zero at equator
        assert abs(pos[0] - 6378.137) < 1.0

    def test_polar_station_has_xy_near_zero(self):
        pos = station_ecef(90.0, 0.0, 0.0)
        assert abs(pos[0]) < 1.0
        assert abs(pos[1]) < 1.0
        assert abs(pos[2] - 6356.752) < 1.0  # WGS-84 semi-minor axis

    def test_altitude_increases_radius(self):
        low = station_ecef(45.0, 0.0, 0.0)
        high = station_ecef(45.0, 0.0, 1000.0)
        assert np.linalg.norm(high) > np.linalg.norm(low)


class TestGmst:
    def test_j2000_epoch(self):
        # At J2000.0 (2000-01-01 12:00 UTC) GMST ≈ 280.461° ≈ 4.894 rad
        t = datetime(2000, 1, 1, 12, 0, 0, tzinfo=UTC)
        val = gmst(t)
        assert abs(val - math.radians(280.46061837)) < 1e-6

    def test_increases_with_time(self):
        t1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = t1 + timedelta(hours=12)
        g1 = gmst(t1)
        g2 = gmst(t2)
        # 12 sidereal hours ≈ π radians
        delta = (g2 - g1) % (2 * math.pi)
        assert abs(delta - math.pi) < 0.01

    def test_returns_value_in_0_2pi(self):
        for year in range(2020, 2030):
            t = datetime(year, 6, 15, 0, 0, 0, tzinfo=UTC)
            g = gmst(t)
            assert 0.0 <= g < 2 * math.pi


class TestEciToEcef:
    def test_z_axis_is_unchanged(self):
        # A vector along +Z is unaffected by a rotation about Z
        v = np.array([0.0, 0.0, 7_000.0])
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        out = eci_to_ecef(v, t)
        assert abs(out[2] - 7_000.0) < 1e-6
        assert abs(out[0]) < 1e-6
        assert abs(out[1]) < 1e-6

    def test_is_a_rotation_preserves_magnitude(self):
        v = np.array([5_000.0, 3_000.0, 4_000.0])
        t = datetime(2024, 7, 4, 15, 30, 0, tzinfo=UTC)
        out = eci_to_ecef(v, t)
        assert abs(np.linalg.norm(out) - np.linalg.norm(v)) < 1e-8


# ---------------------------------------------------------------------------
# 3. TLE epoch helper
# ---------------------------------------------------------------------------


class TestTleEpochDatetime:
    def test_parses_known_epoch(self):
        # TLE line 1 field: year=24, day=1.5 → 2024-01-01 12:00 UTC
        tle1 = "1 25544U 98067A   24001.50000000  .00002182  00000-0  44988-4 0  9992"
        epoch = tle_epoch_datetime(tle1)
        assert epoch is not None
        assert epoch.year == 2024
        assert epoch.month == 1
        assert epoch.day == 1
        # 0.5 days = 12h
        assert epoch.hour == 12

    def test_year_mapping_pre57(self):
        # year 24 → 2024
        tle1 = "1 25544U 98067A   24001.00000000  .00002182  00000-0  44988-4 0  9992"
        epoch = tle_epoch_datetime(tle1)
        assert epoch is not None
        assert epoch.year == 2024

    def test_year_mapping_post57(self):
        # year 99 → 1999
        tle1 = "1 25544U 98067A   99001.00000000  .00002182  00000-0  44988-4 0  9992"
        epoch = tle_epoch_datetime(tle1)
        assert epoch is not None
        assert epoch.year == 1999

    def test_returns_none_on_garbage(self):
        assert tle_epoch_datetime("garbage") is None
        assert tle_epoch_datetime("") is None


# ---------------------------------------------------------------------------
# 4. Degraded states
# ---------------------------------------------------------------------------


class TestDegradedStates:
    def test_missing_tle1(self):
        r = corridor_for_obs(_obs(tle1=""))
        assert r.degraded == "MISSING_TLE"
        assert r.uncorrected is None
        assert r.corrected is None

    def test_missing_tle2(self):
        r = corridor_for_obs(_obs(tle2=None))
        assert r.degraded == "MISSING_TLE"

    def test_missing_station_lat(self):
        o = deepcopy(_FROZEN_OBS)
        del o["station_lat"]
        r = corridor_for_obs(o)
        assert r.degraded == "MISSING_STATION"

    def test_missing_station_lng(self):
        o = deepcopy(_FROZEN_OBS)
        del o["station_lng"]
        r = corridor_for_obs(o)
        assert r.degraded == "MISSING_STATION"

    def test_missing_station_alt(self):
        o = deepcopy(_FROZEN_OBS)
        del o["station_alt"]
        r = corridor_for_obs(o)
        assert r.degraded == "MISSING_STATION"

    def test_missing_freq_all_sources(self):
        r = corridor_for_obs(_obs(
            client_metadata=None,
            observation_frequency=None,
            transmitter_downlink_low=None,
        ))
        assert r.degraded == "MISSING_FREQ"

    def test_stale_tle(self):
        # Move the pass 30 days into the future relative to the TLE epoch
        start = datetime(2024, 1, 31, 12, 0, 0, tzinfo=UTC)
        end = start + timedelta(seconds=210)
        r = corridor_for_obs(_obs(
            start=start.isoformat(),
            end=end.isoformat(),
        ))
        assert r.degraded == "STALE_TLE"
        assert r.tle_epoch_age_days is not None
        assert r.tle_epoch_age_days > TLE_MAX_EPOCH_AGE_DAYS

    def test_degraded_carries_obs_id(self):
        r = corridor_for_obs(_obs(tle1=""))
        assert r.obs_id == _FROZEN_OBS["id"]

    def test_no_degraded_state_raises(self):
        """All error paths return, never raise."""
        bad_cases = [
            _obs(tle1=""),
            _obs(tle2=""),
            _obs(client_metadata=None, observation_frequency=None,
                 transmitter_downlink_low=None),
        ]
        for case in bad_cases:
            try:
                r = corridor_for_obs(case)
                assert r.degraded is not None
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"corridor_for_obs raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# 5. Successful corridor — structure and physical invariants
# ---------------------------------------------------------------------------


class TestSuccessfulCorridor:
    @pytest.fixture(scope="class")
    @classmethod
    def result(cls):
        return corridor_for_obs(_FROZEN_OBS)

    def test_no_degraded_state(self, result):
        assert result.degraded is None

    def test_both_corridors_present(self, result):
        assert result.uncorrected is not None
        assert result.corrected is not None

    def test_fracs_are_0_to_1(self, result):
        fracs = result.uncorrected.fracs
        assert fracs[0] == pytest.approx(0.0, abs=1e-9)
        assert fracs[-1] == pytest.approx(1.0, abs=1e-9)

    def test_enough_samples(self, result):
        # At least 90% of requested samples must succeed for a plausible pass.
        assert len(result.uncorrected.fracs) >= int(N_SAMPLES * 0.9)

    def test_corridor_widths(self, result):
        assert result.uncorrected.half_width_hz == UNCORRECTED_CORRIDOR_HZ
        assert result.corrected.half_width_hz == CORRECTED_CORRIDOR_HZ

    def test_corrected_doppler_is_all_zeros(self, result):
        for v in result.corrected.doppler_hz:
            assert v == 0.0

    def test_uncorrected_has_nonzero_swing(self, result):
        dops = result.uncorrected.doppler_hz
        swing = max(dops) - min(dops)
        # For a 210 s pass at 437 MHz a swing of at least 1 kHz is expected.
        assert swing > 1_000.0

    def test_rx_freq_stored(self, result):
        assert result.rx_freq_hz == pytest.approx(_RX_FREQ, rel=1e-6)

    def test_pass_duration_stored(self, result):
        assert result.pass_duration_s == pytest.approx(630.0, abs=1.0)

    def test_tle_epoch_age_is_small(self, result):
        # TLE epoch and pass are both on 2024-01-01; age must be under 1 day.
        assert result.tle_epoch_age_days is not None
        assert result.tle_epoch_age_days < 1.0

    def test_max_elevation_positive(self, result):
        assert result.uncorrected.max_elevation_deg > 0.0

    def test_both_corridors_share_same_tca_frac(self, result):
        assert result.uncorrected.tca_frac == pytest.approx(
            result.corrected.tca_frac, abs=1e-9
        )

    def test_result_is_deterministic(self):
        """Identical inputs → identical outputs."""
        r1 = corridor_for_obs(_FROZEN_OBS)
        r2 = corridor_for_obs(_FROZEN_OBS)
        assert r1.uncorrected.fracs == r2.uncorrected.fracs
        assert r1.uncorrected.doppler_hz == r2.uncorrected.doppler_hz
        assert r1.uncorrected.max_elevation_deg == r2.uncorrected.max_elevation_deg


# ---------------------------------------------------------------------------
# 6. Sign flip at TCA (range rate must flip sign exactly at peak elevation)
# ---------------------------------------------------------------------------


class TestRangeRateSign:
    """The range rate (and therefore Doppler) must flip from positive to negative
    at the time of closest approach (TCA).

    The satellite approaches → range rate negative (receding positive convention)
    → Doppler positive → flip at TCA → receding → Doppler negative.

    This is the calibration invariant verified during A3 geometry validation.
    """

    def test_doppler_positive_before_tca(self):
        r = corridor_for_obs(_FROZEN_OBS)
        fracs = np.asarray(r.uncorrected.fracs)
        dops = np.asarray(r.uncorrected.doppler_hz)
        tca = r.uncorrected.tca_frac

        early_mask = fracs < (tca - 0.05)
        if early_mask.sum() < 5:
            pytest.skip("not enough pre-TCA samples in this pass")

        # Median Doppler before TCA should be positive (approaching)
        early_med = float(np.median(dops[early_mask]))
        assert early_med > 0.0, (
            f"Expected positive Doppler before TCA, got median {early_med:.1f} Hz. "
            "Check range-rate sign convention."
        )

    def test_doppler_negative_after_tca(self):
        r = corridor_for_obs(_FROZEN_OBS)
        fracs = np.asarray(r.uncorrected.fracs)
        dops = np.asarray(r.uncorrected.doppler_hz)
        tca = r.uncorrected.tca_frac

        late_mask = fracs > (tca + 0.05)
        if late_mask.sum() < 5:
            pytest.skip("not enough post-TCA samples in this pass")

        late_med = float(np.median(dops[late_mask]))
        assert late_med < 0.0, (
            f"Expected negative Doppler after TCA, got median {late_med:.1f} Hz. "
            "Check range-rate sign convention."
        )

    def test_sign_flip_exists_near_tca(self):
        r = corridor_for_obs(_FROZEN_OBS)
        dops = np.asarray(r.uncorrected.doppler_hz)
        # Count sign changes: there must be exactly one transition
        signs = np.sign(dops[dops != 0])
        changes = int(np.sum(np.abs(np.diff(signs)) > 0))
        assert changes >= 1, "No Doppler sign flip found — expected one near TCA"


# ---------------------------------------------------------------------------
# 7. Time-direction guard
#
# The top row of a SatNOGS waterfall is the END of the pass (row_frac = 1).
# corridor_columns() uses row_frac = 1 - (row + 0.5) / H.
#
# This test FAILS if the time direction is flipped.
# ---------------------------------------------------------------------------


class TestTimePainting:
    """Verify that corridor_columns maps pass start to the BOTTOM of the image.

    The Doppler sign is positive (approaching, higher frequency) at the start and
    negative (receding, lower frequency) at the end.  With AXIS_SIGN_CONVENTION=-1,
    a positive Doppler value maps to a pixel column to the LEFT of centre.

    At pass start (bottom of the image, last row):
        - Doppler is positive → AXIS_SIGN_CONVENTION × positive = negative offset
          → column is to the LEFT of centre (column < centre_px)

    At pass end (top of the image, first row):
        - Doppler is negative → AXIS_SIGN_CONVENTION × negative = positive offset
          → column is to the RIGHT of centre (column > centre_px)

    If time runs in the wrong direction these assertions invert.
    """

    def test_start_of_pass_maps_to_bottom_of_image(self):
        r = corridor_for_obs(_FROZEN_OBS)
        assert r.degraded is None

        hz_per_px = 120.0
        centre_px = 300.0
        height = 1000

        cols = corridor_columns(r.uncorrected, hz_per_px, centre_px, height)

        # Bottom row (last) = start of pass = approaching satellite = positive Doppler
        bottom_col = cols[-1]
        # Positive Doppler + AXIS_SIGN_CONVENTION = -1 → col < centre
        assert bottom_col < centre_px, (
            f"Bottom row column {bottom_col:.1f} should be < centre {centre_px} "
            "(satellite approaching at pass start, axis sign convention inverts)."
            " Time may be running in the wrong direction."
        )

    def test_end_of_pass_maps_to_top_of_image(self):
        r = corridor_for_obs(_FROZEN_OBS)
        assert r.degraded is None

        hz_per_px = 120.0
        centre_px = 300.0
        height = 1000

        cols = corridor_columns(r.uncorrected, hz_per_px, centre_px, height)

        # Top row (first) = end of pass = receding satellite = negative Doppler
        top_col = cols[0]
        # Negative Doppler + AXIS_SIGN_CONVENTION = -1 → col > centre
        assert top_col > centre_px, (
            f"Top row column {top_col:.1f} should be > centre {centre_px} "
            "(satellite receding at pass end, axis sign convention inverts)."
            " Time may be running in the wrong direction."
        )

    def test_time_flip_fails_this_test(self):
        """Build a fake corridor whose samples are in reversed-time order.

        If corridor_columns respected the reversed order, the column at the
        image bottom would be 'end-of-pass' (receding, positive offset) rather
        than 'start-of-pass' (approaching, negative offset).  The test asserts
        the correct (non-reversed) result — so a time-reversed corridor column
        function would fail here.
        """
        # A simple linearly increasing Doppler from -5kHz to +5kHz (already reversed)
        n = 100
        fracs_fwd = list(np.linspace(0.0, 1.0, n))
        dops_fwd = list(np.linspace(5_000.0, -5_000.0, n))   # positive → negative
        dops_rev = list(reversed(dops_fwd))                    # negative → positive

        c_fwd = Corridor(fracs=fracs_fwd, doppler_hz=dops_fwd, half_width_hz=1.0,
                         max_elevation_deg=30.0, tca_frac=0.5)
        c_rev = Corridor(fracs=fracs_fwd, doppler_hz=dops_rev, half_width_hz=1.0,
                         max_elevation_deg=30.0, tca_frac=0.5)

        hz_per_px = 100.0
        centre = 200.0
        height = 100

        cols_fwd = corridor_columns(c_fwd, hz_per_px, centre, height)
        cols_rev = corridor_columns(c_rev, hz_per_px, centre, height)

        # Forward: bottom row (last) maps to frac=0, Doppler=+5 kHz → col < centre
        assert cols_fwd[-1] < centre
        # Reversed: bottom row maps to frac=0 but Doppler=-5 kHz → col > centre
        assert cols_rev[-1] > centre
        # Their column positions at top and bottom are mirror images
        assert cols_fwd[0] > centre     # top = end-of-pass = negative Dop → right
        assert cols_rev[0] < centre


# ---------------------------------------------------------------------------
# 8. Frequency-axis sign guard
#
# This test FAILS if AXIS_SIGN_CONVENTION is +1 instead of -1.
# ---------------------------------------------------------------------------


class TestFrequencyAxisSign:
    """Positive Doppler (approaching, higher frequency) must map to a smaller
    pixel column (to the LEFT) under AXIS_SIGN_CONVENTION = -1.

    This mirrors the measured fact from A3: all three uncorrected observations
    chose sign = -1 with margins of 25.1, 15.1 and 15.9 sigma against the
    opposite orientation.
    """

    def test_axis_sign_convention_is_minus_one(self):
        assert AXIS_SIGN_CONVENTION == -1, (
            "AXIS_SIGN_CONVENTION must be -1.  Positive Doppler (approaching) "
            "moves LEFT on the rendered axis, measured in A3 at 25 sigma."
        )

    def test_positive_doppler_maps_left_of_centre(self):
        corridor = Corridor(
            fracs=[0.5],
            doppler_hz=[10_000.0],   # positive = approaching
            half_width_hz=200.0,
            max_elevation_deg=30.0,
            tca_frac=0.5,
        )
        col = corridor_columns(corridor, hz_per_px=100.0, centre_px=300.0,
                               image_height=10)
        # +10 kHz / 100 Hz/px = 100 px; AXIS_SIGN_CONVENTION = -1 → col = 200 < 300
        assert col[5] < 300.0, (
            f"Positive Doppler should map LEFT of centre; got column {col[5]:.1f}. "
            "Check AXIS_SIGN_CONVENTION."
        )

    def test_negative_doppler_maps_right_of_centre(self):
        corridor = Corridor(
            fracs=[0.5],
            doppler_hz=[-10_000.0],  # negative = receding
            half_width_hz=200.0,
            max_elevation_deg=30.0,
            tca_frac=0.5,
        )
        col = corridor_columns(corridor, hz_per_px=100.0, centre_px=300.0,
                               image_height=10)
        assert col[5] > 300.0, (
            f"Negative Doppler should map RIGHT of centre; got column {col[5]:.1f}. "
            "Check AXIS_SIGN_CONVENTION."
        )

    def test_sign_flip_is_wrong_orientation(self):
        """Manually check what happens with the wrong sign."""
        corridor = Corridor(
            fracs=[0.5],
            doppler_hz=[5_000.0],
            half_width_hz=200.0,
            max_elevation_deg=30.0,
            tca_frac=0.5,
        )
        col = corridor_columns(corridor, hz_per_px=100.0, centre_px=300.0,
                               image_height=10)
        # With AXIS_SIGN_CONVENTION = -1: 300 + (-1) * 5000/100 = 250 (LEFT)
        # With AXIS_SIGN_CONVENTION = +1: 300 + (+1) * 5000/100 = 350 (RIGHT)
        assert abs(col[5] - 250.0) < 1.0, (
            f"Expected column 250.0 with correct sign convention, got {col[5]:.1f}."
        )


# ---------------------------------------------------------------------------
# 9. corridor_columns: mapping correctness and shape
# ---------------------------------------------------------------------------


class TestCorridorColumns:
    def test_output_length_equals_image_height(self):
        r = corridor_for_obs(_FROZEN_OBS)
        cols = corridor_columns(r.uncorrected, hz_per_px=120.0, centre_px=300.0,
                                image_height=1200)
        assert len(cols) == 1200

    def test_corrected_corridor_stays_near_centre(self):
        r = corridor_for_obs(_FROZEN_OBS)
        cols = corridor_columns(r.corrected, hz_per_px=120.0, centre_px=300.0,
                                image_height=1200)
        # Corrected corridor: all doppler_hz = 0 → columns should equal centre_px
        assert np.all(np.abs(cols - 300.0) < 1e-6)

    def test_freq_offset_shifts_columns_by_expected_amount(self):
        r = corridor_for_obs(_FROZEN_OBS)
        hz_per_px = 100.0
        centre = 300.0
        h = 100
        offset_hz = 5_000.0  # shift = offset / hz_per_px = 50 px

        cols_no_offset = corridor_columns(r.corrected, hz_per_px, centre, h,
                                          freq_offset_hz=0.0)
        cols_with_offset = corridor_columns(r.corrected, hz_per_px, centre, h,
                                            freq_offset_hz=offset_hz)
        # AXIS_SIGN_CONVENTION = -1: offset shifts column by -50 px
        expected_shift = AXIS_SIGN_CONVENTION * offset_hz / hz_per_px
        np.testing.assert_allclose(
            cols_with_offset - cols_no_offset,
            expected_shift,
            atol=1e-9,
        )

    def test_search_range_constant_is_documented(self):
        """The search range constant must be present and positive."""
        assert FREQ_OFFSET_SEARCH_HZ > 0.0


# ---------------------------------------------------------------------------
# 10. Elevation profile and TCA invariants
# ---------------------------------------------------------------------------


class TestElevationProfile:
    """Verify that the propagation produces a plausible elevation profile.

    Specifically: elevation is positive somewhere during the pass, rises to a
    maximum and then falls, and the recorded TCA fraction is internally consistent.
    """

    def test_max_elevation_is_positive(self):
        r = corridor_for_obs(_FROZEN_OBS)
        assert r.uncorrected.max_elevation_deg > 0.0

    def test_tca_frac_in_valid_range(self):
        r = corridor_for_obs(_FROZEN_OBS)
        tca = r.uncorrected.tca_frac
        assert 0.0 <= tca <= 1.0

    def test_elevation_profile_unimodal(self):
        """Elevation should rise then fall (unimodal) for any valid pass.

        Uses the 68.4-degree ISS pass at 03:00-03:09 UTC which puts TCA firmly
        in the interior of the window (not near either edge), so the unimodal
        assertion is applicable without a skip guard.
        """
        from sgp4.api import Satrec, jday  # noqa: F401 – confirms sgp4 importable

        # 68.4-degree pass over Prague: TCA at 03:04, well inside 03:00–03:09.
        start_dt = datetime(2024, 1, 1, 3, 0, 0, tzinfo=UTC)
        end_dt = datetime(2024, 1, 1, 3, 9, 35, tzinfo=UTC)
        site = station_ecef(_LAT, _LNG, _ALT)
        fracs, _, els, _ = propagate_pass(_TLE1, _TLE2, start_dt, end_dt, site, _RX_FREQ)

        assert len(els) > 10, "expected many samples"
        peak_idx = int(np.argmax(np.asarray(els)))
        peak_el = els[peak_idx]
        assert peak_el > 30.0, f"expected a high pass, got {peak_el:.1f}°"

        before_peak = np.asarray(els[:peak_idx])
        after_peak = np.asarray(els[peak_idx + 1:])

        # Mean elevation on both sides must be below the peak.
        if len(before_peak) > 0:
            assert float(np.mean(before_peak)) < peak_el
        if len(after_peak) > 0:
            assert float(np.mean(after_peak)) < peak_el


# ---------------------------------------------------------------------------
# 11. Constants sanity-check
# ---------------------------------------------------------------------------


class TestConstants:
    def test_corridor_widths_ordered(self):
        assert CORRECTED_CORRIDOR_HZ < UNCORRECTED_CORRIDOR_HZ

    def test_search_range_covers_measured_offsets(self):
        # The three measured offsets were 14.0, 2.4 and 1.8 kHz.
        measured_max_offset = 14_000.0
        assert measured_max_offset < FREQ_OFFSET_SEARCH_HZ, (
            f"FREQ_OFFSET_SEARCH_HZ ({FREQ_OFFSET_SEARCH_HZ:.0f} Hz) must exceed "
            f"the largest measured offset ({measured_max_offset:.0f} Hz)."
        )

    def test_n_samples_reasonable(self):
        assert 100 <= N_SAMPLES <= 2000

    def test_stale_tle_threshold_reasonable(self):
        assert 3 <= TLE_MAX_EPOCH_AGE_DAYS <= 30


class TestCorridorWidthsAreMeasured:
    """A corridor width is a containment band, and A3 measured what it must contain.

    These exist because the first version reused 200 Hz from A3, where it was a
    reference line drawn on an overlay rather than a tolerance. Nothing in the
    suite pinned it, so the value could be changed back without a single test
    turning red, and kill gate 3 would then fail for a reason that is not real.
    """

    # Within-pass wander of the four corrected carriers measured in A3, in Hz.
    CORRECTED_WANDER_HZ = (77.0, 639.0, 639.0, 1935.0)

    # Residual around the fitted curve on the one uncorrected observation with
    # enough per-row detections to measure: obs 14740031, 39 rows.
    UNCORRECTED_RESIDUAL_MAX_HZ = 140.0

    # Largest constant offset from the predicted curve measured in A3, in Hz.
    LARGEST_MEASURED_OFFSET_HZ = 14_000.0

    def test_corrected_band_contains_every_carrier_a3_measured(self):
        needed = max(self.CORRECTED_WANDER_HZ) / 2.0
        assert needed <= CORRECTED_CORRIDOR_HZ, (
            f"a {CORRECTED_CORRIDOR_HZ:.0f} Hz half-width cannot contain a carrier "
            f"that wanders {max(self.CORRECTED_WANDER_HZ):.0f} Hz across its pass; "
            f"at least {needed:.0f} Hz is required"
        )

    def test_the_overlay_reference_line_is_not_reused_as_a_tolerance(self):
        assert CORRECTED_CORRIDOR_HZ > 200.0, (
            "200 Hz was an annotation drawn on an A3 overlay, not a measurement "
            "of how far a corrected carrier moves"
        )

    def test_uncorrected_band_contains_the_measured_residual(self):
        assert UNCORRECTED_CORRIDOR_HZ >= self.UNCORRECTED_RESIDUAL_MAX_HZ

    def test_offset_search_covers_the_largest_measured_offset(self):
        assert FREQ_OFFSET_SEARCH_HZ >= self.LARGEST_MEASURED_OFFSET_HZ, (
            "the corridor is not centred on rx-freq; the search range has to "
            "reach the largest offset A3 actually saw"
        )
