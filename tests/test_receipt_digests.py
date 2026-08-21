"""The digest audit, and the two ways it could pass while meaning nothing.

``scripts/check_receipt_digests.py`` compares every digest a receipt records for a tracked
file against that file's bytes as git publishes them. It exists because two receipts shipped
a ``split_manifest_sha256`` that no committed file produces: the value was the manifest with
CRLF endings, taken before git normalised the file.

A checker like that fails in two quiet ways. It can pass because its table is empty or has
silently shrunk, and it can pass because it is comparing something to itself. Both are
checked here, and the second is checked by planting the original defect.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / "scripts" / "check_receipt_digests.py"

sys.path.insert(0, str(REPO / "scripts"))
from check_receipt_digests import CHECKS, Bytes  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_committed_receipts_name_digests_their_files_produce():
    """The check itself. A failure here names the receipt, the file and both values."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_table_is_not_empty_and_every_row_is_well_formed():
    """An exemption with no number attached to it stops being an exemption.

    The count is asserted rather than described so a row cannot be dropped in passing. If
    a digest is deliberately removed from the audit, this number moves in the same commit
    and the reason lands in the diff beside it.
    """
    assert len(CHECKS) == 8
    for receipt, field, file_rel, how, writer in CHECKS:
        assert receipt.startswith("artifacts/"), receipt
        assert field and not field.startswith("."), field
        assert how in (Bytes.RAW, Bytes.TEXT), how
        assert (REPO / writer).exists(), f"{receipt} names a writer that is not here: {writer}"
        # The file may legitimately be absent in a partial clone, which the checker reports
        # as omitted. What may not happen is a path that was never plausible.
        assert not file_rel.startswith("/"), file_rel


def test_it_actually_compares_and_would_catch_the_defect_that_created_it():
    """Plant the original bug and require a failure.

    Without this, a checker that resolved a field to ``None`` on every row, or hashed the
    recorded value instead of the file, would print a clean tally over nothing.
    """
    receipt = REPO / "artifacts" / "QUEUE_RECEIPT.json"
    manifest = REPO / "artifacts" / "SPLIT_MANIFEST.json"
    if not receipt.exists() or not manifest.exists():
        pytest.skip("this checkout has no queue receipt to perturb")

    original = receipt.read_bytes()
    crlf_digest = hashlib.sha256(
        manifest.read_bytes().replace(b"\n", b"\r\n")
    ).hexdigest()
    payload = json.loads(original.decode("utf-8"))
    payload["split_manifest_sha256"] = crlf_digest
    try:
        receipt.write_bytes(
            json.dumps(payload, indent=1).encode("utf-8")
        )
        done = _run()
        assert done.returncode == 1, "the planted CRLF digest was not caught"
        assert "split_manifest_sha256" in done.stdout
        # And it has to say why, because "re-run the writer" is the fix and hunting for a
        # changed measurement is not.
        assert "CRLF" in done.stdout
    finally:
        receipt.write_bytes(original)

    # The tree is back the way it was, and that is asserted rather than assumed.
    assert receipt.read_bytes() == original


def test_every_sha256_field_that_names_a_file_is_either_audited_or_explained():
    """The coverage half, which is the one that rots.

    A new receipt with a new file digest would leave the audit passing over a field nobody
    checks. Every sha256-shaped value in every receipt is enumerated here and has to be
    either in the audit's table or in the exclusion list below, each with its reason.
    """
    audited = {(r.split("/", 1)[1], f) for r, f, *_ in CHECKS}

    # Not a digest of a tracked file. Each entry says what it is instead, because "it is
    # not checkable" is a claim and an unexplained skip is how the first one got through.
    not_a_file_digest = {
        ("AGENT_RECEIPT.json", "model.digest"): "the Ollama model blob, not a repo file",
        ("EXPLAIN_RECEIPT.json", "model.digest"): "the Ollama model blob",
        ("PRECEDENT_RECEIPT.json", "embedding_model.digest"): "the Ollama model blob",
        ("EXPLAIN_RECEIPT.json", "generation.prompt_contract_sha256"): "a function's output",
        ("WATSONX_RECEIPT.json", "subject.prompt_contract_sha256"): "a function's output",
        ("GATE4_RECEIPT.json", "arm.reveal.salt"): "a random salt",
        ("GATE4_BUNDLE.json", "archive.sha256"): "an archive this repo does not publish",
        ("PRECEDENT_RECEIPT.json", "cards_sha256"): "an in-memory structure",
        ("PRECEDENT_RECEIPT.json", "vectors_sha256"): "in-memory vectors",
        ("BASELINE_RECEIPT.json", "manifest_sha256"): (
            "the dataset manifest as the corpus loader read it, recorded inside the "
            "loader rather than by a receipt writer"
        ),
        ("TRIAGE_RECEIPT.json", "model_checksum"): "the model blob",
        ("TRIAGE_RECEIPT.json", "provenance.artifact_sha256"): (
            "a downloaded waterfall, not a tracked file"
        ),
        ("CIRCULARITY_RECEIPT.json", "queue_receipt_sha256"): "an alias handled by source.sha256",
    }
    # The four split partitions, each a digest over that split's test-set observation ids
    # rather than over a file. scripts/build_splits.py calls them "what prove the partitions
    # did not move", so they are a tripwire on an in-memory list and there is no path to
    # compare them against. Listed by name rather than by a prefix match, so a fifth split
    # would fail here until someone decided what it is.
    for split in ("chronological", "cold_station", "cold_transmitter", "cold_combined"):
        not_a_file_digest[
            ("SPLIT_MANIFEST.json", f"leakage_checks.test_set_untouched.test_id_digests.{split}")
        ] = "a digest over that split's test-set ids, not over a file"

    unexplained: list[str] = []
    for path in sorted((REPO / "artifacts").glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        found: list[str] = []

        def walk(node: object, trail: str, sink: list[str] = found) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{trail}.{key}" if trail else key, sink)
            elif isinstance(node, list):
                # One element is enough: a list of rows repeats the same field name, and
                # walking thousands of them turns this test into a minute of nothing.
                if node:
                    walk(node[0], f"{trail}[]", sink)
            elif isinstance(node, str) and re.fullmatch(r"[0-9a-f]{64}", node):
                sink.append(trail)

        walk(payload, "")
        for field in found:
            plain = field.replace("[]", "")
            key = (path.name, plain)
            if key in audited or key in not_a_file_digest:
                continue
            # A per-row digest inside a list is data, not a claim about a tracked file.
            if "[]" in field:
                continue
            unexplained.append(f"{path.name} {plain}")

    assert not unexplained, (
        "these sha256 fields are neither audited nor listed as not-a-file-digest, so "
        f"nothing checks them: {sorted(set(unexplained))}"
    )
