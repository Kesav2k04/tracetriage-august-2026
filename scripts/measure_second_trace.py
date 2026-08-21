"""Survey: how often does a second satellite appear in the same waterfall?

The failure-injection unit requires every named failure mode to produce a named
degraded state. Eleven of the twelve did. Nothing counted the traces in an image, so a
second carrier was averaged into the background the first one is measured against, and
an image with two satellites in it read as an image with one satellite and noisier
surroundings.

``corridor_fit.second_trace_evidence`` names it. This script answers the question that
decides whether the detector is worth anything: how often does it fire on real data. A
detector that fires on half the corpus is wrong. One that fires on none of it has never
been exercised outside a synthetic test. The number belongs in a receipt rather than in
a sentence, so this writes one.

Why this is not wired into the gate's artifact-freshness check: it reads the 4 GB
snapshot at D:/tracetriage_data/snap-stage1, which no clean clone and no CI runner has.
``scripts/check_artifact_freshness.py`` says the same about itself. It is deterministic,
so a second run over the same snapshot writes identical bytes.

Usage::

    .venv\\Scripts\\python.exe scripts\\measure_second_trace.py --decisive-only
    .venv\\Scripts\\python.exe scripts\\measure_second_trace.py --limit 50
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
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.corridor_fit import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    max_coherent_jump_px,
    second_trace_evidence,
)
from pipeline.tracetriage.physics import corridor_for_obs  # noqa: E402
from pipeline.tracetriage.splits import (  # noqa: E402
    _default_pages_dir,
    _load_raw_pages,
)
from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: E402

_WATERFALL_DIR = Path("D:/tracetriage_data/snap-stage1/waterfalls")


def _image_path(obs_id: int) -> Path:
    return _WATERFALL_DIR / f"waterfall_{obs_id}.png"


def measure_one(rec: dict[str, Any]) -> dict[str, Any]:
    """Measure one observation. Never raises; a failure is a named state."""
    oid = rec["id"]
    out: dict[str, Any] = {"obs_id": oid, "state": None}

    phys = corridor_for_obs(rec)
    if phys.degraded is not None:
        out["state"] = f"PHYSICS_{phys.degraded}"
        return out
    if phys.corrected is None:
        out["state"] = "PHYSICS_NO_CORRIDOR"
        return out

    path = _image_path(oid)
    if not path.exists():
        out["state"] = "NO_IMAGE"
        return out

    geom = parse_waterfall(
        path,
        observation_id=oid,
        pass_duration_s=phys.pass_duration_s,
        rx_freq_hz=phys.rx_freq_hz,
    )
    if getattr(geom, "degraded", None):
        out["state"] = f"GEOMETRY_{geom.degraded}"
        return out
    if geom.hz_per_px is None or geom.crop_box is None:
        out["state"] = "GEOMETRY_NO_SCALE"
        return out

    half_width_hz = phys.corrected.half_width_hz
    if not half_width_hz or half_width_hz <= 0:
        out["state"] = "NO_HALF_WIDTH"
        return out

    n_image_rows = geom.crop_box.height()
    if n_image_rows <= 0:
        out["state"] = "GEOMETRY_NO_ROWS"
        return out
    seconds_per_row = phys.pass_duration_s / n_image_rows

    # The exclusion window is the fitter's own per-row search window: a peak inside it
    # is the trace the fit is already following. The jump bound is Doppler physics,
    # converted into this image's pixels.
    window_px = DEFAULT_THRESHOLDS.search_window_factor * (half_width_hz / geom.hz_per_px)
    max_jump = max_coherent_jump_px(geom.hz_per_px, seconds_per_row)

    try:
        with Image.open(path) as im:
            rgb = np.asarray(im.convert("RGB"))
        ev = second_trace_evidence(
            rgb, geom.crop_box, window_px=window_px, max_jump_px=max_jump
        )
    except Exception as exc:  # noqa: BLE001 - a measurement failure is data, not a crash
        out["state"] = "MEASUREMENT_ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    out["state"] = "measured" if ev["measurable"] else f"UNMEASURABLE_{ev['why_not']}"
    out["hz_per_px"] = geom.hz_per_px
    out["seconds_per_row"] = seconds_per_row
    out["window_px"] = window_px
    out["max_jump_px"] = max_jump
    out["waterfall_status"] = rec.get("waterfall_status")
    out.update(
        {
            "n_rows": ev["n_rows"],
            "n_rows_primary_detected": ev["n_rows_primary_detected"],
            "n_rows_second_detected": ev["n_rows_second_detected"],
            "second_frac_of_primary_rows": ev["second_frac_of_primary_rows"],
            "median_jump_px": ev["median_jump_px"],
            "coherent": ev["coherent"],
            "reason": ev["reason"],
        }
    )
    return out


def _percentiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    a = np.asarray(values, dtype=float)
    return {
        "min": float(a.min()),
        "p10": float(np.percentile(a, 10)),
        "p50": float(np.percentile(a, 50)),
        "p90": float(np.percentile(a, 90)),
        "max": float(a.max()),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Second-trace incidence survey.")
    ap.add_argument("--limit", type=int, default=0, help="Stop after N observations.")
    ap.add_argument(
        "--decisive-only",
        action="store_true",
        help="Only observations carrying a with-signal or without-signal label.",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO / "artifacts" / "SECOND_TRACE_SURVEY.json",
    )
    args = ap.parse_args(argv)

    raw = _load_raw_pages(_default_pages_dir())
    ids = sorted(raw)
    if args.decisive_only:
        ids = [
            i
            for i in ids
            if raw[i].get("waterfall_status") in ("with-signal", "without-signal")
        ]
    if args.limit:
        ids = ids[: args.limit]

    print(f"measuring {len(ids)} observations", flush=True)
    rows: list[dict[str, Any]] = []
    t0 = time.time()
    for n, oid in enumerate(ids, 1):
        rows.append(measure_one(raw[oid]))
        if n % 25 == 0:
            rate = (time.time() - t0) / n
            print(
                f"  {n}/{len(ids)}  {rate:.2f}s/obs  "
                f"eta {(len(ids) - n) * rate / 60:.1f} min",
                flush=True,
            )

    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1

    measured = [r for r in rows if r["state"] == "measured"]
    fired = [r for r in measured if r["reason"] == "MULTIPLE_TRACES_SUSPECTED"]
    # Rows that had a coherent second peak but not in enough rows, and rows that had
    # enough rows but no coherence. Reported separately because they say different
    # things about the detector: the first is a near miss, the second is interference.
    short_of_frac = [
        r for r in measured if r["coherent"] and r["reason"] is None
    ]
    incoherent = [r for r in measured if not r["coherent"]]

    payload = {
        "schema": "SECOND_TRACE_SURVEY",
        "schema_version": "0.1.0",
        "snapshot": str(_WATERFALL_DIR),
        "n_requested": len(ids),
        "decisive_only": bool(args.decisive_only),
        "elapsed_s": round(time.time() - t0, 1),
        "thresholds": {
            "z_min": DEFAULT_THRESHOLDS.z_min,
            "min_detect_frac": DEFAULT_THRESHOLDS.min_detect_frac,
            "search_window_factor": DEFAULT_THRESHOLDS.search_window_factor,
            "filter_width": DEFAULT_THRESHOLDS.filter_width,
        },
        "states": dict(sorted(by_state.items())),
        "incidence": {
            "n_measured": len(measured),
            "n_multiple_traces_suspected": len(fired),
            "frac_multiple_traces_suspected": (
                len(fired) / len(measured) if measured else None
            ),
            "n_coherent_but_too_few_rows": len(short_of_frac),
            "n_second_peak_incoherent": len(incoherent),
        },
        "distribution": {
            "second_frac_of_primary_rows": _percentiles(
                [
                    r["second_frac_of_primary_rows"]
                    for r in measured
                    if r["second_frac_of_primary_rows"] is not None
                ]
            ),
            "median_jump_px": _percentiles(
                [
                    r["median_jump_px"]
                    for r in measured
                    if r["median_jump_px"] is not None
                ]
            ),
            "max_jump_px_allowed": _percentiles(
                [r["max_jump_px"] for r in measured]
            ),
        },
        "fired_obs_ids": sorted(r["obs_id"] for r in fired),
        "rows": rows,
    }
    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    print(f"\nwrote {args.out}")
    print(json.dumps(payload["states"], indent=1))
    print(json.dumps(payload["incidence"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
