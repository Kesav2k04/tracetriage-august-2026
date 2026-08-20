"""Feature blocks for the fusion head (unit B2).

Four blocks, kept separate so an ablation can drop one without touching the others:

``physics``
    SGP4 pass geometry and Doppler kinematics. Derived from the TLE, the station
    position and the commanded receive frequency. No pixels.
``corridor``
    What the image contains *where the physics says to look*: matched-filter response
    along the predicted curve and along the vertical line, and the frequency offset
    that best aligns them. Read from the cache written by
    ``scripts/extract_corridor_features.py`` because each measurement costs about
    three seconds of axis OCR.
``metadata``
    Transmitter and capture properties known before the pass.
``image``
    The HOG plus logistic-regression score from unit A6. Supplied by the caller, not
    computed here.

Every block is bound by ``splits.FIELD_CLASSIFICATION``. ``admissible_source_fields``
checks each source field a block reads and raises on anything not classified
``observation_time``, so the leakage rule is enforced by the code that would break it
rather than by a sentence in a receipt.

Two deliberate exclusions, both because a feature that cannot vary cannot inform:

``half_width_hz``
    A fixed parameter of the corridor model, 2000 Hz on every observation. Measured
    AUC exactly 0.5000 over one distinct value. It looks like a measurement, and unit
    A7's gate 3 failed precisely by comparing two constants, so it is named here
    rather than quietly dropped.
``corridor_containment``
    Whether the predicted trace fits inside the image's frequency window. The window
    spans 832 px at 80 to 128 Hz per px, which is 66 to 106 kHz, against a predicted
    Doppler swing of 13 to 18 kHz. It always fits, so the feature is a constant true
    and was dropped before it was built.

``rx_freq_hz`` is excluded for a different reason. It is very nearly a transmitter
identifier: 613 transmitters each sit at their own downlink frequency, so a model
given the raw value can memorise which transmitter it is looking at. The band it falls
in is kept, and the *offset* between the commanded frequency and the catalogue
downlink is kept, because a difference is not an identity.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .physics import corridor_for_obs
from .splits import FIELD_CLASSIFICATION

_REPO = Path(__file__).resolve().parents[2]
_CORRIDOR_CACHE = _REPO / "artifacts" / "corridor_features.json"

#: Amateur satellite bands, by receive frequency. Coarse on purpose: the band carries
#: propagation and receiver-hardware differences, while the exact frequency carries
#: transmitter identity.
_BANDS: tuple[tuple[str, float, float], ...] = (
    ("vhf_2m", 143.0e6, 147.0e6),
    ("uhf_70cm", 430.0e6, 440.0e6),
    ("uhf_400", 399.0e6, 403.0e6),
    ("l_band", 1.2e9, 1.3e9),
    ("s_band", 2.2e9, 2.5e9),
)


def band_of(rx_freq_hz: float | None) -> str:
    if rx_freq_hz is None or not math.isfinite(rx_freq_hz):
        return "unknown"
    for name, lo, hi in _BANDS:
        if lo <= rx_freq_hz <= hi:
            return name
    return "other"


# ---------------------------------------------------------------------------
# The admissibility gate
# ---------------------------------------------------------------------------

#: Source record fields each block is allowed to read. Declared, then checked against
#: FIELD_CLASSIFICATION, so adding a field to a block cannot quietly admit a label.
BLOCK_SOURCE_FIELDS: dict[str, tuple[str, ...]] = {
    "physics": ("tle1", "tle2", "start", "end", "station_lat", "station_lng", "station_alt",
                "client_metadata", "observation_frequency", "transmitter_downlink_low"),
    "corridor": ("tle1", "tle2", "start", "end", "station_lat", "station_lng", "station_alt",
                 "client_metadata", "observation_frequency", "waterfall"),
    "metadata": ("transmitter_mode", "transmitter_type", "transmitter_baud",
                 "transmitter_downlink_low", "transmitter_downlink_drift",
                 "transmitter_invert", "transmitter_status", "transmitter_unconfirmed",
                 "client_version", "client_metadata", "observation_frequency",
                 "rise_azimuth", "set_azimuth", "max_altitude", "station_lat"),
    "image": ("waterfall",),
}


def admissible_source_fields(blocks: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Check every source field the named blocks read is observation-time available.

    Raises ``ValueError`` on the first field classified ``post_observation`` or
    ``identifier``, or on a field the classification does not cover at all. The
    leakage rule then holds because the code that would break it refuses to run,
    which is a different kind of claim from a receipt that says it holds.
    """
    names = blocks if blocks is not None else tuple(BLOCK_SOURCE_FIELDS)
    checked: dict[str, list[str]] = {}
    for block in names:
        fields = BLOCK_SOURCE_FIELDS[block]
        for field in fields:
            entry = FIELD_CLASSIFICATION.get(field)
            if entry is None:
                msg = (
                    f"block {block!r} reads {field!r}, which FIELD_CLASSIFICATION does "
                    "not cover. Classify it before using it: an unclassified field is a "
                    "leak nobody has ruled out."
                )
                raise ValueError(msg)
            kind, reason = entry
            if kind != "observation_time":
                msg = (
                    f"block {block!r} reads {field!r}, classified {kind!r}: {reason} "
                    "Only observation_time fields may become features."
                )
                raise ValueError(msg)
        checked[block] = list(fields)
    return {"blocks": checked, "n_fields": sum(len(v) for v in checked.values())}


# ---------------------------------------------------------------------------
# Physics block
# ---------------------------------------------------------------------------

PHYSICS_FEATURES: tuple[str, ...] = (
    "max_elevation_deg",
    "pass_duration_s",
    "doppler_swing_hz",
    "doppler_rate_max_hz_s",
    "doppler_rate_at_tca_hz_s",
    "tle_epoch_age_days",
    "tca_frac",
    "rx_offset_from_catalogue_hz",
)


def physics_features(rec: dict[str, Any]) -> dict[str, float | None]:
    """Pass geometry and Doppler kinematics. ``None`` where physics is degraded.

    Individually these are weak. Measured AUC on the 518 decisive training
    observations of the chronological split, before any head was fitted:
    doppler_rate_max 0.567, tle_epoch_age_days 0.550, doppler_swing 0.547,
    tca_frac 0.538, max_elevation 0.521, pass_duration 0.509,
    rx_offset_from_catalogue 0.466. That is the honest starting point, and it is why
    the block is evaluated jointly against the prior-only floor rather than assumed
    to help because it is physics.
    """
    out: dict[str, float | None] = dict.fromkeys(PHYSICS_FEATURES)
    phys = corridor_for_obs(rec)
    if phys.degraded is not None or phys.uncorrected is None:
        return out

    c = phys.uncorrected
    dop = np.asarray(c.doppler_hz, dtype=float)
    fracs = np.asarray(c.fracs, dtype=float)
    duration = phys.pass_duration_s or 0.0
    dt = np.diff(fracs) * duration
    rates = np.abs(np.diff(dop) / np.maximum(dt, 1e-9)) if dop.size > 1 else np.array([0.0])

    # The steepest Doppler slope falls at closest approach, where a tracking receiver
    # is most likely to smear the trace. Reported at TCA as well as at its maximum,
    # because tca_frac is near 0.5 on every pass in this corpus and the two can
    # separate on a corpus where it is not.
    tca_idx = int(np.clip(round(c.tca_frac * (rates.size - 1)), 0, max(rates.size - 1, 0)))

    catalogue = rec.get("transmitter_downlink_low")
    rx = phys.rx_freq_hz
    out.update(
        {
            "max_elevation_deg": float(c.max_elevation_deg),
            "pass_duration_s": float(duration),
            "doppler_swing_hz": float(dop.max() - dop.min()) if dop.size else None,
            "doppler_rate_max_hz_s": float(rates.max()),
            "doppler_rate_at_tca_hz_s": float(rates[tca_idx]) if rates.size else None,
            "tle_epoch_age_days": (
                float(phys.tle_epoch_age_days) if phys.tle_epoch_age_days is not None else None
            ),
            "tca_frac": float(c.tca_frac),
            "rx_offset_from_catalogue_hz": (
                float(rx - catalogue) if (rx is not None and catalogue) else None
            ),
        }
    )
    return out


# ---------------------------------------------------------------------------
# Corridor block
# ---------------------------------------------------------------------------

CORRIDOR_FEATURES: tuple[str, ...] = (
    "sigma_curved",
    "sigma_vertical",
    "sigma_advantage_curved",
    "fitted_offset_ppm",
    "abs_fitted_offset_ppm",
    "detect_frac_curved",
    "detect_frac_vertical",
    "residual_p50_hz",
    "predicted_swing_hz",
    # Fraction of the waterfall with no luminance variation at all: dead capture time.
    # It arrived as a feature by way of a bug, since flat rows were producing the
    # corpus's largest matched-filter responses before the divisor floor was fixed.
    "flat_row_frac",
)


def load_corridor_cache(path: Path | None = None) -> dict[int, dict[str, Any]]:
    """Load the corridor measurement cache, keyed by observation id.

    Returns an empty mapping when the cache is absent, so a caller can run without it
    and report the corridor block as unavailable rather than crash. An absent cache
    and a cache full of degraded rows are different things and both are visible: rows
    keep their ``degraded`` reason code.
    """
    p = path or _CORRIDOR_CACHE
    if not p.exists():
        return {}
    payload = json.loads(p.read_text(encoding="utf-8"))
    return {int(r["obs_id"]): r for r in payload.get("rows", [])}


def corridor_features(
    obs_id: int,
    cache: dict[int, dict[str, Any]],
) -> dict[str, float | None]:
    """Corridor measurements for one observation, or all-``None`` if unmeasured.

    ``abs_fitted_offset_ppm`` is carried alongside the signed value because the
    physical claim is about magnitude: a receiver 32 ppm off its catalogue frequency
    is equally notable in either direction, while the sign belongs to the individual
    station's local oscillator.
    """
    out: dict[str, float | None] = dict.fromkeys(CORRIDOR_FEATURES)
    row = cache.get(obs_id)
    if row is None or row.get("degraded"):
        return out
    for name in CORRIDOR_FEATURES:
        if name == "abs_fitted_offset_ppm":
            v = row.get("fitted_offset_ppm")
            out[name] = abs(float(v)) if v is not None else None
        else:
            v = row.get(name)
            out[name] = float(v) if isinstance(v, (int, float)) else None
    return out


# ---------------------------------------------------------------------------
# Metadata block
# ---------------------------------------------------------------------------

METADATA_NUMERIC: tuple[str, ...] = (
    "transmitter_baud",
    "transmitter_downlink_drift",
    "max_altitude_deg_api",
    "azimuth_sweep_deg",
    "abs_station_lat",
)
METADATA_CATEGORICAL: tuple[str, ...] = (
    "band",
    "transmitter_mode",
    "transmitter_type",
    "client_family",
    "transmitter_status",
)


def metadata_features(rec: dict[str, Any], client_family: str | None = None) -> dict[str, Any]:
    """Transmitter and capture properties known before the pass.

    ``azimuth_sweep_deg`` is the shorter arc between rise and set azimuth, which
    stands in for how much of the sky the pass crossed. ``abs_station_lat`` keeps
    latitude as a magnitude: the physical asymmetry is equatorial versus polar, and
    the signed value would let the model separate hemispheres, which is closer to
    identifying the station than to describing the pass.

    ``rx_freq_hz`` is deliberately absent. See the module docstring.
    """
    rise, sett = rec.get("rise_azimuth"), rec.get("set_azimuth")
    sweep: float | None = None
    if isinstance(rise, (int, float)) and isinstance(sett, (int, float)):
        d = abs(float(sett) - float(rise)) % 360.0
        sweep = min(d, 360.0 - d)

    lat = rec.get("station_lat")
    from .physics import rx_freq_of

    invert = rec.get("transmitter_invert")
    return {
        "transmitter_baud": _num(rec.get("transmitter_baud")),
        "transmitter_downlink_drift": _num(rec.get("transmitter_downlink_drift")),
        "max_altitude_deg_api": _num(rec.get("max_altitude")),
        "azimuth_sweep_deg": sweep,
        "abs_station_lat": abs(float(lat)) if isinstance(lat, (int, float)) else None,
        "band": band_of(rx_freq_of(rec)),
        "transmitter_mode": str(rec.get("transmitter_mode") or "unknown"),
        "transmitter_type": str(rec.get("transmitter_type") or "unknown"),
        "client_family": str(client_family or "unknown"),
        "transmitter_status": str(rec.get("transmitter_status") or "unknown"),
        "transmitter_invert": 1.0 if invert else 0.0,
        "transmitter_unconfirmed": 1.0 if rec.get("transmitter_unconfirmed") else 0.0,
    }


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return None
