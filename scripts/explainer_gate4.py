"""Manim scene: how gate 4 was made falsifiable, and how it came out.

Rendered to `apps/web/public/media/gate4-explainer.mp4` and served from the console's
own origin, so the content security policy stays closed and there is no embed from a
video host.

The subject is the one thing in this project that is not a model, a metric or a plot: a
review whose sample was committed to before anyone looked at it. That is the part a
reader cannot check by running the code, because the interesting claim is about the
order events happened in, so it is the part worth drawing.

The scene ends on the gate's verdict and on who produced it, in that order, and both are
read from the receipt rather than written here. It ended on the literal string
"Gate 4: OPEN" until a person answered the worksheet, at which point the closing frame
would have said OPEN over a gate that had passed with "the reviewer was a human, not a
person" underneath. Nothing caught it: the three checks on this scene's numbers looked for
an `arm` in the receipt, a human answer does not produce one, and all three skipped. A
rendered frame is the one surface a digest check cannot read.

Who reviewed is still the beat the clip ends on rather than the rate. A review that clears
the bar and a review that clears the bar independently are different claims, and this one
is the first: the author reviewed a corpus he built, under a commitment made before he saw
it. A version that stopped at 1.000 would be the most misleading forty seconds on the site.

Render:
    manim -qh scripts/explainer_gate4.py Gate4Explainer

The values below are duplicated from the receipts rather than imported, because this
scene has to keep rendering from a checkout that has no receipts built. They are pinned by
`tests/test_explainer_gate4_values.py`, which fails if the receipts ever disagree with
them.
"""

# ruff: noqa: F403, F405
# `from manim import *` is the idiom manim's own documentation and every example in it
# use, and the library exports several hundred names a scene needs. The star import is
# confined to the render scripts, which nothing else imports.
from pathlib import Path

from manim import *

from explainer_timing import NarratedScene

# ---------------------------------------------------------------------------
# Typeface. Same arrangement as scripts/explainer_corridor.py: the console self-hosts
# IBM Plex as woff2, Pango needs an outline font, and `make explainer` converts the
# same files the site serves. Without this Pango falls back to a serif silently.
# ---------------------------------------------------------------------------
_FONT_DIR = Path(__file__).resolve().parent.parent / "media" / "fonts"
_HAVE_PLEX = False
if _FONT_DIR.is_dir():
    import manimpango

    for _ttf in sorted(_FONT_DIR.glob("*.ttf"), key=lambda p: p.as_posix()):
        manimpango.register_font(str(_ttf))
    _HAVE_PLEX = "IBM Plex Sans" in manimpango.list_fonts()

SANS = "IBM Plex Sans" if _HAVE_PLEX else "Segoe UI"
MONO = "IBM Plex Mono" if _HAVE_PLEX else "Consolas"

# ---------------------------------------------------------------------------
# The numbers. Every one of them is in a receipt and pinned by a test.
# ---------------------------------------------------------------------------
N_ITEMS = 72
N_OBSERVATIONS = 60
N_REPEATS = 12
THRESHOLD = 0.80
DECISIVE = 60
RATE = 1.0000
LOWER = 0.9513
UPPER = 1.0000
INTRA_IDENTICAL = 8
INTRA_PAIRS = 12
COMMITMENTS_CHECKED = 72
REVIEWER_KIND = "human"
#: The gate's own verdict, which the closing frame states. It was the literal string
#: "Gate 4: OPEN" until a person answered the worksheet, at which point the frame would
#: have said OPEN over a passed gate with "the reviewer was a human, not a person" under
#: it. Both follow the receipt now, and the test fails if the frame stops agreeing.
VERDICT = "PASSED"

#: One real commitment from the published manifest, truncated for the frame. The scene
#: shows what a commitment looks like, so it uses one that exists rather than a
#: plausible string of hex: a fabricated digest in a video about not fabricating things
#: would be the joke this project cannot afford.
SAMPLE_ITEM = "G4-001"
SAMPLE_COMMITMENT = "93d2a15a0d4b"


def _palette() -> dict[str, str]:
    """The console's own tokens, read out of its stylesheet rather than copied here.

    The corridor scene learned this the expensive way: seven hardcoded hex strings
    matched the site when they were written, the palette moved twice, and the clip
    embedded on the landing page rendered in a scheme the page had abandoned.
    """
    import re

    css = (Path(__file__).resolve().parents[1] / "apps/web/app/globals.css").read_text(
        encoding="utf-8"
    )
    start = css.index(":root {")
    end = css.index("\n}", start)
    found = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css[start:end]))
    wanted = {
        "INK": "text-01",
        "DIM": "text-03",
        "GRID": "ui-02",
        "OPEN": "verdict-not-measurable",
        "PASS": "verdict-passed",
        "WARN": "verdict-failed",
        "ACCENT": "interactive-01",
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
INK, DIM, GRID = _P["INK"], _P["DIM"], _P["GRID"]
OPEN, WARN, ACCENT = _P["OPEN"], _P["WARN"], _P["ACCENT"]
PASS = _P["PASS"]
PAPER, PANEL = _P["PAPER"], _P["PANEL"]


def caption(text: str, size: int = 20) -> Text:
    """A line of narration, always in the same place, always the same size."""
    node = Text(text, font_size=size, color=DIM, font=SANS)
    node.to_edge(DOWN, buff=0.6)
    return node


def plate(index: int) -> VGroup:
    """One blinded item: a small dark frame with a faint diagonal in it.

    A schematic and labelled as one on screen. It is not a waterfall and must not be
    mistaken for one: the plates are 113 MB of real captures and this is a rectangle.
    """
    box = Rectangle(
        width=0.46,
        height=0.72,
        stroke_color=GRID,
        stroke_width=1.4,
        fill_color=PANEL,
        fill_opacity=1.0,
    )
    # Every third plate gets no trace, so the strip reads as a mixed sample rather
    # than as a row of hits.
    if index % 3 != 2:
        trace = Line(
            box.get_corner(DL) + [0.10, 0.10, 0],
            box.get_corner(UR) + [-0.12, -0.16, 0],
            stroke_color=INK,
            stroke_width=1.2,
            stroke_opacity=0.55,
        )
        return VGroup(box, trace)
    return VGroup(box)


class Gate4Explainer(NarratedScene):
    clip = "gate4"

    def construct(self) -> None:
        self.camera.background_color = PAPER

        # ---- 1. the question -------------------------------------------------
        self.section("intro")
        title = Text("Kill gate 4", font_size=34, color=INK, font=SANS)
        title.to_edge(UP, buff=0.5).to_edge(LEFT, buff=0.7)
        sub = Text(
            "can a person decide anything from the image at all?",
            font_size=21,
            color=DIM,
            font=MONO,
        )
        sub.next_to(title, DOWN, buff=0.18).align_to(title, LEFT)
        self.play(FadeIn(title, shift=UP * 0.2), FadeIn(sub), run_time=0.9)

        axes = VGroup(
            *[
                Text(name, font_size=22, color=INK, font=MONO)
                for name in ("artifact_usable", "visible_signal", "target_consistent")
            ]
        ).arrange(DOWN, buff=0.42, aligned_edge=LEFT)
        axes.move_to(LEFT * 3.1)
        answers = Text("yes · no · unsure", font_size=19, color=ACCENT, font=MONO)
        answers.next_to(axes, RIGHT, buff=0.9)

        first = caption(
            "Three axes, and unsure is an answer rather than a failure to give one."
        )
        self.play(
            LaggedStart(*[FadeIn(a, shift=RIGHT * 0.2) for a in axes], lag_ratio=0.3),
            run_time=1.2,
        )
        self.play(FadeIn(answers), FadeIn(first), run_time=0.7)
        self.hold(1.8)
        self.play(FadeOut(axes), FadeOut(answers), FadeOut(first), run_time=0.5)

        # ---- 2. why the obvious version proves nothing ------------------------
        self.section("protocol")
        problem = VGroup(
            Text("Run the review. Report the rate.", font_size=26, color=INK, font=SANS),
            Text(
                "Nothing stops the sample being chosen after the answers are known.",
                font_size=21,
                color=WARN,
                font=SANS,
            ),
        ).arrange(DOWN, buff=0.34)
        problem.move_to(UP * 0.3)
        self.play(FadeIn(problem[0]), run_time=0.7)
        self.wait(0.7)
        self.play(FadeIn(problem[1], shift=UP * 0.15), run_time=0.8)
        self.hold(1.9)
        self.play(FadeOut(problem), run_time=0.5)

        # ---- 3. the commitment ------------------------------------------------
        self.section("commit")
        formula = Text(
            "sha256( salt | item | observation | image digest )",
            font_size=23,
            color=INK,
            font=MONO,
        )
        formula.move_to(UP * 1.35)
        digest = Text(
            f"{SAMPLE_ITEM}   {SAMPLE_COMMITMENT}…",
            font_size=24,
            color=ACCENT,
            font=MONO,
        )
        digest.next_to(formula, DOWN, buff=0.55)
        outside = Text(
            "the salt and the item-to-observation mapping are written\n"
            "outside the repository, so nobody can invert this",
            font_size=19,
            color=DIM,
            font=SANS,
            line_spacing=0.8,
        )
        outside.next_to(digest, DOWN, buff=0.55)

        self.play(Write(formula), run_time=1.4)
        self.play(FadeIn(digest, shift=UP * 0.15), run_time=0.7)
        self.play(FadeIn(outside), run_time=0.7)
        self.wait(1.6)
        bind = caption(
            f"One per item, all {COMMITMENTS_CHECKED} published before the review began."
        )
        self.play(FadeIn(bind), run_time=0.6)
        self.hold(1.5)
        self.play(FadeOut(formula), FadeOut(digest), FadeOut(outside), FadeOut(bind), run_time=0.5)

        # ---- 4. the sample ----------------------------------------------------
        self.section("sample")
        strip = VGroup(*[plate(i) for i in range(18)]).arrange(RIGHT, buff=0.14)
        strip.move_to(UP * 0.55)
        counts = Text(
            f"{N_ITEMS} items over {N_OBSERVATIONS} observations, "
            f"{N_REPEATS} of them repeated",
            font_size=21,
            color=INK,
            font=MONO,
        )
        counts.next_to(strip, DOWN, buff=0.6)
        schematic = Text(
            "schematic: the plates are full-resolution captures",
            font_size=16,
            color=DIM,
            font=SANS,
        )
        schematic.next_to(counts, DOWN, buff=0.24)
        self.play(
            LaggedStart(*[FadeIn(p, scale=0.85) for p in strip], lag_ratio=0.08),
            run_time=1.8,
        )
        self.play(FadeIn(counts), FadeIn(schematic), run_time=0.7)
        blind = caption("No label. No model output. No way to tell which are the repeats.")
        self.play(FadeIn(blind), run_time=0.6)
        self.hold(2.0)
        self.play(FadeOut(strip), FadeOut(counts), FadeOut(schematic), FadeOut(blind), run_time=0.5)

        # ---- 5. scoring refuses before it scores ------------------------------
        self.section("scoring")
        steps = VGroup(
            Text("re-hash every image from disk", font_size=22, color=INK, font=MONO),
            Text(
                f"recompute all {COMMITMENTS_CHECKED} commitments",
                font_size=22,
                color=INK,
                font=MONO,
            ),
            Text("refuse outright on any mismatch", font_size=22, color=WARN, font=MONO),
            Text("then, and only then, read the answers", font_size=22, color=INK, font=MONO),
        ).arrange(DOWN, buff=0.36, aligned_edge=LEFT)
        steps.move_to(LEFT * 1.4 + UP * 0.35)
        self.play(
            LaggedStart(*[FadeIn(s, shift=RIGHT * 0.25) for s in steps], lag_ratio=0.35),
            run_time=1.9,
        )
        self.hold(1.9)
        self.play(FadeOut(steps), run_time=0.45)

        # ---- 6. what came back ------------------------------------------------
        self.section("result")
        headline = Text(
            f"{DECISIVE} of {N_OBSERVATIONS} decidable",
            font_size=44,
            color=INK,
            font=SANS,
        )
        headline.move_to(UP * 1.1)
        interval = Text(
            f"rate {RATE:.3f},  exact one-sided 95% [{LOWER:.3f}, {UPPER:.3f}]",
            font_size=23,
            color=ACCENT,
            font=MONO,
        )
        interval.next_to(headline, DOWN, buff=0.42)
        bar = Text(
            f"the threshold was {THRESHOLD:.2f}, fixed before any of this",
            font_size=20,
            color=DIM,
            font=SANS,
        )
        bar.next_to(interval, DOWN, buff=0.3)
        agree = Text(
            f"and the same reader answered {INTRA_IDENTICAL} of {INTRA_PAIRS} "
            f"repeated plates identically",
            font_size=20,
            color=DIM,
            font=SANS,
        )
        agree.next_to(bar, DOWN, buff=0.26)
        self.play(FadeIn(headline, shift=UP * 0.2), run_time=0.9)
        self.play(FadeIn(interval), run_time=0.7)
        self.play(FadeIn(bar), FadeIn(agree), run_time=0.7)
        self.hold(2.2)

        # ---- 7. and the gate is open ------------------------------------------
        self.section("verdict")
        self.play(
            FadeOut(headline), FadeOut(interval), FadeOut(bar), FadeOut(agree), run_time=0.5
        )
        _human = REVIEWER_KIND == "human"
        verdict = Text(
            f"Gate 4: {VERDICT}", font_size=42, color=PASS if _human else OPEN, font=SANS
        )
        verdict.move_to(UP * 0.85)
        because = Text(
            "the reviewer was a person, which is what this gate asks for"
            if _human
            else f"the reviewer was a {REVIEWER_KIND}, not a person",
            font_size=24,
            color=INK,
            font=MONO,
        )
        because.next_to(verdict, DOWN, buff=0.44)
        rule = Text(
            (
                "and not an independent one: the author reviewed a corpus\n"
                "he built. What the commitment guarantees instead is that\n"
                "the sample and the plates were fixed before he saw them."
            )
            if _human
            else (
                "so the numbers above are published as an arm, and the gate\n"
                "keeps the verdict it had. The scorer will not write a rate\n"
                "at all without a declaration of who produced it."
            ),
            font_size=20,
            color=DIM,
            font=SANS,
            line_spacing=0.9,
        )
        rule.next_to(because, DOWN, buff=0.46)
        self.play(FadeIn(verdict, shift=UP * 0.2), run_time=0.9)
        self.play(FadeIn(because), run_time=0.7)
        self.play(FadeIn(rule), run_time=0.9)
        self.hold(3.0)
