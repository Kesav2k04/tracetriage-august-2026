"""Waterfall artifact parser for TraceTriage.

Per-observation frequency and time calibration of a SatNOGS waterfall PNG.

CRITICAL: The waterfall does NOT span samp-rate-rx. It spans a decimated band
roughly 32x narrower, and nothing in the API reports that factor. Hz/px was
measured at 123.46 on one client and 80.00 on another — a 54% spread. This
module derives Hz/px from the rendered matplotlib axis ticks on every image.
Assuming samp-rate-rx compresses the Doppler corridor from ~118 px to ~5 px and
makes kill gate 3 fail for a reason that is entirely a wrong constant.

Returns a WaterfallGeometry dataclass whose fields match
contracts/waterfall_geometry.schema.json exactly.

There is deliberately NO fallback-to-constant derivation mode. If the axis
cannot be read, the returned record carries derivation="failed" and a named
degraded reason. Never substitute a per-family constant.

See docs/SATNOGS_API_RECON.md section 7 for measured values and the pixel-to-
frequency mapping rationale.

Runtime dependencies:
    easyocr    — required for label reading. Install via uv.
                 Set EASYOCR_MODULE_PATH=D:/cache/easyocr to keep weights off C:.
    Pillow     — image loading
    numpy      — pixel arithmetic
"""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    def width(self) -> int:
        return self.x1 - self.x0

    def height(self) -> int:
        return self.y1 - self.y0

    def strictly_inside(self, outer: Box) -> bool:
        """True when self is strictly inside outer (not touching its edge)."""
        return (
            self.x0 > outer.x0
            and self.y0 > outer.y0
            and self.x1 < outer.x1
            and self.y1 < outer.y1
        )

    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}


@dataclass(frozen=True)
class WaterfallGeometry:
    """Per-observation pixel-to-frequency mapping.

    Fields match contracts/waterfall_geometry.schema.json exactly.
    """

    observation_id: int
    image_width: int
    image_height: int
    plot_box: Box | None
    crop_box: Box | None
    hz_per_px: float | None
    seconds_per_px: float | None
    centre_px: float | None
    derivation: str            # "axis_ticks" | "axis_ticks_ocr" | "failed"
    derivation_confidence: float | None
    degraded: str | None

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict matching the schema."""
        return {
            "observation_id": self.observation_id,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "plot_box": self.plot_box.to_dict() if self.plot_box is not None else None,
            "crop_box": self.crop_box.to_dict() if self.crop_box is not None else None,
            "hz_per_px": self.hz_per_px,
            "seconds_per_px": self.seconds_per_px,
            "centre_px": self.centre_px,
            "derivation": self.derivation,
            "derivation_confidence": self.derivation_confidence,
            "degraded": self.degraded,
        }


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Pixel brightness sum (R+G+B) below which a pixel is considered non-white.
_NONWHITE_THRESH = 700

# Fraction of rows a column must be non-white to count as "heavy" (plot area).
_COL_HEAVY_FRAC = 0.50

# Minimum run length in pixels to be a plot column run (not a label or noise).
_MIN_PLOT_RUN_PX = 20

# Minimum pixel width for the plot area.
_MIN_PLOT_WIDTH_PX = 100

# Minimum number of pixel rows for a valid plot.
_MIN_PLOT_HEIGHT_PX = 50

# Fraction of plot-width a row must be non-white to be inside the plot.
_ROW_HEAVY_FRAC = 0.25

# How many rows below plot bottom to scan for tick marks.
_TICK_SEARCH_ROWS = 10

# R+G+B brightness threshold for a "dark" tick-mark pixel.
_TICK_DARK_THRESH = 400

# Minimum votes (rows) in the tick band to declare a column a tick candidate.
_TICK_MIN_VOTES = 3

# Minimum ticks needed for a reliable spacing estimate.
_MIN_TICKS = 3

# Fraction of the image height that the colorbar must span to be recognised.
_COLORBAR_MIN_OCC = 0.80

# Minimum column run length to be called a colorbar.
_COLORBAR_MIN_RUN_PX = 5

# Confidence values.
_CONF_OCR_CLEAN = 0.95   # labels read cleanly with OCR
_CONF_OCR_NOISY = 0.75   # OCR read but partial / corrected

# EasyOCR model directory: prefer env var, then the project-local cache.
_EASYOCR_MODEL_DIR: str | None = os.environ.get(
    "EASYOCR_MODULE_PATH",
    "D:/cache/easyocr/model",
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class _DegradedError(Exception):
    """Raised with a named reason code when parsing cannot succeed."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# EasyOCR reader (module-level cache, lazy init)
# ---------------------------------------------------------------------------

_ocr_reader = None


def _get_ocr_reader():
    """Return a cached EasyOCR Reader, or raise _DegradedError if unavailable."""
    global _ocr_reader  # noqa: PLW0603
    if _ocr_reader is not None:
        return _ocr_reader

    try:
        import easyocr  # noqa: PLC0415
    except ImportError as exc:
        raise _DegradedError("NO_OCR_BACKEND") from exc

    try:
        _ocr_reader = easyocr.Reader(
            ["en"],
            gpu=False,           # avoid CUDA memory contention with model pipeline
            verbose=False,
            model_storage_directory=_EASYOCR_MODEL_DIR,
            download_enabled=False,  # weights must be pre-installed; no runtime download
        )
    except Exception as exc:
        logger.warning("EasyOCR init failed: %s", exc)
        raise _DegradedError("NO_OCR_BACKEND") from exc

    return _ocr_reader


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------


def _load_rgb(data: bytes | Path) -> tuple[np.ndarray, int, int]:
    """Load image bytes or path as an (H, W, 3) uint8 RGB array.

    Returns (array, width, height).
    Raises _DegradedError with a reason code on any unrecoverable error.
    """
    raw = data.read_bytes() if isinstance(data, Path) else bytes(data)

    if len(raw) == 0:
        raise _DegradedError("ZERO_BYTE")

    # Verify integrity before decoding.
    try:
        pil = Image.open(io.BytesIO(raw))
        pil.verify()
    except UnidentifiedImageError as exc:
        raise _DegradedError("MALFORMED_PNG") from exc
    except Exception as exc:
        raise _DegradedError("MALFORMED_PNG") from exc

    # Re-open after verify() (verify() closes the internal file pointer).
    try:
        pil = Image.open(io.BytesIO(raw))
    except Exception as exc:
        raise _DegradedError("MALFORMED_PNG") from exc

    # Convert RGBA → RGB by compositing onto white.
    # Alpha must not become a fourth feature plane.
    if pil.mode == "RGBA":
        bg = Image.new("RGB", pil.size, (255, 255, 255))
        bg.paste(pil, mask=pil.split()[3])
        pil = bg
    else:
        pil = pil.convert("RGB")

    arr = np.array(pil, dtype=np.uint8)
    h, w, c = arr.shape
    assert c == 3  # noqa: S101 – guaranteed by convert("RGB")

    # Blank: every pixel white (or near-white).
    if int(arr.astype(np.int32).sum(axis=2).min()) >= 700:
        raise _DegradedError("BLANK_IMAGE")

    return arr, w, h


# ---------------------------------------------------------------------------
# Plot-box detection
# ---------------------------------------------------------------------------


def _contiguous_runs(idx: np.ndarray, min_run: int = 1) -> list[tuple[int, int]]:
    """Return (start, end) pairs for contiguous integer runs in sorted array."""
    if len(idx) == 0:
        return []
    runs: list[tuple[int, int]] = []
    start = int(idx[0])
    prev = start
    for val in idx[1:]:
        v = int(val)
        if v != prev + 1:
            if prev - start + 1 >= min_run:
                runs.append((start, prev))
            start = v
        prev = v
    if prev - start + 1 >= min_run:
        runs.append((start, prev))
    return runs


def _detect_plot_box(rgb: np.ndarray) -> Box:
    """Find the bounding box of the spectrogram plot area.

    Strategy:
    1. Mark non-white pixels (R+G+B < _NONWHITE_THRESH).
    2. Find column runs where > _COL_HEAVY_FRAC of rows are non-white.
    3. The widest such run is the spectrogram; narrower runs are the colorbar.
    4. Find the vertical extent via row occupancy in the detected x-range.

    Raises _DegradedError("NO_AXIS_DETECTED") if no plausible plot found.
    Raises _DegradedError("UNKNOWN_LAYOUT") if plot is too narrow.
    """
    h, w, _ = rgb.shape
    brt = rgb.astype(np.int32).sum(axis=2)
    non_white = brt < _NONWHITE_THRESH

    col_occ = non_white.sum(axis=0) / h
    heavy_cols = np.where(col_occ > _COL_HEAVY_FRAC)[0]
    if len(heavy_cols) == 0:
        raise _DegradedError("NO_AXIS_DETECTED")

    col_runs = _contiguous_runs(heavy_cols, min_run=_MIN_PLOT_RUN_PX)
    if not col_runs:
        raise _DegradedError("NO_AXIS_DETECTED")

    # Widest run = spectrogram plot area (colorbar is narrower).
    plot_x0, plot_x1 = max(col_runs, key=lambda r: r[1] - r[0])
    if plot_x1 - plot_x0 < _MIN_PLOT_WIDTH_PX:
        raise _DegradedError("UNKNOWN_LAYOUT")

    # Vertical extent inside the plot x-range.
    plot_width = plot_x1 - plot_x0 + 1
    col_slice = non_white[:, plot_x0: plot_x1 + 1]
    row_occ = col_slice.sum(axis=1) / plot_width
    heavy_rows = np.where(row_occ > _ROW_HEAVY_FRAC)[0]
    if len(heavy_rows) < _MIN_PLOT_HEIGHT_PX:
        raise _DegradedError("NO_AXIS_DETECTED")

    return Box(plot_x0, int(heavy_rows[0]), plot_x1, int(heavy_rows[-1]))


# ---------------------------------------------------------------------------
# Tick detection
# ---------------------------------------------------------------------------


def _detect_ticks(rgb: np.ndarray, plot_box: Box) -> list[float]:
    """Return sorted x-coordinates of axis tick marks below the plot bottom.

    Tick marks are thin, dark vertical lines drawn in the few rows immediately
    below the plot area (the matplotlib axis spine).
    """
    h, w, _ = rgb.shape
    y_start = min(plot_box.y1 + 1, h - 1)
    y_end = min(plot_box.y1 + _TICK_SEARCH_ROWS, h)
    if y_start >= y_end:
        return []

    band = rgb[y_start:y_end].astype(np.int32)
    dark_votes = (band.sum(axis=2) < _TICK_DARK_THRESH).sum(axis=0)

    tick_idx = np.where(dark_votes >= _TICK_MIN_VOTES)[0]
    tick_runs = _contiguous_runs(tick_idx, min_run=1)

    # Midpoint of each run, restricted to the plot x-range (±5 px margin).
    ticks = []
    for a, b in tick_runs:
        cx = (a + b) / 2.0
        if plot_box.x0 - 5 <= cx <= plot_box.x1 + 5:
            ticks.append(cx)
    return sorted(ticks)


# ---------------------------------------------------------------------------
# Label OCR
# ---------------------------------------------------------------------------


def _extract_label_band(
    rgb: np.ndarray, plot_box: Box
) -> tuple[np.ndarray, int, int]:
    """Return the label band crop and its y-offsets in the full image.

    Scans rows below the tick area for the first row that contains label text
    (several non-white pixels), then extracts a fixed-height band.

    Returns (label_band_rgb, band_y0_in_image, band_height).
    Raises _DegradedError("NO_AXIS_DETECTED") if no label band found.
    """
    h, w, _ = rgb.shape
    brt = rgb.astype(np.int32).sum(axis=2)

    # Search start: skip tick marks (a few rows below plot bottom).
    search_y0 = plot_box.y1 + _TICK_SEARCH_ROWS
    label_y0 = None
    for y in range(search_y0, min(search_y0 + 30, h)):
        n_dark = int((brt[y] < _NONWHITE_THRESH).sum())
        if n_dark >= 3:
            label_y0 = y
            break

    if label_y0 is None:
        raise _DegradedError("NO_AXIS_DETECTED")

    # Label band: 25 rows from the first label row.
    band_h = 25
    label_y1 = min(label_y0 + band_h, h)
    return rgb[label_y0:label_y1, :, :], label_y0, label_y1 - label_y0


def _ocr_labels(
    label_band: np.ndarray,
) -> list[tuple[float, str, float]]:
    """Run EasyOCR on a label band and return (centre_x, text, confidence) triples.

    Images are 4x upscaled and inverted (white-on-black) for better OCR
    accuracy on small matplotlib labels.  The inverted image prevents EasyOCR
    from mis-reading the minus sign as a digit.  Only digits and the minus
    sign are in the allowlist; the sign is inferred from tick position by the
    caller, so single-digit false readings of the minus glyph are filtered out.
    """
    reader = _get_ocr_reader()  # may raise _DegradedError("NO_OCR_BACKEND")

    from PIL import Image as PILImage  # noqa: PLC0415

    pil = PILImage.fromarray(label_band)
    scale = 4
    pil_big = pil.resize((pil.width * scale, pil.height * scale), PILImage.LANCZOS)
    # Invert: white-on-black is more reliable for EasyOCR with small fonts.
    arr_big = 255 - np.array(pil_big)

    raw = reader.readtext(arr_big, allowlist="0123456789-", text_threshold=0.4)

    results = []
    for bbox, text, conf in raw:
        # bbox is [[x0,y0],[x1,y0],[x1,y1],[x0,y1]] in the upscaled image.
        xs = [pt[0] for pt in bbox]
        centre_x_big = (min(xs) + max(xs)) / 2.0
        centre_x = centre_x_big / scale   # back to original label-band coordinates
        results.append((centre_x, text.strip(), float(conf)))

    return results


def _parse_ocr_labels(
    ocr_results: list[tuple[float, str, float]],
    tick_xs: list[float],
    plot_box: Box,
) -> tuple[list[int | None], float]:
    """Map OCR label text to signed Hz values and match them to tick positions.

    Returns:
        hz_values: list parallel to tick_xs; None if no reliable label for that tick.
        confidence: overall confidence score.

    Strategy: OCR gives us the absolute value (magnitude) of each label.
    The sign is inferred from position relative to the axis centre (the tick
    whose OCR reading is "0", or the tick geometrically closest to mid-plot).
    Ticks to the left of centre are negative; ticks to the right are positive.
    This avoids relying on OCR to detect the minus-sign glyph, which EasyOCR
    often misreads on small matplotlib fonts.
    """
    if not ocr_results:
        return [None] * len(tick_xs), 0.0

    # Step 1: parse absolute integer kHz values from OCR text.
    # Reject single-character readings that are not "0" — these are almost
    # always spurious detections of the minus glyph or image noise.
    parsed: list[tuple[float, int, float]] = []   # (centre_x, abs_khz, conf)
    for cx, text, conf in ocr_results:
        text = text.strip().lstrip("-")   # strip any minus: value is always abs
        if not text:
            continue
        try:
            val = abs(int(text))
        except ValueError:
            continue
        # Single-char "0" is the axis centre; single-char non-zero is likely noise.
        if len(text) == 1 and val != 0 and conf < 0.8:
            continue
        parsed.append((cx, val, conf))

    if not parsed:
        return [None] * len(tick_xs), 0.0

    # Step 2: for each tick, find the best OCR reading within 25 px.
    best_per_tick: list[tuple[int, float] | None] = [None] * len(tick_xs)
    for cx, abs_khz, conf in parsed:
        best_idx = min(range(len(tick_xs)), key=lambda i: abs(tick_xs[i] - cx))
        dist_px = abs(tick_xs[best_idx] - cx)
        if dist_px < 25:
            existing = best_per_tick[best_idx]
            if existing is None or conf > existing[1]:
                best_per_tick[best_idx] = (abs_khz, conf)

    # Step 3: identify the centre tick (0 Hz).  Prefer a tick with abs_khz == 0;
    # if none, fall back to the geometrically central tick.
    centre_idx: int | None = None
    for i, entry in enumerate(best_per_tick):
        if entry is not None and entry[0] == 0:
            centre_idx = i
            break
    if centre_idx is None:
        # Geometric fallback: tick closest to plot horizontal midpoint.
        mid = (tick_xs[0] + tick_xs[-1]) / 2.0
        centre_idx = min(range(len(tick_xs)), key=lambda i: abs(tick_xs[i] - mid))

    # Step 4: assign signs: negative left of centre, positive right.
    hz_values: list[int | None] = [None] * len(tick_xs)
    conf_sum = 0.0
    conf_count = 0
    for i, entry in enumerate(best_per_tick):
        if entry is None:
            continue
        abs_khz, conf = entry
        sign = -1 if i < centre_idx else 1
        hz_values[i] = sign * abs_khz * 1000
        conf_sum += conf
        conf_count += 1

    if conf_count == 0:
        return [None] * len(tick_xs), 0.0

    return hz_values, conf_sum / conf_count


def _derive_hz_per_px(
    tick_xs: list[float],
    hz_values: list[int | None],
) -> tuple[float, float]:
    """Derive Hz/px from matched tick positions and their Hz values.

    Uses pairs of ticks with known Hz values to compute Hz/px for each pair,
    then takes the median as the final estimate.

    Returns (hz_per_px, confidence). Raises _DegradedError on failure.
    """
    # Collect (tick_x, hz) pairs for ticks with a label.
    labelled = [
        (tick_xs[i], hz_values[i])
        for i in range(len(tick_xs))
        if hz_values[i] is not None
    ]

    if len(labelled) < 2:
        # Not enough labelled ticks for a pair.
        raise _DegradedError("NO_AXIS_DETECTED")

    # For each pair of labelled ticks compute Hz/px.
    estimates: list[float] = []
    for i in range(len(labelled)):
        for j in range(i + 1, len(labelled)):
            x_i, hz_i = labelled[i]
            x_j, hz_j = labelled[j]
            delta_px = abs(x_j - x_i)
            delta_hz = abs(hz_j - hz_i)
            if delta_px > 5 and delta_hz > 0:
                estimates.append(delta_hz / delta_px)

    if not estimates:
        raise _DegradedError("NO_AXIS_DETECTED")

    hz_per_px = float(np.median(estimates))
    if hz_per_px <= 0:
        raise _DegradedError("NO_AXIS_DETECTED")

    # Confidence: based on spread of estimates (low IQR = high confidence).
    if len(estimates) >= 4:
        iqr = float(np.percentile(estimates, 75) - np.percentile(estimates, 25))
        spread = iqr / hz_per_px if hz_per_px > 0 else 1.0
        # Confidence 0.95 for spread < 1%, down to 0.7 for spread 10%.
        confidence = max(0.7, _CONF_OCR_CLEAN * (1.0 - min(spread / 0.10, 1.0) * 0.25))
    else:
        confidence = _CONF_OCR_NOISY

    return hz_per_px, confidence


# ---------------------------------------------------------------------------
# Colorbar detection
# ---------------------------------------------------------------------------


def _detect_colorbar(rgb: np.ndarray, plot_box: Box) -> Box | None:
    """Detect the optional colorbar rendered to the right of the spectrogram.

    One client renders a colorbar at approximately x=724..755 on the 836 px
    image. A naive "non-white columns" crop swallows it and feeds axis metadata
    to the model. This function finds it so crop_box can exclude it.

    Returns the colorbar Box, or None if not present.
    """
    h, w, _ = rgb.shape
    brt = rgb.astype(np.int32).sum(axis=2)
    non_white = brt < _NONWHITE_THRESH
    col_occ = non_white.sum(axis=0) / h

    # Only search to the right of the plot box.
    right_start = plot_box.x1 + 1
    if right_start >= w:
        return None

    right_occ = col_occ[right_start:]
    cb_idx = np.where(right_occ > _COLORBAR_MIN_OCC)[0]
    if len(cb_idx) == 0:
        return None

    cb_runs = _contiguous_runs(cb_idx + right_start, min_run=_COLORBAR_MIN_RUN_PX)
    if not cb_runs:
        return None

    cb_x0, cb_x1 = cb_runs[0]
    return Box(cb_x0, plot_box.y0, cb_x1, plot_box.y1)


# ---------------------------------------------------------------------------
# Crop box
# ---------------------------------------------------------------------------


def _compute_crop_box(
    rgb: np.ndarray,
    plot_box: Box,
    colorbar: Box | None,
) -> Box:
    """Compute the region delivered to the model.

    Excludes:
    - The colorbar to the right of the plot (if any).
    - Ensures the result is strictly inside the full-image bounding box.

    The y-range is taken from the plot_box: the detected spectrogram data rows.
    Axis labels and tick marks are below plot_y1 and are NOT in the crop.
    """
    h, w, _ = rgb.shape

    x0 = plot_box.x0
    y0 = plot_box.y0
    x1 = plot_box.x1
    y1 = plot_box.y1

    # If a colorbar is adjacent, stop before it.
    if colorbar is not None and colorbar.x0 <= x1 + 30:
        x1 = colorbar.x0 - 1

    # Ensure strictly inside full image (not touching the outer 1-pixel border).
    x0 = max(x0, 1)
    y0 = max(y0, 1)
    x1 = min(x1, w - 2)
    y1 = min(y1, h - 2)

    if x1 <= x0 or y1 <= y0:
        raise _DegradedError("UNKNOWN_LAYOUT")

    return Box(x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# Centre pixel
# ---------------------------------------------------------------------------


def _compute_centre_px(
    tick_xs: list[float],
    hz_values: list[int | None],
    crop_box: Box,
) -> float | None:
    """Return the pixel column within crop_box for the 0 Hz offset (axis centre).

    Returns None when:
    - No tick was labelled "0" and the axis centre cannot be inferred.

    This value is always the axis zero line (where the image plots 0 Hz offset
    relative to rx-freq). A null here does not invalidate hz_per_px.
    """
    # Find the tick explicitly labelled 0 Hz.
    zero_candidates = [
        tick_xs[i] for i, v in enumerate(hz_values) if v is not None and v == 0
    ]
    if zero_candidates:
        axis_zero_x = float(np.median(zero_candidates))
    else:
        # Fall back: the tick closest to the geometric midpoint.
        if not tick_xs:
            return None
        mid = (tick_xs[0] + tick_xs[-1]) / 2.0
        axis_zero_x = min(tick_xs, key=lambda t: abs(t - mid))

    # Convert image x-coordinate to crop_box-relative coordinate (0-based).
    centre_in_crop = axis_zero_x - crop_box.x0
    if centre_in_crop < 0 or centre_in_crop > crop_box.width():
        return None

    return float(centre_in_crop)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_waterfall(
    image_data: bytes | Path,
    observation_id: int,
    pass_duration_s: float | None = None,
    rx_freq_hz: float | None = None,
    observation_freq_hz: float | None = None,
) -> WaterfallGeometry:
    """Parse a SatNOGS waterfall PNG and derive the pixel-to-frequency mapping.

    Parameters
    ----------
    image_data:
        Raw PNG bytes or a Path to the PNG file.
    observation_id:
        The SatNOGS observation ID (stored verbatim in the returned record).
    pass_duration_s:
        Duration of the pass in seconds (``end - start``). Required to compute
        ``seconds_per_px``. None if timing is unavailable — the record will be
        degraded with reason ``NO_TIMING_INFO``.
    rx_freq_hz:
        Receiver centre frequency in Hz, from
        ``client_metadata.radio.parameters.rx-freq``. Used to note that
        ``centre_px`` is valid for this frequency. May be None (≈6 % of records);
        ``centre_px`` will be None in that case.
    observation_freq_hz:
        Fallback from the observation record. Used only when ``rx_freq_hz`` is
        None to decide whether to attempt ``centre_px``.

    Returns
    -------
    WaterfallGeometry
        Fields match ``contracts/waterfall_geometry.schema.json`` exactly.
        On any unrecoverable error the record carries ``derivation="failed"``
        and a named ``degraded`` reason code; no exception is raised.

    Notes
    -----
    There is deliberately **no** fallback-to-constant derivation mode.
    Hz/px varied 54 % across a three-image sample and has never been measured
    as stable within a client family.  Substituting a constant would put a wrong
    pixel mapping into the corridor silently.
    """
    # --- Step 1: load image ----------------------------------------------------
    try:
        rgb, img_w, img_h = _load_rgb(image_data)
    except _DegradedError as exc:
        return _make_failed(observation_id, 0, 0, exc.reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Unexpected load error obs %d: %s", observation_id, exc)
        return _make_failed(observation_id, 0, 0, "MALFORMED_PNG")

    # --- Step 2: detect plot box -----------------------------------------------
    try:
        plot_box = _detect_plot_box(rgb)
    except _DegradedError as exc:
        return _make_failed(observation_id, img_w, img_h, exc.reason)

    # --- Step 3: detect colorbar (optional, non-fatal) -------------------------
    try:
        colorbar = _detect_colorbar(rgb, plot_box)
    except Exception:  # noqa: BLE001
        colorbar = None

    # --- Step 4: detect tick marks --------------------------------------------
    tick_xs = _detect_ticks(rgb, plot_box)
    if len(tick_xs) < _MIN_TICKS:
        return _make_failed(observation_id, img_w, img_h, "NO_AXIS_DETECTED")

    # --- Step 5: OCR tick labels ----------------------------------------------
    try:
        label_band, _, _ = _extract_label_band(rgb, plot_box)
        ocr_results = _ocr_labels(label_band)
    except _DegradedError as exc:
        return _make_failed(observation_id, img_w, img_h, exc.reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed for obs %d: %s", observation_id, exc)
        return _make_failed(observation_id, img_w, img_h, "NO_OCR_BACKEND")

    hz_values, ocr_conf = _parse_ocr_labels(ocr_results, tick_xs, plot_box)

    # --- Step 6: compute Hz/px ------------------------------------------------
    try:
        hz_per_px, confidence = _derive_hz_per_px(tick_xs, hz_values)
    except _DegradedError as exc:
        return _make_failed(observation_id, img_w, img_h, exc.reason)

    # Blend OCR confidence into the derivation confidence.
    confidence = min(confidence, _CONF_OCR_CLEAN) * (0.9 + 0.1 * ocr_conf)

    # --- Step 7: compute crop box --------------------------------------------
    try:
        crop_box = _compute_crop_box(rgb, plot_box, colorbar)
    except _DegradedError as exc:
        return _make_failed(observation_id, img_w, img_h, exc.reason)

    # --- Step 8: seconds per pixel -------------------------------------------
    # seconds_per_px is required (non-null) by the contract on a non-failed record.
    if pass_duration_s is None or pass_duration_s <= 0:
        return _make_failed(observation_id, img_w, img_h, "NO_TIMING_INFO")
    plot_height_px = plot_box.height()
    if plot_height_px <= 0:
        return _make_failed(observation_id, img_w, img_h, "UNKNOWN_LAYOUT")
    seconds_per_px = pass_duration_s / plot_height_px

    # --- Step 9: centre pixel ------------------------------------------------
    # Null when rx_freq and observation_freq are both absent (≈6 % of records).
    if rx_freq_hz is not None or observation_freq_hz is not None:
        centre_px = _compute_centre_px(tick_xs, hz_values, crop_box)
    else:
        centre_px = None

    return WaterfallGeometry(
        observation_id=observation_id,
        image_width=img_w,
        image_height=img_h,
        plot_box=plot_box,
        crop_box=crop_box,
        hz_per_px=hz_per_px,
        seconds_per_px=seconds_per_px,
        centre_px=centre_px,
        derivation="axis_ticks_ocr",
        derivation_confidence=confidence,
        degraded=None,
    )


def _make_failed(
    observation_id: int,
    img_w: int,
    img_h: int,
    reason: str,
) -> WaterfallGeometry:
    """Return a WaterfallGeometry record for an unrecoverable parse failure."""
    return WaterfallGeometry(
        observation_id=observation_id,
        image_width=img_w,
        image_height=img_h,
        plot_box=None,
        crop_box=None,
        hz_per_px=None,
        seconds_per_px=None,
        centre_px=None,
        derivation="failed",
        derivation_confidence=None,
        degraded=reason,
    )


def validate_against_schema(record: WaterfallGeometry) -> list[str]:
    """Validate a WaterfallGeometry record against the JSON schema.

    Returns a list of validation error messages. Empty list means valid.
    """
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        return ["jsonschema not installed"]

    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "waterfall_geometry.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = [str(e.message) for e in validator.iter_errors(record.to_dict())]
    return errors


def crop_array(rgb: np.ndarray, crop_box: Box) -> np.ndarray:
    """Extract the crop region from an RGB array.

    Parameters
    ----------
    rgb:
        Full image array (H, W, 3) uint8.
    crop_box:
        The region to extract, in full-image pixel coordinates.

    Returns
    -------
    np.ndarray
        Cropped region (H, W, 3) uint8.
    """
    return rgb[crop_box.y0: crop_box.y1 + 1, crop_box.x0: crop_box.x1 + 1]
