"""Review-value queue and kill gate 6 (unit C1).

The queue ranks observations by review *value*, not by model probability alone.
A calibrated probability from an arm this weak (Brier 0.1292, AUC 0.875, but
ECE 0.071 and calibration slope 1.48) will not order the queue usefully if used
as the only signal. Review value is a different quantity: disagreement with the
current SatNOGS label, uncertainty, frequency-offset magnitude, and dead-capture
fraction. Disagreement is the one with real content because it does not require
the model to be strong in absolute terms, only to disagree in the right places.

Gate 6, in the plan's words: "Require the top review queue to find at least 1.5
times as many manually actionable conflicts as random ordering at the same budget."

Five design constraints, all enforced in code rather than remembered from prose.

**Conflict definition is fixed before ranking.** ``CONFLICT_CRITERIA`` is declared
as a module-level constant. The script reads it before fitting anything. A definition
changed after seeing the lift is not a definition.

**Duplicate-safe deduplication.** The queue never surfaces two observations of the
same pass episode. Episode = (ground_station, norad_cat_id, orbital_revolution).
When two episodes share a waterfall SHA-256, the one with the higher composite
score is kept and the reason is recorded; the SHA-256 duplicate set is empty in
the stage-1 corpus (all 2,500 hashes are distinct) so this path is exercised by
a constructed test rather than by the data.

**Grouped lift bootstrap.** Episode resampling throughout. Four captures of one pass
at one station share a receiver, a local-oscillator error and a sky geometry. An
observation-level interval for lift would be too narrow by roughly the average
episode size.

**Four baselines, not one.** Random, FIFO, image-uncertainty, physics-only. Each gets
the same budget and the same conflict definition. A queue that beats only random could
be beaten in practice by a simpler baseline a reviewer already uses.

**Every verdict has a not-measurable state.** A split where the entire test set is
smaller than the budget, or where no decisive labels exist, says so with a reason
rather than reporting a failure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Fixed vocabulary of queue reasons
# ---------------------------------------------------------------------------

#: Every reason a queue entry can carry. Fixed before any ranking is computed.
#: ``NO_REASON`` means the entry is ranked but triggers no conflict criterion;
#: it must appear in the final queue because diversity requires filling the budget
#: even when the top-ranked observations do not trigger a criterion.
QUEUE_REASONS: dict[str, str] = {
    "MODEL_LABEL_DISAGREE": (
        "The shipped arm predicts with confidence ≥ 0.75 that the label should be "
        "the opposite of the current waterfall_status."
    ),
    "STALE_CATALOGUE_FREQ": (
        "The fitted frequency offset is ≥ 20 ppm from the catalogue downlink and "
        "the search did not hit its window limit, implying a stale catalogue entry."
    ),
    "DEAD_CAPTURE": (
        "At least 15% of waterfall rows carry no luminance variation, indicating "
        "dead capture time that may reflect a misconfigured receiver."
    ),
    "OFFSET_AT_BOUND": (
        "Informational, not actionable. The offset search hit its window limit; "
        "the reported value is a floor, not a measurement."
    ),
    "NO_REASON": (
        "The observation is ranked by composite review-value score but triggers "
        "no actionable conflict criterion."
    ),
}

# ---------------------------------------------------------------------------
# Conflict definition (fixed before measuring)
# ---------------------------------------------------------------------------

#: Conflict criteria, each checkable from the snapshot without a human.
#: These are the exact parameters used by ``is_conflict`` and ``classify_reasons``.
#: Do not change them after ``scripts/run_queue.py`` has been run.
CONFLICT_CRITERIA: list[dict[str, Any]] = [
    {
        "reason_code": "MODEL_LABEL_DISAGREE",
        "description": (
            "Shipped arm (image_corridor) predicts with calibrated probability ≥ 0.75 "
            "that the observation is positive when the label is without-signal, or "
            "≤ 0.25 (confident negative) when the label is with-signal."
        ),
        "threshold": {"prob_positive_floor": 0.75, "prob_negative_ceiling": 0.25},
        "measurable_from_snapshot": True,
    },
    {
        "reason_code": "STALE_CATALOGUE_FREQ",
        "description": (
            "Fitted frequency offset magnitude ≥ 20 ppm of the catalogue downlink "
            "frequency and offset_at_bound is false. Implies the SatNOGS transmitter "
            "catalogue frequency is at least 20 ppm stale."
        ),
        "threshold": {"abs_offset_ppm_min": 20.0},
        "measurable_from_snapshot": True,
    },
    {
        "reason_code": "DEAD_CAPTURE",
        "description": (
            "flat_row_frac ≥ 0.15: at least 15% of waterfall rows carry no luminance "
            "variation, indicating substantial dead capture time."
        ),
        "threshold": {"flat_row_frac_min": 0.15},
        "measurable_from_snapshot": True,
    },
]

#: Thresholds extracted from ``CONFLICT_CRITERIA`` for direct use in code.
_PROB_DISAGREE_HIGH = 0.75
_PROB_DISAGREE_LOW = 0.25
_OFFSET_PPM_MIN = 20.0
_FLAT_ROW_FRAC_MIN = 0.15


# ---------------------------------------------------------------------------
# Per-observation conflict classification
# ---------------------------------------------------------------------------


def classify_reasons(
    waterfall_status: str | None,
    model_prob: float | None,
    fitted_offset_ppm: float | None,
    offset_at_bound: bool | None,
    flat_row_frac: float | None,
) -> list[str]:
    """Return the list of reasons that apply to one observation.

    Returns exactly one reason per applicable criterion, plus
    ``OFFSET_AT_BOUND`` when offset_at_bound is true (informational, not
    actionable). Returns ``['NO_REASON']`` when nothing applies.

    The order is fixed: MODEL_LABEL_DISAGREE, STALE_CATALOGUE_FREQ, DEAD_CAPTURE,
    OFFSET_AT_BOUND. An observation can carry multiple reasons.
    """
    reasons: list[str] = []

    # MODEL_LABEL_DISAGREE: confident model disagreement with the current label
    if model_prob is not None and waterfall_status in ("with-signal", "without-signal") and (
        (waterfall_status == "without-signal" and model_prob >= _PROB_DISAGREE_HIGH)
        or (waterfall_status == "with-signal" and model_prob <= _PROB_DISAGREE_LOW)
    ):
        reasons.append("MODEL_LABEL_DISAGREE")

    # STALE_CATALOGUE_FREQ: large offset, not at the search boundary
    if (
        fitted_offset_ppm is not None
        and offset_at_bound is not None
        and not offset_at_bound
        and abs(fitted_offset_ppm) >= _OFFSET_PPM_MIN
    ):
        reasons.append("STALE_CATALOGUE_FREQ")

    # DEAD_CAPTURE: substantial flat-row fraction
    if flat_row_frac is not None and flat_row_frac >= _FLAT_ROW_FRAC_MIN:
        reasons.append("DEAD_CAPTURE")

    # OFFSET_AT_BOUND: informational flag, not counted as a conflict
    if offset_at_bound:
        reasons.append("OFFSET_AT_BOUND")

    return reasons if reasons else ["NO_REASON"]


def is_conflict(reasons: list[str]) -> bool:
    """True iff the reasons list contains at least one actionable reason.

    ``OFFSET_AT_BOUND`` is informational. ``NO_REASON`` means nothing applies.
    """
    actionable = {"MODEL_LABEL_DISAGREE", "STALE_CATALOGUE_FREQ", "DEAD_CAPTURE"}
    return bool(set(reasons) & actionable)


# ---------------------------------------------------------------------------
# Composite ranking score
# ---------------------------------------------------------------------------


def composite_score(
    waterfall_status: str | None,
    model_prob: float | None,
    fitted_offset_ppm: float | None,
    offset_at_bound: bool | None,
    flat_row_frac: float | None,
    ensemble_uncertainty: float | None,
    rank_norms: dict[str, float],
) -> float:
    """Composite review-value score in [0, 1].

    Weights (fixed before measuring):
      0.40 × rank-normalised disagreement
      0.35 × rank-normalised safe offset magnitude
      0.15 × rank-normalised flat_row_frac
      0.10 × rank-normalised ensemble uncertainty

    ``rank_norms`` maps feature name to the pre-computed rank-normalised value
    for this observation, computed across the full candidate set.

    Rank normalisation ensures no single signal dominates through scale
    differences. Safe offset magnitude excludes at-bound rows (they are ranked
    to 0 on this signal) because an offset at the search boundary is not
    a measurement of stale frequency; it is a lower bound on the unknown offset.
    """
    disagree = rank_norms.get("disagreement", 0.0)
    offset_safe = rank_norms.get("offset_safe", 0.0)
    flat = rank_norms.get("flat_row_frac", 0.0)
    uncertainty = rank_norms.get("ensemble_uncertainty", 0.0)

    return (
        0.40 * disagree
        + 0.35 * offset_safe
        + 0.15 * flat
        + 0.10 * uncertainty
    )


def _disagreement_value(
    waterfall_status: str | None,
    model_prob: float | None,
) -> float:
    """How much the model disagrees with the current label.

    For a decisively-labelled observation: distance between the model's
    calibrated probability and the label's implied 0-or-1 value. Larger means
    more disagreement. For unlabelled observations: model confidence (distance
    from 0.5), because we cannot measure disagreement without a label.
    """
    if model_prob is None:
        return 0.0
    if waterfall_status == "with-signal":
        # disagreement = model says it is negative (low prob)
        return 1.0 - model_prob
    if waterfall_status == "without-signal":
        # disagreement = model says it is positive (high prob)
        return model_prob
    # unlabelled: use raw confidence (distance from 0.5)
    return abs(model_prob - 0.5) * 2.0


def rank_normalise(values: list[float]) -> list[float]:
    """Rank-normalise a list of values to [0, 1].

    Ties get the average rank. The maximum rank normalised value is 1.0 and
    the minimum is 1/N (not 0), so no observation is permanently zeroed by
    normalisation alone.
    """
    n = len(values)
    if n == 0:
        return []
    arr = np.asarray(values, dtype=float)
    # replace NaN with the minimum finite value so missing data ranks last
    finite_min = float(np.nanmin(arr)) if not np.all(np.isnan(arr)) else 0.0
    arr = np.where(np.isnan(arr), finite_min, arr)
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(1, n + 1, dtype=float)
    # tie-average: same value → same rank
    uniq, inv, counts = np.unique(arr, return_inverse=True, return_counts=True)
    sums = np.zeros(len(uniq))
    np.add.at(sums, inv, ranks)
    avg_ranks = sums / counts
    ranks = avg_ranks[inv]
    return (ranks / n).tolist()


# ---------------------------------------------------------------------------
# Episode deduplication
# ---------------------------------------------------------------------------


def _episode_key(
    ground_station: int,
    norad_cat_id: int,
    orbital_revolution: int,
) -> str:
    """Canonical string key for a pass episode."""
    return f"{ground_station}:{norad_cat_id}:{orbital_revolution}"


def deduplicate_by_episode(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one observation per (ground_station, norad_cat_id, orbital_revolution) episode.

    When an episode appears more than once, keep the one with the highest
    composite score. Ties are broken by obs_id (lower wins, for determinism).

    SHA-256 duplicates: when two different episodes share a waterfall SHA-256,
    both are kept if their episode keys differ, because they are physically
    different passes. The stage-1 corpus has no SHA-256 duplicates (2,500 distinct
    hashes), so this path is exercised by a constructed test only.
    """
    best: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = entry["episode_key"]
        existing = best.get(key)
        replaces = (
            existing is None
            or entry["score"] > existing["score"]
            or (entry["score"] == existing["score"] and entry["obs_id"] < existing["obs_id"])
        )
        if replaces:
            best[key] = entry
    return list(best.values())


# ---------------------------------------------------------------------------
# Lift computation
# ---------------------------------------------------------------------------


@dataclass
class LiftResult:
    """Lift of a ranking over random at a fixed budget, with a grouped interval."""

    n_queue_conflicts: int
    n_random_conflicts: float  # expectation, not integer
    lift_point: float
    ci95: list[float]
    n_budget: int
    n_total: int
    n_groups: int
    n_boot: int
    seed: int
    direction: str  # "above_threshold" | "below_threshold" | "spans_threshold"
    verdict: str    # "PASSED" | "NOT_ESTABLISHED" | "FAILED"
    threshold: float = 1.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_queue_conflicts": self.n_queue_conflicts,
            "n_random_conflicts": self.n_random_conflicts,
            "lift_point": self.lift_point,
            "lift_ci95": self.ci95,
            "n_budget": self.n_budget,
            "n_total": self.n_total,
            "n_groups": self.n_groups,
            "n_boot": self.n_boot,
            "seed": self.seed,
            "threshold": self.threshold,
            "direction": self.direction,
            "verdict": self.verdict,
        }


def compute_lift(
    ranked_obs_ids: list[int],
    conflict_flags: dict[int, bool],
    episode_of: dict[int, str],
    budget: int,
    *,
    n_boot: int = 4000,
    seed: int = 42,
    threshold: float = 1.5,
) -> LiftResult:
    """Lift of the queue over random at ``budget`` observations, with grouped bootstrap.

    ``ranked_obs_ids`` is the queue in rank order (index 0 = top of queue).
    ``conflict_flags`` maps obs_id to True/False (is it an actionable conflict?).
    ``episode_of`` maps obs_id to its episode key string.

    The interval is over episodes (groups), not observations. Four captures of
    one pass at one station share a receiver and a geometry, so an
    observation-level interval would be too narrow.

    Lift = (conflicts found by queue at budget) / (expected conflicts by random
    at budget). Random expectation = budget × (total_conflicts / total_obs).

    The bootstrap resamples episodes to get a distribution of lift values. Each
    bootstrap draw produces a synthetic population, the top-budget entries of the
    re-ranked queue are inspected, and the lift is computed on the draw.

    Direction and verdict follow the same four-state rule as gate 5:
    - "above_threshold" → lo > threshold → PASSED
    - "spans_threshold" → point > threshold but lo <= threshold → NOT_ESTABLISHED
    - "below_threshold" → point <= threshold → FAILED

    The NOT_ESTABLISHED state covers two shapes: the CI spans the threshold, and
    the CI lies entirely below the threshold while the point estimate is above it.
    Both say the same thing: the point went in the right direction but the
    bootstrap does not support the claim. The "below_threshold" direction is
    reserved for the case where even the point estimate fails the gate, because
    that is a stronger finding and collapses the two-part standard into one.
    """
    n = len(ranked_obs_ids)
    budget = min(budget, n)
    top_ids = ranked_obs_ids[:budget]
    n_q_conflicts = sum(1 for oid in top_ids if conflict_flags.get(oid, False))
    total_conflicts = sum(1 for v in conflict_flags.values() if v)
    random_rate = total_conflicts / n if n > 0 else 0.0
    n_random = random_rate * budget

    if n_random == 0:
        # No conflicts at all: lift is undefined (and cannot exceed 1.5)
        return LiftResult(
            n_queue_conflicts=n_q_conflicts,
            n_random_conflicts=0.0,
            lift_point=float("nan"),
            ci95=[float("nan"), float("nan")],
            n_budget=budget,
            n_total=n,
            n_groups=len(sorted(set(episode_of.values()))),
            n_boot=n_boot,
            seed=seed,
            direction="unmeasurable",
            verdict="NOT_MEASURABLE",
            threshold=threshold,
        )

    lift_point = float(n_q_conflicts) / n_random if n_random > 0 else float("nan")

    # Grouped bootstrap: resample episodes, not observations.
    # Sort for determinism: set iteration order is not guaranteed in Python.
    episodes = sorted(set(episode_of.values()))
    episode_to_obs: dict[str, list[int]] = {}
    for oid in ranked_obs_ids:
        ep = episode_of[oid]
        episode_to_obs.setdefault(ep, []).append(oid)

    rng = np.random.default_rng(seed)
    bootstrap_lifts: list[float] = []
    for _ in range(n_boot):
        drawn_eps = rng.choice(episodes, size=len(episodes), replace=True)
        # Rebuild the pool in the drawn sample, preserving within-episode order
        pool: list[int] = []
        for ep in drawn_eps:
            pool.extend(episode_to_obs[ep])
        # The queue ranking within the drawn sample: keep the same relative order
        # as the original ranked list (stable sort preserves order for same episode)
        pool_set = set(pool)
        drawn_ranked = [oid for oid in ranked_obs_ids if oid in pool_set]
        drawn_budget = min(budget, len(drawn_ranked))
        drawn_top = drawn_ranked[:drawn_budget]
        drawn_n = len(pool_set)
        drawn_conflicts = sum(1 for oid in pool_set if conflict_flags.get(oid, False))
        drawn_rate = drawn_conflicts / drawn_n if drawn_n > 0 else 0.0
        drawn_random = drawn_rate * drawn_budget
        if drawn_random == 0 or drawn_budget == 0:
            continue
        drawn_q_conflicts = sum(1 for oid in drawn_top if conflict_flags.get(oid, False))
        bootstrap_lifts.append(float(drawn_q_conflicts) / drawn_random)

    if len(bootstrap_lifts) < max(20, n_boot // 10):
        return LiftResult(
            n_queue_conflicts=n_q_conflicts,
            n_random_conflicts=n_random,
            lift_point=lift_point,
            ci95=[float("nan"), float("nan")],
            n_budget=budget,
            n_total=n,
            n_groups=len(episodes),
            n_boot=n_boot,
            seed=seed,
            direction="unmeasurable",
            verdict="NOT_MEASURABLE",
            threshold=threshold,
        )

    lo, hi = np.percentile(bootstrap_lifts, [2.5, 97.5])
    lo, hi = float(lo), float(hi)

    if lo > threshold:
        direction = "above_threshold"
        verdict = "PASSED"
    elif lift_point > threshold:
        # Point estimate is in the right direction but the bootstrap interval
        # does not clear the threshold (either it spans the threshold or lies
        # entirely below it). Both shapes mean the evidence is insufficient.
        direction = "spans_threshold"
        verdict = "NOT_ESTABLISHED"
    else:
        # Even the point estimate fails the gate.
        direction = "below_threshold"
        verdict = "FAILED"

    return LiftResult(
        n_queue_conflicts=n_q_conflicts,
        n_random_conflicts=n_random,
        lift_point=lift_point,
        ci95=[lo, hi],
        n_budget=budget,
        n_total=n,
        n_groups=len(episodes),
        n_boot=n_boot,
        seed=seed,
        direction=direction,
        verdict=verdict,
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Baseline orderings
# ---------------------------------------------------------------------------


def baseline_fifo(obs_ids_by_time: list[int]) -> list[int]:
    """FIFO ordering: sort by observation id (proxy for chronological order)."""
    return sorted(obs_ids_by_time)


def baseline_image_uncertainty(
    obs_ids: list[int],
    model_probs: dict[int, float | None],
) -> list[int]:
    """Image-uncertainty ordering: descending model confidence (max(p, 1-p)).

    Observations with missing image score go to the bottom.
    """
    def _conf(oid: int) -> float:
        p = model_probs.get(oid)
        if p is None or not math.isfinite(p):
            return 0.0
        return max(p, 1.0 - p)

    return sorted(obs_ids, key=_conf, reverse=True)


def baseline_physics_only(
    obs_ids: list[int],
    physics_scores: dict[int, float | None],
) -> list[int]:
    """Physics-only ordering: descending AUC-proxy score from the physics arm.

    The physics arm predicts with probability; here we just rank by its output.
    Observations without physics scores go to the bottom.
    """
    def _score(oid: int) -> float:
        v = physics_scores.get(oid)
        if v is None or not math.isfinite(v):
            return -1.0
        return v

    return sorted(obs_ids, key=_score, reverse=True)


# ---------------------------------------------------------------------------
# Per-split gate 6 measurement
# ---------------------------------------------------------------------------


def measure_gate6_split(
    split_name: str,
    queue_obs_ids: list[int],          # full queue in rank order
    conflict_flags: dict[int, bool],   # obs_id → is_conflict
    episode_of: dict[int, str],        # obs_id → episode key
    budget: int,
    fifo_order: list[int],
    image_uncertainty_order: list[int],
    physics_only_order: list[int],
    *,
    n_boot: int = 4000,
    seed: int = 42,
    threshold: float = 1.5,
) -> dict[str, Any]:
    """Gate 6 measurement for one split.

    Returns a per-split result dict matching ``split_gate6_result`` in the schema.
    When the split cannot be measured (e.g., zero decisive labels, or the budget
    exceeds the pool), returns a NOT_MEASURABLE result with a reason.
    """
    n = len(queue_obs_ids)
    n_decisive = len(conflict_flags)

    if n_decisive == 0:
        _no_decisive = "No decisively-labelled observations in this split's test partition."
        return {
            "measurable": False,
            "not_measurable_reason": _no_decisive,
            "n_queue_examined": None,
            "n_random_conflicts": None,
            "n_queue_conflicts": None,
            "lift_point": None,
            "lift_ci95": None,
            "lift_vs_fifo": None,
            "lift_vs_image_uncertainty": None,
            "lift_vs_physics_only": None,
            "n_boot": None,
            "n_groups": None,
            "verdict": "NOT_MEASURABLE",
            "direction": "unmeasurable",
        }

    eff_budget = min(budget, n)
    result = compute_lift(
        queue_obs_ids, conflict_flags, episode_of,
        eff_budget, n_boot=n_boot, seed=seed, threshold=threshold,
    )
    if result.verdict == "NOT_MEASURABLE":
        return {
            "measurable": False,
            "not_measurable_reason": "Bootstrap could not produce enough finite resamples.",
            "n_queue_examined": eff_budget,
            "n_random_conflicts": result.n_random_conflicts,
            "n_queue_conflicts": result.n_queue_conflicts,
            "lift_point": result.lift_point if math.isfinite(result.lift_point) else None,
            "lift_ci95": None,
            "lift_vs_fifo": None,
            "lift_vs_image_uncertainty": None,
            "lift_vs_physics_only": None,
            "n_boot": n_boot,
            "n_groups": result.n_groups,
            "verdict": "NOT_MEASURABLE",
            "direction": "unmeasurable",
        }

    # Baseline lifts (point estimate only, no interval — they are reference points)
    def _baseline_lift(baseline_order: list[int]) -> float | None:
        b_top = baseline_order[:eff_budget]
        b_q = sum(1 for oid in b_top if conflict_flags.get(oid, False))
        if result.n_random_conflicts == 0:
            return None
        return float(b_q) / result.n_random_conflicts

    fifo_lift = _baseline_lift(fifo_order)
    img_lift = _baseline_lift(image_uncertainty_order)
    phys_lift = _baseline_lift(physics_only_order)

    return {
        "measurable": True,
        "not_measurable_reason": None,
        "n_queue_examined": eff_budget,
        "n_random_conflicts": result.n_random_conflicts,
        "n_queue_conflicts": result.n_queue_conflicts,
        "lift_point": result.lift_point,
        "lift_ci95": result.ci95,
        "lift_vs_fifo": fifo_lift,
        "lift_vs_image_uncertainty": img_lift,
        "lift_vs_physics_only": phys_lift,
        "n_boot": n_boot,
        "n_groups": result.n_groups,
        "verdict": result.verdict,
        "direction": result.direction,
    }
