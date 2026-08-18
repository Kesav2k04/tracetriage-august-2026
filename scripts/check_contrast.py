"""Recompute every foreground/background contrast pair from the design tokens.

The console's neutrals were re-expressed in OKLCH at Carbon's own lightness values so
the page could carry a deep indigo cast without moving a single contrast ratio. That
is a claim, and a claim needs something that can fail it. This reads the tokens out of
`apps/web/app/globals.css`, computes the WCAG 2.1 ratio for each pair the interface
actually renders, and compares it against the floor that pair needs.

Floors, from WCAG 2.1:

* 4.5:1 for text below 24px, or below 19px at 600 weight or heavier.
* 3.0:1 for large text and for the boundary of a user interface component.

Two pairs sit deliberately below 4.5 and are declared, not discovered:
`--text-03` on `--ui-02` is 3.48:1 and is only used for rules and axis furniture, and
`--ui-04` on the page ground is 3.59:1 and is a component boundary. Both are recorded
with the reason rather than rounded up or quietly excluded, because an exemption with
no measurement attached is how a scoped-out check stops covering anything.

    .venv/Scripts/python.exe scripts/check_contrast.py [--verbose]

Exits 1 if any pair is under its floor. `tests/test_contrast.py` runs the same
comparison inside the offline suite.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CSS = REPO / "apps/web/app/globals.css"

# (foreground token, background token, floor, why this floor)
PAIRS: list[tuple[str, str, float, str]] = [
    ("text-01", "ui-background", 4.5, "body text on the page ground"),
    ("text-02", "ui-background", 4.5, "secondary prose on the page ground"),
    ("text-03", "ui-background", 4.5, "captions, table labels and axis ticks"),
    ("text-01", "ui-01", 4.5, "body text on a tile"),
    ("text-02", "ui-01", 4.5, "secondary prose on a tile"),
    ("text-03", "ui-01", 4.5, "captions on a tile"),
    ("text-04", "ui-background", 4.5, "emphasised text on the page ground"),
    ("link-01", "ui-background", 4.5, "links in prose"),
    ("link-01", "ui-01", 4.5, "links inside a tile"),
    ("verdict-passed", "ui-background", 4.5, "verdict word, page ground"),
    ("verdict-passed", "ui-01", 4.5, "verdict word, tile"),
    ("verdict-failed", "ui-background", 4.5, "verdict word, page ground"),
    ("verdict-failed", "ui-01", 4.5, "verdict word, tile"),
    ("verdict-not-established", "ui-background", 4.5, "verdict word, page ground"),
    ("verdict-not-established", "ui-01", 4.5, "verdict word, tile"),
    ("verdict-not-measurable", "ui-background", 4.5, "verdict word, page ground"),
    ("verdict-not-measurable", "ui-01", 4.5, "verdict word, tile"),
    ("interactive-01", "ui-background", 3.0, "selected rail marker, corridor stroke"),
    ("interactive-04", "ui-background", 4.5, "interactive text"),
    ("support-01", "ui-background", 4.5, "error text"),
    ("support-02", "ui-background", 4.5, "success text"),
    ("support-03", "ui-background", 4.5, "caution text, offset at bound"),
    ("focus", "ui-background", 3.0, "focus ring against the page ground"),
    ("border-strong", "ui-background", 3.0, "component boundary"),
    # Declared exemptions. Each carries its measured value so an exemption cannot
    # outlive the reason for it.
    ("text-03", "ui-02", 3.0, "rules and plot furniture, never a text run"),
    ("ui-04", "ui-background", 3.0, "component boundary, not text"),
]


def read_tokens(css: str) -> dict[str, str]:
    """Every `--name: #rrggbb;` in the file's first `:root` block."""
    start = css.index(":root {")
    end = css.index("\n}", start)
    block = css[start:end]
    return {
        m.group(1): m.group(2).lower()
        for m in re.finditer(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block)
    }


def _linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(fg: str, bg: str) -> float:
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def evaluate(tokens: dict[str, str]) -> list[tuple[str, str, float, float, bool, str]]:
    rows = []
    for fg, bg, floor, why in PAIRS:
        for name in (fg, bg):
            if name not in tokens:
                raise KeyError(
                    f"token --{name} is not defined in {CSS.name}. A pair that "
                    f"names a token nobody defines is a check that never ran."
                )
        ratio = contrast(tokens[fg], tokens[bg])
        rows.append((fg, bg, ratio, floor, ratio >= floor, why))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tokens = read_tokens(CSS.read_text(encoding="utf-8"))
    rows = evaluate(tokens)
    failures = [r for r in rows if not r[4]]

    if args.verbose or failures:
        print(f"{'foreground':26} {'background':16} {'ratio':>6} {'floor':>6}")
        for fg, bg, ratio, floor, ok, why in rows:
            mark = " " if ok else "  UNDER FLOOR"
            print(f"{fg:26} {bg:16} {ratio:6.2f} {floor:6.1f}{mark}")
            if args.verbose:
                print(f"{'':26} {tokens[fg]} on {tokens[bg]}  {why}")

    print(
        f"{len(rows) - len(failures)}/{len(rows)} contrast pairs meet their floor"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
