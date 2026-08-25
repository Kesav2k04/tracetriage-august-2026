"""Animate the architecture, from the same stage table the static SVG is drawn from.

The SVG says what the pipeline is. It does not say which way the data goes, and a reader
meeting thirteen boxes at once has to work the order out from the arrows. This walks the
same thirteen stages in the order they run, so the shape arrives one step at a time and
the reader is told the direction rather than asked to infer it.

Two things it does that the SVG cannot. Every edge in the stage table is routed and drawn
with an arrowhead, and a packet runs along that edge as the stage it leaves finishes, so
the connection is something the reader watches happen rather than something they trace. And
the words live in a panel beside the map instead of inside the boxes: a README renders this
about nine hundred pixels wide, so thirteen boxes of body text is thirteen boxes of nothing
anyone can read, while one stage's description at panel size stays legible after the same
downscale.

It is 3840 by 2160, which is the size a reader gets when they click the image, and it is a
GIF and not an animated SVG because GitHub sanitises SVG in a README: SMIL and CSS
animation are both stripped, so an animated SVG renders as a still and the animation
silently does not exist for the audience it was made for. A GIF plays.

The stage table, the edges and the palette are imported from
`scripts/build_architecture_diagram.py`, which already checks every stage's module and
receipt against the tree before it will emit anything. So a stage renamed in the code
breaks both pictures together, and neither can describe a pipeline this repository does not
have. The pixel layout below is this file's own, because a column that suits a still page
does not suit a sixteen by nine animation, but it places only what that table contains.

    .venv/Scripts/python.exe scripts/build_architecture_gif.py
    .venv/Scripts/python.exe scripts/build_architecture_gif.py --check

`--check` regenerates into memory and compares the bytes, which is what the standing gate
runs. Pillow's GIF encoder is deterministic for a fixed palette and frame list, so the
comparison is meaningful rather than a re-render that always differs.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "architecture.gif"

#: True 4K. The image a README shows is downscaled to the content column, so this is the
#: size of the thing behind the click rather than the size anyone reads at first.
CANVAS_W, CANVAS_H = 3840, 2160

MARGIN = 132
RULE_Y = 344
BODY_TOP = 452
BODY_BOTTOM = 1904
MAP_LEFT, MAP_RIGHT = MARGIN, 1772
FOCUS_LEFT, FOCUS_RIGHT = 1916, CANVAS_W - MARGIN
RAIL_Y = 1984
COL_GUTTER = 48
CARD_H = 88

#: Frames each stage holds before the next lights. At 14 fps a stage reads in under half a
#: second, which is long enough to land and short enough that thirteen of them fit in a
#: loop a reader will sit through on a README.
HOLD = 6
FPS = 14
#: Frames of everything-lit at the end, with every edge carrying a packet at once. A reader
#: who arrives mid-loop should still get one look at the whole shape moving.
SETTLE = 12
#: Length of the moving dash, in pixels of the 4K canvas.
PACKET_LEN = 150


def _diagram():
    """The SVG generator, imported for its stage table rather than duplicated.

    Loaded by path because `scripts/` is not a package. Importing it also runs its
    module-level path verification, so this script cannot draw a stage whose module or
    receipt has gone missing.
    """
    spec = importlib.util.spec_from_file_location(
        "build_architecture_diagram", REPO / "scripts" / "build_architecture_diagram.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _font(size: int, bold: bool = False, mono: bool = False):
    from PIL import ImageFont  # noqa: PLC0415

    # IBM Plex is what the console is set in. Falling back to the default
    # bitmap font would draw a different project, so the fallback is only reached on a
    # machine that has neither, and the diagram says so by being obviously plainer.
    if mono:
        names = ("IBMPlexMono-Regular.ttf", "consola.ttf", "DejaVuSansMono.ttf")
    elif bold:
        names = ("IBMPlexSans-SemiBold.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf")
    else:
        names = ("IBMPlexSans-Regular.ttf", "segoeui.ttf", "DejaVuSans.ttf")
    for name in names:
        for root in (REPO / "media" / "fonts", Path("C:/Windows/Fonts"), Path("/usr/share/fonts")):
            hit = next(root.rglob(name), None) if root.exists() else None
            if hit is not None:
                try:
                    return ImageFont.truetype(str(hit), size)
                except OSError:
                    pass
    return ImageFont.load_default()


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    """Blend two #rrggbb tokens. Used for the lit states, so no new colour is invented."""
    ai = tuple(int(a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    bi = tuple(int(b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return tuple(round(x + (y - x) * t) for x, y in zip(ai, bi, strict=True))


def _layout(stages) -> tuple[dict[str, tuple[int, int, int, int]], list[int]]:
    """Place every stage, and give the order the walk visits them in.

    Column 0 is the spine and spans the map. Columns 1 and 2 are the parallel evidence
    channels and split it in half, which is the same relationship the stage table's own
    column numbers describe.
    """
    rows = sorted({stage.row for stage in stages})
    pitch = (BODY_BOTTOM - BODY_TOP) // len(rows)
    span = MAP_RIGHT - MAP_LEFT
    half = (span - COL_GUTTER) // 2
    geometry = {}
    for stage in stages:
        y = BODY_TOP + rows.index(stage.row) * pitch
        if stage.column == 0:
            x, w = MAP_LEFT, span
        elif stage.column == 1:
            x, w = MAP_LEFT, half
        else:
            x, w = MAP_LEFT + half + COL_GUTTER, half
        geometry[stage.key] = (x, y, w, CARD_H)
    order = sorted(range(len(stages)), key=lambda i: (stages[i].row, stages[i].column))
    return geometry, order


def _route(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """The path from one card's bottom edge to the next card's top edge.

    Straight down when the two centres line up, and an orthogonal dog-leg through the gap
    between the rows when they do not, so a connector between columns never crosses a card
    it has nothing to do with.
    """
    ax, ay, aw, ah = a
    bx, by, bw, _ = b
    start = (ax + aw // 2, ay + ah)
    end = (bx + bw // 2, by)
    if start[0] == end[0]:
        return [start, end]
    mid = (start[1] + end[1]) // 2
    return [start, (start[0], mid), (end[0], mid), end]


def _measure(path: list[tuple[int, int]]) -> tuple[list[float], float]:
    """Cumulative length at each vertex, and the whole path's length."""
    running = [0.0]
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        running.append(running[-1] + abs(x1 - x0) + abs(y1 - y0))
    return running, running[-1]


def _slice(path: list[tuple[int, int]], start: float, stop: float) -> list[tuple[int, int]]:
    """The part of an orthogonal path between two distances along it.

    Used for the packet, which is a short piece of the connector rather than a dot, so it
    turns the corner of a dog-leg instead of jumping across it.
    """
    running, total = _measure(path)
    start, stop = max(0.0, start), min(total, stop)
    if stop <= start:
        return []

    def at(distance: float) -> tuple[int, int]:
        for index in range(len(path) - 1):
            if running[index] <= distance <= running[index + 1]:
                segment = running[index + 1] - running[index]
                k = 0.0 if segment == 0 else (distance - running[index]) / segment
                (x0, y0), (x1, y1) = path[index], path[index + 1]
                return round(x0 + (x1 - x0) * k), round(y0 + (y1 - y0) * k)
        return path[-1]

    points = [at(start)]
    for index, distance in enumerate(running):
        if start < distance < stop:
            points.append(path[index])
    points.append(at(stop))
    return points


def _wrap(draw, text: str, font, limit: int) -> list[str]:
    """Wrap to a pixel width rather than a character count, because the panel is set in a
    proportional face and a character count would leave a third of it empty or overflow it.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and draw.textlength(trial, font=font) > limit:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def frames() -> list:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    d = _diagram()
    t = d.tokens()
    stages = d.STAGES
    by_key = {stage.key: stage for stage in stages}
    geometry, order = _layout(stages)
    paths = {edge: _route(geometry[edge[0]], geometry[edge[1]]) for edge in d.EDGES}
    leaving: dict[str, list[tuple[str, str]]] = {}
    for edge in d.EDGES:
        leaving.setdefault(edge[0], []).append(edge)

    brand = _font(84, bold=True)
    lede = _font(44)
    tally = _font(38, mono=True)
    card_title = _font(42, bold=True)
    card_index = _font(30, mono=True)
    card_receipt = _font(28, mono=True)
    eyebrow = _font(32, mono=True)
    focus_title = _font(104, bold=True)
    focus_body = _font(50)
    label = _font(28, mono=True)
    focus_mono = _font(36, mono=True)
    chip_text = _font(34)
    footnote = _font(32)

    dim_edge = _mix(t["ui-background"], t["border-subtle"], 1.0)
    live_edge = _mix(t["border-subtle"], t["interactive-01"], 0.6)
    packet = t["live-01"]

    out = []
    total = len(order) * HOLD + SETTLE
    for frame_index in range(total):
        position = min(frame_index // HOLD, len(order))
        settling = position >= len(order)
        reached = len(order) if settling else position
        # Where the packets are along their edge, as a fraction. During a stage's hold the
        # packets leave that stage; during the settle every edge carries one at once.
        step_frame = frame_index if not settling else frame_index - len(order) * HOLD
        travel = (step_frame % HOLD) / HOLD
        arrived = {stages[i].key for i in order[:reached]}
        active = None if settling else stages[order[position]]

        img = Image.new("RGB", (CANVAS_W, CANVAS_H), t["ui-background"])
        draw = ImageDraw.Draw(img)

        # ---- header ----
        draw.text((MARGIN, 132), "TraceTriage", font=brand, fill=t["text-04"])
        draw.text(
            (MARGIN, 240), "the pipeline, in the order it runs", font=lede, fill=t["text-02"]
        )
        tally_text = f"{len(stages)} stages, {len({s.receipt for s in stages})} receipts"
        draw.text(
            (FOCUS_RIGHT - draw.textlength(tally_text, font=tally), 172),
            tally_text,
            font=tally,
            fill=t["text-03"],
        )
        draw.line([(MARGIN, RULE_Y), (CANVAS_W - MARGIN, RULE_Y)], fill=t["border-subtle"], width=2)

        # ---- connectors, drawn first so an arrival lands behind the card it feeds ----
        for edge, path in paths.items():
            live = edge[0] in arrived
            colour = live_edge if live else dim_edge
            draw.line(path, fill=colour, width=5 if live else 3, joint="curve")
            tip = path[-1]
            draw.polygon(
                [(tip[0] - 15, tip[1] - 22), (tip[0] + 15, tip[1] - 22), (tip[0], tip[1])],
                fill=colour,
            )

        # ---- packets ----
        running_edges = list(paths) if settling else leaving.get(active.key if active else "", [])
        for edge in running_edges:
            path = paths[edge]
            _, length = _measure(path)
            head = travel * (length + PACKET_LEN)
            piece = _slice(path, head - PACKET_LEN, head)
            if len(piece) > 1:
                draw.line(piece, fill=packet, width=7, joint="curve")

        # ---- cards ----
        for step, stage_index in enumerate(order):
            stage = stages[stage_index]
            x, y, w, h = geometry[stage.key]
            if settling or step < reached:
                fill, border = t["ui-01"], t["edge-highlight"]
                accent, ink = _mix(t["border-subtle"], t["interactive-01"], 0.75), t["text-01"]
                index_ink, receipt_ink = t["text-03"], t["interactive-01"]
            elif step == reached:
                fill, border = t["hover-ui"], t["interactive-01"]
                accent, ink = t["interactive-01"], t["text-04"]
                index_ink, receipt_ink = t["text-04"], t["interactive-04"]
            else:
                fill, border = t["ui-background"], t["border-subtle"]
                accent, ink = t["border-subtle"], t["text-03"]
                index_ink, receipt_ink = t["ui-04"], t["ui-04"]

            draw.rectangle([x, y, x + w, y + h], fill=fill, outline=border, width=3)
            # The accent rail is what carries the state at a glance once the picture is
            # scaled down to a README column and the type has stopped being readable.
            draw.rectangle([x, y, x + 10, y + h], fill=accent)

            draw.text((x + 38, y + h // 2 - 18), f"{step + 1:02d}", font=card_index, fill=index_ink)
            draw.text((x + 128, y + h // 2 - 27), stage.title, font=card_title, fill=ink)
            leaf = stage.receipt.rsplit("/", 1)[-1]
            draw.text(
                (x + w - 34 - draw.textlength(leaf, font=card_receipt), y + h // 2 - 17),
                leaf,
                font=card_receipt,
                fill=receipt_ink,
            )

        # ---- focus panel ----
        panel_w = FOCUS_RIGHT - FOCUS_LEFT
        draw.rectangle(
            [FOCUS_LEFT, BODY_TOP, FOCUS_RIGHT, BODY_BOTTOM],
            fill=t["surface-raised"],
            outline=t["border-subtle"],
            width=3,
        )
        draw.rectangle(
            [FOCUS_LEFT, BODY_TOP, FOCUS_LEFT + 10, BODY_BOTTOM], fill=t["interactive-01"]
        )
        pad = FOCUS_LEFT + 74
        inner = panel_w - 148

        if active is None:
            head = f"ALL {len(stages)} STAGES"
            title = "The whole pipeline"
            detail = (
                "One direction, no cycles. Each stage reads what the stage above it "
                "wrote and writes its own receipt, so any number on the console can be "
                "walked back to the frozen snapshot it came from."
            )
            writes = f"{len({s.receipt for s in stages})} receipts, one per stage"
            module = f"{len(d.EDGES)} connections, every one of them forward"
            left_label, left_chips = "STARTS AT", [stages[order[0]].title]
            right_label, right_chips = "ENDS AT", [stages[order[-1]].title]
        else:
            head = f"STAGE {position + 1:02d} OF {len(stages)}"
            title = active.title
            detail = active.detail
            writes, module = active.receipt, active.module
            # The stage's own edges, read out of the same table the map is drawn from, so
            # the panel names the connections rather than leaving the reader to trace them
            # across a picture that a README has scaled down to a quarter of this size.
            left_label = "READS FROM"
            left_chips = [by_key[a].title for a, b in d.EDGES if b == active.key]
            right_label = "FEEDS"
            right_chips = [by_key[b].title for a, b in d.EDGES if a == active.key]

        draw.text((pad, BODY_TOP + 66), head, font=eyebrow, fill=t["interactive-01"])
        for line_no, line in enumerate(_wrap(draw, title, focus_title, inner)):
            draw.text(
                (pad, BODY_TOP + 126 + line_no * 118),
                line,
                font=focus_title,
                fill=t["text-04"],
            )
        # Fixed, rather than flowed under the title. A two-line title would otherwise push
        # everything below it down and make the panel appear to jump between stages.
        body_top = BODY_TOP + 368
        draw.line(
            [(pad, body_top), (FOCUS_RIGHT - 74, body_top)], fill=t["border-subtle"], width=2
        )
        for line_no, line in enumerate(_wrap(draw, detail, focus_body, inner)):
            draw.text((pad, body_top + 54 + line_no * 74), line, font=focus_body, fill=t["text-02"])

        # ---- what this stage is connected to ----
        chips_top = BODY_TOP + 736
        for column, (chip_label, chips, tone) in enumerate(
            (
                (left_label, left_chips, t["text-02"]),
                (right_label, right_chips, t["interactive-01"]),
            )
        ):
            cx = pad + column * (inner // 2)
            draw.text((cx, chips_top), chip_label, font=label, fill=t["text-03"])
            if not chips:
                draw.text(
                    (cx, chips_top + 50),
                    "nothing upstream" if column == 0 else "nothing downstream",
                    font=chip_text,
                    fill=t["text-03"],
                )
            for chip_no, chip in enumerate(chips):
                cy = chips_top + 46 + chip_no * 78
                cw = draw.textlength(chip, font=chip_text) + 48
                draw.rectangle([cx, cy, cx + cw, cy + 62], outline=tone, width=2)
                draw.text((cx + 24, cy + 15), chip, font=chip_text, fill=tone)

        foot = BODY_TOP + 960
        draw.line([(pad, foot), (FOCUS_RIGHT - 74, foot)], fill=t["border-subtle"], width=2)
        draw.text((pad, foot + 42), "WRITES", font=label, fill=t["text-03"])
        draw.text((pad, foot + 86), writes, font=focus_mono, fill=t["interactive-01"])
        draw.text((pad, foot + 158), "IMPLEMENTED IN", font=label, fill=t["text-03"])
        draw.text((pad, foot + 202), module, font=focus_mono, fill=t["text-02"])

        # ---- how to read the drawing ----
        # A reader meets this cold and has about ten seconds to work out what the colours
        # mean before the loop restarts. Saying so costs four lines and removes the guess.
        legend_top = BODY_TOP + 1282
        draw.line(
            [(pad, legend_top - 40), (FOCUS_RIGHT - 74, legend_top - 40)],
            fill=t["border-subtle"],
            width=2,
        )
        # Each swatch is the mark it stands for, at card scale: a filled rail for a stage
        # that has run, an outlined box for the one running, a length of connector for the
        # packet. Two amber squares side by side would be two things a reader cannot tell
        # apart, which is the opposite of what a key is for.
        keys = (
            ("rail", _mix(t["border-subtle"], t["interactive-01"], 0.75), "already run"),
            ("box", t["interactive-01"], "running now"),
            ("line", t["live-01"], "data on the move"),
            ("rail", t["border-subtle"], "not reached yet"),
        )
        for key_no, (shape, swatch, text) in enumerate(keys):
            kx = pad + (key_no % 2) * (inner // 2)
            ky = legend_top + (key_no // 2) * 64
            if shape == "rail":
                draw.rectangle([kx, ky + 4, kx + 12, ky + 38], fill=swatch)
            elif shape == "box":
                draw.rectangle(
                    [kx, ky + 4, kx + 40, ky + 38],
                    fill=t["hover-ui"],
                    outline=swatch,
                    width=3,
                )
            else:
                draw.line([(kx, ky + 21), (kx + 44, ky + 21)], fill=swatch, width=7)
            draw.text((kx + 62, ky), text, font=label, fill=t["text-03"])

        # ---- progress rail ----
        rail_w = CANVAS_W - 2 * MARGIN
        gap = 10
        seg = (rail_w - gap * (len(order) - 1)) // len(order)
        for step in range(len(order)):
            x = MARGIN + step * (seg + gap)
            done = settling or step <= reached
            draw.rectangle(
                [x, RAIL_Y, x + seg, RAIL_Y + 14],
                fill=t["interactive-01"] if done else t["border-subtle"],
            )
        draw.text(
            (MARGIN, RAIL_Y + 44),
            "Every stage names the receipt it writes. Nothing downstream reads anything else.",
            font=footnote,
            fill=t["text-03"],
        )

        out.append(img.quantize(colors=64, method=Image.Quantize.MEDIANCUT))
    return out


def build() -> bytes:
    buffer = io.BytesIO()
    images = frames()
    images[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=round(1000 / FPS),
        loop=0,
        optimize=True,
        disposal=1,
    )
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    fresh = build()
    if args.check:
        if not OUT.exists():
            print(f"{OUT.relative_to(REPO)} does not exist", file=sys.stderr)
            return 1
        if OUT.read_bytes() != fresh:
            print(
                f"{OUT.relative_to(REPO)} is not what the stage table produces. "
                "Run scripts/build_architecture_gif.py.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUT.relative_to(REPO)} matches the pipeline.")
        return 0

    OUT.write_bytes(fresh)
    print(f"wrote {OUT.relative_to(REPO)}, {len(fresh) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
