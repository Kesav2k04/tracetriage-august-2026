"""Selective prediction and abstention (unit B4).

The product never has to answer. It ranks a review queue, so declining to score an
observation is a legitimate output, and the useful question is not "how accurate is the
model" but "at what coverage does it hold a stated error ceiling".

Two things here are easy to get wrong and both are guarded.

**The threshold is chosen on calibration and verified on test.** Sweeping thresholds on
the test set and reporting the best one measures the sweep. ``threshold_for_risk_ceiling``
picks a confidence cut-off on the calibration partition to hold a target risk, and
``verify_ceiling`` then reports what that same cut-off actually achieved on test, with a
grouped interval. The achieved risk is allowed to exceed the target, and when it does
that is the finding.

**Coverage and risk both need a denominator that is stated.** A model that abstains on
everything has zero risk. Every curve point carries how many observations it kept and
how many groups those came from, so a risk of 0.00 at coverage 0.03 cannot be quoted as
accuracy.

Confidence for a binary score is ``max(p, 1 - p)``: distance from the decision boundary.
A calibrated 0.99 and a calibrated 0.01 are equally confident statements, one positive
and one negative, and treating only the high end as confident would silently make the
queue one-sided.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: Deterministic reason codes for why an observation was not scored. The set is fixed
#: here so the evidence card, the queue and the receipts cannot invent their own
#: wording for the same state.
ABSTAIN_REASONS: dict[str, str] = {
    "LOW_CONFIDENCE": "Calibrated probability too close to the decision boundary.",
    "PHYSICS_DEGRADED": "The pass corridor could not be computed, so no physics evidence exists.",
    "GEOMETRY_UNREADABLE": (
        "The waterfall axis could not be read, so pixels cannot be placed in frequency."
    ),
    "NO_IMAGE": "The waterfall artifact is missing from the snapshot.",
    "OUT_OF_DISTRIBUTION": "The observation is unlike anything in training on a named axis.",
}


def confidence(probs: np.ndarray) -> np.ndarray:
    """Distance from the decision boundary, in [0.5, 1]."""
    p = np.asarray(probs, dtype=float)
    return np.maximum(p, 1.0 - p)


def risk_coverage_curve(
    probs: np.ndarray,
    labels: np.ndarray,
    groups: np.ndarray | None = None,
    n_points: int = 41,
) -> list[dict[str, Any]]:
    """Selective risk against coverage, sweeping the confidence threshold.

    Risk is the error rate among *kept* observations, using a 0.5 decision rule. Each
    point reports ``n_kept`` and ``n_groups_kept`` so a low risk at low coverage cannot
    be read as a low error rate overall.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=int)
    conf = confidence(p)
    pred = (p >= 0.5).astype(int)
    wrong = (pred != y).astype(float)
    g = (
        np.asarray([str(x) for x in groups])
        if groups is not None
        else np.arange(len(y)).astype(str)
    )

    out: list[dict[str, Any]] = []
    for t in np.linspace(0.5, 1.0, n_points):
        keep = conf >= t
        n_kept = int(keep.sum())
        out.append(
            {
                "threshold": float(t),
                "coverage": float(n_kept / len(y)) if len(y) else 0.0,
                "n_kept": n_kept,
                "n_groups_kept": int(len(np.unique(g[keep]))) if n_kept else 0,
                "risk": float(wrong[keep].mean()) if n_kept else None,
                "n_errors": int(wrong[keep].sum()) if n_kept else 0,
            }
        )
    return out


def threshold_for_risk_ceiling(
    cal_probs: np.ndarray,
    cal_labels: np.ndarray,
    target_risk: float,
    min_coverage: float = 0.05,
) -> dict[str, Any]:
    """Lowest confidence threshold on calibration that holds ``target_risk``.

    Lowest, not best: the aim is the most coverage compatible with the ceiling, and
    picking the threshold with the smallest calibration risk would sacrifice coverage
    for a number that will not reproduce on test anyway.

    ``feasible`` is false when no threshold holds the ceiling at ``min_coverage`` or
    above. That is a real answer: it says this model cannot promise this error rate on
    this data, and it must not be turned into a threshold of 1.0 that abstains on
    everything.
    """
    curve = risk_coverage_curve(cal_probs, cal_labels)
    candidates = [
        pt for pt in curve
        if pt["risk"] is not None
        and pt["risk"] <= target_risk
        and pt["coverage"] >= min_coverage
    ]
    if not candidates:
        best = min(
            (pt for pt in curve if pt["risk"] is not None and pt["coverage"] >= min_coverage),
            key=lambda pt: pt["risk"],
            default=None,
        )
        return {
            "feasible": False,
            "target_risk": target_risk,
            "min_coverage": min_coverage,
            "threshold": None,
            "best_calibration_risk": best["risk"] if best else None,
            "best_calibration_coverage": best["coverage"] if best else None,
            "reason": (
                f"No confidence threshold holds risk at or below {target_risk:.3f} while "
                f"keeping at least {min_coverage:.0%} of observations. The lowest "
                f"calibration risk available at that coverage is "
                f"{best['risk']:.3f}" if best else "and no threshold reached the coverage floor."
            ),
        }
    chosen = min(candidates, key=lambda pt: pt["threshold"])
    return {
        "feasible": True,
        "target_risk": target_risk,
        "min_coverage": min_coverage,
        "threshold": chosen["threshold"],
        "calibration_risk": chosen["risk"],
        "calibration_coverage": chosen["coverage"],
        "calibration_n_kept": chosen["n_kept"],
        "note": (
            "Chosen on the calibration partition. The risk achieved on test is a "
            "separate measurement and may exceed the target."
        ),
    }


def verify_ceiling(
    threshold: float,
    test_probs: np.ndarray,
    test_labels: np.ndarray,
    groups: np.ndarray,
    target_risk: float,
    n_boot: int = 10_000,
    seed: int = 42,
) -> dict[str, Any]:
    """Apply a calibration-chosen threshold to test and report what it achieved.

    The upper end of the grouped bootstrap interval is what decides whether the ceiling
    held. A point estimate below the target with an interval reaching well above it is
    not a guarantee, and the queue's promise to a reviewer is about the worst plausible
    case rather than the central one.
    """
    p = np.asarray(test_probs, dtype=float)
    y = np.asarray(test_labels, dtype=int)
    g = np.asarray([str(x) for x in groups])
    keep = confidence(p) >= threshold
    n_kept = int(keep.sum())
    if n_kept == 0:
        return {
            "threshold": threshold,
            "coverage": 0.0,
            "n_kept": 0,
            "risk": None,
            "held": None,
            "note": (
                "The threshold kept nothing on test. Neither held nor failed: there is "
                "no error rate to report, and calling that a pass would make abstaining "
                "on everything the safest way to satisfy the gate."
            ),
        }

    wrong = ((p >= 0.5).astype(int) != y).astype(float)
    kept_groups = g[keep]
    unique = np.unique(kept_groups)
    idx_by_group = {q: np.flatnonzero(kept_groups == q) for q in unique}
    kept_wrong = wrong[keep]
    rng = np.random.default_rng(seed)
    risks = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        drawn = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([idx_by_group[q] for q in drawn])
        risks[b] = float(kept_wrong[idx].mean())
    lo, hi = np.percentile(risks, [2.5, 97.5])

    risk = float(kept_wrong.mean())
    return {
        "threshold": float(threshold),
        "target_risk": target_risk,
        "coverage": float(n_kept / len(y)),
        "n_kept": n_kept,
        "n_total": int(len(y)),
        "n_groups_kept": int(len(unique)),
        "risk": risk,
        "risk_ci95": [float(lo), float(hi)],
        "n_errors": int(kept_wrong.sum()),
        "held": bool(hi <= target_risk),
        "held_at_point_estimate": bool(risk <= target_risk),
        "note": (
            "This holds on the upper end of the interval, not on the point estimate, "
            "because the promise made to a reviewer is about the worst plausible error "
            "rate at the reported coverage. Whether it would also hold on the point "
            "estimate is reported in the column beside it, so the difference between "
            "the two is visible rather than argued about."
        ),
    }


@dataclass
class AbstentionPolicy:
    """Confidence threshold plus the hard reasons that abstain regardless of score.

    A degraded physics result or an unreadable axis abstains even when the head is
    confident, because a confident score computed from a missing measurement is
    confident about nothing. Order matters: the hard reasons are checked first, so a
    receipt says ``GEOMETRY_UNREADABLE`` rather than ``LOW_CONFIDENCE`` when both apply.
    """

    threshold: float
    hard_reasons: tuple[str, ...] = ("NO_IMAGE", "GEOMETRY_UNREADABLE", "PHYSICS_DEGRADED")

    def decide(self, prob: float, states: dict[str, bool]) -> dict[str, Any]:
        for reason in self.hard_reasons:
            if states.get(reason):
                return {
                    "scored": False,
                    "reason": reason,
                    "explanation": ABSTAIN_REASONS[reason],
                    "probability": None,
                }
        if states.get("OUT_OF_DISTRIBUTION"):
            return {
                "scored": False,
                "reason": "OUT_OF_DISTRIBUTION",
                "explanation": ABSTAIN_REASONS["OUT_OF_DISTRIBUTION"],
                "probability": float(prob),
            }
        if float(confidence(np.array([prob]))[0]) < self.threshold:
            return {
                "scored": False,
                "reason": "LOW_CONFIDENCE",
                "explanation": ABSTAIN_REASONS["LOW_CONFIDENCE"],
                "probability": float(prob),
            }
        return {"scored": True, "reason": None, "explanation": None, "probability": float(prob)}


def area_under_risk_coverage(curve: list[dict[str, Any]]) -> float:
    """Area under the risk-coverage curve, lower is better.

    Integrated over coverage rather than over threshold, so two models that abstain at
    different rates are compared on the same axis. Points that kept nothing are skipped
    because they have no risk to contribute.
    """
    pts = [(pt["coverage"], pt["risk"]) for pt in curve if pt["risk"] is not None]
    if len(pts) < 2:
        return float("nan")
    pts.sort()
    cov = np.array([c for c, _ in pts])
    risk = np.array([r for _, r in pts])
    return float(np.trapezoid(risk, cov) / max(cov.max() - cov.min(), 1e-9))
