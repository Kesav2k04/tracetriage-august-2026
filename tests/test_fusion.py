"""Tests for the fusion head and its feature blocks (unit B2).

Synthetic data throughout. The claims being tested are about the machinery, and
machinery that only works on one snapshot is not machinery.

The four that carry real weight:

* ``TestGroupedBootstrap`` proves the interval widens when observations are correlated
  within a group. An observation-level bootstrap would report a narrower interval on
  the same data and call an indistinguishable difference a result.
* ``TestOutOfFold`` proves no training row receives an image score from a model that saw
  its own pass episode. Without this a stacked head reliably flatters itself.
* ``TestAdmissibility`` proves the feature layer refuses a label-bearing field.
* ``TestMissingness`` proves an unmeasurable value arrives as a flag, not as an average.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pipeline.tracetriage.features import (
    BLOCK_SOURCE_FIELDS,
    admissible_source_fields,
    band_of,
    corridor_features,
)
from pipeline.tracetriage.fusion import (
    ARM_LADDER,
    GATE5_CHALLENGER,
    GATE5_REFERENCE,
    Calibrator,
    FusionArm,
    _percentile_resolution,
    auc,
    brier,
    build_design,
    calibration_slope_intercept,
    clustered_multiplicity_adjusted,
    clustered_paired_bootstrap,
    clustered_statistic_difference,
    clustering_diagnostics,
    expected_calibration_error,
    grouped_bootstrap_statistic_difference,
    grouped_paired_bootstrap,
    multiplicity_adjusted,
)
from pipeline.tracetriage.selective import (
    area_under_risk_coverage,
    risk_coverage_curve,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

_run_fusion = importlib.import_module("scripts.run_fusion")
eligible_split_names = _run_fusion.eligible_split_names
usable_ids = _run_fusion.usable_ids


class TestAdmissibility:
    def test_the_declared_blocks_are_all_observation_time(self) -> None:
        result = admissible_source_fields()
        assert result["n_fields"] > 20
        assert set(result["blocks"]) == set(BLOCK_SOURCE_FIELDS)

    @pytest.mark.parametrize(
        ("field", "why"),
        [
            ("waterfall_status", "the label itself"),
            ("status", "the label under another name"),
            ("demoddata", "decoded frames answer the question being asked"),
            ("vetted_status", "a second form of the label"),
            ("transmitter_updated", "can postdate the pass"),
        ],
    )
    def test_a_post_observation_field_is_refused(self, field: str, why: str) -> None:
        original = BLOCK_SOURCE_FIELDS["metadata"]
        BLOCK_SOURCE_FIELDS["metadata"] = (*original, field)
        try:
            with pytest.raises(ValueError, match="post_observation"):
                admissible_source_fields(("metadata",))
        finally:
            BLOCK_SOURCE_FIELDS["metadata"] = original

    def test_an_identifier_is_refused_even_though_it_is_available_at_capture(self) -> None:
        """Station id is known at capture and still must not be a feature.

        Availability and admissibility are different questions. A station id would let
        the head memorise which stations produce signal, which is exactly what the
        cold-station split exists to prevent it from doing.
        """
        original = BLOCK_SOURCE_FIELDS["metadata"]
        BLOCK_SOURCE_FIELDS["metadata"] = (*original, "ground_station")
        try:
            with pytest.raises(ValueError, match="identifier"):
                admissible_source_fields(("metadata",))
        finally:
            BLOCK_SOURCE_FIELDS["metadata"] = original

    def test_an_unclassified_field_is_refused(self) -> None:
        original = BLOCK_SOURCE_FIELDS["physics"]
        BLOCK_SOURCE_FIELDS["physics"] = (*original, "some_field_added_next_month")
        try:
            with pytest.raises(ValueError, match="does not cover"):
                admissible_source_fields(("physics",))
        finally:
            BLOCK_SOURCE_FIELDS["physics"] = original

    def test_rx_freq_is_not_a_feature_anywhere(self) -> None:
        """613 transmitters at 613 frequencies: the raw value is an identifier."""
        for block, fields in BLOCK_SOURCE_FIELDS.items():
            assert "rx_freq_hz" not in fields, block
        design = build_design([{}], ("physics", "corridor", "metadata"))
        assert not any("rx_freq" in c for c in design.columns)


class TestMissingness:
    def test_an_unmeasured_value_becomes_a_flag_not_an_average(self) -> None:
        rows = [
            {"max_elevation_deg": 10.0},
            {"max_elevation_deg": 30.0},
            {"max_elevation_deg": None},
        ]
        design = build_design(rows, ("physics",))
        x = design.transform(rows)
        col = design.columns.index("max_elevation_deg")
        flag = design.columns.index("max_elevation_deg__missing")
        assert list(x[:, flag]) == [0.0, 0.0, 1.0]
        assert x[2, col] == pytest.approx(20.0), "imputed with the train median"

    def test_the_median_comes_from_the_rows_the_design_was_fitted_on(self) -> None:
        """Scoring must not recompute the impute value from the rows being scored."""
        train = [{"pass_duration_s": 100.0}, {"pass_duration_s": 200.0}]
        design = build_design(train, ("physics",))
        test = [{"pass_duration_s": None}, {"pass_duration_s": 9999.0}]
        x = design.transform(test)
        col = design.columns.index("pass_duration_s")
        assert x[0, col] == pytest.approx(150.0), (
            "the missing test value must take the train median, not the test median"
        )

    def test_a_degraded_corridor_row_is_discarded_even_when_it_carries_numbers(self) -> None:
        """A partial measurement with a degraded flag must not be used.

        The row is given real-looking values alongside its reason code on purpose. An
        earlier version of this test passed an empty degraded row, which is all-None
        whether or not the guard exists, so it could not tell a working guard from a
        missing one.
        """
        cache = {
            7: {
                "obs_id": 7,
                "degraded": "GEOMETRY_UNKNOWN_LAYOUT",
                "sigma_curved": 4.2,
                "fitted_offset_ppm": 31.0,
                "detect_frac_curved": 0.8,
            }
        }
        feats = corridor_features(7, cache)
        assert set(feats.values()) == {None}, (
            "a degraded measurement must not become a number; the missingness "
            f"indicator is what carries it into the model. Got {feats}"
        )

    def test_an_observation_absent_from_the_cache_is_all_none(self) -> None:
        assert set(corridor_features(999, {}).values()) == {None}


class TestCategories:
    def test_an_unseen_category_gets_an_all_zero_block(self) -> None:
        """A cold split produces unseen categories. That must not create a column."""
        train = [{"band": "uhf_70cm"}] * 6
        design = build_design(train, ("metadata",))
        x = design.transform([{"band": "s_band"}])
        band_cols = [i for i, c in enumerate(design.columns) if c.startswith("band=")]
        assert sum(x[0, i] for i in band_cols) == 0.0

    def test_a_rare_category_is_folded_rather_than_memorised(self) -> None:
        train = [{"transmitter_mode": "BPSK"}] * 6 + [{"transmitter_mode": "AFSK"}] * 2
        design = build_design(train, ("metadata"), min_category_count=5)
        levels = design.categories["transmitter_mode"]
        assert "BPSK" in levels
        assert "AFSK" not in levels, "a mode seen twice is close to an identifier"
        assert "__rare__" in levels

    def test_band_bucketing(self) -> None:
        assert band_of(435.0e6) == "uhf_70cm"
        assert band_of(145.9e6) == "vhf_2m"
        assert band_of(None) == "unknown"
        assert band_of(9.0e9) == "other"


class TestCalibrator:
    def _data(self, n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
        rng = np.random.default_rng(seed)
        p = rng.uniform(0.05, 0.95, size=n)
        y = (rng.uniform(size=n) < p).astype(int)
        return p, y

    def test_a_small_calibration_set_forces_temperature_and_says_why(self) -> None:
        p, y = self._data(49)
        cal = Calibrator(method="auto").fit(p, y)
        assert cal.method == "temperature"
        assert "49" in cal.chosen_because
        assert "isotonic" in cal.chosen_because

    def test_a_large_calibration_set_allows_isotonic(self) -> None:
        p, y = self._data(400)
        cal = Calibrator(method="auto").fit(p, y)
        assert cal.method == "isotonic"

    def test_the_floor_is_a_recorded_threshold_not_a_measured_choice(self) -> None:
        """Choosing by reliability on 49 points would overfit the choice itself."""
        p, y = self._data(49)
        cal = Calibrator(method="auto", min_isotonic_n=10).fit(p, y)
        assert cal.method == "isotonic", "the threshold, and only the threshold, decides"

    def test_temperature_scaling_returns_probabilities(self) -> None:
        p, y = self._data(120)
        cal = Calibrator(method="temperature").fit(p, y)
        out = cal.apply(np.array([0.001, 0.5, 0.999]))
        assert np.all((out > 0) & (out < 1))

    def test_calibration_improves_a_deliberately_overconfident_model(self) -> None:
        rng = np.random.default_rng(1)
        y = rng.integers(0, 2, size=300)
        # Predictions pushed to the extremes: right on average, far too confident.
        p = np.where(y == 1, 0.98, 0.02)
        flip = rng.uniform(size=300) < 0.30
        p = np.where(flip, 1 - p, p)
        cal = Calibrator(method="temperature").fit(p, y)
        assert brier(cal.apply(p), y) < brier(p, y)


class TestGroupedBootstrap:
    def test_the_margin_sign_favours_the_challenger(self) -> None:
        y = np.array([1, 1, 0, 0])
        good = np.array([0.9, 0.9, 0.1, 0.1])
        bad = np.array([0.6, 0.6, 0.4, 0.4])
        r = grouped_paired_bootstrap(good, bad, y, np.array(["a", "b", "c", "d"]), n_boot=200)
        assert r["margin"] > 0, "positive margin means the challenger errs less"

    def test_grouping_widens_the_interval_when_observations_are_correlated(self) -> None:
        """The claim the whole interval rests on.

        Twelve pass episodes, ten near-identical captures each. Resampling the 120
        observations pretends there are 120 independent samples; resampling the 12
        episodes admits there are 12. The grouped interval must be materially wider, or
        the grouping is decorative.

        The per-episode effect deliberately dominates the per-capture noise, sd 0.05
        against 0.002, because that is the situation the grouping exists for: four
        captures of one pass at one station share a receiver, a local-oscillator error
        and a sky geometry, so the model's error on them moves together. An earlier
        version of this test used comparable magnitudes for both, which left a
        within-group correlation near a third and a grouped interval only 1.15 times
        wider. The threshold was not the problem; the data did not have the property
        the test was asserting about it.
        """
        rng = np.random.default_rng(7)
        labels, challenger, reference, groups = [], [], [], []
        for g in range(12):
            truth = int(g % 2 == 0)
            edge = rng.normal(0.05, 0.05)  # per-episode effect, shared by its captures
            for _ in range(10):
                labels.append(truth)
                base = 0.5 + (0.2 if truth else -0.2)
                reference.append(np.clip(base + rng.normal(0, 0.002), 0.01, 0.99))
                challenger.append(
                    np.clip(base + (edge if truth else -edge) + rng.normal(0, 0.002), 0.01, 0.99)
                )
                groups.append(f"episode{g}")

        y = np.array(labels)
        ch, rf = np.array(challenger), np.array(reference)
        grouped = grouped_paired_bootstrap(ch, rf, y, np.array(groups), n_boot=2000, seed=3)
        per_obs = grouped_paired_bootstrap(
            ch, rf, y, np.arange(len(y)).astype(str), n_boot=2000, seed=3
        )
        grouped_width = grouped["ci95"][1] - grouped["ci95"][0]
        per_obs_width = per_obs["ci95"][1] - per_obs["ci95"][0]
        assert grouped_width > per_obs_width * 1.5, (
            f"grouped width {grouped_width:.5f} vs per-observation {per_obs_width:.5f}: "
            "grouping by episode must widen the interval on correlated data"
        )
        assert grouped["n_groups"] == 12
        assert grouped["mean_group_size"] == pytest.approx(10.0)

    def test_a_zero_difference_is_not_distinguishable(self) -> None:
        rng = np.random.default_rng(11)
        y = rng.integers(0, 2, size=60)
        p = rng.uniform(0.2, 0.8, size=60)
        r = grouped_paired_bootstrap(p, p.copy(), y, np.arange(60).astype(str), n_boot=500)
        assert r["margin"] == pytest.approx(0.0)
        assert not r["distinguishable"]

    def test_the_interval_is_reproducible_for_a_fixed_seed(self) -> None:
        rng = np.random.default_rng(5)
        y = rng.integers(0, 2, size=40)
        a, b = rng.uniform(size=40), rng.uniform(size=40)
        g = np.array([f"g{i // 4}" for i in range(40)])
        first = grouped_paired_bootstrap(a, b, y, g, n_boot=300, seed=99)
        second = grouped_paired_bootstrap(a, b, y, g, n_boot=300, seed=99)
        assert first["ci95"] == second["ci95"]


class TestOutOfFold:
    def test_no_training_row_is_scored_by_a_model_that_saw_its_episode(self) -> None:
        """The stacking discipline, tested by making a leak impossible to miss.

        Each fold's scorer records which episodes it was trained on. If any row's score
        came from a model trained on that row's own episode, the head would be shown an
        image opinion already fitted to the label it is about to predict.
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_fusion", Path(__file__).resolve().parents[1] / "scripts" / "run_fusion.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        ids = list(range(40))
        feature_rows = {i: {"obs_id": i, "episode": f"ep{i // 4}"} for i in ids}
        y = np.array([i % 2 for i in ids])

        seen: list[tuple[set[str], set[str]]] = []

        def fit_predict(train_ids, train_labels, score_ids):
            seen.append(
                (
                    {feature_rows[i]["episode"] for i in train_ids},
                    {feature_rows[i]["episode"] for i in score_ids},
                )
            )
            return np.full(len(score_ids), 0.5)

        mod._oof_by_ids(fit_predict, ids, y, feature_rows, seed=42)

        assert len(seen) >= 2, "folds did not run"
        for train_eps, score_eps in seen:
            assert not (train_eps & score_eps), (
                f"episodes {sorted(train_eps & score_eps)} were both trained on and scored"
            )


class TestArms:
    def _rows(self, n: int = 120, seed: int = 0) -> tuple[list[dict], list[int]]:
        rng = np.random.default_rng(seed)
        rows, labels = [], []
        for _ in range(n):
            y = int(rng.integers(0, 2))
            rows.append(
                {
                    "image_score": float(
                        np.clip(0.5 + (0.3 if y else -0.3) + rng.normal(0, 0.1), 0, 1)
                    ),
                    "max_elevation_deg": float(rng.uniform(5, 80)),
                    "pass_duration_s": float(rng.uniform(100, 600)),
                    "band": "uhf_70cm",
                }
            )
            labels.append(y)
        return rows, labels

    def test_prior_only_predicts_the_train_base_rate_everywhere(self) -> None:
        rows, labels = self._rows()
        arm = FusionArm(name="prior_only", blocks=()).fit(rows, labels)
        preds = arm.predict(rows[:5])
        assert np.allclose(preds, np.mean(labels))
        assert arm.design is None, "the floor must not build a design matrix"

    def test_an_informative_arm_beats_the_floor_it_is_compared_against(self) -> None:
        rows, labels = self._rows()
        floor = FusionArm(name="prior_only", blocks=()).fit(rows, labels)
        img = FusionArm(name="image_only", blocks=("image",)).fit(rows, labels)
        y = np.asarray(labels)
        assert brier(img.predict(rows), y) < brier(floor.predict(rows), y)

    def test_the_scaler_is_fitted_once_and_reused(self) -> None:
        """Re-deriving the scaler at scoring time would leak test statistics."""
        rows, labels = self._rows()
        arm = FusionArm(name="a", blocks=("physics",)).fit(rows, labels)
        before = arm.scaler_mean.copy()
        arm.predict([{"max_elevation_deg": 1e6, "pass_duration_s": 1e6}])
        assert np.array_equal(arm.scaler_mean, before)

    def test_too_few_samples_is_a_named_state_not_a_silent_fit(self) -> None:
        rows, labels = self._rows(n=12)
        arm = FusionArm(name="a", blocks=("physics",)).fit(rows, labels)
        assert arm.degraded == "TOO_FEW_SAMPLES_OR_COLUMNS"
        assert np.allclose(arm.predict(rows), np.mean(labels)), (
            "a degraded arm must fall back to the prior, not to an unfitted model"
        )

    def test_the_gate5_pair_is_on_the_ladder(self) -> None:
        names = {n for n, _ in ARM_LADDER}
        assert GATE5_CHALLENGER in names
        assert GATE5_REFERENCE in names
        blocks = dict(ARM_LADDER)
        assert blocks[GATE5_REFERENCE] == ("image",)
        assert "physics" in blocks[GATE5_CHALLENGER]
        assert "image" in blocks[GATE5_CHALLENGER], (
            "the challenger must contain the reference, or the comparison measures "
            "swapping the image out rather than adding physics to it"
        )


class TestMetrics:
    def test_brier_and_auc_on_a_known_case(self) -> None:
        y = np.array([1, 0])
        assert brier(np.array([1.0, 0.0]), y) == 0.0
        assert auc(np.array([0.9, 0.1]), y) == 1.0
        assert auc(np.array([0.1, 0.9]), y) == 0.0

    def test_auc_is_nan_when_one_class_is_absent(self) -> None:
        assert np.isnan(auc(np.array([0.3, 0.7]), np.array([1, 1])))

    def test_calibration_slope_of_a_well_calibrated_model_is_near_one(self) -> None:
        rng = np.random.default_rng(3)
        p = rng.uniform(0.05, 0.95, size=4000)
        y = (rng.uniform(size=4000) < p).astype(int)
        slope, intercept = calibration_slope_intercept(p, y)
        assert 0.85 < slope < 1.15, slope
        assert abs(intercept) < 0.2, intercept

    def test_calibration_slope_below_one_means_overconfident(self) -> None:
        rng = np.random.default_rng(4)
        y = rng.integers(0, 2, size=2000)
        p = np.where(y == 1, 0.95, 0.05)
        flip = rng.uniform(size=2000) < 0.35
        p = np.where(flip, 1 - p, p)
        slope, _ = calibration_slope_intercept(p, y)
        assert slope < 1.0, f"an overconfident model must show slope < 1, got {slope}"

    def test_ece_is_zero_for_a_perfectly_calibrated_constant(self) -> None:
        y = np.array([1, 1, 0, 0])
        assert expected_calibration_error(np.full(4, 0.5), y) == pytest.approx(0.0)

# ---------------------------------------------------------------------------
# B6: the statistic bootstrap, the two-directional correction, the ablation rule
# ---------------------------------------------------------------------------


def _load_run_fusion():
    """Import scripts/run_fusion.py as a module."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "run_fusion.py"
    spec = importlib.util.spec_from_file_location("run_fusion", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mean_squared_error(probs, labels, groups):  # noqa: ARG001
    return float(np.mean((probs - labels) ** 2))


class TestStatisticBootstrap:
    """``grouped_bootstrap_statistic_difference`` exists because AURC is not a mean."""

    def test_it_agrees_with_the_paired_bootstrap_on_a_statistic_that_is_a_mean(
        self,
    ) -> None:
        """A cross-check with a known answer.

        Brier score *is* a per-observation mean, so running it through the
        resample-and-recompute path must land on the same margin the paired bootstrap
        reports. If it does not, the resampling itself is wrong, and no amount of
        agreement on AURC would reveal that, because nothing else computes AURC.
        """
        rng = np.random.default_rng(3)
        groups = np.repeat(np.arange(40), 3)
        labels = rng.integers(0, 2, size=len(groups))
        challenger = np.clip(labels * 0.6 + 0.2 + rng.normal(0, 0.05, len(groups)), 0.01, 0.99)
        reference = np.clip(0.5 + rng.normal(0, 0.05, len(groups)), 0.01, 0.99)

        paired = grouped_paired_bootstrap(
            challenger, reference, labels, groups, n_boot=400, seed=7
        )
        general = grouped_bootstrap_statistic_difference(
            _mean_squared_error, challenger, reference, labels, groups,
            n_boot=400, seed=7, lower_is_better=True,
        )
        assert general["margin"] == pytest.approx(paired["margin"], abs=1e-9)
        assert general["direction"] == paired["direction"]

    def test_lower_is_better_false_flips_the_sign(self) -> None:
        """A statistic where bigger is better must still report positive for a win."""
        groups = np.arange(30)
        labels = np.array([i % 2 for i in groups])
        good = np.where(labels == 1, 0.9, 0.1)
        bad = np.full(len(groups), 0.5)

        def accuracy(probs, y, _g):
            return float(np.mean((probs > 0.5) == (y == 1)))

        res = grouped_bootstrap_statistic_difference(
            accuracy, good, bad, labels, groups,
            n_boot=200, seed=1, lower_is_better=False,
        )
        assert res["margin"] > 0.0, (
            "the better model must get a positive margin when higher scores are better"
        )

    def test_an_episode_drawn_twice_does_not_collapse_into_one(self) -> None:
        """Repeated draws stay separate groups.

        If the resample reused the original group labels, a group drawn twice would merge
        into a single larger group, so a 40-group bootstrap would silently evaluate fewer
        than 40 groups and the interval would come out too narrow. The statistic here
        counts the distinct group labels it is handed, so a collapse is directly visible.
        """
        groups = np.repeat(np.arange(20), 2)
        labels = np.array([i % 2 for i in range(len(groups))])
        probs = np.full(len(groups), 0.5)
        seen: list[int] = []

        def count_groups(_p, _y, g):
            seen.append(int(len(np.unique(g))))
            return 0.5

        grouped_bootstrap_statistic_difference(
            count_groups, probs, probs, labels, groups, n_boot=50, seed=5
        )
        resampled = seen[2:]  # the first two calls are the un-resampled point estimate
        assert resampled, "no resamples ran"
        assert all(n == 20 for n in resampled), (
            "a resample reported fewer than 20 groups, so repeated draws were merged: "
            f"saw {sorted(set(resampled))}"
        )

    def test_degenerate_resamples_are_counted_not_propagated(self) -> None:
        """A NaN statistic must be excluded and counted, never folded into a percentile."""
        groups = np.arange(30)
        labels = np.array([i % 2 for i in groups])
        probs = np.full(30, 0.5)
        calls = {"n": 0}

        def sometimes_nan(_p, _y, _g):
            calls["n"] += 1
            return float("nan") if calls["n"] % 3 == 0 else 0.5

        res = grouped_bootstrap_statistic_difference(
            sometimes_nan, probs, probs, labels, groups, n_boot=90, seed=2
        )
        assert res["n_degenerate_resamples"] > 0, "the NaN resamples were not counted"
        if res["ci95"] is not None:
            assert all(np.isfinite(res["ci95"])), "a NaN reached the reported interval"

    def test_it_refuses_an_interval_when_almost_every_resample_is_degenerate(self) -> None:
        groups = np.arange(30)
        labels = np.array([i % 2 for i in groups])
        probs = np.full(30, 0.5)
        res = grouped_bootstrap_statistic_difference(
            lambda _p, _y, _g: float("nan"), probs, probs, labels, groups,
            n_boot=100, seed=2,
        )
        assert res["ci95"] is None
        assert res["direction"] == "unmeasurable", (
            "an unmeasurable comparison must not be reported as indistinguishable, "
            "because those are different facts"
        )

    def test_bonferroni_widens_the_interval(self) -> None:
        rng = np.random.default_rng(11)
        groups = np.repeat(np.arange(50), 2)
        labels = rng.integers(0, 2, size=len(groups))
        # Per-observation noise on purpose. The first version of this fixture used
        # ``labels * 0.5 + 0.25``, whose squared error is exactly 0.0625 for both classes,
        # so every resample returned the identical margin and both intervals had zero
        # width. The test then failed on 0.1875 < 0.1875, which is the fixture lacking the
        # variation the assertion is about rather than the correction being wrong.
        challenger = np.clip(
            labels * 0.5 + 0.25 + rng.normal(0, 0.12, len(groups)), 0.01, 0.99
        )
        reference = np.clip(0.5 + rng.normal(0, 0.12, len(groups)), 0.01, 0.99)
        res = grouped_bootstrap_statistic_difference(
            _mean_squared_error, challenger, reference, labels, groups,
            n_boot=400, seed=4, n_comparisons=7,
        )
        assert res["ci_adjusted"][0] < res["ci95"][0]
        assert res["ci_adjusted"][1] > res["ci95"][1]
        assert res["adjusted_confidence"] == pytest.approx(1 - 0.05 / 7)


class TestCorrectionIsTwoDirectional:
    """A correction applied only to good news is not a correction."""

    def test_a_corrected_harm_survives_and_is_named_as_a_harm(self) -> None:
        """The mutation this catches: ``survives_correction = lo > 0``.

        With a one-sided test, an interval lying entirely *below* zero reports
        ``survives_correction: False``, which a reader and the ablation rule both take to
        mean "no reliable effect". It means the opposite. The ablation rule's DROP branch
        was dead code for exactly this reason.
        """
        rng = np.random.default_rng(21)
        groups = np.repeat(np.arange(60), 2)
        labels = rng.integers(0, 2, size=len(groups))
        # The challenger is deliberately the worse model.
        challenger = np.full(len(groups), 0.5)
        reference = np.clip(labels * 0.6 + 0.2, 0.01, 0.99)

        res = multiplicity_adjusted(
            challenger, reference, labels, groups, n_comparisons=7, n_boot=400, seed=9
        )
        assert res["margin"] < 0.0, "fixture is wrong: the challenger should be worse"
        assert res["ci_adjusted"][1] < 0.0, "fixture is wrong: the harm should be clear"
        assert res["survives_correction"] is True, (
            "an interval entirely below zero is a corrected harm, not an absent effect"
        )
        assert res["direction_adjusted"] == "reference_better"

    def test_a_tie_does_not_survive_in_either_direction(self) -> None:
        groups = np.repeat(np.arange(60), 2)
        labels = np.array([i % 2 for i in range(len(groups))])
        probs = np.full(len(groups), 0.5)
        res = multiplicity_adjusted(
            probs, probs.copy(), labels, groups, n_comparisons=7, n_boot=300, seed=9
        )
        assert res["survives_correction"] is False
        assert res["direction_adjusted"] == "indistinguishable"


class TestAblationRule:
    """The retain/drop decision is generated from the measurements, so test the rule."""

    @staticmethod
    def _split(name, train, comparisons, adjusted):
        return {
            "split": name,
            "degraded": None,
            "counts": {"train": train},
            "comparisons": comparisons,
            "multiplicity_adjusted": adjusted,
            "arms": {},
        }

    def test_a_block_that_is_only_ever_worse_is_dropped(self) -> None:
        mod = _load_run_fusion()
        res = mod._ablation_conclusion([
            self._split(
                "chronological", 500,
                {"image_physics_vs_image_only": {"direction": "reference_better"}},
                {"image_physics_vs_image_only": {
                    "survives_correction": True,
                    "direction_adjusted": "reference_better",
                }},
            )
        ])
        assert res["multiplicity_corrected"]["blocks"]["physics"]["decision"] == "DROP"
        assert "physics" not in res["recommended_blocks"]

    def test_a_win_that_does_not_survive_correction_is_not_established(self) -> None:
        """The nominal and corrected rules must disagree here, and both be reported."""
        mod = _load_run_fusion()
        res = mod._ablation_conclusion([
            self._split(
                "chronological", 500,
                {"image_metadata_vs_image_only": {"direction": "challenger_better"}},
                {"image_metadata_vs_image_only": {
                    "survives_correction": False,
                    "direction_adjusted": "indistinguishable",
                }},
            )
        ])
        assert res["nominal"]["blocks"]["metadata"]["decision"] == "RETAIN"
        assert (
            res["multiplicity_corrected"]["blocks"]["metadata"]["decision"]
            == "NOT_ESTABLISHED"
        )
        assert "metadata" in res["rules_disagree_on"]
        assert res["deciding_rule"] == "multiplicity_corrected"

    def test_a_split_below_the_training_floor_cannot_decide(self) -> None:
        """The floor exists because a 188-row verdict measures the sample, not the block.

        A harm on an undersized split must not drop a block, and the receipt has to say
        which splits were set aside, or the exclusion is invisible.
        """
        mod = _load_run_fusion()
        res = mod._ablation_conclusion([
            self._split(
                "cold_combined", 188,
                {"image_corridor_vs_image_only": {"direction": "reference_better"}},
                {"image_corridor_vs_image_only": {
                    "survives_correction": True,
                    "direction_adjusted": "reference_better",
                }},
            )
        ])
        assert res["multiplicity_corrected"]["blocks"]["corridor"]["decision"] == (
            "NOT_ESTABLISHED"
        ), "a split below the training floor must not decide a block"
        assert "cold_combined" in res["splits_below_training_floor"]
        assert res["splits_used"] == []

    def test_a_block_both_better_and_worse_is_not_established(self) -> None:
        mod = _load_run_fusion()
        adj = {
            "survives_correction": True,
            "direction_adjusted": "challenger_better",
        }
        worse = {"survives_correction": True, "direction_adjusted": "reference_better"}
        res = mod._ablation_conclusion([
            self._split(
                "chronological", 500,
                {"image_corridor_vs_image_only": {"direction": "challenger_better"}},
                {"image_corridor_vs_image_only": adj},
            ),
            self._split(
                "cold_station", 400,
                {"image_corridor_vs_image_only": {"direction": "reference_better"}},
                {"image_corridor_vs_image_only": worse},
            ),
        ])
        assert res["multiplicity_corrected"]["blocks"]["corridor"]["decision"] == (
            "NOT_ESTABLISHED"
        ), "a block that helps on one split and hurts on another is not established"

    def test_the_recommended_arm_must_be_one_the_ladder_measured(self) -> None:
        """A selected combination nothing fitted has no score to report."""
        mod = _load_run_fusion()
        res = mod._ablation_conclusion([
            self._split(
                "chronological", 500,
                {
                    "image_corridor_vs_image_only": {"direction": "challenger_better"},
                    "image_metadata_vs_image_only": {"direction": "challenger_better"},
                },
                {
                    "image_corridor_vs_image_only": {
                        "survives_correction": True,
                        "direction_adjusted": "challenger_better",
                    },
                    "image_metadata_vs_image_only": {
                        "survives_correction": True,
                        "direction_adjusted": "challenger_better",
                    },
                },
            )
        ])
        assert res["recommended_blocks"] == ["image", "corridor", "metadata"]
        assert res["multiplicity_corrected"]["shipped_arm_was_measured"] is False, (
            "image + corridor + metadata is not an arm on the ladder, and the receipt "
            "has to admit that rather than report a score for it"
        )

    def test_what_ships_is_not_read_off_the_rule_that_recommends(self) -> None:
        """The two meanings of "shipped" are separated, and the difference is published.

        The ranker is built from ``SHIPPED_ARM``. The ablation recommends a block set.
        Those were one field until SPACE-S7 made them disagree, and collapsing them
        again would either relabel the queue's numbers with another arm's name or hide
        that the corrected rule no longer supports a block the queue is using.
        """
        mod = _load_run_fusion()
        res = mod._ablation_conclusion([
            self._split(
                "chronological", 500,
                {"image_corridor_vs_image_only": {"direction": "challenger_better"}},
                {"image_corridor_vs_image_only": {
                    "survives_correction": False,
                    "direction_adjusted": "indistinguishable",
                }},
            )
        ])
        assert res["shipped_arm"] == mod.SHIPPED_ARM == "image_corridor"
        assert res["shipped_blocks"] == ["image", "corridor"]
        assert res["recommended_arm"] == "image_only"
        assert res["recommended_blocks"] == ["image"]

        stated = res["shipped_arm_vs_recommendation"]
        assert stated["agree"] is False
        assert stated["ships"] == "image_corridor"
        assert stated["nominal_recommends"] == "image_corridor"
        assert stated["corrected_recommends"] == "image_only"
        assert stated["shipped_blocks_without_corrected_support"] == ["corridor"]
        assert "corridor" in stated["note"]

    def test_the_note_carries_the_metric_the_rule_does_not_read(self) -> None:
        """The counter-evidence for the shipped arm is looked up, not asserted.

        The ablation rule reads Brier comparisons. The queue does selective review, which
        is what risk-coverage area measures, and on this corpus the two disagree about the
        corridor block. A note that argued the ranker should stay without citing the
        surviving interval would be a preference; one that cites it is a measurement.
        """
        mod = _load_run_fusion()
        split = self._split(
            "chronological", 500,
            {"image_corridor_vs_image_only": {"direction": "challenger_better"}},
            {"image_corridor_vs_image_only": {
                "survives_correction": False,
                "direction_adjusted": "indistinguishable",
            }},
        )
        split["selective"] = {
            "aurc_shipped_vs_image_only": {
                "margin": 0.05736,
                "ci_adjusted": [0.01192, 0.1158],
                "direction": "challenger_better",
                "survives_correction": True,
                "n_comparisons": 21,
            }
        }
        stated = mod._ablation_conclusion([split])["shipped_arm_vs_recommendation"]
        cited = stated["selective_evidence_for_the_shipped_arm"]
        assert cited["survives_correction"] is True
        assert cited["n_comparisons"] == 21
        assert "+0.01192 to +0.11580" in stated["note"]
        assert "21 comparisons" in stated["note"]

        # And the other direction: a selective comparison that also fails must not be
        # reported as support.
        split["selective"]["aurc_shipped_vs_image_only"]["survives_correction"] = False
        split["selective"]["aurc_shipped_vs_image_only"]["direction"] = (
            "indistinguishable"
        )
        stated = mod._ablation_conclusion([split])["shipped_arm_vs_recommendation"]
        assert "does not clear zero after correction either" in stated["note"]
        assert "+0.01192" not in stated["note"]

    def test_agreement_is_stated_rather_than_left_to_be_inferred(self) -> None:
        """When the two do agree, the receipt says so instead of omitting the field."""
        mod = _load_run_fusion()
        res = mod._ablation_conclusion([
            self._split(
                "chronological", 500,
                {"image_corridor_vs_image_only": {"direction": "challenger_better"}},
                {"image_corridor_vs_image_only": {
                    "survives_correction": True,
                    "direction_adjusted": "challenger_better",
                }},
            )
        ])
        stated = res["shipped_arm_vs_recommendation"]
        assert stated["agree"] is True
        assert stated["corrected_recommends"] == "image_corridor"
        assert stated["shipped_blocks_without_corrected_support"] == []
        assert "recommends the same combination" in stated["note"]

    def test_the_shipped_arm_blocks_come_from_the_ladder(self) -> None:
        """A block tuple written out by hand could name an arm and mean something else.

        ``run_queue.py`` fits ``SHIPPED_ARM_BLOCKS`` and calls the result
        ``SHIPPED_ARM``. Both were literals there until D7, so the queue could have been
        ranked by one feature set while every receipt called it another. The second half
        of this test is not a comparison of two definitions, because there is now one: it
        fails if a local literal is reintroduced in the script and shadows the import.
        """
        from pipeline.tracetriage.fusion import (
            ARM_LADDER,
            SHIPPED_ARM,
            SHIPPED_ARM_BLOCKS,
        )

        assert dict(ARM_LADDER)[SHIPPED_ARM] == SHIPPED_ARM_BLOCKS

        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "scripts" / "run_queue.py"
        spec = importlib.util.spec_from_file_location("run_queue_for_arm", path)
        run_queue = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(run_queue)
        assert run_queue.SHIPPED_ARM == SHIPPED_ARM
        assert run_queue.SHIPPED_ARM_BLOCKS == SHIPPED_ARM_BLOCKS


# ---------------------------------------------------------------------------
# SPACE-S6: a grouped bootstrap that groups nothing is an ungrouped bootstrap
#
# Every published gate-5 interval carried mean_group_size 1.0 while its own note said
# it protected against captures of one pass sharing a receiver. The episode grouping is
# inert on these test partitions; stations are not. Both intervals are now computed and
# the union of the measurable ones governs, which is what gate 6 already did.
# ---------------------------------------------------------------------------


def _clustered_fixture(
    n: int = 80,
    station_spread: float = 0.06,
    within_station_spread: float = 0.12,
    seed: int = 5,
):
    """Scores whose paired difference clusters by station, which is what is bootstrapped.

    The challenger's advantage over the reference varies by station rather than the two
    arms sharing a station offset. A shared offset moves both arms together and mostly
    cancels in the paired Brier difference, which is the quantity the interval is about;
    a per-station advantage does not. That distinction is the whole reason the ICC is
    measured on the difference and not on the scores.

    Iteration is over a sorted list, not a set: a set of strings iterates in an order
    that changes with the process hash seed, which made an earlier version of this
    fixture generate different data on every run and a marginal direction assertion pass
    or fail at random.
    """
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 2, n).astype(float)
    station_ids = np.array([f"s{i % 8}" for i in range(n)])
    stations = sorted(set(station_ids.tolist()))
    advantage = {s: float(rng.normal(0.16, station_spread)) for s in stations}
    signed = 2.0 * labels - 1.0                      # +1 on a positive, -1 otherwise
    reference = np.clip(0.5 + 0.12 * signed + rng.normal(0, 0.08, n), 0.02, 0.98)
    # Between-station spread against within-station spread is what sets the ICC. These
    # values put it at 0.097 with a design effect of 1.873, the same order as the 0.247
    # and 1.374 measured on the shipped chronological split, so the fixture exercises the
    # union and the sensitivity without being a caricature of them.
    per_observation = rng.normal(0.0, within_station_spread, n)
    gain = (np.array([advantage[s] for s in station_ids]) + per_observation) * signed
    challenger = np.clip(reference + gain, 0.02, 0.98)
    episode_ids = np.array([f"e{i}" for i in range(n)])   # one observation each
    return challenger, reference, labels, episode_ids, station_ids


def test_the_episode_grouping_is_reported_as_unmeasurable_not_as_protection():
    """One observation per group cannot partition variance, and the receipt says so."""
    ch, ref, lab, ep, st = _clustered_fixture()
    out = clustered_paired_bootstrap(ch, ref, lab, ep, st, n_boot=400, seed=1)

    episode = out["clustering"]["episode"]
    assert episode["measurable"] is False
    assert "more observations than groups" in episode["reason"]
    assert out["mean_group_size_episode"] == 1.0
    assert out["clustering"]["station"]["measurable"] is True
    assert out["mean_group_size_station"] > 1.0


def test_the_governing_interval_is_the_union_and_names_what_it_unioned():
    """A union can only widen, and the inert grouping is named for what it is.

    Taking the union of both intervals rather than only the measurable ones matters in
    the direction that counts: on the shipped chronological split the station
    bootstrap's lower bound is the HIGHER of the two, so dropping the observation-level
    interval would have raised the published lower bound. A fix to a finding about
    intervals being too narrow must not end up publishing a narrower one.
    """
    ch, ref, lab, ep, st = _clustered_fixture()
    out = clustered_paired_bootstrap(ch, ref, lab, ep, st, n_boot=400, seed=1)

    assert out["governing_interval"] == "union_of_observation_level_and_station", (
        "an episode grouping holding one observation per group is an observation-level "
        f"bootstrap and has to be named as one: {out['governing_interval']}"
    )
    assert out["ci95"][0] == min(out["ci95_episode"][0], out["ci95_station"][0])
    assert out["ci95"][1] == max(out["ci95_episode"][1], out["ci95_station"][1])
    assert out["ci95"] != out["ci95_episode"], (
        "the two groupings produced the same interval, so this fixture cannot show the "
        "union doing anything"
    )


def test_both_groupings_govern_when_both_have_structure():
    """With real episodes the union is at least as wide as either interval."""
    ch, ref, lab, _ep, st = _clustered_fixture()
    episodes = np.array([f"e{i // 2}" for i in range(len(lab))])   # two per episode
    out = clustered_paired_bootstrap(ch, ref, lab, episodes, st, n_boot=400, seed=1)

    assert out["clustering"]["episode"]["measurable"] is True
    assert out["governing_interval"] == "union_of_episode_and_station", (
        "with two measurable groupings the label must name both by their real names"
    )
    assert out["ci95"][0] == min(out["ci95_episode"][0], out["ci95_station"][0])
    assert out["ci95"][1] == max(out["ci95_episode"][1], out["ci95_station"][1])


def test_the_verdict_is_read_off_the_governing_interval():
    """Publishing a verdict from the narrow interval is the defect, not the width.

    A wider interval that nothing reads changes no decision. The direction, the
    distinguishable flag and challenger_better all have to come from the interval that
    governs, or the receipt disagrees with itself.
    """
    ch, ref, lab, ep, st = _clustered_fixture()
    out = clustered_paired_bootstrap(ch, ref, lab, ep, st, n_boot=400, seed=1)
    lo, hi = out["ci95"]
    expected = (
        "challenger_better" if lo > 0 else "reference_better" if hi < 0
        else "indistinguishable"
    )
    assert out["direction"] == expected
    assert out["distinguishable"] is (expected != "indistinguishable")
    assert out["challenger_better"] is (expected == "challenger_better")


def test_the_correction_and_the_clustering_apply_to_the_same_interval():
    """Bonferroni under both groupings, unioned, or the rule reads the narrower one."""
    ch, ref, lab, ep, st = _clustered_fixture()
    adj = clustered_multiplicity_adjusted(
        ch, ref, lab, ep, st, n_comparisons=6, n_boot=400, seed=1
    )
    nominal = clustered_paired_bootstrap(ch, ref, lab, ep, st, n_boot=400, seed=1)

    assert adj["ci_adjusted"][0] == min(
        adj["ci_adjusted_episode"][0], adj["ci_adjusted_station"][0]
    )
    assert adj["ci_adjusted"][1] == max(
        adj["ci_adjusted_episode"][1], adj["ci_adjusted_station"][1]
    )
    assert adj["ci_adjusted"][0] <= nominal["ci95"][0], (
        "the corrected interval is narrower than the nominal one on the low side"
    )
    assert adj["ci_adjusted"][1] >= nominal["ci95"][1]
    assert adj["survives_correction"] is (
        adj["ci_adjusted"][0] > 0 or adj["ci_adjusted"][1] < 0
    )
    assert adj["confidence_level"] > 0.95


def test_a_measured_harm_is_not_flattened_into_no_difference():
    """The three-way verdict survives the union, in the losing direction too."""
    ch, ref, lab, ep, st = _clustered_fixture()
    # Swap the arms: the challenger is now the weaker one by construction.
    out = clustered_paired_bootstrap(ref, ch, lab, ep, st, n_boot=400, seed=1)
    assert out["direction"] == "reference_better"
    assert out["distinguishable"] is True
    assert out["challenger_better"] is False
    assert out["margin"] < 0.0


def test_clustering_diagnostics_measure_the_paired_difference_not_the_scores():
    """The ICC has to be of the quantity the interval is about.

    Measuring it on the raw scores would report the clustering of ability rather than
    the clustering of the difference between two arms, which is what the bootstrap
    resamples.
    """
    ch, ref, lab, _ep, st = _clustered_fixture()
    diag = clustering_diagnostics(ch, ref, lab, st)
    assert diag["measurable"] is True
    assert diag["n_groups"] == len(set(st.tolist()))
    assert diag["design_effect"] >= 1.0
    # Same arm against itself: the difference is identically zero, so there is no
    # variance to partition either way and the ICC must not claim clustering.
    flat = clustering_diagnostics(ch, ch, lab, st)
    assert flat["icc"] == 0.0
    assert flat["design_effect"] == 1.0


class TestClusteredStatisticDifference:
    """The risk-coverage interval was the one SPACE-S6 left ungrouped.

    The paired Brier comparisons were fixed to resample stations as well as episodes, and
    the statistic bootstrap was not, which left the defect in the interval the analysis
    leans on hardest: an episode holds about one observation on these test partitions, so
    an episode-resampled interval is an observation-level interval under a grouped name.
    """

    @staticmethod
    def _aurc(probs, labels, groups):
        return area_under_risk_coverage(risk_coverage_curve(probs, labels, groups))

    def test_the_statistic_does_not_depend_on_the_grouping(self) -> None:
        """The precondition that makes switching the resampling unit legitimate.

        ``risk_coverage_curve`` reads ``groups`` only to report ``n_groups_kept``. Risk
        and coverage are per observation, so the area is the same number under either
        grouping and the two intervals are intervals for one quantity. If this ever stops
        holding, the union stops being meaningful and this test is where it shows.
        """
        ch, _ref, lab, ep, st = _clustered_fixture()
        assert self._aurc(ch, lab, ep) == pytest.approx(self._aurc(ch, lab, st))
        assert self._aurc(ch, lab, ep) == pytest.approx(
            self._aurc(ch, lab, np.arange(len(lab)))
        )

    def test_the_union_is_no_narrower_than_either_grouping(self) -> None:
        ch, ref, lab, ep, st = _clustered_fixture()
        out = clustered_statistic_difference(
            self._aurc, ch, ref, lab, ep, st, n_boot=400, seed=3, n_comparisons=21
        )
        for field in ("ci95", "ci_adjusted"):
            union = out[field]
            for grouping in ("episode", "station"):
                side = out[f"{field}_{grouping}"]
                assert union[0] <= side[0] + 1e-12, f"{field} lower is inside {grouping}"
                assert union[1] >= side[1] - 1e-12, f"{field} upper is inside {grouping}"
        assert out["governing_interval"].startswith("union_of_")
        assert out["n_groups_episode"] > out["n_groups_station"]
        assert out["clustering"]["station"]["n_groups"] == out["n_groups_station"]

    def test_the_verdict_is_read_off_the_union(self) -> None:
        """Not off whichever grouping happened to be narrower."""
        ch, ref, lab, ep, st = _clustered_fixture()
        out = clustered_statistic_difference(
            self._aurc, ch, ref, lab, ep, st, n_boot=400, seed=3, n_comparisons=1
        )
        lo, hi = out["ci95"]
        expected = (
            "challenger_better" if lo > 0
            else "reference_better" if hi < 0
            else "indistinguishable"
        )
        assert out["direction"] == expected
        assert out["distinguishable"] is (expected != "indistinguishable")
        adj_lo, adj_hi = out["ci_adjusted"]
        assert out["survives_correction"] is bool(adj_lo > 0 or adj_hi < 0)

    def test_a_grouping_that_cannot_be_resampled_makes_it_unmeasurable(self) -> None:
        """One grouping's interval is not a union of two.

        Publishing the surviving grouping alone would report a narrower interval under a
        name that claims both were checked, which is the same substitution the union
        exists to prevent.
        """
        ch, ref, lab, ep, st = _clustered_fixture()

        def only_few_groups(probs, labels, groups):
            # Finite for the station grouping, NaN for the episode grouping, so exactly
            # one side fails to form an interval.
            if len(np.unique(groups)) > 20:
                return float("nan")
            return self._aurc(probs, labels, groups)

        out = clustered_statistic_difference(
            only_few_groups, ch, ref, lab, ep, st, n_boot=300, seed=3, n_comparisons=21
        )
        assert out["ci95"] is None
        assert out["ci_adjusted"] is None
        assert out["direction"] == "unmeasurable"
        assert out["survives_correction"] is False
        assert out["governing_interval"] == "none"
        assert "episode" in out["note"]
        assert out["clustering"]["station"]["n_groups"] == 8


def test_the_shipped_fusion_receipt_publishes_both_groupings():
    """Presence and consistency on the artifact, per split and per comparison."""
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "FUSION_RECEIPT.json").read_text(encoding="utf-8")
    )
    seen_inert_episode = False
    for split in receipt["splits"]:
        if split.get("degraded"):
            continue
        for key, comp in split["comparisons"].items():
            for field in ("ci95_episode", "ci95_station", "governing_interval",
                          "clustering", "mean_group_size_episode",
                          "mean_group_size_station"):
                assert field in comp, f"{split['split']}/{key} lacks {field}"
            if comp["mean_group_size_episode"] == 1.0:
                seen_inert_episode = True
                assert comp["clustering"]["episode"]["measurable"] is False, (
                    f"{split['split']}/{key} claims measurable episode clustering at a "
                    "mean group size of 1.0"
                )
            lo, hi = comp["ci95"]
            assert lo <= comp["ci95_station"][0] + 1e-12
            assert hi >= comp["ci95_station"][1] - 1e-12
    assert seen_inert_episode, (
        "no shipped comparison has an inert episode grouping, so the branch this "
        "finding is about is untested on real data"
    )

def test_the_design_effect_check_is_published_and_does_not_decide():
    """The second accounting of the same clustering, reported rather than chosen.

    On the shipped chronological comparison the two disagree at the corrected level: the
    station cluster bootstrap clears zero and a normal-theory widening of the
    observation-level interval by the measured design effect of 1.3741 does not. The
    bootstrap resamples the 35 stations directly and assumes neither normality nor a
    pure variance inflation, so it governs; the disagreement is published so nobody has
    to take that on trust.
    """
    ch, ref, lab, ep, st = _clustered_fixture()
    adj = clustered_multiplicity_adjusted(
        ch, ref, lab, ep, st, n_comparisons=6, n_boot=400, seed=1
    )
    sens = adj["design_effect_sensitivity"]
    assert sens["applicable"] is True
    assert sens["grouping"] == "station"
    assert sens["standard_error_factor"] > 1.0
    assert sens["widened_from"] == adj["ci_adjusted_episode"]
    assert sens["widened_ci"][0] < adj["ci_adjusted_episode"][0]
    assert sens["widened_ci"][1] > adj["ci_adjusted_episode"][1]
    # The published verdict comes from the bootstrap union, not from this.
    assert adj["survives_correction"] is (
        adj["ci_adjusted"][0] > 0 or adj["ci_adjusted"][1] < 0
    )


def test_the_design_effect_check_is_not_applied_twice():
    """With no observation-level grouping there is no independence interval to widen.

    Widening an already-clustered interval by a design effect measured on that same
    clustering would count it twice and manufacture a failure.
    """
    ch, ref, lab, _ep, st = _clustered_fixture()
    episodes = np.array([f"e{i // 2}" for i in range(len(lab))])
    out = clustered_paired_bootstrap(ch, ref, lab, episodes, st, n_boot=400, seed=1)
    sens = out["design_effect_sensitivity"]
    assert sens["applicable"] is False
    assert "no independence interval" in sens["reason"]


# ---------------------------------------------------------------------------
# SPACE-S7: correct over the family the rule reads, and resolve the endpoint
# ---------------------------------------------------------------------------


class TestPercentileResolution:
    """A Bonferroni endpoint the bootstrap cannot resolve is not a measurement.

    The correction pushes the endpoint into the tail, and a percentile bootstrap can
    only report a quantile it has draws for. At 4000 draws over a 21-comparison family
    the endpoint is the fifth-smallest resample. The failure is silent: the interval
    comes back looking like any other interval, which is why the resolution is published
    beside it.
    """

    def test_a_thin_tail_is_reported_as_unresolved(self):
        res = _percentile_resolution(4000, 0.05 / 21)
        assert res["draws_per_tail"] < 5.0
        assert res["endpoint_resolved"] is False
        assert res["n_boot_for_resolution"] > 4000

    def test_the_stated_draw_count_resolves_it(self):
        res = _percentile_resolution(50_000, 0.05 / 21)
        assert res["draws_per_tail"] >= res["min_draws_per_tail"]
        assert res["endpoint_resolved"] is True

    def test_the_required_draw_count_is_what_it_says(self):
        """n_boot_for_resolution must actually resolve, at the family it was asked about."""
        for n_comparisons in (1, 7, 21, 40):
            alpha = 0.05 / n_comparisons
            needed = _percentile_resolution(10, alpha)["n_boot_for_resolution"]
            assert _percentile_resolution(needed, alpha)["endpoint_resolved"] is True
            assert _percentile_resolution(needed - 1, alpha)["endpoint_resolved"] is False

    def test_the_correction_publishes_its_own_resolution(self):
        ch, ref, lab, ep, st = _clustered_fixture()
        adj = clustered_multiplicity_adjusted(
            ch, ref, lab, ep, st, n_comparisons=21, n_boot=400, seed=1
        )
        res = adj["percentile_resolution"]
        assert res["alpha"] == pytest.approx(0.05 / 21)
        assert res["endpoint_resolved"] is False, (
            "400 draws over a 21-comparison family cannot resolve the endpoint, so this "
            "fixture is not exercising the check"
        )


class TestCrossSplitFamily:
    """The family is every comparison the decision rule can read, across splits.

    The rule is a disjunction: retain a block if an arm containing it wins on ANY split
    above the training floor. Correcting over one split's seven comparisons while the
    rule scans seven on each of three splits is a correction over the wrong family, and
    the receipt's own justification already said the ladder runs five comparisons on each
    of four splits.
    """

    @staticmethod
    def _manifest(train_sizes: dict[str, int]) -> dict[str, Any]:
        splits = {}
        nxt = 1
        for name, n_train in train_sizes.items():
            ids = list(range(nxt, nxt + n_train + 60))
            nxt += n_train + 60
            splits[name] = {
                "train": ids[:n_train],
                "calibration": ids[n_train:n_train + 30],
                "test": ids[n_train + 30:],
            }
        return {"splits": splits}

    def test_only_splits_above_the_training_floor_count(self):
        manifest = self._manifest({"a": 400, "b": 350, "c": 100})
        rows = {i: {} for i in range(1, 2000)}
        names = eligible_split_names(manifest, rows, ["a", "b", "c"])
        assert names == ["a", "b"], names

    def test_the_size_matched_control_is_not_a_split_the_rule_reads(self):
        manifest = self._manifest({"chronological": 400, "chronological_size_matched": 400})
        rows = {i: {} for i in range(1, 2000)}
        names = eligible_split_names(
            manifest, rows, ["chronological", "chronological_size_matched"]
        )
        assert names == ["chronological"]

    def test_an_unrequested_or_missing_split_cannot_inflate_the_family(self):
        manifest = self._manifest({"a": 400, "b": 400})
        rows = {i: {} for i in range(1, 2000)}
        assert eligible_split_names(manifest, rows, ["a"]) == ["a"]
        assert eligible_split_names(manifest, rows, ["a", "nope"]) == ["a"]

    def test_a_partition_with_no_decisive_rows_is_excluded(self):
        """Eligibility is over decisive rows, which is what usable_ids filters to."""
        manifest = self._manifest({"a": 400})
        rows = {i: {} for i in range(1, 100)}   # most of split a's ids are not decisive
        assert eligible_split_names(manifest, rows, ["a"]) == []

    def test_the_family_size_is_decided_before_anything_is_fitted(self):
        """The count comes from the manifest and the decisive rows, nothing else.

        A family size that depended on a scored result could be influenced by which
        result looked good, which is the failure a correction exists to prevent.
        """
        manifest = self._manifest({"a": 400, "b": 400})
        rows = {i: {} for i in range(1, 2000)}
        first = eligible_split_names(manifest, rows, ["a", "b"])
        second = eligible_split_names(manifest, rows, ["b", "a"])
        assert first == ["a", "b"] and second == ["b", "a"]
        assert len(first) == len(second)


def test_the_shipped_receipt_measures_the_arm_it_ships():
    """Every split reports the risk-coverage behaviour of the arm the queue is ranked by.

    This exists because it was briefly lost. Pointing the selective block at the arm the
    corrected ablation rule recommends looked like a tightening, and it silently deleted
    the shipped arm's risk-coverage comparison from all four splits, along with the
    measurement the kill-gate document cites for it. The arm that ships is decided by
    ``SHIPPED_ARM``, which the ranker reads, so the two can never differ again; what this
    checks is that the figures are present and labelled with the arm they describe.
    """
    from pipeline.tracetriage.fusion import SHIPPED_ARM

    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "FUSION_RECEIPT.json").read_text(encoding="utf-8")
    )
    assert receipt["ablation_conclusion"]["shipped_arm"] == SHIPPED_ARM
    scores = receipt["ablation_conclusion"]["shipped_arm_scores"]
    assert scores, "the shipped arm ships without a measured score"

    checked = 0
    for split in receipt["splits"]:
        if split.get("degraded"):
            continue
        sel = split.get("selective") or {}
        assert sel.get("aurc_shipped_arm_name") == SHIPPED_ARM, (
            f"{split['split']} labels its shipped-arm figures "
            f"{sel.get('aurc_shipped_arm_name')!r}"
        )
        assert "aurc_shipped_arm" in sel, (
            f"{split['split']} reports no risk-coverage area for {SHIPPED_ARM}"
        )
        if "aurc_shipped_vs_image_only" in sel:
            checked += 1
        else:
            assert sel.get("aurc_shipped_not_measured_reason"), (
                f"{split['split']} omits the shipped arm's comparison without saying why"
            )
    assert checked > 0, (
        "no split compares the shipped arm against the reference, so the receipt cannot "
        "say whether the arm being shipped selects better than the one it is built on"
    )


def test_the_receipt_states_whether_what_ships_is_what_is_recommended():
    """The disagreement is on the artifact, not only in the code that can produce it."""
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "FUSION_RECEIPT.json").read_text(encoding="utf-8")
    )
    conclusion = receipt["ablation_conclusion"]
    stated = conclusion["shipped_arm_vs_recommendation"]
    assert stated["ships"] == conclusion["shipped_arm"]
    assert stated["corrected_recommends"] == conclusion["recommended_arm"]
    assert stated["agree"] is (stated["ships"] == stated["corrected_recommends"])
    assert len(stated["note"]) >= 40
    for block in stated["shipped_blocks_without_corrected_support"]:
        assert block in conclusion["shipped_blocks"], (
            f"{block} is listed as unsupported but is not a block the product ships"
        )
        assert (
            conclusion["multiplicity_corrected"]["blocks"][block]["decision"] != "RETAIN"
        ), f"{block} is listed as unsupported while the corrected rule retains it"


def test_the_shipped_receipt_corrects_over_the_cross_split_family():
    """The receipt's family size must equal seven per split the conclusion says it used."""
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "FUSION_RECEIPT.json").read_text(encoding="utf-8")
    )
    splits_used = receipt["ablation_conclusion"]["splits_used"]
    expected = 7 * len(splits_used)
    seen = []
    for split in receipt["splits"]:
        for entry in (split.get("multiplicity_adjusted") or {}).values():
            seen.append(entry["n_comparisons"])
        selective = split.get("selective") or {}
        if "multiplicity_family_size" in selective:
            seen.append(selective["multiplicity_family_size"])
    assert seen, "no corrected comparison in the receipt"
    assert set(seen) == {expected}, (
        f"the receipt corrects over {sorted(set(seen))} comparisons while the rule reads "
        f"{len(splits_used)} splits, which is {expected}"
    )


def test_the_shipped_receipt_resolves_its_corrected_endpoints():
    """Every published Bonferroni endpoint has enough draws behind it to mean something."""
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "FUSION_RECEIPT.json").read_text(encoding="utf-8")
    )
    checked = 0
    for split in receipt["splits"]:
        for key, entry in (split.get("multiplicity_adjusted") or {}).items():
            res = entry.get("percentile_resolution")
            assert res, f"{split['split']}/{key} publishes no percentile resolution"
            checked += 1
            assert res["endpoint_resolved"] is True, (
                f"{split['split']}/{key} corrected endpoint sits at draw "
                f"{res['draws_per_tail']:.1f}; {res['n_boot_for_resolution']} draws needed"
            )
        for name, entry in (split.get("selective") or {}).items():
            if not isinstance(entry, dict) or "percentile_resolution" not in entry:
                continue
            res = entry["percentile_resolution"]
            checked += 1
            assert res["endpoint_resolved"] is True, (
                f"{split['split']}/{name} corrected endpoint sits at draw "
                f"{res['draws_per_tail']:.1f}"
            )
    assert checked > 0, "nothing in the receipt reports a corrected endpoint"


def test_the_conclusion_states_what_its_retained_blocks_rest_on():
    """A RETAIN on one comparison, or one that fails the design-effect check, is flagged."""
    receipt = json.loads(
        (REPO_ROOT / "artifacts" / "FUSION_RECEIPT.json").read_text(encoding="utf-8")
    )
    conclusion = receipt["ablation_conclusion"]
    assert "fragility" in conclusion
    # The corrected rule retains nothing on this corpus, so the loop below has no rows to
    # check. Say that here rather than let an empty list pass for a satisfied criterion: a
    # fragility row with no RETAIN behind it would be qualifying a verdict the conclusion
    # does not reach, and it is the same defect in the other direction.
    if not [
        b for b, v in conclusion["multiplicity_corrected"]["blocks"].items()
        if v["decision"] == "RETAIN"
    ]:
        assert conclusion["fragility"] == [], (
            "no block survives correction, so there is nothing to qualify, and the "
            f"conclusion still carries {len(conclusion['fragility'])} fragility rows"
        )
    retained = [
        b for b, v in conclusion["multiplicity_corrected"]["blocks"].items()
        if v["decision"] == "RETAIN"
    ]
    flagged = {row["block"] for row in conclusion["fragility"]}
    for block in retained:
        entry = conclusion["multiplicity_corrected"]["blocks"][block]
        if len(entry["better_on"]) == 1:
            assert block in flagged, (
                f"{block} is retained on the single comparison {entry['better_on']} and "
                "the conclusion does not say so"
            )
    for row in conclusion["fragility"]:
        assert row["concerns"], "a fragility row with no stated concern"
        assert row["comparison"]
