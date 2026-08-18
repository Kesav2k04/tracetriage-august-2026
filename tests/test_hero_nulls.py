"""The opening frame draws the nulls that were scored, and this is the proof.

`artifacts/HERO_NULLS.json` exists so the console can draw gate 3's null corridors
without recomputing them, and the whole value of drawing them is that they are the
measured ones. A frame that drew plausible-looking scribbles instead would be the
exact move this project criticises elsewhere: a picture standing in for a
measurement.

So the artifact is checked against `artifacts/GATE3_RECEIPT.json` here, not only
inside the generator. The generator can be edited; this cannot be satisfied by
editing it.

These run offline against two committed artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HERO = REPO / "artifacts" / "HERO_NULLS.json"
RECEIPT = REPO / "artifacts" / "GATE3_RECEIPT.json"


@pytest.fixture(scope="module")
def hero() -> dict:
    return json.loads(HERO.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gate3(hero) -> dict:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    row = next(o for o in receipt["observations"] if o["obs_id"] == hero["obs_id"])
    return row


def test_the_distribution_matches_the_receipt(hero, gate3):
    """Seven statistics, each against the gate's own receipt."""
    want = gate3["null_calibration"]
    got = hero["distribution"]
    for key in ("n_nulls", "n_at_least", "p_value"):
        assert got[key] == want[key], key
    assert got["max"] == pytest.approx(want["null_max"], abs=1e-6)
    assert got["median"] == pytest.approx(want["null_median"], abs=1e-6)
    assert got["p95"] == pytest.approx(want["null_p95"], abs=1e-6)
    assert hero["true"]["sigma"] == pytest.approx(want["true_sigma"], abs=1e-6)


def test_the_drawn_observation_is_one_gate_3_could_test(hero, gate3):
    """A corrected corridor is identically 0 Hz and has no shape to scramble.

    Drawing nulls for one would show two hundred copies of the same vertical line
    and claim it as evidence. `run_gate3.py` refuses to score those, and the frame
    must not draw one either.
    """
    assert gate3["testable"] is True
    assert gate3["not_testable_reason"] is None
    assert gate3["corridor_span_hz"] > 0


def test_the_true_corridor_beat_every_null_that_is_drawn(hero):
    """The claim on screen is that none of them reached it. Check the drawn set."""
    assert all(n["sigma"] < hero["true"]["sigma"] for n in hero["drawn"])
    assert hero["distribution"]["n_at_least"] == 0


def test_the_closest_null_is_on_screen(hero):
    """Exactly one drawn path is the best null, and it is the best one there is.

    A frame that showed six easy nulls and quietly dropped the one that came
    closest would be arranging the evidence. The generator marks it; this checks
    the mark is on the right path and that its sigma is the distribution maximum.
    """
    best = [n for n in hero["drawn"] if n["is_best_null"]]
    assert len(best) == 1
    assert best[0]["sigma"] == pytest.approx(hero["distribution"]["max"], abs=1e-6)
    assert best[0]["sigma"] == max(n["sigma"] for n in hero["drawn"])


def test_every_path_has_a_point_for_every_row(hero):
    """A short path would draw a corridor that stops partway up the pass."""
    n = len(hero["rows"])
    assert n > 100, n
    assert len(hero["true"]["px"]) == n
    for path in hero["drawn"]:
        assert len(path["px"]) == n, path["seed"]


def test_paths_stay_inside_the_frame(hero):
    """Columns outside the image would be clipped, and a clipped null looks tame."""
    width = hero["image"]["width"]
    for path in hero["drawn"] + [hero["true"]]:
        assert min(path["px"]) >= 0
        assert max(path["px"]) <= width


def test_rows_are_inside_the_cropped_image_not_the_source_png(hero):
    """The coordinate space is the crop, and getting this wrong is silent.

    A first version of the exporter used the source PNG's height where the card
    uses the cropped plot region. The curves disagreed by 235.7 px, which is 29 kHz
    against a 17.3 kHz Doppler swing, and it would not have looked obviously wrong.
    """
    height = hero["image"]["height"]
    source = hero["image"]["source_png"]
    assert height < source["height"], "the crop must be shorter than the source"
    assert max(hero["rows"]) < height
    assert hero["transform_residual_px"] < 0.5


def test_the_nulls_are_not_all_the_same_path(hero):
    """A permutation that did nothing would make the whole frame vacuous.

    This is the shape of the bug that made gate 3's corrected observations
    untestable: scrambling a flat corridor reproduces it exactly, so truth and null
    agreed to every decimal and the comparison measured nothing.
    """
    signatures = {tuple(n["px"]) for n in hero["drawn"]}
    assert len(signatures) == len(hero["drawn"])
    assert tuple(hero["true"]["px"]) not in signatures


def test_the_drawn_nulls_span_the_distribution(hero):
    """The written set is a spread, not the six weakest nulls.

    The selection is documented as an even spread across the sigma-sorted nulls
    plus the best one, so the drawn sigmas should reach both ends of the measured
    range rather than clustering at the bottom.
    """
    sigmas = sorted(n["sigma"] for n in hero["drawn"])
    assert sigmas[-1] == pytest.approx(hero["distribution"]["max"], abs=1e-6)
    # The lowest drawn null should sit below the median of all 200, which is what
    # an even spread guarantees and a top-slice selection would not.
    assert sigmas[0] < hero["distribution"]["median"]


def test_the_caption_numbers_come_from_the_gate_receipt(hero):
    """The plate's limitation sentence is generated, and this is what makes it so.

    It read "all three testable observations discriminate ... the exact one-sided 95%
    lower bound on three of three is 0.368" as literal prose, with nothing reading
    either number. SPACE-B4 proposes adding `margin_over_best_null` to the
    `discriminates` criterion, which can drop an observation from that count. The
    sentence would have become false with every test still green.
    """
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    g = hero["gate"]
    assert g["verdict"] == receipt["verdict"]
    assert g["threshold"] == receipt["threshold"]
    assert g["observations_scored"] == receipt["observations_scored"]
    assert g["observations_testable"] == receipt["observations_testable"]
    assert g["observations_decisive"] == receipt["observations_decisive"]
    assert g["discriminating_rate"] == pytest.approx(receipt["discriminating_rate"])
    assert g["rate_lower_bound_95"] == pytest.approx(receipt["rate_lower_bound_95"])
    assert g["observations_discriminating"] == sum(
        1 for o in receipt["observations"] if o["null_calibration"]["discriminates"]
    )


def test_the_discriminating_count_cannot_exceed_the_scored_count(hero):
    """A caption reading "4 of 3" is the shape a wrong denominator takes."""
    g = hero["gate"]
    assert 0 <= g["observations_discriminating"] <= g["observations_scored"]
    assert g["observations_scored"] <= g["observations_testable"]
    assert g["observations_testable"] <= g["observations_decisive"]


def test_the_published_verdict_follows_from_the_bound(hero):
    """PASSED requires the lower bound to clear the bar, not the point estimate."""
    g = hero["gate"]
    if g["verdict"] == "PASSED":
        assert g["rate_lower_bound_95"] >= g["threshold"]
    else:
        assert g["rate_lower_bound_95"] < g["threshold"]
