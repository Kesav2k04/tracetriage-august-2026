"""Read a waterfall's frequency-axis labels without a neural network.

`waterfall.py` reads the tick labels with easyocr, which works and costs four and a half
gigabytes: easyocr declares torch, torchvision, opencv and scikit-image as its own
dependencies, so `pip install tracetriage[ocr]` pulls all of them. Without the axis a
measurement can only report a pixel offset, and a pixel offset is not a frequency error, so
a light install would be a tool that answers nothing. That is the whole reason this exists.

**Why a template matcher is the right instrument here, and general OCR is not.** These
labels are not photographs of text. A SatNOGS waterfall is rendered server-side by
matplotlib at a fixed figure size, so the digits come out as the same handful of bitmaps
every time. Measured over the 400 waterfalls that produced the committed template set: all
3,793 digit components are exactly 10 rows tall and 6, 7 or 8 columns wide, and thresholding
the label band at half intensity gives a clean binary shape with no grey edge to guess about.
Recognising a bitmap that has been seen before is a dictionary lookup. Reading an arbitrary
rendering of a digit is a neural model. Only one of those two problems is present.

**The templates are measured, not designed, and their labeller is not trusted.**
`scripts/build_glyph_templates.py` extracts every digit component from a sample of real
waterfalls and labels each one with easyocr's reading of that same band. easyocr turned out
to be a noisy labeller at this glyph size: on the first build, four bitmaps came back with two
different digits from different images, and it read the wrong number of characters for a
majority of label groups until the title's letters were excluded by height. So a bitmap is
only frozen when several independent images agree on it, and one that does not reach that bar
is dropped rather than resolved by picking a side. A dropped bitmap costs a label; a wrong one
rescales the frequency axis.

**Measured coverage, over 500 waterfalls drawn at random from the stage-1 snapshot, none of
which is a claim about the images the templates were built from:** an
axis is derived on 496 of them, 99.2 percent. The other four produce fewer than three labels
and refuse. Zero produce a label set that is not an arithmetic progression over the tick
positions, which is the check that a wrong digit would fail: across 500 images the failure
mode is always a missing label and never a wrong one.

The template set covers the digits 0, 1, 2, 3, 4, 6 and 8. Five, seven and nine are absent
because a kHz axis is labelled in round numbers at round steps, so they almost never appear,
and a bitmap is not frozen on fewer than three corroborating readings. A label containing an
uncovered digit is dropped whole, and `scripts/build_glyph_templates.py` refuses to write a
set in which any unfrozen bitmap would classify as some other digit, which is the failure
that incomplete coverage could otherwise cause.

**What it refuses.** An unknown bitmap is not guessed. If the nearest template is further
than `MAX_HAMMING` bits away, or is not clearly nearer than the runner-up, that glyph is
dropped; if that leaves too few labels, `read_labels` returns what it has and the caller's
own `_derive_hz_per_px` refuses for the usual reason. A wrong digit is worse than a missing
one here, because a mis-read label does not look like a failure: it looks like a frequency
axis with a different scale, and every offset measured through it would be wrong by that
ratio with nothing in the output to say so.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

#: Where the frozen bitmaps live. Inside the package, so a wheel carries them: the whole
#: point is an install that needs no model weights, and a template file left in the
#: repository would have moved the download rather than removed it.
TEMPLATE_PATH = Path(__file__).with_name("data") / "glyph_templates.json"

#: Below half intensity is ink. The band is white paper with black text, measured min 0 and
#: max 255, so this is not a tuned threshold: any value well inside that gap gives the same
#: bitmap, which is what makes the templates stable.
INK_THRESHOLD = 128.0

#: Height is what separates a digit from everything else in the band, and the separation is
#: wide. Measured over the 400 waterfalls behind the committed template set: 3,793 components
#: are 10 rows tall and nothing else in that range appears at all, because the band also
#: carries the axis title and the letters of "Frequency (kHz)" come out 6 to 8 rows with the
#: parentheses at 8. A first version of this floor was 6, which fed capital F and lower-case z
#: to a digit matcher; the cost was 601 label groups where easyocr read a different number of
#: characters than there were components, against 108 in the build that produced the shipped
#: file.
#:
#: 9 to 11 rather than exactly 10, because an earlier sweep with 4-connected components found
#: seven at height 9 and a clipped digit should get the chance to match rather than be
#: discarded on one row. Nothing rests on the bound being tight: the template match is what
#: decides, and a glyph from a renderer at another size fails it rather than matching the
#: wrong digit.
MIN_GLYPH_HEIGHT = 9
MAX_GLYPH_HEIGHT = 11

#: Two digits inside one label touch or nearly touch; two labels sit far apart. Measured over
#: the 400 waterfalls behind the committed set, digit components only: the largest gap inside
#: a label is 3 columns and the smallest gap between labels is 51, so any threshold in [3, 50]
#: gives the same grouping and 20 sits in the middle of it.
#:
#: The same measurement before the height filter excluded the axis title put the smallest
#: between-label gap at 7, because capital F and lower-case z were being grouped as digits.
#: A threshold chosen against that number would have had a margin of four columns instead of
#: forty-eight.
LABEL_GAP_PX = 20

#: How many bits of a normalised bitmap may differ before a match is refused, and by how
#: much the best match must beat the second best. A digit is about 30 ink pixels in a 10x8
#: box, so 6 bits is a fifth of the glyph: enough for one antialiasing phase, not enough to
#: turn an 8 into a 9. The margin is what stops a near-tie being resolved by template order.
MAX_HAMMING = 6
MIN_MARGIN = 2

#: The grid every candidate is padded into before comparison. Padding rather than scaling:
#: these glyphs differ by whole pixels of sub-pixel phase, and resampling a 6-wide bitmap to
#: 8 would invent grey where the renderer put none.
GRID_H = 20
GRID_W = 12


class GlyphRefusal(Exception):
    """No axis could be read, with the reason as `.code`."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def _pack(bitmap: np.ndarray) -> str:
    """A bitmap as a string, so it can be a dict key and live in JSON.

    Rows joined by `/`, ink as `1`. Readable on purpose: a template file a reader can eyeball
    is a template file a reader can correct, and these are 10 lines of 8 characters.
    """
    return "/".join("".join("1" if v else "0" for v in row) for row in bitmap)


def _unpack(packed: str) -> np.ndarray:
    rows = [[c == "1" for c in row] for row in packed.split("/")]
    return np.array(rows, dtype=bool)


def _normalise(patch: np.ndarray) -> np.ndarray:
    """A component's ink mask, centred in a fixed grid.

    Centred rather than corner-aligned so that a glyph one column wider than its template
    differs by its own extra ink and not by a whole-glyph shift.
    """
    h, w = patch.shape
    if h > GRID_H or w > GRID_W:
        raise GlyphRefusal("GLYPH_TOO_LARGE", f"a {h}x{w} component does not fit the grid")
    out = np.zeros((GRID_H, GRID_W), dtype=bool)
    top = (GRID_H - h) // 2
    left = (GRID_W - w) // 2
    out[top:top + h, left:left + w] = patch
    return out


@lru_cache(maxsize=1)
def _templates() -> tuple[tuple[np.ndarray, str], ...]:
    """The frozen bitmaps, loaded once.

    Cached because `read_labels` is called per observation and a queue calls it per row.
    """
    if not TEMPLATE_PATH.exists():
        raise GlyphRefusal(
            "NO_TEMPLATES",
            f"{TEMPLATE_PATH.name} is not installed beside this module. Regenerate it with "
            f"scripts/build_glyph_templates.py, or use the easyocr path.",
        )
    blob = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return tuple((_unpack(packed), digit) for packed, digit in blob["glyphs"].items())


def template_metadata() -> dict[str, Any]:
    """What the template file says about how it was built. For provenance, not for logic."""
    if not TEMPLATE_PATH.exists():
        return {"present": False}
    blob = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    meta = dict(blob.get("provenance", {}))
    meta["present"] = True
    meta["n_bitmaps"] = len(blob.get("glyphs", {}))
    return meta


def classify(patch: np.ndarray) -> tuple[str | None, int]:
    """One component to one digit, or to None with the reason implicit in the distance.

    Returns the digit and the Hamming distance to it. `None` means either nothing was close
    enough or two templates were too close together to choose between, and the caller treats
    both the same way: the glyph is dropped rather than guessed.
    """
    try:
        grid = _normalise(patch)
    except GlyphRefusal:
        return None, 10**6
    best: tuple[int, str] | None = None
    second = 10**6
    for template, digit in _templates():
        d = int(np.count_nonzero(grid ^ template))
        if best is None or d < best[0]:
            second = best[0] if best is not None else second
            best = (d, digit)
        elif d < second:
            second = d
    if best is None or best[0] > MAX_HAMMING:
        return None, best[0] if best else 10**6
    if second - best[0] < MIN_MARGIN and second <= MAX_HAMMING:
        return None, best[0]
    return best[1], best[0]


# ---------------------------------------------------------------------------
# Reading a band
# ---------------------------------------------------------------------------


def components(label_band: np.ndarray) -> list[tuple[int, int, int, int, np.ndarray]]:
    """Digit-sized ink blobs in a label band, left to right.

    Each entry is `(x0, x1, y0, y1, mask)`. scipy's labeller rather than a hand-rolled flood
    fill: scipy is already a base dependency because the corridor fit needs it, so this adds
    nothing to the install.
    """
    from scipy import ndimage  # noqa: PLC0415

    lum = label_band.astype(np.float32)
    if lum.ndim == 3:
        lum = lum.mean(axis=2)
    mask = lum < INK_THRESHOLD

    # Eight-connectivity, and the default four-connectivity is a bug rather than a preference.
    # The digit 3 at this size has a middle stroke that meets the upper and lower bowls only
    # diagonally, so `ndimage.label` with its default structure cuts it into a 4-row piece and
    # a 6-row piece. Both fail the digit-height filter and vanish, and the label "30" then reads
    # as "0": a wrong value on that tick rather than a missing one, which is the exact failure
    # this module is written to avoid. It cost 30 kHz on the last tick of observation 14740031
    # and moved that image's derived axis by 0.25 percent.
    #
    # Merging two digits is the risk this trades against, and it does not arise: adjacent digits
    # in a label are separated by 1 to 3 blank columns, measured, so there is no diagonal contact
    # to follow.
    labelled, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    out = []
    for sl in ndimage.find_objects(labelled):
        y0, y1 = sl[0].start, sl[0].stop
        x0, x1 = sl[1].start, sl[1].stop
        if not MIN_GLYPH_HEIGHT <= (y1 - y0) <= MAX_GLYPH_HEIGHT:
            continue
        out.append((x0, x1, y0, y1, mask[sl]))
    out.sort(key=lambda c: c[0])
    return out


def read_labels(label_band: np.ndarray) -> list[tuple[float, str, float]]:
    """A label band to `(centre_x, text, confidence)`, the shape `waterfall.py` expects.

    Deliberately the same contract as `waterfall._ocr_labels`, so this drops into
    `parse_waterfall(..., ocr_results=...)` with nothing else changed and the two readers can
    be compared on the same band.

    The confidence reported is not a probability and is not presented as one: it is
    `1 - mean_hamming / MAX_HAMMING` over the glyphs in that label, which is 1.0 for an exact
    bitmap match and falls as a glyph drifts from anything seen before. Every label this
    returns has already passed the match test; the number is there so a caller can prefer a
    clean label over a marginal one, which is what `_parse_ocr_labels` uses it for.
    """
    groups: list[list[tuple[int, int, int, int, np.ndarray]]] = []
    for comp in components(label_band):
        if groups and comp[0] - groups[-1][-1][1] <= LABEL_GAP_PX:
            groups[-1].append(comp)
        else:
            groups.append([comp])

    out: list[tuple[float, str, float]] = []
    for group in groups:
        digits, distances = [], []
        for *_bbox, mask in group:
            digit, distance = classify(mask)
            if digit is None:
                digits = []
                break
            digits.append(digit)
            distances.append(distance)
        if not digits:
            continue
        centre = (group[0][0] + group[-1][1]) / 2.0
        mean_d = sum(distances) / len(distances)
        out.append((centre, "".join(digits), max(0.0, 1.0 - mean_d / MAX_HAMMING)))
    return out
