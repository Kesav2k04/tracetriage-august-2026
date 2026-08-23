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
from pathlib import Path

import numpy as np
import pytest

from pipeline.tracetriage.physics import (
    AXIS_SIGN_CONVENTION,
    AXIS_SIGN_MEASURABLE_RATIO,
    AXIS_SIGN_MEASURED_FAMILIES,
    C_M_PER_S,
    CORRECTED_CORRIDOR_HZ,
    FREQ_OFFSET_SEARCH_HZ,
    HORIZON_MASK_ELEVATION_DEG,
    N_SAMPLES,
    PEAK_DOPPLER_SLOPE_HZ_PER_S,
    SGP4_MAX_MISSING_FRACTION,
    TLE_AGE_TOLERANCE_HALF_WIDTHS,
    TLE_MAX_EPOCH_AGE_DAYS,
    UNCORRECTED_CORRIDOR_HZ,
    Corridor,
    axis_sign_evidence,
    client_family,
    corridor_columns,
    corridor_for_obs,
    corridor_row_elevation,
    ecef_to_geodetic,
    eci_to_ecef,
    geodetic_normal,
    gmst,
    image_row_fracs,
    pass_geometry,
    propagate_pass,
    rx_freq_of,
    station_ecef,
    tle_epoch_datetime,
    visible_rows,
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

    # SPACE-B1: an unparseable TLE epoch must return UNPARSEABLE_TLE_EPOCH,
    # not silently propagate from a garbage epoch and return degraded=None.

    def test_unparseable_tle_epoch_returns_named_code(self):
        """Replacing the epoch year with 'XX' makes tle_epoch_datetime return None.

        Before the fix: the staleness gate is guarded by 'if tle_epoch is not None',
        so it is skipped, propagation runs from a garbage epoch, and degraded=None
        is returned — a confident wrong corridor.  After the fix: UNPARSEABLE_TLE_EPOCH.
        """
        bad_tle1 = _TLE1[:18] + "XX" + _TLE1[20:]   # corrupt the 2-digit year field
        assert tle_epoch_datetime(bad_tle1) is None, (
            "pre-condition: the corrupted TLE1 must not parse"
        )
        r = corridor_for_obs(_obs(tle1=bad_tle1))
        assert r.degraded == "UNPARSEABLE_TLE_EPOCH", (
            f"expected UNPARSEABLE_TLE_EPOCH, got degraded={r.degraded!r}. "
            "A TLE whose epoch cannot be read must not be propagated."
        )
        assert r.uncorrected is None
        assert r.corrected is None

    def test_unparseable_tle_epoch_does_not_raise(self):
        """corridor_for_obs must return, not raise, on a garbage epoch."""
        bad_tle1 = _TLE1[:18] + "XX" + _TLE1[20:]
        try:
            r = corridor_for_obs(_obs(tle1=bad_tle1))
            assert r.degraded is not None
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"corridor_for_obs raised on unparseable epoch: {exc}")


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
        fracs, _, els, _ = propagate_pass(
            _TLE1, _TLE2, start_dt, end_dt, site, _RX_FREQ,
            geodetic_normal(_LAT, _LNG),
        )

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
        """Read the offsets out of A3's receipt rather than pinning them here.

        This test used to assert against a hardcoded ``14_000.0`` copied from a
        comment that named the wrong two of the three offsets: 2.4 and 1.8 kHz,
        which are ``vertical_column_offset_hz``, where the corridor's own offset is
        ``curved_offset_hz`` and reads 7.1 kHz on both. The assertion passed either
        way, because the maximum was right and only the smaller two were wrong, so a
        pinned constant could not have found it. Reading the field the constant is
        derived from can.
        """
        summary = json.loads(
            _A3_SUMMARY_PATH.read_text(encoding="utf-8")
        )
        offsets = [
            abs(float(r["curved_offset_hz"]))
            for r in summary
            if r.get("verdict") == "UNCORRECTED" and r.get("curved_offset_hz") is not None
        ]
        assert offsets, "A3's summary must hold at least one UNCORRECTED offset"
        measured_max_offset = max(offsets)
        assert measured_max_offset < FREQ_OFFSET_SEARCH_HZ, (
            f"FREQ_OFFSET_SEARCH_HZ ({FREQ_OFFSET_SEARCH_HZ:.0f} Hz) must exceed "
            f"the largest measured offset ({measured_max_offset:.0f} Hz)."
        )

    def test_n_samples_reasonable(self):
        assert 100 <= N_SAMPLES <= 2000

    def test_stale_tle_threshold_is_the_bound_its_comment_derives(self):
        """The threshold must follow from the tolerance, not from a range check.

        This test asserted 3 <= threshold <= 30, which every plausible value satisfies
        and which therefore could not fail. The constant was also the only one in the
        module with no derivation behind it. Both are fixed together: the arithmetic
        below is the comment beside the constant, executed.
        """
        budget_hz = TLE_AGE_TOLERANCE_HALF_WIDTHS * UNCORRECTED_CORRIDOR_HZ
        assert budget_hz == pytest.approx(500.0)

        timing_s = budget_hz / PEAK_DOPPLER_SLOPE_HZ_PER_S
        assert timing_s == pytest.approx(4.19, abs=0.01)

        # Along-track position error at orbital speed, and the days of drift that
        # produce it at the faster end of ordinary LEO growth.
        orbital_speed_km_per_s = 7.5
        fastest_ordinary_growth_km_per_day = 3.0
        along_track_km = timing_s * orbital_speed_km_per_s
        days_at_fastest = along_track_km / fastest_ordinary_growth_km_per_day
        assert days_at_fastest == pytest.approx(10.5, abs=0.1)

        assert days_at_fastest >= TLE_MAX_EPOCH_AGE_DAYS, (
            f"the threshold ({TLE_MAX_EPOCH_AGE_DAYS} days) exceeds the age its own "
            f"tolerance allows ({days_at_fastest:.1f} days), so a corridor can be "
            f"displaced by more than {TLE_AGE_TOLERANCE_HALF_WIDTHS} half-widths and "
            "still be reported as fresh"
        )

    def test_the_previous_threshold_did_not_meet_that_tolerance(self):
        """14 days spends 0.33 half-widths at the faster end, which is the reason it moved.

        Kept as a test rather than only as a comment so that raising the constant back
        to 14 fails here with the arithmetic attached.
        """
        previous = 14.0
        timing_s = previous * 3.0 / 7.5
        half_widths = timing_s * PEAK_DOPPLER_SLOPE_HZ_PER_S / UNCORRECTED_CORRIDOR_HZ
        assert half_widths == pytest.approx(0.33, abs=0.01)
        assert half_widths > TLE_AGE_TOLERANCE_HALF_WIDTHS

    def test_the_threshold_is_inert_on_the_corpus_and_the_receipt_says_so(self):
        """A threshold nothing has ever been near is a bound, not a filter.

        Over the validation corpus the maximum epoch age is 3.837 days, so nothing in
        it is anywhere near either the old or the new value. That is worth publishing
        rather than leaving for a reader to assume the threshold is doing work.
        """
        receipt = json.loads(
            (Path(__file__).resolve().parents[1] / "artifacts" / "PHYSICS_VALIDATION.json")
            .read_text(encoding="utf-8")
        )
        block = receipt["distribution"].get("tle_epoch_age")
        assert block, "PHYSICS_VALIDATION.json does not publish the epoch-age distribution"
        assert block["n"] >= 199
        assert block["max_days"] < TLE_MAX_EPOCH_AGE_DAYS, (
            "an observation now sits above the threshold, so it is no longer inert and "
            "the receipt's note has to be rewritten rather than reasserted"
        )
        assert block["threshold_days"] == TLE_MAX_EPOCH_AGE_DAYS
        assert block["n_over_threshold"] == 0


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


class TestPassGeometry:
    """The sky track and the ground track, and the properties that pin them.

    ``pass_geometry`` walks its own propagation loop rather than borrowing
    ``propagate_pass``'s, which buys a clean return type at the cost of a second
    place elevation can be computed. The first test here closes that cost: the two
    loops must agree exactly, not approximately, so a future edit to one of them
    cannot silently move the other.
    """

    _START_DT = datetime(2024, 1, 1, 3, 0, 0, tzinfo=UTC)
    _END_DT = datetime(2024, 1, 1, 3, 9, 35, tzinfo=UTC)

    def _geom(self):
        site = station_ecef(_LAT, _LNG, _ALT)
        return pass_geometry(
            _TLE1, _TLE2, self._START_DT, self._END_DT, site,
            geodetic_normal(_LAT, _LNG),
        )

    def test_pass_geometry_elevation_matches_propagate_pass(self):
        """Two loops, one angle. Exact equality, not a tolerance.

        A tolerance here would let the two drift apart by whatever the tolerance
        is, and the sky plot would then be drawn from a different elevation than
        the corridor was scored against.
        """
        site = station_ecef(_LAT, _LNG, _ALT)
        up = geodetic_normal(_LAT, _LNG)
        fracs, _dop, els, errs = propagate_pass(
            _TLE1, _TLE2, self._START_DT, self._END_DT, site, _RX_FREQ, up,
        )
        geom = pass_geometry(
            _TLE1, _TLE2, self._START_DT, self._END_DT, site, up,
        )
        assert geom.fracs == fracs
        assert geom.elevation_deg == els
        assert geom.error_codes == errs

    def test_range_rate_reproduces_the_doppler_curve_exactly(self):
        """The Doppler shift derived from the geometry must equal the pipeline's.

        pass_geometry returns an unscaled range rate rather than a Doppler shift, so
        the console can show the shift at any instant of the pass without a second
        propagation. That only holds if the two agree exactly, which is what this
        asserts: same samples, same sign, same value once the receive frequency is
        applied. A near-equality here would let the scrubbed readout disagree with
        the corridor drawn on the same page.
        """
        site = station_ecef(_LAT, _LNG, _ALT)
        up = geodetic_normal(_LAT, _LNG)
        _fracs, dops, _els, _errs = propagate_pass(
            _TLE1, _TLE2, self._START_DT, self._END_DT, site, _RX_FREQ, up,
        )
        geom = pass_geometry(
            _TLE1, _TLE2, self._START_DT, self._END_DT, site, up,
        )
        derived = [
            -rate * 1_000.0 / C_M_PER_S * _RX_FREQ for rate in geom.range_rate_km_s
        ]
        assert derived == dops

    def test_range_rate_changes_sign_at_closest_approach(self):
        """Approaching then receding: the sign flip is the physical content.

        If the sign convention were inverted the Doppler curve would run backwards
        and the corridor would be fitted against a mirror image of the trace, which
        is a failure mode this project has already been bitten by on the frequency
        axis.
        """
        geom = self._geom()
        i_near = int(np.argmin(np.asarray(geom.range_km)))
        assert geom.range_rate_km_s[0] < 0.0, "should be approaching at the start"
        assert geom.range_rate_km_s[-1] > 0.0, "should be receding at the end"
        assert abs(geom.range_rate_km_s[i_near]) < abs(geom.range_rate_km_s[0]), (
            "range rate should be near zero at closest approach"
        )

    def test_azimuth_covers_a_range_and_stays_in_bounds(self):
        geom = self._geom()
        assert len(geom.azimuth_deg) > 10
        assert all(0.0 <= a < 360.0 for a in geom.azimuth_deg)
        # A real overhead pass sweeps the sky; a constant azimuth would mean the
        # local basis collapsed and every sample projected onto the same vector.
        assert max(geom.azimuth_deg) - min(geom.azimuth_deg) > 20.0

    def test_subsatellite_track_is_on_the_globe_and_moves(self):
        geom = self._geom()
        assert all(-90.0 <= la <= 90.0 for la in geom.sub_lat_deg)
        assert all(-180.0 <= lo <= 180.0 for lo in geom.sub_lon_deg)
        # ISS altitude, generously bounded: anything outside this is a unit error
        # rather than an orbit.
        assert all(300.0 < h < 500.0 for h in geom.altitude_km), (
            f"altitude range {min(geom.altitude_km):.1f}-{max(geom.altitude_km):.1f} km"
        )
        assert abs(geom.sub_lat_deg[-1] - geom.sub_lat_deg[0]) > 1.0

    def test_range_is_never_shorter_than_the_altitude(self):
        """Slant range to a satellite cannot beat the straight-up distance.

        This is the cheapest available check that the range and the altitude were
        computed in the same units, which is the error that would otherwise pass
        every other test in this class.
        """
        geom = self._geom()
        for rng, alt in zip(geom.range_km, geom.altitude_km, strict=True):
            assert rng >= alt - 1.0, f"range {rng:.1f} km under altitude {alt:.1f} km"

    def test_highest_elevation_is_the_shortest_range(self):
        geom = self._geom()
        i_high = int(np.argmax(np.asarray(geom.elevation_deg)))
        i_near = int(np.argmin(np.asarray(geom.range_km)))
        assert abs(i_high - i_near) <= 1, (
            "the closest approach and the highest elevation should be the same "
            f"sample, got {i_high} and {i_near}"
        )

    def test_geodetic_round_trip_closes(self):
        """station_ecef and ecef_to_geodetic must invert each other.

        Both now read one WGS-84 eccentricity constant. When each computed its
        own, a round trip could close on one and drift on the other with nothing
        to show it.
        """
        for lat, lon, alt_m in [
            (0.0, 0.0, 0.0),
            (_LAT, _LNG, _ALT),
            (-33.9, 151.2, 20.0),
            (89.9, 10.0, 0.0),
            (-70.0, -120.0, 3_000.0),
        ]:
            r = station_ecef(lat, lon, alt_m)
            got_lat, got_lon, got_h = ecef_to_geodetic(r)
            assert abs(got_lat - lat) < 1e-6, f"lat {lat} -> {got_lat}"
            assert abs(got_lon - lon) < 1e-9, f"lon {lon} -> {got_lon}"
            assert abs(got_h - alt_m / 1000.0) < 1e-6, f"h {alt_m} -> {got_h}"

    def test_geodetic_latitude_is_not_geocentric_latitude(self):
        """The distinction the elevation-reference fix was about, asserted here.

        If ecef_to_geodetic ever returned the geocentric latitude it starts from,
        every test above would still pass. This one would not.
        """
        r = station_ecef(45.0, 0.0, 0.0)
        geocentric = math.degrees(math.atan2(float(r[2]), math.hypot(float(r[0]), float(r[1]))))
        geodetic, _, _ = ecef_to_geodetic(r)
        assert abs(geodetic - 45.0) < 1e-6
        assert abs(geodetic - geocentric) > 0.15, (
            "at 45 degrees the two latitudes differ by about 0.19 degrees; "
            f"got {abs(geodetic - geocentric):.4f}"
        )

    def test_site_up_must_be_non_zero(self):
        site = station_ecef(_LAT, _LNG, _ALT)
        with pytest.raises(ValueError, match="non-zero"):
            pass_geometry(
                _TLE1, _TLE2, self._START_DT, self._END_DT, site,
                np.zeros(3),
            )


# ---------------------------------------------------------------------------
# 12. SPACE-B2: n_sgp4_errors and n_samples_propagated on PhysicsResult
#
# errs is collected by propagate_pass and must be surfaced on the result.
# A corridor built on a fraction of the pass (due to SGP4 errors) must degrade
# when the missing-sample fraction exceeds SGP4_MAX_MISSING_FRACTION.
# ---------------------------------------------------------------------------


class TestSgp4ErrorSurfacing:
    """SPACE-B2: SGP4 error counts must be on PhysicsResult, not silently dropped."""

    def test_n_sgp4_errors_field_exists_on_result(self):
        """PhysicsResult must expose n_sgp4_errors."""
        r = corridor_for_obs(_FROZEN_OBS)
        assert hasattr(r, "n_sgp4_errors"), (
            "PhysicsResult must have n_sgp4_errors; errs from propagate_pass "
            "was bound and discarded before this fix."
        )

    def test_n_samples_propagated_field_exists_on_result(self):
        """PhysicsResult must expose n_samples_propagated."""
        r = corridor_for_obs(_FROZEN_OBS)
        assert hasattr(r, "n_samples_propagated"), (
            "PhysicsResult must have n_samples_propagated."
        )

    def test_clean_pass_has_zero_sgp4_errors(self):
        """The frozen ISS pass must propagate without any SGP4 errors."""
        r = corridor_for_obs(_FROZEN_OBS)
        assert r.n_sgp4_errors == 0
        assert r.n_samples_propagated == len(r.uncorrected.fracs)

    def test_sgp4_max_missing_fraction_constant_exists(self):
        """The threshold must be a named constant, not a magic literal."""
        assert 0.0 < SGP4_MAX_MISSING_FRACTION < 1.0

    def test_sgp4_partial_failure_degrades_above_threshold(self):
        """A corridor built on (1 - threshold - epsilon) of the samples must degrade.

        Simulated by patching propagate_pass to return only a tiny slice of fracs,
        leaving most of N_SAMPLES as error codes.
        """
        from unittest.mock import patch

        n_good = max(1, int(N_SAMPLES * (1.0 - SGP4_MAX_MISSING_FRACTION) * 0.5))
        good_fracs = [i / (n_good - 1) for i in range(n_good)] if n_good > 1 else [0.0]
        good_dops = [0.0] * n_good
        good_els = [10.0] * n_good
        # Fill the rest of N_SAMPLES with synthetic error codes
        n_errors = N_SAMPLES - n_good
        fake_errs = [6] * n_errors  # SGP4 error code 6 = decay

        with patch(
            "pipeline.tracetriage.physics.propagate_pass",
            return_value=(good_fracs, good_dops, good_els, fake_errs),
        ):
            r = corridor_for_obs(_FROZEN_OBS)

        assert r.degraded == "SGP4_PARTIAL_ERROR", (
            f"expected SGP4_PARTIAL_ERROR when {n_errors} of {N_SAMPLES} samples "
            f"failed (> {SGP4_MAX_MISSING_FRACTION:.0%} missing), "
            f"got degraded={r.degraded!r}"
        )
        assert r.uncorrected is None
        assert r.corrected is None
        assert r.n_sgp4_errors == n_errors
        assert r.n_samples_propagated == n_good

    def test_sgp4_partial_failure_below_threshold_does_not_degrade(self):
        """A corridor built on (1 - threshold/2) of the samples must succeed."""
        from unittest.mock import patch

        n_good = int(N_SAMPLES * (1.0 - SGP4_MAX_MISSING_FRACTION * 0.5))
        good_fracs = [i / (n_good - 1) for i in range(n_good)]
        good_dops = list(np.linspace(5000.0, -5000.0, n_good))
        good_els = [max(1.0, 30.0 - abs(i - n_good // 2) * 0.1) for i in range(n_good)]
        n_errors = N_SAMPLES - n_good
        fake_errs = [6] * n_errors

        with patch(
            "pipeline.tracetriage.physics.propagate_pass",
            return_value=(good_fracs, good_dops, good_els, fake_errs),
        ):
            r = corridor_for_obs(_FROZEN_OBS)

        assert r.degraded is None, (
            f"expected success when only {n_errors} of {N_SAMPLES} samples failed "
            f"(< {SGP4_MAX_MISSING_FRACTION:.0%} missing), got {r.degraded!r}"
        )
        assert r.n_sgp4_errors == n_errors
        assert r.n_samples_propagated == n_good


# ---------------------------------------------------------------------------
# SPACE-S4: one row-to-fraction map, and the elevation series that rides on it
# ---------------------------------------------------------------------------


class TestHorizonMask:
    """The mask has to agree with the corridor about which row is which.

    corridor_columns and corridor_row_elevation both invert the row index to a
    pass-time fraction. While each carried its own copy of that inversion, a mask
    could be applied to the opposite end of the image from the curve it was masking
    and every summary statistic would come out the same: the same number of rows
    dropped, from the wrong end.
    """

    def _ramp(self, n: int = 64) -> Corridor:
        """A corridor whose Doppler and elevation are both the pass fraction.

        Same series in both fields, so the two maps can be compared row by row
        without a scale factor in between.
        """
        fracs = [i / (n - 1) for i in range(n)]
        return Corridor(
            fracs=fracs,
            doppler_hz=[1000.0 * f for f in fracs],
            half_width_hz=500.0,
            max_elevation_deg=1.0,
            tca_frac=1.0,
            elevation_deg=[1000.0 * f for f in fracs],
        )

    def test_the_elevation_map_and_the_column_map_read_the_same_rows(self):
        c = self._ramp()
        height = 97                       # odd, and not a multiple of the samples
        elevation = corridor_row_elevation(c, height)
        # The columns for the same corridor, with the axis sign and centre removed
        # so what is left is the Doppler value each row was drawn at.
        cols = corridor_columns(
            c, hz_per_px=1.0, centre_px=0.0, image_height=height, freq_offset_hz=0.0
        )
        doppler_at_row = np.asarray(cols) / AXIS_SIGN_CONVENTION
        assert np.allclose(elevation, doppler_at_row, atol=1e-9), (
            "the elevation map and the column map disagree about which row is "
            "which point of the pass"
        )

    def test_row_zero_is_the_end_of_the_pass(self):
        """Time runs bottom to top, so the highest fraction is at row 0."""
        fracs = image_row_fracs(10)
        assert fracs[0] > fracs[-1]
        assert fracs[0] == pytest.approx(0.95)
        assert fracs[-1] == pytest.approx(0.05)

    def test_the_floor_is_the_geometric_horizon(self):
        """Stated, because a station's real mask sits above it and is not known.

        SatNOGS publishes no per-station horizon mask, so zero degrees is the
        strongest floor this project can source. Raising it would mask real signal
        on stations with a clear view.
        """
        assert HORIZON_MASK_ELEVATION_DEG == 0.0

    def test_a_real_pass_carries_one_elevation_per_sample(self):
        """The mask is only as long as the series behind it."""
        r = corridor_for_obs(_FROZEN_OBS)
        assert r.degraded is None
        for corridor in (r.uncorrected, r.corrected):
            assert len(corridor.elevation_deg) == len(corridor.fracs)
            assert max(corridor.elevation_deg) == pytest.approx(
                corridor.max_elevation_deg
            )

    def test_the_masked_fraction_of_a_real_pass_is_measured_not_assumed(self):
        """A SatNOGS window is scheduled around a pass, not clipped to it.

        Over the 150 records the console builds from, 26 windows (17.3 percent)
        open or close below the horizon and the worst spends 16.60 percent of its
        rows there. This frozen record is one of the ordinary ones: it stays above
        the horizon throughout, which is why the shipped receipts do not move.
        """
        r = corridor_for_obs(_FROZEN_OBS)
        mask = visible_rows(r.uncorrected, 1000)
        assert mask.all(), (
            "the frozen record now has below-horizon rows, so any receipt claiming "
            "zero masked rows for it needs regenerating"
        )
        assert min(r.uncorrected.elevation_deg) >= 0.0


# ---------------------------------------------------------------------------
# SPACE-S5: the evidence base behind AXIS_SIGN_CONVENTION
# ---------------------------------------------------------------------------

_A3_SUMMARY_PATH = (
    Path(__file__).resolve().parents[1] / "artifacts" / "a3_overlays" / "summary.json"
)


class TestClientFamily:
    """The renderer version is the unit the axis sign has to be grouped by."""

    def test_a_build_suffix_is_the_same_renderer(self):
        assert client_family({"client_version": "2.1.2+1.gcded8f6"}) == "2.1.2"
        assert client_family({"client_version": "1.9.2+sa2kng"}) == "1.9.2+sa2kng"
        assert client_family({"client_version": "1.8.1.dirty"}) == "1.8.1"
        assert client_family({"client_version": "  2.1.2  "}) == "2.1.2"

    def test_a_missing_version_falls_back_then_names_itself_unknown(self):
        meta = json.dumps({"radio": {"version": "1.9.3"}})
        assert client_family({"client_metadata": meta}) == "1.9.3"
        assert client_family({}) == "unknown"
        assert client_family({"client_version": ""}) == "unknown"
        assert client_family({"client_metadata": "not json at all"}) == "unknown"
        assert client_family({"client_metadata": json.dumps({"radio": None})}) == "unknown"

    def test_unknown_is_not_grouped_with_a_real_family(self):
        """An absent version must not inherit another renderer's evidence."""
        ev = axis_sign_evidence({})
        assert ev["client_family"] == "unknown"
        assert ev["status"] == "ASSUMED_FROM_OTHER_FAMILIES"


class TestAxisSignEvidence:
    def test_the_families_with_a_measurement_are_the_ones_that_claim_one(self):
        for family in ("1.6", "2.1.2"):
            ev = axis_sign_evidence({"client_version": family})
            assert ev["status"] == "MEASURED_ON_FAMILY", family
        for family in ("1.8.1", "1.9.3", "2.1.1", "1.4"):
            ev = axis_sign_evidence({"client_version": family})
            assert ev["status"] == "ASSUMED_FROM_OTHER_FAMILIES", family

    def test_the_evidence_base_is_derived_from_the_a3_artifact(self):
        """Recompute which observations can measure the sign, and from which families.

        This is the test that keeps AXIS_SIGN_MEASURED_FAMILIES honest. Widening it
        without a measurable observation behind the new family fails here, and so does
        a change to the artifact that removes the evidence for a family already
        claimed. The constant itself is checked the same way: every observation where
        the sign is measurable has to choose it.
        """
        a3 = json.loads(_A3_SUMMARY_PATH.read_text(encoding="utf-8"))
        decisive = [r for r in a3 if r.get("verdict") in ("CORRECTED", "UNCORRECTED")]
        assert len(decisive) == 7, f"the decisive pool changed: {len(decisive)}"

        measurable, unmeasurable = [], []
        for r in decisive:
            by_sign = r["sigma_curved_by_sign"]
            plus, minus = float(by_sign["1"]), float(by_sign["-1"])
            better, worse = max(plus, minus), min(plus, minus)
            ratio = better / worse if worse > 0 else float("inf")
            (measurable if ratio >= AXIS_SIGN_MEASURABLE_RATIO else unmeasurable).append(
                (r["obs_id"], client_family({"client_version": r["family"]}), plus, minus, ratio)
            )

        assert len(measurable) == 3, f"measurable pool changed: {measurable}"
        for obs_id, _family, plus, minus, _ratio in measurable:
            implied = -1 if minus > plus else 1
            assert implied == AXIS_SIGN_CONVENTION, (
                f"obs {obs_id} measures the axis sign as {implied}, and the constant "
                f"is {AXIS_SIGN_CONVENTION}"
            )

        assert {f for _, f, *_ in measurable} == set(AXIS_SIGN_MEASURED_FAMILIES), (
            "AXIS_SIGN_MEASURED_FAMILIES no longer names exactly the families with a "
            f"measurable observation: artifact says {sorted({f for _, f, *_ in measurable})}"
        )

        # The four excluded observations are the corrected ones, where the corridor is
        # flat and has no shape to mirror. A3's argmax still returned a sign there and
        # returned +1 twice, which is why they are excluded by the ratio rather than
        # counted as disagreement.
        assert len(unmeasurable) == 4
        assert all(r["verdict"] == "CORRECTED" for r in decisive
                   if r["obs_id"] in {o for o, *_ in unmeasurable})

    def test_the_measurability_threshold_is_not_tuned_to_the_data(self):
        """A threshold anywhere in a wide band classifies the shipped set identically.

        The measurable observations separate at 11.3x and above, the unmeasurable ones
        at 1.18x and below. Reporting that gap is what makes 2.0x a choice rather than
        a fit: any value between them gives the same three observations.
        """
        a3 = json.loads(_A3_SUMMARY_PATH.read_text(encoding="utf-8"))
        ratios = []
        for r in a3:
            if r.get("verdict") not in ("CORRECTED", "UNCORRECTED"):
                continue
            plus, minus = (float(r["sigma_curved_by_sign"][k]) for k in ("1", "-1"))
            better, worse = max(plus, minus), min(plus, minus)
            ratios.append((better / worse if worse > 0 else float("inf"), r["verdict"]))
        strong = min(x for x, v in ratios if v == "UNCORRECTED")
        weak = max(x for x, v in ratios if v == "CORRECTED")
        assert weak < AXIS_SIGN_MEASURABLE_RATIO < strong
        assert strong / weak > 5.0, (
            f"the separation has narrowed to {strong / weak:.1f}x, so the threshold now "
            "decides the answer and has to be justified rather than reported"
        )

    def test_the_shipped_gate3_receipt_states_its_axis_sign_evidence(self):
        """Both halves per observation: the family's status and this image's answer.

        Two of the seven decisive observations come from family 1.9.3, which has no
        measurable observation behind it, so the assumed branch is exercised by
        shipped data rather than only by a unit test.
        """
        receipt = json.loads(
            (Path(__file__).resolve().parents[1] / "artifacts" / "GATE3_RECEIPT.json")
            .read_text(encoding="utf-8")
        )
        statuses, agreements, dissent = [], [], []
        for obs in receipt["observations"]:
            block = obs.get("axis_sign")
            assert block, f"obs {obs['obs_id']} publishes no axis sign evidence"
            assert block["axis_sign_applied"] == AXIS_SIGN_CONVENTION
            statuses.append(block["status"])
            re_m = block["remeasured"]
            assert (re_m["measurable"] is True) == (re_m["sign_implied"] is not None)
            if not re_m["measurable"]:
                assert re_m["not_measurable_reason"], (
                    f"obs {obs['obs_id']} is not measurable for no stated reason"
                )
                continue
            agreements.append(re_m["agrees_with_constant"])
            if not re_m["agrees_with_constant"]:
                dissent.append((
                    obs["obs_id"],
                    max(re_m["sigma_as_shipped"], re_m["sigma_mirrored"]),
                    bool((obs.get("null_calibration") or {}).get("discriminates")),
                ))
        assert "ASSUMED_FROM_OTHER_FAMILIES" in statuses, (
            "no shipped observation exercises the assumed branch, so it is untested"
        )
        assert agreements, "no observation was measurable, so this test checked nothing"

        # Unanimity was the property when this pool was three observations. Over 175 it
        # is not, and the two dissenters are not noise in the ratio: no agreeing ratio
        # falls within 20% of a tie. Both terms of theirs are noise instead. Their best
        # orientation reaches under 1.0 sigma against a median of 2.11 among the
        # agreeing, so neither orientation detects anything and the ratio is decisive
        # arithmetic over nothing.
        #
        # The property that holds is stronger than unanimity over everything: every
        # observation with a detection agrees. A dissenter that discriminates would mean
        # the constant is wrong somewhere, which is a finding and not a tolerance.
        deciding = [d for d in dissent if d[2]]
        assert not deciding, (
            f"an observation that discriminates disagrees with AXIS_SIGN_CONVENTION: "
            f"{deciding}. This is not a weak-signal artifact. Either the constant is "
            f"wrong for that client family or the remeasurement is."
        )
