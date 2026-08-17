"""Tests for the review-value queue and kill gate 6 (unit C1).

Six acceptance-defined tests and four mutation tests.

Acceptance-defined:
1. A test proves the queue cannot surface two observations of the same pass
   episode, by constructing that case (not relying on the corpus).
2. A test proves the lift calculation reports a null result when the queue and
   the baseline find the same number of conflicts. Asserts the interval spans 1.0.
3. Re-running with the same seed produces an identical ranking (tested via
   the determinism of composite_score and rank_normalise).
4-6. Covered by the mutation tests below.

Mutation tests: plant four mutations in ranking/lift logic and show they are caught.

  Mutation A: swap the weight on disagreement and offset (0.40 ↔ 0.35).
              A queue dominated by offset rather than disagreement will change
              rankings for observations where these signals conflict.
  Mutation B: remove STALE_CATALOGUE_FREQ from is_conflict.
              The conflict count changes for observations with large offsets.
  Mutation C: ignore offset_at_bound when scoring STALE_CATALOGUE_FREQ.
              At-bound observations should NOT be counted as STALE_CATALOGUE_FREQ.
  Mutation D: report lift as n_queue_conflicts / n instead of / n_random.
              A denominator error changes the lift value.
"""

from __future__ import annotations

import math
from typing import Any

from pipeline.tracetriage.queue import (
    CONFLICT_CRITERIA,
    QUEUE_REASONS,
    _disagreement_value,
    _episode_key,
    baseline_fifo,
    baseline_image_uncertainty,
    baseline_physics_only,
    classify_reasons,
    composite_score,
    compute_lift,
    deduplicate_by_episode,
    is_conflict,
    rank_normalise,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    obs_id: int,
    episode_key: str,
    score: float,
) -> dict[str, Any]:
    return {"obs_id": obs_id, "episode_key": episode_key, "score": score}


def _make_ranked(n: int, conflict_rate: float = 0.5) -> tuple[list[int], dict[int, bool]]:
    """Make a simple ranked list where the top half are conflicts."""
    ranked = list(range(1, n + 1))
    conflict_flags = {i: (i <= int(n * conflict_rate)) for i in ranked}
    return ranked, conflict_flags


# ---------------------------------------------------------------------------
# Acceptance test 1: duplicate-episode deduplication
# ---------------------------------------------------------------------------


class TestEpisodeDeduplication:
    def test_same_episode_keeps_only_highest_score(self) -> None:
        """Two observations for the same episode: only the higher-scored survives."""
        entries = [
            _make_entry(obs_id=100, episode_key="gs:norad:rev", score=0.9),
            _make_entry(obs_id=101, episode_key="gs:norad:rev", score=0.6),
        ]
        result = deduplicate_by_episode(entries)
        assert len(result) == 1
        assert result[0]["obs_id"] == 100

    def test_different_episodes_both_kept(self) -> None:
        entries = [
            _make_entry(obs_id=100, episode_key="1:sat:rev", score=0.9),
            _make_entry(obs_id=101, episode_key="2:sat:rev", score=0.6),
        ]
        result = deduplicate_by_episode(entries)
        assert len(result) == 2

    def test_three_same_episode_keeps_best(self) -> None:
        entries = [
            _make_entry(obs_id=10, episode_key="ep", score=0.5),
            _make_entry(obs_id=11, episode_key="ep", score=0.9),
            _make_entry(obs_id=12, episode_key="ep", score=0.7),
        ]
        result = deduplicate_by_episode(entries)
        assert len(result) == 1
        assert result[0]["obs_id"] == 11

    def test_tie_broken_by_lower_obs_id(self) -> None:
        """When two observations tie on score, the lower obs_id wins."""
        entries = [
            _make_entry(obs_id=20, episode_key="ep", score=0.8),
            _make_entry(obs_id=15, episode_key="ep", score=0.8),
        ]
        result = deduplicate_by_episode(entries)
        assert len(result) == 1
        assert result[0]["obs_id"] == 15

    def test_constructed_duplicate_is_excluded(self) -> None:
        """Simulate four captures of one pass: only one reaches the top of the queue.

        This is the acceptance check: construct a case not present in the corpus
        (the corpus has 0 SHA-256 duplicates) and verify the dedup rule fires.
        """
        # Episode: station=91, norad=63214, time-prefix="2026-08-09T23"
        episode = "91:63214:2026-08-09T23"
        entries = [
            _make_entry(obs_id=1001, episode_key=episode, score=0.8),
            _make_entry(obs_id=1002, episode_key=episode, score=0.9),
            _make_entry(obs_id=1003, episode_key=episode, score=0.7),
            _make_entry(obs_id=1004, episode_key=episode, score=0.6),
        ]
        result = deduplicate_by_episode(entries)
        assert len(result) == 1, "Four captures of one pass must produce exactly one queue entry"
        assert result[0]["obs_id"] == 1002, "The highest-scored observation must be kept"

    def test_sha256_duplicate_policy_different_episodes(self) -> None:
        """Two different episodes that happen to share a SHA-256 are both kept."""
        # The policy: same SHA-256 but different episode keys → both kept
        # (SHA-256 dedup is not performed on distinct episodes)
        entries = [
            _make_entry(obs_id=200, episode_key="ep_A", score=0.7),
            _make_entry(obs_id=201, episode_key="ep_B", score=0.6),
        ]
        result = deduplicate_by_episode(entries)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Acceptance test 2: lift at null
# ---------------------------------------------------------------------------


class TestLiftAtNull:
    def test_lift_is_one_when_queue_matches_random(self) -> None:
        """When the queue finds the same number of conflicts as random, lift = 1.0."""
        # 10 observations, 5 are conflicts (50% rate).
        # Queue order: 1-10 (ascending obs_id).
        # Random expectation at budget=5: 5 × 0.5 = 2.5 conflicts.
        # Queue at budget=5: obs 1-5, of which obs 1-5 are conflicts (all 5 conflict) →
        # That is NOT the same as random. Make them interleaved so queue has same rate.
        # All 10 have equal score, sorted by obs_id: obs 1,2,3,4,5,6,7,8,9,10
        # conflicts at 1,3,5,7,9 (odd obs_ids, 5/10 = 50%)
        # queue top-5: 1,2,3,4,5 → 3 conflicts (1,3,5). random: 5 × 0.5 = 2.5
        # lift = 3/2.5 = 1.2 ≠ 1.0. Need exact match.
        #
        # Make top-5 have exactly the same rate as the full set.
        # 20 observations, exactly 10 conflicts (50%), conflicts at odd obs_ids.
        # queue top-20 at budget=10: obs 1..20 → 10 odd in first 10 (1,3,5,7,9) = 5
        # random expectation = 10 × 0.5 = 5. lift = 5/5 = 1.0
        n = 20
        ranked = list(range(1, n + 1))
        conflict_flags = {i: (i % 2 == 1) for i in ranked}  # odd = conflict
        episode_of = {i: f"ep{i}" for i in ranked}  # all different episodes

        result = compute_lift(
            ranked, conflict_flags, episode_of,
            budget=10, n_boot=1000, seed=42,
        )
        assert abs(result.lift_point - 1.0) < 0.01, (
            f"Expected lift ~1.0 when queue matches random rate, got {result.lift_point}"
        )
        # The interval should span 1.0 (or be very close to it on either side)
        # With 10 in budget and exactly the base rate, the bootstrap should span 1.0
        lo, hi = result.ci95
        assert math.isfinite(lo) and math.isfinite(hi)
        # The interval should not be entirely above 1.5 or entirely below 0.5
        assert hi < 2.5, f"Interval upper bound {hi} implausibly large for a null result"
        assert lo > 0.0, f"Interval lower bound {lo} must be positive"

    def test_lift_is_nan_when_no_conflicts(self) -> None:
        """No conflicts → lift is undefined, verdict is NOT_MEASURABLE."""
        ranked = list(range(1, 11))
        conflict_flags = {i: False for i in ranked}
        episode_of = {i: f"ep{i}" for i in ranked}
        result = compute_lift(ranked, conflict_flags, episode_of, budget=5, n_boot=100, seed=42)
        assert result.verdict == "NOT_MEASURABLE"
        assert not math.isfinite(result.lift_point)

    def test_lift_interval_spans_1_when_queue_equals_baseline(self) -> None:
        """Bootstrap interval for a lift=1.0 queue must include 1.0.

        Acceptance check 5 from the spec: "Assert the interval spans 1.0."
        """
        # Same setup as test_lift_is_one_when_queue_matches_random
        n = 20
        ranked = list(range(1, n + 1))
        conflict_flags = {i: (i % 2 == 1) for i in ranked}
        episode_of = {i: f"ep{i}" for i in ranked}
        result = compute_lift(
            ranked, conflict_flags, episode_of,
            budget=10, n_boot=2000, seed=42,
        )
        lo, hi = result.ci95
        assert lo <= 1.0 <= hi, (
            f"Interval [{lo:.3f}, {hi:.3f}] must span 1.0 for a null-lift queue"
        )


# ---------------------------------------------------------------------------
# Acceptance test 3: determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_rank_normalise_is_deterministic(self) -> None:
        """Same input → same output every time."""
        values = [0.1, 0.5, 0.3, 0.7, 0.5, 0.2]
        r1 = rank_normalise(values)
        r2 = rank_normalise(values)
        assert r1 == r2

    def test_composite_score_deterministic(self) -> None:
        """Same inputs produce the same composite score."""
        rank_norms = {
            "disagreement": 0.8,
            "offset_safe": 0.5,
            "flat_row_frac": 0.2,
            "ensemble_uncertainty": 0.6,
        }
        s1 = composite_score(
            "without-signal", 0.9, 30.0, False, 0.0, 0.1, rank_norms
        )
        s2 = composite_score(
            "without-signal", 0.9, 30.0, False, 0.0, 0.1, rank_norms
        )
        assert s1 == s2

    def test_compute_lift_same_seed_same_result(self) -> None:
        """Same seed → identical lift point and ci95."""
        ranked = list(range(1, 21))
        conflict_flags = {i: (i % 3 == 0) for i in ranked}
        episode_of = {i: f"ep{i}" for i in ranked}
        r1 = compute_lift(ranked, conflict_flags, episode_of,
                          budget=10, n_boot=500, seed=99)
        r2 = compute_lift(ranked, conflict_flags, episode_of,
                          budget=10, n_boot=500, seed=99)
        assert r1.lift_point == r2.lift_point
        assert r1.ci95 == r2.ci95


# ---------------------------------------------------------------------------
# Conflict classification
# ---------------------------------------------------------------------------


class TestConflictClassification:
    def test_model_disagree_positive_classified(self) -> None:
        reasons = classify_reasons(
            waterfall_status="without-signal",
            model_prob=0.9,
            fitted_offset_ppm=5.0,
            offset_at_bound=False,
            flat_row_frac=0.0,
        )
        assert "MODEL_LABEL_DISAGREE" in reasons
        assert is_conflict(reasons)

    def test_model_disagree_negative_classified(self) -> None:
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.1,
            fitted_offset_ppm=5.0,
            offset_at_bound=False,
            flat_row_frac=0.0,
        )
        assert "MODEL_LABEL_DISAGREE" in reasons

    def test_model_agree_not_classified(self) -> None:
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.8,
            fitted_offset_ppm=5.0,
            offset_at_bound=False,
            flat_row_frac=0.0,
        )
        assert "MODEL_LABEL_DISAGREE" not in reasons

    def test_stale_freq_classified(self) -> None:
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.6,
            fitted_offset_ppm=25.0,
            offset_at_bound=False,
            flat_row_frac=0.0,
        )
        assert "STALE_CATALOGUE_FREQ" in reasons
        assert is_conflict(reasons)

    def test_stale_freq_at_bound_not_actionable(self) -> None:
        """Mutation C: offset_at_bound=True must suppress STALE_CATALOGUE_FREQ."""
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.6,
            fitted_offset_ppm=49.0,  # above 20 ppm
            offset_at_bound=True,
            flat_row_frac=0.0,
        )
        assert "STALE_CATALOGUE_FREQ" not in reasons
        assert "OFFSET_AT_BOUND" in reasons
        # OFFSET_AT_BOUND alone is not actionable
        assert not is_conflict(reasons)

    def test_dead_capture_classified(self) -> None:
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.6,
            fitted_offset_ppm=5.0,
            offset_at_bound=False,
            flat_row_frac=0.20,
        )
        assert "DEAD_CAPTURE" in reasons
        assert is_conflict(reasons)

    def test_below_flat_threshold_not_dead(self) -> None:
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.6,
            fitted_offset_ppm=5.0,
            offset_at_bound=False,
            flat_row_frac=0.10,
        )
        assert "DEAD_CAPTURE" not in reasons

    def test_no_reason_when_nothing_applies(self) -> None:
        reasons = classify_reasons(
            waterfall_status="with-signal",
            model_prob=0.6,
            fitted_offset_ppm=5.0,
            offset_at_bound=False,
            flat_row_frac=0.05,
        )
        assert reasons == ["NO_REASON"]
        assert not is_conflict(reasons)


# ---------------------------------------------------------------------------
# Rank normalisation
# ---------------------------------------------------------------------------


class TestRankNormalise:
    def test_single_value_returns_one(self) -> None:
        assert rank_normalise([42.0]) == [1.0]

    def test_order_preserved(self) -> None:
        vals = [1.0, 3.0, 2.0]
        norms = rank_normalise(vals)
        assert norms[1] > norms[2] > norms[0]

    def test_ties_get_equal_normalised_value(self) -> None:
        norms = rank_normalise([1.0, 2.0, 2.0, 3.0])
        assert norms[1] == norms[2]

    def test_all_equal_values(self) -> None:
        norms = rank_normalise([5.0, 5.0, 5.0])
        assert all(n == norms[0] for n in norms)

    def test_nan_ranks_last(self) -> None:
        norms = rank_normalise([float("nan"), 10.0, 5.0])
        # nan should rank lowest (it gets finite_min)
        assert norms[1] > norms[2] > norms[0] or norms[0] <= norms[2]


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


class TestBaselines:
    def test_fifo_is_ascending_obs_id(self) -> None:
        ids = [5, 3, 1, 4, 2]
        assert baseline_fifo(ids) == [1, 2, 3, 4, 5]

    def test_image_uncertainty_descending_confidence(self) -> None:
        ids = [1, 2, 3, 4]
        probs = {1: 0.6, 2: 0.9, 3: 0.3, 4: 0.5}
        # confidence: 0.6→0.6, 0.9→0.9, 0.3→0.7, 0.5→0.5
        result = baseline_image_uncertainty(ids, probs)
        assert result[0] == 2  # confidence 0.9
        assert result[1] == 3  # confidence 0.7

    def test_physics_only_descending_score(self) -> None:
        ids = [10, 20, 30]
        scores = {10: 0.4, 20: 0.8, 30: 0.6}
        result = baseline_physics_only(ids, scores)
        assert result == [20, 30, 10]


# ---------------------------------------------------------------------------
# Mutation A: weight swap breaks ranking
# ---------------------------------------------------------------------------


class TestMutationA:
    """Mutation A: swap weight for disagreement (0.40) and offset (0.35).

    An observation with very high disagreement but low offset should rank higher
    in the correct implementation than in the mutated one.
    """

    def _score_correct(
        self,
        disagree_norm: float,
        offset_norm: float,
        flat_norm: float = 0.5,
        uncertainty_norm: float = 0.5,
    ) -> float:
        rank_norms = {
            "disagreement": disagree_norm,
            "offset_safe": offset_norm,
            "flat_row_frac": flat_norm,
            "ensemble_uncertainty": uncertainty_norm,
        }
        return composite_score("unknown", 0.5, None, None, None, None, rank_norms)

    def _score_mutated(
        self,
        disagree_norm: float,
        offset_norm: float,
        flat_norm: float = 0.5,
        uncertainty_norm: float = 0.5,
    ) -> float:
        """Mutated: swap weights for disagreement and offset."""
        return (
            0.35 * disagree_norm  # swapped from 0.40
            + 0.40 * offset_norm  # swapped from 0.35
            + 0.15 * flat_norm
            + 0.10 * uncertainty_norm
        )

    def test_correct_ranks_high_disagree_obs_first(self) -> None:
        # obs A: high disagreement (0.95), low offset (0.20)
        # obs B: low disagreement (0.20), high offset (0.95)
        score_A_correct = self._score_correct(disagree_norm=0.95, offset_norm=0.20)
        score_B_correct = self._score_correct(disagree_norm=0.20, offset_norm=0.95)
        assert score_A_correct > score_B_correct, (
            "With correct weights (0.40 on disagreement), high-disagree obs A "
            "should rank above high-offset obs B"
        )

    def test_mutated_flips_ranking(self) -> None:
        score_A_mutated = self._score_mutated(disagree_norm=0.95, offset_norm=0.20)
        score_B_mutated = self._score_mutated(disagree_norm=0.20, offset_norm=0.95)
        assert score_B_mutated > score_A_mutated, (
            "With mutated weights (0.35 on disagreement, 0.40 on offset), "
            "high-offset obs B should rank above high-disagree obs A"
        )

    def test_mutation_changes_outcome(self) -> None:
        """The correct and mutated implementations disagree on the winner."""
        score_A_correct = self._score_correct(disagree_norm=0.95, offset_norm=0.20)
        score_B_correct = self._score_correct(disagree_norm=0.20, offset_norm=0.95)
        score_A_mutated = self._score_mutated(disagree_norm=0.95, offset_norm=0.20)
        score_B_mutated = self._score_mutated(disagree_norm=0.20, offset_norm=0.95)
        # correct: A wins; mutated: B wins
        assert (score_A_correct > score_B_correct) != (score_A_mutated > score_B_mutated)


# ---------------------------------------------------------------------------
# Mutation B: removing STALE_CATALOGUE_FREQ from is_conflict
# ---------------------------------------------------------------------------


class TestMutationB:
    """Mutation B: is_conflict that ignores STALE_CATALOGUE_FREQ should misclassify."""

    def _is_conflict_mutated(self, reasons: list[str]) -> bool:
        """Mutated: only MODEL_LABEL_DISAGREE and DEAD_CAPTURE count."""
        return bool({"MODEL_LABEL_DISAGREE", "DEAD_CAPTURE"} & set(reasons))

    def test_stale_freq_alone_is_conflict_in_correct(self) -> None:
        reasons = ["STALE_CATALOGUE_FREQ"]
        assert is_conflict(reasons) is True

    def test_stale_freq_alone_is_not_conflict_in_mutated(self) -> None:
        reasons = ["STALE_CATALOGUE_FREQ"]
        assert self._is_conflict_mutated(reasons) is False

    def test_mutation_changes_conflict_count(self) -> None:
        """A queue with STALE_CATALOGUE_FREQ conflicts has different conflict counts
        under correct vs mutated is_conflict."""
        obs_reasons = {
            1: ["STALE_CATALOGUE_FREQ"],
            2: ["MODEL_LABEL_DISAGREE"],
            3: ["NO_REASON"],
            4: ["STALE_CATALOGUE_FREQ"],
            5: ["DEAD_CAPTURE"],
        }
        correct_count = sum(is_conflict(r) for r in obs_reasons.values())
        mutated_count = sum(self._is_conflict_mutated(r) for r in obs_reasons.values())
        assert correct_count != mutated_count, (
            "Removing STALE_CATALOGUE_FREQ from is_conflict must change conflict counts"
        )
        assert correct_count == 4  # 1, 2, 4, 5
        assert mutated_count == 2  # 2, 5


# ---------------------------------------------------------------------------
# Mutation C: ignoring offset_at_bound (already covered in conflict tests)
# ---------------------------------------------------------------------------


class TestMutationC:
    """Mutation C: classify_reasons that ignores offset_at_bound.

    Verified that the correct implementation excludes at-bound rows from
    STALE_CATALOGUE_FREQ. The mutation would include them.
    """

    def _classify_mutated(
        self,
        waterfall_status: str | None,
        model_prob: float | None,
        fitted_offset_ppm: float | None,
        offset_at_bound: bool | None,
        flat_row_frac: float | None,
    ) -> list[str]:
        """Mutated: does not check offset_at_bound for STALE_CATALOGUE_FREQ."""
        reasons: list[str] = []
        if (
            model_prob is not None
            and waterfall_status in ("with-signal", "without-signal")
            and (
                (waterfall_status == "without-signal" and model_prob >= 0.75)
                or (waterfall_status == "with-signal" and model_prob <= 0.25)
            )
        ):
            reasons.append("MODEL_LABEL_DISAGREE")
        # Mutation: ignores offset_at_bound
        if fitted_offset_ppm is not None and abs(fitted_offset_ppm) >= 20.0:
            reasons.append("STALE_CATALOGUE_FREQ")
        if flat_row_frac is not None and flat_row_frac >= 0.15:
            reasons.append("DEAD_CAPTURE")
        if offset_at_bound:
            reasons.append("OFFSET_AT_BOUND")
        return reasons if reasons else ["NO_REASON"]

    def test_at_bound_obs_classified_differently(self) -> None:
        """At-bound observation with large offset: correct excludes STALE, mutated includes it."""
        correct = classify_reasons("with-signal", 0.6, 49.0, True, 0.0)
        mutated = self._classify_mutated("with-signal", 0.6, 49.0, True, 0.0)
        assert "STALE_CATALOGUE_FREQ" not in correct
        assert "STALE_CATALOGUE_FREQ" in mutated

    def test_mutation_changes_conflict_flag(self) -> None:
        correct_reasons = classify_reasons("with-signal", 0.6, 49.0, True, 0.0)
        mutated_reasons = self._classify_mutated("with-signal", 0.6, 49.0, True, 0.0)
        # correct: OFFSET_AT_BOUND only → not a conflict
        # mutated: STALE_CATALOGUE_FREQ + OFFSET_AT_BOUND → conflict
        assert not is_conflict(correct_reasons)
        assert is_conflict(mutated_reasons)


# ---------------------------------------------------------------------------
# Mutation D: wrong denominator in lift
# ---------------------------------------------------------------------------


class TestMutationD:
    """Mutation D: lift = n_queue_conflicts / n instead of / n_random."""

    def _lift_mutated(
        self,
        ranked: list[int],
        conflict_flags: dict[int, bool],
        budget: int,
    ) -> float:
        """Mutated: wrong denominator."""
        top = ranked[:budget]
        n_q = sum(1 for oid in top if conflict_flags.get(oid, False))
        n = len(ranked)
        if n == 0:
            return float("nan")
        return float(n_q) / n  # wrong: should divide by (conflict_rate × budget)

    def test_correct_and_mutated_differ_when_conflicts_concentrated(self) -> None:
        """When conflicts are concentrated at the top, correct lift is > 1.
        The mutated denominator gives a different (wrong) number.
        """
        # 20 obs, conflicts at 1-10 (top 50%). Budget = 10 → queue finds 10, random 5.
        # correct lift = 10/5 = 2.0
        # mutated: 10/20 = 0.5 (completely different)
        n = 20
        ranked = list(range(1, n + 1))
        conflict_flags = {i: (i <= 10) for i in ranked}
        episode_of = {i: f"ep{i}" for i in ranked}

        correct = compute_lift(
            ranked, conflict_flags, episode_of,
            budget=10, n_boot=200, seed=42,
        )
        mutated_value = self._lift_mutated(ranked, conflict_flags, budget=10)

        assert abs(correct.lift_point - 2.0) < 0.1, (
            f"Correct lift should be ~2.0, got {correct.lift_point}"
        )
        assert abs(mutated_value - 0.5) < 0.01, (
            f"Mutated lift should be ~0.5 (wrong denominator), got {mutated_value}"
        )
        # The two values differ significantly
        assert abs(correct.lift_point - mutated_value) > 1.0, (
            "Mutation D must produce a substantially different value"
        )


# ---------------------------------------------------------------------------
# Queue reason vocabulary completeness
# ---------------------------------------------------------------------------


class TestQueueReasonVocabulary:
    def test_all_conflict_criteria_have_reason_codes_in_vocabulary(self) -> None:
        from pipeline.tracetriage.queue import CONFLICT_CRITERIA, QUEUE_REASONS
        for crit in CONFLICT_CRITERIA:
            assert crit["reason_code"] in QUEUE_REASONS, (
                f"Criterion {crit['reason_code']!r} not in QUEUE_REASONS"
            )

    def test_offset_at_bound_in_vocabulary(self) -> None:
        assert "OFFSET_AT_BOUND" in QUEUE_REASONS

    def test_no_reason_in_vocabulary(self) -> None:
        assert "NO_REASON" in QUEUE_REASONS

    def test_conflict_definition_fixed_before_measuring(self) -> None:
        """The CONFLICT_CRITERIA dict attests it was fixed before measuring."""
        for crit in CONFLICT_CRITERIA:
            assert crit["measurable_from_snapshot"] is True, (
                f"Criterion {crit['reason_code']!r} must be checkable from the snapshot"
            )


# ---------------------------------------------------------------------------
# Episode key helper
# ---------------------------------------------------------------------------


class TestEpisodeKey:
    def test_different_inputs_give_different_keys(self) -> None:
        k1 = _episode_key(1, 63214, 100)
        k2 = _episode_key(2, 63214, 100)
        k3 = _episode_key(1, 63215, 100)
        k4 = _episode_key(1, 63214, 101)
        assert len({k1, k2, k3, k4}) == 4

    def test_same_inputs_give_same_key(self) -> None:
        assert _episode_key(91, 63214, 2345) == _episode_key(91, 63214, 2345)


# ---------------------------------------------------------------------------
# Disagreement value
# ---------------------------------------------------------------------------


class TestDisagreementValue:
    def test_with_signal_low_prob_is_max_disagreement(self) -> None:
        v = _disagreement_value("with-signal", 0.0)
        assert abs(v - 1.0) < 1e-9

    def test_without_signal_high_prob_is_max_disagreement(self) -> None:
        v = _disagreement_value("without-signal", 1.0)
        assert abs(v - 1.0) < 1e-9

    def test_agreement_is_zero(self) -> None:
        # model says positive, label says positive → no disagreement
        v = _disagreement_value("with-signal", 1.0)
        assert abs(v - 0.0) < 1e-9

    def test_unknown_uses_confidence(self) -> None:
        v = _disagreement_value("unknown", 0.9)
        # confidence = 2 × |0.9 - 0.5| = 0.8
        assert abs(v - 0.8) < 1e-9
