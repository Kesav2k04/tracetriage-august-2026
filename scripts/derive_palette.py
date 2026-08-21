"""Derive the console's neutral ramp, and prove the derivation costs no contrast.

The neutrals on this console are IBM Carbon Gray 100's own lightness values with a hue
and a chroma applied in OKLCH. That is a claim about a method, and until this script
existed the claim was checked by hand: the hex values sat in `globals.css` with a
comment saying which Carbon token each one came from, and nothing recomputed them.

Two things go wrong when a palette is typed rather than generated. The first is drift:
one token gets nudged to look better and the ramp stops being a ramp. The second is the
argument. The reason a cast is free is that OKLCH lightness is perceptually uniform, so
rotating hue at fixed lightness moves a WCAG ratio by rounding and nothing more. A
palette nobody can regenerate cannot demonstrate that, and a designer who wants a
different hue has to relitigate the accessibility result instead of re-running a
command.

    .venv/Scripts/python.exe scripts/derive_palette.py            # print the block
    .venv/Scripts/python.exe scripts/derive_palette.py --check    # fail if CSS drifted

`tests/test_palette_derivation.py` runs `--check` in the offline suite, so the tokens in
the stylesheet and the specification in this file cannot disagree.

WHAT THE SPECIFICATION SAYS, AND WHICH PARTS ARE PREFERENCES

Lightness: Carbon Gray 100's, unchanged, except for the page ground, which is taken
deeper on purpose. A darker ground can only raise a ratio measured against it, so that
one movement is the safe direction and it is stated rather than hidden.

Hue: 262, a deep space blue. This is a preference and it is named as one. What it is
chosen against is not: it sits nearly opposite the inferno accent ramp on the hue
circle, so gold reads as emission against a void rather than as amber on mud, and it is
far from the crimson the failed verdict owns. It replaced hue 305, a deep plum, which
measured the same and read as aubergine under warm room light. Hue 262 is also what a
long-exposure deep-field frame actually looks like: the sky is not black, it is a very
dark blue that carries almost no chroma at the top of the ramp.

Chroma: falls as lightness rises, 0.044 in the void to 0.002 in the brightest ink. A
tinted mid-grey is what makes a dark theme look synthetic. A tinted black reads as a
sky, and white ink with a tint in it is just a dimmer white.
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSS = REPO / "apps/web/app/globals.css"

#: The one hue the neutral ramp carries. A preference, named as one.
NEUTRAL_HUE = 262.0

#: Token name to (Carbon source, OKLCH lightness, chroma, note).
#:
#: The lightness column is Carbon Gray 100's own value for that step, measured by
#: converting Carbon's hex to OKLCH, with one exception recorded in the note.
NEUTRALS: tuple[tuple[str, str, float, float, str], ...] = (
    (
        "ui-background",
        "#161616",
        0.1650,
        0.0440,
        "the page ground, taken below Carbon's 0.200 on purpose: a darker ground "
        "raises every ratio measured against it, and the void is where the cast lives",
    ),
    ("ui-01", "#262626", 0.2600, 0.0330, "a tile"),
    ("ui-02", "#393939", 0.3400, 0.0250, "a raised surface and a rule"),
    ("ui-03", "#393939", 0.3400, 0.0250, "a rule, same step as ui-02 in Carbon"),
    ("ui-04", "#6f6f6f", 0.5450, 0.0120, "a component boundary"),
    ("ui-05", "#f4f4f4", 0.9600, 0.0020, "the inverse surface"),
    ("field-01", "#262626", 0.2600, 0.0330, "an input field, Carbon's tile step"),
    ("hover-ui", "#353535", 0.3200, 0.0290, "hover on a tile"),
    ("text-01", "#f4f4f4", 0.9600, 0.0020, "body ink"),
    ("text-02", "#c6c6c6", 0.8200, 0.0040, "secondary prose"),
    (
        "text-03",
        "#8d8d8d",
        0.6350,
        0.0080,
        "captions, table labels and axis ticks. Carbon's text-03 is Gray 60 and is "
        "the placeholder colour, which measures under 4.5:1 on both surfaces here, so "
        "this token is Gray 50's lightness and the placeholder keeps its own",
    ),
    ("text-04", "#ffffff", 1.0000, 0.0000, "the strongest ink, and the one left achromatic"),
    ("text-05", "#8d8d8d", 0.6350, 0.0080, "the same step as text-03"),
    ("text-placeholder", "#6f6f6f", 0.5450, 0.0120, "a real placeholder"),
    ("border-subtle", "#393939", 0.3400, 0.0250, "a hairline between sections"),
    ("border-strong", "#6f6f6f", 0.5450, 0.0120, "a component boundary"),
)

#: The surfaces a floating panel is built from, above the ramp rather than in it.
#:
#: A console that has one ground and one tile has two planes and reads flat. These are
#: the third and fourth: the plane a sticky panel sits on, and the hairline that catches
#: light along its top edge. Both are derived from the ramp rather than picked, so the
#: elevation system moves with the palette instead of drifting away from it.
ELEVATION: tuple[tuple[str, float, float, str], ...] = (
    ("surface-raised", 0.2250, 0.0380, "a floating panel over the ground"),
    ("surface-sunken", 0.1400, 0.0460, "a well: a plot ground or a code block"),
    ("edge-highlight", 0.4200, 0.0300, "the lit top edge of a raised panel"),
)


# ---------------------------------------------------------------------------
# OKLab, from Björn Ottosson's reference implementation
# ---------------------------------------------------------------------------


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def hex_to_oklch(value: str) -> tuple[float, float, float]:
    h = value.lstrip("#")
    r, g, b = (_srgb_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4))
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (v ** (1 / 3) if v >= 0 else -((-v) ** (1 / 3)) for v in (l_, m_, s_))
    lightness = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_ = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    chroma = math.hypot(a, b_)
    hue = math.degrees(math.atan2(b_, a)) % 360
    return lightness, chroma, hue


def oklch_to_hex(lightness: float, chroma: float, hue: float) -> str:
    """OKLCH to the nearest in-gamut sRGB hex.

    Clamping per channel after the transform rather than gamut-mapping in OKLCH. Every
    colour in this file is a low-chroma neutral, so nothing here is anywhere near the
    sRGB boundary and the two agree; a saturated accent would need the harder path, and
    the accents on this console are samples off a colourmap rather than values derived
    here.
    """
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    out = []
    for channel in (r, g, bl):
        srgb = _linear_to_srgb(max(0.0, min(1.0, channel)))
        out.append(max(0, min(255, round(srgb * 255))))
    return "#{:02x}{:02x}{:02x}".format(*out)


# ---------------------------------------------------------------------------
# WCAG, so the claim that the cast is free can be printed next to it
# ---------------------------------------------------------------------------


def relative_luminance(value: str) -> float:
    h = value.lstrip("#")
    r, g, b = (_srgb_to_linear(int(h[i : i + 2], 16) / 255) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def derive() -> dict[str, str]:
    """Every neutral token, from its specification."""
    out: dict[str, str] = {}
    for name, _carbon, lightness, chroma, _note in NEUTRALS:
        out[name] = oklch_to_hex(lightness, chroma, NEUTRAL_HUE)
    for name, lightness, chroma, _note in ELEVATION:
        out[name] = oklch_to_hex(lightness, chroma, NEUTRAL_HUE)
    return out


def read_css_tokens() -> dict[str, str]:
    css = CSS.read_text(encoding="utf-8")
    start = css.index(":root {")
    end = css.index("\n}", start)
    block = css[start:end]
    return {
        m.group(1): m.group(2).lower()
        for m in re.finditer(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block)
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="Compare against globals.css.")
    args = ap.parse_args(argv)

    derived = derive()

    if args.check:
        in_css = read_css_tokens()
        drift = [
            (name, value, in_css.get(name))
            for name, value in derived.items()
            if in_css.get(name) != value
        ]
        if drift:
            print("the stylesheet's neutrals are not what this specification derives:")
            for name, want, got in drift:
                print(f"  --{name}: css {got}, derived {want}")
            print("Run scripts/derive_palette.py and paste the block, or fix the spec.")
            return 1
        print(f"{len(derived)} neutral tokens match their derivation at hue {NEUTRAL_HUE:.0f}")
        return 0

    print(f"/* Derived by scripts/derive_palette.py at OKLCH hue {NEUTRAL_HUE:.0f}. */")
    for name, carbon, lightness, chroma, note in NEUTRALS:
        print(
            f"  --{name}: {derived[name]};"
            f"  /* Carbon {carbon}, L {lightness:.4f} C {chroma:.4f}: {note} */"
        )
    for name, lightness, chroma, note in ELEVATION:
        print(f"  --{name}: {derived[name]};  /* L {lightness:.4f} C {chroma:.4f}: {note} */")

    ground = derived["ui-background"]
    print("\n/* Ratios against the derived ground, for the record. */")
    for name in ("text-01", "text-02", "text-03", "text-04", "ui-04", "border-strong"):
        print(f"/*   {name:16} {contrast(derived[name], ground):6.2f}:1 */")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
