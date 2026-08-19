"""The demo script is generated, and its numbers have to come from where it says they do.

The video is public and unversioned. `docs/CLAIM_REGISTER.md` rule 4 records that drift there
cannot be recovered after submission, which makes the shot list the one document in this
repository where a stale number is permanent.

`scripts/sync_demo.py --check` compares the committed page against the generator and cannot
catch the generator, which is the same gap `tests/test_for_judges.py` exists to close for the
judges' page. So the checks here go the other way: every number in a spoken line is re-read
from the artifact that shot cites, by a route that does not import the generator's own
formatting.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_DEMO = _REPO / "docs" / "DEMO_SCRIPT.md"
_ARTIFACTS = _REPO / "artifacts"

#: Numbers that are constraints rather than measurements: the competition's own ceiling, the
#: retake target, and shot ids and cue lengths. They belong to the script, not to a receipt,
#: so a citation check that demanded a receipt for them would be asking for a lie.
_SCRIPT_OWNED = {"180", "165", "3"}


def _load_generator():
    path = _REPO / "scripts" / "sync_demo.py"
    spec = importlib.util.spec_from_file_location("sync_demo", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_generator()


@pytest.fixture(scope="module")
def page() -> str:
    assert _DEMO.exists(), "docs/DEMO_SCRIPT.md is missing. Run scripts/sync_demo.py."
    return _DEMO.read_text(encoding="utf-8")


def _numbers(text: str) -> list[str]:
    """Every numeric token in a line, commas stripped, as written."""
    return [t.replace(",", "") for t in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def _leaves(doc: object):
    if isinstance(doc, dict):
        for value in doc.values():
            yield from _leaves(value)
    elif isinstance(doc, list):
        for value in doc:
            yield from _leaves(value)
    else:
        yield doc


def _appears(number: str, doc: object) -> bool:
    """Whether a quoted number is one of the artifact's own values, at the quoted precision.

    Walking the leaves rather than matching substrings, because a large receipt holds enough
    digits that "appears somewhere in the file" can be satisfied by an unrelated observation
    id. A quoted 1.58 matches a stored 1.5818 because the script rounds; the comparison is
    made at the precision the script quoted, which is the precision a viewer sees.
    """
    if "." in number:
        places = len(number.split(".")[1])
        target = float(number)
        return any(
            isinstance(leaf, (int, float))
            and not isinstance(leaf, bool)
            and round(float(leaf), places) == target
            for leaf in _leaves(doc)
        )
    target_i = int(number)
    for leaf in _leaves(doc):
        if isinstance(leaf, bool):
            continue
        if isinstance(leaf, int) and leaf == target_i:
            return True
        if isinstance(leaf, float) and round(leaf) == target_i and abs(leaf - target_i) < 0.5:
            return True
    # A count of a collection is a number the receipt states without storing, and the
    # dataset manifest's observation count is exactly that.
    return _counts_match(target_i, doc)


def _counts_match(target: int, doc: object) -> bool:
    if isinstance(doc, dict):
        return any(_counts_match(target, v) for v in doc.values())
    if isinstance(doc, list):
        return len(doc) == target or any(_counts_match(target, v) for v in doc)
    return False


def test_the_committed_page_is_what_the_receipts_produce(demo, page: str) -> None:
    assert page == demo.render()


def test_the_page_is_idempotent(demo) -> None:
    assert demo.render() == demo.render()


def test_the_budget_is_under_the_competition_ceiling(demo) -> None:
    """Three minutes is the constraint, and the target holds room for a retake."""
    total = demo.budget()
    assert total == sum(int(s["seconds"]) for s in demo.SHOTS)
    assert total <= demo.TARGET_S < demo.CEILING_S == 180
    assert f"**Budget: {total} seconds of {demo.CEILING_S}.**" in demo.render()


def test_a_shot_list_over_the_target_refuses_to_generate(demo, monkeypatch) -> None:
    """The budget check has to be able to fail, or it is decoration.

    Padding one shot past the target has to stop the generator rather than produce a script
    nobody can record to length.
    """
    padded = [dict(s) for s in demo.SHOTS]
    padded[0]["seconds"] = demo.TARGET_S + 1
    monkeypatch.setattr(demo, "SHOTS", padded)
    with pytest.raises(SystemExit) as raised:
        demo.main([])
    assert "cut a shot" in str(raised.value).lower()


def test_the_flow_is_one_flow_in_the_order_the_guidance_asks_for(demo) -> None:
    """Pitch first, product before the caveats, and the caveats before the close.

    The order was changed once and the reason is worth keeping. The first cut put the
    inconclusive gate verdict third, at 36 seconds, before the queue had been shown. It is
    the same information either way, and a judge who hears "not established" before seeing
    the product hears that the project did not work. It sits after the product now, where
    the same sentence reads as a bound on a thing that visibly works, and the close is what
    makes any of it checkable rather than another verdict.
    """
    ids = [s["id"] for s in demo.SHOTS]
    assert ids == sorted(ids)
    assert demo.SHOTS[0]["beat"] == "The pitch"

    beats = [s["beat"].lower() for s in demo.SHOTS]
    product = next(i for i, b in enumerate(beats) if "queue reorder" in b)
    caveats = next(i for i, b in enumerate(beats) if "does not establish" in b)
    assert product < caveats, (
        "the inconclusive verdicts come before the product, so a judge hears the bound "
        "before seeing the thing it bounds"
    )
    assert caveats < len(beats) - 1, "nothing follows the caveats, so the demo ends on them"
    assert "check" in beats[-1]


@pytest.mark.parametrize("index", range(7), ids=[f"shot{i + 1}" for i in range(7)])
def test_every_number_a_shot_speaks_is_in_the_artifact_it_cites(demo, index: int) -> None:
    """The check the register's rule 4 asks for, applied per shot.

    A shot with numbers and no citation fails here, which is the case that would otherwise
    put an unsourced figure into a public video.
    """
    shot = demo.SHOTS[index]
    quoted = [n for n in _numbers(shot["says"]) if n not in _SCRIPT_OWNED]
    if not quoted:
        return
    assert shot["cites"], f"shot {shot['id']} speaks {quoted} and cites no artifact"
    docs = [
        json.loads((_ARTIFACTS / name.strip().split("/")[-1]).read_text(encoding="utf-8"))
        for name in shot["cites"].split(",")
    ]
    unfound = [n for n in quoted if not any(_appears(n, d) for d in docs)]
    assert not unfound, (
        f"shot {shot['id']} speaks {unfound}, which do not appear in {shot['cites']}"
    )


def test_a_number_moved_in_a_receipt_moves_the_script(demo) -> None:
    """The property the whole file exists for, checked by mutation rather than by reading.

    The generator reads its numbers at import, so this reloads it against a receipt whose
    lift has been changed and asserts the rendered line changed with it.
    """
    before = demo.render()
    receipt = _ARTIFACTS / "QUEUE_RECEIPT.json"
    original = receipt.read_bytes()
    doc = json.loads(original.decode("utf-8"))
    doc["gate6"]["per_split"]["chronological"]["lift_point"] = 9.99
    try:
        receipt.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        mutated = _load_generator().render()
    finally:
        receipt.write_bytes(original)
    assert "9.99 times as many" in mutated
    assert mutated != before
    # And the reload against the restored file gives the committed page back, so this test
    # cannot leave the generator holding a mutated number for whatever runs next.
    assert _load_generator().render() == before
