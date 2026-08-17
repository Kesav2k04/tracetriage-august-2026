"""Tests for selective prediction (B4) and out-of-distribution scoring (B5).

The claims worth testing here are the ones that make a reported guarantee mean
something:

* abstaining on everything must not count as holding an error ceiling;
* a threshold must be chosen on calibration and judged on test, not swept on test;
* "held" must use the interval's upper end, not the point estimate;
* a novelty threshold must come from the training distribution rather than from a
  constant;
* a novelty flag that does not separate errors must be reported as uninformative.

All synthetic. A guarantee that only holds on one snapshot is not a guarantee.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.tracetriage.ood import (
    NOVELTY_FEATURES,
    OodDetector,
    risk_by_novelty,
)
from pipeline.tracetriage.selective import (
    ABSTAIN_REASONS,
    AbstentionPolicy,
    area_under_risk_coverage,
    confidence,
    risk_coverage_curve,
    threshold_for_risk_ceiling,
    verify_ceiling,
)


def _scored(n: int, separation: float, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, size=n)
    p = np.clip(
        np.where(y == 1, 0.5 + separation, 0.5 - separation) + rng.normal(0, 0.2, size=n),
        0.01, 0.99,
    )
    groups = np.array([f"ep{i // 4}" for i in range(n)])
    return p, y, groups


class TestConfidence:
    def test_a_confident_negative_counts_as_confident(self) -> None:
        """Treating only high probabilities as confident would make the queue one-sided."""
        assert confidence(np.array([0.02]))[0] == pytest.approx(0.98)
        assert confidence(np.array([0.98]))[0] == pytest.approx(0.98)
        assert confidence(np.array([0.5]))[0] == pytest.approx(0.5)


class TestRiskCoverage:
    def test_risk_falls_as_coverage_falls(self) -> None:
        p, y, g = _scored(600, 0.25, seed=1)
        curve = risk_coverage_curve(p, y, g)
        usable = [pt for pt in curve if pt["risk"] is not None and pt["n_kept"] >= 30]
        assert usable[0]["coverage"] > usable[-1]["coverage"]
        assert usable[0]["risk"] > usable[-1]["risk"], (
            "a model whose confidence means anything must err less on what it keeps"
        )

    def test_every_point_states_its_denominator(self) -> None:
        p, y, g = _scored(80, 0.2)
        for pt in risk_coverage_curve(p, y, g):
            assert "n_kept" in pt and "n_groups_kept" in pt
            if pt["risk"] is None:
                assert pt["n_kept"] == 0

    def test_a_curve_point_that_kept_nothing_has_no_risk(self) -> None:
        p = np.full(20, 0.5)
        y = np.zeros(20, dtype=int)
        curve = risk_coverage_curve(p, y)
        assert curve[-1]["n_kept"] == 0
        assert curve[-1]["risk"] is None, (
            "reporting 0.0 risk for an empty selection would make total abstention the "
            "best-scoring policy"
        )

    def test_aurc_prefers_the_better_ranking(self) -> None:
        good, y, g = _scored(500, 0.3, seed=2)
        rng = np.random.default_rng(3)
        useless = np.clip(rng.uniform(0.01, 0.99, size=len(y)), 0.01, 0.99)
        assert area_under_risk_coverage(
            risk_coverage_curve(good, y, g)
        ) < area_under_risk_coverage(risk_coverage_curve(useless, y, g))


class TestRiskCeiling:
    def test_the_threshold_is_chosen_for_the_most_coverage_that_holds(self) -> None:
        p, y, _ = _scored(400, 0.3, seed=4)
        res = threshold_for_risk_ceiling(p, y, target_risk=0.05)
        assert res["feasible"]
        assert res["calibration_risk"] <= 0.05
        tighter = threshold_for_risk_ceiling(p, y, target_risk=0.02)
        if tighter["feasible"]:
            assert tighter["threshold"] >= res["threshold"], (
                "a stricter ceiling cannot be met at looser confidence"
            )

    def test_an_impossible_ceiling_is_infeasible_not_a_total_abstention(self) -> None:
        """A model with no signal cannot promise 1% error. It must say so."""
        rng = np.random.default_rng(5)
        y = rng.integers(0, 2, size=300)
        p = np.clip(rng.uniform(0.3, 0.7, size=300), 0.01, 0.99)
        res = threshold_for_risk_ceiling(p, y, target_risk=0.01, min_coverage=0.10)
        assert res["feasible"] is False
        assert res["threshold"] is None, (
            "an infeasible ceiling must not be answered with a threshold that keeps "
            "almost nothing"
        )
        assert res["best_calibration_risk"] is not None

    def test_verify_reports_the_test_risk_even_when_it_exceeds_the_target(self) -> None:
        """The generalisation gap is the finding, not something to hide."""
        p, y, g = _scored(400, 0.25, seed=6)
        cal_p, cal_y = p[:200], y[:200]
        chosen = threshold_for_risk_ceiling(cal_p, cal_y, target_risk=0.10)
        assert chosen["feasible"]
        out = verify_ceiling(
            chosen["threshold"], p[200:], y[200:], g[200:], target_risk=0.10, n_boot=500
        )
        assert out["risk"] is not None
        assert "risk_ci95" in out
        assert isinstance(out["held"], bool)

    def test_held_uses_the_upper_interval_not_the_point_estimate(self) -> None:
        """A point estimate under target with a wide interval is not a guarantee."""
        p, y, g = _scored(120, 0.22, seed=7)
        out = verify_ceiling(0.5, p, y, g, target_risk=0.5, n_boot=500)
        assert out["held"] is True, "a target of 0.5 should hold comfortably"
        tight = verify_ceiling(0.5, p, y, g, target_risk=out["risk"] + 1e-9, n_boot=500)
        assert tight["held_at_point_estimate"] is True
        assert tight["held"] is False, (
            "with the target set exactly at the point estimate, half the bootstrap mass "
            "is above it, so the ceiling cannot be claimed"
        )

    def test_keeping_nothing_is_neither_held_nor_failed(self) -> None:
        p = np.full(40, 0.5)
        y = np.zeros(40, dtype=int)
        out = verify_ceiling(0.99, p, y, np.arange(40).astype(str), target_risk=0.05)
        assert out["n_kept"] == 0
        assert out["held"] is None, (
            "if an empty selection counted as held, abstaining on everything would be "
            "the cheapest way to satisfy the gate"
        )


class TestAbstentionPolicy:
    def test_a_hard_state_wins_over_a_confident_score(self) -> None:
        policy = AbstentionPolicy(threshold=0.7)
        out = policy.decide(0.99, {"GEOMETRY_UNREADABLE": True})
        assert out["scored"] is False
        assert out["reason"] == "GEOMETRY_UNREADABLE", (
            "a confident score computed from a measurement that failed is confident "
            "about nothing"
        )

    def test_reason_precedence_is_deterministic(self) -> None:
        policy = AbstentionPolicy(threshold=0.7)
        out = policy.decide(0.51, {"NO_IMAGE": True, "PHYSICS_DEGRADED": True})
        assert out["reason"] == "NO_IMAGE", "the first hard reason in order wins"

    def test_low_confidence_abstains_and_keeps_the_probability_visible(self) -> None:
        policy = AbstentionPolicy(threshold=0.8)
        out = policy.decide(0.55, {})
        assert out["scored"] is False
        assert out["reason"] == "LOW_CONFIDENCE"
        assert out["probability"] == pytest.approx(0.55), (
            "the score is still shown on the evidence card; only the decision is withheld"
        )

    def test_a_confident_clean_observation_is_scored(self) -> None:
        assert AbstentionPolicy(threshold=0.7).decide(0.95, {})["scored"] is True

    def test_every_reason_has_an_explanation(self) -> None:
        policy = AbstentionPolicy(threshold=0.7)
        for reason in ABSTAIN_REASONS:
            out = policy.decide(0.5, {reason: True})
            assert out["explanation"] == ABSTAIN_REASONS[reason]


class TestOodDetector:
    def _rows(self, n: int, seed: int = 0, **override) -> list[dict]:
        rng = np.random.default_rng(seed)
        rows = []
        for i in range(n):
            row = {
                "obs_id": i,
                "max_elevation_deg": float(rng.uniform(20, 60)),
                "pass_duration_s": float(rng.uniform(200, 500)),
                "doppler_swing_hz": float(rng.uniform(12000, 18000)),
                "doppler_rate_max_hz_s": float(rng.uniform(80, 140)),
                "tle_epoch_age_days": float(rng.uniform(0.1, 1.5)),
                "client_family": "satnogs",
                "band": "uhf_70cm",
            }
            row.update(override)
            rows.append(row)
        return rows

    def test_an_unseen_station_is_flagged(self) -> None:
        train = self._rows(120)
        det = OodDetector().fit(train, stations=[1, 2, 3] * 40, transmitters=["tx"] * 120)
        scored = det.score(self._rows(2, seed=9), stations=[1, 99], transmitters=["tx", "tx"])
        assert scored[0]["unseen_station"] is False
        assert scored[1]["unseen_station"] is True
        assert "unseen_station" in scored[1]["novel_axes"]

    def test_the_distance_threshold_comes_from_training(self) -> None:
        """Not a constant. A hardcoded cut-off is how A7's gate 3 became untestable."""
        tight = OodDetector().fit(
            self._rows(200, seed=1), stations=[1] * 200, transmitters=["tx"] * 200
        )
        assert np.isfinite(tight.distance_quantile_99)
        assert tight.distance_quantile_99 > 0
        assert "99%" in tight.summary()["note"]

    def test_about_one_percent_of_training_data_sits_beyond_its_own_quantile(self) -> None:
        train = self._rows(500, seed=2)
        det = OodDetector().fit(train, stations=[1] * 500, transmitters=["tx"] * 500)
        flagged = sum(
            1 for r in det.score(train, [1] * 500, ["tx"] * 500) if r["feature_novelty"]
        )
        assert 0 <= flagged <= 15, (
            f"{flagged} of 500 training rows beyond their own 99th percentile; the "
            "threshold is not being computed from the training distribution"
        )

    def test_a_far_outlier_is_flagged_on_the_feature_axis(self) -> None:
        det = OodDetector().fit(
            self._rows(200, seed=3), stations=[1] * 200, transmitters=["tx"] * 200
        )
        weird = self._rows(1, seed=4)
        weird[0].update(
            max_elevation_deg=2.0, pass_duration_s=15.0,
            doppler_swing_hz=90000.0, doppler_rate_max_hz_s=2000.0,
            tle_epoch_age_days=90.0,
        )
        scored = det.score(weird, stations=[1], transmitters=["tx"])[0]
        assert scored["feature_novelty"] is True
        assert scored["feature_distance"] > det.distance_quantile_99

    def test_a_near_constant_feature_does_not_make_everything_an_outlier(self) -> None:
        """The covariance ridge. Without it a constant column blows up the inverse."""
        train = self._rows(150, seed=5)
        for r in train:
            r["tle_epoch_age_days"] = 1.0  # constant
        det = OodDetector().fit(train, stations=[1] * 150, transmitters=["tx"] * 150)
        assert det.degraded is None
        flagged = sum(
            1 for r in det.score(train, [1] * 150, ["tx"] * 150) if r["feature_novelty"]
        )
        assert flagged <= 10, f"{flagged} of 150 in-distribution rows flagged"

    def test_too_few_rows_is_a_named_state(self) -> None:
        det = OodDetector().fit(self._rows(5), stations=[1] * 5, transmitters=["tx"] * 5)
        assert det.degraded == "TOO_FEW_TRAIN_ROWS_FOR_COVARIANCE"
        scored = det.score(self._rows(3), stations=[1] * 3, transmitters=["tx"] * 3)
        assert all(r["feature_distance"] == 0.0 for r in scored), (
            "a detector that could not fit must not emit distances that look measured"
        )

    def test_missing_features_are_imputed_with_train_medians(self) -> None:
        train = self._rows(120, seed=6)
        det = OodDetector().fit(train, stations=[1] * 120, transmitters=["tx"] * 120)
        assert set(det.medians) == set(NOVELTY_FEATURES)
        blank = [{"obs_id": 1, "client_family": "satnogs", "band": "uhf_70cm"}]
        scored = det.score(blank, stations=[1], transmitters=["tx"])[0]
        assert scored["feature_distance"] < det.distance_quantile_99, (
            "an all-missing row sits at the training centre by construction, so it must "
            "not be reported as novel on the feature axis; its missingness is carried "
            "into the model separately"
        )


class TestRiskByNovelty:
    def test_a_flag_that_separates_errors_is_informative(self) -> None:
        rng = np.random.default_rng(8)
        n = 200
        flagged = np.arange(n) < 60
        y = rng.integers(0, 2, size=n)
        # Flagged rows are predicted badly on purpose.
        p = np.where(
            flagged,
            np.where(y == 1, 0.3, 0.7),
            np.where(y == 1, 0.9, 0.1),
        ).astype(float)
        rows = [
            {
                "unseen_station": bool(flagged[i]), "unseen_transmitter": False,
                "unseen_client_family": False, "unseen_band": False,
                "feature_novelty": False, "is_ood": bool(flagged[i]),
            }
            for i in range(n)
        ]
        out = risk_by_novelty(rows, p, y)
        axis = out["unseen_station"]
        assert axis["informative"] is True
        assert axis["flagged"]["risk"] > axis["unflagged"]["risk"]
        # The unflagged cell makes no errors here, so the ratio is undefined rather
        # than absent, and the two must be told apart: a null that means "the flag
        # separates perfectly" reads identically to one meaning "could not compute".
        assert axis["unflagged"]["risk"] == 0.0
        assert axis["risk_ratio"] is None
        assert "undefined" in axis["risk_ratio_state"]

    def test_a_measurable_ratio_is_reported_as_a_number(self) -> None:
        n = 200
        y = np.zeros(n, dtype=int)
        p = np.full(n, 0.2)
        p[:20] = 0.9   # 20 of the 100 flagged rows are wrong
        p[100:110] = 0.9  # 10 of the 100 unflagged rows are wrong
        rows = [
            {
                "unseen_station": i < 100, "unseen_transmitter": False,
                "unseen_client_family": False, "unseen_band": False,
                "feature_novelty": False, "is_ood": i < 100,
            }
            for i in range(n)
        ]
        axis = risk_by_novelty(rows, p, y)["unseen_station"]
        assert axis["risk_ratio"] == pytest.approx(2.0)
        assert axis["risk_ratio_state"] == "measured"
        assert axis["informative"] is True

    def test_a_flag_that_separates_nothing_is_reported_uninformative(self) -> None:
        """Abstaining on a flag like this costs coverage and buys nothing."""
        rng = np.random.default_rng(9)
        n = 200
        y = rng.integers(0, 2, size=n)
        p = np.where(y == 1, 0.8, 0.2).astype(float)
        flip = rng.uniform(size=n) < 0.2
        p = np.where(flip, 1 - p, p)
        rows = [
            {
                "unseen_station": i % 2 == 0, "unseen_transmitter": False,
                "unseen_client_family": False, "unseen_band": False,
                "feature_novelty": False, "is_ood": i % 2 == 0,
            }
            for i in range(n)
        ]
        out = risk_by_novelty(rows, p, y)
        assert out["unseen_station"]["informative"] is False

    def test_a_cell_with_too_few_rows_is_not_called_informative(self) -> None:
        n = 40
        y = np.zeros(n, dtype=int)
        p = np.full(n, 0.2)
        p[0] = 0.9  # the single flagged row is wrong
        rows = [
            {
                "unseen_station": i == 0, "unseen_transmitter": False,
                "unseen_client_family": False, "unseen_band": False,
                "feature_novelty": False, "is_ood": i == 0,
            }
            for i in range(n)
        ]
        out = risk_by_novelty(rows, p, y)
        assert out["unseen_station"]["flagged"]["risk"] == 1.0
        assert out["unseen_station"]["informative"] is False, (
            "a 100% error rate over one observation is not a rate"
        )
