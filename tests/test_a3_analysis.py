"""Offline tests for the A3 Doppler investigation analysis.

The A3 verdict is the one answer nothing downstream survives being wrong about,
so the measurement that produces it is tested here against the committed
waterfall fixtures, with the OCR reading taken from the committed cache, plus
synthetic images whose correct answer is known by construction. No network, no
model weights.

Several of these are regression tests for defects found while running it:

  - The plot border sits inside the crop box and is brighter than anything in
    its row, so without an edge margin it wins every brightest-column search.
  - Averaging blocks of rows before finding the trace favours one hypothesis: a
    real Doppler curve crosses roughly a dozen columns inside one block near
    closest approach and is smeared away, while a stationary carrier survives.
  - Time runs bottom to top on a SatNOGS waterfall, and the plotted frequency
    axis runs against the Doppler sign. Both were assumed wrong at once, and
    because a Doppler curve is near odd-symmetric about closest approach the
    two errors cancelled and the fit looked excellent.
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


class _Box:
    """Minimal stand-in for the parser's Box, for synthetic images."""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    def width(self):
        return self.x1 - self.x0

    def height(self):
        return self.y1 - self.y0


@pytest.fixture(scope="module")
def flat_fixture():
    cache = json.loads((FIXTURES / "ocr_labels.json").read_text(encoding="utf-8"))
    entry = cache[FLAT]
    ocr = entry.get("ocr_results") if isinstance(entry, dict) else entry
    path = FIXTURES / FLAT
    geom = parse_waterfall(
        image_data=path.read_bytes(),
        observation_id=1,
        pass_duration_s=600.0,
        rx_freq_hz=437_000_000.0,
        ocr_results=[tuple(x) for x in ocr],
    )
    return geom, np.array(Image.open(path).convert("RGB"))


def _doppler_curve(swing_hz: float = 20_000.0, n: int = 240):
    """A curve with the shape the geometry produces: high, through zero, low."""
    fracs = list(np.linspace(0.0, 1.0, n))
    hz = list(swing_hz / 2.0 * np.cos(np.pi * np.asarray(fracs)))
    return fracs, hz


def _synthetic(
    curve_fracs,
    curve_hz,
    hz_per_px: float,
    sign: int,
    shape: str,
    amplitude: float = 40.0,
    seed: int = 7,
):
    """Paint a trace of a known shape into noise and return (rgb, box, centre).

    Time runs bottom to top, matching a real waterfall, so a test that assumed
    the other direction would fail here rather than silently pass.
    """
    h, w = 800, 400
    rng = np.random.default_rng(seed)
    img = rng.normal(90.0, 6.0, size=(h, w)).astype(np.float32)
    centre = w / 2.0

    row_fracs = 1.0 - (np.arange(h) + 0.5) / h
    predicted = np.interp(row_fracs, np.asarray(curve_fracs), np.asarray(curve_hz))
    cols = (
        centre + sign * predicted / hz_per_px
        if shape == "curved"
        else np.full(h, centre + 3.0)
    )

    for row, col in enumerate(cols):
        c = int(round(col))
        if 2 <= c < w - 2:
            img[row, c] += amplitude
            img[row, c - 1] += amplitude * 0.5
            img[row, c + 1] += amplitude * 0.5

    rgb = np.clip(np.stack([img] * 3, axis=-1), 0, 255).astype(np.uint8)
    return rgb, _Box(0, 0, w, h), centre


class TestEdgeMargin:
    def test_border_column_is_excluded(self, flat_fixture):
        """Without the margin the brightest column is the plot border."""
        geom, rgb = flat_fixture
        _, x, _ = a3.visible_track(rgb, geom.crop_box)
        assert x.size > 0
        assert x.min() > a3.EDGE_MARGIN_PX, "track collapsed onto the plot border"
        assert x.max() < geom.crop_box.width() - a3.EDGE_MARGIN_PX

    def test_reported_column_is_in_crop_coordinates(self, flat_fixture):
        geom, rgb = flat_fixture
        _, x, _ = a3.visible_track(rgb, geom.crop_box)
        offsets_hz = (x - geom.centre_px) * geom.hz_per_px
        assert abs(float(np.median(offsets_hz))) < 2000.0


class TestFlatCarrierFixture:
    def test_vertical_hypothesis_wins_decisively(self, flat_fixture):
        geom, rgb = flat_fixture
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        zs = a3.normalised_rows(rgb, geom.crop_box)
        scores = a3.matched_filter(zs, geom.centre_px, geom.hz_per_px, fracs, hz)
        primary = scores[a3.PRIMARY_WIDTH]
        assert primary["sigma_vertical"] > primary["sigma_curved"] + a3.SIGMA_MARGIN
        assert primary["sigma_vertical"] > a3.SIGMA_MIN

    def test_verdict_is_corrected(self, flat_fixture):
        geom, rgb = flat_fixture
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        zs = a3.normalised_rows(rgb, geom.crop_box)
        scores = a3.matched_filter(zs, geom.centre_px, geom.hz_per_px, fracs, hz)
        verdict, _, _ = a3.verdict_from_scores(scores, 20_000.0)
        assert verdict == "CORRECTED"

    def test_carrier_sits_near_axis_zero(self, flat_fixture):
        geom, rgb = flat_fixture
        fracs, hz = _doppler_curve()
        zs = a3.normalised_rows(rgb, geom.crop_box)
        scores = a3.matched_filter(zs, geom.centre_px, geom.hz_per_px, fracs, hz)
        assert abs(scores[a3.PRIMARY_WIDTH]["vertical_column_offset_hz"]) < 2000.0


class TestSyntheticShapes:
    HZ_PER_PX = 100.0

    def test_a_curved_trace_reads_as_uncorrected(self):
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        rgb, box, centre = _synthetic(fracs, hz, self.HZ_PER_PX, -1, "curved")
        zs = a3.normalised_rows(rgb, box)
        scores = a3.matched_filter(zs, centre, self.HZ_PER_PX, fracs, hz)
        verdict, reason, _ = a3.verdict_from_scores(scores, 20_000.0)
        assert verdict == "UNCORRECTED", reason

    def test_a_vertical_trace_reads_as_corrected(self):
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        rgb, box, centre = _synthetic(fracs, hz, self.HZ_PER_PX, -1, "flat")
        zs = a3.normalised_rows(rgb, box)
        scores = a3.matched_filter(zs, centre, self.HZ_PER_PX, fracs, hz)
        verdict, reason, _ = a3.verdict_from_scores(scores, 20_000.0)
        assert verdict == "CORRECTED", reason

    @pytest.mark.parametrize("painted_sign", [1, -1])
    def test_the_frequency_axis_sign_is_recovered_not_assumed(self, painted_sign):
        """The sign is the half of the orientation that cannot be read off a tick."""
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        rgb, box, centre = _synthetic(fracs, hz, self.HZ_PER_PX, painted_sign, "curved")
        zs = a3.normalised_rows(rgb, box)
        scores = a3.matched_filter(zs, centre, self.HZ_PER_PX, fracs, hz)
        assert scores[a3.PRIMARY_WIDTH]["frequency_axis_sign"] == painted_sign

    def test_a_time_reversed_curve_does_not_pass_as_the_right_one(self):
        """Guards the cancellation: flip time only and the fit must fall apart."""
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        rgb, box, centre = _synthetic(fracs, hz, self.HZ_PER_PX, -1, "curved")
        zs = a3.normalised_rows(rgb, box)

        good = a3.matched_filter(zs, centre, self.HZ_PER_PX, fracs, hz)
        reversed_hz = list(reversed(hz))
        bad = a3.matched_filter(zs, centre, self.HZ_PER_PX, fracs, reversed_hz)

        # Reversing time alone leaves a curve of the opposite handedness. The
        # sign scan can mirror it back, so what must not survive is the pairing
        # of a reversed curve with the sign the real one chose.
        good_sigma = good[a3.PRIMARY_WIDTH]["sigma_curved_by_sign"]["-1"]
        bad_sigma = bad[a3.PRIMARY_WIDTH]["sigma_curved_by_sign"]["-1"]
        assert good_sigma > 3 * bad_sigma

    def test_pure_noise_is_unresolved(self):
        fracs, hz = _doppler_curve(swing_hz=20_000.0)
        rgb, box, centre = _synthetic(fracs, hz, self.HZ_PER_PX, -1, "curved", amplitude=0.0)
        zs = a3.normalised_rows(rgb, box)
        scores = a3.matched_filter(zs, centre, self.HZ_PER_PX, fracs, hz)
        verdict, reason, _ = a3.verdict_from_scores(scores, 20_000.0)
        assert verdict == "UNRESOLVED"
        assert "no signal stands out" in reason


class TestVerdictGuards:
    def _scores(self, vertical: float, curved: float) -> dict:
        return {
            w: {
                "sigma_vertical": vertical,
                "sigma_curved": curved,
                "frequency_axis_sign": -1,
                "sigma_curved_by_sign": {"1": 0.0, "-1": curved},
                "vertical_column_offset_hz": 0.0,
                "curved_offset_hz": 0.0,
            }
            for w in a3.FILTER_WIDTHS
        }

    def test_a_small_predicted_swing_cannot_be_called(self):
        """Below a few kHz the two hypotheses draw nearly the same line."""
        verdict, reason, _ = a3.verdict_from_scores(self._scores(40.0, 2.0), 500.0)
        assert verdict == "UNRESOLVED"
        assert "too small to tell the two shapes apart" in reason

    def test_a_narrow_lead_is_not_a_verdict(self):
        verdict, reason, _ = a3.verdict_from_scores(self._scores(20.0, 19.0), 20_000.0)
        assert verdict == "UNRESOLVED"
        assert "neither shape leads" in reason

    def test_below_the_floor_is_unresolved(self):
        verdict, _, _ = a3.verdict_from_scores(
            self._scores(a3.SIGMA_MIN - 1, 0.5), 20_000.0
        )
        assert verdict == "UNRESOLVED"

    def test_filter_widths_must_agree(self):
        scores = self._scores(40.0, 2.0)
        scores[a3.FILTER_WIDTHS[-1]] = dict(scores[a3.FILTER_WIDTHS[-1]])
        scores[a3.FILTER_WIDTHS[-1]]["sigma_vertical"] = 2.0
        scores[a3.FILTER_WIDTHS[-1]]["sigma_curved"] = 40.0
        verdict, reason, _ = a3.verdict_from_scores(scores, 20_000.0)
        assert verdict == "UNRESOLVED"
        assert "filter widths disagree" in reason


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


class TestThrottleTolerance:
    def test_downloads_stop_without_losing_what_was_already_fetched(self, monkeypatch):
        """A closed rate-limit window must cost the remaining images, not the run."""
        calls = {"n": 0}

        def fake_download(obs):
            calls["n"] += 1
            if calls["n"] > 2:
                raise a3.Throttled("rate limited for another 3000s")
            return b"png-bytes"

        monkeypatch.setattr(a3, "download_waterfall", fake_download)
        images = a3.download_all([{"id": i} for i in range(5)])
        assert set(images) == {0, 1}

    def test_other_download_errors_do_not_stop_the_batch(self, monkeypatch):
        def fake_download(obs):
            if obs["id"] == 1:
                raise RuntimeError("connection reset")
            return b"png-bytes"

        monkeypatch.setattr(a3, "download_waterfall", fake_download)
        images = a3.download_all([{"id": i} for i in range(4)])
        assert set(images) == {0, 2, 3}
