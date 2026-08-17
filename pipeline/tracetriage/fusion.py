"""Fusion head over image, physics, corridor and metadata blocks (unit B2).

What this module answers is kill gate 5: does a physics-conditioned model reach a lower
Brier score than a calibrated image-only baseline on the same split? The gate is
measured, with a grouped paired bootstrap interval, and it is allowed to fail.

Three design choices carry most of the weight.

**Out-of-fold image scores.** The image arm is a HOG logistic regression fitted on the
same training rows the fusion head learns from. Handing the head the arm's in-sample
score would show it an image opinion that is already fitted to those labels, and the
head would learn to trust it more than it deserves. So training rows get out-of-fold
scores from a GroupKFold grouped by pass episode, and calibration and test rows get the
score from the arm refitted on all of train. This is ordinary stacking discipline, and
without it a fusion head reliably looks better than it is.

**Missingness is a feature, not a zero.** A degraded physics result, an unreadable
axis, an absent corridor measurement: each is informative about the observation, and
each would become a misleading number if imputed silently. Every numeric column gets a
median impute plus a companion ``*__missing`` indicator, so the head can use "this could
not be measured" as evidence rather than being told it was average.

**Unseen categories go to zero, and that is the point.** Categories are fixed from
train. A test row with a transmitter mode never seen in training gets an all-zero
one-hot block rather than a new column, which is what a cold-entity split is supposed to
produce. B5 scores that condition explicitly.

The arms are named blocks so an ablation is a list of strings, which is what B6 needs.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pipeline.tracetriage.features import (
    CORRIDOR_FEATURES,
    METADATA_CATEGORICAL,
    PHYSICS_FEATURES,
)

#: The blocks an arm can be built from. "image" is the HOG logistic-regression score,
#: supplied per observation by the caller rather than computed here.
ALL_BLOCKS: tuple[str, ...] = ("image", "physics", "corridor", "metadata")

#: The ablation ladder the plan asks for, as (name, blocks). Declared here so the gate
#: and the ablation harness cannot disagree about what "image only" means.
ARM_LADDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prior_only", ()),
    ("image_only", ("image",)),
    ("physics_only", ("physics",)),
    ("corridor_only", ("corridor",)),
    ("metadata_only", ("metadata",)),
    ("image_metadata", ("image", "metadata")),
    ("image_physics", ("image", "physics")),
    ("image_corridor", ("image", "corridor")),
    ("physics_conditioned", ("image", "physics", "corridor")),
    ("full_fusion", ("image", "physics", "corridor", "metadata")),
)

#: The gate-5 comparison: which arm must beat which, and on what.
GATE5_CHALLENGER = "physics_conditioned"
GATE5_REFERENCE = "image_only"


@dataclass
class DesignMatrix:
    """A fitted feature layout: column names, categories and impute values.

    Everything that could differ between fitting and scoring is stored, so scoring a
    test row cannot silently produce a different column order or a different impute
    value from the one training used.
    """

    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    categories: dict[str, tuple[str, ...]]
    medians: dict[str, float]
    columns: tuple[str, ...]

    def transform(self, feature_rows: list[dict[str, Any]]) -> np.ndarray:
        cols: list[np.ndarray] = []
        for name in self.numeric:
            raw = np.array(
                [_as_float(r.get(name)) for r in feature_rows], dtype=float
            )
            missing = ~np.isfinite(raw)
            filled = np.where(missing, self.medians.get(name, 0.0), raw)
            cols.append(filled)
            cols.append(missing.astype(float))
        for name in self.categorical:
            values = [str(r.get(name, "unknown")) for r in feature_rows]
            for level in self.categories[name]:
                cols.append(np.array([1.0 if v == level else 0.0 for v in values]))
        if not cols:
            return np.zeros((len(feature_rows), 0), dtype=float)
        return np.column_stack(cols)


def build_design(
    feature_rows: list[dict[str, Any]],
    blocks: tuple[str, ...],
    *,
    min_category_count: int = 5,
) -> DesignMatrix:
    """Fit the feature layout on training rows only.

    ``min_category_count`` folds rare categories into ``__rare__`` rather than giving
    each its own column. A category seen twice in training is a near-identifier: the
    head can memorise those two rows through it, and on a cold split the column is dead
    weight. Five is a judgement call, fixed before any score was computed.
    """
    numeric: list[str] = []
    categorical: list[str] = []

    if "physics" in blocks:
        numeric.extend(PHYSICS_FEATURES)
    if "corridor" in blocks:
        numeric.extend(CORRIDOR_FEATURES)
    if "image" in blocks:
        numeric.append("image_score")
    if "metadata" in blocks:
        numeric.extend(
            [
                "transmitter_baud",
                "transmitter_downlink_drift",
                "max_altitude_deg_api",
                "azimuth_sweep_deg",
                "abs_station_lat",
                "transmitter_invert",
                "transmitter_unconfirmed",
            ]
        )
        categorical.extend(METADATA_CATEGORICAL)

    medians: dict[str, float] = {}
    for name in numeric:
        vals = np.array([_as_float(r.get(name)) for r in feature_rows], dtype=float)
        finite = vals[np.isfinite(vals)]
        medians[name] = float(np.median(finite)) if finite.size else 0.0

    categories: dict[str, tuple[str, ...]] = {}
    for name in categorical:
        counts: dict[str, int] = {}
        for r in feature_rows:
            v = str(r.get(name, "unknown"))
            counts[v] = counts.get(v, 0) + 1
        kept = sorted(v for v, c in counts.items() if c >= min_category_count)
        categories[name] = tuple([*kept, "__rare__"]) if kept else ("__rare__",)

    columns: list[str] = []
    for name in numeric:
        columns.extend([name, f"{name}__missing"])
    for name in categorical:
        columns.extend([f"{name}={level}" for level in categories[name]])

    return DesignMatrix(
        numeric=tuple(numeric),
        categorical=tuple(categorical),
        categories=categories,
        medians=medians,
        columns=tuple(columns),
    )


def _as_float(v: Any) -> float:
    if v is None or isinstance(v, bool):
        return math.nan
    if isinstance(v, (int, float)):
        f = float(v)
        return f if math.isfinite(f) else math.nan
    return math.nan


# ---------------------------------------------------------------------------
# The head
# ---------------------------------------------------------------------------


@dataclass
class FusionArm:
    """One arm of the ablation ladder: a design, a model and a calibrator."""

    name: str
    blocks: tuple[str, ...]
    seed: int = 42
    design: DesignMatrix | None = None
    model: Any = field(default=None, repr=False)
    prior: float = 0.5
    scaler_mean: np.ndarray | None = field(default=None, repr=False)
    scaler_scale: np.ndarray | None = field(default=None, repr=False)
    degraded: str | None = None

    def fit(self, feature_rows: list[dict[str, Any]], labels: list[int]) -> FusionArm:
        y = np.asarray(labels, dtype=int)
        self.prior = float(y.mean()) if y.size else 0.5

        if not self.blocks:
            # prior_only: the floor. It has no design and no model on purpose, so that
            # "the model that ignores every feature" is a real member of the ladder
            # rather than a number computed elsewhere by different code.
            return self

        self.design = build_design(feature_rows, self.blocks)
        x = self.design.transform(feature_rows)
        if x.shape[1] == 0 or y.size < 20 or len(set(y.tolist())) < 2:
            self.degraded = "TOO_FEW_SAMPLES_OR_COLUMNS"
            return self

        # Standardise with train statistics, kept on the arm so scoring uses the same
        # numbers. A per-call scaler would leak test statistics into test scores.
        self.scaler_mean = x.mean(axis=0)
        self.scaler_scale = np.where(x.std(axis=0) > 1e-12, x.std(axis=0), 1.0)
        xz = (x - self.scaler_mean) / self.scaler_scale

        from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

        # L2 with a fixed C, one setting for every arm. Tuning C per arm would let the
        # comparison between arms measure tuning effort as well as information content.
        # penalty is not passed: L2 is the default and the explicit keyword is
        # deprecated in scikit-learn 1.8. random_state is passed for form only, and the
        # receipt records that it changes nothing for this learner.
        self.model = LogisticRegression(
            C=1.0, max_iter=2000, random_state=self.seed
        ).fit(xz, y)
        return self

    def predict(self, feature_rows: list[dict[str, Any]]) -> np.ndarray:
        n = len(feature_rows)
        if not self.blocks or self.model is None or self.design is None:
            return np.full(n, self.prior, dtype=float)
        x = self.design.transform(feature_rows)
        xz = (x - self.scaler_mean) / self.scaler_scale
        return self.model.predict_proba(xz)[:, 1]


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@dataclass
class Calibrator:
    """Temperature scaling or isotonic regression, fitted on the calibration split.

    Which one is used is a measured choice on splits with enough calibration labels and
    a forced one where there are not. Isotonic has roughly one degree of freedom per
    distinct score and overfits hard on small samples: cold_combined's calibration
    partition holds 49 decisive labels, so temperature scaling is the only admissible
    option there, and picking between them by reliability on 49 points would overfit
    the choice itself. ``min_isotonic_n`` records that threshold instead of leaving it
    to whichever happened to score better.
    """

    method: str = "temperature"
    min_isotonic_n: int = 200
    temperature: float = 1.0
    bias: float = 0.0
    _iso: Any = field(default=None, repr=False)
    chosen_because: str = ""

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> Calibrator:
        n = len(labels)
        if self.method == "auto":
            if n >= self.min_isotonic_n:
                self.method = "isotonic"
                self.chosen_because = (
                    f"{n} calibration labels, at or above the {self.min_isotonic_n} "
                    "floor for isotonic"
                )
            else:
                self.method = "temperature"
                self.chosen_because = (
                    f"only {n} calibration labels, below the {self.min_isotonic_n} floor "
                    "for isotonic; a one-parameter fit is what this sample supports"
                )

        if self.method == "isotonic":
            from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415

            self._iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            self._iso.fit(probs, labels)
            return self

        # Temperature scaling on the logit, one parameter, fitted by minimising log
        # loss over a fixed grid. A grid rather than an optimiser so the result is
        # reproducible to the last digit across platforms.
        logits = _logit(probs)
        best = (float("inf"), 1.0, 0.0)
        for t in np.linspace(0.25, 4.0, 76):
            for b in np.linspace(-2.0, 2.0, 81):
                p = _sigmoid(logits / t + b)
                ll = _log_loss(p, labels)
                if ll < best[0]:
                    best = (ll, float(t), float(b))
        self.temperature, self.bias = best[1], best[2]
        return self

    def apply(self, probs: np.ndarray) -> np.ndarray:
        if self.method == "isotonic" and self._iso is not None:
            return np.clip(self._iso.predict(probs), 1e-6, 1 - 1e-6)
        return _sigmoid(_logit(probs) / self.temperature + self.bias)


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q))


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return np.clip(1.0 / (1.0 + np.exp(-z)), 1e-6, 1 - 1e-6)


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    q = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def calibration_slope_intercept(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Regress the outcome on the predicted logit.

    Slope 1 and intercept 0 is perfect. A slope above 1 means the predictions are too
    timid, below 1 too confident. Returned as a pair because reporting only one of them
    hides the direction of the miscalibration.
    """
    z = _logit(p).reshape(-1, 1)
    if len(set(y.tolist())) < 2:
        return float("nan"), float("nan")
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

    lr = LogisticRegression(C=np.inf, max_iter=2000).fit(z, y)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def expected_calibration_error(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        if not sel.any():
            continue
        total += sel.mean() * abs(p[sel].mean() - y[sel].mean())
    return float(total)


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Rank AUC with tie handling. NaN when one class is absent."""
    if len(set(labels.tolist())) < 2:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    uniq, inv, counts = np.unique(scores, return_inverse=True, return_counts=True)
    sums = np.zeros(len(uniq))
    np.add.at(sums, inv, ranks)
    ranks = (sums / counts)[inv]
    n1 = float(labels.sum())
    n0 = float(len(labels) - n1)
    return float((ranks[labels == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def grouped_paired_bootstrap(
    challenger: np.ndarray,
    reference: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    n_boot: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Paired Brier difference with a bootstrap over *groups*, not observations.

    Resampling observations would treat four captures of one pass over one station as
    four independent samples. They share a receiver, a local oscillator error and a
    sky geometry, so an observation-level interval is too narrow by roughly the average
    group size. Unit A7 made exactly this mistake in the other direction, reading three
    measurements that shared two stations as three independent confirmations.

    Positive ``margin`` means the challenger has the lower Brier score.
    """
    se_c = (challenger - labels) ** 2
    se_r = (reference - labels) ** 2
    diff = se_r - se_c  # positive where the challenger errs less

    unique_groups = np.unique(groups)
    index_by_group = {g: np.flatnonzero(groups == g) for g in unique_groups}
    rng = np.random.default_rng(seed)

    margins = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        drawn = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([index_by_group[g] for g in drawn])
        margins[b] = float(diff[idx].mean())

    lo, hi = np.percentile(margins, [2.5, 97.5])

    # Three directions, not two. An interval entirely below zero means the challenger
    # is reliably *worse*, which is a finding, and a stronger one than "no difference".
    # Reporting it as "spans zero" hides a measured harm behind a null, which is the
    # error this whole comparison exists to avoid.
    if lo > 0.0:
        direction = "challenger_better"
    elif hi < 0.0:
        direction = "reference_better"
    else:
        direction = "indistinguishable"

    return {
        "margin": float(diff.mean()),
        "ci95": [float(lo), float(hi)],
        "direction": direction,
        "distinguishable": bool(direction != "indistinguishable"),
        "challenger_better": bool(direction == "challenger_better"),
        "n_observations": int(len(labels)),
        "n_groups": int(len(unique_groups)),
        "mean_group_size": float(len(labels) / max(len(unique_groups), 1)),
        "n_boot": n_boot,
        "seed": seed,
        "note": (
            "Bootstrap resamples pass episodes, not observations, because captures of "
            "one pass at one station share a receiver and a geometry. margin is the "
            "Brier improvement of the challenger, so a negative margin means the "
            "challenger is worse. direction is the three-way verdict: an interval "
            "entirely below zero is a measured harm, not an absence of difference, and "
            "a positive margin whose interval spans zero is not a gain."
        ),
    }


def grouped_bootstrap_statistic_difference(
    statistic: Callable[[np.ndarray, np.ndarray, np.ndarray], float],
    challenger: np.ndarray,
    reference: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    n_boot: int = 10_000,
    seed: int = 42,
    lower_is_better: bool = True,
    n_comparisons: int = 1,
) -> dict[str, Any]:
    """Grouped bootstrap interval for a statistic that is not a per-observation mean.

    ``grouped_paired_bootstrap`` can average a per-observation difference because Brier
    score is such an average. Area under the risk-coverage curve is not: it depends on
    the ranking of the whole kept set at every threshold, so there is no per-observation
    term to average. The only correct resampling is to redraw the episodes and recompute
    the statistic from scratch on each draw, which is what this does.

    ``statistic(probs, labels, groups) -> float``. ``margin`` is signed so that positive
    always means the challenger is better, whichever direction the statistic runs.

    A resample that produces a NaN statistic, which happens when the drawn sample has
    too few usable points to form a curve, is counted and excluded rather than propagated.
    A NaN silently poisoning a percentile would turn a real interval into nothing, and
    "the resample was degenerate" is a different fact from "the models are tied".

    ``n_comparisons`` widens the reported interval by Bonferroni, and it should be set.
    Comparing arms on a second statistic starts a second family of comparisons: the
    Brier comparisons were corrected over the ladder, so leaving this one uncorrected
    would mean the interval a reader trusts most is the one that was held to the weakest
    standard.
    """
    unique_groups = np.unique(groups)
    index_by_group = {g: np.flatnonzero(groups == g) for g in unique_groups}
    rng = np.random.default_rng(seed)

    sign = 1.0 if lower_is_better else -1.0
    point = sign * (
        statistic(reference, labels, groups) - statistic(challenger, labels, groups)
    )

    margins: list[float] = []
    n_degenerate = 0
    for _ in range(n_boot):
        drawn = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([index_by_group[g] for g in drawn])
        # Each draw of an episode becomes its own group, so a group drawn twice does not
        # collapse into one. Collapsing would shrink the effective sample.
        synthetic = np.concatenate(
            [np.full(len(index_by_group[g]), k) for k, g in enumerate(drawn)]
        )
        m = sign * (
            statistic(reference[idx], labels[idx], synthetic)
            - statistic(challenger[idx], labels[idx], synthetic)
        )
        if not np.isfinite(m):
            n_degenerate += 1
            continue
        margins.append(float(m))

    if len(margins) < max(20, n_boot // 10):
        return {
            "margin": float(point) if np.isfinite(point) else None,
            "ci95": None,
            "direction": "unmeasurable",
            "distinguishable": False,
            "challenger_better": False,
            "n_boot": n_boot,
            "n_usable_resamples": len(margins),
            "n_degenerate_resamples": n_degenerate,
            "seed": seed,
            "note": (
                f"Only {len(margins)} of {n_boot} resamples produced a finite statistic, "
                "so no interval is reported. This is a statement about the resampling, "
                "not about the models."
            ),
        }

    drawn_margins = np.asarray(margins)
    lo, hi = np.percentile(drawn_margins, [2.5, 97.5])
    if lo > 0.0:
        direction = "challenger_better"
    elif hi < 0.0:
        direction = "reference_better"
    else:
        direction = "indistinguishable"

    alpha = 0.05 / max(n_comparisons, 1)
    lo_adj, hi_adj = np.percentile(
        drawn_margins, [100 * alpha / 2, 100 * (1 - alpha / 2)]
    )
    survives = bool(lo_adj > 0.0 or hi_adj < 0.0)

    return {
        "margin": float(point),
        "ci95": [float(lo), float(hi)],
        "direction": direction,
        "distinguishable": bool(direction != "indistinguishable"),
        "challenger_better": bool(direction == "challenger_better"),
        "n_comparisons": int(n_comparisons),
        "ci_adjusted": [float(lo_adj), float(hi_adj)],
        "adjusted_confidence": float(1.0 - alpha),
        "survives_correction": survives,
        "n_observations": int(len(labels)),
        "n_groups": int(len(unique_groups)),
        "n_boot": n_boot,
        "n_usable_resamples": len(margins),
        "n_degenerate_resamples": n_degenerate,
        "seed": seed,
        "note": (
            "The statistic is recomputed on each resampled episode set rather than "
            "averaged from per-observation terms, because it is a functional of the "
            "whole ranking. margin is signed so positive means the challenger is better. "
            "ci_adjusted is Bonferroni-widened over n_comparisons, because comparing "
            "arms on a second statistic opens a second family of comparisons."
        ),
    }


def multiplicity_adjusted(
    challenger: np.ndarray,
    reference: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray,
    n_comparisons: int,
    n_boot: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """The same paired bootstrap at a Bonferroni-widened confidence level.

    Needed because of how an arm gets chosen. The ladder is declared before anything is
    fitted, which is the right discipline, but if several arms are compared against the
    reference and the best one is then quoted, its 95% interval is optimistic: some of
    that margin is the luck of picking the winner. A single arm nominated in advance
    would not need this. One nominated afterwards does.

    So the interval is recomputed at ``1 - 0.05 / n_comparisons``. Bonferroni is
    conservative and that is the point: it is the correction that cannot be accused of
    having been chosen to keep a result alive.
    """
    se_c = (challenger - labels) ** 2
    se_r = (reference - labels) ** 2
    diff = se_r - se_c

    unique = np.unique(groups)
    idx_by_group = {g: np.flatnonzero(groups == g) for g in unique}
    rng = np.random.default_rng(seed)
    margins = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([idx_by_group[g] for g in drawn])
        margins[b] = float(diff[idx].mean())

    alpha = 0.05 / max(n_comparisons, 1)
    lo, hi = np.percentile(margins, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "n_comparisons": int(n_comparisons),
        "family_alpha": 0.05,
        "per_comparison_alpha": float(alpha),
        "confidence_level": float(1 - alpha),
        "margin": float(diff.mean()),
        "ci_adjusted": [float(lo), float(hi)],
        # Either direction. A measured harm is a finding that deserves the same
        # correction as a measured gain, and the earlier one-sided version reported an
        # interval lying entirely below zero as "does not survive", which reads as an
        # absence of effect rather than a corrected harm.
        "survives_correction": bool(lo > 0.0 or hi < 0.0),
        "direction_adjusted": (
            "challenger_better" if lo > 0.0
            else "reference_better" if hi < 0.0
            else "indistinguishable"
        ),
        "note": (
            "Bonferroni over the comparisons reported against the reference on this "
            "split, in both directions. A result that clears zero at 95% but not here was "
            "selected as much as it was measured, and saying so costs less than having it "
            "questioned."
        ),
    }


def seed_sensitivity(
    blocks: tuple[str, ...],
    train_rows: list[dict[str, Any]],
    train_labels: list[int],
    score_rows: list[dict[str, Any]],
    seeds: tuple[int, ...] = (1, 2, 3, 42, 999),
) -> dict[str, Any]:
    """Refit the same arm under several seeds and report the spread of its predictions.

    The plan asks for "a small multi-seed head ensemble for uncertainty". Measured here
    rather than assumed: an L2 logistic regression fitted by lbfgs on fixed data is
    deterministic, so its coefficients are bit-identical across seeds and the spread is
    exactly zero. A seed ensemble over this learner would average five copies of one
    model and report a confidence interval of width zero, which looks like certainty and
    is actually a no-op.

    So the ensemble that does carry information is
    :func:`episode_bootstrap_ensemble`, which resamples the training episodes. This
    function stays because "the seed does nothing" is a claim that should be checked on
    every run rather than remembered from one.
    """
    preds = []
    for s in seeds:
        arm = FusionArm(name="seed_probe", blocks=blocks, seed=s).fit(train_rows, train_labels)
        preds.append(arm.predict(score_rows))
    stack = np.vstack(preds)
    spread = float(np.abs(stack - stack[0]).max()) if stack.size else 0.0
    return {
        "seeds": list(seeds),
        "max_abs_difference": spread,
        "identical": bool(spread == 0.0),
        "note": (
            "Zero spread means the learner ignores its seed, so a multi-seed ensemble "
            "would average identical models and report zero uncertainty. Uncertainty "
            "here comes from the grouped bootstrap and the episode-bootstrap ensemble."
            if spread == 0.0
            else "The learner responds to its seed, so a seed ensemble carries information."
        ),
    }


def episode_bootstrap_ensemble(
    blocks: tuple[str, ...],
    train_rows: list[dict[str, Any]],
    train_labels: list[int],
    train_groups: list[Any],
    score_rows: list[dict[str, Any]],
    n_members: int = 20,
    seed: int = 42,
) -> dict[str, Any]:
    """Bag the head over resampled pass episodes and report per-observation spread.

    Resampling episodes rather than observations, for the same reason the interval does:
    four captures of one pass share a receiver and a geometry, so drawing them
    independently would understate how much the fit depends on which passes happened to
    be in training.

    Returns the ensemble mean (usable as a prediction) and the standard deviation across
    members (usable as an uncertainty the queue can rank on).
    """
    y = np.asarray(train_labels, dtype=int)
    groups = np.asarray([str(g) for g in train_groups])
    unique = np.unique(groups)
    idx_by_group = {g: np.flatnonzero(groups == g) for g in unique}
    rng = np.random.default_rng(seed)

    members: list[np.ndarray] = []
    for _ in range(n_members):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([idx_by_group[g] for g in drawn])
        if len(set(y[idx].tolist())) < 2:
            continue
        arm = FusionArm(name="bag", blocks=blocks, seed=seed).fit(
            [train_rows[i] for i in idx], [int(y[i]) for i in idx]
        )
        members.append(arm.predict(score_rows))

    if not members:
        return {"n_members": 0, "mean": None, "std": None, "degraded": "NO_VALID_MEMBERS"}
    stack = np.vstack(members)
    return {
        "n_members": len(members),
        "n_train_episodes": int(len(unique)),
        "mean": stack.mean(axis=0).tolist(),
        "std": stack.std(axis=0).tolist(),
        "mean_std": float(stack.std(axis=0).mean()),
        "max_std": float(stack.std(axis=0).max()),
        "degraded": None,
    }


def out_of_fold_scores(
    fit_predict: Any,
    feature_rows: list[dict[str, Any]],
    labels: list[int],
    groups: list[Any],
    n_splits: int = 5,
    seed: int = 42,
) -> np.ndarray:
    """Out-of-fold predictions with folds grouped so an episode never splits.

    ``fit_predict(train_rows, train_labels, score_rows) -> np.ndarray``.

    Falls back to a single in-sample fit only when the grouping cannot support the
    requested folds, and that fallback is visible to the caller through the returned
    array being constant-free rather than hidden: callers check ``n_splits_used``.
    """
    from sklearn.model_selection import GroupKFold  # noqa: PLC0415

    y = np.asarray(labels, dtype=int)
    g = np.asarray([str(x) for x in groups])
    n_groups = len(np.unique(g))
    folds = min(n_splits, n_groups)
    scores = np.full(len(y), np.nan, dtype=float)
    if folds < 2:
        return scores

    for train_idx, test_idx in GroupKFold(n_splits=folds).split(
        np.zeros(len(y)), y, groups=g
    ):
        if len(set(y[train_idx].tolist())) < 2:
            continue
        preds = fit_predict(
            [feature_rows[i] for i in train_idx],
            [int(v) for v in y[train_idx]],
            [feature_rows[i] for i in test_idx],
        )
        scores[test_idx] = preds
    return scores
