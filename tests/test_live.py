"""The live path measures what gate 3 measured, on gate 3's own observations.

`pipeline/tracetriage/live.py` exists so that someone outside this machine can point
TraceTriage at an observation recorded an hour ago. That only means anything if it is the
same measurement: a second implementation that agrees in shape and drifts in value is
worse than no live path at all, because it publishes numbers under a receipt's reputation.

So the tests here replay the observations the receipt was built from and compare digit for
digit.

**Why the mode measurement is the interesting part.** Gate 3 reads each observation's
CORRECTED / UNCORRECTED verdict from `artifacts/a3_overlays/summary.json`, a file produced
with a human in the loop. A live observation has no such row, so `live.py` measures the
verdict with `doppler_mode.verdict_from_scores`, the same rule that produced those
annotations. A3 scored through its own `normalised_rows`, whose MAD floor of 1e-6
corridor_fit has since replaced with one grey level, so agreement is not a tautology:
these tests are also the check that the corrected floor does not move a verdict.

Markers: `dataset` because the records and images come from a built snapshot, `ocr`
because the frequency axis is read from the rendered tick labels, `slow` because that runs
easyocr over every image in the set.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
A3_SUMMARY = REPO / "artifacts/a3_overlays/summary.json"
GATE3_RECEIPT = REPO / "artifacts/GATE3_RECEIPT.json"

pytestmark = [pytest.mark.dataset, pytest.mark.ocr, pytest.mark.slow]


def _snapshot_dir() -> Path | None:
    env = os.environ.get("TRACETRIAGE_SNAPSHOT")
    for base in ([Path(env)] if env else []) + [Path("D:/tracetriage_data/snap-stage1")]:
        if (base / "pages").is_dir() and (base / "waterfalls").is_dir():
            return base
    return None


SNAP = _snapshot_dir()
requires_snapshot = pytest.mark.skipif(SNAP is None, reason="no built snapshot on disk")


def _load_raw(obs_id: int) -> dict | None:
    for page_file in sorted((SNAP / "pages").glob("*.json")):
        page = json.loads(page_file.read_text(encoding="utf-8"))
        for rec in page if isinstance(page, list) else page.get("results", []):
            if rec.get("id") == obs_id:
                return rec
    return None


@pytest.fixture(scope="module")
def a3_rows() -> list[dict]:
    return json.loads(A3_SUMMARY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def receipt_fits() -> dict[int, dict]:
    receipt = json.loads(GATE3_RECEIPT.read_text(encoding="utf-8"))
    return {
        int(o["obs_id"]): o
        for o in receipt["observations"]
        if o.get("fit") and o["fit"].get("fitted_offset_hz") is not None
    }


@pytest.fixture(scope="module")
def measured(a3_rows) -> dict[int, object]:
    """Every decisive observation, measured once and shared by the tests below.

    Decisive only: the unresolved rows are covered by their own test, which needs no fit
    and so does not pay for the expensive part twice.
    """
    from pipeline.tracetriage import live

    out: dict[int, object] = {}
    for row in a3_rows:
        if row["verdict"] not in ("CORRECTED", "UNCORRECTED"):
            continue
        raw = _load_raw(row["obs_id"])
        img = SNAP / "waterfalls" / f"waterfall_{row['obs_id']}.png"
        if raw is None or not img.exists():
            continue
        # `label_reader="ocr"` and not the live default of "auto". The receipt these tests
        # compare against was produced through easyocr, and the template matcher in
        # `glyph_axis` is a different reader that does not always agree with it: on 14736773
        # easyocr read the centre tick as 562 kHz and the committed axis for that image was
        # derived through that value. Reproducing a receipt means reproducing the inputs it
        # had. `tests/test_glyph_axis.py` is where the two readers are compared, and this
        # module's own reader-agnostic check is the last test below.
        out[row["obs_id"]] = live.measure(raw, img.read_bytes(), label_reader="ocr")
    return out


@requires_snapshot
def test_the_mode_is_measured_not_looked_up(a3_rows, measured):
    """Every decisive verdict A3 recorded is reproduced from the image alone."""
    disagree = []
    for row in a3_rows:
        m = measured.get(row["obs_id"])
        if m is None:
            continue
        if m.mode != row["verdict"]:
            disagree.append(
                f"obs {row['obs_id']}: A3 says {row['verdict']}, live says {m.mode} "
                f"({m.mode_reason}); curved {m.sigma_curved:.2f} against A3's "
                f"{row['sigma_curved']:.2f}"
            )
    assert measured, "no decisive observation was measurable, so this test proved nothing"
    assert not disagree, "the measured mode left A3's annotations:\n" + "\n".join(disagree)


@requires_snapshot
def test_the_hypothesis_scores_survive_the_mad_floor_change(a3_rows, measured):
    """A3's sigmas are reproduced through corridor_fit's normalisation, not A3's.

    A3 divides by `max(mad, 1e-6)`; the live path divides by `max(mad, 1.0)`. Both floors
    are inert on any row with variation, and corridor_fit's docstring puts the smallest
    non-zero row MAD at 2.471, so these figures should be untouched. This test is what
    makes that an observation rather than an argument, and 0.05 sigma is tight enough that
    a real change in the estimator would fail it.
    """
    for row in a3_rows:
        m = measured.get(row["obs_id"])
        if m is None:
            continue
        assert m.sigma_curved == pytest.approx(row["sigma_curved"], abs=0.05), (
            f"obs {row['obs_id']}: curved sigma moved from {row['sigma_curved']} to "
            f"{m.sigma_curved} under the corrected MAD floor"
        )
        assert m.sigma_vertical == pytest.approx(row["sigma_vertical"], abs=0.05)


@requires_snapshot
def test_the_offset_reproduces_the_gate3_receipt(measured, receipt_fits):
    """Digit for digit against the committed receipt, on every observation in both.

    This is the claim the live path rests on. `live.measure` calls `parse_waterfall`,
    `fit_corridor` and `calibrate_against_nulls` in the order `scripts/run_gate3.py` calls
    them, so the numbers are not merely close: they are the same computation reached by a
    different entry point, and a difference in the last decimal place means one of the two
    has a call the other does not.
    """
    checked = 0
    for obs_id, m in measured.items():
        want = receipt_fits.get(obs_id)
        if want is None:
            continue
        fit = want["fit"]
        assert m.offset_hz == pytest.approx(fit["fitted_offset_hz"], rel=1e-9), obs_id
        assert m.offset_ppm == pytest.approx(fit["fitted_offset_ppm"], rel=1e-9), obs_id
        assert m.at_bound == fit["offset_at_bound"], obs_id
        assert m.bound_hz == pytest.approx(fit["offset_bound_hz"], rel=1e-9), obs_id
        assert m.fit_detail["detect_frac"] == pytest.approx(fit["detect_frac"], rel=1e-9)
        assert m.fit_detail["degraded"] == fit["degraded"], obs_id
        checked += 1
    assert checked >= 3, f"only {checked} observations were compared against the receipt"


@requires_snapshot
def test_a_corrected_capture_gets_no_p_value_and_says_so(measured):
    """The flat-corridor case reports its offset and refuses a null comparison.

    Not an edge case: most of A3's decisive observations are corrected, and the first draft
    of `live.py` scored every observation against the corrected corridor, which returned a
    confident-looking offset with `n_nulls: 0` and nothing in the output saying why.
    """
    corrected = [m for m in measured.values() if m.mode == "CORRECTED"]
    assert corrected, "no corrected capture in the set, so this test proved nothing"
    for m in corrected:
        assert m.offset_hz is not None, "a corrected capture still has a measurable offset"
        assert m.p_value is None, "a flat corridor cannot produce a p-value"
        assert m.n_nulls == 0
        assert any("no curve shape to test" in n for n in m.notes), (
            f"obs {m.observation_id} withheld a p-value without saying why: {m.notes}"
        )


@requires_snapshot
def test_an_uncorrected_capture_is_scored_against_its_own_doppler(measured):
    for m in (m for m in measured.values() if m.mode == "UNCORRECTED"):
        assert m.n_nulls and m.n_nulls > 0, "an S-curve has a shape to scramble"
        assert m.p_value is not None
        assert m.doppler_swing_hz and m.doppler_swing_hz > 3000.0, (
            "a verdict was given below the swing floor the rule refuses under"
        )
        assert m.null_detail["margin_over_best_null"] is not None


@requires_snapshot
def test_an_unresolved_observation_returns_rather_than_raises(a3_rows):
    """The empty case is a value, because on a real queue it is most of the queue.

    Most of these observations settle nothing. A tool that raised on those could not rank a
    queue at all, since ranking needs a comparable result for every entry including the
    ones worth skipping. Every measurement field is None rather than 0: a zero offset
    beside a null p-value reads as a confident measurement of no error, which is the
    opposite of what happened.
    """
    from pipeline.tracetriage import live

    unresolved = [r for r in a3_rows if r["verdict"] == "UNRESOLVED"]
    assert unresolved, "the fixture set has no unresolved observation"
    row = unresolved[0]
    raw = _load_raw(row["obs_id"])
    img = SNAP / "waterfalls" / f"waterfall_{row['obs_id']}.png"
    if raw is None or not img.exists():
        pytest.skip("that observation is not in this snapshot")

    m = live.measure(raw, img.read_bytes())
    assert m.mode == "UNRESOLVED"
    assert m.mode_reason
    for name in ("offset_hz", "offset_ppm", "offset_px", "sigma", "p_value", "n_nulls",
                 "at_bound", "fit_detail", "null_detail"):
        assert getattr(m, name) is None, (
            f"{name} carries a value on an observation that settled nothing"
        )
    # The sigmas that explain the refusal are present, so a caller can see how close it
    # came, and the identity block is filled in so the row is still rankable.
    assert m.sigma_curved is not None and m.sigma_vertical is not None
    assert m.observation_id == row["obs_id"]
    assert m.hz_per_px is not None
    assert m.to_dict()["provenance"]["waterfall_sha256"]


@requires_snapshot
def test_the_result_is_json_serialisable_with_every_input_named(measured):
    """A result nobody can re-derive is an assertion, not a measurement."""
    for m in measured.values():
        d = json.loads(json.dumps(m.to_dict()))
        assert d["schema"] == "LIVE_MEASUREMENT"
        prov = d["provenance"]
        assert prov["waterfall_sha256"] and len(prov["waterfall_sha256"]) == 64
        assert prov["observation_api"].startswith("https://network.satnogs.org/api/")
        assert prov["tle1"] and prov["tle2"], "the orbit used is not recoverable"
        assert "CC BY-SA 4.0" in prov["licence"]
        assert set(prov["code"]) >= {"physics", "axis", "mode", "fit", "nulls"}

@requires_snapshot
def test_the_offset_in_pixels_does_not_depend_on_which_reader_read_the_axis(a3_rows):
    """The measurement is one thing and the axis is another, and this separates them.

    Everything the fit does happens in columns of the image: the corridor is mapped from Hz
    into pixels, the search is bounded in pixels, the nulls are scored in pixels. The axis
    enters once, at the end, to turn a column offset into a frequency. So the two label
    readers must agree exactly on `offset_px` and may differ on `offset_hz` by exactly the
    ratio of the two axes they derived, and nothing else.

    Worth pinning because it is the claim that makes a light install honest. If swapping the
    reader moved the pixel offset, the template matcher would be changing the measurement
    rather than only its units, and no tolerance on the Hz value would tell you that.
    """
    from pipeline.tracetriage import live

    compared, drift = 0, []
    for row in a3_rows:
        if row["verdict"] not in ("CORRECTED", "UNCORRECTED"):
            continue
        raw = _load_raw(row["obs_id"])
        img = SNAP / "waterfalls" / f"waterfall_{row['obs_id']}.png"
        if raw is None or not img.exists():
            continue
        data = img.read_bytes()
        try:
            a = live.measure(raw, data, label_reader="ocr", n_nulls=1)
            b = live.measure(raw, data, label_reader="glyph", n_nulls=1)
        except live.LiveRefusal:
            continue
        if a.offset_px is None or b.offset_px is None:
            continue
        compared += 1
        assert a.mode == b.mode, (
            f"obs {row['obs_id']}: the mode changed with the label reader, from {a.mode} to "
            f"{b.mode}. The hypothesis comparison maps the corridor through hz_per_px, so a "
            f"different axis can change it, and that is worth knowing about explicitly."
        )
        assert round(a.offset_px, 6) == round(b.offset_px, 6), (
            f"obs {row['obs_id']}: the column offset moved with the label reader, "
            f"{a.offset_px} against {b.offset_px}. The reader is supposed to change the units "
            f"of the answer and not the answer."
        )
        if a.hz_per_px and b.hz_per_px:
            drift.append(abs(b.hz_per_px / a.hz_per_px - 1.0))

    assert compared >= 3, f"only {compared} observations were measured through both readers"
    # Not asserted as zero: the readers genuinely disagree on some images, and this is the
    # size of it rather than a claim that it does not happen.
    assert max(drift) < 0.01, (
        f"the two readers' axes differ by up to {max(drift) * 100:.2f} percent, which is "
        f"larger than the {1.0:.0f} percent this was measured at and means one of them "
        f"started reading a label wrongly"
    )


def test_every_way_the_null_test_can_not_run_names_itself():
    """Zero nulls has five causes and they do not carry the same weight.

    Two are refusals the method makes on purpose (a corrected capture has no shape to
    scramble; a grazing pass swings too little for a permutation to differ from the
    truth) and three are failures to measure. A caller that sees only `n: 0` cannot
    tell a refusal from a breakage, and could quote a sigma with no p-value and no
    reason for its absence. So every branch that returns zero nulls sets a reason, and
    both places that turn a reason into prose cover all of them.
    """
    from pipeline.tracetriage import live
    from pipeline.tracetriage.cli import _NO_P_VALUE

    src = (
        Path(__file__).resolve().parents[1] / "pipeline/tracetriage/corridor_fit.py"
    ).read_text(encoding="utf-8")
    body = src.split("def calibrate_against_nulls", 1)[1]
    reasons = set(re.findall(r'_empty\((?:[^,]+),\s*"([a-z_]+)"\)', body))
    assert len(reasons) == 4, (
        f"expected four distinct reasons inside calibrate_against_nulls, found "
        f"{sorted(reasons)}. A new branch that returns zero nulls without a reason "
        f"puts a caller back to guessing from n == 0."
    )
    # `mode_unresolved` never reaches corridor_fit: no corridor is selected at all.
    expected = reasons | {"mode_unresolved"}
    assert set(live._NOT_TESTED_READING) == expected, (
        f"live._NOT_TESTED_READING covers {sorted(live._NOT_TESTED_READING)} but the "
        f"code can produce {sorted(expected)}; a missing key raises KeyError while "
        f"serialising a measurement."
    )
    assert set(_NO_P_VALUE) == expected, (
        f"cli._NO_P_VALUE covers {sorted(_NO_P_VALUE)} but the code can produce "
        f"{sorted(expected)}."
    )
    # A refusal and a failure must not read alike, or the distinction is decorative.
    refusals = {"flat_corridor", "swing_below_floor", "mode_unresolved"}
    refusal_words = ("refus", "possible", "reached")
    for key in refusals:
        reading = live._NOT_TESTED_READING[key]
        assert any(word in reading for word in refusal_words), (
            f"{key} is a refusal but its reading does not say so"
        )
    for key in expected - refusals:
        assert "failure" in live._NOT_TESTED_READING[key], (
            f"{key} is a measurement failure but its reading does not say so"
        )


# The checkout-spelling check used to live here and now lives in
# `tests/test_package_imports.py`. This module is marked `ocr` at module scope and every
# gate runs `pytest -m "not network and not ocr and not llm"`, so a check that parses
# source and needs neither a model nor an image never ran in a gate. It found six
# offenders the first time it ran outside that filter.
