"""Physics corridor module for TraceTriage.

Given one SatNOGS observation record (no external joins, no TLE lookups), compute
the two expected-frequency corridor shapes for that pass:

  - ``uncorrected`` — the full Doppler S-curve, for a capture that was NOT corrected
    in flight.
  - ``corrected``   — a near-vertical residual band centred close to rx-freq, for a
    capture that WAS Doppler-corrected at the ground station.

Both shapes are always emitted so the caller and the model can use their
disagreement as a feature.  Collapsing to one shape early destroys the signal
that TraceTriage ranks on (see A3: docs/DOPPLER_CORRECTION_FINDING.md).

CALIBRATION FACTS — do not re-derive, do not check by eye
==========================================================
These were established in A3 and re-confirmed here. Both were wrong in the first
implementation, and together they cancel (a Doppler curve is near odd-symmetric
about closest approach), so a visual check cannot find the defect:

  * Time runs bottom to top.  The top row of a SatNOGS waterfall is the END of
    the pass.  The ``row_frac`` convention here is therefore::

        row_frac = elapsed / duration            (0 at the BOTTOM, 1 at the TOP)

    and a row index maps onto it by inverting, because row 0 is the top::

        row_frac = 1.0 - (row + 0.5) / image_height

    ``fracs`` in the returned corridor carry the same convention: 0 = pass start
    (which maps to the BOTTOM of the image), 1 = pass end (which maps to the TOP).

  * The plotted frequency axis runs AGAINST the Doppler sign.  A positive Doppler
    shift (satellite approaching → higher received frequency) appears to the LEFT
    in the rendered image.  The returned ``doppler_hz`` values are physics-sign
    (positive when approaching); the caller applies ``axis_sign_convention = -1``
    when mapping them to pixel columns.

FREE CONSTANT OFFSET
====================
The three uncorrected observations in A3 sat 14.0, 2.4 and 1.8 kHz off the
predicted curve.  The corridor is NOT assumed to be centred on rx-freq.
``FREQ_OFFSET_SEARCH_HZ`` (±20 kHz) is the stated search range that A7 and the
model scan over, which clears the largest measured offset by about 40 percent.

DEGRADED STATES
===============
All degrade states return a named reason code in ``PhysicsResult.degraded`` and
never raise.  Codes:

  ``MISSING_TLE``      tle1 or tle2 absent or empty
  ``STALE_TLE``        TLE epoch more than ``TLE_MAX_EPOCH_AGE_DAYS`` from the pass
                       midpoint
  ``SGP4_ERROR``       SGP4 returned a non-zero error code on every sample
  ``MISSING_STATION``  station_lat, station_lng or station_alt missing
  ``MISSING_FREQ``     rx-freq absent in client_metadata and no usable fallback

Usage::

    from pipeline.tracetriage.physics import corridor_for_obs

    result = corridor_for_obs(obs_record)
    if result.degraded:
        # handle named failure
    else:
        fracs   = result.uncorrected.fracs      # list[float], pass-time fractions 0–1
        dop_hz  = result.uncorrected.doppler_hz # list[float], physics-sign Hz
        half_w  = result.uncorrected.half_width_hz  # corridor half-width in Hz
        # corrected corridor:
        result.corrected.half_width_hz          # typically CORRECTED_CORRIDOR_HZ
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass   # sgp4 imports are deferred so the module is importable without them


# ---------------------------------------------------------------------------
# Physical and WGS-84 constants
# ---------------------------------------------------------------------------

C_M_PER_S: float = 299_792_458.0        # speed of light, m/s

WGS84_A: float = 6_378.137              # km, semi-major axis
WGS84_F: float = 1.0 / 298.257_223_563  # flattening
OMEGA_EARTH: float = 7.292_115_9e-5     # rad/s, Earth sidereal rotation rate

# ---------------------------------------------------------------------------
# Corridor parameters
# ---------------------------------------------------------------------------

# Number of time samples across the pass.
N_SAMPLES: int = 512

# Half-width of the near-vertical corridor for a corrected capture (Hz).
#
# Measured, not copied. The 200 Hz used in A3 was a reference line drawn on an
# overlay, not a containment band, and reusing it here would have failed kill
# gate 3 for a reason that is not real: the within-pass wander of the four
# corrected carriers A3 measured is 77, 639, 639 and 1935 Hz, so a 200 Hz
# half-width fails to contain three of the four. 1935 Hz needs 968 Hz of
# half-width; 1200 leaves about 24 percent headroom on the worst case seen.
CORRECTED_CORRIDOR_HZ: float = 1_200.0

# Half-width of the Doppler curve band for an uncorrected capture (Hz).
#
# Deliberately wide. On the one uncorrected observation in A3 with enough
# per-row detections to measure (14740031, 39 rows), the residual around the
# fitted curve had a 95th percentile of 123 Hz and a maximum of 140 Hz. 2 kHz
# is roughly 16 times that, kept because a corridor that is too narrow fails
# kill gate 3 for a reason that is not real, while one that is too wide only
# costs discrimination. Revisit at snapshot scale, with more than one
# observation behind it.
UNCORRECTED_CORRIDOR_HZ: float = 2_000.0

# TLE epoch staleness threshold.  If |epoch - pass_midpoint| > this, emit STALE_TLE.
TLE_MAX_EPOCH_AGE_DAYS: float = 14.0

# Stated search range for the free constant frequency offset (Section 5.4 of the
# task prompt).  The three uncorrected observations sat 14.0, 2.4 and 1.8 kHz off
# the predicted curve, so ±20 kHz covers the largest of those with about 40
# percent to spare. It is not a wide margin; widen it if a larger offset turns
# up at snapshot scale.
FREQ_OFFSET_SEARCH_HZ: float = 20_000.0

# Axis sign convention: the plotted frequency axis runs AGAINST the Doppler sign.
# positive Doppler (approaching) → LEFT on the rendered image.
# The caller must multiply physics doppler_hz by this before mapping to pixels.
AXIS_SIGN_CONVENTION: int = -1


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Corridor:
    """One expected-frequency corridor for a pass.

    ``fracs``       pass-time fractions in [0, 1].  0 = pass start = BOTTOM of
                    the rendered image (because time runs bottom-to-top).
    ``doppler_hz``  physics-sign Doppler offset from rx-freq in Hz.  Positive when
                    the satellite is approaching (higher received frequency, but
                    that is to the LEFT on the axis — see AXIS_SIGN_CONVENTION).
    ``half_width_hz``  corridor half-width in Hz; apply ±this around each sample.
    ``max_elevation_deg``  peak elevation reached in this pass (degrees).
    ``tca_frac``    pass-time fraction of the highest elevation sample.
    """

    fracs: list[float]
    doppler_hz: list[float]
    half_width_hz: float
    max_elevation_deg: float
    tca_frac: float


@dataclass(frozen=True)
class PhysicsResult:
    """Per-observation physics corridor result.

    When ``degraded`` is not None, ``uncorrected`` and ``corrected`` are None and
    the caller must handle the named failure gracefully.
    """

    uncorrected: Corridor | None
    corrected: Corridor | None
    degraded: str | None          # None = success; one of the named reason codes
    obs_id: int | None
    rx_freq_hz: float | None
    pass_duration_s: float | None
    tle_epoch_age_days: float | None    # |epoch − midpoint| in days; None on error


# ---------------------------------------------------------------------------
# Geodetic helpers
# ---------------------------------------------------------------------------


def station_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> np.ndarray:
    """Convert geodetic coordinates to WGS-84 ECEF (kilometres)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    e2 = WGS84_F * (2.0 - WGS84_F)
    n = WGS84_A / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    alt_km = alt_m / 1000.0
    return np.array([
        (n + alt_km) * math.cos(lat) * math.cos(lon),
        (n + alt_km) * math.cos(lat) * math.sin(lon),
        (n * (1.0 - e2) + alt_km) * math.sin(lat),
    ])


def gmst(dt: datetime) -> float:
    """Greenwich Mean Sidereal Time in radians for a UTC datetime.

    Uses the IAU 1982 expression (accurate to a few arcseconds over decades):
        GMST = 280.46061837 + 360.98564736629 * d_J2000
    where d_J2000 is fractional days since J2000.0 (= 2000-01-01 12:00:00 UTC).

    This is the same formulation as the A3 investigation script (which reproduced
    max_altitude to 0.18 degrees), promoted into the production module.
    """
    d_j2000 = (dt - datetime(2000, 1, 1, 12, tzinfo=UTC)).total_seconds() / 86_400.0
    return math.radians(280.460_618_37 + 360.985_647_366_29 * d_j2000) % (2.0 * math.pi)


def eci_to_ecef(v_eci: np.ndarray, dt: datetime) -> np.ndarray:
    """Rotate an ECI vector into ECEF at the given UTC epoch.

    Uses the GMST rotation only (no polar motion, no nutation corrections).
    This level of accuracy reproduced max_altitude to 0.18 degrees in A3.
    """
    theta = gmst(dt)
    ct, st = math.cos(theta), math.sin(theta)
    return np.array([
        ct * v_eci[0] + st * v_eci[1],
        -st * v_eci[0] + ct * v_eci[1],
        v_eci[2],
    ])


def ecef_velocity(v_eci: np.ndarray, r_ecef: np.ndarray, dt: datetime) -> np.ndarray:
    """Convert an ECI velocity to ECEF, subtracting Earth's rotation.

    SGP4 returns velocity in ECI (km/s).  To compute the range rate to a fixed
    ground station in ECEF we need the satellite velocity in the same frame,
    which includes subtracting the surface velocity of the Earth:
        v_ecef = R(GMST) * v_eci - ω × r_ecef
    """
    v_rot = eci_to_ecef(v_eci, dt)
    omega = np.array([0.0, 0.0, OMEGA_EARTH])
    return v_rot - np.cross(omega, r_ecef)


# ---------------------------------------------------------------------------
# TLE epoch helper
# ---------------------------------------------------------------------------


def tle_epoch_datetime(tle1: str) -> datetime | None:
    """Parse the epoch from TLE line 1 and return a UTC datetime.

    TLE line 1 columns 19-31 (0-indexed): epoch year (2 digits) + day-of-year
    as a decimal (ddd.dddddddd).  Returns None if parsing fails.
    """
    try:
        epoch_str = tle1[18:32].strip()
        year_2d = int(epoch_str[:2])
        day_frac = float(epoch_str[2:])
        # Two-digit year: 57–99 → 1957–1999; 00–56 → 2000–2056 (NORAD convention)
        year = (1900 + year_2d) if year_2d >= 57 else (2000 + year_2d)
        epoch = datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day_frac - 1)
        return epoch
    except Exception:
        return None


# ---------------------------------------------------------------------------
# rx-freq extraction (identical logic to A3 script, production form)
# ---------------------------------------------------------------------------


def rx_freq_of(obs: dict) -> float | None:
    """Return the tuned receive frequency in Hz.

    The truth is ``client_metadata.radio.parameters.rx-freq``, which is a
    JSON-encoded string (not a nested object — see contracts/source_observation).
    Falls back to ``observation_frequency`` then ``transmitter_downlink_low``.
    """
    try:
        meta = json.loads(obs["client_metadata"])
        v = meta.get("radio", {}).get("parameters", {}).get("rx-freq")
        if v:
            return float(v)
    except Exception:
        pass
    v = obs.get("observation_frequency") or obs.get("transmitter_downlink_low")
    return float(v) if v else None


# ---------------------------------------------------------------------------
# Core propagation
# ---------------------------------------------------------------------------


def propagate_pass(
    tle1: str,
    tle2: str,
    start_dt: datetime,
    end_dt: datetime,
    site_ecef: np.ndarray,
    freq_hz: float,
    n_samples: int = N_SAMPLES,
) -> tuple[list[float], list[float], list[float], list[int]]:
    """Propagate a satellite pass and compute the Doppler curve.

    Returns
    -------
    fracs : list[float]
        Pass-time fractions at which propagation succeeded (0 = start, 1 = end).
    doppler_hz : list[float]
        Physics-sign Doppler shift in Hz.  Positive = satellite approaching =
        higher received frequency.
        NOTE: on the rendered waterfall axis, positive Doppler maps to the LEFT
        (AXIS_SIGN_CONVENTION = -1).  This function returns raw physics values;
        the sign convention is the caller's responsibility.
    elevations_deg : list[float]
        Elevation above the station horizon at each sample (degrees).
    error_codes : list[int]
        SGP4 error codes for samples where err != 0 (should be empty on success).
    """
    from sgp4.api import Satrec, jday  # deferred: keeps module importable without sgp4

    sat = Satrec.twoline2rv(tle1, tle2)
    duration_s = (end_dt - start_dt).total_seconds()

    site_hat = site_ecef / np.linalg.norm(site_ecef)

    fracs: list[float] = []
    doppler_hz: list[float] = []
    elevations_deg: list[float] = []
    error_codes: list[int] = []

    for i in range(n_samples):
        frac = i / (n_samples - 1)
        t = start_dt + timedelta(seconds=duration_s * frac)

        jd_w, jd_f = jday(
            t.year, t.month, t.day,
            t.hour, t.minute, t.second + t.microsecond / 1_000_000.0,
        )
        err, r_eci, v_eci = sat.sgp4(jd_w, jd_f)
        if err != 0:
            error_codes.append(err)
            continue

        r_ecef = eci_to_ecef(np.array(r_eci), t)
        v_ecef_sat = ecef_velocity(np.array(v_eci), r_ecef, t)

        los = r_ecef - site_ecef
        rng = float(np.linalg.norm(los))
        if rng < 1e-9:
            continue
        los_hat = los / rng

        # Range rate: positive when receding, so Doppler is negated.
        range_rate_km_s = float(np.dot(los_hat, v_ecef_sat))
        dop = -range_rate_km_s * 1_000.0 / C_M_PER_S * freq_hz  # Hz, physics sign

        el_rad = math.asin(max(-1.0, min(1.0, float(np.dot(los_hat, site_hat)))))
        el_deg = math.degrees(el_rad)

        fracs.append(frac)
        doppler_hz.append(dop)
        elevations_deg.append(el_deg)

    return fracs, doppler_hz, elevations_deg, error_codes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def corridor_for_obs(obs: dict) -> PhysicsResult:
    """Compute both corridor shapes for one observation record.

    This is the main entry point.  It never raises; all error conditions return
    a PhysicsResult with a named ``degraded`` reason code.

    Parameters
    ----------
    obs :
        A SatNOGS observation record dict as stored by the snapshot builder.
        Must contain the fields defined in ``contracts/source_observation.schema.json``.

    Returns
    -------
    PhysicsResult
        On success: ``uncorrected`` and ``corrected`` are both populated,
        ``degraded`` is None.
        On failure: ``degraded`` is one of the named reason codes, ``uncorrected``
        and ``corrected`` are both None.
    """
    obs_id: int | None = obs.get("id")
    rx_freq: float | None = None
    pass_dur: float | None = None
    epoch_age: float | None = None

    def _fail(reason: str) -> PhysicsResult:
        return PhysicsResult(
            uncorrected=None,
            corrected=None,
            degraded=reason,
            obs_id=obs_id,
            rx_freq_hz=rx_freq,
            pass_duration_s=pass_dur,
            tle_epoch_age_days=epoch_age,
        )

    # ── 1. TLE presence ──────────────────────────────────────────────────────
    tle1 = obs.get("tle1") or ""
    tle2 = obs.get("tle2") or ""
    if not tle1.strip() or not tle2.strip():
        return _fail("MISSING_TLE")

    # ── 2. Station coordinates ───────────────────────────────────────────────
    try:
        lat = float(obs["station_lat"])
        lon = float(obs["station_lng"])
        alt = float(obs["station_alt"])
    except (KeyError, TypeError, ValueError):
        return _fail("MISSING_STATION")

    # ── 3. Pass timing ───────────────────────────────────────────────────────
    try:
        start_dt = datetime.fromisoformat(obs["start"].replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(obs["end"].replace("Z", "+00:00"))
        pass_dur = (end_dt - start_dt).total_seconds()
    except Exception:
        return _fail("MISSING_STATION")   # timing is always present; fail gracefully

    # ── 4. Receive frequency ─────────────────────────────────────────────────
    rx_freq = rx_freq_of(obs)
    if rx_freq is None or rx_freq <= 0.0:
        return _fail("MISSING_FREQ")

    # ── 5. TLE epoch staleness ───────────────────────────────────────────────
    midpoint = start_dt + timedelta(seconds=pass_dur / 2.0)
    tle_epoch = tle_epoch_datetime(tle1)
    if tle_epoch is not None:
        epoch_age = abs((midpoint - tle_epoch).total_seconds()) / 86_400.0
        if epoch_age > TLE_MAX_EPOCH_AGE_DAYS:
            return PhysicsResult(
                uncorrected=None,
                corrected=None,
                degraded="STALE_TLE",
                obs_id=obs_id,
                rx_freq_hz=rx_freq,
                pass_duration_s=pass_dur,
                tle_epoch_age_days=epoch_age,
            )

    # ── 6. Propagate ─────────────────────────────────────────────────────────
    site = station_ecef(lat, lon, alt)
    fracs, dops, els, errs = propagate_pass(tle1, tle2, start_dt, end_dt, site, rx_freq)

    if not fracs:
        # Every sample failed — could be a decayed object, bad TLE line, etc.
        return _fail("SGP4_ERROR")

    # ── 7. Build corridor objects ─────────────────────────────────────────────
    max_el = max(els)
    tca_idx = int(np.argmax(np.asarray(els)))
    tca_frac = fracs[tca_idx]

    uncorrected = Corridor(
        fracs=fracs,
        doppler_hz=dops,
        half_width_hz=UNCORRECTED_CORRIDOR_HZ,
        max_elevation_deg=max_el,
        tca_frac=tca_frac,
    )

    # The corrected corridor: a near-vertical band.  The Doppler values are all
    # zero (the correction removes the bulk of the shift); the half_width captures
    # the residual stability the matched filter should look inside.
    corrected = Corridor(
        fracs=fracs,
        doppler_hz=[0.0] * len(fracs),
        half_width_hz=CORRECTED_CORRIDOR_HZ,
        max_elevation_deg=max_el,
        tca_frac=tca_frac,
    )

    return PhysicsResult(
        uncorrected=uncorrected,
        corrected=corrected,
        degraded=None,
        obs_id=obs_id,
        rx_freq_hz=rx_freq,
        pass_duration_s=pass_dur,
        tle_epoch_age_days=epoch_age,
    )


# ---------------------------------------------------------------------------
# Convenience: image-row → corridor pixel column
# ---------------------------------------------------------------------------


def corridor_columns(
    corridor: Corridor,
    hz_per_px: float,
    centre_px: float,
    image_height: int,
    freq_offset_hz: float = 0.0,
) -> np.ndarray:
    """Map a Corridor to pixel columns for each image row.

    Parameters
    ----------
    corridor :
        A Corridor as returned by corridor_for_obs.
    hz_per_px :
        Frequency scale from WaterfallGeometry.
    centre_px :
        The pixel column corresponding to rx-freq (0 Hz offset).
    image_height :
        Total height of the (cropped) plot region in pixels.
    freq_offset_hz :
        Free constant offset to apply (search range ±FREQ_OFFSET_SEARCH_HZ).
        The uncorrected traces sat 14.0, 2.4 and 1.8 kHz off the predicted curve.

    Returns
    -------
    np.ndarray, shape (image_height,)
        Pixel column for each image row (float).  Use np.rint(...).astype(int) for
        rasterisation.  Values outside [0, width) indicate the corridor left the
        plot.

    Notes
    -----
    Time runs bottom to top on the waterfall image:
        row 0     = top    = END of pass   (frac = 1)
        row H - 1 = bottom = START of pass (frac = 0)

    The frequency axis runs AGAINST the Doppler sign:
        positive Doppler (approaching) → LEFT = lower pixel column
        AXIS_SIGN_CONVENTION = -1 is applied here.
    """
    rows = np.arange(image_height)
    # row_frac is the pass-time fraction 0–1; 0=bottom, 1=top → invert row index
    row_fracs = 1.0 - (rows + 0.5) / image_height
    interp_hz = np.interp(
        row_fracs,
        np.asarray(corridor.fracs),
        np.asarray(corridor.doppler_hz),
    )
    return (
        centre_px
        + AXIS_SIGN_CONVENTION * (interp_hz + freq_offset_hz) / hz_per_px
    )
