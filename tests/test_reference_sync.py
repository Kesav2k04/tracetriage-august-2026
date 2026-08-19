"""`docs/REFERENCE.md` is generated, and the generator has to notice things changing.

Two properties, and the second is the one that matters. Idempotence: a second run writes
identical bytes, which is the claim the C7f entry records the first generated document
failing. And sensitivity: adding a script, renaming an artifact or dropping a docstring has
to move the page, because a generator whose output does not depend on its input is a check
that cannot fail, and this project has shipped one of those before.

The mutations here are made in a copy of the tree rather than in the repository, so a failing
run leaves nothing behind.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_REFERENCE = _REPO / "docs" / "REFERENCE.md"


def _load(repo: Path):
    """Import `sync_docs` with its module-level paths rebound to `repo`.

    The script resolves everything from its own location, so a copied tree gives a copied
    generator with no parameter threading and no risk of a test writing into the repository.
    """
    path = repo / "scripts" / "sync_docs.py"
    spec = importlib.util.spec_from_file_location(f"sync_docs_{repo.name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_docs():
    return _load(_REPO)


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A copy of the parts of the tree the generator reads."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    for name in ("scripts", "contracts", "artifacts", "tests"):
        shutil.copytree(_REPO / name, repo / name, dirs_exist_ok=True)
    shutil.copytree(
        _REPO / "pipeline" / "tracetriage", repo / "pipeline" / "tracetriage", dirs_exist_ok=True
    )
    shutil.copy2(_REFERENCE, repo / "docs" / "REFERENCE.md")
    return repo


def test_the_committed_page_is_what_the_tree_produces(sync_docs) -> None:
    """The standing gate runs --check; this is the same assertion inside the suite."""
    assert _REFERENCE.exists(), "docs/REFERENCE.md is missing. Run scripts/sync_docs.py."
    assert _REFERENCE.read_text(encoding="utf-8") == sync_docs.render()


def test_the_page_is_idempotent(sync_docs) -> None:
    """Two renders of an unchanged tree are the same bytes."""
    assert sync_docs.render() == sync_docs.render()


def test_a_new_script_changes_the_page(clone: Path) -> None:
    """The gap the page exists to close: a script nobody documented."""
    module = _load(clone)
    before = module.render()
    (clone / "scripts" / "run_something_new.py").write_text(
        '"""A script added in a later wave and mentioned nowhere else."""\n',
        encoding="utf-8",
    )
    after = module.render()
    assert after != before
    assert "run_something_new.py" in after
    assert "A script added in a later wave" in after


def test_a_rebuilt_receipt_changes_the_page(clone: Path) -> None:
    """The digest column is what makes a silently rebuilt artifact visible."""
    module = _load(clone)
    before = module.render()
    receipt = clone / "artifacts" / "QUEUE_RECEIPT.json"
    doc = json.loads(receipt.read_text(encoding="utf-8"))
    doc["a_field_that_was_not_there"] = True
    receipt.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    assert module.render() != before


def test_a_module_with_no_docstring_is_named_rather_than_blank(clone: Path) -> None:
    """An empty cell reads as "nothing to say". This has to read as "nobody wrote one"."""
    module = _load(clone)
    (clone / "scripts" / "run_undocumented.py").write_text("x = 1\n", encoding="utf-8")
    page = module.render()
    row = next(line for line in page.splitlines() if "run_undocumented.py" in line)
    assert "**no module docstring**" in row


def test_an_artifact_no_module_names_is_reported_as_having_no_builder(clone: Path) -> None:
    """A receipt nothing rebuilds is the artifact D3 was told to look for."""
    module = _load(clone)
    (clone / "artifacts" / "ORPHAN_RECEIPT.json").write_text(
        json.dumps({"schema": "ORPHAN", "schema_version": "0.1.0"}), encoding="utf-8"
    )
    page = module.render()
    row = next(line for line in page.splitlines() if "ORPHAN_RECEIPT.json" in line)
    assert "**nothing names it**" in row
    assert "nothing here rebuilds them: `ORPHAN_RECEIPT.json`" in page


def test_a_receipt_whose_schema_no_contract_declares_shows_as_none(sync_docs) -> None:
    """The contract column is matched, not asserted, so a gap is visible rather than assumed.

    Three of the release-audit receipts have no contract file, and the page says `none` for
    them rather than leaving the cell empty or inventing a match.
    """
    page = sync_docs.render()
    row = next(line for line in page.splitlines() if "`SECRET_SCAN.json`" in line)
    assert "| none |" in row
