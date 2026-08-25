"""Animate the architecture diagram, from the same stage table the SVG is drawn from.

The static SVG says what the pipeline is. It does not say which way the data goes, and
a reader meeting ten boxes at once has to work the order out from the arrows. This walks
the same ten stages in the order they run, so the shape arrives one step at a time and
the reader is told the direction rather than asked to infer it.

It is a GIF and not an animated SVG because GitHub sanitises SVG in a README: SMIL and
CSS animation are both stripped, so an animated SVG renders as a still and the animation
silently does not exist for the audience it was made for. A GIF plays.

Nothing here has its own idea of what the pipeline contains. STAGES, the geometry and the
palette are imported from `scripts/build_architecture_diagram.py`, which already checks
every stage's module and receipt against the tree before it will emit anything. So a
stage renamed in the code breaks both pictures together, and neither can describe a
pipeline this repository does not have.

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

#: Frames each stage holds before the next lights. At 12 fps a stage reads in about half
#: a second, which is long enough to land and short enough that ten of them fit in a loop
#: a reader will sit through on a README.
HOLD = 5
FPS = 12
#: Frames of everything-lit at the end, so the last frame is the whole pipeline rather
#: than the last box. A reader who arrives mid-loop should still see the shape.
SETTLE = 16


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


def _font(size: int, bold: bool = False):
    from PIL import ImageFont  # noqa: PLC0415

    # IBM Plex is what the console and the film are set in. Falling back to the default
    # bitmap font would draw a different project, so the fallback is only reached on a
    # machine that has neither, and the diagram says so by being obviously plainer.
    for name in (
        "IBMPlexSans-SemiBold.ttf" if bold else "IBMPlexSans-Regular.ttf",
        "seguisb.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ):
        for root in (REPO / "media" / "fonts", Path("C:/Windows/Fonts"), Path("/usr/share/fonts")):
            hit = next(root.rglob(name), None) if root.exists() else None
            if hit is not None:
                try:
                    return ImageFont.truetype(str(hit), size)
                except OSError:
                    pass
    return ImageFont.load_default()


def _mix(a: str, b: str, t: float) -> tuple[int, int, int]:
    """Blend two #rrggbb tokens. Used for the lit state, so no new colour is invented."""
    ai = tuple(int(a.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    bi = tuple(int(b.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))
    return tuple(round(x + (y - x) * t) for x, y in zip(ai, bi, strict=True))


def frames() -> list:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    d = _diagram()
    t = d.tokens()
    stages = d.STAGES
    width = 904
    height = d.TOP + len({s.row for s in stages}) * (d.ROW_H + d.ROW_GAP) + 40

    title_font, body_font, mono_font = _font(15, True), _font(11), _font(10)
    order = sorted(range(len(stages)), key=lambda i: (stages[i].row, stages[i].column))

    out = []
    total = len(order) * HOLD + SETTLE
    for frame_index in range(total):
        # How far the walk has travelled, in stages. Past the end it sits at the end,
        # which is what SETTLE is for.
        reached = min(frame_index // HOLD, len(order))
        img = Image.new("RGB", (width, height), t["ui-background"])
        draw = ImageDraw.Draw(img)

        # The same hairline scale the SVG carries down the left edge.
        draw.line([(20, d.TOP - 20), (20, height - 30)], fill=t["ui-02"], width=1)

        for position, stage_index in enumerate(order):
            stage = stages[stage_index]
            x, y, w, h = d.box_rect(stage)

            if position < reached:
                # Already passed. Held lit but quiet, so the path behind the pulse is
                # readable as a path rather than competing with the current stage.
                edge = _mix(t["ui-02"], t["interactive-01"], 0.45)
                fill = _mix(t["ui-background"], t["ui-01"], 1.0)
                ink = t["text-01"]
            elif position == reached:
                # Currently lit. Ramped across its own hold rather than switched, because
                # a hard switch at 12 fps reads as a flicker.
                k = (frame_index % HOLD) / max(HOLD - 1, 1)
                edge = _mix(t["interactive-01"], t["text-04"], 0.25 * (1 - k))
                fill = _mix(t["ui-01"], t["surface-raised"], 1.0)
                ink = t["text-04"]
            else:
                # Not yet reached. Present but recessed: the reader can see the shape
                # they are being walked through.
                edge = t["ui-02"]
                fill = t["ui-background"]
                ink = t["text-03"]

            draw.rectangle([x, y, x + w, y + h], fill=fill, outline=edge, width=2)

            draw.text((x + 16, y + 11), stage.title, font=title_font, fill=ink)
            body = d.wrap(stage.detail, 74 if w > 600 else 36)
            if len(body) > 3:
                # An ellipsis, not a silent cut. A detail clipped mid-sentence reads as
                # a sentence the stage table wrote, and it did not.
                body = body[:3]
                body[2] = body[2].rstrip(",.") + "…"
            for line_no, line in enumerate(body):
                draw.text(
                    (x + 16, y + 32 + line_no * 13),
                    line,
                    font=body_font,
                    fill=t["text-02"] if position <= reached else t["ui-02"],
                )
            draw.text(
                (x + 16, y + h - 17),
                stage.receipt,
                font=mono_font,
                fill=t["interactive-01"] if position <= reached else t["ui-02"],
            )

        out.append(img.quantize(colors=32, method=Image.Quantize.MEDIANCUT))
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
    print(f"wrote {OUT.relative_to(REPO)}, {len(fresh) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
