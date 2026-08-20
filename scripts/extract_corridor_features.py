"""Extract per-observation corridor measurements and cache them for the fusion head.

Why this is a separate cached step rather than part of feature extraction: parsing one
waterfall costs about 2.7 seconds, almost all of it axis-tick OCR, so the decisive
corpus takes roughly half an hour. A feature function that quietly cost half an hour
would get called once and then worked around.

**Both corridors are fitted, not one.** Physics predicts two different paths for the
same pass: a curve if the capturing client left the Doppler in, and a vertical line at
the receiver centre if the client removed it. Which one applies is invisible in the
metadata (A3's finding: ``doppler-correction-per-sec`` is null and ``rigctl-port`` is
4532 on both), and only 24 of 2,727 observations have a verdict. Fitting both costs
one extra matched filter on an already-decoded image, and it yields the comparison A3
used to decide correction status in the first place. So the head receives a
measurement of *whether this capture looks Doppler-corrected*, which no metadata field
carries.

Per observation:

``sigma_curved``, ``sigma_vertical``
    Matched-filter response along each predicted path, in units of the null spread.
``sigma_advantage_curved``
    ``sigma_curved - sigma_vertical``. Positive means the energy follows the Doppler
    curve, so the capture was not corrected. This is A3's discriminator.
``fitted_offset_hz``, ``fitted_offset_ppm``
    The shift that best aligns the predicted path with the image's actual energy. This
    is the physics-conditioned quantity that survives Doppler correction: even where
    the corridor is a bare vertical line, its *offset* says whether the strongest
    energy sits where the recorded downlink frequency claims.
``coverage``, ``detect_frac``, ``residual_rms_px``
    From the same fits.

A degraded parse is recorded with its reason code rather than dropped, because "the
axis could not be read" is itself informative and must not silently become a zero.

Usage:
    .venv/Scripts/python.exe scripts/extract_corridor_features.py [--limit N]
        [--out artifacts/corridor_features.json] [--decisive-only]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.corridor_fit import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    fit_corridor,
    flat_row_fraction,
    normalised_rows,
)
from pipeline.tracetriage.physics import corridor_for_obs  # noqa: E402
from pipeline.tracetriage.splits import (  # noqa: E402
    _default_pages_dir,
    _load_raw_pages,
)
from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: E402

_WATERFALL_DIR = Path("D:/tracetriage_data/snap-stage1/waterfalls")

#: Keys this script reads off ``CorridorFit.summary()``. Checked at runtime so a
#: rename in corridor_fit.py stops the extraction instead of filling the cache with
#: nulls that read as "not measurable".
_EXPECTED_FIT_KEYS = frozenset(
    {
        "sigma_at_fit",
        "fitted_offset_hz",
        "fitted_offset_ppm",
        "coverage",
        "detect_frac",
        "residual_p50_hz",
        "residual_p95_hz",
        "offset_at_bound",
        "corridor_hit",
    }
)


def _image_path(obs_id: int) -> Path:
    return _WATERFALL_DIR / f"waterfall_{obs_id}.png"


def measure_one(rec: dict[str, Any]) -> dict[str, Any]:
    """Measure one observation. Never raises; a failure is a named degraded state."""
    oid = rec["id"]
    out: dict[str, Any] = {"obs_id": oid, "degraded": None}

    phys = corridor_for_obs(rec)
    if phys.degraded is not None:
        out["degraded"] = f"PHYSICS_{phys.degraded}"
        return out
    if phys.uncorrected is None or phys.corrected is None:
        out["degraded"] = "PHYSICS_NO_CORRIDOR"
        return out

    path = _image_path(oid)
    if not path.exists():
        out["degraded"] = "NO_IMAGE"
        return out

    geom = parse_waterfall(
        path,
        observation_id=oid,
        pass_duration_s=phys.pass_duration_s,
        rx_freq_hz=phys.rx_freq_hz,
    )
    if getattr(geom, "degraded", None):
        out["degraded"] = f"GEOMETRY_{geom.degraded}"
        return out
    if geom.hz_per_px is None or geom.centre_px is None:
        out["degraded"] = "GEOMETRY_NO_SCALE"
        return out

    try:
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"))
        zs = normalised_rows(rgb, geom.crop_box)
        flat = flat_row_fraction(rgb, geom.crop_box)
        fits = {
            kind: fit_corridor(
                zs,
                corridor,
                kind,
                geom.hz_per_px,
                geom.centre_px,
                phys.rx_freq_hz,
                obs_id=oid,
                thresholds=DEFAULT_THRESHOLDS,
            ).summary()
            for kind, corridor in (
                ("uncorrected", phys.uncorrected),
                ("corrected", phys.corrected),
            )
        }
    except Exception as exc:  # noqa: BLE001 - a fit failure is data, not a crash
        out["degraded"] = f"FIT_ERROR_{type(exc).__name__}: {exc}"
        return out

    curved, vertical = fits["uncorrected"], fits["corrected"]

    # Read the keys by name, and fail loudly if a name is wrong. The first version of
    # this function asked for "sigma", "offset_hz" and "residual_rms_px", none of which
    # exist on the summary. dict.get returned None for every one, so every corridor
    # feature was null and the arm would have been reported as carrying no signal for
    # a reason that had nothing to do with the physics.
    missing = _EXPECTED_FIT_KEYS - set(curved)
    if missing:
        msg = f"CorridorFit.summary() is missing {sorted(missing)}; feature names drifted"
        raise KeyError(msg)

    sig_c, sig_v = curved["sigma_at_fit"], vertical["sigma_at_fit"]
    out.update(
        {
            "sigma_curved": sig_c,
            "sigma_vertical": sig_v,
            "sigma_advantage_curved": (
                None if sig_c is None or sig_v is None else float(sig_c - sig_v)
            ),
            # The curved fit is the one with a shape to align, so its offset is the
            # meaningful frequency measurement. The vertical fit's offset is kept
            # because on a corrected capture it is the only offset there is.
            "fitted_offset_hz": curved["fitted_offset_hz"],
            "fitted_offset_ppm": curved["fitted_offset_ppm"],
            "vertical_offset_hz": vertical["fitted_offset_hz"],
            "coverage_curved": curved["coverage"],
            "coverage_vertical": vertical["coverage"],
            "detect_frac_curved": curved["detect_frac"],
            "detect_frac_vertical": vertical["detect_frac"],
            "residual_p50_hz": curved["residual_p50_hz"],
            "residual_p95_hz": curved["residual_p95_hz"],
            "offset_at_bound": curved["offset_at_bound"],
            "corridor_hit_curved": curved["corridor_hit"],
            "hz_per_px": geom.hz_per_px,
            # Dead capture rows. Before the divisor floor was fixed these produced the
            # largest matched-filter responses in the corpus; now they are a feature.
            "flat_row_frac": flat["flat_row_frac"],
            "n_flat_rows": flat["n_flat_rows"],
            "min_row_mad": flat["min_row_mad"],
            "predicted_swing_hz": float(
                np.ptp(np.asarray(phys.uncorrected.doppler_hz, dtype=float))
            ),
        }
    )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="Stop after N observations.")
    ap.add_argument("--out", type=Path, default=_REPO / "artifacts" / "corridor_features.json")
    ap.add_argument(
        "--decisive-only",
        action="store_true",
        help="Only observations with a with-signal or without-signal label.",
    )
    args = ap.parse_args(argv)

    raw = _load_raw_pages(_default_pages_dir())
    ids = sorted(raw)
    if args.decisive_only:
        ids = [
            i for i in ids
            if raw[i].get("waterfall_status") in ("with-signal", "without-signal")
        ]
    if args.limit:
        ids = ids[: args.limit]

    print(f"measuring {len(ids)} observations", flush=True)
    results: list[dict[str, Any]] = []
    t0 = time.time()
    for n, oid in enumerate(ids, 1):
        results.append(measure_one(raw[oid]))
        if n % 25 == 0:
            rate = (time.time() - t0) / n
            print(
                f"  {n}/{len(ids)}  {rate:.2f}s/obs  "
                f"eta {(len(ids) - n) * rate / 60:.1f} min",
                flush=True,
            )

    by_state: dict[str, int] = {}
    for r in results:
        key = r["degraded"] or "measured"
        by_state[key] = by_state.get(key, 0) + 1

    payload = {
        "schema": "CORRIDOR_FEATURES",
        "schema_version": "0.1.0",
        "n_requested": len(ids),
        "decisive_only": bool(args.decisive_only),
        "elapsed_s": round(time.time() - t0, 1),
        "states": dict(sorted(by_state.items())),
        "thresholds": {
            "z_min": DEFAULT_THRESHOLDS.z_min,
            "min_detect_frac": DEFAULT_THRESHOLDS.min_detect_frac,
            "offset_ppm_limit": DEFAULT_THRESHOLDS.offset_ppm_limit,
            "search_window_factor": DEFAULT_THRESHOLDS.search_window_factor,
        },
        "rows": results,
    }
    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(json.dumps(payload["states"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
