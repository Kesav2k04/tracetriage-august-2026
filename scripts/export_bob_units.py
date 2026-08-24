"""Export the Bob-account units from the build log for the console to render.

The criterion this answers leads on IBM Bob, and until now the evidence for it lived only in
`docs/BOB_BUILD_LOG.md` and `FOR_JUDGES.md`, both of which are files in a repository. Two
blind readers scored the entry and both said the same thing: the word Bob appears twice on
the whole deployed console and both are incidental, so the one tool the criterion names is
the one thing they could not see. This puts the accounting on `/start/`, read out of the log
rather than typed into a page, because a hand-typed count in the console is the same defect
the README had.

The parser is imported from `scripts/sync_for_judges.py` rather than written again here.
Two parsers over the same document eventually disagree, and when they do the number a judge
reads is decided by whichever generator ran last.

What is exported is the honest half as well as the flattering one: the ten Bob units, and the
count of operator-side units beside them, because the log attributes 49 of its 59 dated units
to a person at Cursor and Claude Code and a page that showed only the ten would be reporting
a fraction as a total.

Usage::

    .venv/Scripts/python.exe scripts/export_bob_units.py
    .venv/Scripts/python.exe scripts/export_bob_units.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BUILD_LOG = REPO / "docs" / "BOB_BUILD_LOG.md"
OUT = REPO / "apps" / "web" / "public" / "data" / "bob.json"

SCHEMA_VERSION = "0.1.0"

#: Fields a unit's body may carry. The log grew two spellings of the same idea, so both are
#: read and the first one present wins.
FILES_FIELDS = ("Files changed", "Files created/changed", "Files")
FAILURE_FIELDS = ("Failures and repairs", "Fix")


def _sync_module():
    """`scripts/sync_for_judges.py`, imported by path for its build-log parser."""
    path = REPO / "scripts" / "sync_for_judges.py"
    spec = importlib.util.spec_from_file_location("sync_for_judges_for_export", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _field(body: str, names: tuple[str, ...]) -> str | None:
    """The first of `names` present in `body`, as one line of plain text."""
    for name in names:
        match = re.search(
            rf"^\*\*{re.escape(name)}:\*\*\s*(?P<value>.*?)(?=\n\*\*|\n#{{2,3}} |\Z)",
            body,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match:
            value = " ".join(match.group("value").split())
            if value:
                return value
    return None


def _task_id(body: str) -> str | None:
    """The Bob task hash, when the entry carries one.

    Not every unit does. Two of the ten record the workspace and the account without a hash,
    and a task id invented to fill the column would be the one field in this export that
    cannot be checked against anything. Those two come out null and the page says so.
    """
    raw = _field(body, ("Bob task ID",))
    if not raw:
        return None
    found = re.search(r"`([0-9a-f]{16,64})`|(?<![\w`])([0-9a-f]{32})(?![\w`])", raw)
    if not found:
        return None
    return found.group(1) or found.group(2)


def _files(body: str) -> list[str]:
    """Paths named in the files field, as paths rather than as prose.

    The extension has to start with a letter, and that one character is the whole fix for
    a defect that reached the judges' start page. The old pattern accepted anything
    between backticks that held a dot and no whitespace, so
    ``` `jsonschema>=4.23` ``` in "pyproject.toml (`jsonschema>=4.23` added to runtime
    dependencies, accepted)" came out as a filename: unit A0b-INT published 8 files where
    a clone holds 7, under a column headed "Files". A version specifier's last dotted
    part is always digits and a real suffix never is, so the class is excluded rather
    than the one string.
    """
    raw = _field(body, FILES_FIELDS)
    if not raw:
        return []
    found = re.findall(r"`([^`\s]+\.[A-Za-z][A-Za-z0-9]*)`", raw)
    if not found:
        found = re.findall(r"(?<![\w/`])([\w./-]+/[\w.-]+\.[A-Za-z][A-Za-z0-9]*)", raw)
    seen: list[str] = []
    for path in found:
        if path not in seen:
            seen.append(path)
    return seen


#: Why each path the build log names is absent from the tracked tree. A path that does not
#: resolve and is not named here stops the export, because the alternative is publishing an
#: evidence list holding paths a reader cannot open. Adding a name to this table is a
#: deliberate act that says "the log is right, this really is not shipped, and here is why".
NOT_PUBLISHED = {
    "docs/BOB_HANDOFF.md": (
        "A working handover document, kept out of the tracked tree by .gitignore. What it "
        "briefed is published as these units; the briefing itself is not."
    ),
    "artifacts/hoglr_model.pkl": (
        "A trained model, rebuilt from the snapshot by the pipeline. artifacts/ holds build "
        "outputs, which are regenerated rather than committed."
    ),
    "artifacts/evidence_card_14740031.html": (
        "A rendered evidence card, rebuilt by scripts/render_evidence_card.py from the "
        "observation it names."
    ),
}


def _tracked() -> frozenset[str]:
    """Every path in the tracked tree, read from git.

    A walk of the working directory would answer a different question: it would count build
    outputs and gitignored working documents as published, which is the exact confusion this
    split exists to end. So this asks git, and a checkout with no git available is a refusal
    rather than a fallback, because a quiet fallback here would restore the 404 it fixes.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "export_bob_units.py needs `git ls-files` to tell a published path from a "
            f"withheld one, and it could not run here: {exc}"
        ) from exc
    return frozenset(done.stdout.split())


def _split_files(paths: list[str], tracked: frozenset[str], unit: str) -> tuple[list, list]:
    """Separate the paths a reader can open from the ones the log names but does not ship.

    Both halves are kept. Dropping the second would make this export disagree with
    docs/BOB_BUILD_LOG.md, which genuinely names those files, and the record being faithful
    to its source is the point of generating it from that source at all. Naming them with a
    reason turns an apparent broken link into a disclosure.
    """
    published = [path for path in paths if path in tracked]
    withheld = []
    for path in paths:
        if path in tracked:
            continue
        why = NOT_PUBLISHED.get(path)
        if why is None:
            raise SystemExit(
                f"unit {unit} names `{path}`, which is not in the tracked tree and has no "
                f"entry in NOT_PUBLISHED. This file is published at /data/bob.json as the "
                f"evidence list for these units, so a path in it that resolves nowhere is a "
                f"claim nobody can check. Either the path is wrong in "
                f"docs/BOB_BUILD_LOG.md, or it is deliberately not shipped and belongs in "
                f"that table with a reason."
            )
        withheld.append({"path": path, "why": why})
    return published, withheld

def _first_sentence(text: str, limit: int = 220, floor: int = 40) -> str:
    """One sentence, so a table cell stays a table cell.

    Most of these fields are numbered lists, so a naive split on the first full stop returns
    the string "1." and the page reports that the first failure of every unit was the number
    one. The enumerator is dropped first, and a sentence shorter than `floor` characters takes
    the next one with it rather than standing alone.
    """
    body = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", text.strip())
    # Emphasis and code spans are markup, and the console renders this as text rather than as
    # markdown, so left in place they reach the page as literal asterisks and backticks.
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    body = body.replace("`", "")
    parts = re.split(r"(?<=[.!?])\s+", body)
    sentence = ""
    for part in parts:
        sentence = f"{sentence} {part}".strip() if sentence else part.strip()
        if len(sentence) >= floor:
            break
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rsplit(" ", 1)[0] + "…"
    return sentence


def collect() -> dict[str, Any]:
    """The ten Bob units, in the order the log records them, with the operator count."""
    sync = _sync_module()
    bob_ids, operator_ids = sync._build_log_units()
    text = BUILD_LOG.read_text(encoding="utf-8")

    # The shared pattern is anchored with ^ and compiled without re.MULTILINE, because the
    # counter it belongs to walks the file a line at a time. Matching it against the whole
    # document returns nothing at all, so the walk is repeated here rather than the pattern
    # being copied and quietly loosened.
    matches: list[tuple[re.Match[str], str, int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        found = sync._BUILD_LOG_UNIT_RE.match(line)
        if found:
            # The whole line, not match.group(0). The shared pattern stops at the unit id, so
            # its own match carries the date and the actor and drops the subject that follows.
            matches.append((found, line.strip(), offset, offset + len(line)))
        offset += len(line)
    assert matches, "the build log parser matched no dated units"
    bounds = [start for _, _, start, _ in matches] + [len(text)]

    tracked = _tracked()
    units: list[dict[str, Any]] = []
    for index, (match, heading, _start, end) in enumerate(matches):
        unit = match.group("unit")
        if unit not in bob_ids:
            continue
        body = text[end : bounds[index + 1]]
        subject = heading.split(unit, 1)[1].lstrip(":. ").strip()
        task_id = _task_id(body)
        failure = _field(body, FAILURE_FIELDS)
        published, withheld = _split_files(_files(body), tracked, unit)
        units.append(
            {
                "unit": unit,
                "date": heading.split("IST", 1)[0].split("#")[-1].strip(),
                "actor": match.group("actor").strip(),
                "subject": subject,
                "bob_task_id": task_id,
                "files": published,
                "files_not_published": withheld,
                "what_failed": _first_sentence(failure) if failure else None,
            }
        )

    missing = sorted(set(bob_ids) - {u["unit"] for u in units})
    assert not missing, f"the log counts {missing} as Bob units and no heading was found"

    return {
        "schema": "BOB_UNITS",
        "schema_version": SCHEMA_VERSION,
        "source": "docs/BOB_BUILD_LOG.md",
        "generated_by": "scripts/export_bob_units.py",
        "n_bob_units": len(bob_ids),
        "n_operator_units": len(operator_ids),
        "n_dated_units": len(bob_ids) + len(operator_ids),
        "what_is_not_bobs": (
            "The console, the calibration and abstention blocks, the fusion ladder and the "
            "review waves are operator-side, run from Cursor and Claude Code, and are "
            "labelled that way in the actor field of their own headings. Most of them are "
            "in docs/OPERATOR_BUILD_LOG.md, which is where the Wave D and Wave E units "
            "went when the single log outgrew the size GitHub will render."
        ),
        "units": units,
    }


def render() -> str:
    return json.dumps(collect(), indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed file is not what this run produces",
    )
    args = parser.parse_args(argv)

    produced = render()
    if args.check:
        if not OUT.exists():
            print(f"{OUT.relative_to(REPO)} does not exist. Run this script.")
            return 1
        if OUT.read_text(encoding="utf-8") != produced:
            print(f"{OUT.relative_to(REPO)} is not what the build log produces. Re-run this.")
            return 1
        print(f"{OUT.relative_to(REPO)} is in sync with docs/BOB_BUILD_LOG.md")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(produced, encoding="utf-8", newline="\n")
    doc = json.loads(produced)
    print(
        f"{OUT.relative_to(REPO)} written: {doc['n_bob_units']} Bob units, "
        f"{doc['n_operator_units']} operator-side, {doc['n_dated_units']} dated in total"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
