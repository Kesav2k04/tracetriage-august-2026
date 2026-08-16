"""Acceptance tests for pipeline/tracetriage/waterfall.py.

Acceptance criteria (from A2 task prompt):
  1. Hz/px within 1% of 123.46 (836px fixture) and 80.00 (832px fixture)
  2. Crop excludes ALL axis text and colorbar, asserted on pixel content
  3. Malformed PNG, blank image, zero-byte and unknown layout each return a
     NAMED degraded state (not raised exception)
  4. Property test: crop box always strictly inside image bounds
  5. Every emitted record validates against waterfall_geometry.schema.json
  6. pytest -m "not network" passes with network disabled

All tests are offline (no network marker needed).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PILImage

from pipeline.tracetriage.waterfall import (
    Box,
    WaterfallGeometry,
    _detect_colorbar,
    _detect_plot_box,
    _detect_ticks,
    _load_rgb,
    crop_array,
    parse_waterfall,
    validate_against_schema,
)

# ---------------------------------------------------------------------------
# Constants matching the fixture measurements (see tests/fixtures/README.md and
# docs/SATNOGS_API_RECON.md section 7).
# ---------------------------------------------------------------------------
FIXTURE_836 = Path(__file__).parent / "fixtures" / "waterfall_836px_client_v2.3.png"
FIXTURE_832 = Path(__file__).parent / "fixtures" / "waterfall_832px_client_2.1.2.png"

# Reading the axis glyphs needs a neural OCR model and its weights. Deriving
# Hz/px from what was read does not. Pinning the second step behind the first
# would mean 123.46 and 80.00, the two numbers the whole corridor rests on,
# could only ever be checked on one laptop: every CI runner and every clean
# clone would skip them. So the OCR reading is captured once by
# scripts/dump_ocr_fixture.py, committed, and replayed here. The live model is
# exercised separately by the ocr-marked test at the bottom of this file.
_OCR_CACHE = json.loads(
    (Path(__file__).parent / "fixtures" / "ocr_labels.json").read_text(encoding="utf-8")
)


def _cached_ocr(image_name: str) -> list[tuple[float, str, float]]:
    return [(float(x), str(t), float(c)) for x, t, c in _OCR_CACHE[image_name]["ocr_results"]]


OCR_836 = _cached_ocr("waterfall_836px_client_v2.3.png")
OCR_832 = _cached_ocr("waterfall_832px_client_2.1.2.png")


def ocr_for(fixture: Path) -> list[tuple[float, str, float]]:
    return _cached_ocr(Path(fixture).name)

HZ_PX_836 = 123.46     # measured Hz/px for 836px client
HZ_PX_832 = 80.00      # measured Hz/px for 832px client
HZ_PX_TOLERANCE = 0.01  # 1% relative tolerance

OBS_ID_836 = 14513023
OBS_ID_832 = 14519869
PASS_DURATION_836 = 207.0   # seconds
PASS_DURATION_832 = 180.0   # seconds
RX_FREQ = 436_990_000.0     # Hz

# Known plot-box values from the recon (see docs/SATNOGS_API_RECON.md sec 7)
PLOT_BOX_836 = Box(66, 10, 686, 1550)
PLOT_BOX_832 = Box(74, 7, 677, 1556)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_blank_png(w: int = 100, h: int = 100) -> bytes:
    """Return PNG bytes for a pure-white image."""
    arr = np.full((h, w, 3), 255, dtype=np.uint8)
    pil = PILImage.fromarray(arr)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _make_black_png(w: int = 100, h: int = 100) -> bytes:
    """Return PNG bytes for a pure-black image (not blank by our definition)."""
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    pil = PILImage.fromarray(arr)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _make_solid_colour_rgba_png(r: int, g: int, b: int, a: int = 128) -> bytes:
    """Return a tiny RGBA PNG with a uniform colour."""
    arr = np.full((10, 10, 4), (r, g, b, a), dtype=np.uint8)
    pil = PILImage.fromarray(arr, mode="RGBA")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _truncated_png() -> bytes:
    """Return a PNG with bytes cut off mid-stream."""
    data = _make_blank_png(50, 50)
    return data[: len(data) // 2]


def _fixture_bytes(path: Path) -> bytes:
    return path.read_bytes()


# ---------------------------------------------------------------------------
# 1. Hz/px within 1% of measured values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,obs_id,duration,expected_hz", [
    (FIXTURE_836, OBS_ID_836, PASS_DURATION_836, HZ_PX_836),
    (FIXTURE_832, OBS_ID_832, PASS_DURATION_832, HZ_PX_832),
])
def test_hz_per_px_within_1pct(fixture, obs_id, duration, expected_hz):
    """Hz/px must be within 1% of the measured value on both client layouts."""
    result = parse_waterfall(fixture, obs_id, duration, RX_FREQ,
                              ocr_results=ocr_for(fixture))
    assert result.derivation != "failed", (
        f"Expected successful derivation, got failed: {result.degraded}"
    )
    assert result.hz_per_px is not None
    rel_err = abs(result.hz_per_px - expected_hz) / expected_hz
    assert rel_err < HZ_PX_TOLERANCE, (
        f"hz_per_px={result.hz_per_px:.4f}, expected={expected_hz}, "
        f"relative error={rel_err:.4%} (limit {HZ_PX_TOLERANCE:.0%})"
    )


def test_hz_per_px_836_exact_value():
    """836px fixture: hz_per_px ≈ 123.46 Hz/px."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.hz_per_px is not None
    assert abs(result.hz_per_px - HZ_PX_836) / HZ_PX_836 < 0.01


def test_hz_per_px_832_exact_value():
    """832px fixture: hz_per_px ≈ 80.00 Hz/px."""
    result = parse_waterfall(FIXTURE_832, OBS_ID_832, PASS_DURATION_832, RX_FREQ,
                              ocr_results=OCR_832)
    assert result.hz_per_px is not None
    assert abs(result.hz_per_px - HZ_PX_832) / HZ_PX_832 < 0.01


# ---------------------------------------------------------------------------
# 2. Crop excludes axis text and colorbar, asserted on pixel content
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,obs_id,duration", [
    (FIXTURE_836, OBS_ID_836, PASS_DURATION_836),
    (FIXTURE_832, OBS_ID_832, PASS_DURATION_832),
])
def test_crop_excludes_axis_text(fixture, obs_id, duration):
    """The cropped array must contain no pure-white columns.

    Axis labels and tick text are black-on-white, so any column that is
    entirely white is from the margin, not from the spectrogram data.
    The spectrogram data is multi-coloured and should have no all-white columns.
    """
    result = parse_waterfall(fixture, obs_id, duration, RX_FREQ,
                              ocr_results=ocr_for(fixture))
    assert result.derivation != "failed", f"Parse failed: {result.degraded}"
    assert result.crop_box is not None

    # Load the image and extract crop.
    img_data = fixture.read_bytes()
    rgb, _, _ = _load_rgb(img_data)
    cropped = crop_array(rgb, result.crop_box)

    h, w, _ = cropped.shape
    # No column in the crop should be entirely white (255,255,255).
    col_min = cropped.min(axis=0).sum(axis=1)    # (W,), min brightness per column
    all_white_cols = np.where(col_min >= 3 * 250)[0]
    assert len(all_white_cols) == 0, (
        f"Crop has {len(all_white_cols)} all-white columns (axis text leak): "
        f"cols={all_white_cols[:10].tolist()}"
    )


def test_crop_836_excludes_colorbar():
    """836px: crop_box.x1 must be strictly left of the colorbar at x=724."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.derivation != "failed"
    assert result.crop_box is not None
    # The colorbar starts at x=724 (measured). The crop must end before it.
    assert result.crop_box.x1 < 724, (
        f"crop_box.x1={result.crop_box.x1} is inside the colorbar (x=724..755)"
    )


def test_crop_836_colorbar_not_in_cropped_array():
    """836px: the crop must not include any pixel columns from the colorbar region.

    The colorbar occupies x=724..755 in the full image.  After cropping, the
    rightmost column of the crop array must map to a full-image x-coordinate
    strictly less than 724.  We verify this by comparing crop_box.x1 to the
    known colorbar x0, rather than by pixel density (the spectrogram data is
    itself highly non-white and would trigger a density-based test incorrectly).
    """
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.derivation != "failed"
    assert result.crop_box is not None

    # The crop must stop before the colorbar column 724.
    COLORBAR_X0 = 724
    assert result.crop_box.x1 < COLORBAR_X0, (
        f"crop_box.x1={result.crop_box.x1} reaches into the colorbar "
        f"(colorbar starts at x={COLORBAR_X0})"
    )

    # Additionally: verify the crop array dimensions are consistent.
    img_data = FIXTURE_836.read_bytes()
    rgb, _, _ = _load_rgb(img_data)
    cropped = crop_array(rgb, result.crop_box)
    expected_w = result.crop_box.width() + 1
    expected_h = result.crop_box.height() + 1
    assert cropped.shape == (expected_h, expected_w, 3), (
        f"crop_array shape {cropped.shape} does not match crop_box dimensions "
        f"({expected_h}h × {expected_w}w)"
    )


# ---------------------------------------------------------------------------
# 3. Error cases return named degraded states (no exception raised)
# ---------------------------------------------------------------------------

def test_zero_byte_file_returns_degraded():
    """Empty file bytes → ZERO_BYTE degraded state."""
    result = parse_waterfall(b"", 99999, 100.0)
    assert result.derivation == "failed"
    assert result.degraded == "ZERO_BYTE"


def test_malformed_png_returns_degraded():
    """Truncated PNG → MALFORMED_PNG degraded state."""
    result = parse_waterfall(_truncated_png(), 99999, 100.0)
    assert result.derivation == "failed"
    assert result.degraded == "MALFORMED_PNG"


def test_not_a_png_returns_degraded():
    """Random bytes that are not a PNG → MALFORMED_PNG."""
    result = parse_waterfall(b"not a png file at all XXXX", 99999, 100.0)
    assert result.derivation == "failed"
    assert result.degraded == "MALFORMED_PNG"


def test_blank_image_returns_degraded():
    """Pure-white image → BLANK_IMAGE degraded state."""
    result = parse_waterfall(_make_blank_png(), 99999, 100.0)
    assert result.derivation == "failed"
    assert result.degraded == "BLANK_IMAGE"


def test_no_timing_info_returns_degraded():
    """Valid PNG but no pass duration → NO_TIMING_INFO degraded state.

    seconds_per_px is required by the contract when derivation != 'failed'.
    Passing None for pass_duration_s must produce a named failure, not a
    silent null on an otherwise successful record.
    """
    result = parse_waterfall(
        FIXTURE_836, OBS_ID_836, pass_duration_s=None, ocr_results=OCR_836
    )
    assert result.derivation == "failed"
    assert result.degraded == "NO_TIMING_INFO"


def test_black_image_is_not_blank():
    """A pure-black image is NOT blank: it has non-white pixels.

    The parse attempt will fail (no plot structure), but the degraded reason
    should NOT be BLANK_IMAGE, it should be NO_AXIS_DETECTED or UNKNOWN_LAYOUT.
    """
    result = parse_waterfall(_make_black_png(), 99999, 100.0)
    assert result.derivation == "failed"
    assert result.degraded != "BLANK_IMAGE"
    assert result.degraded in ("NO_AXIS_DETECTED", "UNKNOWN_LAYOUT")


def test_rgba_source_does_not_raise():
    """RGBA source image must be accepted (converted to RGB internally)."""
    # Use a solid-colour RGBA image: it will fail structurally but not crash.
    result = parse_waterfall(_make_solid_colour_rgba_png(128, 64, 32, 200), 99999, 100.0)
    # Should return a degraded record, not raise.
    assert isinstance(result, WaterfallGeometry)
    assert result.derivation == "failed"


def test_zero_byte_preserves_obs_id():
    """The observation_id must be preserved even on failure."""
    result = parse_waterfall(b"", 12345678, 100.0)
    assert result.observation_id == 12345678


def test_all_degraded_states_have_non_null_reason():
    """Every failed record must carry a non-null, non-empty degraded reason."""
    cases = [
        (b"", 1),
        (_truncated_png(), 2),
        (_make_blank_png(), 3),
        (b"junk", 4),
    ]
    for data, obs_id in cases:
        result = parse_waterfall(data, obs_id, 100.0)
        assert result.derivation == "failed"
        assert result.degraded is not None and len(result.degraded) > 0, (
            f"obs {obs_id}: degraded is None or empty"
        )


# ---------------------------------------------------------------------------
# 4. Property test: crop box always strictly inside image bounds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,obs_id,duration", [
    (FIXTURE_836, OBS_ID_836, PASS_DURATION_836),
    (FIXTURE_832, OBS_ID_832, PASS_DURATION_832),
])
def test_crop_box_strictly_inside_image(fixture, obs_id, duration):
    """crop_box must be strictly inside the full image bounds."""
    result = parse_waterfall(fixture, obs_id, duration, RX_FREQ,
                              ocr_results=ocr_for(fixture))
    if result.derivation == "failed":
        pytest.skip(f"parse failed: {result.degraded}")

    assert result.crop_box is not None
    img_box = Box(0, 0, result.image_width - 1, result.image_height - 1)
    assert result.crop_box.strictly_inside(img_box), (
        f"crop_box={result.crop_box} is not strictly inside image "
        f"[0,0,{result.image_width-1},{result.image_height-1}]"
    )


@pytest.mark.parametrize("fixture,obs_id,duration", [
    (FIXTURE_836, OBS_ID_836, PASS_DURATION_836),
    (FIXTURE_832, OBS_ID_832, PASS_DURATION_832),
])
def test_crop_box_positive_dimensions(fixture, obs_id, duration):
    """crop_box must have positive width and height."""
    result = parse_waterfall(fixture, obs_id, duration, RX_FREQ,
                              ocr_results=ocr_for(fixture))
    if result.derivation == "failed":
        pytest.skip(f"parse failed: {result.degraded}")

    assert result.crop_box is not None
    assert result.crop_box.width() > 0
    assert result.crop_box.height() > 0


def test_crop_box_null_exactly_on_failed():
    """crop_box must be None when derivation == 'failed'."""
    result = parse_waterfall(b"", 99999, 100.0)
    assert result.derivation == "failed"
    assert result.crop_box is None


def test_crop_box_non_null_on_success():
    """crop_box must be non-None when derivation != 'failed'."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.derivation != "failed"
    assert result.crop_box is not None


# ---------------------------------------------------------------------------
# 5. Schema validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,obs_id,duration", [
    (FIXTURE_836, OBS_ID_836, PASS_DURATION_836),
    (FIXTURE_832, OBS_ID_832, PASS_DURATION_832),
])
def test_successful_record_validates_against_schema(fixture, obs_id, duration):
    """A successful parse must produce a record valid against the JSON schema."""
    result = parse_waterfall(fixture, obs_id, duration, RX_FREQ,
                              ocr_results=ocr_for(fixture))
    assert result.derivation != "failed", f"Unexpected failure: {result.degraded}"
    errors = validate_against_schema(result)
    assert errors == [], f"Schema validation errors: {errors}"


def test_failed_record_validates_against_schema():
    """A failed parse must also produce a schema-valid record."""
    result = parse_waterfall(b"", 99999, 100.0)
    assert result.derivation == "failed"
    errors = validate_against_schema(result)
    assert errors == [], f"Schema validation errors on failed record: {errors}"


def test_schema_rejects_failed_with_hz_per_px():
    """A record claiming derivation='failed' with a hz_per_px must be schema-invalid."""
    import jsonschema
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "waterfall_geometry.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    bad_record = {
        "observation_id": 1,
        "image_width": 836,
        "image_height": 1603,
        "plot_box": None,
        "crop_box": None,
        "hz_per_px": 123.46,   # must be null when derivation == "failed"
        "seconds_per_px": None,
        "centre_px": None,
        "derivation": "failed",
        "derivation_confidence": None,
        "degraded": "SOME_REASON",
    }
    errors = list(validator.iter_errors(bad_record))
    assert len(errors) > 0, "Schema should reject failed record with non-null hz_per_px"


def test_schema_rejects_success_without_hz_per_px():
    """A record claiming axis_ticks with null hz_per_px must be schema-invalid."""
    import jsonschema
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "waterfall_geometry.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    bad_record = {
        "observation_id": 1,
        "image_width": 836,
        "image_height": 1603,
        "plot_box": {"x0": 66, "y0": 10, "x1": 686, "y1": 1550},
        "crop_box": {"x0": 66, "y0": 10, "x1": 686, "y1": 1550},
        "hz_per_px": None,   # must be non-null when derivation != "failed"
        "seconds_per_px": 0.134,
        "centre_px": None,
        "derivation": "axis_ticks",
        "derivation_confidence": 0.95,
        "degraded": None,
    }
    errors = list(validator.iter_errors(bad_record))
    assert len(errors) > 0, "Schema should reject axis_ticks record with null hz_per_px"


# ---------------------------------------------------------------------------
# 6. to_dict output is JSON-serialisable and round-trips correctly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,obs_id,duration", [
    (FIXTURE_836, OBS_ID_836, PASS_DURATION_836),
    (FIXTURE_832, OBS_ID_832, PASS_DURATION_832),
])
def test_to_dict_is_json_serialisable(fixture, obs_id, duration):
    """to_dict() must produce a JSON-serialisable dict (no Box objects)."""
    result = parse_waterfall(fixture, obs_id, duration, RX_FREQ,
                              ocr_results=ocr_for(fixture))
    d = result.to_dict()
    serialised = json.dumps(d)
    assert len(serialised) > 0
    # Round-trip: the dict must parse back without errors.
    back = json.loads(serialised)
    assert back["observation_id"] == obs_id
    assert back["derivation"] in ("axis_ticks", "axis_ticks_ocr", "failed")


# ---------------------------------------------------------------------------
# 7. Specific field values
# ---------------------------------------------------------------------------

def test_observation_id_preserved_on_success():
    """observation_id must equal the value passed in."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.observation_id == OBS_ID_836


def test_image_dimensions_836():
    """image_width and image_height must match the PNG dimensions."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.image_width == 836
    assert result.image_height == 1603


def test_image_dimensions_832():
    """image_width and image_height must match the PNG dimensions."""
    result = parse_waterfall(FIXTURE_832, OBS_ID_832, PASS_DURATION_832, RX_FREQ,
                              ocr_results=OCR_832)
    assert result.image_width == 832
    assert result.image_height == 1603


def test_seconds_per_px_836():
    """seconds_per_px must equal pass_duration / plot_height (within float tolerance)."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.seconds_per_px is not None
    assert result.plot_box is not None
    expected = PASS_DURATION_836 / result.plot_box.height()
    assert abs(result.seconds_per_px - expected) < 1e-9


def test_centre_px_is_null_without_freq():
    """centre_px must be None when rx_freq_hz and observation_freq_hz are both None."""
    result = parse_waterfall(
        FIXTURE_836, OBS_ID_836, PASS_DURATION_836,
        rx_freq_hz=None, observation_freq_hz=None,
    )
    # If parse succeeds, centre_px must be None (no frequency reference).
    # If parse fails for an unrelated reason, skip.
    if result.derivation != "failed":
        assert result.centre_px is None, (
            f"centre_px should be None without freq info, got {result.centre_px}"
        )


def test_centre_px_non_null_with_freq():
    """centre_px must be non-None when rx_freq is provided and axis reads cleanly."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    if result.derivation != "failed":
        assert result.centre_px is not None


def test_degraded_null_on_success():
    """degraded must be None on a successful parse."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.derivation != "failed"
    assert result.degraded is None


def test_derivation_confidence_in_range():
    """derivation_confidence must be in [0, 1] on success."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.derivation != "failed"
    assert result.derivation_confidence is not None
    assert 0.0 <= result.derivation_confidence <= 1.0


def test_plot_box_matches_known_836():
    """plot_box for 836px fixture must match the recon-measured value."""
    result = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    assert result.derivation != "failed"
    assert result.plot_box is not None
    assert result.plot_box.x0 == PLOT_BOX_836.x0, f"plot_box.x0={result.plot_box.x0}"
    assert result.plot_box.x1 == PLOT_BOX_836.x1, f"plot_box.x1={result.plot_box.x1}"


def test_plot_box_matches_known_832():
    """plot_box for 832px fixture must match the recon-measured value."""
    result = parse_waterfall(FIXTURE_832, OBS_ID_832, PASS_DURATION_832, RX_FREQ,
                              ocr_results=OCR_832)
    assert result.derivation != "failed"
    assert result.plot_box is not None
    assert result.plot_box.x0 == PLOT_BOX_832.x0, f"plot_box.x0={result.plot_box.x0}"
    assert result.plot_box.x1 == PLOT_BOX_832.x1, f"plot_box.x1={result.plot_box.x1}"


# ---------------------------------------------------------------------------
# 8. crop_array helper
# ---------------------------------------------------------------------------

def test_crop_array_shape():
    """crop_array must return an array of the expected dimensions."""
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    box = Box(10, 20, 50, 60)
    cropped = crop_array(rgb, box)
    expected_h = 60 - 20 + 1
    expected_w = 50 - 10 + 1
    assert cropped.shape == (expected_h, expected_w, 3)


def test_crop_array_is_view_or_copy():
    """crop_array must return a numpy array (view or copy, not a list)."""
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    box = Box(0, 0, 10, 10)
    result = crop_array(rgb, box)
    assert isinstance(result, np.ndarray)


# ---------------------------------------------------------------------------
# 9. Internal helper unit tests
# ---------------------------------------------------------------------------

def test_detect_plot_box_836():
    """_detect_plot_box must return the known bounds for the 836px image."""
    rgb, _, _ = _load_rgb(FIXTURE_836)
    box = _detect_plot_box(rgb)
    assert box.x0 == 66
    assert box.x1 == 686


def test_detect_plot_box_832():
    """_detect_plot_box must return the known bounds for the 832px image."""
    rgb, _, _ = _load_rgb(FIXTURE_832)
    box = _detect_plot_box(rgb)
    assert box.x0 == 74
    assert box.x1 == 677


def test_detect_ticks_836():
    """Seven tick marks expected on the 836px image."""
    rgb, _, _ = _load_rgb(FIXTURE_836)
    box = _detect_plot_box(rgb)
    ticks = _detect_ticks(rgb, box)
    assert len(ticks) == 7, f"Expected 7 ticks, got {len(ticks)}: {ticks}"


def test_detect_ticks_832():
    """Five tick marks expected on the 832px image."""
    rgb, _, _ = _load_rgb(FIXTURE_832)
    box = _detect_plot_box(rgb)
    ticks = _detect_ticks(rgb, box)
    assert len(ticks) == 5, f"Expected 5 ticks, got {len(ticks)}: {ticks}"


def test_detect_colorbar_836():
    """Colorbar must be detected on the 836px image (at x≈724..755)."""
    rgb, _, _ = _load_rgb(FIXTURE_836)
    plot_box = _detect_plot_box(rgb)
    cb = _detect_colorbar(rgb, plot_box)
    assert cb is not None, "No colorbar detected on 836px image"
    # Must be to the right of the plot box.
    assert cb.x0 > plot_box.x1
    # Must be in the expected x-range (measured from recon).
    assert 720 <= cb.x0 <= 730, f"Colorbar x0={cb.x0} out of expected range 720..730"


def test_detect_colorbar_832_outside_crop():
    """832px may have a detected element to the right, but it must not affect crop."""
    result = parse_waterfall(FIXTURE_832, OBS_ID_832, PASS_DURATION_832, RX_FREQ,
                              ocr_results=OCR_832)
    assert result.derivation != "failed"
    # The 832px crop_box must end at or before the plot_box x1.
    assert result.crop_box is not None
    assert result.crop_box.x1 <= PLOT_BOX_832.x1 + 1


def test_load_rgb_converts_rgba():
    """RGBA input must be converted to RGB (3 channels, not 4)."""
    rgba_png = _make_solid_colour_rgba_png(100, 150, 200, 128)
    # Note: this image may be blank or structurally invalid for plot detection,
    # but the load itself must succeed and return 3-channel array.
    # We test _load_rgb directly since parse_waterfall may fail on structure.
    arr, w, h = _load_rgb(rgba_png)
    assert arr.shape[2] == 3, f"Expected 3 channels, got {arr.shape[2]}"


def test_box_strictly_inside():
    """Box.strictly_inside must work correctly."""
    outer = Box(0, 0, 100, 100)
    inner = Box(1, 1, 99, 99)
    touching = Box(0, 0, 50, 50)
    outside = Box(50, 50, 110, 110)
    assert inner.strictly_inside(outer)
    assert not touching.strictly_inside(outer)
    assert not outside.strictly_inside(outer)


def test_box_to_dict():
    """Box.to_dict must return the correct keys and values."""
    box = Box(10, 20, 30, 40)
    d = box.to_dict()
    assert d == {"x0": 10, "y0": 20, "x1": 30, "y1": 40}


# ---------------------------------------------------------------------------
# 10. Path-vs-bytes equivalence
# ---------------------------------------------------------------------------

def test_path_and_bytes_produce_same_hz():
    """parse_waterfall must produce the same hz_per_px from a Path and from bytes."""
    data = FIXTURE_836.read_bytes()
    result_path = parse_waterfall(FIXTURE_836, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                              ocr_results=OCR_836)
    result_bytes = parse_waterfall(data, OBS_ID_836, PASS_DURATION_836, RX_FREQ,
                                    ocr_results=OCR_836)
    assert result_path.derivation == result_bytes.derivation
    if result_path.hz_per_px is not None:
        assert abs(result_path.hz_per_px - result_bytes.hz_per_px) < 1e-9


# ---------------------------------------------------------------------------
# Live OCR. Excluded from the offline gate because it needs the easyocr backend
# and its downloaded weights, neither of which exists on a CI runner or a clean
# clone. Run it where the weights are installed:
#     .venv\Scripts\python.exe -m pytest -m ocr -q
# It is what stops tests/fixtures/ocr_labels.json drifting away from what the
# model actually reads. Without it the committed cache could silently rot into
# a set of numbers that agree only with themselves.
# ---------------------------------------------------------------------------

@pytest.mark.ocr
@pytest.mark.parametrize(
    ("fixture", "obs_id", "duration", "expected_hz_px"),
    [
        (FIXTURE_836, OBS_ID_836, PASS_DURATION_836, HZ_PX_836),
        (FIXTURE_832, OBS_ID_832, PASS_DURATION_832, HZ_PX_832),
    ],
    ids=["836px", "832px"],
)
def test_live_ocr_matches_the_committed_reading(fixture, obs_id, duration, expected_hz_px):
    live = parse_waterfall(fixture, obs_id, duration, RX_FREQ)
    cached = parse_waterfall(fixture, obs_id, duration, RX_FREQ, ocr_results=ocr_for(fixture))

    assert live.derivation != "failed", f"live OCR degraded: {live.degraded}"
    assert live.hz_per_px == pytest.approx(cached.hz_per_px, rel=1e-6), (
        "the live model no longer reads what tests/fixtures/ocr_labels.json says it read; "
        "re-run scripts/dump_ocr_fixture.py and inspect the diff before trusting it"
    )
    assert live.hz_per_px == pytest.approx(expected_hz_px, rel=HZ_PX_TOLERANCE)
