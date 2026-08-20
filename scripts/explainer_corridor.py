"""Manim scene: what the Doppler corridor is, and what the fitted offset measures.

Rendered to `apps/web/public/media/corridor-explainer.mp4` and served from the
console's own origin, so the content security policy stays closed and there is no
embed from a video host.

Every number in this scene is read from the exported card for SatNOGS observation
14745984, which is the observation in the shipped set with the strongest corridor
curvature (220 pixels of sweep across 1,540 rows) and therefore the clearest
teaching case. The curve drawn is the predicted Doppler corridor the matched filter
actually scored, in the image's own pixel columns. Nothing here is drawn to look
like the physics; it is the physics, subsampled.

Two presentational liberties are taken, and both are stated on screen rather than
in this docstring alone:

  1. The frequency axis is cropped to columns 170 to 450 of 620. All 620 columns at
     this aspect ratio would render the whole corridor in a strip a few percent of
     the frame wide.
  2. Within that crop the frequency axis is exaggerated relative to the time axis,
     by the factor the code computes rather than one chosen by eye, so a 61 pixel
     shift is visible at all.

Render:
    manim -qh scripts/explainer_corridor.py CorridorExplainer

The values below are duplicated from the export rather than imported, because this
scene has to keep rendering from a checkout that has no receipts built. They are
pinned by `tests/test_explainer_values.py`, which fails if the card they came from
ever disagrees with them.
"""

# ruff: noqa: F403, F405
# `from manim import *` is the idiom manim's own documentation and every example in
# it use, and the library exports several hundred names a scene needs. Importing
# them one by one would be a fifty-line import block that goes stale against the
# next manim release. The star import is confined to this render script, which
# nothing else imports.
from pathlib import Path

import numpy as np
from manim import *

# The console self-hosts IBM Plex through @fontsource, which ships web formats only,
# and Pango needs an outline font. `make explainer` converts the same woff2 files the
# site serves into media/fonts and registers them here, so the video and the page it
# sits on are set in one typeface rather than two. Without this, Pango silently falls
# back to a serif, which is what the first render shipped.
_FONT_DIR = Path(__file__).resolve().parent.parent / "media" / "fonts"
_HAVE_PLEX = False
if _FONT_DIR.is_dir():
    import manimpango

    for _ttf in sorted(_FONT_DIR.glob("*.ttf")):
        manimpango.register_font(str(_ttf))
    _HAVE_PLEX = "IBM Plex Sans" in manimpango.list_fonts()

# Segoe UI and Consolas are the fallbacks, not a serif: both are present on every
# Windows install, and a grotesk plus a mono is the right pairing even when it is not
# the exact one.
SANS = "IBM Plex Sans" if _HAVE_PLEX else "Segoe UI"
MONO = "IBM Plex Mono" if _HAVE_PLEX else "Consolas"

OBS_ID = 14745984
IMG_W, IMG_H = 620, 1540
CENTRE_PX = 310.0
HZ_PER_PX = 92.593
OFFSET_PX = -61.0
OFFSET_HZ = -5648.1
OFFSET_PPM = -12.97
HALF_WIDTH_PX = 21.6
MAX_EL_DEG = 70.7

# (row, column) of the predicted corridor at zero frequency offset. Row 0 is the
# END of the pass: time runs bottom to top on a SatNOGS waterfall.
PRED = [
    (0, 419.77), (60, 418.99), (120, 417.97), (180, 416.63), (240, 414.85),
    (300, 412.46), (360, 409.19), (420, 404.64), (480, 398.21), (540, 389.01),
    (600, 375.82), (660, 357.44), (720, 333.55), (780, 306.12), (840, 279.32),
    (900, 256.87), (960, 240.02), (1020, 228.07), (1080, 219.74), (1140, 213.90),
    (1200, 209.76), (1260, 206.76), (1320, 204.55), (1380, 202.90),
    (1440, 201.65), (1500, 200.70), (1539, 200.30),
]

# Computed from every column that will be drawn: the predicted curve, the fitted
# curve, and the half-width band around the fitted one. Chosen by hand it was wrong.
_COLS = [c for _r, c in PRED]
X_MIN = min(min(_COLS) + OFFSET_PX - HALF_WIDTH_PX, min(_COLS)) - 12.0
X_MAX = max(max(_COLS) + OFFSET_PX + HALF_WIDTH_PX, max(_COLS)) + 12.0
PLOT_W, PLOT_H = 4.6, 5.4
EXAGGERATION = (PLOT_W / (X_MAX - X_MIN)) / (PLOT_H / IMG_H)

# The console's own tokens, so the video and the page it sits on are one artefact.
# The palette, read out of the console's stylesheet rather than copied into this file.
#
# These were seven hardcoded hex strings. They matched the site when they were written
# and then the site's palette moved from a Carbon-blue-accented navy to a deep plum ground
# with an inferno accent ramp, and this scene did not, so the clip embedded halfway down
# the landing page rendered in a colour scheme the rest of the page had abandoned. Read
# here, it cannot happen twice.
#
# Two names changed meaning with the palette, and the mapping is deliberate rather than
# nearest-hue. FITTED is the answer the scene is about, so it takes the page's strongest
# ink, which is what the hero plate and the observation overlay both do with the same
# curve. PREDICTED keeps the accent, because it is the computed comparison arm. Drawing
# both off the inferno ramp would have put them one stop apart, and the whole scene is
# the gap between them.
def _palette() -> dict[str, str]:
    import re

    css = (
        Path(__file__).resolve().parents[1] / "apps/web/app/globals.css"
    ).read_text(encoding="utf-8")
    start = css.index(":root {")
    end = css.index("\n}", start)
    found = dict(
        re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css[start:end])
    )
    wanted = {
        "INK": "text-01",
        "DIM": "text-03",
        "GRID": "ui-02",
        "FITTED": "text-04",
        "PREDICTED": "interactive-01",
        "PAPER": "ui-background",
        "PANEL": "ui-01",
    }
    missing = sorted(t for t in wanted.values() if t not in found)
    if missing:
        raise SystemExit(
            f"globals.css no longer defines {', '.join('--' + m for m in missing)}. This "
            f"scene reads its palette from the stylesheet so the clip cannot render in an "
            f"older one than the page around it."
        )
    return {key: found[token] for key, token in wanted.items()}


_P = _palette()
INK = _P["INK"]
DIM = _P["DIM"]
GRID = _P["GRID"]
FITTED = _P["FITTED"]
PREDICTED = _P["PREDICTED"]
PAPER = _P["PAPER"]
PANEL = _P["PANEL"]


def to_point(col: float, row: float, dx: float = 0.0) -> np.ndarray:
    """Image column and row to scene coordinates."""
    x = -3.9 + ((col + dx) - X_MIN) / (X_MAX - X_MIN) * PLOT_W
    y = -3.15 + (row / IMG_H) * PLOT_H
    return np.array([x, y, 0.0])


class CorridorExplainer(Scene):
    def construct(self) -> None:
        self.camera.background_color = PAPER

        frame = Rectangle(
            width=PLOT_W, height=PLOT_H, stroke_color=GRID, stroke_width=2,
            fill_color=PANEL, fill_opacity=1.0,
        )
        frame.move_to(to_point((X_MIN + X_MAX) / 2, IMG_H / 2))

        axis_freq = Text("frequency", font_size=17, color=DIM, font=SANS)
        axis_time = Text("time, bottom to top", font_size=17, color=DIM, font=SANS)
        axis_time.rotate(PI / 2)
        axis_freq.next_to(frame, DOWN, buff=0.22)
        axis_time.next_to(frame, LEFT, buff=0.22)

        title = Text(f"SatNOGS observation {OBS_ID}", font_size=30, color=INK, font=SANS)
        title.to_edge(UP, buff=0.45).to_edge(LEFT, buff=0.7)
        sub = Text(
            f"one pass, {MAX_EL_DEG:.1f} degrees maximum elevation",
            font_size=19, color=DIM, font=MONO,
        )
        sub.next_to(title, DOWN, buff=0.16).align_to(title, LEFT)

        self.play(FadeIn(title, shift=UP * 0.2), FadeIn(sub), run_time=0.9)
        self.play(Create(frame), FadeIn(axis_freq), FadeIn(axis_time), run_time=1.1)

        # ---- 1. The assumption -------------------------------------------------
        vertical = DashedLine(
            to_point(CENTRE_PX, 0), to_point(CENTRE_PX, IMG_H),
            color=DIM, stroke_width=2.5, dash_length=0.09,
        )
        v_label = Text("commanded receive frequency", font_size=18, color=DIM, font=SANS)
        v_label.next_to(frame, RIGHT, buff=0.5).shift(UP * 2.5)
        v_lead = Line(
            v_label.get_left() + LEFT * 0.1,
            to_point(CENTRE_PX, IMG_H * 0.86),
            color=GRID, stroke_width=1.5,
        )

        step1 = Text(
            "A detector that assumes the trace is vertical\n"
            "looks for energy in one column.",
            font_size=21, color=INK, line_spacing=0.85, font=SANS,
        )
        step1.next_to(frame, RIGHT, buff=0.5).shift(UP * 0.9)

        self.play(Create(vertical), run_time=0.8)
        self.play(FadeIn(v_label), Create(v_lead), run_time=0.6)
        self.play(FadeIn(step1, shift=UP * 0.15), run_time=0.9)
        self.wait(1.6)

        # ---- 2. What the geometry says ----------------------------------------
        predicted = VMobject(color=PREDICTED, stroke_width=4)
        predicted.set_points_as_corners([to_point(col, row) for row, col in PRED])

        step2 = Text(
            "The satellite is moving, so the received\n"
            "frequency sweeps. The corridor is curved,\n"
            "and its shape is fixed by the pass geometry.",
            font_size=21, color=INK, line_spacing=0.85, font=SANS,
        )
        step2.next_to(frame, RIGHT, buff=0.5).shift(UP * 0.75)

        self.play(FadeOut(step1), run_time=0.35)
        self.play(Create(predicted), run_time=2.0)
        self.play(FadeIn(step2, shift=UP * 0.15), run_time=0.8)
        self.wait(1.8)

        # ---- 3. Sliding it to the best match ----------------------------------
        fitted = VMobject(color=FITTED, stroke_width=4.5)
        fitted.set_points_as_corners(
            [to_point(col, row, dx=OFFSET_PX) for row, col in PRED]
        )

        band = VMobject(color=FITTED, fill_opacity=0.12, stroke_width=0)
        upper = [
            to_point(col, row, dx=OFFSET_PX + HALF_WIDTH_PX) for row, col in PRED
        ]
        lower = [
            to_point(col, row, dx=OFFSET_PX - HALF_WIDTH_PX)
            for row, col in reversed(PRED)
        ]
        band.set_points_as_corners([*upper, *lower, upper[0]])

        step3 = Text(
            "Sliding that same curve across the image\n"
            "until it best matches the energy gives one\n"
            "number: how far off the capture was.",
            font_size=21, color=INK, line_spacing=0.85, font=SANS,
        )
        step3.next_to(frame, RIGHT, buff=0.5).shift(UP * 0.75)

        self.play(FadeOut(step2), run_time=0.35)
        self.play(FadeIn(step3, shift=UP * 0.15), run_time=0.7)

        ghost = predicted.copy()
        self.add(ghost)
        self.play(
            Transform(ghost, fitted.copy()),
            run_time=2.2, rate_func=rate_functions.ease_in_out_sine,
        )
        self.remove(ghost)
        self.add(fitted)
        self.play(FadeIn(band), run_time=0.6)
        self.wait(0.8)

        # ---- 4. The measurement ------------------------------------------------
        pred_by_row = dict(PRED)
        mid_row = 300
        gap = DoubleArrow(
            to_point(pred_by_row[mid_row], mid_row, dx=OFFSET_PX),
            to_point(pred_by_row[mid_row], mid_row),
            color=INK, stroke_width=3, tip_length=0.18, buff=0,
        )
        gap_label = VGroup(
            Text(f"{abs(OFFSET_PX):.0f} px", font_size=26, color=INK, font=MONO),
            Text(f"{abs(OFFSET_HZ):,.0f} Hz", font_size=26, color=INK, font=MONO),
            Text(f"{abs(OFFSET_PPM):.1f} ppm", font_size=26, color=FITTED, font=MONO),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12)
        gap_label.next_to(frame, RIGHT, buff=0.5).shift(DOWN * 1.9)

        chain = Text(f"1 px = {HZ_PER_PX:.1f} Hz on this image", font_size=17, color=DIM, font=MONO)
        chain.next_to(gap_label, DOWN, buff=0.22).align_to(gap_label, LEFT)

        self.play(FadeOut(step3), run_time=0.3)
        self.play(GrowFromCenter(gap), run_time=0.7)
        self.play(
            LaggedStart(
                *[FadeIn(m, shift=RIGHT * 0.12) for m in gap_label], lag_ratio=0.35
            ),
            run_time=1.4,
        )
        self.play(FadeIn(chain), run_time=0.5)
        self.wait(1.4)

        closing = Text(
            "The gap between the two curves is the measurement.\n"
            "Not a score the model produced: a frequency error, in hertz,\n"
            "that a reviewer can check against the image itself.",
            font_size=20, color=INK, line_spacing=0.9, font=SANS,
        )
        closing.to_edge(DOWN, buff=0.5)

        scale_note = Text(
            f"Frequency axis cropped to columns {X_MIN:.0f} to {X_MAX:.0f} of {IMG_W}, "
            f"and exaggerated {EXAGGERATION:.1f}x against the time axis, "
            f"so a {abs(OFFSET_PX):.0f} px shift is visible.",
            font_size=14, color=DIM, font=SANS,
        )
        scale_note.to_edge(DOWN, buff=0.16)

        self.play(
            FadeOut(gap), FadeOut(gap_label), FadeOut(chain),
            FadeOut(v_label), FadeOut(v_lead),
            run_time=0.6,
        )
        self.play(FadeIn(closing, shift=UP * 0.2), FadeIn(scale_note), run_time=1.0)
        self.wait(2.6)
