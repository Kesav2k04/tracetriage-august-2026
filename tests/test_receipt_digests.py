"""The digest audit, and the three ways it could pass while meaning nothing.

``scripts/check_receipt_digests.py`` compares every digest a receipt records for a tracked
file against that file's bytes as git publishes them. It exists because two receipts shipped
a ``split_manifest_sha256`` that no committed file produces: the value was the manifest with
CRLF endings, taken before git normalised the file.

A checker like that fails in three quiet ways. It can pass because its table is empty or has
silently shrunk. It can pass because it is comparing something to itself. And it can compare
the wrong bytes: the normalisation that makes a text digest platform-independent corrupts a
binary subject, so the committed film has to be hashed as it sits. All three are checked
here, and the second is checked by planting the original defect.
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
    assert len(CHECKS) == 12
    for receipt, field, file_rel, how, writer in CHECKS:
        assert receipt.startswith("artifacts/"), receipt
        assert field and not field.startswith("."), field
        assert how in (Bytes.RAW, Bytes.TEXT, Bytes.BINARY), how
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


def test_a_binary_subject_is_hashed_as_it_sits_and_the_distinction_is_real():
    """The reason `Bytes.BINARY` exists, measured rather than argued.

    The other rows hash the working copy normalised to LF, which is what git stores for a
    text file. Doing that to a video rewrites byte pairs that are not line endings. This
    asserts the committed film actually contains such pairs, so the mode is not a
    hypothetical: normalising it produces a different digest, and a checker without the
    mode would report a failure on a correct receipt rather than catching anything.
    """
    film = REPO / "presentation" / "out" / "tracetriage-film.mp4"
    if not film.is_file():
        pytest.skip("this checkout holds no rendered film")

    data = film.read_bytes()
    pairs = data.count(b"\r\n")
    assert pairs > 0, (
        "the committed film holds no CR LF byte pair, so this test can no longer tell a "
        "raw digest from a normalised one. Re-check that Bytes.BINARY is still needed "
        "rather than deleting this."
    )
    assert (
        hashlib.sha256(data).hexdigest()
        != hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
    )

    rows = [row for row in CHECKS if row[2].endswith("tracetriage-film.mp4")]
    assert len(rows) == 1, rows
    assert rows[0][3] == Bytes.BINARY, (
        f"the film is audited as {rows[0][3]}, which normalises {pairs} byte pairs that "
        "are not line endings"
    )


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
        # Every axis the model-free reader derived, as `obs_id:value` lines, hashed. It names
        # no file: it is there so a second run over the same 2,424 images can be compared to
        # this one in one value instead of row by row.
        ("AXIS_READER_AUDIT.json", "readings_fingerprint_sha256"): (
            "the readings this run produced, not a file"
        ),
        # The salt is 32 random bytes as hex, which is indistinguishable from a sha256 by
        # shape. Where it sits in the receipt depends on who reviewed: under `arm` for a
        # reviewer the gate is not about, at the top level once a person has answered, and
        # under `prior_review` for the earlier review that a human answer carries forward.
        # All three are listed rather than matched by suffix, so a fourth place a salt could
        # appear fails here until someone says what it is.
        # The camera original of the filmed take is not tracked, on purpose: it is the
        # same frames at a quarter of the useful pixels per byte. Its digest is published
        # so the cut that is tracked can be tied back to it.
        ("LIVE_TAKE.json", "take.source.raw_sha256"): (
            "the untracked camera original the published cut came from"
        ),
        # SatNOGS serves the waterfall; this repository does not carry that observation's
        # image. The digest is what a reader would compare their own download against.
        ("LIVE_TAKE.json", "measured_live.waterfall_sha256"): (
            "the image SatNOGS served, not a repo file"
        ),
        ("GATE4_RECEIPT.json", "arm.reveal.salt"): "a random salt",
        ("GATE4_RECEIPT.json", "reveal.salt"): "a random salt, from the human review",
        ("GATE4_RECEIPT.json", "prior_review.reveal.salt"): (
            "a random salt, from the review a human answer carried forward"
        ),
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
        # The Kokoro weights that spoke the narration: 354 MB across two files, fetched
        # from a release and deliberately not committed. Digested rather than merely named
        # because the voice is a measurement input, so a reader who wants to know which
        # weights produced the audio in the mp4 can check that they hold the same two
        # files. The wavs those weights produced are tracked and are audited above.
        ("NARRATION_RECEIPT.json", "renderer.model_sha256.kokoro-v1.0.onnx"): (
            "a released model file this repository does not publish"
        ),
        ("NARRATION_RECEIPT.json", "renderer.model_sha256.voices-v1.0.bin"): (
            "a released voice pack this repository does not publish"
        ),
        # The recording the narration voice is cloned from. It is a few seconds of a real
        # person speaking, which is a biometric, so it is not committed and never will be.
        # The digest is here so a reader can tell whether two renders were conditioned on
        # the same source without the source being published, and so can a future render:
        # the same clip and the same seed reproduce the committed wavs, and those wavs are
        # audited above. Nothing that could reconstruct the voice is in this repository.
        ("NARRATION_RECEIPT.json", "renderer.reference_sha256"): (
            "a private voice recording this repository deliberately does not publish"
        ),
        ("EXPLAINER_NARRATION.json", "renderer.reference_sha256"): (
            "the same private voice recording, so the console and the film are one speaker"
        ),
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
