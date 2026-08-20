"""The link preview card, drawn from the receipts rather than typed.

A pasted link to this console rendered as a bare text card: no `og:image`, and a
`twitter:card` of `summary` with nothing to summarise. That is the first thing a judge
sees if the submission is shared in a chat window before it is opened.

Everything on the card is read from `artifacts/QUEUE_RECEIPT.json`, so it cannot claim a
verdict the console does not hold. Both verdicts appear, at one size, in the same order
the landing page weighs them: a preview card carrying only the split that passed would be
the one place in this project that shows a win without the failure beside it.

Set in IBM Plex Sans, decompressed out of the vendored `@fontsource` package. The web
fonts ship as `.woff` and `.woff2`; the `.woff` form needs no brotli, so `fontTools` can
turn it back into a TrueType file `Pillow` will load. Without `apps/web/node_modules` the
script refuses rather than falling back to a substitute face, because a card set in a
different family is a card that contradicts the colophon.

Colours are read out of `apps/web/app/globals.css` at run time rather than copied,
so the card cannot render an older palette than the site does.

    .venv/Scripts/python.exe scripts/build_og_image.py [--check]

Writes `apps/web/public/og.png`. Deterministic: the same receipts give the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
QUEUE_RECEIPT = REPO / "artifacts" / "QUEUE_RECEIPT.json"
CIRCULARITY = REPO / "artifacts" / "CIRCULARITY_RECEIPT.json"
OUT = REPO / "apps" / "web" / "public" / "og.png"
FONT_DIR = (
    REPO / "apps" / "web" / "node_modules" / "@fontsource" / "ibm-plex-sans" / "files"
)
MONO_DIR = (
    REPO / "apps" / "web" / "node_modules" / "@fontsource" / "ibm-plex-mono" / "files"
)

WIDTH, HEIGHT = 1200, 630
MARGIN = 72

CSS = REPO / "apps/web/app/globals.css"


def _tokens() -> dict[str, tuple[int, int, int]]:
    """The palette, read out of the stylesheet the console ships.

    These were ten hardcoded RGB tuples under a comment saying they were "the same
    values globals.css sets". They were, once. The palette then moved from a
    Carbon-blue-accented navy to a warm graphite with an inferno accent ramp, the
    stylesheet moved with it and this file did not, so the card a pasted link renders
    was still the old design and the comment asserting otherwise was false. A second
    copy of a palette is one palette and one lie waiting, which is the same reason the
    architecture diagram reads its colours from here too.
    """
    import re

    text = CSS.read_text(encoding="utf-8")
    start = text.index(":root {")
    end = text.index("\n}", start)
    found = dict(re.findall(r"--([a-z0-9-]+):\s*#([0-9a-fA-F]{6})", text[start:end]))

    wanted = {
        "BACKGROUND": "ui-background",
        "UI_01": "ui-01",
        "TEXT_01": "text-01",
        "TEXT_02": "text-02",
        "TEXT_03": "text-03",
        "BORDER": "border-subtle",
        "PASSED": "verdict-passed",
        "NOT_ESTABLISHED": "verdict-not-established",
        "ACCENT": "interactive-01",
    }
    missing = sorted(t for t in wanted.values() if t not in found)
    if missing:
        raise SystemExit(
            f"globals.css no longer defines {', '.join('--' + m for m in missing)}. "
            f"The preview card reads its palette from the stylesheet so the two cannot "
            f"drift; a renamed token has to be renamed here too."
        )
    return {
        key: tuple(int(found[token][i : i + 2], 16) for i in (0, 2, 4))
        for key, token in wanted.items()
    }


_PALETTE = _tokens()
BACKGROUND = _PALETTE["BACKGROUND"]
UI_01 = _PALETTE["UI_01"]
TEXT_01 = _PALETTE["TEXT_01"]
TEXT_02 = _PALETTE["TEXT_02"]
TEXT_03 = _PALETTE["TEXT_03"]
BORDER = _PALETTE["BORDER"]
PASSED = _PALETTE["PASSED"]
NOT_ESTABLISHED = _PALETTE["NOT_ESTABLISHED"]
ACCENT = _PALETTE["ACCENT"]


def _font(weight: int, size: int, mono: bool = False):
    """One IBM Plex face at one size, or a refusal naming what is missing."""
    from fontTools.ttLib import TTFont
    from PIL import ImageFont

    directory = MONO_DIR if mono else FONT_DIR
    name = "ibm-plex-mono" if mono else "ibm-plex-sans"
    path = directory / f"{name}-latin-{weight}-normal.woff"
    if not path.exists():
        raise SystemExit(
            f"{path} is not on this machine, so the card cannot be set in IBM Plex. "
            "Run `npm install` in apps/web first. This script does not substitute "
            "another family: the colophon states every figure on this site is set in "
            "Plex, and a preview card in a different face would make that false."
        )
    face = TTFont(path, fontNumber=0)
    face.flavor = None
    buffer = io.BytesIO()
    face.save(buffer)
    buffer.seek(0)
    return ImageFont.truetype(buffer, size)


def _verdict_colour(verdict: str) -> tuple[int, int, int]:
    return {
        "PASSED": PASSED,
        "NOT_ESTABLISHED": NOT_ESTABLISHED,
    }.get(verdict, TEXT_03)


def build() -> bytes:
    from PIL import Image, ImageDraw

    receipt = json.loads(QUEUE_RECEIPT.read_text(encoding="utf-8"))
    circularity = json.loads(CIRCULARITY.read_text(encoding="utf-8"))
    per_split = receipt["gate6"]["per_split"]
    for name in ("chronological", "cold_station"):
        if name not in per_split:
            raise SystemExit(
                f"the queue receipt has no {name} split, so the card cannot show the "
                f"pair the landing page shows. It holds {sorted(per_split)}."
            )

    control = circularity["random_ordering_control"]

    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    kicker = _font(600, 22)
    title = _font(600, 84)
    body = _font(400, 27)
    label = _font(600, 19)
    number = _font(600, 62, mono=True)
    small = _font(400, 21)
    smaller = _font(400, 19, mono=True)

    # A rule at the top edge in the accent, so a card cropped to a thumbnail still
    # carries one piece of colour that is this project's rather than the platform's.
    draw.rectangle([0, 0, WIDTH, 6], fill=ACCENT)

    y = MARGIN
    draw.text((MARGIN, y), "SATNOGS WATERFALL TRIAGE", font=kicker, fill=TEXT_03)
    y += 42
    draw.text((MARGIN, y), "TraceTriage", font=title, fill=TEXT_01)
    y += 104
    draw.text(
        (MARGIN, y),
        "A review queue, and the measurement that says how much it is worth.",
        font=body,
        fill=TEXT_02,
    )

    # The two verdicts, side by side and at one size.
    card_top = 336
    card_height = 168
    gap = 28
    card_width = (WIDTH - 2 * MARGIN - gap) // 2
    pair = [
        ("PRE-REGISTERED SPLIT", per_split["chronological"], "decides the gate"),
        ("HELD-OUT STATIONS", per_split["cold_station"], "same queue, unseen sites"),
    ]
    for index, (heading, split, note) in enumerate(pair):
        left = MARGIN + index * (card_width + gap)
        draw.rectangle(
            [left, card_top, left + card_width, card_top + card_height],
            fill=UI_01,
            outline=BORDER,
        )
        colour = _verdict_colour(split["verdict"])
        draw.rectangle([left, card_top, left + 4, card_top + card_height], fill=colour)
        draw.text((left + 28, card_top + 22), heading, font=label, fill=TEXT_03)
        draw.text(
            (left + 28, card_top + 50),
            f"{split['lift_point']:.2f}x",
            font=number,
            fill=TEXT_01,
        )
        draw.text(
            (left + 28, card_top + 124),
            f"{split['verdict'].replace('_', ' ')}  ·  {note}",
            font=small,
            fill=colour,
        )

    footer = (
        f"tracetriage.vercel.app   ·   IBM Granite, run locally   ·   "
        f"{control['n_permutations_at_or_above_observed']} of "
        f"{control['n_permutations']} random orderings matched it"
    )
    draw.text((MARGIN, HEIGHT - MARGIN - 6), footer, font=smaller, fill=TEXT_03)

    buffer = io.BytesIO()
    # optimize keeps the file small and, with no timestamp chunk, byte-identical
    # across runs, which is what lets --check compare digests rather than pixels.
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="recompute and compare against the committed card without writing",
    )
    args = ap.parse_args(argv)

    fresh = build()
    if args.check:
        if not OUT.exists():
            print(f"{OUT.relative_to(REPO)} is absent. Run this script without --check.")
            return 1
        committed = OUT.read_bytes()
        if committed == fresh:
            print("og.png matches the receipts")
            return 0
        print(
            f"og.png is stale. Run scripts/build_og_image.py. "
            f"committed {hashlib.sha256(committed).hexdigest()[:16]}, "
            f"fresh {hashlib.sha256(fresh).hexdigest()[:16]}"
        )
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(fresh)
    print(f"{OUT.relative_to(REPO)} written, {len(fresh)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
