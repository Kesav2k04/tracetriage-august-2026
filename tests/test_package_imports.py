"""How `pipeline/tracetriage` spells its own imports, and which files are allowed to differ.

The wheel ships `pipeline/tracetriage` as the top-level package `tracetriage`, so `pipeline`
does not exist inside an install and `from pipeline.tracetriage.x import y` raises
ModuleNotFoundError there. That shipped once: `[project.scripts]` was right, the console
script ran, `--help` printed, and `tracetriage triage <id>` from any directory other than the
repository root died with `No module named 'pipeline'`. Nothing caught it because every test
runs with the repository root as the working directory, where the checkout spelling resolves,
and the wheel check only exercised `--help`, which imports none of the measurement path.

Three files are allowed the checkout spelling, and the reason is a LangFlow contract rather
than a convenience. LangFlow serialises a custom component by storing its **source** in the
flow JSON and executing that source on load, with no parent package: a relative import in
that source raises `attempted relative import with no known parent package`, so a component
module has to name an absolute path, and the only absolute path that resolves in the
checkout it runs from is `pipeline.tracetriage`. Two of the three have their source, import
line and all, sitting in a committed flow under `flows/`, which is what makes this an
observation rather than a claim.

Those three are excluded from the wheel by `pyproject.toml`, so nothing that cannot work in
an install is shipped in one. Both halves are checked here, in both directions: an exempt
file that stops being a component, or stops being excluded from the wheel, fails.

This module exists separately from `tests/test_live.py`, which is where the first version of
the check lived. That module is marked `ocr` at module scope, and every gate here runs
`pytest -m "not network and not ocr and not llm"`, so a pure syntax check that needs neither
a model nor an image was excluded from every gate run for as long as it existed. It found six
offenders the first time it was run outside that filter.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "pipeline" / "tracetriage"
FLOWS = REPO / "flows"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_langflow_component(tree: ast.Module) -> bool:
    """Does this module define a subclass of LangFlow's `Component`?

    The base is matched by name, which covers `Component` and `langflow.custom.Component`
    alike. A module that only imports the symbol does not qualify: it has to define a class
    on top of it, because it is the class that LangFlow serialises.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                if name == "Component":
                    return True
    return False


def _checkout_imports(tree: ast.Module) -> list[int]:
    """Line numbers of every absolute `pipeline.` import, including lazy ones in functions."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # `level > 0` is already relative, and `module` is None for `from . import x`.
            if node.level == 0 and (node.module or "").split(".")[0] == "pipeline":
                lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "pipeline":
                    lines.append(node.lineno)
    return lines


def _wheel_excludes() -> list[str]:
    """The wheel target's exclude patterns, read without a TOML parser dependency."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split("[tool.hatch.build.targets.wheel]", 1)[1].split("\n[", 1)[0]
    match = re.search(r"^exclude = \[(.*?)\]", block, flags=re.MULTILINE | re.DOTALL)
    return re.findall(r'"([^"]+)"', match.group(1)) if match else []


EXEMPT = sorted(p for p in PACKAGE.rglob("*.py") if _is_langflow_component(_tree(p)))


def test_no_module_the_wheel_ships_imports_itself_by_the_checkout_name() -> None:
    """The rule, over every module that is not a LangFlow component."""
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path in EXEMPT:
            continue
        for line in _checkout_imports(_tree(path)):
            offenders.append(f"{path.name}:{line}")
    assert offenders == [], (
        "these imports resolve in a checkout and raise ModuleNotFoundError in an install, "
        f"so the console script fails on its first measurement: {offenders}. Use a relative "
        "import (`from .physics import ...`), which is correct in both."
    )


def test_the_exemption_names_something_that_exists() -> None:
    """An exemption with nothing under it is a rule that was quietly switched off."""
    assert len(EXEMPT) == 3, (
        "the exempt set is the LangFlow component modules and there were three of them; "
        f"this checkout finds {[p.name for p in EXEMPT]}"
    )
    for path in EXEMPT:
        assert _checkout_imports(_tree(path)), (
            f"{path.name} is exempt from the checkout-spelling rule and does not use the "
            "checkout spelling, so the exemption is doing nothing and should be removed"
        )


def test_the_exempt_modules_are_the_ones_langflow_executes_on_its_own() -> None:
    """Corroborated from the committed flows rather than from the docstring that says so."""
    embedded = "".join(p.read_text(encoding="utf-8") for p in sorted(FLOWS.glob("*.json")))
    if not embedded:
        pytest.skip("no flows are committed in this checkout, so there is nothing to read")
    corroborated = [
        path.name
        for path in EXEMPT
        if any(
            f"class {node.name}" in embedded
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ClassDef)
        )
    ]
    assert len(corroborated) >= 2, (
        "at most one exempt module has its source in a committed flow, so the reason for "
        f"the exemption is no longer visible in the tree: {corroborated}"
    )
    assert "from pipeline.tracetriage.langchain_tools import" in embedded, (
        "no committed flow carries the checkout spelling, which is the whole reason these "
        "three modules are allowed to use it"
    )


def test_the_wheel_does_not_ship_what_cannot_be_imported_from_it() -> None:
    """Every exempt module is excluded from the wheel, and every exclusion earns its place.

    The exclusion is wider than the exempt set by one file. `langflow_components.py` only
    re-exports the three components and its own imports are relative, so it would import
    cleanly from an install right up to the point where it reaches for three modules the
    install does not have. A re-export of nothing is not worth shipping, so it goes with
    them, and this test allows that only for a file that imports one of the three.
    """
    patterns = _wheel_excludes()
    assert patterns, (
        "the wheel target has no exclude list, so it ships the LangFlow components, whose "
        "imports cannot resolve inside an install"
    )
    excluded = {
        path for pattern in patterns for path in REPO.glob(pattern) if path.suffix == ".py"
    }
    missing = sorted(p.name for p in set(EXEMPT) - excluded)
    assert not missing, (
        f"{missing} use the checkout spelling and the wheel ships them anyway, so importing "
        "them from an install raises ModuleNotFoundError"
    )
    exempt_names = {p.stem for p in EXEMPT}
    for path in sorted(excluded - set(EXEMPT)):
        source = path.read_text(encoding="utf-8")
        assert any(f"{name} import" in source for name in exempt_names), (
            f"{path.name} is kept out of the wheel and does not depend on any of the "
            "LangFlow components, so the exclusion has widened past its reason"
        )
