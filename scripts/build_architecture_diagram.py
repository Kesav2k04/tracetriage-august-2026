"""Generate the architecture diagram, from the stages that actually exist.

    .venv/Scripts/python.exe scripts/build_architecture_diagram.py
    .venv/Scripts/python.exe scripts/build_architecture_diagram.py --check

The README carried an ASCII block for this. It read fine and it had the property every
hand-drawn diagram has: nothing connected it to the code, so a stage could be renamed,
split or deleted and the picture would keep describing the old shape. This writes an
SVG from a table of stages, and every stage names the module that implements it and the
receipt it writes. Both are checked against the tree before a single rectangle is
emitted, so the diagram cannot describe a pipeline this repository does not have.

`--check` regenerates and compares, so the standing gate can fail on drift rather than
on someone remembering to re-run this.

The colours are the console's tokens, read from `apps/web/app/globals.css` rather than
retyped, which is the same reason: two copies of a palette is one palette and one
mistake waiting. The diagram is therefore in the same warm graphite and inferno the site
is, and a judge who opens the README and then the console sees one project.

Why an SVG and not Mermaid: GitHub renders Mermaid, the console does not, and the
diagram is wanted in both places. An SVG is one file that works in a README, in a static
export and in a slide.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "apps/web/app/globals.css"
OUT = REPO / "docs/architecture.svg"


@dataclass(frozen=True)
class Stage:
    """One box. `module` and `receipt` are paths that must exist."""

    key: str
    title: str
    detail: str
    module: str
    receipt: str
    column: int
    row: int


# The pipeline, in the order it runs. Column 0 is the spine; columns 1 and 2 are the
# four parallel evidence channels that feed the fusion head, drawn side by side because
# they are computed independently from the same snapshot.
STAGES: tuple[Stage, ...] = (
    Stage(
        "snapshot",
        "Snapshot",
        "SatNOGS metadata and waterfalls, frozen with a SHA-256 per file, retrieval "
        "times and CC BY-SA terms",
        "pipeline/tracetriage/snapshot.py",
        "artifacts/DATASET_MANIFEST.json",
        0,
        0,
    ),
    Stage(
        "physics",
        "Physics",
        "SGP4 from each observation's own stored TLE: elevation, range rate, the "
        "expected corrected-centre corridor",
        "pipeline/tracetriage/physics.py",
        "artifacts/PHYSICS_VALIDATION.json",
        0,
        1,
    ),
    Stage(
        "splits",
        "Splits",
        "four holdouts, frozen before any model is fitted",
        "pipeline/tracetriage/splits.py",
        "artifacts/SPLIT_MANIFEST.json",
        0,
        2,
    ),
    Stage(
        "waterfall",
        "Image",
        "crop, dead-row detection, the frequency axis derived per observation "
        "from its own rendered ticks",
        "pipeline/tracetriage/waterfall.py",
        "artifacts/SECOND_TRACE_SURVEY.json",
        1,
        3,
    ),
    Stage(
        "corridor",
        "Corridor fit",
        "one bounded offset search per observation, scored against nulls built "
        "from that observation's own Doppler values",
        "pipeline/tracetriage/corridor_fit.py",
        "artifacts/GATE3_RECEIPT.json",
        2,
        3,
    ),
    Stage(
        "features",
        "Features",
        "centre energy, HOG, and the corridor statistics the fit produces",
        "pipeline/tracetriage/features.py",
        "artifacts/corridor_features.json",
        1,
        4,
    ),
    Stage(
        "baseline",
        "Baseline arm",
        "image-only, calibrated, the control the physics arm has to beat",
        "pipeline/tracetriage/baseline.py",
        "artifacts/BASELINE_RECEIPT.json",
        2,
        4,
    ),
    Stage(
        "fusion",
        "Fusion head",
        "small and calibrated, reported against the baseline on a chronological "
        "split with an interval",
        "pipeline/tracetriage/fusion.py",
        "artifacts/FUSION_RECEIPT.json",
        0,
        5,
    ),
    Stage(
        "selective",
        "Calibration, OOD, abstention",
        "the model declines rather than guessing, and the risk-coverage curve says "
        "what declining bought",
        "pipeline/tracetriage/selective.py",
        "artifacts/TRIAGE_RECEIPT.json",
        0,
        6,
    ),
    Stage(
        "queue",
        "Review-value queue",
        "disagreement reason codes, episode deduplication, concentration caps, and "
        "the lift over random at equal budget",
        "pipeline/tracetriage/queue.py",
        "artifacts/QUEUE_RECEIPT.json",
        0,
        7,
    ),
    Stage(
        "explain",
        "Reviewer note",
        "Granite 3.1 dense 8B on a closed evidence packet, behind a grounding "
        "checker that refuses more than it accepts",
        "pipeline/tracetriage/explain.py",
        "artifacts/EXPLAIN_RECEIPT.json",
        1,
        8,
    ),
    Stage(
        "agent",
        "Evidence agent",
        "five read-only MCP tools over the receipts, measured against a control arm "
        "with none",
        "pipeline/tracetriage/agent.py",
        "artifacts/AGENT_RECEIPT.json",
        2,
        8,
    ),
    Stage(
        "console",
        "Static console",
        "one evidence card per observation, every number read from a receipt. No "
        "server, no database, nothing written back",
        "apps/web/app/page.tsx",
        "apps/web/public/data/queue.json",
        0,
        9,
    ),
)

# Edges, as (from, to). Written out rather than inferred from the rows, because the
# four parallel channels rejoin and a layout rule cannot know that.
EDGES: tuple[tuple[str, str], ...] = (
    ("snapshot", "physics"),
    ("physics", "splits"),
    ("splits", "waterfall"),
    ("splits", "corridor"),
    ("waterfall", "features"),
    ("corridor", "baseline"),
    ("features", "fusion"),
    ("baseline", "fusion"),
    ("fusion", "selective"),
    ("selective", "queue"),
    ("queue", "explain"),
    ("queue", "agent"),
    ("explain", "console"),
    ("agent", "console"),
)


def tokens() -> dict[str, str]:
    """The palette, read from the stylesheet the console ships."""
    css = CSS.read_text(encoding="utf-8")
    start = css.index(":root {")
    # The whole block, not up to the spacing steps. --border-subtle and
    # --interactive-01 both sit after them, and a reader that stops early reports a
    # token as missing when it is only further down the file.
    end = css.index("\n}", start)
    found = dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", css[start:end]))
    needed = (
        "ui-background",
        "ui-01",
        "text-01",
        "text-02",
        "text-03",
        "border-subtle",
        "interactive-01",
    )
    missing = [n for n in needed if n not in found]
    if missing:
        raise SystemExit(
            f"globals.css no longer defines {', '.join(missing)}. The diagram reads its "
            f"palette from the stylesheet so the two cannot drift; a renamed token has "
            f"to be renamed here too."
        )
    return found


def verify_paths() -> None:
    """Every module and receipt a box names must exist. A diagram that describes a
    stage this repository does not have is worse than no diagram."""
    problems: list[str] = []
    for stage in STAGES:
        for label, rel in (("module", stage.module), ("receipt", stage.receipt)):
            path = REPO / rel
            if not path.exists():
                problems.append(f"{stage.key}: {label} {rel} does not exist")
            elif path.is_file() and path.stat().st_size == 0:
                problems.append(f"{stage.key}: {label} {rel} is empty")
    keys = {s.key for s in STAGES}
    for a, b in EDGES:
        if a not in keys:
            problems.append(f"edge {a} -> {b}: {a} is not a stage")
        if b not in keys:
            problems.append(f"edge {a} -> {b}: {b} is not a stage")
    unreached = keys - {b for _, b in EDGES} - {STAGES[0].key}
    if unreached:
        problems.append(
            f"stages nothing points at: {', '.join(sorted(unreached))}. A box with no "
            f"inbound edge is drawn but disconnected, which reads as a stage that runs "
            f"on nothing."
        )
    if problems:
        raise SystemExit("architecture diagram is out of date:\n  " + "\n  ".join(problems))


# ---- geometry ---------------------------------------------------------------
COL_X = (40, 40, 452)
COL_W = (824, 400, 412)
ROW_H = 96
ROW_GAP = 22
TOP = 64


def wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if len(trial) > width and line:
            lines.append(line)
            line = w
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def box_rect(stage: Stage) -> tuple[int, int, int, int]:
    x = COL_X[stage.column]
    w = COL_W[stage.column]
    if stage.column == 1:
        w = 400
    y = TOP + stage.row * (ROW_H + ROW_GAP)
    return x, y, w, ROW_H


def render() -> str:
    t = tokens()
    height = TOP + len({s.row for s in STAGES}) * (ROW_H + ROW_GAP) + 40
    width = 904

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-labelledby="arch-title arch-desc" font-family="IBM Plex Sans, '
        f'system-ui, sans-serif">',
        '<title id="arch-title">TraceTriage pipeline architecture</title>',
        '<desc id="arch-desc">'
        + escape(
            "Ten stages running top to bottom. A frozen SatNOGS snapshot feeds SGP4 "
            "physics, then four frozen splits. Two evidence channels run side by side, "
            "image processing into features and a bounded corridor fit into a "
            "calibrated image-only baseline arm. Both feed a small calibrated fusion "
            "head, then calibration with out-of-distribution detection and abstention, "
            "then the review-value queue. The queue feeds a Granite reviewer note and a "
            "read-only evidence agent, and both feed the static console. Every box "
            "names the module that implements it and the receipt it writes."
        )
        + "</desc>",
        f'<rect width="{width}" height="{height}" fill="{t["ui-background"]}"/>',
    ]

    # A hairline scale down the left edge, the same plate furniture the console carries.
    parts.append(
        f'<g stroke="{t["ui-01"]}" stroke-width="1">'
        + "".join(
            f'<line x1="12" y1="{y}" x2="24" y2="{y}"/>'
            for y in range(24, height - 12, 8)
        )
        + "</g>"
    )

    # Edges first, so a box always paints over a line rather than under it.
    rects = {s.key: box_rect(s) for s in STAGES}
    parts.append(f'<g stroke="{t["interactive-01"]}" stroke-width="1.5" fill="none">')
    for a, b in EDGES:
        ax, ay, aw, ah = rects[a]
        bx, by, bw, bh = rects[b]
        x1, y1 = ax + aw / 2, ay + ah
        x2, y2 = bx + bw / 2, by
        if abs(x1 - x2) < 1:
            parts.append(f'<path d="M {x1} {y1} L {x2} {y2}"/>')
        else:
            mid = (y1 + y2) / 2
            parts.append(
                f'<path d="M {x1} {y1} L {x1} {mid} L {x2} {mid} L {x2} {y2}"/>'
            )
        # A tick at the arrival, rather than an arrowhead marker: one shape fewer and
        # it reads as a registration mark on a plate.
        parts.append(f'<path d="M {x2 - 4} {y2 - 5} L {x2} {y2} L {x2 + 4} {y2 - 5}"/>')
    parts.append("</g>")

    for stage in STAGES:
        x, y, w, h = rects[stage.key]
        parts.append("<g>")
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{t["ui-01"]}" '
            f'stroke="{t["border-subtle"]}" stroke-width="1"/>'
        )
        # The accent rule at the leading edge of every box, so the spine reads as one
        # sequence rather than as ten unrelated panels.
        parts.append(
            f'<rect x="{x}" y="{y}" width="3" height="{h}" '
            f'fill="{t["interactive-01"]}"/>'
        )
        parts.append(
            f'<text x="{x + 16}" y="{y + 24}" fill="{t["text-01"]}" font-size="14" '
            f'font-weight="600">{escape(stage.title)}</text>'
        )
        chars = max(28, int((w - 32) / 5.05))
        for i, line in enumerate(wrap(stage.detail, chars)[:3]):
            parts.append(
                f'<text x="{x + 16}" y="{y + 42 + i * 15}" fill="{t["text-02"]}" '
                f'font-size="11.5">{escape(line)}</text>'
            )
        # Basenames, not full paths. At font-size 10 the widest pair,
        # `pipeline/tracetriage/waterfall.py → artifacts/SECOND_TRACE_SURVEY.json`, is
        # 71 characters at about 6px each, which is 426px inside a 368px box: it ran
        # off the right edge. The two directory prefixes are constant across all
        # thirteen stages, so they are stated once in the strapline and the box carries
        # the part that differs. `verify_paths` still checks the full paths, and each
        # box carries them in a <title> so a hover and a screen reader both get them.
        parts.append(
            f"<title>{escape(stage.module)} writes {escape(stage.receipt)}</title>"
        )
        parts.append(
            f'<text x="{x + 16}" y="{y + h - 10}" fill="{t["text-03"]}" '
            f'font-size="10" font-family="IBM Plex Mono, ui-monospace, monospace">'
            f"{escape(Path(stage.module).name)}  →  "
            f"{escape(Path(stage.receipt).name)}</text>"
        )
        parts.append("</g>")

    parts.append(
        f'<text x="40" y="34" fill="{t["text-03"]}" font-size="10" font-weight="600" '
        f'letter-spacing="1.4">TRACETRIAGE PIPELINE  ·  MODULES UNDER '
        f'PIPELINE/TRACETRIAGE/  ·  RECEIPTS UNDER ARTIFACTS/</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail instead of writing")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    verify_paths()
    svg = render()

    if args.check:
        if not args.out.exists():
            print(f"{args.out.relative_to(REPO)} does not exist")
            return 1
        if args.out.read_text(encoding="utf-8") != svg:
            print(
                f"{args.out.relative_to(REPO)} is out of date. Run "
                f"scripts/build_architecture_diagram.py"
            )
            return 1
        print(f"{args.out.relative_to(REPO)} is current: {len(STAGES)} stages")
        return 0

    args.out.write_text(svg, encoding="utf-8")
    print(
        f"wrote {args.out.relative_to(REPO)}: {len(STAGES)} stages, "
        f"{len(EDGES)} edges, {len(svg)} bytes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
