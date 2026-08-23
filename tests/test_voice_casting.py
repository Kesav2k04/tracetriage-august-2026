"""The voice the film uses is the voice the measurement chose, and the table proves it.

`artifacts/VOICE_CASTING.json` is a decision record: thirteen candidates, a rule fixed
before the run, and a winner. A record like that has two ways to become decoration. The
`chosen` field can be edited to a voice somebody preferred, leaving the table underneath it
saying something else. And `scripts/render_narration.py` can be pointed at a different voice
by changing one line, leaving the record describing a run that no longer decides anything.

So the winner is recomputed here from the published rows, and the script's own constant is
compared against it. Neither check trusts the `chosen` field.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CASTING = REPO / "artifacts" / "VOICE_CASTING.json"


@pytest.fixture(scope="module")
def casting() -> dict:
    if not CASTING.is_file():
        pytest.skip("this checkout holds no casting record")
    return json.loads(CASTING.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def renderer():
    spec = importlib.util.spec_from_file_location(
        "render_narration", REPO / "scripts" / "render_narration.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because the module declares a dataclass and
    # `dataclasses` resolves field types through `sys.modules`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_film_speaks_in_the_voice_the_measurement_chose(casting, renderer):
    """One line in one script decides this, and nothing else was checking it."""
    assert casting["chosen"] == renderer.VOICE, (
        f"scripts/render_narration.py speaks as {renderer.VOICE} and the casting record "
        f"chose {casting['chosen']}. Either re-run scripts/cast_narration_voice.py or "
        "put the constant back: a voice picked by hand over a table that says otherwise is "
        "the situation this record exists to prevent."
    )


def test_the_winner_is_what_the_rule_gives_when_applied_to_the_rows(casting):
    """Recompute the ranking from the published table rather than reading `chosen`.

    This is the check that makes the record evidence. The rule is four keys in a fixed
    order, so a reader can do this by hand; doing it here means a hand-edited winner, a
    dropped row, or a reordered `ranking` array fails rather than reads plausibly.
    """
    rows = casting["candidates"]
    assert len(rows) == casting["n_candidates"] > 1
    ranked = sorted(
        rows,
        key=lambda r: (
            -r["figures_heard"],
            r["beats_over_card"],
            r["word_error_rate"],
            r["voice"],
        ),
    )
    assert ranked[0]["voice"] == casting["chosen"]
    assert [r["voice"] for r in ranked] == casting["ranking"]
    if casting["runner_up"] is not None:
        assert ranked[1]["voice"] == casting["runner_up"]


def test_the_rule_recorded_is_the_rule_the_script_implements(casting):
    """Two copies of an ordering, compared, because the record quotes it as prose."""
    spec = importlib.util.spec_from_file_location(
        "cast_narration_voice", REPO / "scripts" / "cast_narration_voice.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert casting["rule"] == module.RULE


def test_the_chosen_voice_carries_every_figure_and_overruns_nothing(casting):
    """The two properties the film actually depends on, asserted on the winner alone.

    The rule could in principle elect a voice that drops a figure, if every candidate did.
    That would be a real finding and it must not pass quietly: a film whose narration says
    a number no receipt holds is the failure this whole pipeline exists to prevent.
    """
    winner = next(r for r in casting["candidates"] if r["voice"] == casting["chosen"])
    assert winner["figures_heard"] == winner["figures_total"], (
        f"{winner['voice']} won having missed "
        f"{winner['figures_total'] - winner['figures_heard']} figures, so every candidate "
        "missed at least that many. Shorten the line that carries them rather than "
        "shipping a narration that says a number the receipts do not."
    )
    assert winner["beats_over_card"] == 0
    for beat in winner["beats"]:
        assert beat["fits"], f"{beat['beat']} runs {beat['seconds']}s into the next card"
        assert not beat["figures_missed"], beat


def test_the_table_says_what_it_does_not_measure(casting):
    """An honest decision record names the property it could not rank on.

    Timbre is the thing a listener actually reacts to and nothing here scores it. A record
    that presented a word error rate as "the best voice" would be overclaiming, and the
    docstring of the script that writes this file is where that limit is stated.
    """
    spec = importlib.util.spec_from_file_location(
        "cast_narration_voice", REPO / "scripts" / "cast_narration_voice.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    doc = (module.__doc__ or "").lower()
    assert "timbre" in doc, "the script no longer states which property it cannot rank on"
