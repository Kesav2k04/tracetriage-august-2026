"""Every committed artifact has to be JSON, not Python's dialect of it.

`json.dumps` emits the bare tokens `NaN`, `Infinity` and `-Infinity` unless told not to.
None of them is in the JSON grammar. `json.loads` accepts them, so a Python-only project
can carry one for as long as it likes and never find out.

This one carried two. `artifacts/GATE3_POOL.json` held a NaN in the `trace_q75` block for
one observation, `scripts/run_gate3.py` copied it into
`artifacts/GATE3_RECEIPT.json`, and both files became unreadable by `jq`, by a browser's
`JSON.parse`, and by anything else a judge might reasonably reach for. It surfaced only
because the console imports the receipt through a bundler, whose JSON plugin is
strict, and the failure it produced said "Failed to parse JSON file" with no line number.

The whole argument of this project is that a reader can open the receipts and check the
numbers. A receipt that only Python can open does not support that argument, and the
defect is invisible from inside Python, so it needs a test that reads the way an outsider
would.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Where a reader is invited to look. `artifacts/` is what the register cites,
#: `apps/web/public/data/` is what the console serves, and `tests/fixtures/` holds the
#: frozen runs the receipts are published from.
_ROOTS = (
    REPO / "artifacts",
    REPO / "apps" / "web" / "public" / "data",
    REPO / "tests" / "fixtures",
    REPO / "contracts",
)


def _strict(raw: str) -> object:
    """Parse the way a parser that is not Python's would.

    `parse_constant` is called for exactly the three tokens outside the grammar, so
    raising from it turns Python's permissiveness off without reimplementing a parser.
    """

    def reject(token: str) -> object:
        raise ValueError(f"{token} is not JSON")

    return json.loads(raw, parse_constant=reject)


def _every_json() -> list[Path]:
    out: list[Path] = []
    for root in _ROOTS:
        if root.is_dir():
            out.extend(sorted(root.rglob("*.json")))
    return out


def test_there_are_artifacts_to_check():
    """A glob that matched nothing would pass every assertion below."""
    files = _every_json()
    assert len(files) >= 20, (
        f"only {len(files)} JSON files were found under {[str(r) for r in _ROOTS]}. "
        "This test passes trivially on an empty list, so the count is the check."
    )


@pytest.mark.parametrize("path", _every_json(), ids=lambda p: p.name)
def test_the_artifact_parses_under_a_strict_reader(path: Path):
    """No NaN, no Infinity, no -Infinity, anywhere a reader is pointed at."""
    raw = path.read_text(encoding="utf-8")
    try:
        _strict(raw)
    except ValueError as exc:
        # Point at the line, because the bundler error that found this said only
        # "Failed to parse JSON file" and cost an hour.
        lines = [
            f"  line {i}: {ln.strip()[:90]}"
            for i, ln in enumerate(raw.splitlines(), 1)
            if "NaN" in ln or "Infinity" in ln
        ]
        pytest.fail(
            f"{path.relative_to(REPO).as_posix()} is not JSON: {exc}. "
            f"`json.dumps` writes these tokens unless `allow_nan=False`, and "
            f"`json.loads` reads them back, so nothing in Python notices.\n"
            + "\n".join(lines[:10])
        )


def test_the_strict_reader_actually_rejects_what_python_accepts():
    """Without this, a reader that had stopped being strict would report zero failures.

    The exact shape that shipped: a float field holding NaN, nested two deep.
    """
    shipped = '{"observations": [{"a3_reference": {"sigma_curved": NaN}}]}'
    assert json.loads(shipped)["observations"][0]["a3_reference"]["sigma_curved"] != (
        json.loads(shipped)["observations"][0]["a3_reference"]["sigma_curved"]
    ), "Python read it back as a NaN, which is the whole problem"
    with pytest.raises(ValueError):
        _strict(shipped)
    for token in ("Infinity", "-Infinity"):
        with pytest.raises(ValueError):
            _strict(f'{{"x": {token}}}')
