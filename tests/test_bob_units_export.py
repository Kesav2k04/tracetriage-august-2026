"""`apps/web/public/data/bob.json` is what the build log produces, and it says the hard part.

The console shows what IBM Bob built because the criterion that leads on Bob had no evidence
inside the console: two blind readers scored the entry independently and both wrote down that
the word appeared twice on the whole site and both times incidentally. The table that answers
them is only worth having if it cannot drift, so the numbers on it are parsed out of
`docs/BOB_BUILD_LOG.md` at build time and this asserts the committed file is that parse.

Every unit on the table has to carry something a reader can check: the files it changed,
the task id of the account that ran it, and what failed before it was accepted. A path it
names has to resolve in the tracked tree, and one it withholds has to say so rather than
disappear.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXPORT = REPO / "scripts" / "export_bob_units.py"
OUT = REPO / "apps" / "web" / "public" / "data" / "bob.json"


@pytest.fixture(scope="module")
def doc() -> dict:
    assert OUT.exists(), f"{OUT.name} is missing. Run scripts/export_bob_units.py."
    return json.loads(OUT.read_text(encoding="utf-8"))


def test_the_committed_file_is_what_the_build_log_produces() -> None:
    """The generator in check mode, so a log edit cannot leave the page behind."""
    finished = subprocess.run(
        [sys.executable, str(EXPORT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr


def test_the_counted_units_are_the_ones_the_judge_document_counts(doc) -> None:
    """One parse, two consumers. FOR_JUDGES and the console cannot disagree."""
    import importlib.util

    path = REPO / "scripts" / "sync_for_judges.py"
    spec = importlib.util.spec_from_file_location("sync_for_judges_for_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    bob_ids, operator_ids = module._build_log_units()
    # The list is in the log's order rather than sorted, so the sequence is asserted against
    # the counter's own sequence and not against an alphabetisation of itself.
    assert [unit["unit"] for unit in doc["units"]] == list(bob_ids)
    assert doc["n_bob_units"] == len(bob_ids)


def test_every_unit_carries_something_a_reader_can_check(doc) -> None:
    """A row with no files and no failure is a claim, not a record."""
    thin = [
        unit["unit"]
        for unit in doc["units"]
        if not unit["files"] and not unit["what_failed"]
    ]
    assert not thin, (
        f"{thin} name neither a file they changed nor a failure they repaired, so the table "
        "would be asserting that Bob did something rather than showing it"
    )
    for unit in doc["units"]:
        assert unit["subject"], f"{unit['unit']} has no subject, so its row says only an id"


def test_a_missing_task_hash_is_null_rather_than_invented(doc) -> None:
    """Two of the ten record a workspace and an account and no hash. That has to survive.

    A generator that filled the column with the account, or with the previous unit's hash,
    would make the strongest field in the table the one least worth trusting.
    """
    hashes = [unit["bob_task_id"] for unit in doc["units"]]
    assert any(value is None for value in hashes), (
        "every unit now reports a task hash. If the log gained the two that were missing, "
        "this is correct and the test should be updated; if the generator started filling "
        "them in, it is not."
    )
    for value in hashes:
        assert value is None or (
            len(value) >= 16 and all(c in "0123456789abcdef" for c in value)
        ), f"{value!r} is not a hexadecimal task id"


def test_no_cited_file_is_a_dependency_specifier(doc) -> None:
    """A "file" the table counts has to be shaped like a path.

    The parse that fills this column matched anything between backticks holding a dot and
    no whitespace, so `jsonschema>=4.23` out of "`pyproject.toml` (`jsonschema>=4.23`
    added to runtime dependencies, accepted)" was published as a filename and unit A0b-INT
    reported 8 files where a clone holds 7, under a column headed "Files" on the page a
    judge opens first.

    Two properties, because either one alone lets the next shape through: no comparison or
    version operator anywhere in the string, and a suffix that starts with a letter. A
    specifier's last dotted part is digits and a real suffix never is.
    """
    offenders: list[tuple[str, str]] = []
    for unit in doc["units"]:
        for cited in unit["files"]:
            suffix = cited.rsplit(".", 1)[-1] if "." in cited else ""
            if any(ch in cited for ch in "<>=!~,;*?\"'") or not suffix[:1].isalpha():
                offenders.append((unit["unit"], cited))
    assert not offenders, (
        "these are counted as files and are not paths: "
        + ", ".join(f"{unit} cites {cited!r}" for unit, cited in offenders)
    )


def test_every_published_path_resolves_in_the_tracked_tree(doc) -> None:
    """`bob.json` is published as the evidence list for the criterion that leads on Bob.

    Six of the sixty-six paths the log names are not shipped: a withheld handover document
    cited by four units, and two build outputs under `artifacts/`. They used to sit in `files`
    beside sixty that resolve, so four units published a file count a clone cannot account
    for. The start page renders the count rather than the paths, so this was never a broken
    link; it was a number that did not mean what it said.
    """
    tracked = set(
        subprocess.run(
            ["git", "-C", str(REPO), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )
    dead = {
        f"{unit['unit']}: {path}"
        for unit in doc["units"]
        for path in unit["files"]
        if path not in tracked
    }
    assert not dead, f"published paths that a reader cannot open: {sorted(dead)}"


def test_the_withheld_paths_are_disclosed_rather_than_dropped(doc) -> None:
    """Deleting them would be the easy fix and the wrong one.

    `docs/BOB_BUILD_LOG.md` genuinely names those files, and an export that quietly disagreed
    with the source it is generated from would be a worse defect than the broken link: it
    would be unfalsifiable. Each one is kept, with a reason, so the gap is visible.
    """
    withheld = [
        entry for unit in doc["units"] for entry in unit.get("files_not_published", [])
    ]
    assert withheld, (
        "the log names files that are not shipped, so an empty list here means the split "
        "stopped working and the paths were dropped instead"
    )
    for entry in withheld:
        assert entry["path"] and entry["why"], entry
        assert len(entry["why"]) > 30, (
            f"`{entry['path']}` is withheld with no reason a reader could act on: "
            f"{entry['why']!r}"
        )


def test_no_path_is_published_and_withheld_at_once(doc) -> None:
    """The two lists partition the log's paths; they do not overlap and nothing falls out."""
    for unit in doc["units"]:
        published = set(unit["files"])
        withheld = {entry["path"] for entry in unit.get("files_not_published", [])}
        assert not (published & withheld), (
            f"{unit['unit']} lists {sorted(published & withheld)} as both shipped and not"
        )


def test_every_date_is_iso_and_every_actor_is_spelled_one_way(doc) -> None:
    """B1's heading read `17 Aug 2026 IST | account 3` where the other nine read ISO.

    The console sorts and groups on these, so one unit written in a second format is a unit
    that sorts wrong. Fixed at the heading in the build log rather than in the exporter,
    because the exporter's job is to report the log faithfully and a normaliser here would
    hide the next one.
    """
    for unit in doc["units"]:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", unit["date"]), (
            f"{unit['unit']} is dated {unit['date']!r}, which is not ISO"
        )
        assert re.fullmatch(r"Account \d+", unit["actor"]), (
            f"{unit['unit']} names its actor {unit['actor']!r}, which is not the casing the "
            f"other units use"
        )
