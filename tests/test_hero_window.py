"""The hero plate's display window, checked against the image it windows.

`components/CorridorHero.tsx` maps the greyscale plate through inferno, and ahead of
the colour table it applies a linear window with two constants written into the
markup: slope 4.8113 and intercept -0.9623. Both are derived from the committed
image. A derived constant that nobody re-derives is a number in a document that
nothing reads, which is the defect this project exists to argue against, so this
recomputes both from the file on disk.

It also asserts the palette rule the whole design rests on. `globals.css` states that
grey is measured and colour is computed, and gives as its reason that every published
waterfall is achromatic. That is a measurement, and it is the one that would silently
stop being true if a future snapshot were rendered with a colour map applied. If it
did, the console would be drawing computed colour on top of measured colour and a
reader would have no way to tell the two apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
HERO = REPO / "apps/web/components/CorridorHero.tsx"
WATERFALLS = REPO / "apps/web/public/waterfalls"

# The observation the hero draws. Read from the receipt rather than typed, so that
# changing which observation leads the page moves this test with it.
HERO_NULLS = REPO / "artifacts/HERO_NULLS.json"

# Tolerances. The markup carries four decimal places, so a constant that rounds to
# the same four is the same constant. 1e-4 is that, not a loosened threshold.
TOL = 1e-4


def _hero_obs_id() -> int:
    import json

    return int(json.loads(HERO_NULLS.read_text(encoding="utf-8"))["obs_id"])


def _plate() -> np.ndarray:
    """The hero plate as a float array in 0..1, the way the browser sees it."""
    path = WATERFALLS / f"{_hero_obs_id()}.webp"
    assert path.exists(), f"the hero plate {path.name} is not committed"
    return np.asarray(Image.open(path).convert("L")).astype(np.float64) / 255.0


def _markup_window() -> tuple[float, float]:
    """The slope and intercept the component actually ships."""
    src = HERO.read_text(encoding="utf-8")
    m = re.search(
        r'<feFuncR type="linear" slope="([-\d.]+)" intercept="([-\d.]+)" />', src
    )
    assert m, "CorridorHero no longer applies a linear window ahead of the colour table"
    return float(m.group(1)), float(m.group(2))


def test_all_three_channels_share_one_window() -> None:
    """A per-channel window would tint a greyscale plate, which is the one thing the
    palette rule forbids: colour on this page means computed, and a channel-dependent
    stretch would introduce colour that no computation put there."""
    src = HERO.read_text(encoding="utf-8")
    found = re.findall(
        r'<feFunc([RGB]) type="linear" slope="([-\d.]+)" intercept="([-\d.]+)" />', src
    )
    assert len(found) == 3, f"expected R, G and B windows, found {len(found)}"
    assert {c for c, _, _ in found} == {"R", "G", "B"}
    assert len({(s, i) for _, s, i in found}) == 1, (
        f"the three channels carry different windows: {found}. A greyscale plate "
        f"windowed per channel comes out tinted."
    )


def test_window_low_end_is_the_measured_noise_floor() -> None:
    """The low end is the modal level, not a percentile. It is a hard floor: a
    receiver's quantised noise level, and it holds a large share of the frame."""
    a = _plate()
    counts = np.bincount((a * 255).round().astype(int).ravel(), minlength=256)
    mode_level = int(np.argmax(counts))
    mode_share = counts[mode_level] / a.size

    assert mode_share > 0.10, (
        f"the modal level holds only {mode_share:.1%} of the frame, so it is no "
        f"longer a hard noise floor and windowing from it is no longer justified"
    )

    lo = mode_level / 255.0
    hi = float(np.percentile(a, 99.5))
    slope = 1.0 / (hi - lo)
    intercept = -lo * slope

    ship_slope, ship_intercept = _markup_window()
    assert abs(slope - ship_slope) < TOL, (
        f"CorridorHero ships slope {ship_slope}, the image gives {slope:.4f} "
        f"(noise floor {lo:.4f}, 99.5th percentile {hi:.4f})"
    )
    assert abs(intercept - ship_intercept) < TOL, (
        f"CorridorHero ships intercept {ship_intercept}, the image gives "
        f"{intercept:.4f}"
    )


def test_window_clamps_the_share_the_comment_claims() -> None:
    """Both clamped fractions are stated in the component's comment.

    The black share is the modal level plus everything under it, and the modal level
    is included because the window maps it to exactly zero. Writing this test with a
    strict `<` gave 7.4%, that number went into the component's comment, and the
    comment was wrong by a factor of four: a third of the plate renders black, not a
    fourteenth. The bound below is on the number the browser actually produces.
    """
    a = _plate()
    counts = np.bincount((a * 255).round().astype(int).ravel(), minlength=256)
    lo = int(np.argmax(counts)) / 255.0
    hi = float(np.percentile(a, 99.5))

    black = float((a <= lo).mean())
    white = float((a > hi).mean())

    assert 0.25 < black < 0.35, (
        f"{black:.4f} of the frame clamps to black, not ~0.307. The component's "
        f"comment states 30.7%, and a window that discarded materially more than "
        f"that would be hiding signal rather than suppressing a noise floor."
    )
    assert white < 0.01, f"{white:.4f} of the frame clamps to white, not ~0.005"
    assert black + white < 0.40, (
        f"the window discards {black + white:.1%} of the frame; above about 40% the "
        f"display is a threshold rather than a map"
    )


def test_the_window_is_monotonic() -> None:
    """The claim in the comment is that the ordering of the measured intensities is
    preserved exactly. A positive slope is what makes that true, and it is worth
    asserting rather than assuming, because a negative slope would invert the plate
    and still look like a plausible spectrogram."""
    slope, _ = _markup_window()
    assert slope > 0, f"slope {slope} inverts the plate"


@pytest.mark.parametrize("path", sorted(WATERFALLS.glob("*.webp")))
def test_every_published_waterfall_is_achromatic(path: Path) -> None:
    """The palette rule: grey is measured, colour is computed.

    `globals.css` derives the whole palette from the fact that the instrument records
    intensity and no hue. If a snapshot ever ships a colour-mapped waterfall, the
    console would be painting computed colour over measured colour with no way for a
    reader to separate them, and the design's central claim would be false while
    every other test stayed green.
    """
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    spread = a.max(axis=2) - a.min(axis=2)
    assert spread.max() <= 2, (
        f"{path.name} carries chroma: the largest channel spread is "
        f"{spread.max()} of 255. globals.css states that every published waterfall "
        f"is greyscale and derives the palette from it."
    )
