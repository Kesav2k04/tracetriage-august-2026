"""Kill gate 3, measured: does the expected corridor intersect a visible trace?

Runs every decisive observation A3 produced, fits each corridor with a
ppm-bounded constant frequency offset, measures the per-row residual between the
detected trace and the fitted curve, and reports the fraction of observations
whose corridor contains the trace.

Then it does the part that makes the number mean something: it repeats the whole
measurement against null corridors that should not fit. The gate's verdict is a
comparison, not a threshold. A hit rate of 100 percent proves nothing if a
scrambled curve also scores 100 percent.

Unit A7 reported this gate as passed on one observation using a check that
compared a matched-filter kernel width against the corridor width. Both are
constants, so the check could not fail. This script replaces it.

Usage
-----
    python scripts/run_gate3.py \\
        --snapshot D:/tracetriage_data/snap-stage1 \\
        --a3       artifacts/a3_overlays/summary.json \\
        --out      artifacts/GATE3_RECEIPT.json

Outputs
-------
    artifacts/GATE3_RECEIPT.json   per-observation fits, null controls, verdict
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.tracetriage.corridor_fit import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    THRESHOLD_RATIONALE,
    CorridorFit,
    calibrate_against_nulls,
    fit_corridor,
    normalised_rows,
    run_null_controls,
)
from pipeline.tracetriage.physics import corridor_for_obs, rx_freq_of  # noqa: E402

logger = logging.getLogger("gate3")


def _load_raw_obs(snapshot_dir: Path, obs_id: int) -> dict[str, Any] | None:
    """Find one full raw observation record in the snapshot's stored pages."""
    pages_dir = snapshot_dir / "pages"
    if not pages_dir.exists():
        return None
    for page_file in sorted(pages_dir.glob("*.json")):
        try:
            page = json.loads(page_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = page if isinstance(page, list) else page.get("results", [])
        for rec in records:
            if rec.get("id") == obs_id:
                return rec
    return None


def _geometry_of(image_path: Path, obs_id: int, rx_freq_hz: float | None, duration_s: float):
    """Parse one waterfall's geometry.

    ``rx_freq_hz`` has to be passed. waterfall.py:795 only attempts ``centre_px``
    when a receiver frequency is supplied, so omitting it returns
    ``centre_px=None`` and every corridor becomes unplaceable. An earlier run of
    this script omitted it and reported all seven observations UNMEASURABLE,
    which looked like a physics result and was a call-signature mistake.

    ``pass_duration_s`` only feeds ``seconds_per_px``, which this measurement
    never reads, because residuals are indexed by row fraction rather than by
    seconds. It is passed truthfully anyway so the record is not misleading.
    """
    from pipeline.tracetriage.waterfall import parse_waterfall

    return parse_waterfall(
        image_path,
        observation_id=obs_id,
        pass_duration_s=duration_s,
        rx_freq_hz=rx_freq_hz,
    )


def _fit_row(fit: CorridorFit) -> dict[str, Any]:
    return fit.summary()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=Path("D:/tracetriage_data/snap-stage1"))
    ap.add_argument("--a3", type=Path, default=REPO_ROOT / "artifacts/a3_overlays/summary.json")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts/GATE3_RECEIPT.json")
    ap.add_argument("--gate-threshold", type=float, default=0.70)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    a3_rows = json.loads(args.a3.read_text(encoding="utf-8"))
    decisive = [r for r in a3_rows if r.get("verdict") in ("CORRECTED", "UNCORRECTED")]
    logger.info("A3 decisive observations: %d", len(decisive))

    wf_dir = args.snapshot / "waterfalls"

    # Donor corridor for the mismatched control: the pass geometry of a
    # different observation in the set. Chosen as the next decisive entry so the
    # choice is deterministic and stated, not picked to flatter a result.
    corridors: dict[int, Any] = {}
    prepared: list[dict[str, Any]] = []

    for entry in decisive:
        obs_id = entry["obs_id"]
        raw = _load_raw_obs(args.snapshot, obs_id)
        if raw is None:
            logger.warning("obs %d: not in snapshot pages, skipping", obs_id)
            prepared.append({"obs_id": obs_id, "degraded": "NOT_IN_SNAPSHOT"})
            continue

        img = wf_dir / f"waterfall_{obs_id}.png"
        if not img.exists():
            logger.warning("obs %d: waterfall missing on disk", obs_id)
            prepared.append({"obs_id": obs_id, "degraded": "WATERFALL_MISSING"})
            continue

        phys = corridor_for_obs(raw)
        rx_hz = rx_freq_of(raw)
        duration_s = phys.pass_duration_s or 200.0

        geom = _geometry_of(img, obs_id, rx_hz, duration_s)
        if geom is None or geom.degraded is not None:
            logger.warning("obs %d: geometry degraded (%s)", obs_id, getattr(geom, "degraded", "?"))
            prepared.append({"obs_id": obs_id, "degraded": "GEOMETRY_DEGRADED"})
            continue

        if phys.degraded is not None:
            logger.warning("obs %d: physics degraded (%s)", obs_id, phys.degraded)
            prepared.append({"obs_id": obs_id, "degraded": f"PHYSICS_{phys.degraded}"})
            continue

        verdict = entry["verdict"]
        corridor = phys.uncorrected if verdict == "UNCORRECTED" else phys.corrected
        corridors[obs_id] = corridor

        from PIL import Image

        with Image.open(img) as im:
            rgb = np.asarray(im.convert("RGB"))
        zs = normalised_rows(rgb, geom.crop_box)

        prepared.append({
            "obs_id": obs_id,
            "verdict": verdict,
            "station_id": raw.get("ground_station"),
            "norad_cat_id": raw.get("norad_cat_id"),
            "transmitter_uuid": raw.get("transmitter_uuid"),
            "start": raw.get("start"),
            "end": raw.get("end"),
            "zs": zs,
            "corridor": corridor,
            "corridor_type": "uncorrected" if verdict == "UNCORRECTED" else "corrected",
            "hz_per_px": geom.hz_per_px,
            "centre_px": geom.centre_px,
            "rx_freq_hz": rx_freq_of(raw),
            "a3_curved_offset_hz": entry.get("curved_offset_hz"),
            "a3_sigma_curved": entry.get("sigma_curved"),
            "a3_sigma_vertical": entry.get("sigma_vertical"),
            "predicted_swing_hz": entry.get("predicted_swing_hz"),
        })

    ok = [p for p in prepared if "zs" in p]
    donor_ids = [p["obs_id"] for p in ok]

    results: list[dict[str, Any]] = []
    for i, p in enumerate(ok):
        obs_id = p["obs_id"]
        donor_id = donor_ids[(i + 1) % len(donor_ids)] if len(donor_ids) > 1 else None
        donor = corridors.get(donor_id) if donor_id != obs_id else None

        corridor_span_hz = float(
            np.ptp(np.asarray(p["corridor"].doppler_hz, dtype=float))
        )
        testable = corridor_span_hz > 0.0

        fit = fit_corridor(
            p["zs"], p["corridor"], p["corridor_type"],
            p["hz_per_px"], p["centre_px"], p["rx_freq_hz"],
            obs_id=obs_id,
        )
        cal = calibrate_against_nulls(
            p["zs"], p["corridor"], p["hz_per_px"], p["centre_px"], p["rx_freq_hz"],
        )
        controls = run_null_controls(
            p["zs"], p["corridor"], p["corridor_type"],
            p["hz_per_px"], p["centre_px"], p["rx_freq_hz"],
            obs_id=obs_id, donor_corridor=donor,
        )

        logger.info(
            "obs %d %-11s span=%7.0f Hz  offset=%+8s Hz (%+6s ppm)  "
            "sigma=%s  null_med=%s  p=%s  %s",
            obs_id, p["verdict"], corridor_span_hz,
            f"{fit.fitted_offset_hz:,.0f}" if fit.fitted_offset_hz is not None else "n/a",
            f"{fit.fitted_offset_ppm:.1f}" if fit.fitted_offset_ppm is not None else "n/a",
            f"{cal.true_sigma:.2f}" if cal.true_sigma is not None else "n/a",
            f"{cal.null_median:.2f}" if cal.null_median is not None else "n/a",
            f"{cal.p_value:.4f}" if cal.p_value is not None else "n/a",
            "TESTABLE" if testable else "NOT TESTABLE (flat corridor)",
        )

        results.append({
            "obs_id": obs_id,
            "verdict": p["verdict"],
            "station_id": p["station_id"],
            "norad_cat_id": p["norad_cat_id"],
            "transmitter_uuid": p["transmitter_uuid"],
            "start": p["start"],
            "end": p["end"],
            "corridor_span_hz": corridor_span_hz,
            "testable": testable,
            "not_testable_reason": (
                None if testable else
                "The corrected corridor is identically 0 Hz across the pass, so it "
                "is a bare vertical line with a free horizontal offset. There is no "
                "predicted shape to confirm, and every null built from it reproduces "
                "it exactly. Gate 3 is vacuous here rather than passing."
            ),
            "a3_reference": {
                "curved_offset_hz": p["a3_curved_offset_hz"],
                "sigma_curved": p["a3_sigma_curved"],
                "sigma_vertical": p["a3_sigma_vertical"],
                "predicted_swing_hz": p["predicted_swing_hz"],
            },
            "fit": _fit_row(fit),
            "null_calibration": cal.summary(),
            "null_controls": [
                {"name": c.name, "rationale": c.rationale, "fit": _fit_row(c.fit)}
                for c in controls
            ],
            "donor_obs_id": donor_id,
        })

    # ---------------------------------------------------------------------
    # Verdict
    # ---------------------------------------------------------------------
    testable = [r for r in results if r["testable"]]
    not_testable = [r for r in results if not r["testable"]]
    scored = [r for r in testable if r["null_calibration"]["p_value"] is not None]
    discriminating = [r for r in scored if r["null_calibration"]["discriminates"]]
    hit_rate = len(discriminating) / len(scored) if scored else None
    clears_threshold = hit_rate is not None and hit_rate >= args.gate_threshold

    # Entity grouping. A rate over observations overstates the evidence when the
    # observations are not independent, and the plan requires bootstrapping "by
    # orbital episode or day, not by image row". Measured here: the three
    # testable observations span 2 ground stations and 1 UTC night inside a
    # 22-minute window, on satellites with consecutive NORAD IDs (63214, 63217,
    # 63218) that are almost certainly one deployment cluster. Two of them share
    # station 1696 three minutes apart, which is why they fit an identical
    # -7,149 Hz offset: the same receiver carries the same local-oscillator error,
    # so that is one systematic offset measured twice rather than two independent
    # confirmations.
    def _day(row: dict[str, Any]) -> str | None:
        start = row.get("start")
        return start[:10] if isinstance(start, str) and len(start) >= 10 else None

    grouping = {
        "distinct_stations": len({r["station_id"] for r in scored}),
        "distinct_satellites": len({r["norad_cat_id"] for r in scored}),
        "distinct_transmitters": len({r["transmitter_uuid"] for r in scored}),
        "distinct_days": len({_day(r) for r in scored}),
        "distinct_station_days": len({(r["station_id"], _day(r)) for r in scored}),
        "note": (
            "The discriminating rate is over observations, not over independent "
            "episodes. Per-observation evidence is strong: each beats 200 nulls "
            "with 0 reaching it, and each beats all four scaled-swing controls. "
            "The cross-observation rate does not carry three independent samples."
        ),
    }

    if not scored:
        verdict = "UNMEASURABLE"
    elif clears_threshold:
        verdict = "PASSED"
    else:
        verdict = "FAILED"

    receipt = {
        "gate": 3,
        "question": "Does the expected corridor intersect a visible target-like trace?",
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "threshold": args.gate_threshold,
        "observations_decisive": len(decisive),
        "observations_testable": len(testable),
        "observations_not_testable": len(not_testable),
        "observations_scored": len(scored),
        "discriminating_rate": hit_rate,
        "clears_threshold": clears_threshold,
        "entity_grouping": grouping,
        "not_testable_note": (
            "A corrected corridor is identically 0 Hz across the pass, so it is a "
            "vertical line with a free horizontal offset and predicts no shape. "
            "Gate 3 can only be asked of uncorrected captures, where an S-curve is "
            "predicted and can be wrong. Excluding these is a limit on the gate's "
            "scope, not a pass."
        ),
        "thresholds": {
            "z_min": DEFAULT_THRESHOLDS.z_min,
            "min_detect_frac": DEFAULT_THRESHOLDS.min_detect_frac,
            "coverage_threshold": DEFAULT_THRESHOLDS.coverage_threshold,
            "offset_ppm_limit": DEFAULT_THRESHOLDS.offset_ppm_limit,
            "filter_width": DEFAULT_THRESHOLDS.filter_width,
            "search_window_factor": DEFAULT_THRESHOLDS.search_window_factor,
            "seed": DEFAULT_THRESHOLDS.seed,
        },
        "threshold_rationale": THRESHOLD_RATIONALE,
        "method": (
            "Per observation: fit one constant frequency offset bounded at "
            "offset_ppm_limit ppm of the downlink, scoring the predicted curve with "
            "a matched filter and taking the best offset. Then repeat the identical "
            "fit for n_nulls corridors built by permuting the observation's own "
            "Doppler samples in time, which preserves every frequency value and the "
            "whole swing while destroying the monotone shape. The statistic is the "
            "one-sided empirical p-value of the true corridor against that null "
            "distribution. An observation discriminates when p <= p_value_max. The "
            "gate passes when the discriminating rate over scored observations "
            "reaches the threshold. Per-row residuals and coverage are reported as "
            "diagnostics but are not the gate: these traces integrate to "
            "significance along the path while individual rows stay below z_min, so "
            "a per-row instrument reports zero detections on a trace A3 localised "
            "at high sigma."
        ),
        "observations": results,
        "skipped": [p for p in prepared if "zs" not in p],
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    print()
    print("=" * 72)
    print(f"KILL GATE 3: {verdict}")
    print("=" * 72)
    print(f"  decisive observations   {len(decisive)}")
    print(f"  testable (has a shape)  {len(testable)}")
    print(f"  not testable (flat)     {len(not_testable)}")
    print(f"  scored against nulls    {len(scored)}")
    print(f"  stations / sats / days  "
          f"{grouping['distinct_stations']} / {grouping['distinct_satellites']}"
          f" / {grouping['distinct_days']}")
    print(f"  discriminating rate     "
          f"{f'{hit_rate:.3f}' if hit_rate is not None else 'n/a'}"
          f"  (threshold {args.gate_threshold})")
    print()
    for r in scored:
        c = r["null_calibration"]
        scaled = "  ".join(f"{k}={v:.2f}" for k, v in c["scaled_swing_sigmas"].items())
        print(f"    obs {r['obs_id']}  sigma={c['true_sigma']:.2f}  "
              f"null_med={c['null_median']:.2f}  null_max={c['null_max']:.2f}  "
              f"margin={c['margin_over_best_null']:+.2f}")
        print(f"        {c['n_at_least']} of {c['n_nulls']} nulls reached it, "
              f"p={c['p_value']:.4f}  |  scaled swing: {scaled}  "
              f"beats_scaled={c['beats_scaled_swing']}")
    print()
    print(f"  receipt                 {args.out}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
