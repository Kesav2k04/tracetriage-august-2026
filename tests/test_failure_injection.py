"""Failure injection: every mode must produce a NAMED degraded state.

The rule this suite exists to enforce is that an absence is never published as a
measurement. Not a blank frame, not a zero, not a silent success, and not a name that
belongs to a different cause. A test that asserts only "no exception escaped" does not
count, so every test here asserts the exact reason string.

Twelve modes are in scope. Six were already covered in the module they belong to and are
not repeated here:

  malformed image     MALFORMED_PNG  tests/test_waterfall.py::test_malformed_png_returns_degraded
  blank image         BLANK_IMAGE    tests/test_waterfall.py::test_blank_image_returns_degraded
  missing TLE         MISSING_TLE    tests/test_physics.py::TestDegradedStates::test_missing_tle1
  stale TLE           STALE_TLE      tests/test_physics.py::TestDegradedStates::test_stale_tle
  request times out   TIMEOUT        tests/test_snapshot.py, TestDownloadWaterfall,
                                     test_timeout_returns_timeout_reason
  absent bins, fit    NO_HZ_PER_PX   tests/test_corridor_fit.py,
                                     test_missing_inputs_are_named_degraded_states

The six below were uncovered, or were covered against the wrong input. Two of them had
no named reason in the code at all until this suite was written, and one had no
implementation: nothing counted the traces in a waterfall, so a second satellite in the
same image was averaged into the background the first one is measured against.
``corridor_fit.second_trace_evidence`` names that now, and the incidence across the
shipped corpus is measured in ``artifacts/SECOND_TRACE_SURVEY.json`` rather than
asserted here, because a detector's value is how often it fires on real data.

Every anchor is recorded in docs/DEGRADED_STATE_RECON.md, read out of the source rather
than from a docstring, and each test below was confirmed to go red against the behaviour
it replaces.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import numpy as np
import pytest
from PIL import Image

from pipeline.tracetriage.corridor_fit import (
    max_coherent_jump_px,
    second_trace_evidence,
)
from pipeline.tracetriage.physics import corridor_for_obs
from pipeline.tracetriage.snapshot import download_waterfall
from pipeline.tracetriage.waterfall import (
    _DegradedError,
    _derive_hz_per_px,
    parse_waterfall,
)

REPO = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> Any:
    """Import a file under scripts/ by path, the way tests/test_console_export.py does."""
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# A physically plausible record that reaches the pass-timing step: the TLE parses, its
# epoch is within a day of the pass, and the station coordinates are present. Same ISS
# pass over Prague as tests/test_physics.py, restated here so this suite owns its input.
_OBS: dict[str, Any] = {
    "id": 99000002,
    "start": "2024-01-01T01:22:30Z",
    "end": "2024-01-01T01:33:00Z",
    "station_lat": 50.073,
    "station_lng": 14.437,
    "station_alt": 200.0,
    "tle0": "ISS (ZARYA)",
    "tle1": "1 25544U 98067A   24001.50000000  .00002182  00000-0  44988-4 0  9992",
    "tle2": "2 25544  51.6416  77.8062 0003071  51.8048 308.3459 15.49601040429996",
    "client_metadata": json.dumps(
        {
            "radio": {
                "name": "gr-satnogs",
                "version": "2.3.4",
                "parameters": {"rx-freq": "437525000", "samp-rate-rx": "2.5e6"},
            }
        }
    ),
    "observation_frequency": 437_525_000,
    "waterfall_status": "with-signal",
    "status": "good",
}


def _obs(**overrides: Any) -> dict[str, Any]:
    o = dict(_OBS)
    o.update(overrides)
    return o


def _png_bytes(colour: tuple[int, int, int] = (10, 20, 30), size: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(colour: tuple[int, int, int] = (10, 20, 30), size: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Mode 5: absent frequency bins, at the image level
# ---------------------------------------------------------------------------


class TestAbsentFrequencyAxis:
    """NO_AXIS_DETECTED, asserted exactly.

    The existing coverage was ``assert degraded in ("NO_AXIS_DETECTED",
    "UNKNOWN_LAYOUT")`` on a black image, which passes whichever of the two the code
    returns and cannot tell a lost axis from a lost layout. These call the axis
    derivation directly, which is the only way to choose the branch.
    """

    def test_one_labelled_tick_cannot_make_a_pair(self):
        with pytest.raises(_DegradedError) as exc:
            _derive_hz_per_px([100.0], [1000])
        assert exc.value.args[0] == "NO_AXIS_DETECTED"

    def test_ticks_with_no_labels_at_all(self):
        with pytest.raises(_DegradedError) as exc:
            _derive_hz_per_px([100.0, 200.0, 300.0], [None, None, None])
        assert exc.value.args[0] == "NO_AXIS_DETECTED"

    def test_labelled_ticks_too_close_to_measure(self):
        # Two labelled ticks 3 px apart. The pair exists and the scale it implies is
        # noise, so no estimate is produced. This is the branch that would otherwise
        # divide by a 3 px baseline and publish the result as a measured Hz/px.
        with pytest.raises(_DegradedError) as exc:
            _derive_hz_per_px([100.0, 103.0], [1000, 2000])
        assert exc.value.args[0] == "NO_AXIS_DETECTED"

    def test_a_measurable_axis_is_not_degraded(self):
        # The control. Without it the three above would pass against a function that
        # raised NO_AXIS_DETECTED unconditionally.
        hz_per_px, confidence = _derive_hz_per_px([100.0, 200.0], [1000, 3000])
        assert hz_per_px == pytest.approx(20.0)
        assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# Mode 6: wrong start offset
# ---------------------------------------------------------------------------


class TestPassWindow:
    """A broken recording window used to be published as MISSING_STATION.

    The station coordinates are present in every case below. The old code returned the
    name of a missing station with the comment "timing is always present; fail
    gracefully", which sends a reader to a field that was never the problem.
    """

    def test_unparseable_start(self):
        r = corridor_for_obs(_obs(start="not-a-timestamp"))
        assert r.degraded == "UNPARSEABLE_PASS_WINDOW"
        assert r.uncorrected is None
        assert r.corrected is None

    def test_unparseable_end(self):
        r = corridor_for_obs(_obs(end=""))
        assert r.degraded == "UNPARSEABLE_PASS_WINDOW"

    def test_end_before_start(self):
        r = corridor_for_obs(
            _obs(start="2024-01-01T01:33:00Z", end="2024-01-01T01:22:30Z")
        )
        assert r.degraded == "NONPOSITIVE_PASS_WINDOW"

    def test_zero_length_window(self):
        r = corridor_for_obs(
            _obs(start="2024-01-01T01:22:30Z", end="2024-01-01T01:22:30Z")
        )
        assert r.degraded == "NONPOSITIVE_PASS_WINDOW"

    def test_a_missing_station_is_still_a_missing_station(self):
        # The rename must not widen. A record with no station coordinates has to keep
        # reporting the station, not the window.
        o = _obs()
        del o["station_lat"]
        assert corridor_for_obs(o).degraded == "MISSING_STATION"

    def test_a_good_window_is_not_degraded(self):
        r = corridor_for_obs(_obs())
        assert r.degraded is None
        assert r.uncorrected is not None


# ---------------------------------------------------------------------------
# Mode 8: network unavailable
# ---------------------------------------------------------------------------


class TestNetworkUnavailable:
    """HTTP_ERROR has two producers and only one was exercised.

    The existing test injects a 500 response, which reaches the status branch. A machine
    with no route to the host never receives a response at all: the transport raises,
    and that is the branch "network unavailable" actually takes.
    """

    def _client_raising(self, exc: Exception) -> MagicMock:
        client = MagicMock()
        client.get.side_effect = exc
        return client

    def test_connect_error_is_named(self, tmp_path):
        client = self._client_raising(httpx.ConnectError("no route to host"))
        sha, nbytes, reason = download_waterfall(
            client, 11, "https://example.com/wf.png", tmp_path / "wf.png"
        )
        assert reason == "HTTP_ERROR"
        assert sha is None
        assert nbytes is None
        assert not (tmp_path / "wf.png").exists()

    def test_dns_failure_is_named(self, tmp_path):
        client = self._client_raising(httpx.ConnectError("name resolution failed"))
        _, _, reason = download_waterfall(
            client, 12, "https://example.invalid/wf.png", tmp_path / "wf.png"
        )
        assert reason == "HTTP_ERROR"

    def test_read_error_mid_transfer_is_named(self, tmp_path):
        client = self._client_raising(httpx.ReadError("connection reset"))
        _, _, reason = download_waterfall(
            client, 13, "https://example.com/wf.png", tmp_path / "wf.png"
        )
        assert reason == "HTTP_ERROR"


# ---------------------------------------------------------------------------
# Mode 9: missing model artifact
# ---------------------------------------------------------------------------


class TestMissingModelArtifact:
    """MODEL_ARTIFACT_MISSING reaches the receipt and nothing asserted it.

    contracts/triage_receipt.schema.json declares model_checksum_source, so a receipt
    with a null checksum validates either way. The value is what tells a reader whether
    the model was absent or merely unread.
    """

    def test_absent_artifact_is_named_and_carries_no_checksum(self, tmp_path):
        rts = _load_script("run_triage_slice")
        checksum, source = rts.model_checksum_and_source(tmp_path / "nothing.pkl")
        assert checksum is None
        assert source == "MODEL_ARTIFACT_MISSING"

    def test_present_artifact_reports_its_path_and_a_checksum(self, tmp_path):
        rts = _load_script("run_triage_slice")
        model = tmp_path / "hoglr_model.pkl"
        model.write_bytes(b"not a real model, but it has bytes")
        checksum, source = rts.model_checksum_and_source(model)
        assert source == "artifacts/hoglr_model.pkl"
        assert checksum is not None
        assert len(checksum) == 64


# ---------------------------------------------------------------------------
# Mode 10: unsupported client image format
# ---------------------------------------------------------------------------


class TestUnsupportedImageFormat:
    """A complete JPEG is neither malformed nor truncated.

    Before this, _load_rgb accepted anything PIL could decode, so a JPEG went on into
    layout detection and came back as UNKNOWN_LAYOUT, which names the layout and sends
    the reader after a client that draws its axes differently. The download-time magic
    check calls the same file TRUNCATED, which is false for a complete image.
    """

    def test_jpeg_is_named_by_its_format(self):
        result = parse_waterfall(_jpeg_bytes(), 99999, 100.0)
        assert result.degraded == "UNSUPPORTED_IMAGE_FORMAT"
        assert result.derivation == "failed"

    def test_gif_is_named_by_its_format(self):
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (10, 20, 30)).save(buf, format="GIF")
        result = parse_waterfall(buf.getvalue(), 99998, 100.0)
        assert result.degraded == "UNSUPPORTED_IMAGE_FORMAT"

    def test_png_is_not_rejected_for_its_format(self):
        # The control, and the reason the check tests fmt != "PNG" rather than keeping a
        # list of formats to reject: a PNG has to reach layout detection and fail there
        # on its own terms.
        result = parse_waterfall(_png_bytes(), 99997, 100.0)
        assert result.degraded != "UNSUPPORTED_IMAGE_FORMAT"


# ---------------------------------------------------------------------------
# Mode 11: empty queue after filtering
# ---------------------------------------------------------------------------


class TestEmptyQueueAfterFiltering:
    """An empty test partition is a named absence with a NOT_MEASURABLE verdict.

    Nothing in the suite referenced this path. It matters because the alternative to a
    named reason here is a lift computed over zero candidates, which is a ratio of two
    zeros dressed as a gate result.
    """

    def _fit_result(self, test_ids: list[int]) -> dict[str, Any]:
        return {
            "degraded": None,
            "test_ids": test_ids,
            "shipped_probs": {i: 0.5 for i in test_ids},
            "physics_only_probs": {i: 0.5 for i in test_ids},
            "image_uncertainty_probs": {i: 0.5 for i in test_ids},
            "ensemble_stds": {i: 0.1 for i in test_ids},
        }

    def test_empty_test_partition_is_named_not_zero(self, monkeypatch):
        rq = _load_script("run_queue")
        monkeypatch.setattr(
            rq, "fit_arm_for_split", lambda *a, **k: self._fit_result([])
        )

        out = rq.build_split_queue(
            "chronological", {}, {}, {}, {}, (None, {}), 7, 10, set()
        )

        assert out["degraded"] == "No test observations"
        assert out["gate6_result"]["verdict"] == "NOT_MEASURABLE"
        # The reason has to say which split and why, not merely that something failed.
        reason = out["gate6_result"]["not_measurable_reason"]
        assert "chronological" in reason
        assert "0 " in reason
        # No lift, no ranking, no queue: an empty container must not be published as one
        # of those with a value in it.
        assert "lift" not in out
        assert "queue" not in out

    def test_a_fit_failure_keeps_its_own_reason(self, monkeypatch):
        # The neighbouring guard. Both return a degraded dict and they must not collapse
        # into one message, because one means the arm would not fit and the other means
        # it fitted and had nothing to rank.
        rq = _load_script("run_queue")
        monkeypatch.setattr(
            rq,
            "fit_arm_for_split",
            lambda *a, **k: {"degraded": "TOO_FEW_TRAINING_ROWS"},
        )

        out = rq.build_split_queue(
            "cold_station", {}, {}, {}, {}, (None, {}), 7, 10, set()
        )

        assert out["degraded"] == "TOO_FEW_TRAINING_ROWS"
        assert out["gate6_result"]["verdict"] == "NOT_MEASURABLE"
        assert "TOO_FEW_TRAINING_ROWS" in out["gate6_result"]["not_measurable_reason"]


# ---------------------------------------------------------------------------
# Mode 7: multiple traces in one waterfall
# ---------------------------------------------------------------------------


_TRACE_H = 160
_TRACE_W = 320


def _noise_field(seed: int) -> np.ndarray:
    """Background with enough variation that a row has a non-zero MAD."""
    rng = np.random.default_rng(seed)
    lum = np.clip(rng.normal(40.0, 6.0, size=(_TRACE_H, _TRACE_W)), 0, 255)
    return lum.astype(np.uint8)[:, :, None].repeat(3, axis=2)


def _draw(img: np.ndarray, cols: np.ndarray, brightness: int = 200, width: int = 3):
    out = img.copy()
    half = width // 2
    for r in range(img.shape[0]):
        c = int(round(float(cols[r])))
        lo, hi = max(0, c - half), min(img.shape[1], c + half + 1)
        out[r, lo:hi, :] = brightness
    return out


def _s_curve(centre: float, swing: float, steepness: float = 3.0) -> np.ndarray:
    """The shape a Doppler trace has: steep at closest approach, flat at the ends."""
    t = np.linspace(-1.0, 1.0, _TRACE_H)
    return centre - swing * np.tanh(steepness * t)


class TestMultipleTraces:
    """A second satellite in the same waterfall, which nothing counted.

    One corridor is fitted and one path is scored, so a second carrier was averaged
    into the background the first is measured against. The image read as one satellite
    with noisier surroundings, which is a silent success rather than a named state.

    The hard part is not finding a second peak. Real waterfalls are full of second
    peaks. It is telling a second trace from interference, and the separator is physics:
    a real trace cannot move faster than Doppler allows, which is what
    max_coherent_jump_px converts into pixels.
    """

    def _box(self, h: int = _TRACE_H, w: int = _TRACE_W):
        from pipeline.tracetriage.waterfall import Box

        return Box(x0=0, y0=0, x1=w, y1=h)

    # A 12 px corridor half-width at the fitter's own search factor of 2.0.
    WINDOW_PX = 24.0
    # 119.4 Hz/s of peak Doppler slope at 123.46 Hz/px and 0.19 s/row, plus half the
    # 3 px matched-filter width.
    MAX_JUMP_PX = 1.68375

    def _measure(self, img: np.ndarray, h: int = _TRACE_H, w: int = _TRACE_W):
        return second_trace_evidence(
            img,
            self._box(h, w),
            window_px=self.WINDOW_PX,
            max_jump_px=self.MAX_JUMP_PX,
        )

    def test_one_trace_is_not_two(self):
        img = _draw(_noise_field(11), _s_curve(160.0, 40.0))
        ev = self._measure(img)

        assert ev["measurable"] is True
        assert ev["reason"] is None
        assert ev["n_rows_primary_detected"] > 100
        assert ev["second_frac_of_primary_rows"] == 0.0

    def test_a_second_trace_is_named(self):
        img = _draw(_noise_field(12), _s_curve(160.0, 40.0))
        img = _draw(img, _s_curve(250.0, 30.0, steepness=2.0))
        ev = self._measure(img)

        assert ev["reason"] == "MULTIPLE_TRACES_SUSPECTED"
        assert ev["coherent"] is True
        assert ev["second_frac_of_primary_rows"] >= 0.30
        assert ev["median_jump_px"] <= self.MAX_JUMP_PX

    def test_interference_is_not_a_second_trace(self):
        # This is the test the coherence bound exists for. Sporadic bright pixels put a
        # second peak above the detection bar in most rows, so a detector that counted
        # second peaks and stopped there would report a second satellite here.
        rng = np.random.default_rng(13)
        img = _draw(_noise_field(13), _s_curve(160.0, 40.0))
        for r in range(_TRACE_H):
            c = int(rng.integers(10, _TRACE_W - 10))
            img[r, c - 1 : c + 2, :] = 200
        ev = self._measure(img)

        # The fraction bar is cleared and the coherence bar is not, which is the whole
        # point: assert both, or this passes for the wrong reason.
        assert ev["second_frac_of_primary_rows"] > 0.30
        assert ev["median_jump_px"] > ev["max_jump_px_allowed"]
        assert ev["coherent"] is False
        assert ev["reason"] is None

    def test_a_peak_inside_the_search_window_is_the_same_trace(self):
        # A trace 8 px from the first, well inside the fitter's 24 px window. By this
        # pipeline's own definition that is one trace, and calling it two would report a
        # second satellite for every wide carrier in the corpus.
        img = _draw(_noise_field(14), _s_curve(160.0, 40.0))
        img = _draw(img, _s_curve(168.0, 40.0))
        ev = self._measure(img)

        assert ev["reason"] is None
        assert ev["second_frac_of_primary_rows"] == 0.0

    def test_an_image_with_no_detection_is_unmeasurable_not_clean(self):
        # A flat image cannot answer the question. Reporting it as "no second trace"
        # would count it as evidence of a single trace, which it is not.
        flat = np.full((_TRACE_H, _TRACE_W, 3), 100, dtype=np.uint8)
        ev = self._measure(flat)

        assert ev["measurable"] is False
        assert ev["why_not"] == "TOO_FEW_DETECTED_ROWS"
        assert ev["reason"] is None

    def test_too_few_rows_is_named(self):
        tiny = np.full((6, _TRACE_W, 3), 100, dtype=np.uint8)
        ev = self._measure(tiny, h=6)

        assert ev["measurable"] is False
        assert ev["why_not"] == "TOO_FEW_ROWS"

    def test_a_plot_too_narrow_to_hold_two_peaks_is_named(self):
        narrow = np.full((_TRACE_H, 40, 3), 100, dtype=np.uint8)
        ev = self._measure(narrow, w=40)

        assert ev["measurable"] is False
        assert ev["why_not"] == "PLOT_TOO_NARROW"


class TestCoherentJumpBound:
    """The jump bound is derived from Doppler, not chosen to fit the data."""

    def test_the_arithmetic(self):
        # 119.4 Hz/s at 0.19 s per row is 22.686 Hz per row. At 123.46 Hz/px that is
        # 0.18375 px per row, plus half of the 3 px filter width.
        assert max_coherent_jump_px(123.46, 0.19) == pytest.approx(1.68375, abs=1e-5)

    def test_the_bound_scales_with_the_image(self):
        # A coarser frequency axis means the same Hz moves fewer pixels, so the bound
        # falls. A detector with one pixel bound for every image would be wrong on both.
        fine = max_coherent_jump_px(80.0, 0.19)
        coarse = max_coherent_jump_px(123.46, 0.19)
        assert fine > coarse

    def test_it_refuses_impossible_inputs(self):
        # A zero or negative scale is a missing measurement. Returning a number here
        # would put a fabricated bound into the comparison.
        with pytest.raises(ValueError):
            max_coherent_jump_px(0.0, 0.19)
        with pytest.raises(ValueError):
            max_coherent_jump_px(123.46, 0.0)
