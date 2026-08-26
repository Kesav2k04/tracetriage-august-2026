"""Manim scene: the nine pages of the console, and the one path through them.

Rendered to `apps/web/public/media/console-explainer.mp4` and served from the console's
own origin, so the content security policy stays closed and there is no embed from a
video host.

The subject is not a measurement. It is the shape of the site: a reader who lands on
`/start` has nine routes in front of them and no reason to believe any one of them
answers the question they arrived with. So this clip assembles the map in the order the
work happens rather than in the order of the navigation rail. One pass, then the two
pages that measure it, then the queue that ranks four hundred and seven of them, then
the four pages a reviewer checks the result against. The nav rail lists the routes. This
says what each one is for.

One decision worth stating, because it is the one that shaped every frame:

  Nothing in this clip quotes a fitted number. The three figures on screen are 407, 50
  and 3, and each of them is a count that a receipt already publishes: the deduplicated
  queue, the review budget fixed before any result was seen, and the gates that came back
  NOT_ESTABLISHED. The obvious version of the opening beat put a frequency offset in hertz
  beside the plate, which would have been a second copy of a value that lives in
  `scripts/explainer_corridor.py` and is pinned by `tests/test_explainer_values.py` against
  the card it came from. A duplicate has nothing holding it, so the two would drift and the
  video would be the one that was wrong. The opening readout names what the image holds
  instead, and the pass's actual numbers stay on the page the arrow points at.

The second decision is layout rather than content, and it is why the close beat looks the
way it does. Four of the eight arrows into the receipt token run down a lane between two
of the bottom-row nodes rather than straight at the token. Drawn straight, an arrow from
the upper band crosses a node it has nothing to do with, and a map whose lines run through
its own boxes is a worse map than one with two corners in it.

Render:
    manim -qh scripts/explainer_console.py ConsoleExplainer
    ffmpeg -i <manim output>.mp4 -c copy -movflags +faststart \
        apps/web/public/media/console-explainer.mp4

The second command is not optional, for the reason `scripts/explainer_corridor.py` gives:
Manim writes the `moov` atom after `mdat`, so a browser cannot start playback until it has
fetched to the end of the file. `-c copy` is a stream copy, so the frames stay bit
identical and the palette check still reads true colours out of the committed file.

Mute, the authored floors run 36.6 seconds. With the narration laid on they run about 44,
because three of the five sections take longer to say than to draw.
`explainer_timing.NarratedScene` holds each section for its own line, and the floor only
decides the two whose line is shorter than the animation it sits over.

The opening is deliberately slow and deliberately empty. For the first two seconds there
is one rectangle drawing itself in the middle of a dark frame and nothing else, not even
the title. This clip is the first thing a reader sees on a page of tables, and the beat
that earns their attention is the one that shows them the whole thing is simple.
"""

# ruff: noqa: F403, F405
# `from manim import *` is the idiom manim's own documentation and every example in it
# use, and the library exports several hundred names a scene needs. The star import is
# confined to the render scripts, which nothing else imports.
from pathlib import Path

import numpy as np
from explainer_timing import NarratedScene
from manim import *

# ---------------------------------------------------------------------------
# Typeface. Same arrangement as scripts/explainer_corridor.py: the console self-hosts
# IBM Plex as woff2, Pango needs an outline font, and `make explainer` converts the same
# files the site serves. Without this Pango falls back to a serif silently.
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


def _palette() -> dict[str, str]:
    """The console's own tokens, read out of its stylesheet rather than copied here.

    The corridor scene learned this the expensive way: seven hardcoded hex strings matched
    the site when they were written, the palette moved twice, and the clip embedded on the
    landing page rendered in a scheme the page had abandoned.

    Two of these are chosen for what the token means rather than for its hue. EDGE is
    `ui-04`, the component boundary, because every arrow here is a boundary between two
    pages. LIVE is `live-01`, which the stylesheet reserves for "measured just now", and
    the only node it is spent on is `/live`, which is the only page in the map that
    measures anything at request time.
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
        "EDGE": "ui-04",
        "ACCENT": "interactive-01",
        "LIVE": "live-01",
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
EDGE, ACCENT, LIVE = _P["EDGE"], _P["ACCENT"], _P["LIVE"]
PAPER, PANEL = _P["PAPER"], _P["PANEL"]

# ---------------------------------------------------------------------------
# The three figures on screen. Each is a count a receipt publishes rather than a number a
# model produced. Two of them are spoken as well. The third, the gates that did not pass,
# is named in the narration without its count, so the frame carries the number and the
# line carries the claim.
# ---------------------------------------------------------------------------
#: Observations in the deduplicated queue. artifacts/QUEUE_RECEIPT.json,
#: deduplication.n_observations_after.
RANKED = 407
#: The review budget, fixed before any result was seen. Same receipt, review_budget.
BUDGET = 50
#: Gates whose verdict is NOT_ESTABLISHED: 3, 5 and 6. The gate summary the console
#: renders counts three of six met, which is the same statement from the other side.
GATES_NOT_PASSED = 3
#: The closing line, which is the one sentence in this clip that makes a claim about the
#: site rather than about a page. Seven routes are drawn; it counts all nine, and the two
#: it does not draw are the page this clip sits on and the replay.
CLOSING_LINE = "Nine pages. Every arrow ends at a receipt."
#: So the sentence above cannot outlive the site it describes. A route added or removed
#: stops the render rather than shipping a clip that miscounts the console by one, which
#: is the drift nobody watching a video would catch.
PAGES = 9
_ROUTES = sorted(
    p.relative_to(Path(__file__).resolve().parents[1] / "apps/web/app").as_posix()
    for p in (Path(__file__).resolve().parents[1] / "apps/web/app").rglob("page.tsx")
)
if len(_ROUTES) != PAGES:
    raise SystemExit(
        f"the closing frame says {PAGES} pages and apps/web/app now holds {len(_ROUTES)}: "
        f"{', '.join(_ROUTES)}. Reword the line and the narration together."
    )

#: The ranked column is a picture of a ratio, not of 407 rows. Drawing one bar per
#: observation at this size gives a solid block, so the column is subsampled and the
#: highlight is computed from the real counts rather than picked to look right.
N_BARS = 34
N_HIGHLIGHT = max(1, round(BUDGET / RANKED * N_BARS))

# ---------------------------------------------------------------------------
# Layout. The frame is 14.22 by 8 units, so x runs -7.11 to 7.11 and y runs -4 to 4.
# Every number below is a centre or an edge in that space, and they are written here
# rather than inline because the close beat has to route arrows through the gaps the
# bottom row leaves, and a gap that is only correct by accident closes the first time
# a caption is reworded.
# ---------------------------------------------------------------------------
PASS_AT = np.array([-5.15, 1.0, 0.0])

OBS_AT, OBS_W = np.array([-0.6, 2.15, 0.0]), 4.30
LIVE_AT, LIVE_W = np.array([-1.5, 0.5, 0.0]), 2.50
QUEUE_AT, QUEUE_W = np.array([3.1, 1.55, 0.0]), 1.90

#: The ranked column hangs off the queue node. Left aligned, widest bar at the top, so
#: the shape reads as a ranking rather than as a histogram.
BARS_LEFT, BARS_TOP, BARS_H, BARS_W = 2.575, 0.75, 1.70, 1.05

#: The bottom row, laid out left to right with the widths its captions need. The first
#: gap is wider than the other two on purpose: two of the close beat's arrows come down
#: through it.
CHECK_Y = -1.95
CHECK_SPEC = [
    ("/evaluation", f"the gates, including\nthe {GATES_NOT_PASSED} that did not pass", 3.55),
    ("/agent", "the same evidence,\nfor a model", 2.88),
    ("/provenance", "where every number\ncame from", 2.88),
    ("/precedent", "what was\nalready known", 2.66),
]
CHECK_GAPS = [0.95, 0.35, 0.35]
CHECK_X = [-5.035, -0.87, 2.36, 5.48]

RECEIPT_AT, RECEIPT_W, RECEIPT_H = np.array([0.0, -3.42, 0.0]), 2.70, 0.66

#: The four vertical lanes the close beat's routed arrows run down, each in a gap the
#: bottom row leaves. LANE_L1 and LANE_L2 share the wide first gap.
LANE_L1, LANE_L2, LANE_M, LANE_R = -3.12, -2.90, 0.745, 3.975
#: The height the lanes turn toward the token at, clear of the bottom row.
LANE_FLOOR = -3.02

#: What a section that has had its turn is held at while the next one is drawn. It is an
#: absolute opacity rather than a multiplier, so a node that is dimmed twice is no fainter
#: than a node dimmed once, and on a ground this dark it reads as receding rather than as
#: fading out. The whole map comes back to full before the closing beat.
DIMMED = 0.6


def node(route: str, caption: str, width: float, accent: str = INK) -> VGroup:
    """One page: a bordered plate holding a route and what the route is for.

    The plate is sized from the caller's width rather than from its contents, because the
    map is laid out to the unit and a node that grows with its own text moves everything
    to the right of it. The guard below is the price of that: if the installed font is
    wider than IBM Plex the body is scaled to fit rather than allowed to run over its own
    border, which is the one failure a still frame makes obvious and a digest cannot see.
    """
    label = Text(route, font_size=20, color=accent, font=MONO)
    note = Text(caption, font_size=14, color=DIM, font=SANS, line_spacing=0.8)
    body = VGroup(label, note).arrange(DOWN, buff=0.16)
    inner = width - 0.36
    if body.width > inner:
        body.scale(inner / body.width)
    box = RoundedRectangle(
        corner_radius=0.09,
        width=width,
        height=body.height + 0.44,
        stroke_color=GRID,
        stroke_width=2.0,
        fill_color=PANEL,
        fill_opacity=1.0,
    )
    body.move_to(box.get_center())
    return VGroup(box, body)


def link(start, end, color: str = EDGE) -> Arrow:
    """A directed edge between two nodes.

    `max_tip_length_to_length_ratio` is raised from manim's default because several of
    these arrows are shorter than a unit, and at the default the tip on a 0.6 unit arrow
    shrinks until the edge reads as a line with no direction in it.
    """
    return Arrow(
        np.array(start, dtype=float),
        np.array(end, dtype=float),
        color=color,
        stroke_width=2.6,
        buff=0.06,
        tip_length=0.18,
        max_tip_length_to_length_ratio=0.4,
    )


def routed(points: list, color: str = ACCENT) -> VGroup:
    """A directed edge with corners in it, for the arrows that cannot travel straight."""
    corners = [np.array(p, dtype=float) for p in points]
    legs = [
        Line(corners[i], corners[i + 1], color=color, stroke_width=2.4)
        for i in range(len(corners) - 2)
    ]
    legs.append(link(corners[-2], corners[-1], color=color))
    return VGroup(*legs)


class ConsoleExplainer(NarratedScene):
    clip = "console"

    def construct(self) -> None:
        self.camera.background_color = PAPER

        title = Text("The console", font_size=28, color=INK, font=SANS)
        title.to_edge(UP, buff=0.42).to_edge(LEFT, buff=0.56)
        sub = Text("nine pages, one map", font_size=17, color=DIM, font=MONO)
        sub.next_to(title, DOWN, buff=0.16).align_to(title, LEFT)

        # ---- 1. one pass, and what was written down about it -------------------
        self.section("pass")
        plate = Rectangle(
            width=1.15,
            height=1.50,
            stroke_color=GRID,
            stroke_width=1.6,
            fill_color=PANEL,
            fill_opacity=1.0,
        )
        # The trace is steep through the middle and flat at both ends, which is the shape
        # a Doppler corridor has and the shape the corridor clip fits. It is drawn from a
        # tanh rather than traced from an image: this plate is a diagram of a waterfall,
        # and the real ones are 113 MB of captures, so a rectangle must not be mistaken
        # for one.
        trace = VMobject(color=INK, stroke_width=2.2, stroke_opacity=0.9)
        trace.set_points_as_corners(
            [
                np.array(
                    [
                        0.30 * np.tanh(4.0 * (t - 0.5)) / np.tanh(2.0),
                        -0.65 + 1.30 * t,
                        0.0,
                    ]
                )
                for t in np.linspace(0.0, 1.0, 21)
            ]
        )
        plate_group = VGroup(plate, trace)

        archive = VGroup(
            Text("the archive", font_size=12, color=DIM, font=SANS),
            Text("with-signal", font_size=17, color=INK, font=MONO),
            Text("two words", font_size=14, color=DIM, font=MONO),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.11)
        top_row = VGroup(plate_group, archive).arrange(RIGHT, buff=0.26)

        signal = VGroup(
            Text("what the image holds", font_size=12, color=DIM, font=SANS),
            Text("a curved trace", font_size=15, color=ACCENT, font=MONO),
            Text("a fitted offset", font_size=15, color=ACCENT, font=MONO),
            Text("a corridor it sits in", font_size=15, color=ACCENT, font=MONO),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.11)

        one_pass = VGroup(top_row, signal).arrange(DOWN, aligned_edge=LEFT, buff=0.30)
        one_pass.move_to(PASS_AT)

        # The recording opens near the middle of the frame and walks to its place on the
        # left once there is something to make room for. Only the plate is on screen while
        # it does, so this is one object moving, not a group of them: the rest of the pass
        # block keeps the position the arrange gave it and is faded in afterwards.
        plate_home = plate_group.get_center().copy()
        plate_group.move_to([-1.2, 0.6, 0.0])

        self.play(Create(plate), run_time=0.9)
        self.play(Create(trace), run_time=0.8)
        self.wait(0.5)
        self.play(
            plate_group.animate.move_to(plate_home),
            run_time=0.9,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(FadeIn(title, shift=UP * 0.2), FadeIn(sub), run_time=0.9)
        self.play(FadeIn(archive, shift=RIGHT * 0.15), run_time=0.8)
        self.play(
            LaggedStart(
                *[FadeIn(line, shift=RIGHT * 0.12) for line in signal], lag_ratio=0.65
            ),
            run_time=1.3,
        )
        self.hold(2.4)

        # ---- 2. the two pages that measure it ----------------------------------
        self.section("measure")
        observation = node("/observation/[id]", "the evidence\nfor one pass", OBS_W)
        observation.move_to(OBS_AT)
        live = node("/live", "measures a new\none on demand", LIVE_W, accent=LIVE)
        live.move_to(LIVE_AT)

        to_observation = link(
            [top_row.get_right()[0], OBS_AT[1], 0.0],
            [observation.get_left()[0], OBS_AT[1], 0.0],
        )
        to_live = link(
            [signal.get_right()[0], LIVE_AT[1], 0.0],
            [live.get_left()[0], LIVE_AT[1], 0.0],
        )

        self.play(one_pass.animate.set_opacity(DIMMED), run_time=0.4)
        self.play(
            FadeIn(observation, shift=LEFT * 0.25),
            run_time=0.8,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(GrowArrow(to_observation), run_time=0.55)
        self.play(
            FadeIn(live, shift=LEFT * 0.25),
            run_time=0.8,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(GrowArrow(to_live), run_time=0.55)
        self.hold(3.8)

        # ---- 3. the queue that ranks them --------------------------------------
        self.section("queue")
        queue = node("/", "the queue", QUEUE_W)
        queue.move_to(QUEUE_AT)

        slot = BARS_H / N_BARS
        bars = VGroup()
        for index in range(N_BARS):
            width = BARS_W * (1.0 - 0.62 * index / (N_BARS - 1))
            bar = Rectangle(
                width=width,
                height=slot * 0.62,
                stroke_width=0.0,
                fill_opacity=1.0,
                fill_color=ACCENT if index < N_HIGHLIGHT else EDGE,
            )
            bar.move_to([BARS_LEFT + width / 2.0, BARS_TOP - (index + 0.5) * slot, 0.0])
            bars.add(bar)

        opened = VGroup(
            Text(f"{BUDGET}", font_size=20, color=ACCENT, font=MONO),
            Text("opened", font_size=12, color=DIM, font=SANS),
        ).arrange(DOWN, buff=0.06)
        opened.move_to([1.95, BARS_TOP - N_HIGHLIGHT * slot / 2.0, 0.0])
        ranked = VGroup(
            Text(f"{RANKED}", font_size=20, color=DIM, font=MONO),
            Text("ranked", font_size=12, color=DIM, font=SANS),
        ).arrange(DOWN, buff=0.06)
        ranked.move_to([1.95, -0.50, 0.0])

        observation_to_queue = link(
            [observation.get_right()[0], 2.00, 0.0], [queue.get_left()[0], 1.90, 0.0]
        )
        live_to_queue = link(
            [live.get_right()[0], 0.55, 0.0], [queue.get_left()[0], 1.30, 0.0]
        )

        measured = VGroup(observation, live, to_observation, to_live)
        self.play(measured.animate.set_opacity(DIMMED), run_time=0.4)
        self.play(
            FadeIn(queue, shift=DOWN * 0.2),
            run_time=0.75,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(
            LaggedStart(
                GrowArrow(observation_to_queue),
                GrowArrow(live_to_queue),
                lag_ratio=0.55,
            ),
            run_time=1.1,
        )
        # One wipe down the column rather than 34 entrances. The lag is short enough that
        # the bars read as a single object filling in, which is what they are: a picture
        # of one ratio, not thirty-four things arriving.
        self.play(
            LaggedStart(*[FadeIn(bar) for bar in bars], lag_ratio=0.04), run_time=1.2
        )
        self.play(FadeIn(opened, shift=DOWN * 0.1), FadeIn(ranked), run_time=0.7)
        self.hold(3.6)

        # ---- 4. the four pages a reviewer checks it against --------------------
        self.section("check")
        checks = VGroup()
        for (route, caption, width), x in zip(CHECK_SPEC, CHECK_X, strict=True):
            page = node(route, caption, width)
            page.move_to([x, CHECK_Y, 0.0])
            checks.add(page)

        fan_from = [BARS_LEFT + BARS_W * 0.19, BARS_TOP - BARS_H, 0.0]
        fan = VGroup(
            *[
                link(fan_from, [x, page.get_top()[1], 0.0])
                for page, x in zip(checks, CHECK_X, strict=True)
            ]
        )

        ranking = VGroup(queue, bars, opened, ranked, observation_to_queue, live_to_queue)
        self.play(ranking.animate.set_opacity(DIMMED), run_time=0.4)
        # Four nodes, one at a time. At this lag each entrance is 0.8 seconds and only
        # overlaps its neighbour's tail, so the row builds left to right rather than
        # arriving all at once.
        self.play(
            LaggedStart(
                *[FadeIn(page, shift=UP * 0.22) for page in checks], lag_ratio=0.75
            ),
            run_time=2.6,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(
            LaggedStart(*[GrowArrow(edge) for edge in fan], lag_ratio=0.7),
            run_time=1.7,
        )
        self.hold(3.2)

        # ---- 5. and all of it ends in the same place ---------------------------
        self.section("close")
        token = VGroup(
            RoundedRectangle(
                corner_radius=0.10,
                width=RECEIPT_W,
                height=RECEIPT_H,
                stroke_color=ACCENT,
                stroke_width=2.2,
                fill_color=PANEL,
                fill_opacity=1.0,
            ),
            Text("receipt", font_size=21, color=ACCENT, font=MONO),
        )
        token.move_to(RECEIPT_AT)

        closing = Text(CLOSING_LINE, font_size=24, color=INK, font=SANS)
        closing.move_to([0.0, 3.42, 0.0])

        # The bottom row reaches the token straight down. Everything above it goes through
        # a lane, for the reason the module docstring gives: drawn straight, four of these
        # run through a node they have nothing to do with.
        receipts = VGroup(
            routed(
                [
                    [PASS_AT[0], one_pass.get_bottom()[1], 0.0],
                    [PASS_AT[0], -0.85, 0.0],
                    [LANE_L1, -0.85, 0.0],
                    [LANE_L1, LANE_FLOOR, 0.0],
                    [-1.40, -3.28, 0.0],
                ]
            ),
            routed(
                [
                    observation.get_corner(DL),
                    [LANE_L2, observation.get_bottom()[1] - 0.22, 0.0],
                    [LANE_L2, LANE_FLOOR, 0.0],
                    [-1.34, -3.16, 0.0],
                ]
            ),
            routed(
                [
                    live.get_bottom(),
                    [LIVE_AT[0], -0.55, 0.0],
                    [LANE_M, -0.55, 0.0],
                    [LANE_M, LANE_FLOOR, 0.0],
                    [0.55, -3.12, 0.0],
                ]
            ),
            routed(
                [
                    [BARS_LEFT + BARS_W, 0.72, 0.0],
                    [LANE_R, 0.72, 0.0],
                    [LANE_R, LANE_FLOOR, 0.0],
                    [1.34, -3.26, 0.0],
                ]
            ),
            *[
                link(page.get_bottom(), target, color=ACCENT)
                for page, target in zip(
                    checks,
                    (
                        [-1.30, -3.34, 0.0],
                        [-0.45, -3.12, 0.0],
                        [0.45, -3.12, 0.0],
                        [1.30, -3.34, 0.0],
                    ),
                    strict=True,
                )
            ],
        )

        # The four long lanes and the four short drops are not equally worth looking at.
        # Drawn at one weight the lanes win, because they are the longest lines on screen,
        # and the closing frame then reads as traffic rather than as a map that resolves.
        # So the lanes drop back to connective tissue and the short drops stay crisp: the
        # eye lands on the token, and the lanes are still there for anyone who follows one.
        for lane in receipts[:4]:
            lane.set_stroke(width=1.6, opacity=0.32)

        # The payoff for the opening. Every section that stepped back while the next one
        # was drawn comes forward together, so the last thing on screen is the whole map
        # rather than the part that happens to be talking. An earlier version dimmed the
        # explained nodes here instead, which is right in the middle of a clip and wrong at
        # the end of one: it leaves a reader looking at a diagram that is still receding.
        whole_map = VGroup(one_pass, measured, ranking, checks, fan)
        self.play(
            whole_map.animate.set_opacity(1.0), FadeOut(VGroup(title, sub)), run_time=0.6
        )
        self.play(
            FadeIn(token, scale=0.92),
            run_time=0.7,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(
            LaggedStart(*[Create(edge) for edge in receipts], lag_ratio=0.55),
            run_time=1.9,
        )
        self.play(FadeIn(closing, shift=DOWN * 0.12), run_time=0.75)
        self.hold(1.6)
