"""Every digest a receipt records for a tracked file, checked against that file.

Why this exists. On 2026-08-22 `artifacts/QUEUE_RECEIPT.json` recorded
`split_manifest_sha256` as `bdb159ca...`, and no committed file in this repository
produces that value. The manifest it names hashes to `c0f8cd3a...`. The receipt was
written on a Windows working tree where `artifacts/SPLIT_MANIFEST.json` still held CRLF;
`.gitattributes` normalised the file to LF on commit and nothing re-derived the digest, so
the published value was the hash of bytes that were never published. A judge running
`sha256sum` on the file the receipt names would have got a mismatch, and every gate in this
repository was green.

That is the failure `.gitattributes` was written for, one level up: the rule fixed the
files and left the numbers *about* the files behind. Nothing else here catches it. The
freshness check rebuilds a different set of artifacts, the sync gates compare documents to
receipts rather than receipts to bytes, and every test that reads a fixture reads it
through the same translating call that hid the problem.

Three outcomes, not two. `[PASS]` means the recorded digest is the digest of the file as
git publishes it. `[FAIL]` names the field, the file and both values. `[ -- ]` means the
receipt or the file it names is not in this checkout, which is a real state of a partial
clone and is not the same answer as wrong.

    .venv/Scripts/python.exe scripts/check_receipt_digests.py [--verbose]

The digest is taken over the working copy normalised to LF, which is what `.gitattributes`
stores for every text file here, rather than over the working copy as it sits. Those differ
on exactly one axis and it is the axis that broke: a CRLF working copy hashes to a value git
never publishes, so a check reading the bytes as-is would pass on the machine that wrote the
bad value.

Reading `git show HEAD:<path>` instead was the first attempt and it is wrong for a different
reason: when a receipt and the file it hashes are rebuilt in the same change, HEAD still
holds the old file and the check reports a failure on a correct pair. Normalising the
working copy is right at every point in a commit rather than only after one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[1]


class Bytes:
    """How the recorded digest was taken, because the three are not interchangeable.

    ``RAW`` is ``sha256(path.read_bytes())``: the file exactly as it sits, line endings
    included. This is the form that broke.

    ``TEXT`` is ``sha256(path.read_text().encode())``. Python's text mode translates CRLF
    to LF on read, so a digest taken this way is the same on every platform and cannot go
    stale when git normalises the file. Recording which form each field used is the whole
    content of this table: checking a TEXT digest against raw bytes would report a failure
    on a correct receipt.

    ``BINARY`` is ``sha256(path.read_bytes())`` over a file git stores as binary.
    ``text=auto`` in `.gitattributes` detects a binary file and leaves it alone, so the
    working copy *is* what a clone receives and normalising it would corrupt the
    subject: an mp4 holds 0d 0a byte pairs that are not line endings, and rewriting
    them produces a digest of a file that has never existed.
    """

    RAW = "raw"
    TEXT = "text"
    BINARY = "binary"


#: (receipt, dotted field, file the digest is of, how it was taken, the writer).
#:
#: Only digests of a *tracked file* belong here. A model digest, a random salt, a hash of an
#: in-memory structure and a hash of an archive this repository does not publish are all
#: sha256-shaped and none of them can be checked against a path, so listing them would mean
#: inventing a source for them.
CHECKS: list[tuple[str, str, str, str, str]] = [
    (
        # The lockfile the clean clone installed against. It is a claim about a tracked file
        # like every other row here, and when the field was added it was neither audited nor
        # declared as something else, which tests/test_receipt_digests.py catches by design.
        "artifacts/CLEAN_CLONE_TRANSCRIPT.json",
        "node_modules.package_lock_sha256",
        "apps/web/package-lock.json",
        Bytes.RAW,
        "scripts/clean_clone_check.py",
    ),
    (
        "artifacts/QUEUE_RECEIPT.json",
        "split_manifest_sha256",
        "artifacts/SPLIT_MANIFEST.json",
        Bytes.RAW,
        "scripts/run_queue.py",
    ),
    (
        "artifacts/FUSION_RECEIPT.json",
        "split_manifest_sha256",
        "artifacts/SPLIT_MANIFEST.json",
        Bytes.RAW,
        "scripts/run_fusion.py",
    ),
    (
        "artifacts/CIRCULARITY_RECEIPT.json",
        "source.sha256",
        "artifacts/QUEUE_RECEIPT.json",
        Bytes.RAW,
        "scripts/run_circularity_check.py",
    ),
    (
        "artifacts/AGENT_RECEIPT.json",
        "frozen_runs_sha256",
        "tests/fixtures/agent_runs.json",
        Bytes.RAW,
        "scripts/run_agent_study.py",
    ),
    (
        "artifacts/PRECEDENT_RECEIPT.json",
        "frozen_retrievals_sha256",
        "tests/fixtures/precedent_retrievals.json",
        Bytes.RAW,
        "scripts/run_precedent_study.py",
    ),
    (
        "artifacts/EXPLAIN_RECEIPT.json",
        "frozen_drafts_sha256",
        "tests/fixtures/granite_notes.json",
        Bytes.TEXT,
        "scripts/run_explanations.py",
    ),
    (
        "artifacts/LANGFLOW_RECEIPT.json",
        "flows.grounding.sha256",
        "flows/tracetriage_grounding.json",
        Bytes.RAW,
        "scripts/run_langflow_check.py",
    ),
    (
        "artifacts/LANGFLOW_RECEIPT.json",
        "flows.granite_agent.sha256",
        "flows/tracetriage_granite_agent.json",
        Bytes.RAW,
        "scripts/run_langflow_check.py",
    ),
    (
        "artifacts/FILM_RECEIPT.json",
        "render.sha256",
        "presentation/out/tracetriage-film.mp4",
        Bytes.BINARY,
        "presentation/scripts/report-table.ts",
    ),
    (
        "artifacts/FILM_RECEIPT.json",
        "poster.sha256",
        "presentation/out/tracetriage-film-poster.jpg",
        Bytes.BINARY,
        "presentation/scripts/report-table.ts",
    ),
]


def _resolve(node: Any, dotted: str) -> Any:
    for step in dotted.split("."):
        if not isinstance(node, dict) or step not in node:
            return None
        node = node[step]
    return node


def _published(rel: str, how: str) -> bytes | None:
    """The file's content as git stores it.

    For a text file that is the working copy with LF endings: `.gitattributes` sets
    `* text=auto eol=lf`, so this is what a clone receives and it is the same on every
    machine. Returning the raw working copy instead would make the check agree with
    whichever tree happened to write the receipt.

    For a binary one it is the working copy untouched, because `text=auto` detects a
    binary file and stores it byte for byte. Normalising an mp4 would rewrite byte
    pairs that are not line endings and hash a file that has never existed.
    """
    path = REPO / rel
    if not path.is_file():
        return None
    data = path.read_bytes()
    return data if how == Bytes.BINARY else data.replace(b"\r\n", b"\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true", help="print the passing rows too")
    args = ap.parse_args()

    failures: list[str] = []
    omitted = 0
    checked = 0

    for receipt_rel, field, file_rel, how, writer in CHECKS:
        receipt_path = REPO / receipt_rel
        if not receipt_path.exists():
            print(f"  [ -- ] {receipt_rel} {field}  omitted: the receipt is not here")
            omitted += 1
            continue
        recorded = _resolve(
            json.loads(receipt_path.read_text(encoding="utf-8")), field
        )
        if not isinstance(recorded, str):
            print(f"  [ -- ] {receipt_rel} {field}  omitted: the field is absent or null")
            omitted += 1
            continue
        raw = _published(file_rel, how)
        if raw is None:
            print(f"  [ -- ] {receipt_rel} {field}  omitted: {file_rel} is not in this checkout")
            omitted += 1
            continue

        subject = raw.decode("utf-8").encode("utf-8") if how == Bytes.TEXT else raw
        actual = hashlib.sha256(subject).hexdigest()
        checked += 1

        if actual == recorded:
            if args.verbose:
                print(f"  [PASS] {receipt_rel} {field}  {actual[:16]}")
            continue

        # The line-ending case is worth naming, because the fix is to re-run the writer
        # rather than to hunt for a changed measurement.
        # It cannot arise for a binary subject, and asking would mean hashing a
        # rewritten mp4 to answer a question that has no meaning for one.
        why = ""
        if how != Bytes.BINARY:
            crlf = hashlib.sha256(raw.replace(b"\n", b"\r\n")).hexdigest()
            if recorded == crlf:
                why = (
                    " (the recorded value is this file with CRLF endings, so the "
                    "receipt was written before git normalised it: re-run the writer)"
                )
        message = (
            f"{receipt_rel} {field} records {recorded[:16]} and {file_rel} hashes to "
            f"{actual[:16]}{why}. Writer: {writer}"
        )
        print(f"  [FAIL] {message}")
        failures.append(message)

    print()
    print(f"{checked - len(failures)}/{checked} recorded digests match their file"
          + (f", {omitted} omitted" if omitted else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
