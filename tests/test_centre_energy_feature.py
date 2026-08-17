"""Guards on the centre-energy feature itself, not on the pipeline around it.

A6 shipped with 46 passing tests and a feature that was a constant. The score
was computed as ``1 - strip_mean / full_mean`` and clipped to [0, 1], but on
this corpus that expression is negative for every observation, around -0.11 for
both classes, so the clip pinned all 591 training samples to exactly 0.0. The
model received one input value for every sample, its Brier score landed exactly
on the prior-only floor, and the result was written up as "the feature is not
discriminative on this dataset". The feature had never been computed.

Nothing in the suite caught it, because every test went through the trained
model or the receipt schema and none asked the feature a question it could get
wrong. These do. They run on arrays with a known answer and need no OCR
backend, which is why ``centre_strip_score`` exists as a separate function.
"""

from __future__ import annotations

import numpy as np
import pytest

from pipeline.tracetriage.baseline import centre_strip_score

RNG = np.random.default_rng(20260817)
H, W = 60, 200
CENTRE = W // 2
STRIP = (CENTRE - 6, CENTRE + 7)


def _noise(scale: float = 8.0, base: float = 60.0) -> np.ndarray:
    """A plausible noise-only waterfall crop: flat in frequency, real spread."""
    return (base + RNG.normal(0, scale, size=(H, W))).astype(np.float32)


def _with_carrier(amplitude: float = 40.0, at: int = CENTRE) -> np.ndarray:
    """Noise plus a bright vertical carrier, which is what a signal looks like."""
    arr = _noise()
    arr[:, at - 2:at + 3] += amplitude
    return arr


class TestFeatureIsNotConstant:
    def test_carrier_and_noise_do_not_score_the_same(self):
        """The exact failure that shipped: one value for every input."""
        noise = centre_strip_score(_noise(), *STRIP)
        carrier = centre_strip_score(_with_carrier(), *STRIP)
        assert noise is not None and carrier is not None
        assert carrier != noise, (
            "a centred carrier and pure noise produced the same score, so the "
            "feature carries no information"
        )

    def test_many_inputs_give_many_distinct_scores(self):
        scores = [centre_strip_score(_with_carrier(amplitude=a), *STRIP)
                  for a in (0.0, 5.0, 10.0, 20.0, 40.0, 80.0)]
        assert all(s is not None for s in scores)
        assert len(set(scores)) == len(scores), (
            f"six different carrier strengths produced {len(set(scores))} distinct "
            "scores; the feature is being flattened somewhere"
        )

    def test_score_rises_monotonically_with_carrier_strength(self):
        scores = [centre_strip_score(_with_carrier(amplitude=a), *STRIP)
                  for a in (0.0, 10.0, 20.0, 40.0, 80.0)]
        assert scores == sorted(scores), (
            f"score did not increase with carrier amplitude: {scores}"
        )


class TestSignIsCorrect:
    def test_bright_carrier_scores_higher_than_noise(self):
        """A3 established that a signal is BRIGHT, at 32 to 54 sigma.

        The version this replaced assumed dark = signal and inverted the ratio,
        which is backwards for a SatNOGS waterfall.
        """
        assert centre_strip_score(_with_carrier(), *STRIP) > centre_strip_score(
            _noise(), *STRIP
        )

    def test_a_dark_centre_scores_below_noise(self):
        arr = _noise()
        arr[:, CENTRE - 2:CENTRE + 3] -= 40.0
        assert centre_strip_score(arr, *STRIP) < centre_strip_score(_noise(), *STRIP)


class TestNoBoundedSquashing:
    def test_a_strong_carrier_exceeds_one(self):
        """Pins the clip out. Platt scaling needs the range, not a [0, 1] box."""
        score = centre_strip_score(_with_carrier(amplitude=200.0), *STRIP)
        assert score > 1.0, (
            f"score {score} is inside [0, 1]; a bounded output here is what "
            "destroyed the feature the first time"
        )

    def test_a_dark_centre_can_go_negative(self):
        arr = _noise()
        arr[:, CENTRE - 2:CENTRE + 3] -= 200.0
        score = centre_strip_score(arr, *STRIP)
        assert score < 0.0, (
            f"score {score} was floored at zero; clipping the negative half is "
            "what pinned every observation to a constant"
        )


class TestRowNormalisationDoesItsJob:
    def test_a_vertical_brightness_ramp_barely_moves_the_score(self):
        """Range changes across a pass, so rows differ in brightness.

        Per-row z-scoring is what makes the measurement about frequency rather
        than about how close the satellite was.
        """
        flat = _with_carrier()
        ramped = flat + np.linspace(0, 120, H, dtype=np.float32)[:, None]
        a = centre_strip_score(flat, *STRIP)
        b = centre_strip_score(ramped, *STRIP)
        assert abs(a - b) < 0.05 * max(abs(a), 1.0), (
            f"a vertical ramp moved the score from {a} to {b}; the row "
            "normalisation is not removing the range gradient"
        )

    def test_a_uniform_offset_does_not_change_the_score(self):
        arr = _with_carrier()
        a = centre_strip_score(arr, *STRIP)
        b = centre_strip_score(arr + 50.0, *STRIP)
        assert a == pytest.approx(b, abs=1e-4)

    def test_a_per_row_gain_does_not_change_the_score(self):
        """The property that a difference of raw means does not have.

        Range and receiver gain scale a whole row, signal and noise together.
        Dividing by the row's own MAD makes the score invariant to that;
        subtracting the crop mean from the strip mean does not, and would rank
        two identical passes differently because one was received louder.

        An additive ramp cannot test this: it shifts strip and crop means
        equally, so a raw difference survives it and the guard reads as passing
        while measuring nothing.
        """
        arr = _with_carrier()
        gain = np.linspace(0.5, 3.0, H, dtype=np.float32)[:, None]
        scaled = arr * gain
        a = centre_strip_score(arr, *STRIP)
        b = centre_strip_score(scaled, *STRIP)
        assert a == pytest.approx(b, rel=0.02), (
            f"a per-row gain moved the score from {a} to {b}; the score is "
            "reporting how loud the pass was, not where the energy sat"
        )


class TestItMeasuresTheCentre:
    def test_an_off_centre_carrier_scores_below_a_centred_one(self):
        centred = centre_strip_score(_with_carrier(at=CENTRE), *STRIP)
        off = centre_strip_score(_with_carrier(at=CENTRE + 60), *STRIP)
        assert off < centred, (
            "a carrier well outside the strip scored at least as high as one "
            "inside it, so the strip bounds are not being applied"
        )


class TestDegenerateInputsReturnNone:
    def test_empty_crop(self):
        assert centre_strip_score(np.zeros((0, 0), dtype=np.float32), 0, 1) is None

    def test_inverted_strip_bounds(self):
        assert centre_strip_score(_noise(), 100, 100) is None
        assert centre_strip_score(_noise(), 100, 90) is None
