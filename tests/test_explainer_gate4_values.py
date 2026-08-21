"""Every number the gate 4 clip shows, checked against the receipt it came from.

The scene duplicates its values rather than importing them, for a reason stated in its
own docstring: it has to keep rendering from a checkout with no receipts built. The cost
of that decision is this file. Without it the clip is the one place on the site where a
number can drift from its receipt and nothing notices, and it is a place a reader cannot
diff: a video is 2 MB of H.264 and a stale figure in it survives every check the console
has.

The video is also the hardest artefact here to regenerate, which is exactly why the test
matters. If it fails, the fix is to re-render, not to edit the constant.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCENE = REPO / "scripts/explainer_gate4.py"
RECEIPT = REPO / "artifacts/GATE4_RECEIPT.json"
WORKSHEET = REPO / "artifacts/GATE4_WORKSHEET.json"
BUNDLE = REPO / "artifacts/GATE4_BUNDLE.json"
PUBLISHED = REPO / "apps/web/public/media/gate4-explainer.mp4"
POSTER = REPO / "apps/web/public/media/gate4-explainer-poster.jpg"


def _constants() -> dict[str, str]:
    """The scene's module-level constants, read as text.

    Parsed rather than imported: importing the scene imports manim, which is not a
    dependency of the offline suite and does not need to be for this check. The
    constants are the contract, and they are plain literals on purpose.
    """
    source = SCENE.read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Z][A-Z0-9_]*) = (.+?)$", source, re.MULTILINE))


@pytest.fixture(scope="module")
def scene() -> dict[str, str]:
    return _constants()


@pytest.fixture(scope="module")
def arm() -> dict:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if "arm" not in receipt:
        pytest.skip(
            "GATE4_RECEIPT.json carries no arm, so there is no review for the clip to "
            "be checked against. Skipped rather than failed: an unrun gate is a state "
            "this project publishes, not a broken test."
        )
    return receipt["arm"]


def test_the_headline_numbers_are_the_receipt_s(scene, arm):
    assert int(scene["DECISIVE"]) == arm["decisive"]
    assert int(scene["N_OBSERVATIONS"]) == arm["observations_scored"]
    assert float(scene["RATE"]) == pytest.approx(arm["rate"], abs=5e-5)
    assert float(scene["LOWER"]) == pytest.approx(arm["rate_lower_bound_95"], abs=5e-5)
    assert float(scene["UPPER"]) == pytest.approx(arm["rate_upper_bound_95"], abs=5e-5)


def test_the_intra_rater_pair_count_is_the_receipt_s(scene, arm):
    intra = arm["intra_rater"]
    assert int(scene["INTRA_IDENTICAL"]) == intra["identical_on_all_three_axes"]
    assert int(scene["INTRA_PAIRS"]) == intra["repeated_pairs_scored"]


def test_the_clip_says_who_reviewed_and_says_it_correctly(scene, arm):
    """The one claim in the clip that decides how the rest of it should be read."""
    assert scene["REVIEWER_KIND"].strip('"') == arm["reviewer"]["kind"]
    source = SCENE.read_text(encoding="utf-8")
    assert "Gate 4: OPEN" in source, (
        "the clip must end on the gate being open. A version that ends on the rate is "
        "the most misleading thirty-seven seconds this site could serve."
    )


def test_the_sample_shape_is_the_committed_worksheet_s(scene):
    manifest = json.loads(WORKSHEET.read_text(encoding="utf-8"))
    assert int(scene["N_ITEMS"]) == manifest["items"]
    assert int(scene["N_OBSERVATIONS"]) == manifest["unique_observations"]
    assert int(scene["N_REPEATS"]) == manifest["repeated_observations"]
    assert float(scene["THRESHOLD"]) == manifest["threshold"]


def test_the_commitment_shown_on_screen_is_a_real_one(scene):
    """Not a plausible string of hex.

    The clip's subject is a project that does not fabricate values, so a fabricated
    digest in it would undo the point of showing one at all.
    """
    manifest = json.loads(WORKSHEET.read_text(encoding="utf-8"))
    item = scene["SAMPLE_ITEM"].strip('"')
    prefix = scene["SAMPLE_COMMITMENT"].strip('"')
    row = next((r for r in manifest["commitments"] if r["item"] == item), None)
    assert row is not None, f"{item} is not in the committed manifest"
    assert row["commitment"].startswith(prefix), (
        f"the clip shows {prefix} for {item} and the manifest commits to "
        f"{row['commitment'][: len(prefix)]}"
    )


def test_the_commitment_count_is_the_one_the_packer_verified(scene):
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    assert int(scene["COMMITMENTS_CHECKED"]) == bundle["commitments_checked"]


def test_the_clip_and_its_poster_are_published():
    """A scene that renders and is not published is a scene nobody sees."""
    assert PUBLISHED.is_file(), f"{PUBLISHED} is missing: render and copy the scene"
    assert POSTER.is_file(), f"{POSTER} is missing: a video with no poster loads blank"
    assert PUBLISHED.stat().st_size > 200_000, "the published clip is implausibly small"


def test_the_page_that_embeds_it_names_both_files():
    page = (REPO / "apps/web/app/evaluation/page.tsx").read_text(encoding="utf-8")
    assert "/media/gate4-explainer.mp4" in page
    assert "/media/gate4-explainer-poster.jpg" in page
    assert 'preload="none"' in page, (
        "the clip must not be fetched by a reader who does not play it"
    )


def test_the_scene_reads_the_palette_rather_than_hardcoding_it():
    """The failure the corridor scene already had, and the reason this one cannot."""
    source = SCENE.read_text(encoding="utf-8")
    assert "globals.css" in source
    literals = re.findall(r'"#[0-9a-fA-F]{6}"', source)
    assert not literals, f"hardcoded colours in the scene: {literals}"


def test_this_module_pulls_in_neither_the_scene_nor_its_renderer():
    """Parsing, not importing, stated as a test so a later refactor cannot undo it.

    Importing the scene to read its constants would pull manim into the offline suite,
    and manim is a render-time dependency: a clean clone runs the suite and does not
    render video.

    Checked against this file's own import statements rather than against its text. Two
    earlier drafts got this wrong in the two available ways. One asserted
    `"manim" not in sys.modules or True`, a tautology that passes with the import in
    place. The other searched this file's source for the import as a string, which found
    the string inside its own assertion and failed on a file that was correct.
    """
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
