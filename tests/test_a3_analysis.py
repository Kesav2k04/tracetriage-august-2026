"""Offline tests for the A3 Doppler investigation analysis.

The A3 verdict is the one answer nothing downstream survives being wrong about,
so the measurement that produces it is tested here against the two committed
waterfall fixtures, with the OCR reading taken from the committed cache. No
network, no model weights.

Two of these are regression tests for defects the fixtures caught:
  - the plot border sits inside the crop box and is brighter than any row, so
    without an edge margin it wins every argmax and reports a signal pinned to
    column 0
  - a single detection threshold can invent a track out of noise, so a verdict
    is only accepted when three settings agree
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"

sys.path.insert(0, str(REPO))
from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: E402


def _load_a3():
    """Import the investigation script by path; scripts/ is not a package."""
    spec = importlib.util.spec_from_file_location(
        "a3_doppler_investigation", REPO / "scripts" / "a3_doppler_investigation.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


a3 = _load_a3()

FLAT = "waterfall_832px_client_2.1.2.png"
FAINT = "waterfall_836px_client_v2.3.png"


def _geometry(name: str):
    cache = json.loads((FIXTURES / "ocr_labels.json").read_text(encoding="utf-8"))
    entry = cache[name]
    ocr = entry.get("ocr_results") if isinstance(entry, dict) else entry
    path = FIXTURES / name
    geom = parse_waterfall(
        image_data=path.read_bytes(),
        observation_id=1,
        pass_duration_s=600.0,
        rx_freq_hz=437_000_000.0,
        ocr_results=[tuple(x) for x in ocr],
    )
    rgb = np.array(Image.open(path).convert("RGB"))
    return geom, rgb


@pytest.fixture(scope="module")
def flat_fixture():
    return _geometry(FLAT)


@pytest.fixture(scope="module")
def faint_fixture():
    return _geometry(FAINT)


class TestEdgeMargin:
    def test_border_column_is_excluded(self, flat_fixture):
        """Without the margin the argmax pins to the border, not the carrier."""
        geom, rgb = flat_fixture
        _, x, _ = a3.measure_track(rgb, geom.crop_box, 8, 5.0)
        assert x.size > 0
        assert x.min() > a3.EDGE_MARGIN_PX, "track collapsed onto the plot border"
        assert x.max() < geom.crop_box.width() - a3.EDGE_MARGIN_PX

    def test_margin_is_added_back_to_the_reported_column(self, flat_fixture):
        """Columns are reported in crop-box coordinates, margin included."""
        geom, rgb = flat_fixture
        _, x, _ = a3.measure_track(rgb, geom.crop_box, 16, 5.0)
        centre = geom.centre_px
        offsets_hz = (x - centre) * geom.hz_per_px
        # The carrier on this fixture sits within a kilohertz of the axis zero.
        assert abs(float(np.median(offsets_hz))) < 2000.0


class TestFlatCarrier:
    def test_detected_in_every_block(self, flat_fixture):
        geom, rgb = flat_fixture
        fracs, x, z = a3.measure_track(rgb, geom.crop_box, 8, 5.0)
        n_blocks = (geom.crop_box.height() - 2 * a3.EDGE_MARGIN_PX) // 8
        assert len(fracs) > 0.9 * n_blocks
        assert float(np.median(z)) > 6.0

    def test_track_is_vertical_within_a_kilohertz(self, flat_fixture):
        geom, rgb = flat_fixture
        _, x, _ = a3.measure_track(rgb, geom.crop_box, 16, 5.0)
        hz = (x - geom.centre_px) * geom.hz_per_px
        swing = float(np.percentile(hz, 95) - np.percentile(hz, 5))
        assert swing < a3.SWING_CORRECTED_HZ

    def test_verdict_is_stable_across_settings(self, flat_fixture):
        """A carrier this strong must not depend on the threshold chosen."""
        geom, rgb = flat_fixture
        swings = []
        for block, z_min in a3.DETECTION_SETTINGS:
            _, x, _ = a3.measure_track(rgb, geom.crop_box, block, z_min)
            hz = (x - geom.centre_px) * geom.hz_per_px
            swings.append(float(np.percentile(hz, 95) - np.percentile(hz, 5)))
        assert max(swings) - min(swings) < 500.0


class TestScoring:
    def _curve(self, swing_hz: float = 20_000.0, n: int = 120):
        fracs = list(np.linspace(0.0, 1.0, n))
        # An S-curve in the shape the geometry produces: high on approach,
        # crossing zero at closest approach, low on recession.
        hz = list(swing_hz / 2.0 * np.cos(np.pi * np.asarray(fracs)))
        return fracs, hz

    def test_constant_offset_does_not_penalise_the_uncorrected_fit(self):
        """A satellite oscillator sits off nominal; that must not decide the answer."""
        fracs, hz = self._curve()
        meas_f = np.asarray(fracs)
        meas_hz = np.asarray(hz)
        base = a3.score_hypotheses(meas_f, meas_hz, fracs, hz)
        shifted = a3.score_hypotheses(meas_f, meas_hz + 4_000.0, fracs, hz)
        assert base["rms_vs_uncorrected_hz"] == pytest.approx(
            shifted["rms_vs_uncorrected_hz"], abs=1e-6
        )

    def test_matching_curve_reads_as_uncorrected(self):
        fracs, hz = self._curve()
        stats = a3.score_hypotheses(np.asarray(fracs), np.asarray(hz), fracs, hz)
        verdict, _ = a3.verdict_for(stats)
        assert verdict == "UNCORRECTED"

    def test_flat_track_reads_as_corrected(self):
        fracs, hz = self._curve()
        meas = np.full(len(fracs), 300.0)
        stats = a3.score_hypotheses(np.asarray(fracs), meas, fracs, hz)
        verdict, _ = a3.verdict_for(stats)
        assert verdict == "CORRECTED"

    def test_too_few_samples_is_unresolved_not_a_guess(self):
        fracs, hz = self._curve()
        few = np.asarray(fracs[: a3.MIN_SIGNAL_ROWS - 1])
        stats = a3.score_hypotheses(few, np.asarray(hz[: few.size]), fracs, hz)
        verdict, reason = a3.verdict_for(stats)
        assert verdict == "UNRESOLVED"
        assert "detectable signal" in reason

    def test_noise_matches_neither_hypothesis(self):
        """A track that is neither flat nor the predicted shape must not be forced."""
        fracs, hz = self._curve()
        rng = np.random.default_rng(0)
        noise = rng.uniform(-25_000, 25_000, size=len(fracs))
        stats = a3.score_hypotheses(np.asarray(fracs), noise, fracs, hz)
        verdict, _ = a3.verdict_for(stats)
        assert verdict == "UNRESOLVED"


class TestPagination:
    def test_next_cursor_is_read_from_the_link_header(self):
        header = (
            '<https://network.satnogs.org/api/observations/?cursor=cD0yMDI2&format=json>; '
            'rel="next"'
        )
        assert a3.next_cursor(header) == "cD0yMDI2"

    def test_absent_next_link_ends_paging(self):
        assert a3.next_cursor(None) is None
        assert a3.next_cursor('<https://example.invalid/?cursor=x>; rel="prev"') is None
