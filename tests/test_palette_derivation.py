"""The neutral ramp in the stylesheet is the one the specification derives.

The palette's whole argument is that a hue can be applied to Carbon's lightness ramp
without moving a contrast ratio, because OKLCH lightness is perceptually uniform. That
argument only holds while the values in `globals.css` are actually the output of that
construction. Before `scripts/derive_palette.py` existed they were hex literals with a
comment naming the Carbon token each one came from, and nothing recomputed them: one
nudged value would have left the file claiming a method it no longer followed.

This runs the generator in check mode, so the stylesheet and the specification cannot
disagree, and it re-derives the ratios so the claim that the cast is free is measured
here rather than quoted from a comment.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def palette():
    spec = importlib.util.spec_from_file_location(
        "derive_palette", REPO / "scripts" / "derive_palette.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_stylesheet_matches_the_derivation():
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "derive_palette.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        "the neutral tokens in globals.css are not what scripts/derive_palette.py "
        "derives: " + (proc.stdout or proc.stderr)
    )


def test_every_neutral_holds_its_specified_lightness(palette):
    """Round-trip each token: the hex in the file has the lightness it claims."""
    derived = palette.derive()
    for name, _carbon, lightness, chroma, _note in palette.NEUTRALS:
        got_l, got_c, got_h = palette.hex_to_oklch(derived[name])
        # 8-bit quantisation is the only thing between the specification and the file,
        # and it is not uniform: near the bottom of the ramp one integer step of an
        # sRGB channel is a large fraction of the chroma, so the recovered hue of the
        # void wanders further than the recovered hue of a mid grey. Measured on this
        # ramp: 1.9 degrees at L 0.165, under 0.5 everywhere above L 0.30. The
        # tolerance follows the quantisation rather than pretending it is not there.
        assert got_l == pytest.approx(lightness, abs=0.004), name
        assert got_c == pytest.approx(chroma, abs=0.004), name
        if chroma > 0.005:
            tolerance = 4.0 if lightness < 0.20 else 1.5
            assert got_h == pytest.approx(palette.NEUTRAL_HUE, abs=tolerance), name


def test_the_hue_rotation_costs_no_contrast(palette):
    """The claim, measured: at fixed lightness, a cast does not move a WCAG ratio.

    Each neutral is compared with an achromatic colour at the same OKLCH lightness. If
    a tint were paying for itself in contrast, the two would differ.
    """
    derived = palette.derive()
    ground = derived["ui-background"]
    achromatic_ground = palette.oklch_to_hex(0.1650, 0.0, palette.NEUTRAL_HUE)

    for name in ("text-01", "text-02", "text-03"):
        spec = next(row for row in palette.NEUTRALS if row[0] == name)
        tinted = palette.contrast(derived[name], ground)
        plain = palette.contrast(
            palette.oklch_to_hex(spec[2], 0.0, palette.NEUTRAL_HUE), achromatic_ground
        )
        assert abs(tinted - plain) < 0.35, (
            f"{name} measures {tinted:.2f}:1 tinted and {plain:.2f}:1 achromatic, so "
            f"the cast is not free after all"
        )


def test_the_ground_is_darker_than_carbons_and_that_is_the_safe_direction(palette):
    derived = palette.derive()
    carbon_ground_l, _c, _h = palette.hex_to_oklch("#161616")
    ours_l, _c2, _h2 = palette.hex_to_oklch(derived["ui-background"])

    assert ours_l < carbon_ground_l
    # And every ink is still above its floor on it, which check_contrast.py owns in
    # full. Two spot checks here so this file fails on its own if the ground moves.
    assert palette.contrast(derived["text-01"], derived["ui-background"]) > 16.0
    assert palette.contrast(derived["text-03"], derived["ui-background"]) > 4.5


def test_the_elevation_planes_are_ordered(palette):
    """A sunken well is darker than the ground, a raised panel lighter, an edge lighter still."""
    derived = palette.derive()
    lum = palette.relative_luminance

    assert lum(derived["surface-sunken"]) < lum(derived["ui-background"])
    assert lum(derived["ui-background"]) < lum(derived["surface-raised"])
    assert lum(derived["surface-raised"]) < lum(derived["ui-01"])
    assert lum(derived["ui-01"]) < lum(derived["edge-highlight"])


def test_the_live_accent_is_not_on_the_intensity_ramp():
    """The cyan that means "measured just now" must not read as a brighter gold.

    Position on inferno is ordinal, so an accent taken off that ramp says "more". A
    live measurement is a different kind of fact, not a larger one, which is why this
    token carries a hue instead of a position. The test is that it is far from every
    accent the ramp contributes.
    """
    css = (REPO / "apps" / "web" / "app" / "globals.css").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "derive_palette", REPO / "scripts" / "derive_palette.py"
    )
    assert spec and spec.loader
    palette = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(palette)

    import re

    tokens = {
        m.group(1): m.group(2)
        for m in re.finditer(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css)
    }
    live_hue = palette.hex_to_oklch(tokens["live-01"])[2]
    for gold in ("interactive-01", "interactive-04", "link-01", "support-03"):
        gold_hue = palette.hex_to_oklch(tokens[gold])[2]
        separation = abs((live_hue - gold_hue + 180) % 360 - 180)
        assert separation > 90, (
            f"live-01 sits {separation:.0f} degrees from {gold}, close enough that a "
            f"reader could read it as a position on the same ramp"
        )
    # And it still has to be readable on both surfaces it is used on.
    assert palette.contrast(tokens["live-01"], tokens["ui-background"]) >= 4.5
    assert palette.contrast(tokens["live-01"], tokens["ui-01"]) >= 4.5
