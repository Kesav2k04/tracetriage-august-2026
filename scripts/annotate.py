"""Record and verify local reviewer annotations (unit C3).

Writes to a local JSONL log and nothing else. The module this uses has no network
capability anywhere in its import closure, which is asserted by
``tests/test_annotate.py`` rather than promised here.

    .venv/Scripts/python.exe scripts/annotate.py add 14740031 STALE_FREQUENCY_CONFIRMED
    .venv/Scripts/python.exe scripts/annotate.py verify
    .venv/Scripts/python.exe scripts/annotate.py summary

The receipt digest is read from the queue receipt on disk, so an annotation is
always bound to the ranking that produced it. Re-running the queue changes that
digest, and annotations made against the old one keep pointing at it rather than
being silently reattributed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.annotate import (  # noqa: E402
    ANNOTATION_DECISIONS,
    AnnotationStore,
)

_RECEIPT = _REPO / "artifacts" / "QUEUE_RECEIPT.json"
_STORE = _REPO / "artifacts" / "annotations" / "annotations.jsonl"


def receipt_digest(path: Path) -> str:
    """Digest of the receipt file as it sits on disk."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rank_and_split(obs_id: int, receipt_path: Path) -> tuple[int | None, str]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    for entry in receipt.get("queue", []):
        if entry["obs_id"] == obs_id:
            return entry["rank"], receipt["gate6"]["decided_on"]
    return None, receipt["gate6"]["decided_on"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(_STORE))
    parser.add_argument("--receipt", default=str(_RECEIPT))
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="append one annotation")
    add.add_argument("obs_id", type=int)
    add.add_argument("decision", choices=sorted(ANNOTATION_DECISIONS))
    add.add_argument("--note", default=None)
    add.add_argument("--annotator", default="local")

    sub.add_parser("verify", help="check every digest and link")
    sub.add_parser("summary", help="counts by decision")
    sub.add_parser("decisions", help="list the decision vocabulary")

    args = parser.parse_args(argv)
    store = AnnotationStore(args.store)

    if args.command == "decisions":
        for name, description in ANNOTATION_DECISIONS.items():
            print(f"{name}\n    {description}\n")
        return 0

    if args.command == "add":
        receipt_path = Path(args.receipt)
        if not receipt_path.exists():
            print(
                f"No queue receipt at {receipt_path}. An annotation has to name the "
                f"ranking it was made against, so run scripts/run_queue.py first.",
                file=sys.stderr,
            )
            return 2
        rank, split = _rank_and_split(args.obs_id, receipt_path)
        record = store.append(
            args.obs_id,
            args.decision,
            receipt_sha256=receipt_digest(receipt_path),
            split=split,
            rank_at_annotation=rank,
            note=args.note,
            annotator=args.annotator,
        )
        where = f"rank {rank}" if rank is not None else "not in the shipped queue"
        print(f"recorded {args.decision} for {args.obs_id} ({where})")
        print(f"  chained to {record['prev_sha256'][:12]}")
        print(f"  digest     {record['record_sha256'][:12]}")
        print(f"  log        {store.path}")
        return 0

    if args.command == "verify":
        report = store.verify()
        print(f"records examined: {report['n_examined']}")
        print(f"intact: {report['intact']}")
        if not report["intact"]:
            print(f"  edited records at indices: {report['broken_digest_indices']}")
            print(f"  broken links at indices:   {report['broken_link_indices']}")
        return 0 if report["intact"] else 1

    summary = store.summarise()
    print(f"records: {summary['n_records']}  observations: {summary['n_observations']}")
    for decision, count in summary["counts_by_decision"].items():
        print(f"  {decision:32s} {count}")
    print(f"receipts referenced: {len(summary['receipts_referenced'])}")
    print(f"chain intact: {summary['verification']['intact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
