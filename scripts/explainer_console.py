"""Manim scene: a camera tour of the nine pages of the console, and the path through them.

Rendered to `apps/web/public/media/console-explainer.mp4` and served from the console's
own origin, so the content security policy stays closed and there is no embed from a
video host.

The subject is not a measurement. It is the shape of the site: a reader who lands on
`/start` has nine routes in front of them and no reason to believe any one of them
answers the question they arrived with. So the whole map is laid out once, in world
coordinates about 28 units wide and 15 tall, roughly four screens across and two down,
and the camera flies along it. One recording, then the two pages that measure it, then
the queue that ranks four hundred and seven of them, then the four pages a reviewer
checks the result against, and only in the last three seconds does the frame pull back
far enough to hold the whole thing at once.

The first version of this clip drew the same map inside a single frame and dimmed each
group as the next arrived. Everything was legible in the still and nothing was legible in
motion: a node sized to fit nine of its siblings is a node nobody can read, and dimming
is a way of apologising for that rather than fixing it. Moving the camera instead means a
node is only ever on screen at the size it was drawn for. The cost is that the closing
frame is a shape rather than a page of text, and the two things a reader is meant to read
there, the receipt and the closing line, are set two and a half times larger than
everything else so they survive the pull back.

Two other decisions are worth stating, because both are load bearing:

  The plate in the opening beat is a real waterfall, observation 14740031 from the
  shipped set, cropped in time to its first 810 rows and untouched in value. An earlier
  version drew a tanh curve inside a rectangle so that no rectangle could be mistaken for
  a capture. That was the wrong trade: the whole clip argues the console shows evidence,
  and opening on a drawing of evidence undercuts the argument in the first two seconds.
  The image is CC BY-SA 4.0, and `artifacts/ATTRIBUTION_AUDIT.json` resolves an
  observation id from the filename, so a video called `console-explainer.mp4` audits as
  `not_applicable` no matter what it contains. The credit is therefore in the frame,
  under the plate, where it does not depend on an auditor that cannot see it.

  No arrow in this map crosses another arrow or passes through a node, and that is
  checked rather than claimed. `_audit` runs over the real bounding boxes and the real
  segment endpoints before the first frame is drawn, and stops the render with the pair
  of names that collided. The layout is built to make it pass by construction: the map is
  a directed graph with one source, the recording, and one sink, the receipt, drawn in
  four bands that do not overlap in y, so an arrow in one band cannot reach an arrow in
  another. Inside a band the rules are narrow. The two arrows out of the plate are
  parallel horizontals at different heights. The one route that bends does so once, at a
  right angle, down a vertical lane in the gap between the observation node and the
  queue. The fan into the review pages is four straight segments from one point, and
  segments sharing an endpoint cannot meet anywhere else. The four evidence links are an
  order preserving matching between two horizontal lines, left to left and right to
  right, which is the standard non crossing construction.

Because the graph has one sink, the closing line is now literally true rather than
figuratively true. Follow any arrow forward and it reaches the receipt.

Render:
    manim -qh scripts/explainer_console.py ConsoleExplainer
    ffmpeg -i <manim output>.mp4 -c copy -movflags +faststart \
        apps/web/public/media/console-explainer.mp4

The second command is not optional, for the reason `scripts/explainer_corridor.py` gives:
Manim writes the `moov` atom after `mdat`, so a browser cannot start playback until it has
fetched to the end of the file. `-c copy` is a stream copy, so the frames stay bit
identical and the palette check still reads true colours out of the committed file.

Mute, the authored floors run 42.9 seconds. With the narration laid on they run about 47,
because four of the five sections take longer to say than to fly.
`explainer_timing.NarratedScene` holds each section for its own line, and the floor only
decides the section whose line is shorter than the move it sits over.
"""

# ruff: noqa: F403, F405
# `from manim import *` is the idiom manim's own documentation and every example in it
# use, and the library exports several hundred names a scene needs. The star import is
# confined to the render scripts, which nothing else imports.
import math
from pathlib import Path

import numpy as np
from explainer_timing import NarratedScene
from manim import *

REPO = Path(__file__).resolve().parents[1]

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
    `ui-04`, the component boundary, because every data arrow here is a boundary between
    two pages. LIVE is `live-01`, which the stylesheet reserves for "measured just now",
    and the only node it is spent on is `/live`, which is the only page in the map that
    measures anything at request time.
    """
    import re

    css = (REPO / "apps/web/app/globals.css").read_text(encoding="utf-8")
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
    p.relative_to(REPO / "apps/web/app").as_posix()
    for p in (REPO / "apps/web/app").rglob("page.tsx")
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
# The plate. A real capture from the shipped set, not a drawing of one.
# ---------------------------------------------------------------------------
#: The observation the opening beat shows. It is in the manifest, its waterfall_status is
#: the literal string the beat quotes, and the same file is what `/observation/14740031`
#: serves, so the arrow out of the plate points at a page that shows this image.
WATERFALL_OBS = 14740031
WATERFALL_FILE = f"apps/web/public/waterfalls/{WATERFALL_OBS}.webp"
#: Rows kept, out of 1540. The capture is 620 by 1540, which at any height that makes the
#: corridor visible is a strip too narrow to compose a frame around. The crop is in time
#: and not in frequency: every column the receiver recorded is on screen, and the trace
#: keeps the curvature that makes it a Doppler corridor rather than a line.
WATERFALL_ROWS = 810
WATERFALL_COLS = 620
WATERFALL_LICENCE = (f"observation {WATERFALL_OBS}", "SatNOGS, CC BY-SA 4.0")

# ---------------------------------------------------------------------------
# Layout. World coordinates, not frame coordinates: the map spans x -15.95 to 12.35 and
# y -9.25 to 6.23, which is about four default frames across and two down. Every arrow
# lives in exactly one of four bands that do not overlap in y, which is what makes the
# no-crossing check below pass rather than merely usually pass:
#
#   the pipeline band        y >= 0.12   plate, /observation/[id], /live, / and the bars
#   the fan band             y in -4.57 .. -0.60
#   the review row           y in -5.83 .. -4.57
#   the evidence band        y in -7.55 .. -5.83
# ---------------------------------------------------------------------------
WATERFALL_H = 4.30
WATERFALL_AT = (-14.30, 2.40)

OBS_AT, OBS_W = (-4.60, 3.85), 4.80
LIVE_AT, LIVE_W = (-3.40, 0.75), 4.40
QUEUE_AT, QUEUE_W = (2.90, 3.85), 2.90

#: The two heights the plate's arrows leave at. The upper one passes over the archive
#: caption, the lower one passes under it, and both start on the plate's right edge.
TO_OBS_Y = 3.85
TO_LIVE_Y = 0.75

#: The two heights the queue is entered at, both on its left edge. Different heights so
#: the straight route and the bent route cannot land on the same point.
TO_QUEUE_Y = 4.20
LIVE_TURN_Y = 3.45
#: The vertical lane the bent route runs up, in the gap between the observation node's
#: right edge and the queue node's left edge. It is inside `/live`'s own width, so the
#: route leaves from the top of the node it belongs to rather than from a corner.
LIVE_LANE_X = -1.45

#: The ranked column hangs off the queue node. Left aligned, widest bar at the top, so
#: the shape reads as a ranking rather than as a histogram.
BARS_LEFT, BARS_TOP, BARS_H, BARS_W = 1.50, 2.75, 3.10, 2.40
#: The two figures beside the column, in one right hand rail so the eye reads down.
FIGURE_X = 4.75

#: Where the fan into the review row starts: one point, below the narrowest bar. Four
#: straight segments from a single point cannot cross each other, which is half of why
#: the bottom of this map is legible.
FAN_FROM = (2.05, -0.60)

#: The review row. One line of description each, because a page whose purpose needs two
#: lines is a page the map is describing badly.
CHECK_Y = -5.20
CHECK_SPEC = [
    ("/evaluation", f"the gates, and the {GATES_NOT_PASSED} that did not pass", 5.45),
    ("/agent", "the same evidence, reached by a model", 5.30),
    ("/provenance", "where every number came from", 4.25),
    ("/precedent", "what was already known before this", 5.05),
]
CHECK_GAPS = [1.55, 1.55, 1.55]


def _row_centres(widths: list[float], gaps: list[float], centre: float) -> list[float]:
    """Centres for a row of boxes with the given widths and gaps, centred on `centre`.

    Computed rather than written down, because the widths above are chosen from the
    captions and a reworded caption moves every node to the right of it. The first version
    of this scene hardcoded four x values, which meant every edit had a silent chance of
    closing the lane an arrow runs down.
    """
    edge = centre - (sum(widths) + sum(gaps)) / 2.0
    out = []
    for index, width in enumerate(widths):
        out.append(edge + width / 2.0)
        edge += width + (gaps[index] if index < len(gaps) else 0.0)
    return out


CHECK_X = _row_centres([w for _, _, w in CHECK_SPEC], CHECK_GAPS, 0.0)

RECEIPT_AT, RECEIPT_W, RECEIPT_H = (0.0, -8.40), 6.40, 1.70
#: Where each review page's evidence link lands on the receipt. Left to right in the same
#: order as the row above, which is the whole reason none of the four cross.
RECEIPT_PORTS = [-2.30, -0.80, 0.80, 2.30]

CLOSING_AT = (0.0, 5.85)

# ---------------------------------------------------------------------------
# The camera. Every move between beats is played rather than cut, and only the opening
# frame is a number: the rest are asked for by naming what has to be in shot, and
# `frame_on` measures those mobjects and covers them. Doing it the other way round, with
# a centre and a width per beat, is what put the waterfall half outside the left edge for
# two beats, because a width picked by eye does not know how tall the group at that
# centre is. Widths still decide readability, so the floor on the opening beat is kept:
# at width 10.5 a 30 point route is about 50 pixels tall at 1080, and by the closing
# frame it is nearer 24, which is why the receipt and the closing line are set at 62 and
# 60 and nothing else is asked to carry meaning in the last beat.
FRAME_PAD = 0.85
ASPECT = 16.0 / 9.0

CAM_OPEN = ((-14.30, 2.40), 8.2)


# ---------------------------------------------------------------------------
# The layout check. Prose in a docstring saying the arrows do not cross is worth nothing
# the first time somebody widens a caption, so the claim is made against the mobjects
# that were actually built, before a single frame is rendered.
# ---------------------------------------------------------------------------
def _point(vector) -> tuple[float, float]:
    """A hashable 2D point. Rounded so two arrows sharing a corner compare equal."""
    return (round(float(vector[0]), 6), round(float(vector[1]), 6))


def _box(mobject) -> tuple[float, float, float, float]:
    """A mobject's bounding box as (left, right, bottom, top)."""
    return (
        float(mobject.get_left()[0]),
        float(mobject.get_right()[0]),
        float(mobject.get_bottom()[1]),
        float(mobject.get_top()[1]),
    )


def _inside(box, start, end) -> float:
    """How far segment start to end travels inside `box`, in world units.

    Liang and Barsky's clip. The box is shrunk first, so an arrow that begins or ends on a
    node's edge, which every arrow here does, reports zero rather than reporting the
    single point it touches.
    """
    left, right, bottom, top = box
    slack = 0.03
    lo = 0.0
    hi = 1.0
    for low, high, origin, delta in (
        (left + slack, right - slack, start[0], end[0] - start[0]),
        (bottom + slack, top - slack, start[1], end[1] - start[1]),
    ):
        if abs(delta) < 1e-9:
            if origin < low or origin > high:
                return 0.0
            continue
        first, second = (low - origin) / delta, (high - origin) / delta
        if first > second:
            first, second = second, first
        lo, hi = max(lo, first), min(hi, second)
        if lo > hi:
            return 0.0
    return (hi - lo) * math.hypot(end[0] - start[0], end[1] - start[1])


def _side(a, b, c) -> float:
    """Which side of the line a to b the point c falls on."""
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _cross(one, other) -> bool:
    """True when two segments meet anywhere other than at a shared endpoint."""
    a, b = one
    c, d = other
    if {a, b} & {c, d}:
        return False
    return (_side(c, d, a) > 0) != (_side(c, d, b) > 0) and (_side(a, b, c) > 0) != (
        _side(a, b, d) > 0
    )


def _audit(boxes: dict, edges: dict) -> None:
    """Stop the render if any arrow runs through a node or across another arrow."""
    for node_name, box in boxes.items():
        for edge_name, (start, end) in edges.items():
            depth = _inside(box, start, end)
            if depth > 0.06:
                raise SystemExit(
                    f"the {edge_name} arrow runs {depth:.2f} units through the "
                    f"{node_name} node. Move the node or bend the route once at a right "
                    f"angle; a map whose lines run through its own boxes is a worse map "
                    f"than one with a corner in it."
                )
    names = list(edges)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            if _cross(edges[first], edges[second]):
                raise SystemExit(
                    f"the {first} and {second} arrows cross. The layout is meant to make "
                    f"that impossible by construction, so this is a band that stopped "
                    f"being a band rather than a near miss to nudge."
                )


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------
def node(route: str, caption: str, width: float, accent: str = INK) -> VGroup:
    """One page: a bordered plate holding a route and what the route is for.

    The plate is sized from the caller's width rather than from its contents, because the
    map is laid out to the unit and a node that grows with its own text moves everything
    to the right of it. The guard below is the price of that: if the installed font is
    wider than IBM Plex the body is scaled to fit rather than allowed to run over its own
    border, which is the one failure a still frame makes obvious and a digest cannot see.
    """
    label = Text(route, font_size=30, color=accent, font=MONO)
    note = Text(caption, font_size=21, color=DIM, font=SANS)
    body = VGroup(label, note).arrange(DOWN, buff=0.16)
    inner = width - 0.40
    if body.width > inner:
        body.scale(inner / body.width)
    box = RoundedRectangle(
        corner_radius=0.12,
        width=width,
        height=body.height + 0.46,
        stroke_color=GRID,
        stroke_width=2.4,
        fill_color=PANEL,
        fill_opacity=1.0,
    )
    body.move_to(box.get_center())
    return VGroup(box, body)


def flow(start, end) -> Arrow:
    """A data arrow: one page handing its output to the next. Muted grey, weight 3.

    `max_tip_length_to_length_ratio` is raised from manim's default because the shortest
    of these is under three units, and at the default the tip shrinks until the edge reads
    as a line with no direction in it.
    """
    return Arrow(
        np.array([start[0], start[1], 0.0]),
        np.array([end[0], end[1], 0.0]),
        color=EDGE,
        stroke_width=3.0,
        buff=0.06,
        tip_length=0.20,
        max_tip_length_to_length_ratio=0.4,
    )


def evidence(start, end) -> Arrow:
    """An evidence link: a page pointing at the receipt behind it. Accent, weight 2."""
    return Arrow(
        np.array([start[0], start[1], 0.0]),
        np.array([end[0], end[1], 0.0]),
        color=ACCENT,
        stroke_width=2.0,
        buff=0.06,
        tip_length=0.20,
        max_tip_length_to_length_ratio=0.4,
    )


def bent(start, corner, end) -> tuple[Line, Arrow]:
    """The one route that cannot travel straight: a leg, one right angle, then the head.

    Returned as two pieces rather than as a group so the entrance can be a `Succession`.
    An arrow that appears whole is a cut; this one is drawn along its own direction, turns
    the corner, and arrives.
    """
    leg = Line(
        np.array([start[0], start[1], 0.0]),
        np.array([corner[0], corner[1], 0.0]),
        color=EDGE,
        stroke_width=3.0,
    )
    return leg, flow(corner, end)


class ConsoleExplainer(NarratedScene, MovingCameraScene):
    """The tour. `NarratedScene` gives the section timing, `MovingCameraScene` the frame.

    The method resolution order is ConsoleExplainer, NarratedScene, MovingCameraScene,
    Scene. `NarratedScene` defines `setup` and `tear_down` and calls `super()` in both,
    which lands on `MovingCameraScene`, which defines neither, so both reach `Scene`.
    `MovingCameraScene.__init__` is the only `__init__` in the chain, so the camera class
    is still `MovingCamera` and `self.camera.frame` exists.
    """

    clip = "console"

    def frame_on(self, *items, pad=FRAME_PAD, least=0.0):
        """Frame the union of `items`, with clearance, at the render's aspect ratio.

        This replaced a table of centres and widths picked by eye, three of which cut a
        node off at the frame edge: a centre and a width cannot know how tall the thing
        at that centre is, so a group that is wide enough to fit was still too tall, and
        the waterfall spent two beats hanging half outside the left edge with the right
        half of the frame empty. A union box covering both axes cannot make that mistake.

        `least` is a floor for the width, for the two beats where the group is small
        enough that fitting it exactly would push the type larger than the beat before.
        """
        group = Group(*items)
        need = max(group.width + 2 * pad, (group.height + 2 * pad) * ASPECT, least)
        return self.camera.frame.animate.move_to(group.get_center()).set(width=need)

    def construct(self) -> None:
        self.camera.background_color = PAPER
        (open_x, open_y), open_width = CAM_OPEN
        self.camera.frame.move_to([open_x, open_y, 0.0]).set(width=open_width)

        # ---- the whole map, built once, added nothing ---------------------------
        # Every mobject below exists before the first frame and is positioned for good.
        # None of them are in the scene yet: each arrives on the beat its camera does, and
        # a mobject that has not been added is invisible without anyone having to hold an
        # opacity at zero and remember to raise it later.
        from PIL import Image  # noqa: PLC0415

        source = REPO / WATERFALL_FILE
        if not source.is_file():
            raise SystemExit(
                f"{WATERFALL_FILE} is missing. The opening beat of this clip is a real "
                f"capture rather than a drawing of one, so there is no fallback worth "
                f"rendering."
            )
        capture = Image.open(source).convert("RGB")
        if capture.size != (WATERFALL_COLS, 1540):
            raise SystemExit(
                f"{WATERFALL_FILE} is {capture.size[0]} by {capture.size[1]} and this "
                f"scene crops it as {WATERFALL_COLS} by 1540. Recompute the crop and the "
                f"sentence in the docstring together."
            )
        plate = ImageMobject(
            np.array(capture.crop((0, 0, WATERFALL_COLS, WATERFALL_ROWS)))
        )
        plate.height = WATERFALL_H
        plate.move_to([WATERFALL_AT[0], WATERFALL_AT[1], 0.0])

        archive = VGroup(
            Text("the archive", font_size=19, color=DIM, font=SANS),
            Text("with-signal", font_size=32, color=INK, font=MONO),
            Text("two words", font_size=22, color=DIM, font=SANS),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.15)
        archive.next_to(plate, RIGHT, buff=0.45)

        # In the frame rather than in a receipt, for the reason the docstring gives: the
        # attribution audit resolves an observation id out of the filename, and no video
        # filename carries one, so a credit that lives only in a JSON file is a credit
        # that was never checked against what the video shows.
        credit = VGroup(
            *[
                Text(line, font_size=15, color=DIM, font=SANS)
                for line in WATERFALL_LICENCE
            ]
        ).arrange(DOWN, buff=0.08)
        credit.next_to(plate, DOWN, buff=0.30)

        observation = node("/observation/[id]", "the evidence for one pass", OBS_W)
        observation.move_to([OBS_AT[0], OBS_AT[1], 0.0])
        live = node("/live", "measures a new one on demand", LIVE_W, accent=LIVE)
        live.move_to([LIVE_AT[0], LIVE_AT[1], 0.0])
        queue = node("/", "the queue", QUEUE_W)
        queue.move_to([QUEUE_AT[0], QUEUE_AT[1], 0.0])

        slot = BARS_H / N_BARS
        bars = VGroup()
        for index in range(N_BARS):
            width = BARS_W * (1.0 - 0.62 * index / (N_BARS - 1))
            bar = Rectangle(
                width=width,
                height=slot * 0.62,
                stroke_width=0.0,
                fill_opacity=1.0,
                fill_color=EDGE,
            )
            bar.move_to([BARS_LEFT + width / 2.0, BARS_TOP - (index + 0.5) * slot, 0.0])
            bars.add(bar)

        opened = VGroup(
            Text(f"{BUDGET}", font_size=30, color=ACCENT, font=MONO),
            Text("opened", font_size=19, color=DIM, font=SANS),
        ).arrange(DOWN, buff=0.07)
        opened.move_to([FIGURE_X, BARS_TOP - N_HIGHLIGHT * slot / 2.0, 0.0])
        ranked = VGroup(
            Text(f"{RANKED}", font_size=30, color=DIM, font=MONO),
            Text("ranked", font_size=19, color=DIM, font=SANS),
        ).arrange(DOWN, buff=0.07)
        ranked.move_to([FIGURE_X, BARS_TOP - BARS_H * 0.71, 0.0])

        checks = [
            node(route, caption, width).move_to([x, CHECK_Y, 0.0])
            for (route, caption, width), x in zip(CHECK_SPEC, CHECK_X, strict=True)
        ]

        token = VGroup(
            RoundedRectangle(
                corner_radius=0.14,
                width=RECEIPT_W,
                height=RECEIPT_H,
                stroke_color=ACCENT,
                stroke_width=2.6,
                fill_color=PANEL,
                fill_opacity=1.0,
            ),
            Text("receipt", font_size=62, color=ACCENT, font=MONO),
        )
        token.move_to([RECEIPT_AT[0], RECEIPT_AT[1], 0.0])

        closing = Text(CLOSING_LINE, font_size=60, color=INK, font=SANS)
        closing.move_to([CLOSING_AT[0], CLOSING_AT[1], 0.0])

        # ---- the arrows, in four bands that do not overlap ----------------------
        plate_edge = float(plate.get_right()[0])
        to_observation = flow(
            (plate_edge, TO_OBS_Y), (float(observation.get_left()[0]), TO_OBS_Y)
        )
        to_live = flow((plate_edge, TO_LIVE_Y), (float(live.get_left()[0]), TO_LIVE_Y))

        queue_edge = float(queue.get_left()[0])
        observation_to_queue = flow(
            (float(observation.get_right()[0]), TO_QUEUE_Y), (queue_edge, TO_QUEUE_Y)
        )
        live_leg, live_head = bent(
            (LIVE_LANE_X, float(live.get_top()[1])),
            (LIVE_LANE_X, LIVE_TURN_Y),
            (queue_edge, LIVE_TURN_Y),
        )

        fan = [
            flow(FAN_FROM, (float(page.get_x()), float(page.get_top()[1])))
            for page in checks
        ]
        links = [
            evidence(
                (float(page.get_x()), float(page.get_bottom()[1])),
                (port, float(token.get_top()[1])),
            )
            for page, port in zip(checks, RECEIPT_PORTS, strict=True)
        ]

        # ---- and the promise the docstring makes, kept ---------------------------
        boxes = {
            "plate": _box(plate),
            "archive caption": _box(archive),
            "licence credit": _box(credit),
            "/observation/[id]": _box(observation),
            "/live": _box(live),
            "/": _box(queue),
            "ranked column": _box(bars),
            "opened figure": _box(opened),
            "ranked figure": _box(ranked),
            "receipt": _box(token),
            **{spec[0]: _box(page) for spec, page in zip(CHECK_SPEC, checks, strict=True)},
        }
        edges = {
            "plate to /observation/[id]": (
                _point((plate_edge, TO_OBS_Y)),
                _point((observation.get_left()[0], TO_OBS_Y)),
            ),
            "plate to /live": (
                _point((plate_edge, TO_LIVE_Y)),
                _point((live.get_left()[0], TO_LIVE_Y)),
            ),
            "/observation/[id] to /": (
                _point((observation.get_right()[0], TO_QUEUE_Y)),
                _point((queue_edge, TO_QUEUE_Y)),
            ),
            "/live lane": (
                _point((LIVE_LANE_X, live.get_top()[1])),
                _point((LIVE_LANE_X, LIVE_TURN_Y)),
            ),
            "/live to /": (
                _point((LIVE_LANE_X, LIVE_TURN_Y)),
                _point((queue_edge, LIVE_TURN_Y)),
            ),
            **{
                f"/ to {spec[0]}": (
                    _point(FAN_FROM),
                    _point((page.get_x(), page.get_top()[1])),
                )
                for spec, page in zip(CHECK_SPEC, checks, strict=True)
            },
            **{
                f"{spec[0]} to receipt": (
                    _point((page.get_x(), page.get_bottom()[1])),
                    _point((port, token.get_top()[1])),
                )
                for spec, page, port in zip(
                    CHECK_SPEC, checks, RECEIPT_PORTS, strict=True
                )
            },
        }
        _audit(boxes, edges)

        # ---- 1. one recording, and the two words written about it ---------------
        # The frame opens on the capture alone, filling most of its height, and widens
        # only once there is something to make room for. This clip is the first thing a
        # reader sees on a page of tables, and the beat that earns their attention is the
        # one that shows them it starts somewhere they recognise.
        self.section("pass")
        self.play(FadeIn(plate, scale=0.95), run_time=0.9)
        self.wait(0.5)
        self.play(
            self.frame_on(plate, archive, credit, least=10.5),
            run_time=1.5,
            rate_func=rate_functions.smooth,
        )
        self.play(
            FadeIn(archive, shift=RIGHT * 0.20),
            run_time=0.9,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(FadeIn(credit), run_time=0.6)
        self.hold(2.2)

        # ---- 2. the two pages that measure it ----------------------------------
        # Arrow first, node second. An arrow that grows into empty space and then finds a
        # page there reads as the recording being handed somewhere; a node that appears
        # and is then connected reads as a diagram being assembled.
        self.section("measure")
        self.play(
            self.frame_on(plate, archive, credit, to_observation, observation, to_live, live),
            run_time=1.7,
            rate_func=rate_functions.smooth,
        )
        self.play(GrowArrow(to_observation), run_time=0.7)
        self.play(
            FadeIn(observation, shift=LEFT * 0.25),
            run_time=0.9,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(GrowArrow(to_live), run_time=0.7)
        self.play(
            FadeIn(live, shift=LEFT * 0.25),
            run_time=0.9,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.hold(3.5)

        # ---- 3. the queue that ranks them --------------------------------------
        self.section("queue")
        self.play(
            self.frame_on(
                observation, live, queue, observation_to_queue, live_leg, live_head,
                *bars, ranked, opened,
            ),
            run_time=1.6,
            rate_func=rate_functions.smooth,
        )
        self.play(
            FadeIn(queue, shift=DOWN * 0.20),
            run_time=0.8,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(GrowArrow(observation_to_queue), run_time=0.6)
        self.play(Succession(Create(live_leg), GrowArrow(live_head)), run_time=0.7)
        # One wipe down the column rather than 34 entrances. The lag is short enough that
        # the bars read as a single object filling in, which is what they are: a picture
        # of one ratio, not thirty-four things arriving.
        self.play(
            LaggedStart(*[FadeIn(bar) for bar in bars], lag_ratio=0.035), run_time=1.4
        )
        self.play(FadeIn(ranked), run_time=0.5)
        # The ignition. Four of thirty-four is the real ratio and four bars changing
        # colour on their own is too small a change to see, so the other thirty step back
        # at the same moment. The counts are untouched; only the emphasis moves.
        self.play(
            *[bar.animate.set_fill(ACCENT) for bar in bars[:N_HIGHLIGHT]],
            *[bar.animate.set_fill(opacity=0.40) for bar in bars[N_HIGHLIGHT:]],
            FadeIn(opened, shift=LEFT * 0.15),
            run_time=0.7,
        )
        self.hold(2.7)

        # ---- 4. the four pages a reviewer checks it against --------------------
        # Two at a time, at a width where both the route and its line are readable. All
        # four in one frame would need a width near 26, and at 26 the descriptions are
        # texture. `/precedent` gets the same seconds and the same type as `/evaluation`,
        # which is the point of splitting the beat rather than fanning four nodes at once.
        self.section("check")
        self.play(
            self.frame_on(checks[0], checks[1], fan[0], fan[1]),
            run_time=1.8,
            rate_func=rate_functions.smooth,
        )
        self.play(
            LaggedStart(
                FadeIn(checks[0], shift=UP * 0.22),
                FadeIn(checks[1], shift=UP * 0.22),
                lag_ratio=0.75,
            ),
            run_time=1.6,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(
            LaggedStart(GrowArrow(fan[0]), GrowArrow(fan[1]), lag_ratio=0.75),
            run_time=1.2,
        )
        self.play(
            self.frame_on(checks[2], checks[3], fan[2], fan[3]),
            run_time=1.8,
            rate_func=rate_functions.smooth,
        )
        self.play(
            LaggedStart(
                FadeIn(checks[2], shift=UP * 0.22),
                FadeIn(checks[3], shift=UP * 0.22),
                lag_ratio=0.75,
            ),
            run_time=1.6,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(
            LaggedStart(GrowArrow(fan[2]), GrowArrow(fan[3]), lag_ratio=0.75),
            run_time=1.2,
        )
        # A short lift before the pull back, so the four arrows are seen leaving toward a
        # source off the top of the frame rather than arriving from nowhere. It is also
        # the run up: the closing move starts from a frame that is already rising.
        self.play(
            self.frame_on(*checks, *fan),
            run_time=1.5,
            rate_func=rate_functions.smooth,
        )
        self.hold(1.9)

        # ---- 5. and all of it ends in the same place ---------------------------
        # One continuous move from a frame 15.4 units wide to one 30.4 units wide. The
        # whole map is in shot for the first time here, at 42 seconds, and it is the only
        # beat that has nothing left to explain: the receipt and its four links land, the
        # line lands, and nothing moves again.
        self.section("close")
        self.play(
            self.frame_on(
                plate, archive, credit, to_observation, observation, to_live, live,
                queue, observation_to_queue, live_leg, live_head, *bars, ranked, opened,
                *checks, *fan, token, closing, *links,
            ),
            run_time=2.5,
            rate_func=rate_functions.smooth,
        )
        self.play(
            FadeIn(token, scale=0.94),
            run_time=0.7,
            rate_func=rate_functions.ease_out_cubic,
        )
        self.play(*[GrowArrow(edge) for edge in links], run_time=0.7)
        self.play(FadeIn(closing, shift=DOWN * 0.12), run_time=0.7)
        self.hold(1.7)
