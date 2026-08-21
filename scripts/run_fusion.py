"""Fit the fusion ladder, calibrate it, and measure kill gate 5.

Gate 5, from the plan: "Require the physics-conditioned model to lower Brier score
against a calibrated image-only baseline." This script measures that with a paired
bootstrap over pass episodes and writes the verdict to artifacts/FUSION_RECEIPT.json,
including the case where the gate fails.

Every arm on the ladder gets identical treatment: fitted on train, calibrated on the
calibration partition, scored once on test. The image-only reference is calibrated the
same way as the challenger, because comparing a calibrated model against an
uncalibrated one measures the calibration step rather than the physics.

Usage:
    .venv/Scripts/python.exe scripts/run_fusion.py [--splits chronological,cold_station]
        [--seed 42] [--n-boot 10000]
"""

from __future__ import annotations

import argparse
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
    ARM_LADDER,
    GATE5_CHALLENGER,
    GATE5_REFERENCE,
    SHIPPED_ARM,
    SHIPPED_ARM_BLOCKS,
    Calibrator,
    FusionArm,
    auc,
    brier,
    calibration_slope_intercept,
    clustered_multiplicity_adjusted,
    clustered_paired_bootstrap,
    clustered_statistic_difference,
    episode_bootstrap_ensemble,
    expected_calibration_error,
    seed_sensitivity,
)
from pipeline.tracetriage.ood import OodDetector, risk_by_novelty  # noqa: E402
from pipeline.tracetriage.selective import (  # noqa: E402
    area_under_risk_coverage,
    risk_coverage_curve,
    threshold_for_risk_ceiling,
    verify_ceiling,
)
from pipeline.tracetriage.splits import (  # noqa: E402
    _A3_SUMMARY_PATH,
    _MANIFEST_PATH,
    _default_pages_dir,
    _load_a3_verdicts,
    _load_raw_pages,
)

#: How many risk-coverage comparisons each split reports: the gate-5 challenger against
#: image-only, and the shipped arm against image-only. Named so the multiplicity family
#: size can be computed before the selective block runs.
#:
#: Fixed by the ladder, which was declared before anything was fitted. A family size that
#: shrank because one comparison turned out vacuous would be a family size influenced by
#: the results, which is the thing a correction exists to prevent.
_N_AURC_COMPARISONS = 2

_HOG_DIR = _REPO / "artifacts" / "hog_cache"
_SPLIT_MANIFEST = _REPO / "artifacts" / "SPLIT_MANIFEST.json"
_DECISIVE = {"with-signal": 1, "without-signal": 0}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_hog() -> tuple[np.ndarray, dict[int, int]]:
    """Return (matrix, {obs_id: row_index}). Empty when the cache is absent."""
    idx_path = _HOG_DIR / "index.json"
    npy_path = _HOG_DIR / "hog.npy"
    if not (idx_path.exists() and npy_path.exists()):
        return np.zeros((0, 0), dtype=np.float32), {}
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    matrix = np.load(npy_path)
    return matrix, {int(o): i for i, o in enumerate(index["obs_ids"])}


def build_feature_rows(
    raw: dict[int, dict[str, Any]],
    corridor_cache: dict[int, dict[str, Any]],
    verdicts: dict[int, str],
) -> dict[int, dict[str, Any]]:
    """One feature dict per decisive observation, image score filled in later."""
    rows: dict[int, dict[str, Any]] = {}
    for oid, rec in raw.items():
        label = _DECISIVE.get(rec.get("waterfall_status"))
        if label is None:
            continue
        row: dict[str, Any] = {
            "obs_id": oid,
            "label": label,
            "episode": (
                rec.get("ground_station"),
                rec.get("norad_cat_id"),
                rec.get("start", "")[:13],
            ),
            "a3_verdict": verdicts.get(oid, "unresolved"),
        }
        row.update(physics_features(rec))
        row.update(corridor_features(oid, corridor_cache))
        row.update(metadata_features(rec, client_family=_client_family(rec)))
        rows[oid] = row
    return rows


def _client_family(rec: dict[str, Any]) -> str:
    """Coarse capture-software family from client_version.

    Coarse on purpose. The full version string is close to a station identifier,
    because a given operator runs one version for months.
    """
    v = str(rec.get("client_version") or "")
    if not v:
        return "unknown"
    return v.split("+")[0].split("-")[0].strip() or "unknown"


# ---------------------------------------------------------------------------
# The image arm
# ---------------------------------------------------------------------------


def image_arm_scorer(matrix: np.ndarray, row_of: dict[int, int], seed: int) -> Any:
    """Return ``fit_predict(train_ids, train_labels, score_ids) -> np.ndarray``.

    Plain L2 logistic regression on standardised HOG vectors. No inner calibration:
    every arm on the ladder is calibrated once, later, on the calibration partition, so
    calibrating this arm separately would give the image reference a second helping of
    the same treatment and make the gate-5 comparison measure calibration effort.
    """
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
        model = LogisticRegression(
            C=1.0, max_iter=3000, random_state=seed
        ).fit((x - mean) / std, np.asarray(tl, dtype=int))

        out = np.full(len(score_ids), float(np.mean(tl)), dtype=float)
        present = [(k, row_of[i]) for k, i in enumerate(score_ids) if i in row_of]
        if present:
            ks, ridx = zip(*present, strict=True)
            xz = (matrix[list(ridx)].astype(float) - mean) / std
            out[list(ks)] = model.predict_proba(xz)[:, 1]
        return out

    return fit_predict


# ---------------------------------------------------------------------------
# One split
# ---------------------------------------------------------------------------


def usable_ids(
    partitions: dict[str, Any], feature_rows: dict[int, Any], part: str
) -> list[int]:
    """Decisive observation ids in one partition of one split.

    Module level because the multiplicity family has to be counted before any split is
    scored, and a second copy of this filter would let the family size and the splits
    the rule reads disagree about which splits are eligible.
    """
    return [i for i in partitions.get(part, []) if i in feature_rows]


def eligible_split_names(
    manifest: dict[str, Any], feature_rows: dict[int, Any], requested: list[str]
) -> list[str]:
    """Splits the ablation rule is allowed to read, decided before anything is fitted.

    SPACE-S7: the multiplicity correction has to be over the family the decision rule
    ranges across, and that rule is a disjunction over splits: retain a block if some
    arm containing it beat image-only on SOME split above the training floor. So the
    family size cannot be known inside one split, and this pass answers it up front.

    ``chronological_size_matched`` is excluded because it is a control on the
    chronological split rather than an independent split the rule may read, which is the
    same exclusion the ablation conclusion applies.
    """
    out = []
    for name in requested:
        partitions = manifest["splits"].get(name)
        if partitions is None or name == "chronological_size_matched":
            continue
        counts = {
            part: len(usable_ids(partitions, feature_rows, part))
            for part in ("train", "calibration", "test")
        }
        if min(counts.values()) < 20:
            continue
        if counts["train"] < MIN_TRAIN_FOR_BLOCK_VERDICT:
            continue
        out.append(name)
    return out


def run_split(
    split_name: str,
    partitions: dict[str, list[int]],
    feature_rows: dict[int, dict[str, Any]],
    hog: tuple[np.ndarray, dict[int, int]],
    seed: int,
    n_boot: int,
    station_of: dict[int, Any],
    transmitter_of: dict[int, str],
    n_eligible_splits: int,
) -> dict[str, Any]:
    matrix, row_of = hog
    fit_predict = image_arm_scorer(matrix, row_of, seed)

    def usable(part: str) -> list[int]:
        return usable_ids(partitions, feature_rows, part)

    train_ids, cal_ids, test_ids = usable("train"), usable("calibration"), usable("test")
    counts = {
        "train": len(train_ids),
        "calibration": len(cal_ids),
        "test": len(test_ids),
        "train_with_image": sum(1 for i in train_ids if i in row_of),
        "test_with_image": sum(1 for i in test_ids if i in row_of),
        "test_with_corridor": sum(
            1 for i in test_ids if feature_rows[i].get("sigma_curved") is not None
        ),
    }

    if min(len(train_ids), len(cal_ids), len(test_ids)) < 20:
        return {
            "split": split_name,
            "degraded": "TOO_FEW_DECISIVE_LABELS",
            "counts": counts,
            "note": (
                "A partition with fewer than 20 decisive labels cannot support a "
                "calibrated comparison. Reported rather than scored, because a Brier "
                "score on a handful of rows is a number without a meaning."
            ),
        }

    def rows_of(ids: list[int]) -> list[dict[str, Any]]:
        return [feature_rows[i] for i in ids]

    def labels_of(ids: list[int]) -> np.ndarray:
        return np.array([feature_rows[i]["label"] for i in ids], dtype=int)

    y_train, y_cal, y_test = labels_of(train_ids), labels_of(cal_ids), labels_of(test_ids)

    # Image scores. Train gets out-of-fold values, calibration and test get the arm
    # refitted on all of train. Handing train its own in-sample image score is the
    # standard way a stacked model flatters itself.
    oof = _oof_by_ids(fit_predict, train_ids, y_train, feature_rows, seed)
    full_cal = fit_predict(train_ids, [int(v) for v in y_train], cal_ids)
    full_test = fit_predict(train_ids, [int(v) for v in y_train], test_ids)

    for ids, scores in ((train_ids, oof), (cal_ids, full_cal), (test_ids, full_test)):
        for oid, s in zip(ids, scores, strict=True):
            feature_rows[oid] = {**feature_rows[oid], "image_score": float(s)}

    arms: dict[str, dict[str, Any]] = {}
    scored: dict[str, np.ndarray] = {}
    for name, blocks in ARM_LADDER:
        arm = FusionArm(name=name, blocks=blocks, seed=seed).fit(
            rows_of(train_ids), [int(v) for v in y_train]
        )
        p_cal_raw = arm.predict(rows_of(cal_ids))
        cal = Calibrator(method="auto").fit(p_cal_raw, y_cal)
        p_test = cal.apply(arm.predict(rows_of(test_ids)))
        scored[name] = p_test

        slope, intercept = calibration_slope_intercept(p_test, y_test)
        arms[name] = {
            "blocks": list(blocks),
            "degraded": arm.degraded,
            "n_columns": len(arm.design.columns) if arm.design else 0,
            "calibrator": cal.method,
            "calibrator_chosen_because": cal.chosen_because,
            "temperature": cal.temperature if cal.method == "temperature" else None,
            "brier": brier(p_test, y_test),
            "log_loss": _log_loss(p_test, y_test),
            "auc": auc(p_test, y_test),
            "ece": expected_calibration_error(p_test, y_test),
            "calibration_slope": slope,
            "calibration_intercept": intercept,
            "mean_prediction": float(p_test.mean()),
        }

    # B3: is a multi-seed head ensemble worth anything here, and what does an
    # episode-bootstrap ensemble say instead? Measured on the gate-5 challenger.
    challenger_blocks = dict(ARM_LADDER)[GATE5_CHALLENGER]
    seed_probe = seed_sensitivity(
        challenger_blocks, rows_of(train_ids), [int(v) for v in y_train], rows_of(test_ids)
    )
    bag = episode_bootstrap_ensemble(
        challenger_blocks,
        rows_of(train_ids),
        [int(v) for v in y_train],
        [str(feature_rows[i]["episode"]) for i in train_ids],
        rows_of(test_ids),
        n_members=20,
        seed=seed,
    )
    ensemble = {
        "seed_sensitivity": seed_probe,
        "episode_bootstrap": {k: v for k, v in bag.items() if k not in ("mean", "std")},
    }
    if bag.get("mean") is not None:
        bag_cal = Calibrator(method="auto").fit(
            np.asarray(
                episode_bootstrap_ensemble(
                    challenger_blocks,
                    rows_of(train_ids),
                    [int(v) for v in y_train],
                    [str(feature_rows[i]["episode"]) for i in train_ids],
                    rows_of(cal_ids),
                    n_members=20,
                    seed=seed,
                )["mean"]
            ),
            y_cal,
        )
        p_bag = bag_cal.apply(np.asarray(bag["mean"]))
        ensemble["episode_bootstrap"]["brier"] = brier(p_bag, y_test)
        ensemble["episode_bootstrap"]["single_fit_brier"] = arms[GATE5_CHALLENGER]["brier"]
        ensemble["episode_bootstrap"]["helps"] = bool(
            ensemble["episode_bootstrap"]["brier"] < arms[GATE5_CHALLENGER]["brier"]
        )

    groups = np.array([str(feature_rows[i]["episode"]) for i in test_ids])
    # SPACE-S6: the second grouping. Every published gate-5 interval carried
    # mean_group_size 1.0, so the episode bootstrap was an observation-level bootstrap
    # wearing a note about shared receivers. Stations are where the clustering is on
    # these partitions, and gate 6 already measures it. Both are computed below and the
    # union governs.
    station_groups = np.array([str(station_of[i]) for i in test_ids])

    # Every arm that contains the reference's blocks is compared against it, so the
    # comparison family is fixed by the ladder rather than by which result looked good.
    # The count of comparisons is what the multiplicity correction below is over.
    challengers = [
        name for name, blocks in ARM_LADDER
        if name not in (GATE5_REFERENCE, "prior_only") and "image" in blocks
    ]
    comparisons = {}
    for challenger in challengers:
        comparisons[f"{challenger}_vs_{GATE5_REFERENCE}"] = clustered_paired_bootstrap(
            scored[challenger], scored[GATE5_REFERENCE], y_test, groups, station_groups,
            n_boot=n_boot, seed=seed,
        )
    comparisons[f"{GATE5_REFERENCE}_vs_prior_only"] = clustered_paired_bootstrap(
        scored[GATE5_REFERENCE], scored["prior_only"], y_test, groups, station_groups,
        n_boot=n_boot, seed=seed,
    )

    # Which published comparisons the correction covers, stated per comparison rather
    # than left to a reader counting keys. Eight intervals are reported against a family
    # of seven per split: image_only_vs_prior_only is a sanity check that the reference
    # arm beats the prior, not a claim about the physics, and no decision reads it.
    for key in comparisons:
        counted = key.endswith(f"_vs_{GATE5_REFERENCE}")
        comparisons[key]["in_multiplicity_family"] = counted
        if not counted:
            # Written only when it applies. A null reason beside
            # in_multiplicity_family=false would satisfy a schema that requires the key
            # while saying nothing, which is the shape this pair exists to prevent.
            comparisons[key]["family_exclusion_reason"] = (
                "A sanity check that the reference arm beats the prior-only arm. It is "
                "not a comparison the ablation rule reads and no block verdict depends "
                "on it, so it is published outside the corrected family."
            )

    # The multiplicity family is every arm-against-reference comparison reported for this
    # split, across both statistics: the Brier comparisons for each challenger, plus the
    # two risk-coverage comparisons in the selective block below. Counting only the Brier
    # ones would let the AURC claim, which is the one a reader leans on hardest, be the
    # one held to the weakest standard. The AURC statistic was also added after the Brier
    # ladder had been read, which is exactly the situation a correction is for.
    # SPACE-S7: over the whole family the decision rule reads, not one split's worth.
    # The rule retains a block if an arm containing it wins on ANY split above the
    # training floor, so a correction over 7 comparisons while the rule scans 7 on each
    # of several splits is a correction over the wrong family, and the receipt's own
    # justification already said the ladder runs 5 comparisons on each of 4 splits. The
    # eligible split count is computed before anything is fitted, so it cannot be
    # influenced by which result looked good.
    n_family = (len(challengers) + _N_AURC_COMPARISONS) * max(n_eligible_splits, 1)

    # Any arm whose interval clears zero at 95% is re-tested at the widened level,
    # because an arm quoted after the fact was selected as well as measured.
    #
    # In *either* direction, and that word is the whole point. The first version of this
    # loop corrected only comparisons where the challenger won, which quietly made a
    # measured harm impossible to correct: the ablation rule then read a missing
    # correction as "the harm does not survive", so its DROP branch could never fire and
    # the rule collapsed into "retain anything with one corrected win". A correction
    # applied only to good news is not a correction.
    multiplicity = {}
    for challenger in challengers:
        key = f"{challenger}_vs_{GATE5_REFERENCE}"
        if comparisons[key]["distinguishable"]:
            multiplicity[key] = clustered_multiplicity_adjusted(
                scored[challenger], scored[GATE5_REFERENCE], y_test, groups,
                station_groups, n_comparisons=n_family, n_boot=n_boot, seed=seed,
            )

    # B4: selective prediction on the gate-5 challenger. Threshold chosen on the
    # calibration partition, achieved risk measured on test.
    p_challenger = scored[GATE5_CHALLENGER]
    p_cal_challenger = _challenger_cal_probs(
        challenger_blocks, rows_of(train_ids), y_train, rows_of(cal_ids), y_cal, seed
    )
    selective: dict[str, Any] = {"curve": risk_coverage_curve(p_challenger, y_test, groups)}
    selective["aurc"] = area_under_risk_coverage(selective["curve"])
    selective["aurc_image_only"] = area_under_risk_coverage(
        risk_coverage_curve(scored[GATE5_REFERENCE], y_test, groups)
    )

    # The AURC difference gets its own interval. Without one it is a bare pair of
    # numbers, and a 36% reduction quoted with no interval is the same unsupported claim
    # the gate-5 wording exists to refuse. AURC is not a per-observation mean, so this
    # uses the resample-and-recompute bootstrap rather than the paired one.
    def _aurc(probs: np.ndarray, labels: np.ndarray, grp: np.ndarray) -> float:
        return area_under_risk_coverage(risk_coverage_curve(probs, labels, grp))

    # Both groupings, union governing, for the same reason the Brier comparisons use
    # both. SPACE-S6 fixed those and left this one resampling episodes, which on these
    # test partitions hold about one observation each, so the interval a reader leans on
    # hardest was the one still wearing a grouped name over an ungrouped resample.
    selective["aurc_vs_image_only"] = clustered_statistic_difference(
        _aurc, p_challenger, scored[GATE5_REFERENCE], y_test, groups, station_groups,
        # The 2000-draw cap is gone: measured at 1.07 ms per draw on this corpus, so
        # 50,000 draws costs under a minute per comparison, and the Bonferroni
        # endpoint over a cross-split family cannot be resolved by 2.4 draws.
        n_boot=n_boot, seed=seed, lower_is_better=True,
        n_comparisons=n_family,
    )
    # The arm the product ships, which is what the console ranks its queue by. It is
    # read from the library constant the ranker itself uses, not from the ablation
    # conclusion: the conclusion is computed after every split has been scored, and
    # after SPACE-S7 it recommends a narrower arm than the one being shipped. Measuring
    # the recommendation instead would publish the risk-coverage behaviour of an arm
    # nobody can select in the console.
    shipped = SHIPPED_ARM
    selective["aurc_shipped_arm_name"] = shipped
    if shipped == GATE5_REFERENCE:
        # Reachable only by changing what the product ships to image alone. Comparing
        # that against itself has a margin of exactly zero by construction and would
        # read as "no evidence of benefit" when it is really "no comparison was made".
        selective["aurc_shipped_arm"] = selective.get("aurc_image_only")
        selective["aurc_shipped_not_measured_reason"] = (
            f"The product ships {shipped!r}, which is the reference arm, so a "
            "shipped-against-reference comparison is a self-comparison. The gate-5 "
            "challenger comparison above is unaffected."
        )
    elif shipped == GATE5_CHALLENGER:
        selective["aurc_shipped_arm"] = selective["aurc"]
        selective["aurc_shipped_not_measured_reason"] = (
            f"The product ships {shipped!r}, which is the gate-5 challenger, so the "
            "comparison above already is the shipped arm's comparison."
        )
    elif shipped in scored:
        selective["aurc_shipped_arm"] = area_under_risk_coverage(
            risk_coverage_curve(scored[shipped], y_test, groups)
        )
        selective["aurc_shipped_vs_image_only"] = clustered_statistic_difference(
            _aurc, scored[shipped], scored[GATE5_REFERENCE], y_test, groups,
            station_groups,
            # The 2000-draw cap is gone: measured at 1.07 ms per draw on this corpus, so
            # 50,000 draws costs under a minute per comparison, and the Bonferroni
            # endpoint over a cross-split family cannot be resolved by 2.4 draws.
            n_boot=n_boot, seed=seed, lower_is_better=True,
            n_comparisons=n_family,
        )
    else:
        selective["aurc_shipped_not_measured_reason"] = (
            f"The product ships {shipped!r}, which this split did not score, so its "
            "risk-coverage behaviour is not measurable here."
        )
    selective["multiplicity_family_size"] = n_family
    selective["ceilings"] = []
    for target in (0.05, 0.10, 0.20):
        chosen = threshold_for_risk_ceiling(p_cal_challenger, y_cal, target_risk=target)
        entry = {"chosen_on_calibration": chosen}
        if chosen["feasible"]:
            entry["achieved_on_test"] = verify_ceiling(
                chosen["threshold"], p_challenger, y_test, groups,
                target_risk=target, n_boot=min(n_boot, 2000), seed=seed,
            )
        selective["ceilings"].append(entry)

    # B5: out-of-distribution scoring, fitted on train and scored on test.
    detector = OodDetector().fit(
        rows_of(train_ids),
        stations=[station_of[i] for i in train_ids],
        transmitters=[transmitter_of[i] for i in train_ids],
    )
    ood_rows = detector.score(
        rows_of(test_ids),
        stations=[station_of[i] for i in test_ids],
        transmitters=[transmitter_of[i] for i in test_ids],
    )
    ood = {
        "detector": detector.summary(),
        "n_test_flagged": sum(1 for r in ood_rows if r["is_ood"]),
        "by_axis_counts": {
            axis: sum(1 for r in ood_rows if r[axis])
            for axis in ("unseen_station", "unseen_transmitter", "unseen_client_family",
                         "unseen_band", "feature_novelty")
        },
        "risk_by_novelty": risk_by_novelty(ood_rows, p_challenger, y_test),
    }

    return {
        "split": split_name,
        "degraded": None,
        "counts": counts,
        "test_positive_rate": float(y_test.mean()),
        "train_positive_rate": float(y_train.mean()),
        "arms": arms,
        "comparisons": comparisons,
        "multiplicity_adjusted": multiplicity,
        "ensemble": ensemble,
        "selective": selective,
        "ood": ood,
    }


def _challenger_cal_probs(
    blocks: tuple[str, ...],
    train_rows: list[dict[str, Any]],
    y_train: np.ndarray,
    cal_rows: list[dict[str, Any]],
    y_cal: np.ndarray,
    seed: int,
) -> np.ndarray:
    """Calibrated challenger probabilities on the calibration partition.

    The abstention threshold has to be chosen on scores that look like the ones it will
    be applied to, so the calibration rows are scored through the same calibrator that
    the test rows go through. Fitting the calibrator on these rows and then choosing a
    threshold on them is in-sample by construction; that is why the achieved risk is
    always re-measured on test rather than reported from here.
    """
    arm = FusionArm(name="cal_probe", blocks=blocks, seed=seed).fit(
        train_rows, [int(v) for v in y_train]
    )
    raw = arm.predict(cal_rows)
    return Calibrator(method="auto").fit(raw, y_cal).apply(raw)


def _oof_by_ids(
    fit_predict: Any,
    ids: list[int],
    y: np.ndarray,
    feature_rows: dict[int, dict[str, Any]],
    seed: int,
    n_splits: int = 5,
) -> np.ndarray:
    """Out-of-fold image scores, folds grouped by pass episode."""
    from sklearn.model_selection import GroupKFold  # noqa: PLC0415

    groups = np.array([str(feature_rows[i]["episode"]) for i in ids])
    n_groups = len(np.unique(groups))
    folds = min(n_splits, n_groups)
    out = np.full(len(ids), float(y.mean()), dtype=float)
    if folds < 2:
        return out
    for tr, te in GroupKFold(n_splits=folds).split(np.zeros(len(ids)), y, groups=groups):
        if len(set(y[tr].tolist())) < 2:
            continue
        out[te] = fit_predict(
            [ids[i] for i in tr], [int(y[i]) for i in tr], [ids[i] for i in te]
        )
    return out


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--splits", default="chronological,cold_station,cold_transmitter,cold_combined")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-boot", type=int, default=10_000)
    ap.add_argument("--out", type=Path, default=_REPO / "artifacts" / "FUSION_RECEIPT.json")
    args = ap.parse_args(argv)

    admissibility = admissible_source_fields()
    print(f"feature admissibility: {admissibility['n_fields']} source fields, all observation-time")

    raw = _load_raw_pages(_default_pages_dir())
    corridor_cache = load_corridor_cache()
    verdicts = _load_a3_verdicts(_A3_SUMMARY_PATH)
    hog = load_hog()
    print(f"corridor cache: {len(corridor_cache)} rows | hog cache: {len(hog[1])} rows")

    feature_rows = build_feature_rows(raw, corridor_cache, verdicts)
    print(f"decisive observations with features: {len(feature_rows)}")

    # Entity identities, used only for novelty scoring and grouping. They are never
    # features: FIELD_CLASSIFICATION marks both as identifiers, and
    # admissible_source_fields refuses any block that reads them.
    station_of = {oid: raw[oid].get("ground_station") for oid in feature_rows}
    transmitter_of = {oid: str(raw[oid].get("transmitter_uuid")) for oid in feature_rows}

    manifest = json.loads(_SPLIT_MANIFEST.read_text(encoding="utf-8"))
    requested = [name.strip() for name in args.splits.split(",")]
    eligible_names = eligible_split_names(manifest, feature_rows, requested)
    n_eligible = len(eligible_names)
    print(
        f"\nmultiplicity family: {n_eligible} eligible split(s) "
        f"{eligible_names} x 7 comparisons each",
        flush=True,
    )
    results = []
    for split_name in args.splits.split(","):
        split_name = split_name.strip()
        if split_name not in manifest["splits"]:
            continue
        print(f"\n=== {split_name} ===", flush=True)
        res = run_split(
            split_name,
            manifest["splits"][split_name],
            feature_rows,
            hog,
            args.seed,
            args.n_boot,
            station_of,
            transmitter_of,
            n_eligible,
        )
        results.append(res)
        if res["degraded"]:
            print(f"  degraded: {res['degraded']}  counts={res['counts']}")
            continue
        print(f"  counts: {res['counts']}")
        for name, a in res["arms"].items():
            print(
                f"  {name:22s} brier={a['brier']:.4f} logloss={a['log_loss']:.4f} "
                f"auc={a['auc']:.3f} ece={a['ece']:.4f} slope={a['calibration_slope']:.2f} "
                f"cal={a['calibrator']}"
            )
        for key, c in res["comparisons"].items():
            mark = {
                "challenger_better": "CHALLENGER BETTER",
                "reference_better": "REFERENCE BETTER",
                "indistinguishable": "indistinguishable",
            }[c["direction"]]
            adj = res.get("multiplicity_adjusted", {}).get(key)
            suffix = ""
            if adj:
                suffix = (
                    f"  | corrected ci=[{adj['ci_adjusted'][0]:+.5f},"
                    f"{adj['ci_adjusted'][1]:+.5f}] "
                    f"{'survives' if adj['survives_correction'] else 'DOES NOT SURVIVE'}"
                )
            print(
                f"  {key:44s} margin={c['margin']:+.5f} "
                f"ci=[{c['ci95'][0]:+.5f},{c['ci95'][1]:+.5f}] {mark}{suffix}"
            )
        sel = res.get("selective", {})
        for label, aurc_key, cmp_key in (
            (GATE5_CHALLENGER, "aurc", "aurc_vs_image_only"),
            (SHIPPED_ARM, "aurc_shipped_arm", "aurc_shipped_vs_image_only"),
        ):
            if aurc_key not in sel or sel.get(aurc_key) is None:
                continue
            if sel.get(cmp_key) is None:
                # Reported as a named absence rather than as a zero margin.
                reason = sel.get("aurc_shipped_not_measured_reason")
                print(f"  AURC {label:22s} not compared: {reason}")
                continue
            cmp_ = sel[cmp_key]
            ci = cmp_.get("ci95")
            ci_txt = f"ci=[{ci[0]:+.5f},{ci[1]:+.5f}]" if ci else "ci=unmeasurable"
            adj_txt = ""
            if cmp_.get("ci_adjusted") and cmp_.get("direction") != "indistinguishable":
                a = cmp_["ci_adjusted"]
                adj_txt = (
                    f"  | corrected ci=[{a[0]:+.5f},{a[1]:+.5f}] "
                    f"{'survives' if cmp_['survives_correction'] else 'DOES NOT SURVIVE'}"
                )
            print(
                f"  AURC {label:22s} {sel[aurc_key]:.4f} vs image_only "
                f"{sel['aurc_image_only']:.4f} margin={cmp_.get('margin', float('nan')):+.5f} "
                f"{ci_txt} {cmp_.get('direction', '?')}{adj_txt}"
            )

    # B6: the size-matched control. cold_combined trains on far fewer observations than
    # chronological, so a drop there confounds "the entities are unseen" with "there was
    # less to learn from". This refits the chronological split with its training
    # partition subsampled, by episode, to the size of cold_combined's, and reports the
    # result next to it. Any remaining gap is attributable to the entities.
    size_matched = None
    by_name = {r["split"]: r for r in results if not r["degraded"]}
    if "chronological" in by_name and "cold_combined" in by_name:
        target_n = by_name["cold_combined"]["counts"]["train"]
        chron = manifest["splits"]["chronological"]
        trimmed = _subsample_train_by_episode(
            [i for i in chron["train"] if i in feature_rows],
            feature_rows, target_n, args.seed,
        )
        print(
            f"\n=== chronological_size_matched (train {len(trimmed)} to match "
            f"cold_combined's {target_n}) ===",
            flush=True,
        )
        res = run_split(
            "chronological_size_matched",
            {**chron, "train": trimmed},
            feature_rows, hog, args.seed, args.n_boot, station_of, transmitter_of,
            # The size-matched control is not a split the ablation rule reads, so it is
            # corrected at the same family size as the split it controls rather than
            # adding to the family.
            n_eligible,
        )
        if not res["degraded"]:
            for name, a in res["arms"].items():
                print(f"  {name:22s} brier={a['brier']:.4f} auc={a['auc']:.3f}")
        results.append(res)
        size_matched = {
            "target_train_n": target_n,
            "achieved_train_n": len(trimmed),
            "full_chronological_train_n": by_name["chronological"]["counts"]["train"],
            "purpose": (
                "Separates the cost of unseen entities from the cost of a smaller "
                "training set. Compare cold_combined against this row, not against the "
                "full chronological split."
            ),
        }
        if not res["degraded"]:
            for arm in (GATE5_REFERENCE, GATE5_CHALLENGER):
                size_matched[arm] = {
                    "full_chronological_brier": by_name["chronological"]["arms"][arm]["brier"],
                    "size_matched_brier": res["arms"][arm]["brier"],
                    "cold_combined_brier": by_name["cold_combined"]["arms"][arm]["brier"],
                    "cost_of_smaller_train": (
                        res["arms"][arm]["brier"]
                        - by_name["chronological"]["arms"][arm]["brier"]
                    ),
                    "cost_of_unseen_entities": (
                        by_name["cold_combined"]["arms"][arm]["brier"]
                        - res["arms"][arm]["brier"]
                    ),
                }

    gate5 = _gate5_verdict(results)
    ablation = _ablation_conclusion(results)
    payload = {
        "schema": "FUSION_RECEIPT",
        "schema_version": "0.1.0",
        "contract": "contracts/fusion_receipt.schema.json",
        "unit": "B2-B6",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "seed": args.seed,
        "snapshot_id": json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))["snapshot_id"],
        "split_manifest_sha256": hashlib.sha256(
            _SPLIT_MANIFEST.read_bytes()
        ).hexdigest(),
        "feature_admissibility": admissibility,
        "caches": {
            "corridor_rows": len(corridor_cache),
            "hog_rows": len(hog[1]),
            "hog_dim": int(hog[0].shape[1]) if hog[0].size else 0,
        },
        "arm_ladder": [{"name": n, "blocks": list(b)} for n, b in ARM_LADDER],
        "gate5": gate5,
        "ablation_conclusion": ablation,
        "size_matched_control": size_matched,
        "splits": results,
    }
    _validate_against_contract(payload)
    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8", newline="\n")
    print(f"\nwrote {args.out}")
    print(f"\nGATE 5: {gate5['verdict']}")
    print(gate5["statement"])
    print("\nABLATION CONCLUSION")
    for rule in ("nominal", "multiplicity_corrected"):
        mark = " <- decides" if rule == ablation["deciding_rule"] else ""
        print(f"  [{rule}]{mark}")
        for block, v in ablation[rule]["blocks"].items():
            print(
                f"    {block:9s} {v['decision']:16s} "
                f"better={v['better_on'] or '-'} worse={v['worse_on'] or '-'}"
            )
        print(
            f"    -> recommends {ablation[rule]['shipped_blocks']} "
            f"arm={ablation[rule]['shipped_arm']} "
            f"measured={ablation[rule]['shipped_arm_was_measured']}"
        )
    print(f"  rules disagree on: {ablation['rules_disagree_on'] or 'nothing'}")
    stated = ablation["shipped_arm_vs_recommendation"]
    print(
        f"  ships {stated['ships']}; corrected rule recommends "
        f"{stated['corrected_recommends']}: "
        f"{'agree' if stated['agree'] else 'DISAGREE'}"
    )
    if not stated["agree"]:
        print(f"    {stated['note']}")
    if ablation["shipped_arm_scores"]:
        sc = ablation["shipped_arm_scores"]
        print(
            f"  shipped arm on {sc['split']}: brier={sc['brier']:.4f} "
            f"auc={sc['auc']:.3f} ece={sc['ece']:.4f} "
            f"slope={sc['calibration_slope']:.2f}"
        )
    print(
        f"  below the {ablation['min_train_for_verdict']}-row training floor, so not used "
        f"for the decision: {ablation['splits_below_training_floor']}"
    )
    return 0


def _subsample_train_by_episode(
    ids: list[int],
    feature_rows: dict[int, dict[str, Any]],
    target_n: int,
    seed: int,
) -> list[int]:
    """Trim a training partition to about ``target_n`` rows, dropping whole episodes.

    Dropping whole episodes rather than individual observations keeps the remaining
    training set the same *kind* of sample as the original. Removing single captures from
    a pass would leave partial episodes, which is a different data shape from the one the
    comparison is trying to hold constant.
    """
    if target_n >= len(ids):
        return list(ids)
    by_episode: dict[str, list[int]] = {}
    for oid in ids:
        by_episode.setdefault(str(feature_rows[oid]["episode"]), []).append(oid)
    order = sorted(by_episode)
    np.random.default_rng(seed).shuffle(order)
    kept: list[int] = []
    for key in order:
        if len(kept) >= target_n:
            break
        kept.extend(by_episode[key])
    return sorted(kept)



#: A split needs at least this many decisive training rows before its verdict counts
#: toward keeping or dropping a block.
#:
#: 300 is set from a measurement, not from taste. The size-matched control shows the
#: corridor block loses 0.036 Brier on the chronological split purely by dropping the
#: training partition from 530 rows to 188, which is larger than the 0.020 it gains at
#: full size. At 188 rows the block cannot help whatever the entities are, so a verdict
#: from a split that small measures the sample size rather than the block. Splits below
#: the floor still appear in the receipt and still inform the training-size caveat; they
#: just do not decide whether a block ships.
MIN_TRAIN_FOR_BLOCK_VERDICT = 300


def _validate_against_contract(payload: dict[str, Any]) -> None:
    """Refuse to write a receipt that violates its own contract.

    Validating after the fact only works if somebody runs the validation. The contract
    encodes four things the receipt must not be able to say (a margin with no interval, a
    two-valued direction, a bare gate verdict, an infeasible ceiling with no reason), and
    those constraints are worth nothing if a violating receipt still lands on disk and
    gets read.
    """
    import jsonschema  # noqa: PLC0415

    schema_path = _REPO / "contracts" / "fusion_receipt.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.validators.validator_for(schema)(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"  {list(e.absolute_path)}: {e.message}" for e in errors[:10]]
        msg = (
            f"The receipt violates {schema_path.name} in {len(errors)} place(s) and was "
            "not written:\n" + "\n".join(lines)
        )
        raise SystemExit(msg)


def _shipped_arm_vs_recommendation(
    nominal: dict[str, Any],
    corrected: dict[str, Any],
    eligible: list[dict[str, Any]],
) -> dict[str, Any]:
    """State whether the arm being shipped is the arm the ablation recommends.

    An earlier version of this aborted the run when the two differed, on the reasoning
    that the receipt would otherwise report the risk-coverage behaviour of an arm nobody
    ships. That reasoning had the direction wrong. What ships is decided by
    ``SHIPPED_ARM``, which the ranker itself reads, so the risk-coverage figures describe
    the shipped arm by construction; what can differ is whether the ablation still
    supports every block in it.

    After SPACE-S7 it does not. Correcting over the 21 comparisons the ablation rule
    reads rather than the 7 on one split, on the station-clustered union interval, the
    corridor block's single win no longer clears zero, so the corrected rule recommends
    image alone while the queue is still ranked by image and corridor together. Aborting
    on that would leave the pipeline unable to publish its own most useful result, so the
    disagreement is measured, named, and carried in the receipt.
    """
    unsupported = sorted(
        b for b in SHIPPED_ARM_BLOCKS
        if corrected["blocks"].get(b, {}).get("decision") != "RETAIN"
        and b not in ("image",)
    )

    # The ablation rule reads the Brier comparisons only. The shipped arm's risk-coverage
    # comparison is corrected over the same family and published beside them, and on this
    # corpus the two metrics disagree about the corridor block. Carrying that here is the
    # difference between a shipped arm defended by a measurement and one defended by
    # having been chosen first, so it is looked up rather than argued. Read from the split
    # the gate is worded against, because that is where its verdict is taken.
    selective_evidence: dict[str, Any] | None = None
    for r in eligible:
        if r["split"] != "chronological":
            continue
        cmp_ = (r.get("selective") or {}).get("aurc_shipped_vs_image_only")
        if cmp_ is None:
            continue
        selective_evidence = {
            "split": r["split"],
            "metric": "risk-coverage area against the reference arm",
            "margin": cmp_.get("margin"),
            "ci_adjusted": cmp_.get("ci_adjusted"),
            "direction": cmp_.get("direction"),
            "survives_correction": cmp_.get("survives_correction"),
            "n_comparisons": cmp_.get("n_comparisons"),
        }
    agree = corrected["shipped_arm"] == SHIPPED_ARM
    if agree:
        note = (
            f"The queue is ranked by {SHIPPED_ARM}, and the corrected ablation rule "
            "recommends the same combination."
        )
    else:
        recommends = corrected["shipped_arm"] or "a combination no arm on the ladder fitted"
        note = (
            f"The queue is ranked by {SHIPPED_ARM} "
            f"({' + '.join(SHIPPED_ARM_BLOCKS)}), while the corrected ablation rule "
            f"recommends {recommends} "
            f"({' + '.join(corrected['shipped_blocks'])}). "
        )
        if unsupported:
            note += (
                "The blocks the shipped ranker uses without corrected support are "
                f"{', '.join(unsupported)}: retained by the nominal rule, and the Brier "
                "interval does not clear zero once the multiplicity correction runs over "
                "the family the rule reads. The ranker was not rebuilt to match, for two "
                "measured reasons. The same comparison does not establish the narrower "
                "arm as better either, so swapping on it would be a change made for the "
                "appearance of consistency rather than for a result. "
            )
            if (
                selective_evidence
                and selective_evidence["survives_correction"]
                and selective_evidence["direction"] == "challenger_better"
            ):
                ci = selective_evidence["ci_adjusted"]
                note += (
                    "And the ablation rule reads Brier comparisons only, while the same "
                    f"arm's {selective_evidence['metric']} on "
                    f"{selective_evidence['split']} is "
                    f"{selective_evidence['margin']:+.5f} with a corrected interval of "
                    f"{ci[0]:+.5f} to {ci[1]:+.5f} over the same "
                    f"{selective_evidence['n_comparisons']} comparisons, which does clear "
                    "zero. Selective review is what the queue does, so that is the metric "
                    "closest to the shipped use, and it is reported rather than promoted "
                    "into the rule after the fact."
                )
            elif selective_evidence:
                note += (
                    "The same arm's "
                    f"{selective_evidence['metric']} on {selective_evidence['split']} "
                    "does not clear zero after correction either, so nothing measured "
                    "here supports the block."
                )
        else:
            note += (
                "The difference is in which ladder arm the block set maps to rather "
                "than in the blocks themselves."
            )
    return {
        "ships": SHIPPED_ARM,
        "ship_blocks": list(SHIPPED_ARM_BLOCKS),
        "nominal_recommends": nominal["shipped_arm"],
        "nominal_recommends_blocks": nominal["shipped_blocks"],
        "corrected_recommends": corrected["shipped_arm"],
        "corrected_recommends_blocks": corrected["shipped_blocks"],
        "agree": agree,
        "shipped_blocks_without_corrected_support": unsupported,
        "selective_evidence_for_the_shipped_arm": selective_evidence,
        "note": note,
    }


def _ablation_conclusion(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide which blocks ship, from the measured comparisons rather than from taste.

    The plan requires it: "Every layer must survive an ablation. Remove layers that do
    not improve calibration or queue utility." So the decision is generated here, and the
    rule is printed next to its own output.

    Two rules are evaluated, not one, because they disagree and the disagreement is the
    interesting part.

    ``nominal``
        Retain a block if some arm containing it beat image-only with a 95% interval
        clearing zero, on a split at or above the training-size floor, and no such split
        showed an arm containing it reliably worse.
    ``multiplicity_corrected``
        The same, but the interval must clear zero after Bonferroni correction over the
        family of comparisons run on that split.

    The corrected rule is the decision. Its cost is stated plainly: the correction was
    promoted from a report to a gate after the nominal rule retained the metadata block
    on a single split whose interval did not survive correction. That is a rule tightened
    after seeing a number, which is worth saying out loud. It stands on two grounds that
    do not depend on which way it fell. Gate 5 already reports corrected intervals, so
    holding the ablation to a weaker standard would have been the inconsistency. And this
    ladder runs 5 comparisons on each of 4 splits, so at 20 comparisons one interval
    clearing zero by chance is the expected outcome rather than evidence.

    The corrected rule also lands on a combination the ladder actually fitted, so the
    shipped arm carries a measured score with a bootstrap interval around it. The nominal
    rule selects image + corridor + metadata, which no arm in the ladder fits, so its
    score would have to come from a fresh fit that nothing in this receipt covers.

    One caveat neither rule removes, and it belongs in the README rather than being
    smoothed over: the retain decision reads test-set comparisons, so the shipped arm's
    reported Brier is optimistic by an amount this corpus cannot measure.
    """
    eligible = [
        r for r in results
        if not r["degraded"]
        and r["split"] != "chronological_size_matched"
        and r["counts"]["train"] >= MIN_TRAIN_FOR_BLOCK_VERDICT
    ]
    below_floor = [
        r["split"] for r in results
        if not r["degraded"]
        and r["split"] != "chronological_size_matched"
        and r["counts"]["train"] < MIN_TRAIN_FOR_BLOCK_VERDICT
    ]
    blocks_by_arm = dict(ARM_LADDER)

    def _decide(corrected: bool) -> dict[str, Any]:
        verdicts: dict[str, Any] = {}
        for block in ("physics", "corridor", "metadata"):
            better_on: list[str] = []
            worse_on: list[str] = []
            for r in eligible:
                adj = r.get("multiplicity_adjusted", {})
                for key, comp in r["comparisons"].items():
                    arm = key.replace(f"_vs_{GATE5_REFERENCE}", "")
                    if block not in blocks_by_arm.get(arm, ()):
                        continue
                    # Read the direction off whichever interval the rule is using, rather
                    # than filtering on the corrected one and then reading the nominal
                    # verdict. The two agree today, because the corrected interval is a
                    # superset of the nominal one, but a rule that mixes the two would
                    # start disagreeing the moment either side changes.
                    if corrected:
                        entry = adj.get(key)
                        if entry is None:
                            continue
                        direction = entry["direction_adjusted"]
                    else:
                        direction = comp["direction"]
                    if direction == "challenger_better":
                        better_on.append(f"{r['split']}/{arm}")
                    elif direction == "reference_better":
                        worse_on.append(f"{r['split']}/{arm}")
            if better_on and not worse_on:
                decision = "RETAIN"
            elif worse_on and not better_on:
                decision = "DROP"
            else:
                decision = "NOT_ESTABLISHED"
            verdicts[block] = {
                "decision": decision,
                "better_on": better_on,
                "worse_on": worse_on,
            }
        retained = [b for b, v in verdicts.items() if v["decision"] == "RETAIN"]
        shipped = ("image", *retained)
        arm = next((n for n, blocks in ARM_LADDER if set(blocks) == set(shipped)), None)
        return {
            "blocks": verdicts,
            "shipped_blocks": list(shipped),
            "shipped_arm": arm,
            "shipped_arm_was_measured": arm is not None,
        }

    nominal = _decide(corrected=False)
    corrected = _decide(corrected=True)

    # SPACE-S6 and SPACE-S7: every way this conclusion could be thinner than it looks,
    # collected in one place instead of left for a reader to reconstruct from four nested
    # blocks. A RETAIN that rests on a single comparison, on an interval endpoint the
    # bootstrap cannot resolve, or on a comparison that fails the design-effect check, is
    # still a RETAIN; it is a RETAIN a reader is entitled to see qualified.
    fragility: list[dict[str, Any]] = []
    for block, verdict in corrected["blocks"].items():
        if verdict["decision"] != "RETAIN":
            continue
        for label in verdict["better_on"]:
            split_name, arm = label.split("/", 1)
            res = next((r for r in eligible if r["split"] == split_name), None)
            if res is None:
                continue
            entry = res.get("multiplicity_adjusted", {}).get(
                f"{arm}_vs_{GATE5_REFERENCE}"
            )
            if entry is None:
                continue
            sens = entry.get("design_effect_sensitivity") or {}
            resolution = entry.get("percentile_resolution") or {}
            concerns = []
            if len(verdict["better_on"]) == 1:
                concerns.append("the block rests on this one comparison")
            if sens.get("applicable") and not sens.get("clears_zero"):
                concerns.append(
                    "a normal-theory widening by the measured design effect of "
                    f"{sens['design_effect']:.4f} does not clear zero "
                    f"({sens['widened_ci'][0]:+.6f})"
                )
            if resolution and not resolution.get("endpoint_resolved"):
                concerns.append(
                    f"the corrected endpoint sits at draw "
                    f"{resolution['draws_per_tail']:.1f} of the bootstrap, so it is not "
                    f"resolved; {resolution['n_boot_for_resolution']} draws would resolve it"
                )
            if concerns:
                fragility.append({
                    "block": block,
                    "comparison": label,
                    # Both correction paths always emit this. Read it defensively
                    # anyway: a fragility row exists to qualify a verdict, and is a
                    # poor place to lose the whole conclusion to a KeyError.
                    "corrected_ci": entry.get("ci_adjusted"),
                    "governing_interval": entry.get("governing_interval"),
                    "concerns": concerns,
                })

    # Scores for the arm that ships, not for the arm the rule recommends. The console
    # displays these under the shipped arm's name beside a queue ranked by it, so reading
    # them off the recommendation would put one arm's name on another arm's numbers.
    shipped_scores = None
    for r in eligible:
        if r["split"] == "chronological":
            row = r["arms"].get(SHIPPED_ARM)
            if row is not None:
                shipped_scores = {
                    "split": r["split"],
                    "brier": row["brier"],
                    "auc": row["auc"],
                    "ece": row["ece"],
                    "calibration_slope": row["calibration_slope"],
                }

    return {
        "rules": {
            "nominal": (
                "Retain a block if an arm containing it beat image-only with a 95% "
                "interval clearing zero on a split with at least "
                f"{MIN_TRAIN_FOR_BLOCK_VERDICT} decisive training rows, and no such "
                "split showed it reliably worse."
            ),
            "multiplicity_corrected": (
                "The same, but the interval must clear zero after Bonferroni correction "
                "over the comparison family run on that split."
            ),
        },
        "deciding_rule": "multiplicity_corrected",
        "why_the_corrected_rule_decides": (
            "The correction was promoted from a report to a gate after the nominal rule "
            "retained the metadata block on one split whose interval did not survive "
            "correction, so this is a rule tightened after seeing a number and that is "
            "worth stating. It stands on two grounds independent of which way it fell: "
            "gate 5 already reports corrected intervals, so holding the ablation to a "
            "weaker standard would be the inconsistency; and this ladder runs 5 "
            "comparisons on each of 4 splits, where one nominal win by chance is the "
            "expected outcome rather than evidence. The corrected rule also selects a "
            "combination the ladder actually fitted, so its recommendation carries "
            "a measured score and an interval, which the nominal rule's selection does not."
        ),
        "shipped_arm_vs_recommendation": _shipped_arm_vs_recommendation(
            nominal, corrected, eligible
        ),
        "fragility": fragility,
        "fragility_note": (
            "Qualifications on the corrected conclusion above, not corrections to it. "
            "The verdict is read from the cluster bootstrap, which resamples stations "
            "directly; the design-effect entry here is a cruder normal-theory check on "
            "the same clustering and is reported where the two disagree."
        ),
        "min_train_for_verdict": MIN_TRAIN_FOR_BLOCK_VERDICT,
        "min_train_justification": (
            "Set from the size-matched control, not from taste. The corridor block loses "
            "roughly 0.036 Brier on the chronological split purely by cutting the "
            "training partition from 530 rows to 188, which exceeds the 0.020 it gains "
            "at full size. Below the floor a verdict measures the sample size instead of "
            "the block, so those splits still appear in the receipt and still inform the "
            "training-size caveat; they do not decide whether a block ships."
        ),
        "splits_used": [r["split"] for r in eligible],
        "splits_below_training_floor": below_floor,
        "nominal": nominal,
        "multiplicity_corrected": corrected,
        "rules_disagree_on": sorted(
            b for b in nominal["blocks"]
            if nominal["blocks"][b]["decision"] != corrected["blocks"][b]["decision"]
        ),
        # "shipped" at this level means what the product ships. The per-rule blocks
        # above are each rule's recommendation, which is a different thing and after
        # SPACE-S7 a different answer.
        "shipped_blocks": list(SHIPPED_ARM_BLOCKS),
        "shipped_arm": SHIPPED_ARM,
        "shipped_arm_scores": shipped_scores,
        "recommended_arm": corrected["shipped_arm"],
        "recommended_blocks": corrected["shipped_blocks"],
        "caveat": (
            "The retain decision reads test-set comparisons, so the shipped arm's Brier "
            "is optimistic by an amount this corpus cannot measure. A second snapshot is "
            "the only thing that settles it, and until then the number travels with this "
            "sentence."
        ),
    }


def _gate5_verdict(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide gate 5 on the chronological split, and report every split.

    The gate is worded against a chronological split, so that is where the verdict is
    taken. The other splits are reported next to it because a gain that appears only
    where entities are shared is a different claim from one that survives a cold split.
    """
    key = f"{GATE5_CHALLENGER}_vs_{GATE5_REFERENCE}"
    per_split = {}
    for r in results:
        if r["degraded"]:
            per_split[r["split"]] = {"measurable": False, "reason": r["degraded"]}
            continue
        c = r["comparisons"].get(key)
        per_split[r["split"]] = {
            "measurable": True,
            "margin": c["margin"],
            "ci95": c["ci95"],
            "direction": c["direction"],
            "distinguishable": c["distinguishable"],
            "challenger_better": c["challenger_better"],
            "n_observations": c["n_observations"],
            # SPACE-S6: both groupings, and which interval the verdict above came from.
            # "n_groups" alone, equal to n_observations on every split, was the number
            # that made an observation-level bootstrap look like a clustered one.
            "n_groups": c["n_groups"],
            "n_groups_episode": c["n_groups_episode"],
            "n_groups_station": c["n_groups_station"],
            "mean_group_size_episode": c["mean_group_size_episode"],
            "mean_group_size_station": c["mean_group_size_station"],
            "ci95_episode": c["ci95_episode"],
            "ci95_station": c["ci95_station"],
            "governing_interval": c["governing_interval"],
            "clustering": c["clustering"],
            "challenger_brier": r["arms"][GATE5_CHALLENGER]["brier"],
            "reference_brier": r["arms"][GATE5_REFERENCE]["brier"],
        }

    chron = per_split.get("chronological", {"measurable": False, "reason": "not run"})
    if not chron.get("measurable"):
        verdict = "UNMEASURABLE"
        statement = (
            "Gate 5 could not be measured on the chronological split: "
            f"{chron.get('reason')}. No verdict is claimed."
        )
    elif chron["challenger_better"]:
        verdict = "PASSED"
        statement = (
            f"The physics-conditioned arm lowers Brier by {chron['margin']:.5f} "
            f"(95% CI {chron['ci95'][0]:.5f} to {chron['ci95'][1]:.5f}) against the "
            f"calibrated image-only baseline on {chron['n_observations']} test "
            f"observations across {chron['n_groups']} pass episodes. The interval "
            "clears zero."
        )
    elif chron["margin"] > 0:
        verdict = "NOT_ESTABLISHED"
        statement = (
            f"The physics-conditioned arm has the lower Brier score by "
            f"{chron['margin']:.5f}, but the 95% interval "
            f"({chron['ci95'][0]:.5f} to {chron['ci95'][1]:.5f}) spans zero on "
            f"{chron['n_observations']} test observations across {chron['n_groups']} "
            "episodes. A point estimate in the right direction with an interval "
            "containing zero is not a gain, and reporting it as one would be the "
            "same error unit A7 made. The gate is not met."
        )
    elif chron["direction"] == "reference_better":
        verdict = "FAILED"
        statement = (
            "The physics-conditioned arm has a reliably HIGHER Brier score than the "
            f"calibrated image-only baseline, by {-chron['margin']:.5f} "
            f"(95% CI {chron['ci95'][0]:.5f} to {chron['ci95'][1]:.5f}, entirely below "
            "zero). Adding the physics and corridor blocks makes the model measurably "
            "worse on this corpus. That is a finding, not an absence of one: the gate "
            "is not met and the blocks do not belong in the shipped model as built."
        )
    else:
        verdict = "FAILED"
        statement = (
            "The physics-conditioned arm has a higher Brier score than the calibrated "
            f"image-only baseline, by {-chron['margin']:.5f} "
            f"(95% CI {chron['ci95'][0]:.5f} to {chron['ci95'][1]:.5f}). The gate is "
            "not met."
        )

    return {
        "gate": 5,
        "wording": (
            "Require the physics-conditioned model to lower Brier score against a "
            "calibrated image-only baseline."
        ),
        "challenger": GATE5_CHALLENGER,
        "reference": GATE5_REFERENCE,
        "decided_on": "chronological",
        "verdict": verdict,
        "statement": statement,
        "per_split": per_split,
    }


if __name__ == "__main__":
    sys.exit(main())
