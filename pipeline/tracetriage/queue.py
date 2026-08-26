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
        "the search did not hit its window limit, implying a stale catalogue entry. "
        "This criterion asks the offset's size and not its significance, which is its "
        "known weakness and is stated here rather than left to be found: over the 716 "
        "rows carrying both quantities, the 189 it fires on have a median matched-filter "
        "sigma of 0.591 against 0.482 for the rows it does not fire on, and 17 of the "
        "189, 9 percent, reach 2 sigma. So most of what it flags is an offset the "
        "corridor cannot separate from noise. It is pre-registered and it is left "
        "as written, because choosing a criterion after seeing which one helps is the "
        "practice this project rejects everywhere else. Read the queue's lift with this "
        "in view: this reason supplies 19 of the 22 conflicts on the chronological split."
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
    "DISPLACED_STATION_CAP": (
        "Ranked inside the review budget but displaced below it because its ground "
        "station had already filled its share of the budget. Still a candidate, "
        "still in the queue, and not deleted."
    ),
    "DISPLACED_TRANSMITTER_CAP": (
        "Ranked inside the review budget but displaced below it because its "
        "transmitter had already filled its share of the budget. Still a candidate, "
        "still in the queue, and not deleted."
    ),
}

# ---------------------------------------------------------------------------
# Entity concentration
# ---------------------------------------------------------------------------

#: Share of the review budget any single entity may occupy. Fixed in
#: docs/C2_PREREGISTRATION.md and committed before the effect on lift was
#: measured. Station 10%: five entries is enough for a reviewer to recognise a
#: systematic fault at one site, and it leaves 45 of 50 slots for the other 270
#: stations. Transmitter 20%: one transmitter already holds 312 of 2727
#: observations, 11.4% of the corpus, so a cap at its corpus share would bind on
#: ordinary data rather than on flooding.
CONCENTRATION_CAPS: dict[str, float] = {
    "ground_station": 0.10,
    "transmitter_uuid": 0.20,
}

#: Which reason each capped entity records when it displaces an entry.
_CAP_REASON: dict[str, str] = {
    "ground_station": "DISPLACED_STATION_CAP",
    "transmitter_uuid": "DISPLACED_TRANSMITTER_CAP",
}

#: What to call each cap in a sentence a reviewer reads.
#:
#: The concentration note printed the field names as a Python list, so the console said
#: "Caps that displaced nothing ...: ['transmitter_uuid']". That is a value, not a
#: sentence, and it asks a reader to know the schema to learn which cap was inert. Kept
#: beside the caps rather than in the formatter, so a new cap cannot be added without a
#: name; the lookup falls back to the key rather than raising, because an unnamed cap
#: should still be reportable.
_CAP_LABEL: dict[str, str] = {
    "ground_station": "the per-ground-station cap",
    "transmitter_uuid": "the per-transmitter cap",
}


def _cap_names(names: list[str]) -> str:
    """One or more cap names, joined the way a sentence joins them."""
    labelled = [_CAP_LABEL.get(name, f"the {name} cap") for name in sorted(names)]
    if len(labelled) == 1:
        return labelled[0]
    return ", ".join(labelled[:-1]) + " and " + labelled[-1]


def cap_entries(budget: int, share: float) -> int:
    """Entries one entity may hold at a given budget, at least one.

    Rounded up, so a cap can never silently become zero on a small budget and
    exclude an entity from review altogether.
    """
    return max(1, math.ceil(share * budget))


def apply_concentration_caps(
    ranked_obs_ids: list[int],
    entity_of: dict[str, dict[int, Any]],
    budget: int,
    caps: dict[str, float] | None = None,
) -> tuple[list[int], dict[str, Any]]:
    """Reorder a ranking so no single entity floods the review budget.

    One greedy pass down the ranking. An entry whose station or transmitter has
    already filled its quota within the budget slice is displaced below the
    budget line, keeps its relative order among the displaced, and carries a
    reason. Nothing is deleted: a displaced observation is still a real candidate,
    and a silently dropped row is a suppressed finding.

    ``entity_of`` maps an entity name to a per-observation lookup. An observation
    missing from a lookup is treated as its own singleton entity, because an
    unknown station cannot be shown to share a receiver with anything.

    Returns the reordered ranking and a record carrying, per entity, the cap in
    entries, the number displaced, and the observations displaced. The record also
    carries ``budget_filled``, because a cap tight enough to leave the budget
    short changes what "at the same budget" means in the gate's wording, and that
    has to be visible rather than inferred.
    """
    caps = CONCENTRATION_CAPS if caps is None else caps
    quota = {name: cap_entries(budget, share) for name, share in caps.items()}
    counts: dict[str, dict[Any, int]] = {name: {} for name in caps}

    admitted: list[int] = []
    displaced: list[int] = []
    displaced_by: dict[str, list[int]] = {name: [] for name in caps}

    for oid in ranked_obs_ids:
        if len(admitted) >= budget:
            displaced.append(oid)
            continue

        # Every cap that would block this entry, not just the first one found.
        # Stopping at the first would make a cap look inert when it was simply
        # never reached: an entry blocked by both its station and its transmitter
        # would be attributed to whichever cap the loop happened to check first,
        # and the other would report zero displacements as though it had never
        # bound on anything.
        blocking = [
            name
            for name in caps
            if counts[name].get(
                entity_of.get(name, {}).get(oid, ("__unknown__", oid)), 0
            )
            >= quota[name]
        ]

        if not blocking:
            admitted.append(oid)
            for name in caps:
                value = entity_of.get(name, {}).get(oid, ("__unknown__", oid))
                counts[name][value] = counts[name].get(value, 0) + 1
        else:
            displaced.append(oid)
            for name in blocking:
                displaced_by[name].append(oid)

    # An entry can be blocked by more than one cap, so the per-entity lists
    # overlap and cannot be summed. The distinct count is what "displaced" means.
    displaced_distinct = {oid for v in displaced_by.values() for oid in v}
    record = {
        "caps": {
            name: {
                "share_of_budget": share,
                "entries_at_budget": quota[name],
                "n_displaced": len(displaced_by[name]),
                "displaced_obs_ids": displaced_by[name],
                "reason_code": _CAP_REASON.get(name, "DISPLACED_STATION_CAP"),
                "bound": len(displaced_by[name]) > 0,
            }
            for name, share in caps.items()
        },
        "n_admitted_to_budget": len(admitted),
        "n_displaced_total": len(displaced_distinct),
        "budget": budget,
        "budget_filled": len(admitted) >= min(budget, len(ranked_obs_ids)),
        "binding": len(displaced_distinct) > 0,
    }
    inert = [name for name in caps if not displaced_by[name]]
    if inert:
        record["note"] = (
            f"Displaced nothing at budget {budget} over "
            f"{len(ranked_obs_ids)} ranked observations: {_cap_names(inert)}. Reported "
            f"as inert on this split rather than as exercised. A cap is credited "
            f"with a displacement whenever it would have blocked the entry, even "
            f"if another cap would have blocked it too, so an inert result here is "
            f"a property of the data and not of the order the caps are checked in."
        )
    return admitted + displaced, record


def intraclass_correlation(groups: list[list[float]]) -> dict[str, Any]:
    """One-way random-effects intra-class correlation on unequal group sizes.

    Answers the question a grouped interval exists to answer: how much of the
    variance in an outcome sits between groups rather than within them. Reported
    with the design effect ``1 + (mean group size - 1) * ICC``, which is the
    factor by which a clustered variance exceeds the independence variance.

    This is what showed that the episode grouping was doing nothing on this
    corpus. Episodes hold 1.004 observations each, so there is no within-episode
    variance to partition, while stations hold 2.86 in the chronological test
    partition and carry an ICC of 0.1409 on the conflict indicator.

    A negative ICC is a real result on small samples and means the within-group
    variance exceeds the between-group variance. It is reported as measured and
    clamped only where it feeds the design effect, which cannot sensibly fall
    below 1.

    Which group size goes where, because the two sit adjacent and differ. The ICC's own
    denominator uses the size-adjusted ``n0 = (N - sum(n_i^2)/N) / (k - 1)``; the design
    effect uses the plain mean ``N / k``. That pairing is the conventional one, and both
    sizes are returned so a reader can recompute either way: on the gate-6 chronological
    split they are 2.4857 and 2.4165, a 3 percent difference that moves the design effect
    by under 1 percent. Stated here rather than in the emitted dict because
    ``contracts/queue_receipt.schema.json`` closes the clustering object, and a note is
    not worth a schema version bump.
    """
    populated = [g for g in groups if g]
    n_total = sum(len(g) for g in populated)
    k = len(populated)
    if k < 2 or n_total <= k:
        return {
            "measurable": False,
            "reason": (
                f"An intra-class correlation needs at least 2 populated groups and "
                f"more observations than groups. Got {k} groups over {n_total} "
                f"observations."
            ),
            "icc": None,
            "design_effect": None,
            "n_groups": k,
            "n_observations": n_total,
            "mean_group_size": (n_total / k) if k else None,
        }

    grand = sum(sum(g) for g in populated) / n_total
    ss_between = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in populated)
    ss_within = sum(
        sum((x - sum(g) / len(g)) ** 2 for x in g) for g in populated
    )
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n_total - k)

    # Size-adjusted mean group size for unequal groups, the standard n_0.
    sum_sq = sum(len(g) ** 2 for g in populated)
    n0 = (n_total - sum_sq / n_total) / (k - 1)

    denominator = ms_between + (n0 - 1) * ms_within
    # A zero denominator means both variance components are zero: every group
    # holds the same constant value, so there is no variance to partition and
    # the correlation is undefined rather than perfect. Reported as zero, which
    # gives a design effect of 1 and leaves the interval unchanged.
    icc = 0.0 if denominator == 0 else (ms_between - ms_within) / denominator

    mean_size = n_total / k
    return {
        "measurable": True,
        "reason": None,
        "icc": float(icc),
        "design_effect": float(1 + (mean_size - 1) * max(icc, 0.0)),
        "n_groups": k,
        "n_observations": n_total,
        "mean_group_size": float(mean_size),
        "size_adjusted_mean_group_size": float(n0),
    }

# ---------------------------------------------------------------------------
# Conflict definition (fixed before measuring)
# ---------------------------------------------------------------------------

#: Conflict criteria, each checkable from the snapshot without a human.
#: These are the exact parameters used by ``is_conflict`` and ``classify_reasons``.
#: Do not change them after ``scripts/run_queue.py`` has been run.
#:
#: That includes the ``description`` strings, and it was tested on 2026-08-22. A scan of
#: judge-facing prose found three field names inside these sentences: ``image_corridor``,
#: ``offset_at_bound`` and ``flat_row_frac``. Every other leak it found was rewritten. These
#: three were left exactly as they are, because this block is what ``fixed_before_measuring``
#: is a claim about. The console prints that flag, the pre-registration rests on it, and a
#: reader who diffed a description against an earlier copy and found different words would be
#: right to read the definition as having moved after the results were seen. Tidier prose is
#: not worth putting a doubt next to the one property this project is built on. The field
#: names stay; they are the exact keys the thresholds below are measured from, so a reader who
#: wants to check a criterion can.
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


#: The verdict words, as clauses rather than as tokens.
#:
#: The replay conclusion read "Episode grouping says queue_better (survives correction:
#: False)", which puts a snake_case verdict and a JSON boolean inside an English sentence
#: on a page a reviewer reads. The words are unchanged in the fields beside the note, which
#: is where a machine reads them; only the sentence is written out.
#:
#: The correction is named once, at the end, rather than after each grouping. A first draft
#: attached it to both and produced "and that does not survive it" before anything called
#: "it" had been mentioned, and attached a survival clause to a direction that was never
#: established in the first place. Every branch below was read out loud before it shipped.
_DIRECTION_PHRASE: dict[str, str] = {
    "queue_better": "did better",
    "baseline_better": "did worse",
    "not_established": "was not separated from the baseline",
    # Two spellings reach here for the same state: the receipt writes "not_established"
    # and the replay comparison writes "indistinguishable". Both are mapped rather than
    # left to the fallback, because "came back indistinguishable" is a token in a sentence
    # and the whole point of this map is that there are none.
    "indistinguishable": "was not separated from the baseline",
}


def _direction_phrase(direction: str) -> str:
    return _DIRECTION_PHRASE.get(direction, f"came back {direction}")


def _correction_sentence(episode_survives: bool, station_survives: bool) -> str:
    """Which of the two groupings survived, as a sentence rather than two booleans."""
    if episode_survives and station_survives:
        return "Both survive the multiplicity correction"
    if not episode_survives and not station_survives:
        return "Neither survives the multiplicity correction"
    held, dropped = (
        ("episode", "station") if episode_survives else ("station", "episode")
    )
    return (
        f"The {held} grouping survives the multiplicity correction and the "
        f"{dropped} grouping does not"
    )


def combine_replays(
    replay_episode: dict[str, Any],
    replay_station: dict[str, Any],
) -> dict[str, Any]:
    """One conclusion per baseline, requiring both groupings to agree.

    The same principle the C2 pre-registration fixed for the gate's own interval,
    applied to the baseline comparisons: where two defensible groupings are
    available, the conservative reading governs. A comparison is claimed only when
    the Bonferroni-widened interval excludes the null under **both** the episode
    and the station resample. Claiming a comparison that survives under whichever
    grouping happens to support it is the same failure as quoting whichever
    interval clears the threshold.

    A disagreement between the two groupings is not discarded. It is reported as
    ``not_established`` with both directions named, because "the finer grouping
    said yes and the coarser said no" is a real state and folding it into either
    answer hides it.
    """
    if not (replay_episode.get("measurable") and replay_station.get("measurable")):
        return {
            "measurable": False,
            "reason": (
                "A combined conclusion needs both groupings measured. Episode: "
                f"{replay_episode.get('reason') or 'measured'}. Station: "
                f"{replay_station.get('reason') or 'measured'}."
            ),
            "baselines": {},
        }

    ep = replay_episode["comparisons"]
    st = replay_station["comparisons"]
    baselines: dict[str, Any] = {}
    for name in sorted(set(ep) | set(st)):
        e, s = ep.get(name), st.get(name)
        if e is None or s is None:
            baselines[name] = {
                "claim": "not_measurable",
                "reason": (
                    f"Baseline {name!r} was compared under only one grouping, so "
                    f"the two cannot be required to agree."
                ),
                "direction_episode": e["direction"] if e else None,
                "direction_station": s["direction"] if s else None,
            }
            continue

        both_survive = bool(e["survives_correction"] and s["survives_correction"])
        agree = e["direction"] == s["direction"]
        if both_survive and agree and e["direction"] == "queue_better":
            claim = "queue_better"
        elif both_survive and agree and e["direction"] == "baseline_better":
            claim = "baseline_better"
        else:
            claim = "not_established"

        baselines[name] = {
            "claim": claim,
            "direction_episode": e["direction"],
            "direction_station": s["direction"],
            "survives_correction_episode": e["survives_correction"],
            "survives_correction_station": s["survives_correction"],
            "diff_point": e["diff_point"],
            "diff_ci_adjusted_episode": e["diff_ci_adjusted"],
            "diff_ci_adjusted_station": s["diff_ci_adjusted"],
            "reason": (
                None
                if claim != "not_established"
                else (
                    f"Not claimed. Grouped by pass episode the queue "
                    f"{_direction_phrase(e['direction'])}; grouped by ground "
                    f"station it {_direction_phrase(s['direction'])}. "
                    + _correction_sentence(
                        bool(e["survives_correction"]),
                        bool(s["survives_correction"]),
                    )
                    + ", and a comparison is claimed only when both groupings "
                    "survive it and agree."
                )
            ),
        }

    claimed = [n for n, b in baselines.items() if b["claim"] == "queue_better"]
    lost = [n for n, b in baselines.items() if b["claim"] == "baseline_better"]
    return {
        "measurable": True,
        "reason": None,
        "baselines": baselines,
        "n_baselines": len(baselines),
        "n_beaten_under_both_groupings": len(claimed),
        "beaten": claimed,
        "lost_to": lost,
        "rule": (
            "A baseline counts as beaten only when the Bonferroni-widened interval "
            "excludes zero under both the episode and the station resample, and "
            "both groupings agree on the direction. Where they disagree the "
            "comparison is reported as not established with both directions named, "
            "because a disagreement between two defensible groupings is a real "
            "state rather than a reason to pick one."
        ),
    }


def verdict_from_interval(
    lo: float,
    hi: float,
    threshold: float,
    point_in_ci: bool = True,
) -> tuple[str, str]:
    """The gate 6 decision rule, in one place.

    Extracted so the same rule decides a single-grouping interval and a combined
    one. A rule written twice is a rule that will eventually disagree with itself,
    and the two copies would be exactly where a verdict quietly diverged from its
    interval.
    """
    if not point_in_ci:
        return "inconsistent_interval", "NOT_MEASURABLE"
    if lo > threshold:
        return "above_threshold", "PASSED"
    if hi < threshold:
        # The whole interval sits below the bar. This is the only shape that
        # refutes the gate rather than failing to establish it.
        return "below_threshold", "FAILED"
    # The interval contains the threshold. Gate 5's precedent, applied in both
    # directions: an interval spanning the bar neither establishes the claim nor
    # refutes it, whichever side the point estimate falls on.
    return "spans_threshold", "NOT_ESTABLISHED"


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
        # The draw's budget holds the real measurement's selectivity, budget / n.
        # This was round(budget / n * drawn_n), and round lets the realised
        # selectivity drift below it on draws whose product falls under .5. A draw
        # with a smaller budget than its share has a higher ceiling than the real
        # measurement, because the best any ordering can score is
        # drawn_n / drawn_budget once conflicts are scarcer than the budget. Under
        # round, 7.92% of chronological draws exceeded 87/50 = 1.740 and the
        # published 95% upper bound was 93/53 = 1.7547, above the ceiling it was
        # being read against.
        #
        # Ceiling, not round, and in integers. math.ceil(budget / n * drawn_n) is
        # 51 at drawn_n == n, because that product is 50.000000000000007 in binary
        # floating point, which would make a draw identical to the real population
        # less selective than it. -(-a // b) is the exact ceiling of a / b.
        drawn_budget = max(1, min(drawn_n, -(-budget * drawn_n // n)))
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

    direction, verdict = verdict_from_interval(lo, hi, threshold, point_in_ci)

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


def baseline_offset_magnitude(
    obs_ids: list[int],
    offset_safe: dict[int, float],
) -> list[int]:
    """Offset-magnitude ordering: descending abs(fitted_offset_ppm), at-bound zeroed.

    This is the single feature that STALE_CATALOGUE_FREQ thresholds, and that
    criterion accounts for most realised conflicts, so a one-line sort on it is
    the ordering a sceptical reader reaches for first: if the composite score
    cannot beat it, the other three terms bought nothing on this split. The
    at-bound zeroing matches the ``offset_safe`` signal the score itself uses, so
    the two differ only in the weighting, not in the quantity.

    Observations with no usable offset sort to the bottom at zero.
    """

    def _mag(oid: int) -> float:
        v = offset_safe.get(oid)
        if v is None or not math.isfinite(v):
            return 0.0
        return float(v)

    return sorted(obs_ids, key=lambda oid: (-_mag(oid), oid))


# ---------------------------------------------------------------------------
# Per-split gate 6 measurement
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Active-selection replay against every baseline (unit C4)
# ---------------------------------------------------------------------------


#: The comparison family for one split: the queue against each of five baselines.
#: Bonferroni widens over this, because a queue tested against five orderings and
#: reported on whichever it beat would be held to no standard at all.
#: The fifth is ``offset_magnitude``, added after a review pointed out that the
#: first four (random, FIFO, model confidence, physics classifier) all miss the
#: obvious one: a plain sort on the quantity most realised conflicts are defined
#: from. Adding it widens every interval in the family, including the ones the
#: queue already wins.
_N_ORDERING_COMPARISONS = 5


def compare_orderings(
    orderings: dict[str, list[int]],
    conflict_flags: dict[int, bool],
    group_of: dict[int, str],
    budget: int,
    *,
    queue_name: str = "queue",
    n_boot: int = 4000,
    seed: int = 42,
    n_comparisons: int = _N_ORDERING_COMPARISONS,
) -> dict[str, Any]:
    """Replay every ordering over the same resampled populations, pairwise.

    Gate 6 asks only whether the queue beats random. A queue that beats random and
    loses to FIFO has not earned a reviewer's attention, because FIFO is what a
    reviewer already does, so each baseline gets the same budget and the same
    conflict definition.

    The comparisons are **paired**. One draw of groups produces one synthetic
    population, and every ordering is scored on that same population before the
    next draw. Drawing separately per ordering would compare two orderings across
    two different populations and attribute the difference between the populations
    to the difference between the orderings.

    Each ordering is re-sorted within the draw by its own rank, so an ordering's
    top-k in a resampled population is what that ordering would actually have
    surfaced there. Reusing the original top-k would score every ordering on rows
    the draw may not contain.

    Ratios are queue over baseline, so 1.0 is the null and above 1.0 favours the
    queue. Intervals are reported nominally and Bonferroni-widened over
    ``n_comparisons``, following the convention
    :func:`fusion.grouped_bootstrap_statistic_difference` set in Wave B, and
    survival is tested in both directions: a corrected interval lying entirely
    below 1.0 is a measured loss and has to be representable, which is the defect
    that left an ablation rule's DROP branch as dead code.
    """
    if queue_name not in orderings:
        raise KeyError(
            f"The queue ordering {queue_name!r} must be present among "
            f"{sorted(orderings)}, because every ratio is taken over it."
        )

    population = list(orderings[queue_name])
    n = len(population)
    budget = min(budget, n)
    if n == 0 or budget == 0:
        return {
            "measurable": False,
            "reason": (
                f"No population to replay: {n} ranked observations at budget "
                f"{budget}."
            ),
            "orderings": {},
            "comparisons": {},
        }

    for name, order in orderings.items():
        if set(order) != set(population):
            raise ValueError(
                f"Ordering {name!r} covers a different set of observations than "
                f"{queue_name!r}. Every ordering must rank the same population, "
                f"or the budgets are not comparable: "
                f"{len(set(order) ^ set(population))} differ."
            )

    rank_of = {
        name: {oid: i for i, oid in enumerate(order)}
        for name, order in orderings.items()
    }
    total_conflicts = sum(1 for oid in population if conflict_flags.get(oid, False))
    if total_conflicts == 0:
        return {
            "measurable": False,
            "reason": (
                f"No actionable conflicts among {n} ranked observations, so every "
                f"ordering finds zero and no ordering can be distinguished from "
                f"another."
            ),
            "orderings": {},
            "comparisons": {},
        }

    random_expect = total_conflicts / n * budget

    def _found(order: list[int], k: int) -> int:
        return sum(1 for oid in order[:k] if conflict_flags.get(oid, False))

    point_counts = {name: _found(order, budget) for name, order in orderings.items()}
    point_lift = {
        name: found / random_expect for name, found in point_counts.items()
    }

    # Grouped, paired resampling.
    group_to_obs: dict[str, list[int]] = {}
    for oid in population:
        group_to_obs.setdefault(group_of[oid], []).append(oid)
    groups = sorted(group_to_obs)
    rng = np.random.default_rng(seed)
    drawn_lifts: dict[str, list[float]] = {name: [] for name in orderings}
    #: Difference in conflicts found at the same budget, queue minus baseline.
    #: This is the tested statistic: it is defined in every draw, including the
    #: draws where a baseline finds nothing, and its null is exactly 0.
    drawn_diffs: dict[str, list[float]] = {
        name: [] for name in orderings if name != queue_name
    }
    #: The same comparison on a ratio scale, for readers who want "how many
    #: times". Both terms carry a +0.5 continuity correction in every draw, not
    #: only in the draws where the denominator is zero, because a correction
    #: applied selectively changes the estimator between draws.
    drawn_ratios: dict[str, list[float]] = {
        name: [] for name in orderings if name != queue_name
    }
    n_degenerate = 0

    for _ in range(n_boot):
        drawn_groups = rng.choice(groups, size=len(groups), replace=True)
        pool: list[int] = []
        for g in drawn_groups:
            pool.extend(group_to_obs[g])
        drawn_n = len(pool)
        if drawn_n == 0:
            n_degenerate += 1
            continue
        drawn_conflicts = sum(1 for oid in pool if conflict_flags.get(oid, False))
        if drawn_conflicts == 0:
            # No conflicts drawn, so every ordering finds zero and the ratio has
            # no denominator. Counted, not silently skipped.
            n_degenerate += 1
            continue
        # The draw's budget holds the real measurement's selectivity, budget / n.
        # This was round(budget / n * drawn_n), and round lets the realised
        # selectivity drift below it on draws whose product falls under .5. A draw
        # with a smaller budget than its share has a higher ceiling than the real
        # measurement, because the best any ordering can score is
        # drawn_n / drawn_budget once conflicts are scarcer than the budget. Under
        # round, 7.92% of chronological draws exceeded 87/50 = 1.740 and the
        # published 95% upper bound was 93/53 = 1.7547, above the ceiling it was
        # being read against.
        #
        # Ceiling, not round, and in integers. math.ceil(budget / n * drawn_n) is
        # 51 at drawn_n == n, because that product is 50.000000000000007 in binary
        # floating point, which would make a draw identical to the real population
        # less selective than it. -(-a // b) is the exact ceiling of a / b.
        drawn_budget = max(1, min(drawn_n, -(-budget * drawn_n // n)))
        drawn_random = drawn_conflicts / drawn_n * drawn_budget

        found: dict[str, int] = {}
        for name in orderings:
            # The rank map is bound as a default argument rather than captured, so
            # the key function cannot read a later iteration's ordering.
            ordered = sorted(pool, key=lambda oid, r=rank_of[name]: r[oid])
            found[name] = _found(ordered, drawn_budget)
            drawn_lifts[name].append(found[name] / drawn_random)

        for name in drawn_diffs:
            drawn_diffs[name].append(float(found[queue_name] - found[name]))
            drawn_ratios[name].append(
                (found[queue_name] + 0.5) / (found[name] + 0.5)
            )

    alpha = 0.05 / max(n_comparisons, 1)
    min_effective = max(20, n_boot // 10)

    def _interval(samples: list[float]) -> dict[str, Any]:
        if len(samples) < min_effective:
            return {
                "measurable": False,
                "reason": (
                    f"Only {len(samples)} of {n_boot} resamples produced a finite "
                    f"value, below the {min_effective} required."
                ),
                "ci95": None,
                "ci_adjusted": None,
            }
        lo, hi = np.percentile(samples, [2.5, 97.5])
        lo_a, hi_a = np.percentile(
            samples, [100 * alpha / 2, 100 * (1 - alpha / 2)]
        )
        return {
            "measurable": True,
            "reason": None,
            "ci95": [float(lo), float(hi)],
            "ci_adjusted": [float(lo_a), float(hi_a)],
            "median": float(np.median(samples)),
            "n_effective": len(samples),
        }

    ordering_report = {}
    for name in orderings:
        iv = _interval(drawn_lifts[name])
        ordering_report[name] = {
            "n_conflicts_at_budget": point_counts[name],
            "lift_over_random": point_lift[name],
            "lift_ci95": iv["ci95"],
            "measurable": iv["measurable"],
            "reason": iv["reason"],
        }

    comparisons = {}
    for name in drawn_diffs:
        diff_iv = _interval(drawn_diffs[name])
        ratio_iv = _interval(drawn_ratios[name])
        diff_point = float(point_counts[queue_name] - point_counts[name])
        ratio_point = (point_counts[queue_name] + 0.5) / (point_counts[name] + 0.5)

        if not diff_iv["measurable"]:
            comparisons[name] = {
                "measurable": False,
                "reason": diff_iv["reason"],
                "diff_point": diff_point,
                "diff_ci95": None,
                "diff_ci_adjusted": None,
                "ratio_point": ratio_point,
                "ratio_ci95": None,
                "direction": "unmeasurable",
                "survives_correction": None,
                "n_comparisons": n_comparisons,
            }
            continue

        lo, hi = diff_iv["ci95"]
        lo_a, hi_a = diff_iv["ci_adjusted"]
        # Decided on the difference, whose null is 0 and which is defined in every
        # draw. The ratio is reported alongside on its own scale.
        if lo > 0.0:
            direction = "queue_better"
        elif hi < 0.0:
            direction = "baseline_better"
        else:
            direction = "indistinguishable"
        comparisons[name] = {
            "measurable": True,
            "reason": None,
            "diff_point": diff_point,
            "diff_ci95": [lo, hi],
            "diff_ci_adjusted": [lo_a, hi_a],
            "diff_median": diff_iv["median"],
            "ratio_point": ratio_point,
            "ratio_ci95": ratio_iv["ci95"],
            "ratio_ci_adjusted": ratio_iv["ci_adjusted"],
            "direction": direction,
            # Tested in both directions. A corrected interval entirely below the
            # null is a measured loss to the baseline and must be representable:
            # a one-sided survival test is what left an ablation rule's DROP
            # branch as dead code in Wave B.
            "survives_correction": bool(lo_a > 0.0 or hi_a < 0.0),
            "n_comparisons": n_comparisons,
            "adjusted_confidence": float(1.0 - alpha),
            "n_effective": diff_iv["n_effective"],
            "statistic": (
                "Conflicts found by the queue minus conflicts found by the "
                "baseline, at the same budget, on the same resampled population. "
                "Null 0. The ratio beside it carries a +0.5 continuity correction "
                "on both terms in every draw, so a baseline that finds nothing "
                "does not produce an unbounded value and the estimator does not "
                "change between draws."
            ),
        }

    return {
        "measurable": True,
        "reason": None,
        "queue_name": queue_name,
        "budget": budget,
        "n_population": n,
        "n_total_conflicts": total_conflicts,
        "random_expected_conflicts": float(random_expect),
        "n_groups": len(groups),
        "n_boot": n_boot,
        "n_degenerate_resamples": n_degenerate,
        "seed": seed,
        "orderings": ordering_report,
        "comparisons": comparisons,
        "note": (
            "Every ordering is scored on the same resampled population within each "
            "draw, so the comparisons are paired. Each ordering is re-sorted by its "
            "own rank inside the draw, because an ordering's top-k in a resampled "
            "population is not the same set as its top-k in the original. Ratios "
            "are queue over baseline, corrected by Bonferroni over the four "
            "comparisons reported for this split: the three baseline orderings here "
            "plus gate 6's own queue-against-random test, which is measured "
            "separately but belongs to the same family. Random is not carried as an "
            "ordering because FIFO is observation-id order and would report the same "
            "comparison twice under two names; random enters through its "
            "expectation. Survival is tested in both directions, so a loss to a "
            "baseline is representable."
        ),
    }


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
    "lift_ci95_episode": None,
    "lift_ci95_station": None,
    "governing_interval": None,
    "station_interval_note": None,
    "verdict_episode_only": None,
    "fifo_lift_over_random": None,
    "image_uncertainty_lift_over_random": None,
    "physics_only_lift_over_random": None,
    "offset_magnitude_lift_over_random": None,
    "n_boot": None,
    "n_boot_effective": None,
    "bootstrap_median": None,
    "point_in_ci": None,
    "consistency_note": None,
    "verdict": None,
    "direction": None,
    "n_groups": None,
    "n_station_groups": None,
    "episode_clustering": None,
    "station_clustering": None,
    "uncapped_reference": None,
    "replay_episode": None,
    "replay_station": None,
    "replay_conclusion": None,
}


def _grouped_values(
    obs_ids: list[int],
    flags: dict[int, bool],
    group_of: dict[int, str] | None,
) -> list[list[float]]:
    """Conflict indicators bucketed by group, for an intra-class correlation."""
    if group_of is None:
        return []
    buckets: dict[str, list[float]] = {}
    for oid in obs_ids:
        if oid not in flags:
            continue
        buckets.setdefault(group_of[oid], []).append(1.0 if flags[oid] else 0.0)
    return [buckets[k] for k in sorted(buckets)]


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
    offset_magnitude_order: list[int],
    *,
    station_of: dict[int, str] | None = None,
    n_boot: int = 4000,
    seed: int = 42,
    threshold: float = 1.5,
) -> dict[str, Any]:
    """Gate 6 measurement for one split, under two groupings.

    Returns a per-split result dict matching ``split_gate6_result`` in the schema.
    When the split cannot be measured (zero decisive labels, no conflicts to find,
    too few surviving resamples, or an interval inconsistent with its own point
    estimate), returns a NOT_MEASURABLE result carrying that specific reason.

    Two intervals are reported whenever ``station_of`` is supplied. The pass
    episode is the finer grouping and is what Waves B and C have published. It is
    also nearly inert on this corpus: episodes hold 1.004 observations each, so
    there is no within-episode correlation for the interval to absorb. The
    conflict indicator does cluster by ground station, with an intra-class
    correlation of 0.1409 over the chronological test partition and a design
    effect of 1.262, which is consistent with a shared receiver and a shared
    local-oscillator error persisting across passes.

    The verdict is decided on the union of the two intervals. The pre-registration
    said "the wider one", and the union refines that: a wider interval is not
    necessarily the more conservative one for a one-sided threshold test, because
    it may also be shifted upward. The union is at least as wide as either and is
    conservative in both directions, so it cannot be gamed by preferring whichever
    grouping clears the bar.
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

    # The second grouping. Every episode lies within exactly one station, so a
    # station-clustered resample subsumes the episode one, and the two are
    # combined by union rather than by choosing between them. Fixed in
    # docs/C2_PREREGISTRATION.md before either was computed on the shipped queue.
    station_result = None
    if station_of is not None:
        station_result = compute_lift(
            queue_obs_ids, conflict_flags, station_of,
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

    # Combine the two groupings. The union is conservative in both directions.
    ep_lo, ep_hi = result.ci95
    if station_result is not None and station_result.verdict != "NOT_MEASURABLE":
        st_lo, st_hi = station_result.ci95
        gov_lo, gov_hi = min(ep_lo, st_lo), max(ep_hi, st_hi)
        governing = "union_of_episode_and_station"
        station_ci = [st_lo, st_hi]
        station_groups = station_result.n_groups
        station_note = None
    else:
        gov_lo, gov_hi = ep_lo, ep_hi
        governing = "episode_only"
        station_ci = None
        station_groups = (
            station_result.n_groups if station_result is not None else None
        )
        station_note = (
            station_result.not_measurable_reason
            if station_result is not None
            else "No station grouping was supplied for this split."
        )

    gov_direction, gov_verdict = verdict_from_interval(
        gov_lo, gov_hi, threshold, result.point_in_ci
    )

    return _gate6_result(
        measurable=True,
        verdict=gov_verdict,
        direction=gov_direction,
        not_measurable_reason=None,
        n_queue_examined=eff_budget,
        n_random_conflicts=result.n_random_conflicts,
        n_queue_conflicts=result.n_queue_conflicts,
        lift_point=result.lift_point,
        lift_ci95=[gov_lo, gov_hi],
        lift_ci95_episode=[ep_lo, ep_hi],
        lift_ci95_station=station_ci,
        governing_interval=governing,
        station_interval_note=station_note,
        verdict_episode_only=result.verdict,
        fifo_lift_over_random=_lift_over_random(fifo_order),
        image_uncertainty_lift_over_random=_lift_over_random(image_uncertainty_order),
        physics_only_lift_over_random=_lift_over_random(physics_only_order),
        offset_magnitude_lift_over_random=_lift_over_random(offset_magnitude_order),
        n_boot=n_boot,
        n_boot_effective=result.n_boot_effective,
        n_groups=result.n_groups,
        n_station_groups=station_groups,
        bootstrap_median=result.bootstrap_median,
        point_in_ci=result.point_in_ci,
        consistency_note=result.consistency_note,
        episode_clustering=intraclass_correlation(
            _grouped_values(queue_obs_ids, conflict_flags, episode_of)
        ),
        station_clustering=(
            intraclass_correlation(
                _grouped_values(queue_obs_ids, conflict_flags, station_of)
            )
            if station_of is not None
            else None
        ),
    )
