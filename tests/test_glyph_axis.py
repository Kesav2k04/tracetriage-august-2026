"""The template matcher reads the same frequency axis the neural model read.

`pipeline/tracetriage/glyph_axis.py` exists so that a 166 MB install can report a frequency
offset in Hz instead of in pixels.

**The obvious test for it is the wrong test.** Comparing its derived Hz/px against the value
in `artifacts/a3_overlays/summary.json` looks like the natural check, and it was the first one
written here, at a relative tolerance of 1e-9. It failed on nine of twenty-four observations,
and reading those failures produced both of the findings below.

easyocr is not ground truth at this glyph size. On observation 14736773 it read the centre
tick as `562`, so the committed axis for that image was derived through a label of 562 kHz
where the value is 0. Asserting agreement with the committed number would have been asserting
that the template matcher reproduces that.

**So the axis is checked against its own structure instead.** A matplotlib linear axis puts
evenly spaced ticks at an arithmetic progression of round values. That is a property neither
reader can fake and neither reader is needed to establish: given the tick positions, the
labels have to be `a + k*step`. It catches exactly the failure that matters, and it caught
one: with 4-connected components the digit 3 splits in two at this size, because its middle
stroke meets the bowls only diagonally. Both halves then fail the digit-height filter and
`30` reads as `0`. The progression check fails on
`[-30000, -20000, -10000, 0, 10000, 20000, 0]` for a reason no tolerance would have
articulated.

A misread label does not look like a failure downstream. It rescales the frequency axis, so
every offset measured through it is wrong by that ratio, with a plausible number and a
confidence figure beside it and nothing anywhere in the output to say so.

Marker: `dataset`, because the images come from a built snapshot. One test adds `ocr`, since
comparing the two readers means running both.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
A3_SUMMARY = REPO / "artifacts/a3_overlays/summary.json"

pytestmark = [pytest.mark.dataset]


def _snapshot_dir() -> Path | None:
    env = os.environ.get("TRACETRIAGE_SNAPSHOT")
    for base in ([Path(env)] if env else []) + [Path("D:/tracetriage_data/snap-stage1")]:
        if (base / "waterfalls").is_dir():
            return base
    return None


SNAP = _snapshot_dir()
requires_snapshot = pytest.mark.skipif(SNAP is None, reason="no built snapshot on disk")


@pytest.fixture(scope="module")
def a3_rows() -> list[dict]:
    return json.loads(A3_SUMMARY.read_text(encoding="utf-8"))


def _band(obs_id: int):
    """The label band, and the PATH the whole image came from.

    The path, not the decoded array: `parse_waterfall` takes bytes or a Path and reports
    MALFORMED_PNG for anything else, so handing it the ndarray this function already had made
    all 24 observations fail with a reason that reads like corrupt data.
    """
    from PIL import Image

    from pipeline.tracetriage import waterfall as wf

    path = SNAP / "waterfalls" / f"waterfall_{obs_id}.png"
    if not path.exists():
        return None, None
    rgb = np.asarray(Image.open(path).convert("RGB"))
    box = wf._detect_plot_box(rgb)
    band, _, _ = wf._extract_label_band(rgb, box)
    return path, band


def test_the_templates_are_committed_and_say_how_they_were_built():
    """A template file with no provenance is a magic number in a JSON wrapper."""
    from pipeline.tracetriage import glyph_axis as ga

    meta = ga.template_metadata()
    assert meta["present"], (
        f"{ga.TEMPLATE_PATH} is missing. It ships inside the package on purpose: a template "
        f"file that lived in the repository would have moved the download rather than "
        f"removed it. Regenerate with scripts/build_glyph_templates.py."
    )
    assert meta["n_bitmaps"] > 0
    assert meta["labelled_by"].startswith("easyocr")
    assert meta["images_sampled"] >= 100, "a handful of images is not a corpus"
    assert meta["min_votes"] >= 3, (
        "a bitmap frozen on fewer than three readings rests on a labeller this project "
        "measured to be noisy at this glyph size"
    )
    assert meta["grid"] == [ga.GRID_H, ga.GRID_W], (
        "the templates were padded into a different grid than the reader pads into, so every "
        "comparison is between a glyph and a shifted template"
    )
    assert meta["ink_threshold"] == ga.INK_THRESHOLD


def test_every_template_classifies_as_its_own_digit():
    """The set's internal consistency, which nothing else checks.

    Two templates for different digits can sit close together without breaking anything,
    because `MIN_MARGIN` refuses a near-tie. What must not happen is a template that reads as
    some other digit: that is a glyph the matcher gets wrong every single time it appears,
    and it would be invisible in any aggregate agreement rate.
    """
    from pipeline.tracetriage import glyph_axis as ga

    blob = json.loads(ga.TEMPLATE_PATH.read_text(encoding="utf-8"))
    wrong = []
    for packed, digit in blob["glyphs"].items():
        grid = ga._unpack(packed)
        got, distance = ga.classify(grid)
        if got != digit:
            wrong.append(f"a {digit!r} template classifies as {got!r} at Hamming {distance}")
    assert not wrong, "\n".join(wrong)


def test_an_unknown_bitmap_is_refused_rather_than_guessed():
    """Nothing is closer to a digit than a digit, and noise is closer to nothing.

    The refusal path is the whole safety argument of this module, so it gets a test that does
    not depend on any particular corpus: a random mask and an empty mask must both come back
    as None. If either classified, the matcher would be assigning digits to the axis title,
    to compression artefacts and to the tick marks.
    """
    from pipeline.tracetriage import glyph_axis as ga

    rng = np.random.default_rng(20260820)
    for _ in range(50):
        noise = rng.random((10, 6)) < 0.5
        digit, _ = ga.classify(noise)
        assert digit is None, "random ink classified as a digit"
    assert ga.classify(np.zeros((10, 6), dtype=bool))[0] is None
    assert ga.classify(np.ones((10, 6), dtype=bool))[0] is None


def test_the_builders_decision_rule_matches_the_readers():
    """The builder carries a copy of `classify`, and a copy is a thing that drifts.

    It has to be a copy: the builder decides whether a template set is safe before writing
    it, so calling the reader would test the previous build's file. This test is what keeps
    the two in step, by running both over the committed set.
    """
    import importlib.util

    from pipeline.tracetriage import glyph_axis as ga

    spec = importlib.util.spec_from_file_location(
        "build_glyph_templates", REPO / "scripts" / "build_glyph_templates.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    blob = json.loads(ga.TEMPLATE_PATH.read_text(encoding="utf-8"))
    glyphs = blob["glyphs"]
    rng = np.random.default_rng(7)
    cases = [ga._unpack(p) for p in list(glyphs)[:8]]
    cases += [rng.random((10, 6)) < 0.45 for _ in range(12)]
    for grid in cases:
        want = ga.classify(grid if grid.shape == (ga.GRID_H, ga.GRID_W)
                           else ga._normalise(grid))
        got = module._classify_against(
            glyphs,
            grid if grid.shape == (ga.GRID_H, ga.GRID_W) else ga._normalise(grid),
        )
        assert want == got, f"the two rules disagree: reader {want}, builder {got}"


@requires_snapshot
def test_the_axis_title_is_not_read_as_digits(a3_rows):
    """Every component the reader keeps is digit-height, and the title's letters are not.

    A first version of this module had a height floor of 6, which fed capital F, lower-case z
    and the parentheses of the axis title to a digit matcher. It did not produce wrong digits,
    because they fail the match, but it did make easyocr read a different number of characters
    than there were components in 601 label groups during a template build, which
    is how the height distribution came to be measured at all.
    """
    from pipeline.tracetriage import glyph_axis as ga

    heights: set[int] = set()
    checked = 0
    for row in a3_rows[:8]:
        _path, band = _band(row["obs_id"])
        if band is None:
            continue
        checked += 1
        for _x0, _x1, y0, y1, _mask in ga.components(band):
            heights.add(y1 - y0)
    assert checked, "no snapshot image was available, so this test proved nothing"
    assert heights, "no digit-height component in any band"
    assert heights <= {9, 10, 11}, f"the reader kept components of height {sorted(heights)}"


def _progression_error(tick_xs, hz_values) -> str | None:
    """Is this set of labels an arithmetic progression over the tick indices?

    Returns None when it is, and a description when it is not. Ticks with no label are
    skipped rather than treated as zero, and the step is taken from the first and last
    labelled tick so a single wrong value in the middle cannot define the line it is then
    measured against.
    """
    known = [(i, hz) for i, hz in enumerate(hz_values) if hz is not None]
    if len(known) < 3:
        return f"only {len(known)} of {len(tick_xs)} ticks carry a label"
    (i0, h0), (i1, h1) = known[0], known[-1]
    if i1 == i0:
        return "the first and last labelled tick are the same tick"
    step = (h1 - h0) / (i1 - i0)
    if step == 0:
        return f"every labelled tick reads {h0}, so the axis has no scale"
    bad = [
        f"tick {i} reads {hz} where the progression gives {h0 + step * (i - i0):.0f}"
        for i, hz in known
        if abs(hz - (h0 + step * (i - i0))) > 1.0
    ]
    return "; ".join(bad) if bad else None


def _ticks_and_band(obs_id: int):
    """Tick positions, the plot box and the label band for one observation."""
    from PIL import Image

    from pipeline.tracetriage import waterfall as wf

    path, band = _band(obs_id)
    if band is None:
        return None, None, None
    rgb = np.asarray(Image.open(path).convert("RGB"))
    box = wf._detect_plot_box(rgb)
    ticks = wf._detect_ticks(rgb, box)
    if len(ticks) < 3:
        return None, None, None
    return ticks, box, band


@requires_snapshot
def test_the_labels_form_the_arithmetic_progression_an_axis_has_to_be(a3_rows):
    """The reader-independent check, and the one that found the connectivity bug.

    Every tick this reader labels has to sit on one straight line through the tick index.
    Nothing about easyocr, nothing about a committed value, and no tolerance to choose: a
    linear axis is a linear axis.
    """
    from pipeline.tracetriage import glyph_axis as ga
    from pipeline.tracetriage import waterfall as wf

    broken, checked = [], 0
    for row in a3_rows:
        ticks, box, band = _ticks_and_band(row["obs_id"])
        if ticks is None:
            continue
        hz_values, _ = wf._parse_ocr_labels(ga.read_labels(band), ticks, box)
        problem = _progression_error(ticks, hz_values)
        checked += 1
        if problem:
            broken.append(f"obs {row['obs_id']}: {hz_values} -> {problem}")
    assert checked >= 10, f"only {checked} observations had a readable axis"
    assert not broken, (
        "the glyph reader produced labels that are not an arithmetic progression, which "
        "means a wrong value on a tick rather than a missing one:\n" + "\n".join(broken)
    )


@pytest.mark.ocr
@requires_snapshot
def test_it_agrees_with_the_committed_axis_wherever_that_axis_is_sound(a3_rows):
    """Agreement where easyocr's labels pass the progression check, and a count where not.

    Split in two because the disagreements are not symmetrical. Where the neural reader
    produced a clean set of labels, the two derivations should land on the same axis and the
    tolerance can be tight. Where it did not, the committed number was derived through a
    label like 562 kHz, and agreement with it would be the wrong thing to want.

    Marked `ocr` on the test rather than the module: the question is whether easyocr's reading
    of a given band was sound, and a frozen copy of that reading cannot answer it.
    """
    from pipeline.tracetriage import glyph_axis as ga
    from pipeline.tracetriage import waterfall as wf

    agree, mismatch, unsound = 0, [], []
    for row in a3_rows:
        ticks, box, band = _ticks_and_band(row["obs_id"])
        if ticks is None:
            continue
        glyph_hz, _ = wf._parse_ocr_labels(ga.read_labels(band), ticks, box)
        ocr_hz, _ = wf._parse_ocr_labels(wf._ocr_labels(band), ticks, box)
        if _progression_error(ticks, ocr_hz) is not None:
            unsound.append(row["obs_id"])
            continue
        try:
            g, _ = wf._derive_hz_per_px(ticks, glyph_hz)
            o, _ = wf._derive_hz_per_px(ticks, ocr_hz)
        except Exception:  # noqa: BLE001
            continue
        if g == pytest.approx(o, rel=1e-9):
            agree += 1
        else:
            mismatch.append(f"obs {row['obs_id']}: glyph {g:.6f} against easyocr {o:.6f}")

    assert agree >= 3, (
        f"only {agree} observations had a sound reading from both, so this proved little. "
        f"Unsound easyocr readings: {unsound}"
    )
    assert not mismatch, (
        "the two readers derived different axes from label sets that both pass the "
        "progression check, so one of them is misreading a digit:\n" + "\n".join(mismatch)
    )
