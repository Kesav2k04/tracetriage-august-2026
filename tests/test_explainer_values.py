"""Every number and every axis direction the corridor clip draws, against its card.

The scene duplicates its values rather than importing them, for the reason stated in its
own docstring: it has to keep rendering from a checkout with no receipts built. The cost
of that decision is this file. Eight constants and two axis mappings are copied out of
`artifacts/` by hand, and nothing but these checks holds them to the source.

The axis checks are not decoration, and a magnitude test alone would not replace them.
`OFFSET_PX` is a column delta, not the fitted offset in hertz divided by hertz per pixel:
those two differ in sign, because the card's own note says the frequency axis runs against
the Doppler sign, which is why a ``peak_offset_hz`` of -5648.1 pairs with a
``peak_offset_px`` of +61. Row 0 is the start of the pass and time runs bottom to top, so
row 0 belongs at the top of the plot.

Get either one backwards on this observation and the picture still looks right. Closest
approach sits at 0.499 of the pass, so the corridor is very nearly odd-symmetric about its
own centre, and flipping both axes is a 180 degree rotation that maps the predicted curve
onto itself. Only the side the fitted curve falls on gives it away.
`pipeline/doppler_mode.py` documents this same cancellation as a defect that has bitten
once elsewhere in the project.

If a check here fails the fix is to re-render, not to edit the constant.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCENE = REPO / "scripts/explainer_corridor.py"
CARDS = REPO / "apps/web/public/data/cards.json"
PUBLISHED = REPO / "apps/web/public/media/corridor-explainer.mp4"
POSTER = REPO / "apps/web/public/media/corridor-explainer-poster.jpg"


def _constants() -> dict[str, str]:
    """The scene's module-level constants, read as text.

    Parsed rather than imported, for the reason the gate 4 twin gives: importing the
    scene imports manim, and manim is a render-time dependency that the offline suite
    does not have and does not need.
    """
    source = SCENE.read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Z][A-Z0-9_]*) = (.+?)$", source, re.MULTILINE))


@pytest.fixture(scope="module")
def scene() -> dict[str, str]:
    return _constants()


@pytest.fixture(scope="module")
def source() -> str:
    return SCENE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def card() -> dict:
    """The exported card the scene says every number comes from."""
    rows = json.loads(CARDS.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("cards", [])
    obs = _constants()["OBS_ID"].strip()
    hit = [r for r in rows if str(r.get("observation_id") or r.get("obs_id")) == obs]
    assert hit, f"the scene draws observation {obs} and no card for it is published"
    return hit[0]


def test_the_scalar_figures_are_the_card_s(scene, card):
    corridor = card["corridor"]
    assert int(scene["OBS_ID"]) == int(card.get("observation_id") or card["obs_id"])
    assert float(scene["HZ_PER_PX"]) == pytest.approx(card["hz_per_px"], abs=5e-3)
    assert float(scene["CENTRE_PX"]) == pytest.approx(card["centre_px"], abs=5e-3)
    assert float(scene["HALF_WIDTH_PX"]) == pytest.approx(
        corridor["half_width_px"], abs=5e-2
    )
    assert float(scene["MAX_EL_DEG"]) == pytest.approx(
        corridor["max_elevation_deg"], abs=5e-2
    )
    assert float(scene["OFFSET_HZ"]) == pytest.approx(
        corridor["fitted_offset_hz"], abs=5e-2
    )
    assert float(scene["OFFSET_PPM"]) == pytest.approx(
        corridor["fitted_offset_ppm"], abs=5e-3
    )


def _image_size(source: str) -> tuple[int, int]:
    """``IMG_W, IMG_H`` is a tuple assignment, so the scalar reader cannot see it."""
    pair = re.search(r"^IMG_W, IMG_H = (\d+), (\d+)$", source, re.MULTILINE)
    assert pair, "the scene no longer declares IMG_W, IMG_H as a plain tuple"
    return int(pair.group(1)), int(pair.group(2))


def test_the_image_dimensions_are_the_card_s(source, card):
    width, height = _image_size(source)
    assert width == card["width"]
    assert height == card["height"]


def test_the_offset_is_a_column_delta_and_not_a_hertz_quotient(scene, card):
    """The check that would have caught the mirrored clip.

    ``fitted_px`` minus ``predicted_px`` is the number of columns the scene has to shift
    by, and the card holds both arrays so the delta is not inferred. Dividing the hertz
    offset by hertz per pixel gives the same magnitude with the opposite sign, because
    the frequency axis runs against the Doppler sign. Both readings are 61. Only one of
    them puts the fitted curve on the side the console draws it.
    """
    corridor = card["corridor"]
    deltas = {
        round(f - p, 6)
        for f, p in zip(corridor["fitted_px"], corridor["predicted_px"], strict=True)
    }
    assert len(deltas) == 1, (
        f"the card's fitted and predicted curves differ by more than one constant "
        f"{sorted(deltas)[:4]}, so there is no single offset for the scene to draw"
    )
    delta = deltas.pop()
    assert float(scene["OFFSET_PX"]) == pytest.approx(delta, abs=5e-2), (
        f"the scene shifts the fitted curve by {scene['OFFSET_PX']} columns and the card "
        f"shifts it by {delta:+g}. The magnitudes agreeing while the signs do not is the "
        f"signature of OFFSET_HZ / HZ_PER_PX being used as a column delta: the card's "
        f"note says the frequency axis runs against the Doppler sign. Re-render; do not "
        f"edit the sign here to match a stale mp4."
    )
    quotient = corridor["fitted_offset_hz"] / card["hz_per_px"]
    assert float(scene["OFFSET_PX"]) != pytest.approx(quotient, abs=5e-2), (
        "OFFSET_PX equals the hertz offset divided by hertz per pixel, which is the "
        "wrong sign by construction on this axis"
    )


def test_the_significance_the_clip_states_is_the_card_s(scene, card):
    """The clip's closing card names its own sigma, and it has to be the real one.

    This observation was chosen for having the strongest corridor curvature in the
    shipped set, which is what makes the shape readable, and the cost of that choice is
    that the fit on it is not decisive. A clip that draws the clearest picture on the
    site while saying nothing about significance invites the reading that it is also the
    strongest result on the site, which is a different claim and one the card does not
    support. So the sigma goes on screen, and the number on screen is pinned here.
    """
    corridor = card["corridor"]
    assert float(scene["SIGMA_CURVED"]) == pytest.approx(
        corridor["sigma_curved"], abs=5e-4
    )
    assert float(scene["SIGMA_VERTICAL"]) == pytest.approx(
        corridor["sigma_vertical"], abs=5e-4
    )
    assert float(scene["SIGMA_CURVED"]) < 2.0, (
        "the clip says this fit is not decisive. If the card now reports a sigma that "
        "clears the usual bar, the closing card's wording has to change with it."
    )


def test_the_offset_agrees_with_the_published_sweep_peak(scene, card):
    """A second, independent reading of the same quantity.

    ``offset_sweep.peak_offset_px`` is written by the fit rather than derived from the
    two curves, so it catches the case where both arrays are wrong together.
    """
    peak = card["corridor"]["offset_sweep"]["peak_offset_px"]
    assert float(scene["OFFSET_PX"]) == pytest.approx(peak, abs=5e-2)


def test_the_predicted_curve_is_the_card_s_row_for_row(scene, source, card):
    """Every sample the scene draws, against the row the card holds for it."""
    corridor = card["corridor"]
    by_row = dict(zip(card["corridor"]["rows"], corridor["predicted_px"], strict=True))
    block = re.search(r"^PRED = \[(.+?)^\]", source, re.MULTILINE | re.DOTALL)
    assert block, "the scene no longer carries a PRED table this test can read"
    drawn = ast.literal_eval("[" + block.group(1) + "]")
    assert drawn, "PRED is empty"
    for row, column in drawn:
        assert row in by_row, (
            f"the scene draws row {row} and the card publishes no such row, so the "
            f"sample was not taken from the card"
        )
        assert column == pytest.approx(by_row[row], abs=5e-2), (
            f"row {row}: the scene draws column {column} and the card holds "
            f"{by_row[row]}"
        )


def test_row_zero_is_drawn_at_the_top_of_the_plot(source):
    """The time axis, checked as a direction rather than as a label.

    The card's note and the scene's own comment both say row 0 is the end of the pass
    and that time runs bottom to top, so row 0 is the latest sample and belongs at the
    top of the frame. Manim's y increases upward, so a mapping that sends row 0 to the
    bottom of the plot draws the pass upside down. The scene's on-screen axis label says
    "time, bottom to top" either way, which is why the label cannot be the test.
    """
    body = re.search(r"def to_point\(.*?\n(?:.*?\n)*?    return ", source)
    assert body, "to_point is no longer shaped so this test can read its mapping"
    mapping = re.search(r"^\s*y = (.+)$", body.group(0), re.MULTILINE)
    assert mapping, "to_point no longer assigns y from row"
    expression = mapping.group(1)
    namespace_top = {"row": 0.0, "IMG_H": 1540.0, "PLOT_H": 5.4}
    namespace_bottom = {"row": 1540.0, "IMG_H": 1540.0, "PLOT_H": 5.4}
    y_first = eval(expression, {"__builtins__": {}}, namespace_top)  # noqa: S307
    y_last = eval(expression, {"__builtins__": {}}, namespace_bottom)  # noqa: S307
    assert y_first > y_last, (
        f"row 0 renders at y={y_first:g} and the last row at y={y_last:g}, so the first "
        f"row is drawn below the last. Row 0 is the end of the pass and time runs bottom "
        f"to top, so row 0 belongs at the top. Re-render after fixing the mapping."
    )


def test_the_stated_crop_is_the_crop_the_code_computes(source, scene):  # noqa: D401
    """The docstring's two presentational liberties, held to the computed values.

    X_MIN and X_MAX are derived from OFFSET_PX, so a wrong offset silently moves the
    crop as well, and a prose range that no longer matches is the trace it leaves.
    """
    stated = re.search(
        r"frequency axis is cropped to columns (\d+) to (\d+) of (\d+)", source
    )
    assert stated, "the docstring no longer states the crop this test can check"
    columns = [c for _r, c in ast.literal_eval(
        "[" + re.search(r"^PRED = \[(.+?)^\]", source, re.MULTILINE | re.DOTALL).group(1) + "]"
    )]
    offset = float(scene["OFFSET_PX"])
    half = float(scene["HALF_WIDTH_PX"])
    x_min = min(min(columns) + offset - half, min(columns)) - 12.0
    x_max = max(max(columns) + offset + half, max(columns)) + 12.0
    assert int(stated.group(1)) == round(x_min), (
        f"the docstring says the crop starts at column {stated.group(1)} and the code "
        f"computes {x_min:.1f}"
    )
    assert int(stated.group(2)) == round(x_max), (
        f"the docstring says the crop ends at column {stated.group(2)} and the code "
        f"computes {x_max:.1f}"
    )
    width, _height = _image_size(source)
    assert int(stated.group(3)) == width


def test_the_clip_and_its_poster_are_published():
    """A scene that renders and is not published is a scene nobody sees."""
    assert PUBLISHED.is_file(), f"{PUBLISHED} is missing: render and copy the scene"
    assert POSTER.is_file(), f"{POSTER} is missing: a video with no poster loads blank"
    assert PUBLISHED.stat().st_size > 200_000, "the published clip is implausibly small"


def test_the_page_that_embeds_it_names_both_files():
    page = (REPO / "apps/web/app/page.tsx").read_text(encoding="utf-8")
    assert "/media/corridor-explainer.mp4" in page
    assert "/media/corridor-explainer-poster.jpg" in page


def test_the_scene_reads_the_palette_rather_than_hardcoding_it(source):
    """The failure this scene already had once, kept closed."""
    assert "globals.css" in source
    literals = re.findall(r'"#[0-9a-fA-F]{6}"', source)
    assert not literals, f"hardcoded colours in the scene: {literals}"


def test_this_module_pulls_in_neither_the_scene_nor_its_renderer():
    """Parsing, not importing, stated as a test so a later refactor cannot undo it."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    forbidden = sorted(n for n in names if "manim" in n or "explainer" in n)
    assert not forbidden, (
        f"this module imports {forbidden}, which puts a render-time dependency in the "
        f"offline suite. Read the scene's constants as text instead."
    )
