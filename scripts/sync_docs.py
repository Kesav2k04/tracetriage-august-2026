"""Regenerate `docs/REFERENCE.md` from the tree: what writes what, and what checks it.

Every other document in this repository that carries numbers is generated. This one carries
structure instead, and structure drifts the same way: a script added in one wave and never
mentioned again, an artifact whose builder was renamed, a contract that no committed receipt
validates against. A judge tracing a number back to the code follows exactly this map, and a
map maintained by hand is stale from the first commit that touches the tree.

Nothing here is typed. Each column is read off the tree:

* the one-line purpose of a module is the first sentence of its own docstring, and a module
  with no docstring is named as such rather than skipped;
* the builder of an artifact is the module whose source contains that filename, which is a
  fact about the code rather than a table someone maintained;
* the contract an artifact validates against is matched by its identifier against the
  receipt's own ``schema`` field, so a receipt naming a schema no contract declares shows up
  as a gap;
* the tests that cover an artifact are the test modules whose source names it.

Run it after adding a script, a receipt or a contract::

    .venv/Scripts/python.exe scripts/sync_docs.py
    .venv/Scripts/python.exe scripts/sync_docs.py --check

``--check`` regenerates into memory and exits 1 on any difference, writing nothing. The
standing gate runs ``--check``, so an undocumented script fails the gate rather than passing
quietly. It is idempotent: a second run writes identical bytes, and
``tests/test_reference_sync.py`` asserts that against a mutation rather than against a claim.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
ARTIFACTS = REPO / "artifacts"
CONTRACTS = REPO / "contracts"
SCRIPTS = REPO / "scripts"
PACKAGE = REPO / "pipeline" / "tracetriage"
TESTS = REPO / "tests"
#: The console's browser probes. Not Python, and one of them writes a receipt.
WEB_AUDIT = REPO / "apps" / "web" / "audit"
REFERENCE = REPO / "docs" / "REFERENCE.md"

#: Fixture dumpers rather than pipeline stages. They write into tests/fixtures and are run
#: by hand once; documenting them beside the pipeline would suggest a judge should run them.
_SKIP_SCRIPT_NAMES = {"_inspect_fixtures.py", "dump_ocr_fixture.py"}

#: Files under artifacts/ that are logs, caches or rendered output rather than receipts. They
#: are named in the document rather than given rows, because they carry no schema to report.
_NOT_RECEIPTS = (".log", ".pkl", ".html")


def _first_sentence(text: str | None) -> str:
    """The first sentence of a docstring, collapsed to one line.

    A module with no docstring returns a named absence rather than an empty cell, because an
    empty cell in a generated table reads as "nothing to say" and this means "nobody wrote
    one".
    """
    if not text:
        return "**no module docstring**"
    first = text.strip().split("\n\n")[0]
    first = " ".join(first.split())
    match = re.match(r"^(.+?[.!?])(\s|$)", first)
    sentence = match.group(1) if match else first
    return sentence.replace("|", "\\|")


def _docstring(path: pathlib.Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # a file that will not parse cannot be documented from
        return f"**does not parse: {exc.msg}**"
    return _first_sentence(ast.get_docstring(tree))


def _modules(root: pathlib.Path, tracked: set[str]) -> list[pathlib.Path]:
    return sorted(
        (
            p
            for p in root.glob("*.py")
            if p.name not in _SKIP_SCRIPT_NAMES
            and not p.name.startswith("__")
            and _rel(p) in tracked
        ),
        key=lambda p: p.as_posix(),
    )


def _sources(tracked: set[str]) -> dict[pathlib.Path, str]:
    """Every published source that could name an artifact, read once.

    Python under `scripts/`, the package and `tests/`, plus the console's browser probes under
    `apps/web/audit/`. That last root is here because a builder does not have to be Python:
    `apps/web/audit/offline-probe.mjs` writes `artifacts/OFFLINE_RECEIPT.json`, and with only
    the three Python roots scanned this page reported that receipt under "nothing here rebuilds
    them", which is a published statement that a tracked, committed generator does not exist.
    """
    out: dict[pathlib.Path, str] = {}
    for root in (SCRIPTS, PACKAGE, TESTS):
        for path in sorted(root.rglob("*.py"), key=lambda p: p.as_posix()):
            if _rel(path) in tracked:
                out[path] = path.read_text(encoding="utf-8")
    for pattern in ("*.mjs", "*.js"):
        for path in sorted((WEB_AUDIT).glob(pattern), key=lambda p: p.as_posix()):
            if _rel(path) in tracked:
                out[path] = path.read_text(encoding="utf-8")
    return out


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(REPO).as_posix()


def _tracked() -> set[str]:
    """Every path git publishes, as repo-relative posix strings.

    The page describes what a judge gets, and a judge gets the tracked tree. The first
    version walked the working tree instead and listed the pickled model, three build
    logs, a rendered evidence card and corridor_features.json: six files that exist only
    because they were built here once. A clean clone regenerated the page without them,
    the committed one no longer matched, and that is how it was found.

    Git being unavailable is a named failure rather than a fallback to the working tree,
    because the fallback is exactly the defect.
    """
    proc = subprocess.run(["git", "ls-files"], cwd=str(REPO), capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            "git ls-files failed, so this cannot tell a published file from a local one. "
            "It refuses rather than describing the working tree, because a page listing "
            "files a clone does not have is worse than no page."
        )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def _untracked_under(roots: tuple[pathlib.Path, ...]) -> list[str]:
    """Present here and not published. Printed for the local reader, never rendered."""
    proc = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", *(str(r) for r in roots)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    return sorted(line.strip() for line in proc.stdout.splitlines() if line.strip())


def _writers(name: str, sources: dict[pathlib.Path, str]) -> list[str]:
    """The non-test modules whose source names this artifact.

    Naming a file is not the same as writing it, and this does not pretend otherwise: a
    reader who follows the link sees whether the module writes it or reads it. What the check
    buys is the other direction, which is the one that goes stale. An artifact no module
    mentions at all has no builder in this repository, and the row says so in those words.
    """
    return sorted(
        _rel(p) for p, text in sources.items() if TESTS not in p.parents and name in text
    )


def _tests_naming(name: str, sources: dict[pathlib.Path, str]) -> list[str]:
    return sorted(p.name for p, text in sources.items() if TESTS in p.parents and name in text)


def _contracts(tracked: set[str]) -> list[dict]:
    out = []
    for path in sorted(CONTRACTS.glob("*.schema.json"), key=lambda p: p.as_posix()):
        if _rel(path) not in tracked:
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        out.append({"path": path, "doc": doc, "id": str(doc.get("$id", path.stem))})
    return out


def _artifact_rows(sources: dict[pathlib.Path, str], tracked: set[str]) -> list[dict]:
    rows = []
    contracts = _contracts(tracked)
    # Sorted by the POSIX string rather than by the Path, because comparing Path objects
    # is case-insensitive on Windows and case-sensitive on POSIX. artifacts/ holds one
    # lowercase name among uppercase ones, corridor_features.json, so this page listed it
    # first when generated on Windows and last when generated on Linux. Same rows, same
    # digests, different order, and the standing --check gate failed on CI for twenty runs
    # with a diff that showed two identical lines. The key makes the order a property of
    # the names instead of a property of the machine.
    for path in sorted(ARTIFACTS.glob("*.json"), key=lambda p: p.as_posix()):
        if _rel(path) not in tracked:
            continue
        raw = path.read_bytes()
        try:
            doc = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            doc = None
        schema = doc.get("schema") if isinstance(doc, dict) else None
        version = doc.get("schema_version") if isinstance(doc, dict) else None
        contract = next(
            (
                _rel(entry["path"])
                for entry in contracts
                if schema and entry["id"].split("/")[-1] == str(schema).lower()
            ),
            None,
        )
        rows.append(
            {
                "name": path.name,
                "schema": str(schema) if schema else "none declared",
                "version": str(version) if version else "n/a",
                "contract": contract,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest()[:16],
                "writers": _writers(path.name, sources),
                "tests": _tests_naming(path.name, sources),
            }
        )
    return rows


def _test_rows(tracked: set[str]) -> list[dict]:
    rows = []
    for path in sorted(TESTS.glob("test_*.py"), key=lambda p: p.as_posix()):
        if _rel(path) not in tracked:
            continue
        text = path.read_text(encoding="utf-8")
        rows.append(
            {
                "name": path.name,
                "n": len(re.findall(r"^\s*(?:async )?def test_", text, re.MULTILINE)),
                "purpose": _docstring(path),
            }
        )
    return rows


def _table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _listing(names: list[str]) -> str:
    return ", ".join(f"`{n}`" for n in names) + "." if names else "none."


def render() -> str:
    """The whole page, as a string. Writing it is a separate step so --check can compare."""
    tracked = _tracked()
    sources = _sources(tracked)
    artifacts = _artifact_rows(sources, tracked)
    tests = _test_rows(tracked)
    contracts = _contracts(tracked)
    n_tests = sum(r["n"] for r in tests)
    other = sorted(
        p.name
        for p in ARTIFACTS.iterdir()
        if p.is_file() and p.suffix in _NOT_RECEIPTS and _rel(p) in tracked
    )
    unbuilt = [r["name"] for r in artifacts if not r["writers"]]
    untested = [r["name"] for r in artifacts if not r["tests"]]

    parts = [
        "# Reference",
        "",
        "<!-- Generated by scripts/sync_docs.py from the tree. Do not edit by hand: every cell",
        "     is read off a docstring, a receipt or a source file, and the standing gate runs",
        "     the generator with --check. -->",
        "",
        "What writes what, what validates it, and what checks it. Nothing on this page is",
        "typed. The purpose column is the first sentence of a module's own docstring, the",
        "builder column is the module whose source names the file, and the contract column is",
        "matched by identifier against the receipt's own `schema` field.",
        "",
        "It describes the **tracked** tree, which is what a clone gets. A file present in",
        "a working copy and not published does not appear here, because a page listing",
        "files a judge does not have is worse than no page.",
        "",
        (
            f"At this commit: {len(artifacts)} JSON artifacts, {len(contracts)} contracts, "
            f"{len(_modules(SCRIPTS, tracked))} scripts, "
            f"{len(_modules(PACKAGE, tracked))} package modules and "
            f"{n_tests} test functions across {len(tests)} test modules. Parametrised "
            "functions collect as more than one case, so pytest's collected count is higher."
        ),
        "",
        "## Artifacts",
        "",
        "`sha256` is the first 16 hex characters of the committed bytes, so a receipt rebuilt",
        "without regenerating this page fails `--check` rather than sitting here describing a",
        "file that no longer exists in that form.",
        "",
        _table(
            [
                "Artifact",
                "Schema",
                "Version",
                "Contract",
                "Bytes",
                "sha256",
                "Named by",
                "Named in tests",
            ],
            [
                [
                    f"`{r['name']}`",
                    r["schema"],
                    r["version"],
                    f"`{r['contract']}`" if r["contract"] else "none",
                    f"{r['bytes']:,}",
                    f"`{r['sha256']}`",
                    ", ".join(f"`{w}`" for w in r["writers"]) or "**nothing names it**",
                    ", ".join(f"`{t}`" for t in r["tests"]) or "**none**",
                ]
                for r in artifacts
            ],
        ),
        "",
        "Files under `artifacts/` that are logs, caches or rendered output rather than "
        "receipts, and so carry no schema: " + _listing(other),
        "",
        "Receipts no module in this repository names, which means nothing here rebuilds them: "
        + _listing(unbuilt),
        "",
        "Receipts no test names: " + _listing(untested),
        "",
        "## Contracts",
        "",
        _table(
            ["Contract", "Title", "Status", "Version"],
            [
                [
                    f"`{_rel(entry['path'])}`",
                    str(entry["doc"].get("title", "**no title**")),
                    str(entry["doc"].get("status", "**no status**")),
                    str(entry["doc"].get("version", "**no version**")),
                ]
                for entry in contracts
            ],
        ),
        "",
        "## Package modules",
        "",
        _table(
            ["Module", "What it is"],
            [[f"`{_rel(p)}`", _docstring(p)] for p in _modules(PACKAGE, tracked)],
        ),
        "",
        "## Scripts",
        "",
        _table(
            ["Script", "What it does"],
            [[f"`{_rel(p)}`", _docstring(p)] for p in _modules(SCRIPTS, tracked)],
        ),
        "",
        "## Tests",
        "",
        _table(
            ["Module", "Tests", "What it pins"],
            [[f"`tests/{r['name']}`", str(r["n"]), r["purpose"]] for r in tests],
        ),
        "",
    ]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate docs/REFERENCE.md from the tree.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate into memory and compare against docs/REFERENCE.md, writing nothing",
    )
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        if not REFERENCE.exists():
            print("docs/REFERENCE.md does not exist. Run scripts/sync_docs.py.")
            return 1
        current = REFERENCE.read_text(encoding="utf-8")
        if current == rendered:
            print(f"docs/REFERENCE.md is current: {len(rendered.splitlines())} lines")
            return 0
        print("docs/REFERENCE.md is stale. Run scripts/sync_docs.py.")
        for i, (c, e) in enumerate(
            zip(current.splitlines(), rendered.splitlines(), strict=False), start=1
        ):
            if c != e:
                print(f"  first difference, line {i}:")
                print(f"    committed: {c[:120]}")
                print(f"    the tree:  {e[:120]}")
                break
        else:
            print(
                f"  the committed page has {len(current.splitlines())} lines and the tree "
                f"produces {len(rendered.splitlines())}"
            )
        return 1

    REFERENCE.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"docs/REFERENCE.md synced: {len(rendered.splitlines())} lines")
    loose = _untracked_under((ARTIFACTS, SCRIPTS, PACKAGE, TESTS, CONTRACTS))
    if loose:
        print(
            f"  {len(loose)} file(s) present here and not published, so absent from the "
            "page: " + ", ".join(loose[:8]) + (" ..." if len(loose) > 8 else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
