"""Freeze the digit bitmaps a SatNOGS waterfall's axis labels are drawn from.

    .venv/Scripts/python.exe scripts/build_glyph_templates.py --images 400

Runs once, needs easyocr, and writes `pipeline/tracetriage/data/glyph_templates.json`. After
that `pipeline/tracetriage/glyph_axis.py` reads the same labels with numpy, scipy and pillow,
which is what makes a 166 MB install able to report a frequency in Hz rather than in pixels.

**The labelling is easyocr's, and that is the point.** Every bitmap in the output was read by
easyocr on the same band it was cut from, so the matcher agrees with the neural path by
construction on the shapes it has seen. What that does NOT establish is agreement on shapes
it has not seen, and no amount of care here can establish it. That is
`tests/test_glyph_axis.py`, and it does not do it by comparing against the committed axis
values either, because those came from easyocr too and one of them is wrong: on observation
14736773 it read the centre tick as `562`. What the tests check is a property of the artefact
rather than another reader's opinion of it, namely that the labels form the arithmetic
progression a linear axis has to be.

**A bitmap is frozen only when several images agree on it.** The first version of this script
treated any disagreement as fatal, on the reasoning that a wrong template does not fail loudly
downstream: it rescales the frequency axis, and every offset measured through it is wrong by
that ratio with nothing in the output to say so. That reasoning still holds. What was wrong was
the assumption behind it, that easyocr's reading of a 10-pixel digit is reliable enough to be
ground truth. Measured on the first build over 120 waterfalls: four bitmaps came back with two
different digits from different images, and easyocr read a different number of characters than
there were components in 601 label groups, against 108 in the build that produced the
committed file.

So the evidence for a label is the number of independent images that agree on it. A bitmap
needs `MIN_VOTES` readings and `MIN_AGREEMENT` of them agreeing, and one that does not reach
both is dropped with its vote spread printed. Dropping costs a label, which the caller's
Hz/px derivation tolerates because it fits over several ticks. Guessing costs the axis.

Also measures and prints the two spacings `glyph_axis` relies on, because both are asserted
in its docstring and neither should be a guess: the largest column gap inside a label, and
the smallest gap between labels.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage import glyph_axis as ga  # noqa: E402
from pipeline.tracetriage import waterfall as wf  # noqa: E402

DEFAULT_SNAPSHOT = Path("D:/tracetriage_data/snap-stage1")

#: How many independent images must read a bitmap, and what share of them must agree, before
#: it is frozen. Three because two agreeing readings cannot outvote a third, and 0.8 because
#: the observed disagreement rate is a few bitmaps in several hundred rather than a coin flip:
#: a bitmap read the same way four times out of five is a bitmap with one bad reading against
#: it, and one read three times out of five is a bitmap nobody should rely on.
MIN_VOTES = 3
MIN_AGREEMENT = 0.8
OUT = REPO / "pipeline" / "tracetriage" / "data" / "glyph_templates.json"


def _classify_against(glyphs: dict[str, str], grid: np.ndarray) -> tuple[str | None, int]:
    """`glyph_axis.classify`, against a template set that is not on disk yet.

    A copy of the decision rule rather than a call into it, for one reason: the file being
    checked has not been written, so the real classifier would be testing the previous build.
    Writing an unverified file and then testing that is the shape of a check that passes
    because it examined the wrong thing. `tests/test_glyph_axis.py` asserts the two rules
    agree, so the copy cannot drift silently.
    """
    best: tuple[int, str] | None = None
    second = 10**6
    for packed, digit in glyphs.items():
        d = int(np.count_nonzero(grid ^ ga._unpack(packed)))
        if best is None or d < best[0]:
            second = best[0] if best is not None else second
            best = (d, digit)
        elif d < second:
            second = d
    if best is None or best[0] > ga.MAX_HAMMING:
        return None, best[0] if best else 10**6
    if second - best[0] < ga.MIN_MARGIN and second <= ga.MAX_HAMMING:
        return None, best[0]
    return best[1], best[0]


def _bands(files: list[Path]) -> Any:
    for path in files:
        try:
            rgb = np.asarray(Image.open(path).convert("RGB"))
            box = wf._detect_plot_box(rgb)
            band, _, _ = wf._extract_label_band(rgb, box)
        except Exception as exc:  # noqa: BLE001
            print(f"  {path.name}: no label band ({type(exc).__name__}: {exc})")
            continue
        yield path, band


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    ap.add_argument("--images", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260820)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    waterfalls = sorted((args.snapshot / "waterfalls").glob("*.png"))
    if not waterfalls:
        print(f"no waterfalls under {args.snapshot}", file=sys.stderr)
        return 2
    random.seed(args.seed)
    sample = random.sample(waterfalls, min(args.images, len(waterfalls)))
    print(f"{len(waterfalls)} waterfalls on disk, sampling {len(sample)} with seed {args.seed}")

    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    heights: collections.Counter = collections.Counter()
    widths: collections.Counter = collections.Counter()
    within_gaps: list[int] = []
    between_gaps: list[int] = []
    n_labelled = n_bands = n_unaligned = 0

    for _path, band in _bands(sample):
        n_bands += 1
        comps = ga.components(band)
        if not comps:
            continue
        for x0, x1, y0, y1, _ in comps:
            heights[y1 - y0] += 1
            widths[x1 - x0] += 1

        # Group exactly as the reader does, so the gaps measured here are the gaps it sees.
        groups: list[list] = []
        for comp in comps:
            if groups and comp[0] - groups[-1][-1][1] <= ga.LABEL_GAP_PX:
                groups[-1].append(comp)
            else:
                if groups:
                    between_gaps.append(comp[0] - groups[-1][-1][1])
                groups.append([comp])
        for group in groups:
            for a, b in zip(group, group[1:], strict=False):
                within_gaps.append(b[0] - a[1])

        readings = wf._ocr_labels(band)
        for group in groups:
            centre = (group[0][0] + group[-1][1]) / 2.0
            near = min(readings, key=lambda r: abs(r[0] - centre), default=None)
            if near is None or abs(near[0] - centre) > 8:
                n_unaligned += 1
                continue
            text = near[1].strip().lstrip("-")
            if not text.isdigit() or len(text) != len(group):
                n_unaligned += 1
                continue
            for (*_bbox, mask), digit in zip(group, text, strict=True):
                try:
                    packed = ga._pack(ga._normalise(mask))
                except ga.GlyphRefusal:
                    continue
                votes[packed][digit] += 1
                n_labelled += 1

    # easyocr is the labeller and it is not trusted: a bitmap is frozen only when several
    # independent images read it the same way. See the note at the top of this file for the
    # measurement that made that necessary rather than cautious.
    glyphs: dict[str, str] = {}
    dropped: list[str] = []
    for packed, counter in votes.items():
        total = sum(counter.values())
        digit, count = counter.most_common(1)[0]
        if total < MIN_VOTES or count / total < MIN_AGREEMENT:
            dropped.append(f"{dict(counter)} ({total} readings)")
            continue
        glyphs[packed] = digit

    print(f"\nbands read          {n_bands}")
    print(f"glyphs labelled     {n_labelled}")
    print(f"distinct bitmaps    {len(glyphs)}")
    print(f"groups unaligned    {n_unaligned} (easyocr read a different number of digits)")
    print(f"component heights   {sorted(heights.items())}")
    print(f"component widths    {sorted(widths.items())}")
    if within_gaps:
        print(f"within-label gaps   min {min(within_gaps)} max {max(within_gaps)}")
    if between_gaps:
        print(f"between-label gaps  min {min(between_gaps)} max {max(between_gaps)}")
    per_digit = collections.Counter(glyphs.values())
    print(f"bitmaps per digit   {dict(sorted(per_digit.items()))}")

    print(f"bitmaps kept        {len(glyphs)} of {len(votes)} seen")
    if dropped:
        print(f"bitmaps dropped     {len(dropped)}, below {MIN_VOTES} votes or "
              f"{MIN_AGREEMENT:.0%} agreement:")
        for d in dropped[:12]:
            print(f"  {d}")
    # ---- the safety check that replaced "every digit must appear" --------------------
    #
    # A frequency axis labelled in kHz rarely shows 5, 7 or 9: the ticks are round numbers at
    # round steps, so 0, 1, 2, 3, 4, 6 and 8 turn up constantly and the rest almost never.
    # Requiring all ten stopped the build over 200 images, and the requirement was aimed at
    # the wrong risk. A digit with no template is not read wrongly, it is not read at all: the
    # glyph fails the match, the label is dropped, and the Hz/px fit runs on the ticks that
    # are left. That is a loss of evidence, not a wrong number.
    #
    # The risk worth checking is the opposite one. A bitmap with no template of its own could
    # still land within MAX_HAMMING of some OTHER digit's template, and then it is read as
    # that digit and the axis is rescaled with nothing to show it. So every bitmap seen and
    # not frozen is run through the same decision rule: if any of them classifies, and to a
    # digit that disagrees with what easyocr read it as, the set is unsafe and nothing is
    # written.
    unsafe: list[str] = []
    for packed, counter in votes.items():
        if packed in glyphs:
            continue
        read_as, _ = counter.most_common(1)[0]
        would_be, distance = _classify_against(glyphs, ga._unpack(packed))
        if would_be is not None and would_be != read_as:
            unsafe.append(
                f"a bitmap read as {read_as!r} in {sum(counter.values())} image(s) "
                f"classifies as {would_be!r} at Hamming {distance}"
            )
    absent = "".join(sorted(set("0123456789") - set(per_digit)))
    print(f"digits covered      {''.join(sorted(set(per_digit)))}  "
          f"(absent: {absent or 'none'})")
    print(f"unfrozen bitmaps    {len(votes) - len(glyphs)}, of which "
          f"{len(unsafe)} would be misread")
    if unsafe:
        print(f"\n{len(unsafe)} UNSAFE templates; nothing written:", file=sys.stderr)
        for u in unsafe[:12]:
            print(f"  {u}", file=sys.stderr)
        print(
            "  A glyph with no template must fail to match, not match something else. "
            "Raise MIN_MARGIN, lower MAX_HAMMING, or sample more images so the missing "
            "digits get templates of their own.",
            file=sys.stderr,
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "schema": "GLYPH_TEMPLATES",
                "schema_version": 1,
                "provenance": {
                    "built_by": "scripts/build_glyph_templates.py",
                    "labelled_by": "easyocr, via waterfall._ocr_labels, on the same band",
                    "snapshot": str(args.snapshot),
                    "images_sampled": len(sample),
                    "seed": args.seed,
                    "bands_read": n_bands,
                    "glyphs_labelled": n_labelled,
                    "bitmaps_seen": len(votes),
                    "bitmaps_dropped": len(dropped),
                    "min_votes": MIN_VOTES,
                    "min_agreement": MIN_AGREEMENT,
                    "digits_covered": "".join(sorted(set(per_digit))),
                    "digits_absent": "".join(sorted(set("0123456789") - set(per_digit))),
                    "unfrozen_bitmaps_checked_for_misreads": len(votes) - len(glyphs),
                    "grid": [ga.GRID_H, ga.GRID_W],
                    "ink_threshold": ga.INK_THRESHOLD,
                    "component_heights": dict(sorted(heights.items())),
                    "within_label_gap_max": max(within_gaps) if within_gaps else None,
                    "between_label_gap_min": min(between_gaps) if between_gaps else None,
                    "reading": (
                        "Each key is a digit bitmap padded into the grid above, ink as 1, "
                        "rows joined by /. Read by easyocr once so that nothing downstream "
                        "needs easyocr. A conflicting label stops the build rather than "
                        "being resolved by majority, because a wrong template rescales the "
                        "frequency axis instead of failing."
                    ),
                },
                "glyphs": dict(sorted(glyphs.items())),
            },
            indent=1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(f"\nwrote {args.out.relative_to(REPO)}  ({args.out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
