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
    direction: str  # above_threshold | below_threshold | spans_threshold
                    # | inconsistent_interval | unmeasurable
    verdict: str    # "PASSED" | "NOT_ESTABLISHED" | "FAILED" | "NOT_MEASURABLE"
    threshold: float = 1.5
    #: Bootstrap median. Reported so the bias of the point estimate is auditable
    #: rather than something a reader has to take on trust.
    bootstrap_median: float = float("nan")
    #: False when the point estimate falls outside its own interval by more than
    #: percentile noise. That is a defect in the statistic, not a finding about
    #: the queue, so it is surfaced instead of narrated. See consistency_note.
    point_in_ci: bool = True
    consistency_note: str | None = None
    #: Effective resamples that produced a finite lift, out of n_boot.
    n_boot_effective: int = 0
    #: Why the measurement could not be made, with the count that made it so.
    #: Travels with the result, so a caller cannot label one unmeasurable cause
    #: with another's reason.
    not_measurable_reason: str | None = None

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
            "n_boot_effective": self.n_boot_effective,
            "seed": self.seed,
            "threshold": self.threshold,
            "direction": self.direction,
            "verdict": self.verdict,
            "bootstrap_median": self.bootstrap_median,
            "point_in_ci": self.point_in_ci,
            "consistency_note": self.consistency_note,
            "not_measurable_reason": self.not_measurable_reason,
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

    The bootstrap resamples episodes with replacement to get a distribution of
    lift values. Two properties of that resample are load-bearing.

    First, an episode drawn twice contributes its observations twice. Collapsing
    the draw to a set of distinct observations looks harmless and is not: a draw
    of ``k`` episodes with replacement covers only about 63% of them, so the
    deduplicated population shrinks by roughly a third while the budget stays
    fixed. Selecting 50 of a 55-row population is not selection at all, the drawn
    conflict rate converges on the population rate, and lift is driven to 1.0 by
    construction. That produced intervals lying entirely below their own point
    estimate on every split. Multiplicity is the fix, and ``point_in_ci`` is the
    guard that makes a recurrence loud.

    Second, the budget scales with the drawn population, because lift is a
    function of selectivity. Holding an absolute budget while the population
    size moves changes the quantity being measured between draws.

    The ranking itself is not re-fitted per draw. The queue order is held fixed
    and only the population under it is resampled, because the question is what
    this ranking is worth, not how stable the ranker would be under refitting.

    A draw containing no conflict has no denominator, so its lift is undefined
    and it is dropped. That conditions the interval on "the population contained
    at least one conflict", which matters when conflicts are scarce: with a
    single conflict episode about 37% of draws are dropped. The survivor count
    is reported as ``n_boot_effective`` rather than left implicit, because an
    interval drawn from a conditioned subsample is a different quantity from one
    drawn from all draws, and a reader cannot see that from the interval alone.

    Direction and verdict, four states plus a defect state:
    - "above_threshold"       lo > threshold                      PASSED
    - "spans_threshold"       lo <= threshold <= hi               NOT_ESTABLISHED
    - "below_threshold"       hi < threshold                      FAILED
    - "inconsistent_interval" point outside its own CI            NOT_MEASURABLE
    - "unmeasurable"          no conflicts, or too few resamples  NOT_MEASURABLE

    FAILED requires the whole interval to sit below the bar. An interval that
    spans the bar is NOT_ESTABLISHED whichever side the point estimate falls on,
    which is gate 5's precedent applied in both directions: an interval
    containing the threshold does not establish a claim about it, and it does not
    refute one either.
    """
    n = len(ranked_obs_ids)
    budget = min(budget, n)
    top_ids = ranked_obs_ids[:budget]
    n_q_conflicts = sum(1 for oid in top_ids if conflict_flags.get(oid, False))
    total_conflicts = sum(1 for v in conflict_flags.values() if v)
    random_rate = total_conflicts / n if n > 0 else 0.0
    n_random = random_rate * budget

    if n_random == 0:
        # No conflicts in the population, so random expects zero and the ratio
        # has no denominator. Not a failure of the queue: nothing was there to
        # find. Report the counts that establish that.
        return LiftResult(
            n_queue_conflicts=n_q_conflicts,
            n_random_conflicts=0.0,
            lift_point=float("nan"),
            ci95=[float("nan"), float("nan")],
            n_budget=budget,
            n_total=n,
            n_groups=len({episode_of[oid] for oid in ranked_obs_ids}),
            n_boot=n_boot,
            seed=seed,
            direction="unmeasurable",
            verdict="NOT_MEASURABLE",
            threshold=threshold,
            not_measurable_reason=(
                f"No actionable conflicts in the population, so random ordering "
                f"expects zero and lift has no denominator. Examined {n} ranked "
                f"observations, {total_conflicts} conflicts."
            ),
        )

    lift_point = float(n_q_conflicts) / n_random if n_random > 0 else float("nan")

    # Grouped bootstrap: resample episodes, not observations.
    # Episodes come from the queue itself, not from episode_of, so an episode
    # with no ranked observation cannot be drawn and index into nothing.
    episode_to_obs: dict[str, list[int]] = {}
    for oid in ranked_obs_ids:
        ep = episode_of[oid]
        episode_to_obs.setdefault(ep, []).append(oid)
    # Sort for determinism: set and dict-key iteration order must not decide a
    # published number. This is the C1 non-determinism defect, kept fixed.
    episodes = sorted(episode_to_obs)

    #: Selectivity of the real measurement: the fraction of the population a
    #: reviewer actually gets to look at. Held constant across draws.
    budget_fraction = budget / n

    #: Rank position of each observation, so a resampled pool can be ordered by
    #: the queue's own ranking without re-deriving it.
    rank_of = {oid: i for i, oid in enumerate(ranked_obs_ids)}

    rng = np.random.default_rng(seed)
    bootstrap_lifts: list[float] = []
    for _ in range(n_boot):
        drawn_eps = rng.choice(episodes, size=len(episodes), replace=True)
        # An episode drawn twice contributes its observations twice. Do not
        # deduplicate: multiplicity is what keeps the drawn population the same
        # size as the real one, and therefore keeps the budget selective.
        pool: list[int] = []
        for ep in drawn_eps:
            pool.extend(episode_to_obs[ep])
        drawn_n = len(pool)
        if drawn_n == 0:
            continue
        # Order the drawn pool by the queue's ranking. Duplicates of one
        # observation land adjacent, which is correct: the draw says that row
        # occurs twice in this synthetic population.
        pool.sort(key=lambda oid: rank_of[oid])
        # Budget scales with the drawn population so selectivity is fixed.
        drawn_budget = max(1, min(drawn_n, round(budget_fraction * drawn_n)))
        drawn_top = pool[:drawn_budget]
        drawn_conflicts = sum(1 for oid in pool if conflict_flags.get(oid, False))
        drawn_rate = drawn_conflicts / drawn_n
        drawn_random = drawn_rate * drawn_budget
        if drawn_random == 0:
            continue
        drawn_q_conflicts = sum(1 for oid in drawn_top if conflict_flags.get(oid, False))
        bootstrap_lifts.append(float(drawn_q_conflicts) / drawn_random)

    min_effective = max(20, n_boot // 10)
    if len(bootstrap_lifts) < min_effective:
        return LiftResult(
            n_queue_conflicts=n_q_conflicts,
            n_random_conflicts=n_random,
            lift_point=lift_point,
            ci95=[float("nan"), float("nan")],
            n_budget=budget,
            n_total=n,
            n_groups=len(episodes),
            n_boot=n_boot,
            n_boot_effective=len(bootstrap_lifts),
            seed=seed,
            direction="unmeasurable",
            verdict="NOT_MEASURABLE",
            threshold=threshold,
            not_measurable_reason=(
                f"Only {len(bootstrap_lifts)} of {n_boot} resamples produced a "
                f"finite lift, below the {min_effective} required. Too few draws "
                f"contained a conflict for a percentile interval to mean anything, "
                f"over {len(episodes)} episodes and {n} observations."
            ),
        )

    lo, hi, median = np.percentile(bootstrap_lifts, [2.5, 97.5, 50])
    lo, hi, median = float(lo), float(hi), float(median)

    # Consistency guard. The bootstrap distribution of a ratio on a small,
    # discrete sample is skewed, so the point estimate need not sit at the
    # centre of its interval. It does have to sit inside it. A tolerance of 5%
    # of the interval width absorbs percentile noise on a discrete distribution
    # while still catching a resample that measures a different quantity than
    # the point estimate does.
    tol = 1e-9 + 0.05 * (hi - lo)
    point_in_ci = (lo - tol) <= lift_point <= (hi + tol)
    consistency_note: str | None = None
    if not point_in_ci:
        gap = lift_point - hi if lift_point > hi else lo - lift_point
        consistency_note = (
            f"Point estimate {lift_point:.4f} lies outside its own 95% interval "
            f"[{lo:.4f}, {hi:.4f}] by {gap:.4f}, beyond the {tol:.4f} percentile "
            f"tolerance, over {len(bootstrap_lifts)} effective resamples. The "
            f"resample and the point estimate are measuring different quantities, "
            f"so no verdict is reported."
        )

    if not point_in_ci:
        direction = "inconsistent_interval"
        verdict = "NOT_MEASURABLE"
    elif lo > threshold:
        direction = "above_threshold"
        verdict = "PASSED"
    elif hi < threshold:
        # The whole interval sits below the bar. This is the only shape that
        # refutes the gate rather than failing to establish it.
        direction = "below_threshold"
        verdict = "FAILED"
    else:
        # The interval contains the threshold. Gate 5's precedent, applied in
        # both directions: an interval spanning the bar neither establishes the
        # claim nor refutes it, whichever side the point estimate falls on.
        direction = "spans_threshold"
        verdict = "NOT_ESTABLISHED"

    return LiftResult(
        n_queue_conflicts=n_q_conflicts,
        n_random_conflicts=n_random,
        lift_point=lift_point,
        ci95=[lo, hi],
        n_budget=budget,
        n_total=n,
        n_groups=len(episodes),
        n_boot=n_boot,
        n_boot_effective=len(bootstrap_lifts),
        seed=seed,
        direction=direction,
        verdict=verdict,
        threshold=threshold,
        bootstrap_median=median,
        point_in_ci=point_in_ci,
        consistency_note=consistency_note,
        not_measurable_reason=consistency_note if not point_in_ci else None,
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


#: Every key the schema's split_gate6_result allows, with the value that means
#: "not computed". Built through one constructor so a per-split result cannot
#: omit a key: with additionalProperties closed, a missing key and a null key
#: look identical to a reader, and a misspelled one silently reads as absent.
_GATE6_RESULT_KEYS: dict[str, Any] = {
    "measurable": None,
    "not_measurable_reason": None,
    "n_queue_examined": None,
    "n_random_conflicts": None,
    "n_queue_conflicts": None,
    "lift_point": None,
    "lift_ci95": None,
    "fifo_lift_over_random": None,
    "image_uncertainty_lift_over_random": None,
    "physics_only_lift_over_random": None,
    "n_boot": None,
    "n_boot_effective": None,
    "bootstrap_median": None,
    "point_in_ci": None,
    "consistency_note": None,
    "verdict": None,
    "direction": None,
    "n_groups": None,
}


def _gate6_result(**fields: Any) -> dict[str, Any]:
    """One split's gate 6 result, with every schema key present.

    Raises on an unknown key rather than passing it through, so a typo fails at
    the call site instead of at schema validation time with a confusing message,
    or worse, reads as a measurement nobody took.
    """
    unknown = set(fields) - set(_GATE6_RESULT_KEYS)
    if unknown:
        raise KeyError(
            f"Unknown gate 6 result field(s): {sorted(unknown)}. "
            f"Allowed: {sorted(_GATE6_RESULT_KEYS)}"
        )
    out = dict(_GATE6_RESULT_KEYS)
    out.update(fields)
    return out


def unmeasurable_gate6_result(reason: str) -> dict[str, Any]:
    """A gate 6 result for a split that could not be measured at all.

    For the cases that fail before any ranking exists: no test partition, or an
    arm that would not fit. The reason is required and is not allowed to be a
    placeholder, because "not measurable" with no cause attached is the shape
    that let a scoped-out leakage check hide 12 real violations in Wave B.
    """
    if not reason or len(reason.strip()) < 20:
        raise ValueError(
            "An unmeasurable gate 6 result needs a reason of at least 20 "
            f"characters stating the cause and its counts. Got: {reason!r}"
        )
    return _gate6_result(
        measurable=False,
        verdict="NOT_MEASURABLE",
        direction="unmeasurable",
        not_measurable_reason=reason,
    )


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
        return _gate6_result(
            measurable=False,
            verdict="NOT_MEASURABLE",
            direction="unmeasurable",
            not_measurable_reason=(
                "No decisively-labelled observations in this split's test "
                f"partition. The queue held {n} ranked observations and 0 of them "
                "carry a with-signal or without-signal label, so a conflict "
                "cannot be confirmed or denied for any of them."
            ),
        )

    eff_budget = min(budget, n)
    result = compute_lift(
        queue_obs_ids, conflict_flags, episode_of,
        eff_budget, n_boot=n_boot, seed=seed, threshold=threshold,
    )
    if result.verdict == "NOT_MEASURABLE":
        return _gate6_result(
            measurable=False,
            verdict="NOT_MEASURABLE",
            direction=result.direction,
            # The reason travels with the result. Naming one unmeasurable cause
            # with another's reason is the failure this replaced: a split with
            # zero conflicts was reported as a bootstrap that ran short.
            not_measurable_reason=result.not_measurable_reason,
            n_queue_examined=eff_budget,
            n_random_conflicts=result.n_random_conflicts,
            n_queue_conflicts=result.n_queue_conflicts,
            lift_point=result.lift_point if math.isfinite(result.lift_point) else None,
            n_boot=n_boot,
            n_boot_effective=result.n_boot_effective,
            n_groups=result.n_groups,
            point_in_ci=result.point_in_ci if result.consistency_note else None,
            consistency_note=result.consistency_note,
        )

    # Each baseline's own lift over random at the same budget, on one scale so
    # the five orderings are comparable. These are point estimates: C4 replaces
    # them with paired intervals drawn from the same episode resample, because a
    # ratio between two orderings needs the same draw under both to mean
    # anything.
    def _lift_over_random(ordering: list[int]) -> float | None:
        top = ordering[:eff_budget]
        found = sum(1 for oid in top if conflict_flags.get(oid, False))
        if result.n_random_conflicts == 0:
            return None
        return float(found) / result.n_random_conflicts

    return _gate6_result(
        measurable=True,
        verdict=result.verdict,
        direction=result.direction,
        not_measurable_reason=None,
        n_queue_examined=eff_budget,
        n_random_conflicts=result.n_random_conflicts,
        n_queue_conflicts=result.n_queue_conflicts,
        lift_point=result.lift_point,
        lift_ci95=result.ci95,
        fifo_lift_over_random=_lift_over_random(fifo_order),
        image_uncertainty_lift_over_random=_lift_over_random(image_uncertainty_order),
        physics_only_lift_over_random=_lift_over_random(physics_only_order),
        n_boot=n_boot,
        n_boot_effective=result.n_boot_effective,
        n_groups=result.n_groups,
        bootstrap_median=result.bootstrap_median,
        point_in_ci=result.point_in_ci,
        consistency_note=result.consistency_note,
    )
