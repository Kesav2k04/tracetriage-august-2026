"""The satellite name behind every observation the console ranks.

    .venv/Scripts/python.exe scripts/export_satellite_names.py
    .venv/Scripts/python.exe scripts/export_satellite_names.py --check

Writes ``artifacts/SATELLITE_NAMES.json``: one entry per row of the shipped queue,
mapping the observation id to the ``tle0`` line the snapshot recorded for that pass.

Why this is an artifact rather than a lookup inside the console builder. The name lives
in the 20 GB snapshot, and ``scripts/build_console_data.py --skip-images`` is the one
rebuild path that runs in a clean clone with no snapshot at all: it is what
``scripts/clean_clone_check.py`` runs and what ``scripts/check_artifact_freshness.py``
diffs the published payloads against. Reading the pages directly from the console
builder would have made queue.json unbuildable on every machine that does not hold the
snapshot, which is every CI runner and every judge. So the snapshot is read once, here,
and committed as a receipt with its own digest; the console builder reads the receipt.

``tle0`` is the first line of the three-line element set the station propagated for the
pass, and it is written verbatim. That is the same field, under the same name, that the
live path already publishes at ``pipeline/tracetriage/live.py:555``. It carries the
line-number marker the format prescribes, so most values begin "0 ", and stripping that
for display is the console's job rather than this file's: an artifact that quietly
edited the snapshot's own string would be the wrong place to find out what the record
said.

A missing or blank name is a refusal, not a null. Every one of the ranked observations
came out of the same snapshot as the queue receipt, so an absent name means the snapshot
or the field name moved, and publishing 407 rows with some of them unnamed would read as
a property of the data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.splits import (  # noqa: E402
    _default_pages_dir,
    _load_raw_pages,
)

_ARTIFACTS = _REPO / "artifacts"
_RECEIPT = _ARTIFACTS / "SATELLITE_NAMES.json"

#: The snapshot field this file carries, named once so the receipt and the refusal
#: message cannot disagree about which field was read.
_SOURCE_FIELD = "tle0"

#: Fields that move on every write and are not measurements.
_VOLATILE = ("generated_at",)


def build(pages_dir: Path | None = None) -> dict[str, Any]:
    """The name map, or a refusal naming the first observation without a name."""
    queue = json.loads((_ARTIFACTS / "QUEUE_RECEIPT.json").read_text(encoding="utf-8"))
    obs_ids = [int(entry["obs_id"]) for entry in queue["queue"]]
    raw = _load_raw_pages(pages_dir or _default_pages_dir())

    names: dict[str, str] = {}
    for obs_id in obs_ids:
        record = raw.get(obs_id)
        if record is None:
            raise ValueError(
                f"observation {obs_id} is ranked in QUEUE_RECEIPT.json and is not in the "
                f"snapshot this ran against. The queue and the names have to come from "
                f"one snapshot, so this is a wrong pages directory rather than a missing "
                f"name."
            )
        name = str(record.get(_SOURCE_FIELD) or "").strip()
        if not name:
            raise ValueError(
                f"observation {obs_id} has no {_SOURCE_FIELD} in the snapshot. The "
                f"console publishes this as the satellite, and a blank one there would "
                f"read as an unnamed pass rather than as a field that moved."
            )
        names[str(obs_id)] = name

    return {
        "schema": "SATELLITE_NAMES/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot_id": queue["snapshot_id"],
        "source_field": _SOURCE_FIELD,
        "source_note": (
            "tle0 verbatim: the first line of the three-line element set the station "
            "propagated for this pass. The line-number marker the format prescribes is "
            "left on, so a reader can match this against the snapshot record."
        ),
        "n_observations": len(names),
        "n_distinct_names": len(set(names.values())),
        "names": names,
    }


def _comparable(receipt: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in receipt.items() if k not in _VOLATILE}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild and compare against the committed receipt instead of writing it",
    )
    parser.add_argument(
        "--pages-dir",
        type=Path,
        default=None,
        help="the snapshot's pages folder, if TRACETRIAGE_PAGES_DIR is not set",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write somewhere other than artifacts/SATELLITE_NAMES.json",
    )
    args = parser.parse_args(argv)

    fresh = build(args.pages_dir)

    if args.check:
        if not _RECEIPT.exists():
            print(f"[FAIL] {_RECEIPT.relative_to(_REPO)} is missing. Run this script.")
            return 1
        committed = json.loads(_RECEIPT.read_text(encoding="utf-8"))
        if _comparable(committed) == _comparable(fresh):
            print(
                f"[PASS] satellite names match the snapshot  "
                f"{fresh['n_observations']} observations, "
                f"{fresh['n_distinct_names']} distinct names"
            )
            return 0
        print(
            f"[FAIL] {_RECEIPT.relative_to(_REPO)} disagrees with a rebuild. "
            f"Committed {len(committed.get('names') or {})} names, rebuilt "
            f"{fresh['n_observations']}. Re-run scripts/export_satellite_names.py, "
            f"then scripts/build_console_data.py --skip-images."
        )
        return 1

    out = args.out or _RECEIPT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(
        f"{fresh['n_observations']} observations, {fresh['n_distinct_names']} distinct "
        f"names"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
