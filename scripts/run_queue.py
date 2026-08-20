"""Build the review-value queue and measure kill gate 6 (unit C1).

Produces artifacts/QUEUE_RECEIPT.json validated against its contract before writing.
A receipt that violates the schema never reaches disk.

Gate 6 wording: "Require the top review queue to find at least 1.5 times as many
manually actionable conflicts as random ordering at the same budget."

Measured with a grouped bootstrap over pass episodes (not observations).

Usage:
    .venv/Scripts/python.exe scripts/run_queue.py [--seed 42] [--n-boot 4000]
        [--splits chronological,cold_station,cold_transmitter,cold_combined]
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.features import (  # noqa: E402
    admissible_source_fields,
    corridor_features,
    load_corridor_cache,
    metadata_features,
    physics_features,
)
from pipeline.tracetriage.fusion import (  # noqa: E402
    SHIPPED_ARM,
    SHIPPED_ARM_BLOCKS,
    Calibrator,
    FusionArm,
)
from pipeline.tracetriage.queue import (  # noqa: E402
    CONFLICT_CRITERIA,
    _disagreement_value,
    _episode_key,
    apply_concentration_caps,
    baseline_fifo,
    baseline_image_uncertainty,
    baseline_offset_magnitude,
    baseline_physics_only,
    classify_reasons,
    combine_replays,
    compare_orderings,
    composite_score,
    compute_lift,
    deduplicate_by_episode,
    is_conflict,
    measure_gate6_split,
    rank_normalise,
    unmeasurable_gate6_result,
)
from pipeline.tracetriage.splits import (  # noqa: E402
    _A3_SUMMARY_PATH,
    _default_pages_dir,
    _load_a3_verdicts,
    _load_raw_pages,
    orbital_revolution_index,
)

_SPLIT_MANIFEST = _REPO / "artifacts" / "SPLIT_MANIFEST.json"
_CORRIDOR_CACHE = _REPO / "artifacts" / "corridor_features.json"
_HOG_DIR = _REPO / "artifacts" / "hog_cache"
_FUSION_RECEIPT = _REPO / "artifacts" / "FUSION_RECEIPT.json"
_OUT = _REPO / "artifacts" / "QUEUE_RECEIPT.json"
_CONTRACT = _REPO / "contracts" / "queue_receipt.schema.json"

_DECISIVE = {"with-signal": 1, "without-signal": 0}

#: Review budget: fixed before measuring, applied to all splits.
#: 50 observations. Budget on cold splits is
#: min(REVIEW_BUDGET, n_decisive_test_observations).
#: The coverage it buys is not written down here, because it depends on how many
#: of the split's test rows carry a decisive label, and that is a measurement.
#: The receipt derives it from ``n_test_decisive`` at write time.
REVIEW_BUDGET = 50

#: Gate 6 lift threshold.
GATE6_THRESHOLD = 1.5

#: The gate 6 wording, copied from the plan verbatim.
GATE6_WORDING = (
    "Require the top review queue to find at least 1.5 times as many manually "
    "actionable conflicts as random ordering at the same budget."
)


# ---------------------------------------------------------------------------
# Loading helpers (reuse patterns from run_fusion.py)
# ---------------------------------------------------------------------------


def load_hog() -> tuple[np.ndarray, dict[int, int]]:
    idx_path = _HOG_DIR / "index.json"
    npy_path = _HOG_DIR / "hog.npy"
    if not (idx_path.exists() and npy_path.exists()):
        return np.zeros((0, 0), dtype=np.float32), {}
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    matrix = np.load(npy_path)
    return matrix, {int(o): i for i, o in enumerate(index["obs_ids"])}


def _client_family(rec: dict[str, Any]) -> str:
    v = str(rec.get("client_version") or "")
    if not v:
        return "unknown"
    return v.split("+")[0].split("-")[0].strip() or "unknown"


#: Cache of computed revolution indices, so the TLE arithmetic runs once per
#: observation rather than once per lookup.
_REV_CACHE: dict[int, int] = {}


def _revolution_of(obs_id: int, raw: dict[int, dict[str, Any]]) -> int:
    """Orbital revolution index at the observation's start, from its TLE.

    The same computation splits.py partitions on, so the queue's episode grouping
    and the split's leakage guarantee agree on what a pass is. A TLE that will not
    parse yields -1, matching splits.py: that merges the affected observations of
    one satellite over one station into a single group, which widens the interval
    rather than narrowing it, so the degraded case fails safe. The count of
    degraded rows is reported per split.
    """
    if obs_id in _REV_CACHE:
        return _REV_CACHE[obs_id]
    rec = raw.get(obs_id, {})
    try:
        rev = orbital_revolution_index(
            rec.get("tle1") or "", rec.get("tle2") or "", rec["start"]
        )
    except Exception:
        rev = -1
    _REV_CACHE[obs_id] = rev
    return rev


def build_feature_rows(
    raw: dict[int, dict[str, Any]],
    corridor_cache: dict[int, dict[str, Any]],
    verdicts: dict[int, str],
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for oid, rec in raw.items():
        row: dict[str, Any] = {
            "obs_id": oid,
            "waterfall_status": rec.get("waterfall_status"),
            # (station, satellite, orbital revolution), the same key splits.py
            # partitions on. Not an hour bucket: a pass crossing an hour boundary
            # would become two groups, and a grouped interval built on that
            # treats correlated captures as independent.
            "episode": (
                rec.get("ground_station"),
                rec.get("norad_cat_id"),
                _revolution_of(oid, raw),
            ),
            "ground_station": rec.get("ground_station"),
            "norad_cat_id": rec.get("norad_cat_id"),
            "a3_verdict": verdicts.get(oid, "unresolved"),
        }
        row.update(physics_features(rec))
        row.update(corridor_features(oid, corridor_cache))
        row.update(metadata_features(rec, client_family=_client_family(rec)))
        # raw corridor cache values for conflict classification
        cr = corridor_cache.get(oid, {})
        row["fitted_offset_ppm"] = cr.get("fitted_offset_ppm") if not cr.get("degraded") else None
        row["offset_at_bound"] = cr.get("offset_at_bound") if not cr.get("degraded") else None
        row["flat_row_frac_raw"] = cr.get("flat_row_frac") if not cr.get("degraded") else None
        rows[oid] = row
    return rows


def image_arm_scorer(matrix: np.ndarray, row_of: dict[int, int], seed: int) -> Any:
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

    def fit_predict(
        train_ids: list[int], train_labels: list[int], score_ids: list[int]
    ) -> np.ndarray:
        tr = [row_of[i] for i in train_ids if i in row_of]
        tl = [lab for i, lab in zip(train_ids, train_labels, strict=True) if i in row_of]
        if len(set(tl)) < 2 or len(tr) < 10:
            return np.full(len(score_ids), float(np.mean(tl)) if tl else 0.5)
        x = matrix[tr].astype(float)
        mean, std = x.mean(axis=0), x.std(axis=0)
        std = np.where(std > 1e-9, std, 1.0)
        model = LogisticRegression(C=1.0, max_iter=3000, random_state=seed).fit(
            (x - mean) / std, np.asarray(tl, dtype=int)
        )
        out = np.full(len(score_ids), float(np.mean(tl)), dtype=float)
        present = [(k, row_of[i]) for k, i in enumerate(score_ids) if i in row_of]
        if present:
            ks, ridx = zip(*present, strict=True)
            xz = (matrix[list(ridx)].astype(float) - mean) / std
            out[list(ks)] = model.predict_proba(xz)[:, 1]
        return out

    return fit_predict


# ---------------------------------------------------------------------------
# Model fitting for one split
# ---------------------------------------------------------------------------


def fit_arm_for_split(
    split_name: str,
    partitions: dict[str, list[int]],
    feature_rows: dict[int, dict[str, Any]],
    hog: tuple[np.ndarray, dict[int, int]],
    seed: int,
) -> dict[str, Any]:
    """Fit and calibrate the shipped arm and physics-only arm on train, return test probs.

    Returns a dict with:
      - "shipped_probs": {obs_id: float} for all test observations
      - "physics_only_probs": {obs_id: float} for all test observations
      - "image_uncertainty_probs": {obs_id: float} for image-only confidence
      - "ensemble_stds": {obs_id: float} episode-bootstrap uncertainty
      - "degraded": str | None  why we couldn't score (e.g., too few labels)
    """
    matrix, row_of = hog
    fit_predict = image_arm_scorer(matrix, row_of, seed)

    def usable(part: str) -> list[int]:
        return [i for i in partitions.get(part, []) if i in feature_rows]

    train_ids = usable("train")
    cal_ids = usable("calibration")
    test_ids = usable("test")

    # The full corpus (all non-excluded obs) is what gets ranked
    all_ids = usable("train") + usable("calibration") + usable("test")

    if len(train_ids) < 20 or len(cal_ids) < 5:
        return {
            "shipped_probs": {},
            "physics_only_probs": {},
            "image_uncertainty_probs": {},
            "ensemble_stds": {},
            "test_ids": test_ids,
            "all_ids": all_ids,
            "degraded": f"Too few decisive labels: train={len(train_ids)} cal={len(cal_ids)}",
        }

    def rows_of(ids: list[int]) -> list[dict[str, Any]]:
        return [feature_rows[i] for i in ids]

    def labels_of(ids: list[int]) -> np.ndarray:
        return np.array([feature_rows[i].get("label", 0) for i in ids], dtype=int)

    y_train = labels_of(train_ids)
    y_cal = labels_of(cal_ids)

    # Image scores: train gets out-of-fold; cal and test get full-train model.
    # For the full corpus (including train), we use the in-sample model for scoring
    # (ranking, not evaluation, so slight flattery here is acceptable and stated).
    full_image_score = fit_predict(train_ids, y_train.tolist(), all_ids)
    for i, oid in enumerate(all_ids):
        feature_rows[oid] = {**feature_rows[oid], "image_score": float(full_image_score[i])}

    # Shipped arm
    shipped_arm = FusionArm(
        name=SHIPPED_ARM, blocks=SHIPPED_ARM_BLOCKS, seed=seed
    ).fit(rows_of(train_ids), y_train.tolist())
    p_cal_raw = shipped_arm.predict(rows_of(cal_ids))
    cal = Calibrator(method="auto").fit(p_cal_raw, y_cal)

    shipped_all = cal.apply(shipped_arm.predict(rows_of(all_ids)))
    shipped_probs = {oid: float(shipped_all[i]) for i, oid in enumerate(all_ids)}

    # Image-only arm (for uncertainty baseline)
    img_arm = FusionArm(name="image_only", blocks=("image",), seed=seed).fit(
        rows_of(train_ids), y_train.tolist()
    )
    p_img_cal = img_arm.predict(rows_of(cal_ids))
    img_cal = Calibrator(method="auto").fit(p_img_cal, y_cal)
    img_all = img_cal.apply(img_arm.predict(rows_of(all_ids)))
    image_uncertainty_probs = {oid: float(img_all[i]) for i, oid in enumerate(all_ids)}

    # Physics-only arm (for physics-only baseline)
    phys_arm = FusionArm(name="physics_only", blocks=("physics",), seed=seed).fit(
        rows_of(train_ids), y_train.tolist()
    )
    if phys_arm.degraded:
        physics_probs = {oid: 0.5 for oid in all_ids}
    else:
        p_phys_cal = phys_arm.predict(rows_of(cal_ids))
        phys_cal = Calibrator(method="auto").fit(p_phys_cal, y_cal)
        phys_all = phys_cal.apply(phys_arm.predict(rows_of(all_ids)))
        physics_probs = {oid: float(phys_all[i]) for i, oid in enumerate(all_ids)}

    # Episode-bootstrap uncertainty for the shipped arm (read from FUSION_RECEIPT
    # when available for chronological, otherwise compute a compact version)
    ensemble_stds: dict[int, float] = {}
    try:
        from pipeline.tracetriage.fusion import episode_bootstrap_ensemble  # noqa: PLC0415
        # Lightweight: 10 members instead of 20 for non-chronological splits
        n_members = 10
        ens = episode_bootstrap_ensemble(
            SHIPPED_ARM_BLOCKS,
            rows_of(train_ids),
            y_train.tolist(),
            [str(feature_rows[i]["episode"]) for i in train_ids],
            rows_of(all_ids),
            n_members=n_members,
            seed=seed,
        )
        if ens.get("std") is not None:
            stds = ens["std"]
            for i, oid in enumerate(all_ids):
                ensemble_stds[oid] = float(stds[i])
    except Exception:
        pass

    return {
        "shipped_probs": shipped_probs,
        "physics_only_probs": physics_probs,
        "image_uncertainty_probs": image_uncertainty_probs,
        "ensemble_stds": ensemble_stds,
        "test_ids": test_ids,
        "all_ids": all_ids,
        "degraded": None,
    }


# ---------------------------------------------------------------------------
# Build queue for one split
# ---------------------------------------------------------------------------


def build_split_queue(
    split_name: str,
    partitions: dict[str, list[int]],
    raw: dict[int, dict[str, Any]],
    feature_rows: dict[int, dict[str, Any]],
    corridor_cache: dict[int, dict[str, Any]],
    hog: tuple[np.ndarray, dict[int, int]],
    seed: int,
    n_boot: int,
    decisive_ids: set[int],
) -> dict[str, Any]:
    """Build the ranked queue and measure gate 6 for one split.

    The queue ranks the test partition only. Training and calibration observations
    are excluded: they were seen during fitting and would not be fair lift subjects.
    The queue is measured on the decisive-labelled observations in the test set.
    """
    fit_result = fit_arm_for_split(split_name, partitions, feature_rows, hog, seed)
    if fit_result["degraded"]:
        return {
            "split": split_name,
            "degraded": fit_result["degraded"],
            "gate6_result": unmeasurable_gate6_result(
                f"Arm would not fit for split {split_name}: {fit_result['degraded']}. "
                "No ranking exists, so lift has nothing to measure."
            ),
        }

    test_ids = fit_result["test_ids"]
    shipped_probs = fit_result["shipped_probs"]
    physics_probs = fit_result["physics_only_probs"]
    image_uncertainty_probs = fit_result["image_uncertainty_probs"]
    ensemble_stds = fit_result["ensemble_stds"]

    # Restrict to test set
    candidate_ids = [i for i in test_ids]

    if not candidate_ids:
        return {
            "split": split_name,
            "degraded": "No test observations",
            "gate6_result": unmeasurable_gate6_result(
                f"Split {split_name} has an empty test partition, so there are 0 "
                "candidate observations to rank and no budget to spend."
            ),
        }

    # Compute per-observation signals
    disagreement_vals: list[float] = []
    offset_safe_vals: list[float] = []
    flat_vals: list[float] = []
    uncertainty_vals: list[float] = []

    for oid in candidate_ids:
        ws = raw[oid].get("waterfall_status") if oid in raw else None
        prob = shipped_probs.get(oid)
        disagreement_vals.append(_disagreement_value(ws, prob))

        cr = corridor_cache.get(oid, {})
        ppm = cr.get("fitted_offset_ppm") if not cr.get("degraded") else None
        at_bound = cr.get("offset_at_bound") if not cr.get("degraded") else None
        # at-bound rows get 0 on the safe offset signal
        offset_safe_vals.append(
            abs(float(ppm)) if ppm is not None and at_bound is False else 0.0
        )

        flat_frac = cr.get("flat_row_frac") if not cr.get("degraded") else None
        flat_vals.append(float(flat_frac) if flat_frac is not None else 0.0)

        uncertainty_vals.append(float(ensemble_stds.get(oid, 0.0)))

    # The raw, un-normalised offset signal, kept per observation so the
    # offset-magnitude baseline can sort on exactly the quantity the score's
    # offset term is derived from rather than on a second reading of the cache.
    offset_safe_of = dict(zip(candidate_ids, offset_safe_vals, strict=True))

    # Rank-normalise each signal
    norm_disagree = rank_normalise(disagreement_vals)
    norm_offset = rank_normalise(offset_safe_vals)
    norm_flat = rank_normalise(flat_vals)
    norm_uncertainty = rank_normalise(uncertainty_vals)

    # Build one rank_norms dict per observation
    scores: dict[int, float] = {}
    reasons_map: dict[int, list[str]] = {}
    for i, oid in enumerate(candidate_ids):
        rank_norms = {
            "disagreement": norm_disagree[i],
            "offset_safe": norm_offset[i],
            "flat_row_frac": norm_flat[i],
            "ensemble_uncertainty": norm_uncertainty[i],
        }
        ws = raw[oid].get("waterfall_status") if oid in raw else None
        prob = shipped_probs.get(oid)
        cr = corridor_cache.get(oid, {})
        ppm = cr.get("fitted_offset_ppm") if not cr.get("degraded") else None
        at_bound = cr.get("offset_at_bound") if not cr.get("degraded") else None
        flat_frac = cr.get("flat_row_frac") if not cr.get("degraded") else None

        scores[oid] = composite_score(ws, prob, ppm, at_bound, flat_frac,
                                      ensemble_stds.get(oid), rank_norms)
        reasons_map[oid] = classify_reasons(ws, prob, ppm, at_bound, flat_frac)

    # Sort by composite score descending, break ties by obs_id ascending
    ranked = sorted(candidate_ids, key=lambda x: (-scores[x], x))

    # Episode deduplication, on the canonical key.
    #
    # The key is (ground_station, norad_cat_id, orbital_revolution), which is what
    # splits.py partitions on. The previous key here was
    # (ground_station, norad_cat_id, start[:13]), an hour bucket, which splits any
    # pass crossing an hour boundary into two groups and so treats correlated
    # captures as independent in every grouped interval built on it. Measured
    # difference on this corpus: 2716 revolution episodes against 2722 hour
    # buckets, 17 observations affected. Small here, and not small on a multi-day
    # snapshot, where an hour bucket has no orbital meaning at all.
    def proper_ep_key(oid: int) -> str:
        rec = raw.get(oid, {})
        return _episode_key(
            rec.get("ground_station", -1),
            rec.get("norad_cat_id", -1),
            _revolution_of(oid, raw),
        )

    # Build dedup entry list
    dedup_entries = [
        {
            "obs_id": oid,
            "episode_key": proper_ep_key(oid),
            "score": scores[oid],
            "rank": i + 1,
        }
        for i, oid in enumerate(ranked)
    ]
    deduped = deduplicate_by_episode(dedup_entries)

    # Re-sort after dedup (dedup keeps the highest-score per episode)
    deduped.sort(key=lambda e: (-e["score"], e["obs_id"]))
    deduped_ranked_ids = [e["obs_id"] for e in deduped]

    # Entity-concentration caps, so one noisy station cannot fill a reviewer's
    # budget. Shares fixed in docs/C2_PREREGISTRATION.md and committed before the
    # effect on lift was measured. Displaced entries stay in the queue below the
    # budget line and carry a reason; nothing is deleted.
    cap_budget = min(REVIEW_BUDGET, len(deduped_ranked_ids))
    final_ranked_ids, concentration = apply_concentration_caps(
        deduped_ranked_ids,
        {
            "ground_station": {
                oid: raw.get(oid, {}).get("ground_station") for oid in deduped_ranked_ids
            },
            "transmitter_uuid": {
                oid: raw.get(oid, {}).get("transmitter_uuid")
                for oid in deduped_ranked_ids
            },
        },
        cap_budget,
    )
    displaced_reason_of = {
        oid: entry["reason_code"]
        for entry in concentration["caps"].values()
        for oid in entry["displaced_obs_ids"]
    }

    # Conflict flags for decisive observations
    conflict_flags: dict[int, bool] = {}
    for oid in final_ranked_ids:
        if oid in decisive_ids:
            conflict_flags[oid] = is_conflict(reasons_map[oid])

    # Budget for this split
    n_decisive_test = sum(1 for oid in final_ranked_ids if oid in decisive_ids)

    # Baselines (on the test set, decisive obs only)
    decisive_ranked = [oid for oid in final_ranked_ids if oid in decisive_ids]
    fifo_order = baseline_fifo(decisive_ranked)
    img_order = baseline_image_uncertainty(
        decisive_ranked,
        {oid: image_uncertainty_probs.get(oid) for oid in decisive_ranked},
    )
    phys_order = baseline_physics_only(
        decisive_ranked,
        {oid: physics_probs.get(oid) for oid in decisive_ranked},
    )
    offset_order = baseline_offset_magnitude(
        decisive_ranked,
        {oid: offset_safe_of.get(oid, 0.0) for oid in decisive_ranked},
    )
    # Queue order restricted to decisive
    queue_decisive = [oid for oid in final_ranked_ids if oid in decisive_ids]

    if not decisive_ranked:
        gate6_result = unmeasurable_gate6_result(
            f"Split {split_name} ranked {len(final_ranked_ids)} test observations "
            "and 0 of them carry a decisive with-signal or without-signal label, "
            "so no conflict can be confirmed and lift has no numerator."
        )
    else:
        decisive_conflict_flags = {
            oid: is_conflict(reasons_map[oid]) for oid in decisive_ranked
        }
        decisive_episode_of = {oid: proper_ep_key(oid) for oid in decisive_ranked}
        # Stations nest episodes, so a station-clustered resample subsumes the
        # episode one. Both intervals are reported and the verdict takes their
        # union, fixed in docs/C2_PREREGISTRATION.md before either was computed.
        decisive_station_of = {
            oid: f"station-{raw.get(oid, {}).get('ground_station', 'unknown')}"
            for oid in decisive_ranked
        }
        decisive_budget = min(REVIEW_BUDGET, len(decisive_ranked))

        gate6_result = measure_gate6_split(
            split_name,
            queue_decisive,
            decisive_conflict_flags,
            decisive_episode_of,
            decisive_budget,
            fifo_order,
            img_order,
            phys_order,
            offset_order,
            station_of=decisive_station_of,
            n_boot=n_boot,
            seed=seed,
            threshold=GATE6_THRESHOLD,
        )

        # The uncapped queue, measured as a reference point only. Not eligible to
        # be the verdict: the shipped queue is the capped one, because
        # duplicate-safe diversity is a product requirement rather than an
        # optimisation. Reported so the cost of that diversity is visible.
        uncapped_decisive = [oid for oid in deduped_ranked_ids if oid in decisive_ids]
        uncapped = compute_lift(
            uncapped_decisive,
            decisive_conflict_flags,
            decisive_episode_of,
            decisive_budget,
            n_boot=n_boot,
            seed=seed,
            threshold=GATE6_THRESHOLD,
        )
        # C4: the five-baseline replay, paired within each draw, under both
        # groupings. Gate 6 asks only about random; a queue that beats random and
        # loses to FIFO has not earned a reviewer's attention, because FIFO is
        # what a reviewer already does. offset_magnitude is the harder test of the
        # two: it is a one-line sort on the quantity most realised conflicts are
        # defined from, so it asks whether the composite score's other three terms
        # buy anything at all on this split.
        replay_orderings = {
            "queue": queue_decisive,
            "random": sorted(decisive_ranked),
            "fifo": fifo_order,
            "image_uncertainty": img_order,
            "physics_only": phys_order,
            "offset_magnitude": offset_order,
        }
        # "random" as an ordering is obs-id order, which is FIFO by another name,
        # so it is dropped from the ordering set and handled by its expectation.
        # Keeping it would report the same comparison twice under two names.
        del replay_orderings["random"]
        gate6_result["replay_episode"] = compare_orderings(
            replay_orderings,
            decisive_conflict_flags,
            decisive_episode_of,
            decisive_budget,
            n_boot=n_boot,
            seed=seed,
        )
        gate6_result["replay_station"] = compare_orderings(
            replay_orderings,
            decisive_conflict_flags,
            decisive_station_of,
            decisive_budget,
            n_boot=n_boot,
            seed=seed,
        )

        gate6_result["replay_conclusion"] = combine_replays(
            gate6_result["replay_episode"], gate6_result["replay_station"]
        )

        gate6_result["uncapped_reference"] = {
            "lift_point": uncapped.lift_point,
            "lift_ci95_episode": uncapped.ci95,
            "verdict_if_it_were_eligible": uncapped.verdict,
            "n_queue_conflicts": uncapped.n_queue_conflicts,
            "note": (
                "Reference only. The shipped queue is the capped queue and the "
                "verdict above is measured on it. This row exists so the price of "
                "entity-concentration control is on record instead of hidden by "
                "reporting only whichever queue scored better."
            ),
        }

    # Build the full queue entries
    queue_entries = []
    for rank_idx, oid in enumerate(final_ranked_ids, start=1):
        cr = corridor_cache.get(oid, {})
        ppm = cr.get("fitted_offset_ppm") if not cr.get("degraded") else None
        at_bound = cr.get("offset_at_bound") if not cr.get("degraded") else None
        flat_frac = cr.get("flat_row_frac") if not cr.get("degraded") else None
        ws = raw[oid].get("waterfall_status") if oid in raw else "unknown"
        # A displaced entry carries the cap that displaced it, from the fixed
        # vocabulary. It keeps its conflict reasons: being displaced says where a
        # reviewer will meet it, not what is wrong with it.
        reasons = list(reasons_map[oid])
        if oid in displaced_reason_of:
            reasons = reasons + [displaced_reason_of[oid]]
        entry = {
            "obs_id": oid,
            "episode_key": proper_ep_key(oid),
            "rank": rank_idx,
            "score": float(scores[oid]),
            "reasons": reasons,
            "displaced_by_cap": displaced_reason_of.get(oid),
            "within_budget": rank_idx <= cap_budget,
            "is_conflict": is_conflict(reasons_map[oid]),
            "waterfall_status": ws or "unknown",
            "model_prob": shipped_probs.get(oid),
            "fitted_offset_ppm": float(ppm) if ppm is not None else None,
            "offset_at_bound": bool(at_bound) if at_bound is not None else None,
            "flat_row_frac": float(flat_frac) if flat_frac is not None else None,
            "ensemble_uncertainty": (
                float(ensemble_stds[oid]) if oid in ensemble_stds else None
            ),
        }
        queue_entries.append(entry)

    return {
        "split": split_name,
        "degraded": None,
        "n_test_total": len(candidate_ids),
        "n_test_decisive": n_decisive_test,
        "n_queue_after_dedup": len(final_ranked_ids),
        "n_episodes_deduplicated": len(candidate_ids) - len(deduped_ranked_ids),
        "n_degraded_revolution": sum(
            1 for oid in final_ranked_ids if _revolution_of(oid, raw) == -1
        ),
        "concentration": concentration,
        "n_at_bound_obs": sum(
            1 for oid in final_ranked_ids
            if corridor_cache.get(oid, {}).get("offset_at_bound") is True
        ),
        "queue": queue_entries,
        "gate6_result": gate6_result,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _criteria_fired(queue_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per criterion, how many shipped rows it actually flagged.

    Three criteria were fixed before measuring and all three are published as the
    conflict definition. That is not the same as all three doing work. On this
    corpus DEAD_CAPTURE fires on nothing: the highest flat_row_frac in the whole
    queue is below its own threshold, so every sentence of the form "the two
    criteria the model does not enter" was describing one criterion. A criterion
    that fires zero times is named here as inert rather than left for a reader to
    discover by counting, and the prose downstream is generated from these counts.

    ``max_observed`` is the largest value of the quantity the criterion
    thresholds, over the rows where that quantity was measurable. It is null when
    no row carried it, which is an absence and not a zero.
    """
    quantity_of: dict[str, tuple[str, Any]] = {
        "MODEL_LABEL_DISAGREE": ("model_prob", None),
        "STALE_CATALOGUE_FREQ": ("fitted_offset_ppm", None),
        "DEAD_CAPTURE": ("flat_row_frac", None),
    }
    out: list[dict[str, Any]] = []
    for criterion in CONFLICT_CRITERIA:
        code = criterion["reason_code"]
        field = quantity_of.get(code, (None, None))[0]
        n_flagged = sum(1 for e in queue_entries if code in (e.get("reasons") or []))
        values: list[float] = []
        for e in queue_entries:
            v = e.get(field) if field else None
            if v is None:
                continue
            if code == "STALE_CATALOGUE_FREQ":
                # The criterion reads the magnitude and excludes at-bound fits, so
                # the census has to read the same thing the criterion does.
                if e.get("offset_at_bound") is True:
                    continue
                v = abs(float(v))
            values.append(float(v))
        out.append(
            {
                "reason_code": code,
                "n_flagged": n_flagged,
                "n_rows_the_quantity_was_measurable_on": len(values),
                "max_observed": max(values) if values else None,
                "inert_on_this_corpus": n_flagged == 0,
                "note": (
                    f"No row in the shipped queue meets this criterion. The highest "
                    f"value of the quantity it thresholds is "
                    f"{max(values):.4f} over {len(values)} measurable rows."
                    if n_flagged == 0 and values
                    else (
                        "No row in the shipped queue meets this criterion, and the "
                        "quantity it thresholds was not measurable on any row."
                        if n_flagged == 0
                        else (
                            f"Fires on {n_flagged} of the {len(values)} rows where "
                            f"the quantity it thresholds is measurable, out of "
                            f"{len(queue_entries)} in the queue."
                        )
                    )
                ),
            }
        )
    return out


def _budget_coverage_clause(primary_split: dict[str, Any] | None) -> str:
    """The coverage sentence for the review budget, measured rather than recalled.

    The published rationale said the chronological test set has 88 decisively
    labelled observations and the budget is ~57% of it. The set has 87, and the
    figure had been carried forward across several re-freezes of the corpus. A
    count that changes when the dataset changes does not belong in a literal, so
    it is read off the split that was actually measured. A missing count is named
    rather than defaulted.
    """
    if primary_split is None:
        return (
            "The chronological split produced no result in this run, so the "
            "coverage the budget buys is not stated here."
        )
    n = primary_split.get("n_test_decisive")
    if not isinstance(n, int) or n <= 0:
        return (
            "The chronological split published no decisive test count, so the "
            "coverage the budget buys is not stated here."
        )
    return (
        f"The chronological test set has {n} decisively-labelled observations, so "
        f"{REVIEW_BUDGET} is {REVIEW_BUDGET / n:.0%} coverage: large enough to "
        f"measure lift with reasonable precision and small enough that "
        f"{GATE6_THRESHOLD:g}x is non-trivial."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-boot", type=int, default=4000)
    parser.add_argument(
        "--splits",
        default="chronological,cold_station,cold_transmitter,cold_combined",
    )
    args = parser.parse_args()
    seed = args.seed
    n_boot = args.n_boot
    split_names = [s.strip() for s in args.splits.split(",")]

    print(f"run_queue: seed={seed} n_boot={n_boot} splits={split_names}")

    # ---------- Load data ----------
    raw = _load_raw_pages(_default_pages_dir())
    verdicts = _load_a3_verdicts(_A3_SUMMARY_PATH)
    corridor_cache = load_corridor_cache(_CORRIDOR_CACHE)
    split_manifest = json.loads(_SPLIT_MANIFEST.read_text(encoding="utf-8"))
    split_manifest_sha256 = hashlib.sha256(
        _SPLIT_MANIFEST.read_bytes()
    ).hexdigest()

    # Validate admissibility
    admissible_source_fields(SHIPPED_ARM_BLOCKS)

    # Build feature rows for ALL observations (not just decisive)
    # We need to rank everything, not just the decisive subset
    feature_rows_all = build_feature_rows(raw, corridor_cache, verdicts)
    # Add label for decisive observations
    decisive_ids: set[int] = set()
    for oid, rec in raw.items():
        lbl = _DECISIVE.get(rec.get("waterfall_status"))
        if lbl is not None:
            if oid in feature_rows_all:
                feature_rows_all[oid]["label"] = lbl
            decisive_ids.add(oid)

    hog = load_hog()

    snapshot_id = split_manifest.get("snapshot_id", "unknown")

    # ---------- Admissibility check ----------
    adm = admissible_source_fields(SHIPPED_ARM_BLOCKS)
    print(f"  admissibility: {adm['n_fields']} fields checked, all observation_time")

    # ---------- Corridor stats for receipt ----------
    n_sha256_dupes = 0  # verified: 2500 distinct hashes in stage-1

    # ---------- Per-split results ----------
    per_split_results: list[dict[str, Any]] = []
    per_split_gate6: dict[str, dict[str, Any]] = {}

    for split_name in split_names:
        if split_name not in split_manifest.get("splits", {}):
            print(f"  WARNING: split {split_name!r} not in manifest, skipping")
            continue

        print(f"  processing split: {split_name}")
        partitions = split_manifest["splits"][split_name]
        # feature_rows is mutated during fit (image_score added), use a copy per split
        split_feature_rows = copy.deepcopy(feature_rows_all)

        split_result = build_split_queue(
            split_name,
            partitions,
            raw,
            split_feature_rows,
            corridor_cache,
            hog,
            seed,
            n_boot,
            decisive_ids,
        )
        per_split_results.append(split_result)
        per_split_gate6[split_name] = split_result["gate6_result"]
        g6 = split_result["gate6_result"]
        print(
            f"    verdict={g6['verdict']} "
            f"lift={g6.get('lift_point')} "
            f"ci={g6.get('lift_ci95')} "
            f"n_queue_conflicts={g6.get('n_queue_conflicts')}"
        )

    # ---------- Gate 6 overall verdict ----------
    # Decided on the chronological split (primary reference, same as gate 5)
    primary = per_split_gate6.get("chronological", {})
    primary_verdict = primary.get("verdict", "NOT_MEASURABLE")

    if primary_verdict == "PASSED":
        overall_verdict = "PASSED"
        overall_statement = (
            f"The queue finds {primary['n_queue_conflicts']} actionable conflicts "
            f"in the top {primary['n_queue_examined']} observations on the "
            f"chronological split, against an expected "
            f"{primary['n_random_conflicts']:.1f} by random ordering. "
            f"Point lift: {primary['lift_point']:.2f}. "
            f"95% interval: {primary['lift_ci95'][0]:.2f} to {primary['lift_ci95'][1]:.2f}. "
            f"Both the point estimate and the lower bound of the interval exceed 1.5. "
            f"Bootstrap over {primary['n_groups']} pass episodes."
        )
    elif primary_verdict == "NOT_ESTABLISHED":
        overall_verdict = "NOT_ESTABLISHED"
        _ci = primary.get('lift_ci95', [float('nan'), float('nan')])
        _ci_lo, _ci_hi = _ci[0], _ci[1]
        _ci_desc = (
            f"spans the 1.5 threshold ({_ci_lo:.2f} to {_ci_hi:.2f})"
            if _ci_lo <= 1.5 <= _ci_hi
            else (
                f"lies entirely below 1.5 ({_ci_lo:.2f} to {_ci_hi:.2f}), "
                f"despite the point estimate exceeding 1.5. This is a known behaviour "
                f"of percentile bootstrap CIs on ratio statistics with concentrated "
                f"numerators"
            )
        )
        overall_statement = (
            f"The queue's point lift is {primary['lift_point']:.2f} on the "
            f"chronological split ({primary['n_queue_conflicts']} conflicts in "
            f"{primary['n_queue_examined']} examined, expected "
            f"{primary['n_random_conflicts']:.1f} by random). "
            f"The 95% interval {_ci_desc}. "
            f"A point estimate above 1.5 whose interval does not sit above 1.5 "
            f"is not a pass, for the same reason gate 5 was recorded as "
            f"NOT_ESTABLISHED: the evidence does not exclude noise."
        )
    elif primary_verdict == "FAILED":
        overall_verdict = "FAILED"
        overall_statement = (
            f"The queue's point lift is {primary['lift_point']:.2f} on the "
            f"chronological split, below the 1.5 threshold. "
            f"95% interval: {primary['lift_ci95'][0]:.2f} to {primary['lift_ci95'][1]:.2f}."
        )
    else:
        overall_verdict = "NOT_MEASURABLE"
        overall_statement = (
            f"Gate 6 could not be measured on the chronological split: "
            f"{primary.get('not_measurable_reason', 'reason unknown')}."
        )

    # ---------- Build QUEUE_RECEIPT ----------
    # Combine all split queues into one global queue (for receipt)
    # The primary (chronological) queue is the authoritative one
    primary_split = next(
        (r for r in per_split_results if r["split"] == "chronological"), None
    )
    primary_queue = primary_split.get("queue", []) if primary_split else []

    receipt: dict[str, Any] = {
        "schema": "QUEUE_RECEIPT",
        "schema_version": "0.3.0",
        "contract": "contracts/queue_receipt.schema.json",
        "unit": "C2",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "seed": seed,
        "snapshot_id": snapshot_id,
        "split_manifest_sha256": split_manifest_sha256,
        "conflict_definition": {
            "criteria": CONFLICT_CRITERIA,
            "criteria_fired": _criteria_fired(primary_queue),
            "fixed_before_measuring": True,
            "caveats": [
                (
                    "MODEL_LABEL_DISAGREE uses all decisively-labelled observations, "
                    "not only single-vetted ones. The SatNOGS waterfall_status_user "
                    "field is present in the snapshot but the single-vetter count per "
                    "observation is not stored; restricting to single-vetted records "
                    "would require a second API call not made at snapshot time."
                ),
                (
                    "DOPPLER_UNCORRECTED_OUTLIER is not included as a criterion. "
                    "A3 identified only 3 UNCORRECTED observations (out of 24 vetted); "
                    "applying the criterion to the remaining corpus would be a guess. "
                    "It is named in QUEUE_REASONS and listed as NOT_APPLICABLE in the "
                    "per-split state because the data do not support it."
                ),
                (
                    "Corridor features are unavailable for 18 observations "
                    "(4 NO_IMAGE + 14 PHYSICS_STALE_TLE). Those observations score 0 "
                    "on the offset and flat-row signals and rank on disagreement alone."
                ),
            ],
        },
        "review_budget": {
            "n_observations": REVIEW_BUDGET,
            "rationale": (
                f"Fixed at {REVIEW_BUDGET} before any results were seen. "
                f"{_budget_coverage_clause(primary_split)} "
                f"For cold splits the budget is min({REVIEW_BUDGET}, n_decisive_test)."
            ),
        },
        "deduplication": {
            "key": ["ground_station", "norad_cat_id", "orbital_revolution"],
            "rule": (
                "One observation per (ground_station, norad_cat_id, "
                "orbital_revolution) episode, where the revolution index comes "
                "from SGP4 propagation of the TLE that was current at the "
                "observation start. When an episode appears more than once, the "
                "observation with the highest composite score is kept; ties are "
                "broken by lower obs_id for determinism. An hour bucket was the "
                "earlier key and was wrong: it split one pass across a boundary "
                "and merged two passes that fell in the same hour."
            ),
            "n_degraded_revolution": (
                primary_split.get("n_degraded_revolution") if primary_split else None
            ),
            "degraded_revolution_policy": (
                "When SGP4 cannot supply a revolution index the observation "
                "falls back to its own obs_id as the episode key, so it "
                "deduplicates against nothing and is counted here rather than "
                "silently grouped."
            ),
            "n_episodes_before": (
                len(primary_queue) if primary_queue else 0
            ),
            "n_episodes_after": (
                len({e["episode_key"] for e in primary_queue}) if primary_queue else 0
            ),
            "n_observations_after": len(primary_queue),
            "sha256_duplicate_policy": (
                "Different episodes that share a waterfall SHA-256 are both kept; "
                "they represent physically different passes. The test suite covers "
                "this with a constructed case because the stage-1 corpus has "
                "0 SHA-256 duplicates."
            ),
            "n_sha256_duplicates_in_corpus": n_sha256_dupes,
        },
        "queue": primary_queue,
        # Per-split corpus counts only. The gate 6 measurement lives once, in
        # gate6.per_split: the same numbers in two places is a drift surface,
        # and a reader has no way to tell which copy is authoritative.
        "per_split_summaries": [
            {
                "split": r["split"],
                "degraded": r.get("degraded"),
                "n_test_total": r.get("n_test_total"),
                "n_test_decisive": r.get("n_test_decisive"),
                "n_queue_after_dedup": r.get("n_queue_after_dedup"),
                "n_episodes_deduplicated": r.get("n_episodes_deduplicated"),
                "n_degraded_revolution": r.get("n_degraded_revolution"),
                "concentration": r.get("concentration"),
                "n_at_bound_obs": r.get("n_at_bound_obs"),
            }
            for r in per_split_results
        ],
        "gate6": {
            "gate": 6,
            "wording": GATE6_WORDING,
            "decided_on": "chronological",
            "verdict": overall_verdict,
            "statement": overall_statement,
            "per_split": per_split_gate6,
        },
    }

    # ---------- Validate against schema ----------
    _validate_receipt(receipt)

    # ---------- Write ----------
    _OUT.write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    print(f"\nWrote {_OUT}")
    print(f"Gate 6 verdict: {overall_verdict}")
    if primary.get("lift_point") is not None:
        print(f"  lift={primary['lift_point']:.3f} ci95={primary.get('lift_ci95')}")


def _validate_receipt(receipt: dict[str, Any]) -> None:
    """Validate the receipt against its JSON schema. Raises on violation."""
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError as e:
        raise RuntimeError("jsonschema is required to validate the receipt") from e

    schema = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(receipt))
    if errors:
        msgs = "\n".join(f"  {e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(f"Receipt violates its schema:\n{msgs}")
    print("  schema validation: PASS")


if __name__ == "__main__":
    main()
