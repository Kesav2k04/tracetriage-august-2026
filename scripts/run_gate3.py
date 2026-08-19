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
    measure_axis_sign,
    normalised_rows,
    run_null_controls,
)
from pipeline.tracetriage.physics import (  # noqa: E402
    AXIS_SIGN_CONVENTION,
    AXIS_SIGN_MEASURED_FAMILIES,
    axis_sign_evidence,
    client_family,
    corridor_for_obs,
    rx_freq_of,
)

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


def _axis_sign_scope(snapshot_dir: Path) -> dict[str, Any]:
    """Census the client families across the dataset the gate draws from.

    SPACE-S5: AXIS_SIGN_CONVENTION is a property of the renderer, measured on 3
    observations from 2 client families. This counts how much of the corpus those 2
    families actually cover, so the reach of the assumption is a published number
    rather than a sentence. Nothing here changes a verdict; it is scope.

    The corpus is the one `artifacts/DATASET_MANIFEST.json` records, not every row on
    disk. The two differ, and the first version of this census counted the rows: the API
    pages hold 2,750 observations and the dataset holds 2,727, because the ingest stopped
    at its 2,500-waterfall target part-way through the last page it had already written
    whole. So the README quoted a denominator of 2,750 for a scope statement about a
    corpus of 2,727, next to a demo script quoting 2,727 for the same corpus. Both counts
    are published here with the difference named, because the honest fix for two numbers
    that disagree is to say which is which, not to pick one.
    """
    manifest_path = REPO_ROOT / "artifacts" / "DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    in_the_dataset = {obs["id"] for obs in manifest["observations"] if "id" in obs}

    families: dict[str, int] = {}
    n = 0
    rows_on_disk = 0
    pages_dir = snapshot_dir / "pages"
    for page_file in sorted(pages_dir.glob("*.json")):
        try:
            page = json.loads(page_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = page if isinstance(page, list) else page.get("results", [])
        for obs in rows:
            if not isinstance(obs, dict) or "id" not in obs:
                continue
            rows_on_disk += 1
            if obs["id"] not in in_the_dataset:
                continue
            n += 1
            fam = client_family(obs)
            families[fam] = families.get(fam, 0) + 1
    if n != len(in_the_dataset):
        raise SystemExit(
            f"the dataset manifest records {len(in_the_dataset)} observations and the "
            f"snapshot pages carry {n} of them. The census would be computed over a "
            "corpus that is not the one every other number in this repository is about."
        )
    covered = sum(v for k, v in families.items() if k in AXIS_SIGN_MEASURED_FAMILIES)
    return {
        "axis_sign_applied": AXIS_SIGN_CONVENTION,
        "measured_families": sorted(AXIS_SIGN_MEASURED_FAMILIES),
        "measured_on_observations": 3,
        "observations_in_snapshot": n,
        "rows_in_the_api_pages_on_disk": rows_on_disk,
        "rows_on_disk_not_in_the_dataset": rows_on_disk - n,
        "why_those_rows_are_not_in_the_dataset": (
            "The ingest fetched whole API pages and stopped at its 2,500-waterfall "
            "target part-way through the last one, so the final page was written to disk "
            "complete and only part of it was stored. Every count in this repository is "
            "over the stored dataset, which artifacts/DATASET_MANIFEST.json defines."
        ),
        "distinct_families_in_snapshot": len(families),
        "observations_from_a_measured_family": covered,
        "observations_inheriting_the_constant": n - covered,
        "family_counts": dict(sorted(families.items(), key=lambda kv: (-kv[1], kv[0]))),
        "note": (
            "The sign was measured on 3 observations, one UTC night, 2 stations, "
            "436.4 MHz, families 1.6 and 2.1.2. Every other family inherits it. A "
            "renderer that flipped its frequency axis between client versions is the "
            "untested risk, and each scored observation carries its own remeasurement "
            "under observations[].axis_sign.remeasured."
        ),
    }


def _fit_row(fit: CorridorFit) -> dict[str, Any]:
    return fit.summary()


def rate_lower_bound(successes: int, trials: int, alpha: float = 0.05) -> float | None:
    """Exact one-sided Clopper-Pearson lower bound on a binomial rate.

    A rate is not a measurement until it has an interval, and this gate was
    comparing a point estimate against its threshold: 3 successes in 3 trials gives
    a rate of 1.0, and 1.0 >= 0.70 is True, so the gate read PASSED. The same
    comparison would have passed 1 of 1. This document already made that argument
    once, when the earlier one-observation version of this gate was withdrawn with
    the note that "a 70% rate cannot be measured on one observation in any case",
    and then the three-observation version was accepted on the identical logic.

    For k = n the bound has the closed form alpha ** (1 / n), which is 0.368 for
    3 of 3 at 95 percent and 0.224 for 2 of 2. Both sit far below a 0.70 bar, so
    the data are consistent with a true rate around half the threshold. The general
    case uses the Beta quantile the closed form is a special case of, and the two
    are cross-checked in tests/test_gate3_bound.py.

    Gates 5 and 6 already publish NOT_ESTABLISHED when an interval fails to exclude
    a threshold. This makes gate 3 read from the same register.
    """
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    if successes == 0:
        return 0.0
    if successes == trials:
        return float(alpha ** (1.0 / trials))
    from scipy.stats import beta

    return float(beta.ppf(alpha, successes, trials - successes + 1))


def rate_upper_bound(successes: int, trials: int, alpha: float = 0.05) -> float | None:
    """Exact one-sided Clopper-Pearson upper bound, the partner of the bound above.

    Added for gate 4, which needs three outcomes rather than two: a rate whose interval sits
    entirely below the threshold is a failure and says the labelling protocol is wrong, while
    a rate whose interval merely contains the threshold is inconclusive. Deciding that with a
    lower bound alone would collapse those two into one and report the protocol as broken on
    evidence that does not support it.

    For k = 0 the closed form is 1 - alpha ** (1 / n), which mirrors the k = n case beside it.
    """
    if trials <= 0 or successes < 0 or successes > trials:
        return None
    if successes == trials:
        return 1.0
    if successes == 0:
        return float(1.0 - alpha ** (1.0 / trials))
    from scipy.stats import beta

    return float(beta.ppf(1.0 - alpha, successes + 1, trials - successes))


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
            "client_family": client_family(raw),
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
                # SPACE-S8: the two sigmas above and fit.sigma_at_fit below are different
                # statistics. A3 normalised per column band; corridor_fit normalises
                # against the median and MAD of the whole image. The ratio is published
                # per observation because it is not a constant, so no conversion exists
                # and the two cannot be read against each other.
                "sigma_scale_ratio_to_fit": (
                    float(p["a3_sigma_curved"] / fit.sigma_at_fit)
                    if p["a3_sigma_curved"] and fit.sigma_at_fit else None
                ),
                "sigma_comparability": (
                    "Not comparable. sigma_curved and sigma_vertical come from A3's "
                    "per-band normalisation; fit.sigma_at_fit and "
                    "null_calibration.true_sigma come from this module's whole-image "
                    "MAD. Measured across the seven decisive observations the ratio "
                    "runs from 0.87 to 12.4, so it is not a rescaling. On 14740031 the "
                    "A3 vertical sigma of 2.83 exceeds this module's curved sigma of "
                    "2.02, which inverts the comparison the two artifacts agree on. "
                    "Compare a sigma only against another sigma from the same estimator."
                ),
            },
            "fit": _fit_row(fit),
            # SPACE-S5: the axis sign is a property of the client that rendered this
            # image, applied here as a global constant measured on 3 observations from
            # 2 client families. Published per observation so a renderer with no
            # measurement behind it is visible, and re-measured from the image itself
            # wherever the corridor has the swing to make that possible.
            "axis_sign": {
                **axis_sign_evidence({"client_version": p.get("client_family") or ""}),
                "remeasured": measure_axis_sign(
                    p["zs"], p["corridor"], p["hz_per_px"], p["centre_px"],
                    p["rx_freq_hz"],
                ),
            },
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
    # The point estimate is reported, but the threshold is read off the lower bound.
    # A rate of 1.0 on three trials does not establish a rate of 0.70.
    rate_bound = rate_lower_bound(len(discriminating), len(scored))
    clears_point = hit_rate is not None and hit_rate >= args.gate_threshold
    clears_threshold = rate_bound is not None and rate_bound >= args.gate_threshold

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

    # Collapse correlated observations before computing the rate, rather than
    # disclosing the correlation only in prose. A consumer that reads
    # clears_threshold without reading entity_grouping's note would otherwise
    # inherit the overstatement, and at snapshot scale that matters.
    by_group: dict[tuple[Any, Any], list[bool]] = {}
    for r in scored:
        key = (r["station_id"], _day(r))
        by_group.setdefault(key, []).append(
            bool(r["null_calibration"]["discriminates"])
        )
    # A group counts as discriminating only if every observation in it does, so
    # collapsing can never manufacture a pass.
    group_flags = [all(v) for v in by_group.values()]
    grouped_rate = sum(group_flags) / len(group_flags) if group_flags else None
    grouped_bound = rate_lower_bound(sum(group_flags), len(group_flags))
    grouped_clears_point = (
        grouped_rate is not None and grouped_rate >= args.gate_threshold
    )
    grouped_clears = grouped_bound is not None and grouped_bound >= args.gate_threshold

    grouping["groups_scored"] = len(group_flags)
    grouping["grouped_discriminating_rate"] = grouped_rate
    grouping["grouped_rate_lower_bound_95"] = grouped_bound
    grouping["grouped_clears_point_estimate"] = grouped_clears_point
    grouping["grouped_clears_threshold"] = grouped_clears
    grouping["group_key"] = "(ground_station, UTC date)"

    if not scored:
        verdict = "UNMEASURABLE"
    elif clears_threshold and grouped_clears:
        verdict = "PASSED"
    elif clears_threshold and not grouped_clears:
        verdict = "PASSED_UNGROUPED_ONLY"
    elif clears_point or grouped_clears_point:
        # Every observation discriminated and the point estimate is above the bar,
        # but the sample cannot resolve the bar. That is a different finding from a
        # gate whose observations missed, and it is the finding gates 5 and 6 also
        # report, so it gets their word rather than FAILED.
        verdict = "NOT_ESTABLISHED"
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
        "rate_lower_bound_95": rate_bound,
        "clears_point_estimate": clears_point,
        "clears_threshold": clears_threshold,
        "entity_grouping": grouping,
        "axis_sign_scope": _axis_sign_scope(args.snapshot),
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
        "claim": {
            "established": (
                "After fitting one constant frequency offset bounded at 50 ppm, the "
                "predicted Doppler SHAPE fits the observed trace significantly better "
                "than corridors built by permuting the same Doppler values in time, "
                "and better than the same curve rescaled to 0.25x, 0.5x, 2x or 4x its "
                "predicted swing. The shape and the magnitude of the SGP4 prediction "
                "are both doing work."
            ),
            "not_established": (
                "That the corridor sits where physics places it without a fitted "
                "offset. All three fitted offsets are 40 to 84 percent of their own "
                "predicted swing, so each needed a large slide to fit. This is a "
                "shape test, not an absolute-position test, and the plan's phrase "
                "'corridor intersects a visible trace' is looser than what is "
                "measured here. The per-row position diagnostic (fit.coverage, "
                "fit.corridor_hit) is null on every scored observation because these "
                "traces do not clear the per-row detection floor."
            ),
            "why_the_offset_is_not_a_fudge": (
                "A cubesat oscillator drifts and the SatNOGS transmitter frequency a "
                "station tunes to is community-maintained, so an absolute-position "
                "test would be testing the database rather than the orbital "
                "mechanics. The offset is a real physical quantity and is reported "
                "per observation as fitted_offset_ppm."
            ),
        },
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
    g_rate = grouping["grouped_discriminating_rate"]
    g_txt = f"{g_rate:.3f}" if g_rate is not None else "n/a"
    print(f"  grouped rate            {g_txt}"
          f"  over {grouping['groups_scored']} {grouping['group_key']} groups")
    print(f"  per-observation rate    "
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
