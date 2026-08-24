"""Rasterise the site mark into the icon sizes a home-screen install needs.

Five files: four for the console's install prompt across Android and iOS, and one for the
Android client in `mobile/`, all from the same mark so the two surfaces cannot diverge.

    .venv/Scripts/python.exe scripts/build_pwa_icons.py
    .venv/Scripts/python.exe scripts/build_pwa_icons.py --check

Why this exists rather than a hand-exported PNG: the mark in `apps/web/app/icon.svg` is the
measurement, not a monogram, and its colours are the palette's own tokens. A PNG exported once
by hand goes stale the day the palette moves, and nothing would say so. This reads the five
colours back out of the SVG and fails if any of them is missing, so the icons cannot disagree
with the mark they are supposed to be.

No new dependency. Pillow is already here for the pipeline's imagery, and the two curves are
cubic Beziers sampled directly rather than handed to an SVG renderer, which would have meant
adding cairo or a headless browser to the build for five files.

`--check` re-renders into memory and compares bytes, so it is a gate row rather than a habit.
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
MARK = REPO / "apps" / "web" / "app" / "icon.svg"
OUT = REPO / "apps" / "web" / "public" / "icons"

#: The Android client's launcher icon, from the same mark and the same script. Expo reads
#: `mobile/assets/icon.png` at build time and generates the density buckets from it, so this
#: is the one file that decides what the app looks like on a home screen. A second
#: hand-exported PNG would have been the same staleness problem in a second directory.
MOBILE = REPO / "mobile" / "assets"

#: Supersampling factor. The mark is a 32-unit plate with a 3.1-unit stroke, so at 192 px the
#: curve is 18 px wide and its edge is what a phone actually shows. Drawing at 8x and reducing
#: with LANCZOS is cheaper than writing an antialiased stroke by hand and looks the same.
SCALE = 8

#: What gets written, and why each size is here.
#:   180  `apple-touch-icon`, the size iOS reads for Add to Home Screen. iOS applies its
#:        own rounding and refuses transparency, which is why the plain variant fills the
#:        square rather than drawing a rounded plate of its own.
#:   192  the Android launcher size every install prompt asks for
#:   512  the splash and store-listing size
#:   512m a maskable variant: Android crops icons to a device-chosen shape, so the mark is
#:        inset to the 80% safe zone and the ground colour is allowed to bleed to the edge
#:   1024 the Android client's source icon, which Expo downsamples into every density
#:        bucket. It goes to mobile/assets rather than to the console's public directory.
SIZES: tuple[tuple[Path, str, int, bool], ...] = (
    (OUT, "apple-touch-icon.png", 180, False),
    (OUT, "icon-192.png", 192, False),
    (OUT, "icon-512.png", 512, False),
    (OUT, "icon-512-maskable.png", 512, True),
    (MOBILE, "icon.png", 1024, False),
)


def _palette() -> dict[str, str]:
    """The five colours, read out of the mark rather than retyped here.

    Keyed by what each one is, not by where it appears, because the SVG's own comment names
    them that way and a reader of either file should find the same vocabulary.
    """
    svg = MARK.read_text(encoding="utf-8")
    # Only the paint attributes, never the prose. The SVG's comment block names hexes it used
    # to carry, and matching those would resurrect exactly the stale values it warns about.
    paints = re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]{6})"', svg)
    if len(paints) < 5:
        raise SystemExit(
            f"{MARK.name} has {len(paints)} paint attributes, expected at least 5. The mark "
            f"changed shape, so this script needs reading before it is trusted."
        )
    ground, plate, edge, corridor, commanded, trace = (
        paints[0],
        paints[1],
        paints[2],
        paints[3],
        paints[4],
        paints[5],
    )
    return {
        "ground": ground,
        "plate": plate,
        "edge": edge,
        "corridor": corridor,
        "commanded": commanded,
        "trace": trace,
    }


def _cubic(p0, p1, p2, p3, steps: int = 96):
    """Sample one cubic Bezier. The two curves in the mark are single segments each."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        out.append((x, y))
    return out


def _render(size: int, maskable: bool) -> Image.Image:
    """One icon, drawn in the mark's own 32-unit coordinate space and then scaled.

    Every coordinate below is the same number as in `icon.svg`, which is the only way the two
    files can be read against each other.
    """
    c = _palette()
    big = size * SCALE
    # A maskable icon is cropped to a device-chosen shape, so the mark sits inside the 80%
    # safe zone and the ground fills the whole square instead of a rounded plate.
    inset = 0.10 if maskable else 0.0
    unit = big * (1 - 2 * inset) / 32.0
    origin = big * inset

    def at(x: float, y: float) -> tuple[float, float]:
        return (origin + x * unit, origin + y * unit)

    img = Image.new("RGB", (big, big), c["ground"])
    d = ImageDraw.Draw(img)

    if maskable:
        d.rectangle([0, 0, big, big], fill=c["ground"])
    else:
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=6 * unit, fill=c["ground"])

    d.rounded_rectangle(
        [*at(2.5, 2.5), *at(29.5, 29.5)],
        radius=4 * unit,
        fill=c["plate"],
        outline=c["edge"],
        width=max(1, round(0.6 * unit)),
    )

    # The corridor: the tolerance the fit is allowed, under everything else.
    # The SVG path is: M19.8 6  C 19 12.6, 9.8 19.4, 9 26  L 14.2 26
    #                  C 15 19.4, 24.2 12.6, 25 6  Z
    # Two cubics joined by a straight base, closed back to the start. The second cubic begins
    # where the line ended, at (14.2, 26); starting it anywhere else draws a different shape.
    corridor = (
        _cubic((19.8, 6), (19, 12.6), (9.8, 19.4), (9, 26))
        + _cubic((14.2, 26), (15, 19.4), (24.2, 12.6), (25, 6))
    )
    d.polygon([at(x, y) for x, y in corridor], fill=c["corridor"])

    # The commanded receive frequency, dashed the way the SVG dashes it: 2.6 on, 2.4 off.
    y = 5.0
    while y < 27.0:
        d.line(
            [*at(16, y), *at(16, min(y + 2.6, 27.0))],
            fill=c["commanded"],
            width=max(1, round(1.2 * unit)),
        )
        y += 5.0

    # The Doppler curve. The gap between it and the dashed line is the whole project.
    # Stamped as a round brush rather than drawn with `d.line(..., joint="curve")`. That
    # version left visible darker seams across the gold where consecutive segments met, which
    # at 512 px reads as hatching on the one element the icon exists to show. A circle at every
    # sample gives clean round caps for free and cannot seam, because there are no joins.
    trace = _cubic((22.4, 6), (21.6, 12.6), (12.4, 19.4), (11.6, 26), steps=480)
    r = 3.1 * unit / 2
    for x, y in trace:
        cx, cy = at(x, y)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c["trace"])

    return img.resize((size, size), Image.LANCZOS)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    # No timestamp chunk, so two runs of this script produce the same bytes and `--check`
    # is comparing the drawing rather than the clock.
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build the home-screen icons from the site mark.")
    ap.add_argument(
        "--check", action="store_true", help="verify the committed icons match the mark"
    )
    args = ap.parse_args(argv)

    stale: list[str] = []
    for directory, name, size, maskable in SIZES:
        directory.mkdir(parents=True, exist_ok=True)
        want = _png_bytes(_render(size, maskable))
        path = directory / name
        if args.check:
            rel = path.relative_to(REPO).as_posix()
            if not path.exists():
                stale.append(f"{rel} is missing")
            elif path.read_bytes() != want:
                stale.append(f"{rel} does not match the mark")
        else:
            path.write_bytes(want)
            print(f"  {path.relative_to(REPO).as_posix()}  {len(want):,} bytes")

    if args.check:
        if stale:
            print("icons disagree with apps/web/app/icon.svg:")
            for line in stale:
                print(f"  {line}")
            print("Run scripts/build_pwa_icons.py to rebuild them.")
            return 1
        print(f"{len(SIZES)} icons match the mark")
    return 0


if __name__ == "__main__":
    sys.exit(main())
