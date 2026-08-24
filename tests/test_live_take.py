"""The filmed take is what the film says it is.

One beat of the presentation film is footage rather than a drawing: a screen recording of
the deployed console measuring a SatNOGS observation. Footage is the one thing in this
repository that cannot be re-derived from a receipt, so what is pinned here is everything
around it. The video the film plays is the video the receipt hashes. The observation typed
into the console is one this project already published figures for, and those figures are
quoted from the tree rather than copied into the receipt by hand. The agreement table
carries the two quantities that do not match as well as the eight that do.

`scripts/record_live_take.py --check` is the check that owns the digest and the quoted
rows, and it runs offline. What is added here is the part a `--check` cannot assert about
itself: that the comparison covers what the script says it covers, and that the file is
attributable under the same rule every other redistributed image obeys.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "LIVE_TAKE.json"
TAKE = REPO / "apps" / "web" / "public" / "film" / "live-take.mp4"
MANIFEST = REPO / "artifacts" / "DATASET_MANIFEST.json"


@pytest.fixture(scope="module")
def receipt() -> dict:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_the_checker_agrees_with_the_tree() -> None:
    """The script's own offline check, run the way a reader would run it."""
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "record_live_take.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_video_the_film_plays_is_tracked(receipt: dict) -> None:
    assert TAKE.is_file(), "the film references a video that is not in the tree"
    assert receipt["take"]["path"] == TAKE.relative_to(REPO).as_posix()
    assert TAKE.stat().st_size == receipt["take"]["bytes"]


def test_the_observation_is_one_the_manifest_can_attribute(receipt: dict) -> None:
    """The take redistributes SatNOGS pixels, so its observation has to be attributable.

    `scripts/audit_release.py` resolves this file through `_EMBEDDED_OBSERVATION` because
    the filename carries no id. That declaration is only worth anything if the id it
    declares is an observation the manifest holds a licence and a station for.
    """
    ids = {int(o["id"]) for o in json.loads(MANIFEST.read_text(encoding="utf-8"))["observations"]}
    assert receipt["observation"]["id"] in ids


def test_the_agreement_table_covers_every_quantity_the_script_compares(receipt: dict) -> None:
    """The two lists together are the whole comparison, not a selection from it.

    A table that publishes agreements and quietly drops a quantity that stopped agreeing
    would read exactly like a table that agrees. So the count is checked against the
    script's own field lists rather than against a number typed here.
    """
    spec = _load_script()
    expected = len(spec.FIT_FIELDS) + len(spec.FIT_INNER) + 3  # the three mode comparisons
    agreement = receipt["agreement"]
    assert agreement["n_exact"] == len(agreement["exact"])
    assert agreement["n_differs"] == len(agreement["differs"])
    assert agreement["n_exact"] + agreement["n_differs"] == expected


def test_the_fit_reproduces_and_the_difference_is_named(receipt: dict) -> None:
    """The claim the film makes out loud, held to the receipt.

    The film says the offset and the corridor sigma come back as the committed digits. If
    either ever stopped doing that, the line would still be spoken and the card would still
    be drawn, because both read the live figure. This is the assertion that goes red.
    """
    exact = {row["quantity"] for row in receipt["agreement"]["exact"]}
    assert {"offset_hz", "offset_ppm", "sigma"} <= exact
    differs = {row["quantity"] for row in receipt["agreement"]["differs"]}
    assert differs <= {"mode.sigma_curved", "mode.sigma_vertical"}
    assert "mode score" in receipt["agreement"]["reading"]


def test_the_edit_is_declared_in_figures(receipt: dict) -> None:
    """A sped-up recording that does not say so is a claim about how long something took."""
    edit = receipt["take"]["edit"]
    assert edit["takes"] == 1
    assert edit["rate_before_handover"] > 1
    assert edit["rate_after_handover"] > 1
    assert edit["hold_last_frame_s"] > 0


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "record_live_take", REPO / "scripts" / "record_live_take.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module
