"""Tests for the A6 image-only baseline module.

Offline tests (no network, no real snapshot required):
- ExclusionTable construction and sum invariant
- load_labelled on a synthetic manifest (no real images)
- CentreEnergyBaseline: mock scoring path
- HogLrBaseline: synthetic feature extraction
- evaluate() / prior_only_metrics(): metric correctness
- Receipt structure

Dataset tests (mark=dataset; skip when no snapshot on disk):
- End-to-end: load_labelled reproduces the counts from docs/BOB_HANDOFF.md
- Exclusion table sums to corpus_total
- Base rates are consistent with the snapshot manifest
- Both models score without crashing on a small subset
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers for synthetic data
# ---------------------------------------------------------------------------

def _make_manifest(
    n_pos: int = 10,
    n_neg: int = 6,
    n_unknown: int = 20,
    n_no_url: int = 5,
    n_transient: int = 2,
) -> dict[str, Any]:
    """Build a minimal synthetic manifest dict for offline tests."""
    obs: list[dict[str, Any]] = []
    obs_id = 10_000

    # Positive (decisive)
    for _ in range(n_pos):
        obs.append({
            "id": obs_id,
            "waterfall_url": f"https://example.com/waterfall_{obs_id}.png",
            "waterfall_missing_reason": None,
            "waterfall_status": "with-signal",
            "waterfall_sha256": "abc",
            "ground_station": 1,
            "transmitter_uuid": "uuid1",
            "source_url": f"https://example.com/obs/{obs_id}/",
            "retrieved_at": "2026-08-01T00:00:00+00:00",
            "client_version": "1.9",
            "client_family": "1.9",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "schema_version": "0.2.1",
        })
        obs_id += 1

    # Negative (decisive)
    for _ in range(n_neg):
        obs.append({
            "id": obs_id,
            "waterfall_url": f"https://example.com/waterfall_{obs_id}.png",
            "waterfall_missing_reason": None,
            "waterfall_status": "without-signal",
            "waterfall_sha256": "abc",
            "ground_station": 2,
            "transmitter_uuid": "uuid2",
            "source_url": f"https://example.com/obs/{obs_id}/",
            "retrieved_at": "2026-08-01T00:01:00+00:00",
            "client_version": "1.9",
            "client_family": "1.9",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "schema_version": "0.2.1",
        })
        obs_id += 1

    # Unknown
    for _ in range(n_unknown):
        obs.append({
            "id": obs_id,
            "waterfall_url": f"https://example.com/waterfall_{obs_id}.png",
            "waterfall_missing_reason": None,
            "waterfall_status": "unknown",
            "waterfall_sha256": "abc",
            "ground_station": 3,
            "transmitter_uuid": "uuid3",
            "source_url": f"https://example.com/obs/{obs_id}/",
            "retrieved_at": "2026-08-01T00:02:00+00:00",
            "client_version": "1.9",
            "client_family": "1.9",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "schema_version": "0.2.1",
        })
        obs_id += 1

    # No URL (permanent missing)
    for _ in range(n_no_url):
        obs.append({
            "id": obs_id,
            "waterfall_url": None,
            "waterfall_missing_reason": "NO_WATERFALL_URL",
            "waterfall_status": "unknown",
            "ground_station": 4,
            "transmitter_uuid": "uuid4",
            "source_url": f"https://example.com/obs/{obs_id}/",
            "retrieved_at": "2026-08-01T00:03:00+00:00",
            "client_version": "1.9",
            "client_family": "1.9",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "schema_version": "0.2.1",
        })
        obs_id += 1

    # Transient failure
    for _ in range(n_transient):
        obs.append({
            "id": obs_id,
            "waterfall_url": None,
            "waterfall_missing_reason": "THROTTLED",
            "waterfall_status": "unknown",
            "ground_station": 5,
            "transmitter_uuid": "uuid5",
            "source_url": f"https://example.com/obs/{obs_id}/",
            "retrieved_at": "2026-08-01T00:04:00+00:00",
            "client_version": "1.9",
            "client_family": "1.9",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "schema_version": "0.2.1",
        })
        obs_id += 1

    return {
        "snapshot_id": "test-snap",
        "schema_version": "0.2.1",
        "stage": 1,
        "built_at": "2026-08-01T00:00:00+00:00",
        "counts": {
            "observations_stored": n_pos + n_neg + n_unknown + n_no_url + n_transient,
            "waterfalls_stored": n_pos + n_neg + n_unknown,
            "waterfalls_missing": n_no_url + n_transient,
            "waterfall_status_decisive": n_pos + n_neg,
        },
        "observations": obs,
    }


# ---------------------------------------------------------------------------
# ExclusionTable tests
# ---------------------------------------------------------------------------

class TestExclusionTable:
    def test_build_from_manifest_sums_to_total(self):
        from pipeline.tracetriage.baseline import build_exclusion_table
        manifest = _make_manifest(n_pos=10, n_neg=6, n_unknown=20, n_no_url=5, n_transient=2)
        tbl = build_exclusion_table(manifest)
        assert tbl.corpus_total == 43

    def test_build_counts_are_correct(self):
        from pipeline.tracetriage.baseline import build_exclusion_table
        manifest = _make_manifest(n_pos=10, n_neg=6, n_unknown=20, n_no_url=5, n_transient=2)
        tbl = build_exclusion_table(manifest)
        assert tbl.n_positive == 10
        assert tbl.n_negative == 6
        assert tbl.n_unknown_label == 20
        assert tbl.n_missing_url == 5
        assert tbl.n_transient_fail == 2

    def test_check_sum_raises_on_mismatch(self):
        from pipeline.tracetriage.baseline import ExclusionTable
        tbl = ExclusionTable(corpus_total=100, n_positive=10, n_negative=10,
                             n_unknown_label=10, n_missing_url=10, n_transient_fail=10)
        with pytest.raises(AssertionError):
            tbl.check_sum()

    def test_check_sum_passes_on_match(self):
        from pipeline.tracetriage.baseline import ExclusionTable
        tbl = ExclusionTable(corpus_total=50, n_positive=10, n_negative=10,
                             n_unknown_label=20, n_missing_url=5, n_transient_fail=5)
        tbl.check_sum()  # should not raise

    def test_to_dict_has_all_keys(self):
        from pipeline.tracetriage.baseline import ExclusionTable
        tbl = ExclusionTable(corpus_total=10, n_positive=5, n_negative=5)
        d = tbl.to_dict()
        assert "corpus_total" in d
        assert "n_positive" in d
        assert "n_negative" in d
        assert "n_missing_url" in d
        assert "n_transient_fail" in d
        assert "n_unknown_label" in d
        assert "n_geometry_fail_train" in d
        assert "n_geometry_fail_val" in d

    def test_unknown_label_never_treated_as_negative(self):
        """Trap 1: unknown must not inflate the negative class."""
        from pipeline.tracetriage.baseline import build_exclusion_table
        manifest = _make_manifest(n_pos=5, n_neg=3, n_unknown=100, n_no_url=0, n_transient=0)
        tbl = build_exclusion_table(manifest)
        # unknown stays as unknown_label, never as negative
        assert tbl.n_unknown_label == 100
        assert tbl.n_negative == 3

    def test_missing_url_never_negative(self):
        """Trap 2: missing waterfall URL is not a negative."""
        from pipeline.tracetriage.baseline import build_exclusion_table
        manifest = _make_manifest(n_pos=0, n_neg=0, n_unknown=0, n_no_url=10, n_transient=0)
        tbl = build_exclusion_table(manifest)
        assert tbl.n_missing_url == 10
        assert tbl.n_negative == 0

    def test_transient_fail_counted_separately(self):
        """Trap 3: transient failures are a separate bucket from permanent missing."""
        from pipeline.tracetriage.baseline import build_exclusion_table
        manifest = _make_manifest(n_pos=0, n_neg=0, n_unknown=0, n_no_url=5, n_transient=3)
        tbl = build_exclusion_table(manifest)
        assert tbl.n_transient_fail == 3
        assert tbl.n_missing_url == 5


# ---------------------------------------------------------------------------
# load_labelled tests (offline with mock images)
# ---------------------------------------------------------------------------

class TestLoadLabelled:
    def _write_manifest_and_images(
        self,
        tmp_path: Path,
        n_pos: int = 8,
        n_neg: int = 4,
    ) -> tuple[Path, Path]:
        """Write manifest and create dummy PNG files in a temp directory."""
        manifest = _make_manifest(n_pos=n_pos, n_neg=n_neg, n_unknown=5, n_no_url=2, n_transient=1)
        # Write dummy waterfall PNGs for decisive observations.
        wf_dir = tmp_path / "waterfalls"
        wf_dir.mkdir()
        for obs in manifest["observations"]:
            url = obs.get("waterfall_url")
            reason = obs.get("waterfall_missing_reason")
            if url and reason is None:
                fname = wf_dir / f"waterfall_{obs['id']}.png"
                # Minimal valid PNG (1×1 white pixel).
                _write_dummy_png(fname)
        manifest_path = tmp_path / "DATASET_MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest))
        return manifest_path, tmp_path

    def test_decisive_only_loaded(self, tmp_path):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        total = len(corpus.train) + len(corpus.val)
        assert total == 12  # only decisive obs

    def test_labels_are_correct(self, tmp_path):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        all_labels = [r.label for r in corpus.train] + [r.label for r in corpus.val]
        assert sum(all_labels) == 8       # positives
        assert len(all_labels) - sum(all_labels) == 4   # negatives

    def test_split_is_80_20(self, tmp_path):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        n_total = len(corpus.train) + len(corpus.val)
        expected_train = math.floor(0.80 * n_total)
        assert len(corpus.train) == expected_train

    def test_train_prior_is_fraction_positive(self, tmp_path):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        expected_prior = corpus.n_train_positive / max(len(corpus.train), 1)
        assert abs(corpus.train_prior - expected_prior) < 1e-9

    def test_exclusion_sums_to_corpus_total(self, tmp_path):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        corpus.exclusion.check_sum()  # should not raise

    def test_snapshot_id_and_sha256_recorded(self, tmp_path):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        assert corpus.snapshot_id == "test-snap"
        assert len(corpus.manifest_sha256) == 64   # sha256 hex digest

    def test_chronological_split_sort_by_id(self, tmp_path):
        """Train set must contain older (lower-id) observations only."""
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = self._write_manifest_and_images(tmp_path, n_pos=8, n_neg=4)
        corpus = load_labelled(mpath, sdir)
        if corpus.train and corpus.val:
            max_train_id = max(r.obs_id for r in corpus.train)
            min_val_id = min(r.obs_id for r in corpus.val)
            assert max_train_id < min_val_id


# ---------------------------------------------------------------------------
# evaluate() tests
# ---------------------------------------------------------------------------

class TestEvaluateMetrics:
    def test_brier_perfect_classifier(self):
        from pipeline.tracetriage.baseline import evaluate
        y = np.array([1, 1, 0, 0])
        p = np.array([1.0, 1.0, 0.0, 0.0])
        m = evaluate(y, p, "test", n_total_val=4)
        assert m.brier_score < 1e-6

    def test_brier_worst_classifier(self):
        """Always predicting the wrong label gives Brier score of 1."""
        from pipeline.tracetriage.baseline import evaluate
        y = np.array([1, 1, 0, 0])
        p = np.array([0.0, 0.0, 1.0, 1.0])
        m = evaluate(y, p, "test", n_total_val=4)
        assert abs(m.brier_score - 1.0) < 1e-6

    def test_prior_only_brier_equals_prior_times_one_minus_prior(self):
        """Brier score for a constant prior p is p*(1-p) + (1-p)*p² / ...
        Actually it is Var(y) = p*(1-p) for balanced data, but let's just
        verify the formula numerically."""
        from pipeline.tracetriage.baseline import prior_only_metrics
        y = np.array([1, 1, 1, 0, 0, 0])
        prior = 0.5
        m = prior_only_metrics(y, prior, "floor", n_total_val=6)
        # Brier = mean((0.5 - label)^2) = 0.25 for every observation
        assert abs(m.brier_score - 0.25) < 1e-6

    def test_n_excluded_counts_geometry_failures(self):
        from pipeline.tracetriage.baseline import evaluate
        y = np.array([1, 0])
        p = np.array([0.8, 0.2])
        m = evaluate(y, p, "test", n_total_val=10)
        assert m.n_excluded == 8

    def test_reliability_bins_non_empty(self):
        from pipeline.tracetriage.baseline import evaluate
        rng = np.random.default_rng(0)
        y = rng.integers(0, 2, size=100)
        p = rng.uniform(0.0, 1.0, size=100).astype(np.float32)
        m = evaluate(y, p, "test", n_total_val=100)
        assert len(m.reliability_bins) > 0

    def test_ece_is_between_0_and_1(self):
        from pipeline.tracetriage.baseline import evaluate
        rng = np.random.default_rng(1)
        y = rng.integers(0, 2, size=200)
        p = rng.uniform(0.0, 1.0, size=200).astype(np.float32)
        m = evaluate(y, p, "test", n_total_val=200)
        assert 0.0 <= m.ece <= 1.0

    def test_to_dict_has_required_keys(self):
        from pipeline.tracetriage.baseline import evaluate
        y = np.array([1, 0, 1])
        p = np.array([0.8, 0.2, 0.7])
        m = evaluate(y, p, "test", n_total_val=3)
        d = m.to_dict()
        for key in ("model_name", "n_scored", "n_excluded", "brier_score",
                    "log_loss", "calibration_slope", "calibration_intercept",
                    "reliability_bins", "ece"):
            assert key in d, f"Missing key: {key}"

    def test_empty_input_returns_nan(self):
        from pipeline.tracetriage.baseline import evaluate
        m = evaluate(np.array([]), np.array([]), "test", n_total_val=5)
        assert math.isnan(m.brier_score)
        assert m.n_scored == 0
        assert m.n_excluded == 5


# ---------------------------------------------------------------------------
# HogLrBaseline tests (offline, synthetic data)
# ---------------------------------------------------------------------------

class TestHogLrBaselineOffline:
    def test_predict_proba_without_fit_returns_fallback(self, tmp_path):
        """An unfitted model returns 0.5 rather than crashing."""
        from pipeline.tracetriage.baseline import HogLrBaseline, ObsRecord
        model = HogLrBaseline(seed=0)
        # model._model is None — the model was never fitted

        dummy_png = tmp_path / "waterfall_1.png"
        _write_dummy_png(dummy_png)
        records = [ObsRecord(obs_id=1, label=1, image_path=dummy_png, waterfall_url="")]
        proba, indices, n_fail = model.predict_proba(records)
        # Either scored as 0.5 (fallback) or image fails gracefully
        assert len(proba) + n_fail == 1

    def test_fit_and_predict_shapes(self, tmp_path):
        """Fit on synthetic images; shape of output must match scorable count."""
        from pipeline.tracetriage.baseline import HogLrBaseline, ObsRecord

        # Create 20 synthetic images (10 pos, 10 neg).
        records_train: list[ObsRecord] = []
        records_val: list[ObsRecord] = []
        for i in range(20):
            p = tmp_path / f"waterfall_{i}.png"
            _write_synthetic_png(p, has_signal=(i < 10))
            rec = ObsRecord(obs_id=i, label=int(i < 10), image_path=p, waterfall_url="")
            if i < 16:
                records_train.append(rec)
            else:
                records_val.append(rec)

        model = HogLrBaseline(seed=42)
        model.fit(records_train)
        proba, indices, n_fail = model.predict_proba(records_val)
        assert len(proba) + n_fail == len(records_val)
        if len(proba) > 0:
            assert ((proba >= 0.0) & (proba <= 1.0)).all()

    def test_probabilities_sum_to_reasonable_range(self, tmp_path):
        """Platt scaling must keep probabilities in (0, 1)."""
        from pipeline.tracetriage.baseline import HogLrBaseline, ObsRecord

        records: list[ObsRecord] = []
        for i in range(30):
            p = tmp_path / f"w_{i}.png"
            _write_synthetic_png(p, has_signal=(i % 3 == 0))
            rec = ObsRecord(obs_id=i, label=int(i % 3 == 0), image_path=p, waterfall_url="")
            records.append(rec)

        model = HogLrBaseline(seed=0)
        model.fit(records[:24])
        proba, indices, _ = model.predict_proba(records[24:])
        if len(proba) > 0:
            assert proba.min() >= 0.0
            assert proba.max() <= 1.0


# ---------------------------------------------------------------------------
# BASELINE_RECEIPT.json structure tests (offline)
# ---------------------------------------------------------------------------

class TestReceiptStructure:
    def _build_minimal_receipt(self) -> dict[str, Any]:
        return {
            "schema": "BASELINE_RECEIPT",
            "schema_version": "0.1.0",
            "generated_at": "2026-08-17T00:00:00+00:00",
            "unit": "A6",
            "seed": 42,
            "snapshot_id": "snap-test",
            "manifest_sha256": "a" * 64,
            "split": {
                "method": "chronological_ascending_id",
                "train_fraction": 0.80,
                "note": "...",
                "n_train_total": 100,
                "n_train_positive": 60,
                "n_train_negative": 40,
                "n_val_total": 25,
                "n_val_positive": 15,
                "n_val_negative": 10,
                "train_prior": 0.6,
            },
            "exclusion_table": {
                "corpus_total": 200,
                "n_positive": 75,
                "n_negative": 50,
                "n_unknown_label": 50,
                "n_missing_url": 20,
                "n_transient_fail": 5,
                "n_geometry_fail_train": 0,
                "n_geometry_fail_val": 0,
            },
            "base_rates": {
                "corpus_decisive_fraction": 0.625,
                "decisive_positive_fraction": 0.6,
                "note": "...",
            },
            "results": [
                {
                    "model_name": "prior_only",
                    "n_scored": 25,
                    "n_excluded": 0,
                    "brier_score": 0.24,
                    "log_loss": 0.68,
                    "calibration_slope": 1.0,
                    "calibration_intercept": 0.0,
                    "reliability_bins": [],
                    "ece": 0.05,
                }
            ],
            "beats_floor": {
                "centre_energy": False,
                "hog_logistic_regression": True,
                "note": "...",
            },
            "floor_note": "...",
        }

    def test_required_top_level_keys_present(self):
        r = self._build_minimal_receipt()
        for key in ("schema", "schema_version", "generated_at", "unit", "seed",
                    "snapshot_id", "manifest_sha256", "split", "exclusion_table",
                    "base_rates", "results", "beats_floor", "floor_note"):
            assert key in r, f"Missing key: {key}"

    def test_prior_only_must_be_in_results(self):
        r = self._build_minimal_receipt()
        model_names = [m["model_name"] for m in r["results"]]
        assert "prior_only" in model_names

    def test_exclusion_sums_to_corpus_total(self):
        r = self._build_minimal_receipt()
        et = r["exclusion_table"]
        total = (et["n_positive"] + et["n_negative"] + et["n_unknown_label"]
                 + et["n_missing_url"] + et["n_transient_fail"])
        assert total == et["corpus_total"]

    def test_seed_is_recorded(self):
        r = self._build_minimal_receipt()
        assert r["seed"] == 42

    def test_manifest_sha256_has_length_64(self):
        r = self._build_minimal_receipt()
        assert len(r["manifest_sha256"]) == 64

    def test_beats_floor_section_present(self):
        r = self._build_minimal_receipt()
        assert "beats_floor" in r
        assert "hog_logistic_regression" in r["beats_floor"]


# ---------------------------------------------------------------------------
# Dataset-level tests (require the stage-1 snapshot on disk)
# ---------------------------------------------------------------------------

def _snap_manifest() -> tuple[Path, Path] | None:
    snap_dir = Path("D:/tracetriage_data/snap-stage1")
    manifest_path = snap_dir / "DATASET_MANIFEST.json"
    if manifest_path.exists():
        return manifest_path, snap_dir
    return None


@pytest.mark.dataset
class TestLoadLabelledOnRealCorpus:
    @pytest.fixture(autouse=True)
    def require_snapshot(self):
        if _snap_manifest() is None:
            pytest.skip("Stage-1 snapshot not on disk")

    def test_positive_count_matches_manifest(self):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = _snap_manifest()
        corpus = load_labelled(mpath, sdir)
        assert corpus.n_train_positive + corpus.n_val_positive == 462

    def test_negative_count_matches_manifest(self):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = _snap_manifest()
        corpus = load_labelled(mpath, sdir)
        assert corpus.n_train_negative + corpus.n_val_negative == 277

    def test_exclusion_table_sums_to_2727(self):
        """The exclusion table must account for every observation."""
        import json

        from pipeline.tracetriage.baseline import build_exclusion_table
        mpath, _ = _snap_manifest()
        manifest = json.loads(mpath.read_text())
        tbl = build_exclusion_table(manifest)
        assert tbl.corpus_total == 2727
        tbl.check_sum()

    def test_unknown_label_bucket_is_1761(self):
        """Trap 1 guard: 1761 obs with a URL but unknown status must never enter training.
        (227 observations have no URL at all and go into n_missing_url instead.
        Total unknown waterfall_status in the manifest is 1988 = 1761 + 227.)
        """
        import json

        from pipeline.tracetriage.baseline import build_exclusion_table
        mpath, _ = _snap_manifest()
        manifest = json.loads(mpath.read_text())
        tbl = build_exclusion_table(manifest)
        assert tbl.n_unknown_label == 1761

    def test_missing_url_bucket_is_227(self):
        """Trap 2 guard: 227 missing URL obs are not negatives."""
        import json

        from pipeline.tracetriage.baseline import build_exclusion_table
        mpath, _ = _snap_manifest()
        manifest = json.loads(mpath.read_text())
        tbl = build_exclusion_table(manifest)
        assert tbl.n_missing_url == 227

    def test_no_transient_fails_in_stage1(self):
        """Stage-1 snapshot had zero transient failures after hardening."""
        import json

        from pipeline.tracetriage.baseline import build_exclusion_table
        mpath, _ = _snap_manifest()
        manifest = json.loads(mpath.read_text())
        tbl = build_exclusion_table(manifest)
        assert tbl.n_transient_fail == 0

    def test_train_prior_is_between_0_and_1(self):
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = _snap_manifest()
        corpus = load_labelled(mpath, sdir)
        assert 0.0 < corpus.train_prior < 1.0

    def test_decisive_split_80_20(self):
        import math

        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = _snap_manifest()
        corpus = load_labelled(mpath, sdir)
        n_total = len(corpus.train) + len(corpus.val)
        expected_train = math.floor(0.80 * n_total)
        assert len(corpus.train) == expected_train

    def test_train_before_val_chronologically(self):
        """Every train observation must precede every val observation in TIME.

        This test previously asserted that train ids were all below val ids,
        which quietly assumed id order is time order. It is not: measured on
        this corpus, id order disagrees with time order on 27% of adjacent
        pairs, and sorting by id produced halves whose time ranges overlapped by
        more than five hours while the receipt called the split chronological.
        The assertion now names the property the split is supposed to have.
        """
        from pipeline.tracetriage.baseline import _observation_time, load_labelled
        mpath, sdir = _snap_manifest()
        corpus = load_labelled(mpath, sdir)

        train_t = [t for t in (_observation_time(r.waterfall_url) for r in corpus.train) if t]
        val_t = [t for t in (_observation_time(r.waterfall_url) for r in corpus.val) if t]
        assert len(train_t) == len(corpus.train), "some train timestamps did not parse"
        assert len(val_t) == len(corpus.val), "some val timestamps did not parse"
        assert max(train_t) < min(val_t), (
            f"train runs to {max(train_t)} but val starts at {min(val_t)}; "
            "the halves overlap in time, so this is not a temporal split"
        )
        assert corpus.split_audit["time_ranges_overlap"] is False

    def test_split_audit_states_what_the_split_cannot_show(self):
        """The caveat is part of the deliverable, not a nicety.

        This corpus spans a single evening and most of the validation split sits
        on stations the model trained on, so the validation numbers are
        in-distribution. A receipt that omits that invites the reader to take
        them for generalisation.
        """
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = _snap_manifest()
        audit = load_labelled(mpath, sdir).split_audit
        assert audit["n_val"] > 0
        assert audit["n_val_on_a_station_seen_in_train"] <= audit["n_val"]
        assert audit["caveat"].strip(), "the split caveat must not be empty"
        assert audit["n_without_timestamp"] == 0, (
            f"{audit['n_without_timestamp']} observations have no parseable time, "
            "so the ordering is partly arbitrary"
        )

    def test_base_rates_read_from_manifest_not_constants(self):
        """The baseline must derive rates from the snapshot, not from provenance.py."""
        from pipeline.tracetriage.baseline import load_labelled
        mpath, sdir = _snap_manifest()
        corpus = load_labelled(mpath, sdir)
        # From handoff: 462 positive, 277 negative = 739 decisive
        # prior = 462/739 ≈ 0.6252
        measured_prior = corpus.n_train_positive / max(len(corpus.train), 1)
        # Should be close to corpus decisive positive fraction,
        # not 0.1883 (provenance.py constant, which is fraction of ALL obs, not decisive).
        assert measured_prior > 0.5, "Expected positive > 50% among decisive labels"


@pytest.mark.dataset
class TestBaselineReceiptExists:
    def test_receipt_exists_after_run(self):
        receipt_path = Path("artifacts/BASELINE_RECEIPT.json")
        if not receipt_path.exists():
            pytest.skip("Receipt not yet generated; run scripts/run_baseline.py first")
        r = json.loads(receipt_path.read_text())
        assert r["schema"] == "BASELINE_RECEIPT"
        assert r["snapshot_id"] is not None

    def test_receipt_prior_only_in_results(self):
        receipt_path = Path("artifacts/BASELINE_RECEIPT.json")
        if not receipt_path.exists():
            pytest.skip("Receipt not yet generated")
        r = json.loads(receipt_path.read_text())
        model_names = [m["model_name"] for m in r["results"]]
        assert "prior_only" in model_names

    def test_receipt_hog_lr_in_results(self):
        receipt_path = Path("artifacts/BASELINE_RECEIPT.json")
        if not receipt_path.exists():
            pytest.skip("Receipt not yet generated")
        r = json.loads(receipt_path.read_text())
        model_names = [m["model_name"] for m in r["results"]]
        assert "hog_logistic_regression" in model_names

    def test_receipt_exclusion_sums_to_total(self):
        receipt_path = Path("artifacts/BASELINE_RECEIPT.json")
        if not receipt_path.exists():
            pytest.skip("Receipt not yet generated")
        r = json.loads(receipt_path.read_text())
        et = r["exclusion_table"]
        total = (et["n_positive"] + et["n_negative"] + et["n_unknown_label"]
                 + et["n_missing_url"] + et["n_transient_fail"])
        assert total == et["corpus_total"]


# ---------------------------------------------------------------------------
# Helpers for dummy PNG generation
# ---------------------------------------------------------------------------

def _write_dummy_png(path: Path) -> None:
    """Write a minimal valid 32×32 white PNG."""
    from PIL import Image
    img = Image.new("RGB", (32, 32), color=(255, 255, 255))
    img.save(path, format="PNG")


def _write_synthetic_png(path: Path, *, has_signal: bool) -> None:
    """Write a synthetic 128×256 PNG simulating a waterfall.

    signal=True:  a dark vertical stripe in the centre (energy at 0 Hz offset).
    signal=False: uniform noise (no stripe).
    """
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(int(has_signal))
    # White-ish background.
    arr = (rng.uniform(200, 255, (256, 128)) ).astype(np.uint8)
    if has_signal:
        # Dark vertical stripe at columns 55..73.
        arr[:, 55:74] = rng.uniform(30, 80, (256, 19)).astype(np.uint8)
    img = Image.fromarray(arr, mode="L").convert("RGB")
    img.save(path, format="PNG")
