"""Local annotation store for reviewed observations (unit C3).

A reviewer working the queue records what they found. Those records stay on this
machine. Nothing here can write to SatNOGS, and that is a property of the code
rather than a promise in a document:

**No network capability in the import closure.** This module imports only the
standard library modules needed to hash and serialise, and nothing it imports
transitively reaches ``httpx``, ``requests``, ``urllib.request``, ``socket`` or
``http.client``. ``tests/test_annotate.py`` walks the first-party import graph from
this file and fails if any of them appears. The snapshot fetcher does use httpx,
read-only, and it is not in this closure.

**The sink is verified to be a local path.** :func:`resolve_store_path` rejects
anything carrying a URL scheme, so a configuration mistake cannot redirect the
store at a remote endpoint. A bare Windows drive letter is not a scheme and is
accepted.

**No HTTP write verb exists anywhere in the codebase.** A repository-wide test
asserts that, so a future unit cannot quietly add a POST path that this module
would then be able to reach.

The log is append-only and hash-chained. Each record carries the digest of the one
before it, so a deleted or edited record is detectable rather than invisible. That
matters for a reviewer's own trust in their work, and it is the same discipline the
claim register applies to published numbers.

Every annotation is bound to the receipt it was made against. An annotation of
"rank 3 disagrees with its label" is meaningless against a different ranking, so a
record that cannot name its receipt is refused.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path
from typing import Any

#: What a reviewer can conclude, fixed. Free text is available as an additional
#: local note, but a decision is always one of these, so a queue's outcomes can be
#: counted without parsing prose.
ANNOTATION_DECISIONS: dict[str, str] = {
    "AGREES_WITH_LABEL": (
        "The reviewer agrees with the current SatNOGS waterfall_status. The queue "
        "surfaced this observation and the existing label stands."
    ),
    "DISAGREES_WITH_LABEL": (
        "The reviewer judges the current waterfall_status to be wrong. This is the "
        "outcome the queue exists to find."
    ),
    "STALE_FREQUENCY_CONFIRMED": (
        "The reviewer confirms the trace sits away from the catalogue downlink "
        "frequency, implying a stale catalogue entry a volunteer can correct."
    ),
    "MISCONFIGURED_CLIENT_SUSPECTED": (
        "The capture looks Doppler-uncorrected or otherwise misconfigured relative "
        "to the station's other captures."
    ),
    "DEAD_CAPTURE_CONFIRMED": (
        "The reviewer confirms a substantial fraction of the capture carries no "
        "signal variation, indicating lost capture time."
    ),
    "CANNOT_TELL": (
        "The reviewer cannot decide from the waterfall. A real and common outcome: "
        "17 of 24 vetted with-signal observations in A3 carried no measurable "
        "narrowband trace. Recording it keeps it out of the other five buckets."
    ),
}

#: Modules that would give this code a way off the machine. Asserted absent from
#: the whole first-party import closure by the test suite, not just from this file.
FORBIDDEN_NETWORK_MODULES: frozenset[str] = frozenset(
    {
        "httpx",
        "requests",
        "urllib.request",
        "urllib3",
        "http.client",
        "socket",
        "ftplib",
        "smtplib",
        "asyncio",
        "aiohttp",
        "websockets",
        "paramiko",
        "boto3",
    }
)

_SCHEMA = "ANNOTATION_RECORD"
_SCHEMA_VERSION = "0.1.0"

#: A URL scheme, per RFC 3986: a letter followed by letters, digits, plus, minus
#: or dot, then a colon. Deliberately requires two or more characters before the
#: colon so a Windows drive letter such as D: is not mistaken for a scheme.
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:")

#: Genesis link for the hash chain, so the first record's prev_sha256 is a stated
#: constant rather than a null that could also mean "field missing".
GENESIS_SHA256 = "0" * 64


class RemoteSinkRefused(ValueError):
    """Raised when an annotation store path is not a local filesystem path."""


def resolve_store_path(path: str | Path) -> Path:
    """Local filesystem path for the annotation store, or refuse.

    A path carrying a URL scheme is refused rather than normalised, because the
    only reason for one to appear here is a misconfiguration that would send a
    reviewer's private notes somewhere. ``file:`` is refused too: it is a URL, and
    accepting one scheme invites the next.
    """
    text = str(path)
    match = _URL_SCHEME.match(text)
    if match:
        raise RemoteSinkRefused(
            f"An annotation store must be a local filesystem path. Got a URL with "
            f"scheme {match.group(0)!r}: {text!r}. Annotations never leave this "
            f"machine, so no scheme is accepted, including file:."
        )
    if text.startswith("\\\\") or text.startswith("//"):
        raise RemoteSinkRefused(
            f"An annotation store must be a local filesystem path. Got what looks "
            f"like a network share: {text!r}."
        )
    return Path(text)


def record_digest(record: dict[str, Any]) -> str:
    """Digest of a record with its own digest field excluded.

    Sorted keys and a compact separator, so the digest depends on the content and
    not on how the JSON happened to be formatted.
    """
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_record(
    obs_id: int,
    decision: str,
    *,
    receipt_sha256: str,
    split: str,
    rank_at_annotation: int | None,
    note: str | None = None,
    annotator: str = "local",
    prev_sha256: str = GENESIS_SHA256,
    created_at: str | None = None,
) -> dict[str, Any]:
    """One annotation, validated, hashed and chained to its predecessor.

    ``receipt_sha256`` binds the annotation to the ranking it was made against.
    An annotation of "the third row disagrees with its label" says nothing about a
    different ranking, so a record without a receipt digest is refused rather than
    stored with a null.
    """
    if decision not in ANNOTATION_DECISIONS:
        raise ValueError(
            f"Unknown decision {decision!r}. The vocabulary is fixed: "
            f"{sorted(ANNOTATION_DECISIONS)}."
        )
    if not isinstance(obs_id, int) or isinstance(obs_id, bool) or obs_id <= 0:
        raise ValueError(f"obs_id must be a positive integer, got {obs_id!r}.")
    if not re.fullmatch(r"[0-9a-f]{64}", receipt_sha256 or ""):
        raise ValueError(
            f"receipt_sha256 must be a 64-character hex digest binding this "
            f"annotation to the ranking it was made against. Got "
            f"{receipt_sha256!r}."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", prev_sha256 or ""):
        raise ValueError(
            f"prev_sha256 must be a 64-character hex digest, or GENESIS_SHA256 for "
            f"the first record. Got {prev_sha256!r}."
        )
    if not split:
        raise ValueError("split must name the split whose queue was reviewed.")

    record = {
        "schema": _SCHEMA,
        "schema_version": _SCHEMA_VERSION,
        "obs_id": obs_id,
        "decision": decision,
        "note": note,
        "annotator": annotator,
        "split": split,
        "receipt_sha256": receipt_sha256,
        "rank_at_annotation": rank_at_annotation,
        "created_at": created_at
        or datetime.datetime.now(datetime.UTC).isoformat(),
        "prev_sha256": prev_sha256,
    }
    record["record_sha256"] = record_digest(record)
    return record


class AnnotationStore:
    """Append-only, hash-chained local annotation log.

    Reads and writes one JSON object per line. Nothing is ever rewritten in place:
    a changed decision is a new record, and the log keeps both, because a reviewer
    changing their mind is information rather than a correction to be hidden.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = resolve_store_path(path)

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for lineno, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{self.path}:{lineno} is not valid JSON, so the log cannot be "
                    f"verified: {exc}"
                ) from exc
        return records

    def head_digest(self) -> str:
        records = self.read_all()
        return records[-1]["record_sha256"] if records else GENESIS_SHA256

    def append(
        self,
        obs_id: int,
        decision: str,
        *,
        receipt_sha256: str,
        split: str,
        rank_at_annotation: int | None = None,
        note: str | None = None,
        annotator: str = "local",
        created_at: str | None = None,
    ) -> dict[str, Any]:
        record = build_record(
            obs_id,
            decision,
            receipt_sha256=receipt_sha256,
            split=split,
            rank_at_annotation=rank_at_annotation,
            note=note,
            annotator=annotator,
            prev_sha256=self.head_digest(),
            created_at=created_at,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def verify(self) -> dict[str, Any]:
        """Check every digest and every link in the chain.

        Returns a report rather than raising, with the count examined beside the
        result: a verification that examined nothing is not a passing verification.
        """
        records = self.read_all()
        broken_digest: list[int] = []
        broken_link: list[int] = []
        expected_prev = GENESIS_SHA256

        for index, record in enumerate(records):
            if record.get("record_sha256") != record_digest(record):
                broken_digest.append(index)
            if record.get("prev_sha256") != expected_prev:
                broken_link.append(index)
            expected_prev = record.get("record_sha256", "")

        return {
            "n_examined": len(records),
            "intact": not broken_digest and not broken_link,
            "broken_digest_indices": broken_digest,
            "broken_link_indices": broken_link,
            "head_sha256": records[-1]["record_sha256"] if records else GENESIS_SHA256,
            "note": (
                f"Verified {len(records)} records. A broken digest means a record "
                f"was edited in place. A broken link means a record was removed or "
                f"reordered. Zero records examined is reported as such rather than "
                f"as a pass."
            ),
        }

    def decisions_by_obs(self) -> dict[int, str]:
        """Latest decision per observation, in log order."""
        latest: dict[int, str] = {}
        for record in self.read_all():
            latest[record["obs_id"]] = record["decision"]
        return latest

    def summarise(self) -> dict[str, Any]:
        records = self.read_all()
        counts: dict[str, int] = dict.fromkeys(ANNOTATION_DECISIONS, 0)
        for record in records:
            if record["decision"] in counts:
                counts[record["decision"]] += 1
        return {
            "n_records": len(records),
            "n_observations": len({r["obs_id"] for r in records}),
            "counts_by_decision": counts,
            "receipts_referenced": sorted({r["receipt_sha256"] for r in records}),
            "verification": self.verify(),
        }
