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
    auc,
    brier,
    build_design,
    calibration_slope_intercept,
    expected_calibration_error,
    grouped_bootstrap_statistic_difference,
    grouped_paired_bootstrap,
    multiplicity_adjusted,
)


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
        assert "physics" not in res["shipped_blocks"]

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

    def test_the_shipped_arm_must_be_one_the_ladder_measured(self) -> None:
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
        assert res["shipped_blocks"] == ["image", "corridor", "metadata"]
        assert res["multiplicity_corrected"]["shipped_arm_was_measured"] is False, (
            "image + corridor + metadata is not an arm on the ladder, and the receipt "
            "has to admit that rather than report a score for it"
        )

    def test_the_declared_shipped_arm_is_checked_against_the_measured_one(self) -> None:
        """The consistency guard on ``SHIPPED_ARM_CANDIDATE``.

        Without it, the selective block would keep reporting risk-coverage figures for
        whichever arm the constant names, even after the ablation started selecting a
        different one, and nothing in the receipt would say so.
        """
        mod = _load_run_fusion()
        with pytest.raises(SystemExit, match="ablation rule selected"):
            mod._check_shipped_arm_agrees({"shipped_arm": "full_fusion"})
        mod._check_shipped_arm_agrees({"shipped_arm": mod.SHIPPED_ARM_CANDIDATE})
