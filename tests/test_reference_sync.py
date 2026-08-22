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
import re
import shutil
import subprocess
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
    """A copy of exactly what the generator reads, and nothing else.

    The first version copied `artifacts/` whole and put `hog_cache/hog.npy` into the system
    temp directory four times over, which filled the disk and errored the suite. The
    generator globs `artifacts/*.json` rather than walking it, and reads only `.py` under
    the source roots, so copying a cache into a test directory was work in service of
    nothing. It also put weights on `C:`, which this project's rules forbid outright.
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    for name in ("scripts", "contracts", "tests", "artifacts"):
        (repo / name).mkdir(parents=True, exist_ok=True)
    (repo / "pipeline" / "tracetriage").mkdir(parents=True)

    for source, pattern in (
        (_REPO / "scripts", "*.py"),
        (_REPO / "contracts", "*.schema.json"),
        (_REPO / "tests", "*.py"),
        (_REPO / "pipeline" / "tracetriage", "*.py"),
    ):
        target = repo / source.relative_to(_REPO)
        for path in source.glob(pattern):
            shutil.copy2(path, target / path.name)

    # Top-level files only. The generator lists these by suffix and never descends.
    for path in (_REPO / "artifacts").iterdir():
        if path.is_file():
            shutil.copy2(path, repo / "artifacts" / path.name)

    shutil.copy2(_REFERENCE, repo / "docs" / "REFERENCE.md")

    # The generator asks git what is published, so the copy has to be a repository. A
    # plain directory would make it refuse, which is correct behaviour and would test
    # nothing about rendering.
    _git_init(repo)
    return repo


def _git_init(repo: Path) -> None:
    """Initialise and stage, so `git ls-files` in the copy answers about the copy."""
    for args in (
        ["init", "-q"],
        ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A"],
    ):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _stage(repo: Path) -> None:
    """Publish whatever has just been written into the copy."""
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True, capture_output=True)


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
    _stage(clone)
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
    _stage(clone)
    assert module.render() != before


def test_a_module_with_no_docstring_is_named_rather_than_blank(clone: Path) -> None:
    """An empty cell reads as "nothing to say". This has to read as "nobody wrote one"."""
    module = _load(clone)
    (clone / "scripts" / "run_undocumented.py").write_text("x = 1\n", encoding="utf-8")
    _stage(clone)
    page = module.render()
    row = next(line for line in page.splitlines() if "run_undocumented.py" in line)
    assert "**no module docstring**" in row


def test_an_artifact_no_module_names_is_reported_as_having_no_builder(clone: Path) -> None:
    """A receipt nothing rebuilds is the artifact D3 was told to look for."""
    module = _load(clone)
    (clone / "artifacts" / "ORPHAN_RECEIPT.json").write_text(
        json.dumps({"schema": "ORPHAN", "schema_version": "0.1.0"}), encoding="utf-8"
    )
    _stage(clone)
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


def test_the_page_names_no_file_a_clone_would_not_have(sync_docs) -> None:
    """The defect a clean clone found, as a check that does not need a clone.

    The first version walked the working tree, so it listed the pickled model, three build
    logs, a rendered evidence card and `corridor_features.json`: six files that exist here
    because they were built once and are not published. A judge's clone regenerated the page
    without them and the committed one no longer matched.
    """
    tracked = sync_docs._tracked()
    page = sync_docs.render()
    named = set(re.findall(r"`([^`]+)`", page))
    candidates = {
        n
        for n in named
        if not n.endswith("/")
        and (
            n.startswith(("artifacts/", "scripts/", "tests/", "pipeline/", "contracts/"))
            or n.endswith((".json", ".py", ".pkl", ".log", ".html"))
        )
    }
    resolved = {n if "/" in n else f"artifacts/{n}" for n in candidates}

    def published(name: str) -> bool:
        """Tracked, or a directory git publishes something out of.

        A directory is never in `tracked`, which lists files, so the first version of this
        called every backticked directory unpublished. `pipeline/tracetriage` in a module
        docstring failed a check about files a clone would not have, while being the
        package the clone is mostly made of. A directory counts as published when git
        carries at least one file under it, which is the same question asked of a path
        that can hold more than one thing.
        """
        if name in tracked:
            return True
        prefix = f"{name}/"
        return any(t.startswith(prefix) for t in tracked)

    unpublished = sorted(
        n
        for n in resolved
        if (_REPO / n).exists() and not published(n) and not n.endswith(".schema.json")
    )
    assert not unpublished, f"the page names files git does not publish: {unpublished}"


def test_a_working_tree_only_file_stays_off_the_page(clone: Path) -> None:
    """And the mutation, because the check above passes on any page that names nothing."""
    module = _load(clone)
    (clone / "artifacts" / "LOCAL_ONLY.json").write_text(
        json.dumps({"schema": "LOCAL_ONLY", "schema_version": "0.1.0"}), encoding="utf-8"
    )
    page = module.render()
    assert "LOCAL_ONLY" not in page
    _stage(clone)
    assert "LOCAL_ONLY" in module.render()


def test_a_tree_git_cannot_answer_about_is_refused(tmp_path: Path) -> None:
    """Falling back to the working tree is the defect, so absence of git is a failure.

    A generator that quietly walked the directory when `git ls-files` failed would put
    the six unpublished files back on the page in exactly the environment least able to
    notice.
    """
    bare = tmp_path / "nogit"
    for name in ("scripts", "contracts", "artifacts", "tests", "docs"):
        (bare / name).mkdir(parents=True)
    (bare / "pipeline" / "tracetriage").mkdir(parents=True)
    shutil.copy2(_REPO / "scripts" / "sync_docs.py", bare / "scripts" / "sync_docs.py")
    module = _load(bare)
    with pytest.raises(SystemExit, match="git ls-files failed"):
        module.render()
