"""What the reviewer bundle may and may not contain.

Both tests here exist because of a defect rather than a design. The packer copied
``responses.csv`` out of the bundle, and the bundle is where a review is carried out, so
one answered worksheet would have shipped the next reviewer a form with someone else's
judgments in it. And it built every entry with ``ZipFile.write``, which records each file's
modification time, so the sha256 published beside the archive changed on any touch and was
never a digest a reader could reproduce.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from pack_gate4_bundle import FIXED_TIME, FORM, PACKED, _add, _blank_form  # noqa: E402

MANIFEST = json.loads(
    (REPO / "artifacts/GATE4_WORKSHEET.json").read_text(encoding="utf-8")
)


def test_the_shipped_form_is_empty_and_lists_the_committed_items():
    rows = list(csv.DictReader(io.StringIO(_blank_form(MANIFEST).decode("utf-8"))))
    assert [row["item"] for row in rows] == [
        row["item"] for row in MANIFEST["commitments"]
    ], "the form must be the committed sample, in the committed order"
    for row in rows:
        for axis in ("artifact_usable", "visible_signal", "target_consistent", "notes"):
            assert row[axis] == "", f"{row['item']} arrives with {axis} already answered"


def test_the_form_is_generated_rather_than_copied_from_the_bundle():
    """The bundle's own responses.csv is not in the list of files that get copied.

    This is the defect stated as a test: if `responses.csv` is ever added back to `PACKED`,
    an answered review starts shipping to the next reviewer and nothing else would notice.
    """
    assert FORM not in PACKED
    assert FORM == "responses.csv"


def _digest(payloads: dict[str, bytes]) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, payload in payloads.items():
            _add(zf, name, payload, zipfile.ZIP_DEFLATED)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def test_the_archive_digest_is_reproducible_from_the_contents_alone():
    payloads = {"worksheet.md": b"protocol\n", FORM: _blank_form(MANIFEST)}
    assert _digest(payloads) == _digest(payloads), (
        "two archives over identical bytes must have identical digests, or the sha256 "
        "published beside the bundle is not a claim anyone can check"
    )
    changed = dict(payloads, **{"worksheet.md": b"protocol, revised\n"})
    assert _digest(changed) != _digest(payloads), (
        "and a real change must still move it, or the digest is not binding anything"
    )


def test_every_entry_carries_the_fixed_timestamp():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        _add(zf, FORM, _blank_form(MANIFEST), zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(buffer) as zf:
        for info in zf.infolist():
            assert info.date_time == FIXED_TIME, info.filename
            assert info.filename.startswith("tracetriage_gate4/"), (
                "the archive must unpack into its own folder rather than over the "
                "reviewer's working directory"
            )
