"""A7 end-to-end triage slice: one observation, all the way through.

Waterfall parse → physics corridor → corridor intersection → HOG-LR probability
→ provenance → baseline score → evidence receipt.

This script is the seam test for Wave A.  It proves that every module
connects before Wave B builds volume on top.  It does NOT train anything;
it reads the already-trained model from BASELINE_RECEIPT.json (the calibrated
HOG-LR baseline whose beats_floor entry is True) and re-applies the same
inference path offline.

Chosen observation: 14740031 (UNCORRECTED, 25.1 sigma curved vs 2.8 sigma
vertical, station M0EYT/2E0NOG, NORAD 63214).  Rationale:
  - A3 measured a located trace at 25.1 sigma on this observation.
  - Verdict is UNCORRECTED, so we use the uncorrected corridor (S-curve).
  - Corridor half_width=2000 Hz; trace offset from predicted curve measured
    by A3 at ~-14 kHz absolute (A3 curved_offset_hz), but A3 measured the
    offset from rx_freq, not from the curve.  The curve itself accounts for
    the Doppler; the residual is what the corridor wraps.
  - Choosing an UNRESOLVED observation silently turns a null result into an
    apparent failure; choosing a CORRECTED observation with a near-vertical
    corridor leaves the gate-3 question unanswerable on this slice.

Usage
-----
    python scripts/run_triage_slice.py \\
        --obs-id     14740031 \\
        --out        artifacts/TRIAGE_RECEIPT.json \\
        --seed       42

Outputs
-------
    artifacts/TRIAGE_RECEIPT.json — schema-valid triage receipt
    (card rendered separately by scripts/render_evidence_card.py)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixed rule table for reason codes
# ---------------------------------------------------------------------------
# Reason codes come from this table ONLY.  Never from model attribution,
# saliency maps, or phrased as though the model explained itself.

REASON_LABEL_CONFLICT   = "LABEL_CONFLICT"      # model score disagrees with API label
REASON_CORRIDOR_MISS    = "CORRIDOR_MISS"        # corridor does not intersect trace
REASON_CORRIDOR_HIT     = "CORRIDOR_HIT"         # corridor intersects trace
REASON_OOD_STATION      = "OOD_STATION"          # station not seen in training
REASON_MISSING_ARTIFACT = "MISSING_ARTIFACT"     # waterfall PNG absent
REASON_PHYSICS_DEGRADED = "PHYSICS_DEGRADED"     # SGP4/TLE/station failure
REASON_UNCORRECTED_PASS = "UNCORRECTED_PASS"     # A3 classified this as uncorrected
REASON_CORRECTED_PASS   = "CORRECTED_PASS"       # A3 classified this as corrected
REASON_UNRESOLVED_PASS  = "UNRESOLVED_PASS"      # A3 could not classify

A3_SUMMARY_PATH = _REPO_ROOT / "artifacts" / "a3_overlays" / "summary.json"


@lru_cache(maxsize=1)
def _a3_verdicts() -> dict[int, str]:
    """A3's correction verdict per observation, read from its own artifact.

    This used to be a hardcoded four-entry dict whose comment said it was read
    from summary.json. It was not, and it had drifted: observation 14746055 was
    listed UNCORRECTED while A3's artifact records CORRECTED for it. A table
    transcribed by hand from an artifact is a second copy of that artifact, and
    the copy is what goes stale.

    The verdict cannot be inferred from metadata. A3 measured that
    doppler-correction-per-sec is null and rigctl-port is 4532 on corrected and
    uncorrected records alike, so the image is the only witness.
    """
    if not A3_SUMMARY_PATH.exists():
        return {}
    rows = json.loads(A3_SUMMARY_PATH.read_bytes())
    return {
        int(r["obs_id"]): str(r.get("verdict", "UNRESOLVED"))
        for r in rows
        if r.get("obs_id") is not None
    }


def _a3_correction_status(obs_id: int) -> str:
    """Return A3's correction verdict: UNCORRECTED, CORRECTED or UNRESOLVED."""
    return _a3_verdicts().get(obs_id, "UNRESOLVED")


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _resolve_snapshot(given: Path | None) -> Path:
    """The snapshot root, from the flag or from the environment, or a stated refusal.

    This defaulted to ``Path("D:/tracetriage_data/snap-stage1")``, one machine's drive
    letter in a published script, and the failure it produced on any other checkout was
    ``FileNotFoundError: Manifest not found: D:\\...``. That reads like a corrupt snapshot
    rather than like a path from somebody else's computer, and it had a second cost:
    `scripts/check_artifact_freshness.py` classifies a builder that raises anything other
    than `SplitsPathNotConfigured` as CRASHED, so on a fresh clone the triage-slice row
    printed [FAIL] and two tests in `tests/test_freshness_outcomes.py` failed. A 20 GB data
    plane that is deliberately outside the repository being absent is not staleness.

    So the same refusal `pipeline/tracetriage/splits.py` already raises for the pages
    directory, for the same reason and naming the same variable. The pages directory is the
    snapshot's own subfolder, so one variable addresses both and there is no second thing
    to configure.
    """
    if given is not None:
        return given.resolve()
    from pipeline.tracetriage.splits import _default_pages_dir

    return _default_pages_dir().resolve().parent


def _load_manifest(snapshot_dir: Path) -> dict[str, Any]:
    manifest_path = snapshot_dir / "DATASET_MANIFEST.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_bytes())


def _manifest_entry_for(manifest: dict[str, Any], obs_id: int) -> dict[str, Any] | None:
    for obs in manifest["observations"]:
        if obs.get("id") == obs_id:
            return obs
    return None


def _load_raw_obs(snapshot_dir: Path, obs_id: int) -> dict[str, Any] | None:
    """Find the full raw observation record from the snapshot pages."""
    pages_dir = snapshot_dir / "pages"
    if not pages_dir.exists():
        return None
    for page_file in sorted(pages_dir.glob("*.json"), key=lambda p: p.as_posix()):
        try:
            records = json.loads(page_file.read_bytes())
        except Exception:
            continue
        if not isinstance(records, list):
            continue
        for rec in records:
            if rec.get("id") == obs_id:
                return rec
    return None


def _waterfall_path(snapshot_dir: Path, obs_id: int) -> Path:
    return snapshot_dir / "waterfalls" / f"waterfall_{obs_id}.png"


# ---------------------------------------------------------------------------
# Corridor intersection check
# ---------------------------------------------------------------------------

def _target_consistency(
    a3_entry: dict[str, Any] | None,
    a3_verdict: str,
    physics_available: bool,
) -> float | None:
    """How well the trace matches the shape A3's verdict predicts, in [0, 1].

    The shape depends on the verdict, and the original A7 version ignored that.
    It computed ``min(1, sigma_curved / sigma_vertical)`` for every observation,
    which is the right ratio only for an uncorrected pass. A corrected pass has
    its Doppler removed at capture, so a strong VERTICAL trace is the evidence of
    target consistency, and dividing by it inverts the axis. Measured over A3's
    seven decisive observations, that scored all four corrected ones between
    0.046 and 0.648 while saturating all three uncorrected ones at exactly 1.000.
    Observation 14746048 carries a 37.0 sigma vertical trace, which is A3's own
    basis for calling it corrected, and the old formula rated it 0.046, the least
    target-consistent of the set.

    The ratio is taken against the hypothesis the verdict selected, and mapped
    through x / (1 + x) rather than clipped at 1.0, so a strong match keeps
    resolution instead of saturating.
    """
    if not a3_entry or not physics_available:
        return None
    curved = float(a3_entry.get("sigma_curved") or 0.0)
    vertical = float(a3_entry.get("sigma_vertical") or 0.0)

    if a3_verdict == "UNCORRECTED":
        signal, alternative = curved, vertical
    elif a3_verdict == "CORRECTED":
        signal, alternative = vertical, curved
    else:
        # No verdict means no predicted shape, so there is nothing to be
        # consistent with. None is the honest value; 0.0 would read as "measured
        # and inconsistent".
        return None

    if signal <= 0.0:
        return 0.0
    ratio = signal / max(alternative, 1.0)
    return float(ratio / (1.0 + ratio))


def _measure_corridor(
    a3_entry: dict[str, Any],
    physics_result,
    geom,
    rx_freq_hz: float | None,
    wf_path: Path,
) -> tuple[bool | None, float | None, str, dict[str, Any] | None]:
    """Measure whether the corridor contains the trace, from the image.

    Replaces the original A7 check, which computed
    ``trace_half_width_hz = 3 * hz_per_px / 2`` and compared it against the
    corridor half-width. Both sides were constants: the left one a matched-filter
    kernel width, the right one a hardcoded 1200 or 2000 Hz. Neither depended on
    where the trace sat, so the check returned True for all seven of A3's
    decisive observations and could not return False for any waterfall with a
    normal axis scale. It also cited a "max deviation 140 Hz" that exists only as
    a comment and a test literal, never as a measurement.

    What happens here instead: fit the constant frequency offset within a
    ppm-bounded range, locate the trace per image row, and compare the per-row
    residual against the corridor half-width. A corrected corridor is identically
    0 Hz, so it has no shape to confirm and comes back as a named degraded state
    rather than a hit. Detail in ``pipeline/tracetriage/corridor_fit.py``, and the
    cross-observation verdict in ``scripts/run_gate3.py``.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    from pipeline.tracetriage.corridor_fit import (  # noqa: PLC0415
        calibrate_against_nulls,
        fit_corridor,
        measure_axis_sign,
        normalised_rows,
    )
    from pipeline.tracetriage.physics import axis_sign_evidence  # noqa: PLC0415

    if physics_result.degraded is not None:
        return None, None, f"physics_degraded:{physics_result.degraded}", None
    if geom is None or geom.degraded is not None:
        return None, None, "geometry_degraded", None
    if rx_freq_hz is None:
        return None, None, "no_rx_freq", None

    obs_id = a3_entry["obs_id"]
    a3_verdict = _a3_correction_status(obs_id)
    if a3_verdict == "UNCORRECTED":
        corridor, corridor_type = physics_result.uncorrected, "uncorrected"
    elif a3_verdict == "CORRECTED":
        corridor, corridor_type = physics_result.corrected, "corrected"
    else:
        return None, None, "unresolved_correction_status", None

    with Image.open(wf_path) as im:
        rgb = np.asarray(im.convert("RGB"))
    zs = normalised_rows(rgb, geom.crop_box)

    fit = fit_corridor(
        zs, corridor, corridor_type,
        geom.hz_per_px, geom.centre_px, rx_freq_hz, obs_id=obs_id,
    )
    cal = calibrate_against_nulls(
        zs, corridor, geom.hz_per_px, geom.centre_px, rx_freq_hz,
    )

    summary: dict[str, Any] = {
        "fit": fit.summary(),
        "null_calibration": cal.summary(),
        "corridor_span_hz": float(
            np.ptp(np.asarray(corridor.doppler_hz, dtype=float))
        ),
        # SPACE-S5: which client rendered this waterfall, whether the axis sign was
        # ever measured on that family, and what this image says about it. The family
        # comes from the A3 entry, normalised by the same rule physics.client_family
        # applies.
        "axis_sign": {
            **axis_sign_evidence({"client_version": a3_entry.get("family") or ""}),
            "remeasured": measure_axis_sign(
                zs, corridor, geom.hz_per_px, geom.centre_px, rx_freq_hz,
            ),
        },
    }

    # The gate-3 answer for one observation is the null-calibrated verdict, not
    # the per-row coverage: these traces integrate to significance along the path
    # while individual rows stay under the detection floor.
    if cal.discriminates is None:
        detail = (
            f"corridor_type={corridor_type} not_testable "
            f"span={summary['corridor_span_hz']:.0f}Hz "
            "(flat corridor predicts no shape)"
        )
        return None, fit.residual_p95_hz, detail, summary

    detail = (
        f"corridor_type={corridor_type} "
        f"offset={fit.fitted_offset_hz:,.0f}Hz "
        f"({fit.fitted_offset_ppm:+.1f}ppm) "
        f"sigma={cal.true_sigma:.2f} null_max={cal.null_max:.2f} "
        f"p={cal.p_value:.4f}"
    )
    return bool(cal.discriminates), fit.residual_p95_hz, detail, summary


# ---------------------------------------------------------------------------
# HOG-LR scoring (re-apply from BASELINE_RECEIPT context)
# ---------------------------------------------------------------------------

def _score_with_hoglr(
    image_path: Path,
    seed: int = 42,
    model_path: Path | None = None,
) -> float | None:
    """Score one waterfall with the HOG-LR baseline.

    Loads the pickled (scaler, CalibratedClassifierCV) tuple from
    artifacts/hoglr_model.pkl (written by run_baseline.py --save-model).
    The HOG feature path is identical to training: _geometry_of (cached),
    _hog_features, scaler.transform, calibrated.predict_proba.

    Returns None if the pickle does not exist or feature extraction fails.
    The caller treats None as an abstain condition.
    """
    import pickle  # noqa: PLC0415

    from pipeline.tracetriage.baseline import _hog_features  # noqa: PLC0415

    if model_path is None:
        model_path = Path("artifacts/hoglr_model.pkl")

    if not model_path.exists():
        logger.warning(
            "HOG-LR model pickle not found at %s; "
            "run scripts/run_baseline.py --save-model first",
            model_path,
        )
        return None

    with open(model_path, "rb") as fh:
        scaler, calibrated = pickle.load(fh)

    feats = _hog_features(image_path)
    if feats is None:
        logger.warning("HOG feature extraction failed for %s", image_path)
        return None

    f_scaled = scaler.transform(feats.reshape(1, -1))
    p = float(calibrated.predict_proba(f_scaled)[0, 1])
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def model_checksum_and_source(model_path: Path) -> tuple[str | None, str]:
    """The model artifact's checksum, or the named absence when it is not on disk.

    Split out of ``main`` so the absent branch can be tested. The receipt has to let a
    reader tell two situations apart: the artifact was missing, and the artifact was
    there and its bytes were never read. A null checksum with no reason beside it says
    the model is unverified without saying which of those happened.
    """
    if model_path.exists():
        return hashlib.sha256(model_path.read_bytes()).hexdigest(), "artifacts/hoglr_model.pkl"
    return None, "MODEL_ARTIFACT_MISSING"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end triage slice for one observation."
    )
    parser.add_argument("--snapshot", type=Path, default=None,
                        help="the snapshot root. Defaults to the parent of "
                             "TRACETRIAGE_PAGES_DIR, and refuses if that is unset.")
    parser.add_argument("--obs-id", type=int, default=14740031,
                        help="SatNOGS observation ID to triage")
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/TRIAGE_RECEIPT.json"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-hoglr", action="store_true",
                        help="Skip HOG-LR scoring (score will be null in receipt)")
    parser.add_argument("--model", type=Path,
                        default=Path("artifacts/hoglr_model.pkl"),
                        help="Path to pickled HOG-LR model (from run_baseline.py --save-model)")
    args = parser.parse_args(argv)

    obs_id = args.obs_id
    snapshot_dir = _resolve_snapshot(args.snapshot)

    # ── 1. Load manifest entry ────────────────────────────────────────────────
    logger.info("Loading manifest from %s", snapshot_dir)
    manifest = _load_manifest(snapshot_dir)
    manifest_entry = _manifest_entry_for(manifest, obs_id)
    if manifest_entry is None:
        logger.error("Observation %d not found in manifest", obs_id)
        return 1

    # ── 2. Load full raw obs (needed for physics) ─────────────────────────────
    logger.info("Loading raw obs record for %d", obs_id)
    raw_obs = _load_raw_obs(snapshot_dir, obs_id)
    if raw_obs is None:
        logger.error("Raw obs record not found in pages for %d", obs_id)
        return 1

    # ── 3. Waterfall geometry parse ──────────────────────────────────────────
    wf_path = _waterfall_path(snapshot_dir, obs_id)
    artifact_usable = wf_path.exists()
    logger.info("Waterfall path: %s  exists=%s", wf_path, artifact_usable)

    # ── 4. Physics corridor ──────────────────────────────────────────────────
    logger.info("Computing physics corridor for obs %d", obs_id)
    from pipeline.tracetriage.physics import corridor_for_obs, rx_freq_of  # noqa: PLC0415
    phys = corridor_for_obs(raw_obs)
    rx_freq_hz = rx_freq_of(raw_obs)

    geom = None
    wf_geometry_version = None
    if artifact_usable:
        from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: PLC0415
        logger.info("Parsing waterfall geometry (OCR)…")
        # rx_freq_hz has to be passed. waterfall.py only attempts centre_px when a
        # receiver frequency is supplied, and baseline._geometry_of omits it
        # because the HOG baselines never need a centre. Reusing that helper here
        # is why the original A7 slice held centre_px=None and could not have
        # placed the corridor on the image even in principle.
        geom = parse_waterfall(
            wf_path,
            observation_id=obs_id,
            pass_duration_s=phys.pass_duration_s or 200.0,
            rx_freq_hz=rx_freq_hz,
        )
        wf_geometry_version = "0.2.2"
        if geom.degraded:
            logger.warning("Geometry parse degraded: %s", geom.degraded)
            artifact_usable = False
    physics_available = phys.degraded is None
    if not physics_available:
        logger.warning("Physics degraded: %s", phys.degraded)
    else:
        unc = phys.uncorrected
        logger.info(
            "Physics OK: max_el=%.1f° TCA_frac=%.3f Doppler_swing=%.0f→%.0f Hz",
            unc.max_elevation_deg,
            unc.tca_frac,
            min(unc.doppler_hz),
            max(unc.doppler_hz),
        )

    # ── 5. Load A3 summary entry ──────────────────────────────────────────────
    a3_summary_path = Path("artifacts/a3_overlays/summary.json")
    a3_entry: dict[str, Any] | None = None
    if a3_summary_path.exists():
        a3_all = json.loads(a3_summary_path.read_bytes())
        for entry in a3_all:
            if entry.get("obs_id") == obs_id:
                a3_entry = entry
                break
    if a3_entry is None:
        logger.error("obs %d not found in A3 summary; cannot evaluate gate 3", obs_id)
        return 1

    # ── 6. Corridor intersection ──────────────────────────────────────────────
    intersects, residual_hz, corridor_detail, corridor_fit_summary = (
        _measure_corridor(
            a3_entry, phys, geom if artifact_usable else None, rx_freq_hz, wf_path,
        )
    )
    logger.info(
        "Corridor intersection: %s  residual_hz=%s  (%s)",
        intersects, residual_hz, corridor_detail
    )

    # ── 7. HOG-LR score ───────────────────────────────────────────────────────
    calibrated_prob: float | None = None
    if artifact_usable and not args.skip_hoglr:
        logger.info("Scoring with HOG-LR baseline (loading pickled model)…")
        calibrated_prob = _score_with_hoglr(wf_path, seed=args.seed, model_path=args.model)
        logger.info("HOG-LR calibrated_probability: %s", calibrated_prob)

    # ── 8. Provenance ─────────────────────────────────────────────────────────
    from pipeline.tracetriage.provenance import (  # noqa: PLC0415
        label_from_obs,
        to_receipt_provenance,
    )

    # Adapt manifest entry shape for provenance (label_from_obs reads 'waterfall' key)
    prov_obs = {
        "id":               manifest_entry["id"],
        "status":           "good",
        "waterfall":        manifest_entry.get("waterfall_url"),
        "waterfall_status": manifest_entry.get("waterfall_status"),
        "_retrieved_at":    manifest_entry.get("retrieved_at"),
        "end":              raw_obs.get("end"),
        "ground_station":   manifest_entry.get("ground_station"),
        "transmitter_uuid": manifest_entry.get("transmitter_uuid"),
        "_source_url":      manifest_entry.get("source_url"),
    }
    prov_record = label_from_obs(prov_obs)

    artifact_sha256 = manifest_entry.get("waterfall_sha256")
    prov_dict = to_receipt_provenance(
        prov_record,
        artifact_sha256=artifact_sha256,
        split=None,   # splits not yet frozen at A7
    )

    # ── 9. Reason codes (fixed rule table) ───────────────────────────────────
    a3_verdict = _a3_correction_status(obs_id)
    reason_codes: list[str] = []

    if not artifact_usable:
        reason_codes.append(REASON_MISSING_ARTIFACT)
    if not physics_available:
        reason_codes.append(REASON_PHYSICS_DEGRADED)

    if a3_verdict == "UNCORRECTED":
        reason_codes.append(REASON_UNCORRECTED_PASS)
    elif a3_verdict == "CORRECTED":
        reason_codes.append(REASON_CORRECTED_PASS)
    else:
        reason_codes.append(REASON_UNRESOLVED_PASS)

    if intersects is True:
        reason_codes.append(REASON_CORRIDOR_HIT)
    elif intersects is False:
        reason_codes.append(REASON_CORRIDOR_MISS)

    api_label = manifest_entry.get("waterfall_status")
    if calibrated_prob is not None:
        # LABEL_CONFLICT: model says <0.5 but label is with-signal, or vice-versa
        model_says_signal = calibrated_prob >= 0.5
        label_says_signal = api_label == "with-signal"
        if api_label in ("with-signal", "without-signal") and (
            model_says_signal != label_says_signal
        ):
            reason_codes.append(REASON_LABEL_CONFLICT)

    # ── 10. Decision ──────────────────────────────────────────────────────────
    # A null calibrated_prob (model pickle absent or --skip-hoglr) is an abstain
    # ONLY if no other evidence is sufficient to decide.  If the corridor missed,
    # flag_for_review regardless.  If the corridor hit and label agrees, no_conflict.
    if not artifact_usable and not physics_available:
        decision = "abstain"
        abstention_reason = "Both artifact and physics unavailable"
    elif intersects is False or REASON_LABEL_CONFLICT in reason_codes:
        decision = "flag_for_review"
        abstention_reason = None
    elif calibrated_prob is not None and calibrated_prob >= 0.5 and api_label == "with-signal":
        decision = "no_conflict"
        abstention_reason = None
    elif calibrated_prob is None and intersects is True and api_label == "with-signal":
        # Corridor hit confirms the label; no image-model conflict possible without a score.
        decision = "no_conflict"
        abstention_reason = None
    elif calibrated_prob is None:
        # No image score and no definitive corridor conflict.
        decision = "abstain"
        abstention_reason = "HOG-LR score unavailable; load artifacts/hoglr_model.pkl"
    else:
        decision = "flag_for_review"
        abstention_reason = None

    # ── 11. Assemble receipt ──────────────────────────────────────────────────
    # model_checksum is the SHA-256 of the model that actually produced the
    # score, artifacts/hoglr_model.pkl.
    #
    # It used to hash artifacts/BASELINE_RECEIPT.json instead. That file is
    # metrics and metadata, not the model, so the checksum stayed identical when
    # the pickle was swapped and changed when it was not: BASELINE_RECEIPT.json
    # carries a wall-clock generated_at, so commit ff2b871 moved the checksum
    # without touching the model. The path was also relative, so running from any
    # other directory silently produced the "00" * 32 fallback, which is a
    # well-formed 64-character hex string that reads like a real hash in a
    # provenance field. A missing model is now a named degraded state.
    model_path = _REPO_ROOT / "artifacts" / "hoglr_model.pkl"
    model_checksum, model_checksum_source = model_checksum_and_source(model_path)

    receipt: dict[str, Any] = {
        # Pinned to the contract this writer was built against. The contract requires
        # it as of 0.3.0, so a receipt from an older writer no longer validates and
        # cannot be read as current.
        "schema_version":   "0.3.0",
        "observation_id":   obs_id,
        "snapshot_id":      manifest.get("snapshot_id", "snap-stage1"),
        "model_checksum":   model_checksum,
        "model_checksum_source": model_checksum_source,
        "generated_at":     datetime.now(UTC).isoformat(),
        "evidence": {
            "artifact_usable":          artifact_usable,
            "physics_available":        physics_available,
            "visible_signal":           calibrated_prob,
            "target_consistency":       _target_consistency(
                a3_entry, _a3_correction_status(obs_id), physics_available,
            ),
            "residual_hz":              residual_hz,
            "corridor_intersects_trace": intersects,
            "corridor_measurement":     corridor_fit_summary,
            "waterfall_geometry_version": wf_geometry_version,
        },
        "scores": {
            "calibrated_probability": calibrated_prob,
            "uncertainty":            None,
            "ood_score":              None,
            "review_value":           None,
        },
        "decision":           decision,
        "reason_codes":       reason_codes,
        "provenance":         prov_dict,
    }
    if decision == "abstain":
        receipt["abstention_reason"] = abstention_reason

    # ── 12. Validate against schema ───────────────────────────────────────────
    # Anchored to the repository rather than the working directory. It was relative,
    # so running this from anywhere else made schema_path.exists() false and skipped
    # validation without saying so: the same shape as the hardcoded audit path in
    # ENG-B3, where a missing input read as a pass. A missing contract is now a
    # failure, because a receipt nothing validated is not a validated receipt.
    schema_path = _REPO_ROOT / "contracts" / "triage_receipt.schema.json"
    if not schema_path.exists():
        logger.error("Contract missing: %s", schema_path)
        return 1
    try:
        import jsonschema  # noqa: PLC0415
        schema = json.loads(schema_path.read_bytes())
        jsonschema.validate(receipt, schema)
        logger.info("Receipt validates against triage_receipt.schema.json ✓")
    except Exception as exc:
        logger.error("Schema validation failed: %s", exc)
        return 1

    # ── 13. Write ─────────────────────────────────────────────────────────────
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2), encoding="utf-8", newline="\n")
    logger.info("Receipt written: %s", args.out)

    # ── 14. Summary ───────────────────────────────────────────────────────────
    print()
    print("=" * 70)
    print(f"TRIAGE SLICE  obs={obs_id}  snapshot={manifest.get('snapshot_id')}")
    print("=" * 70)
    print(f"  A3 verdict:         {a3_verdict}")
    print(f"  Artifact usable:    {artifact_usable}")
    print(f"  Physics available:  {physics_available}")
    if physics_available:
        print(f"  Max elevation:      {phys.uncorrected.max_elevation_deg:.1f}°")
        swing = max(phys.uncorrected.doppler_hz) - min(phys.uncorrected.doppler_hz)
        print(f"  Doppler swing:      {swing:.0f} Hz")
    geom_degraded = geom.degraded if geom else "n/a"
    print(f"  Waterfall geometry: {wf_geometry_version}  degraded={geom_degraded}")
    if geom and geom.hz_per_px:
        print(f"  Hz/px:              {geom.hz_per_px:.3f}")
    print(f"  Corridor intersects:{intersects}  residual_hz={residual_hz}")
    print(f"  HOG-LR prob:        {calibrated_prob}")
    print(f"  API label:          {api_label}")
    print(f"  Decision:           {decision}")
    print(f"  Reason codes:       {reason_codes}")
    print()
    print(f"  Receipt: {args.out}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
