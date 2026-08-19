"""Local annotation store, and the proof that it cannot write to SatNOGS (C3).

The plan's requirement is that a test assert no outbound write to SatNOGS is even
possible. "Possible" is stronger than "does not happen", so three things are
checked and each one closes a different route.

The import closure: the annotation module, and everything first-party it imports
transitively, contains no module that can open a socket. This is walked rather than
eyeballed, because a clean import list at the top of one file says nothing about
what its imports import.

The sink: the store refuses any path carrying a URL scheme, so a configuration
mistake cannot redirect a reviewer's notes at a remote endpoint.

The codebase: no HTTP write verb exists anywhere in non-test code, so a future unit
cannot add a POST path that this module could then reach.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from pipeline.tracetriage.annotate import (
    ANNOTATION_DECISIONS,
    FORBIDDEN_NETWORK_MODULES,
    GENESIS_SHA256,
    AnnotationStore,
    RemoteSinkRefused,
    build_record,
    record_digest,
    resolve_store_path,
)

_REPO = Path(__file__).resolve().parents[1]
_ANNOTATE = _REPO / "pipeline" / "tracetriage" / "annotate.py"
_RECEIPT_SHA = "a" * 64


# ---------------------------------------------------------------------------
# No outbound write is possible
# ---------------------------------------------------------------------------


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def _first_party_path(module: str) -> Path | None:
    if not module.startswith("pipeline"):
        return None
    candidate = _REPO / Path(module.replace(".", "/") + ".py")
    if candidate.exists():
        return candidate
    package = _REPO / Path(module.replace(".", "/")) / "__init__.py"
    return package if package.exists() else None


def _import_closure(entry: Path) -> tuple[set[str], set[Path]]:
    """Every module named anywhere in the first-party import graph from ``entry``."""
    seen_files = {entry}
    all_imports: set[str] = set()
    frontier = [entry]
    while frontier:
        current = frontier.pop()
        imports = _imports_of(current)
        all_imports |= imports
        for module in imports:
            path = _first_party_path(module)
            if path is not None and path not in seen_files:
                seen_files.add(path)
                frontier.append(path)
    return all_imports, seen_files


def test_annotation_import_closure_has_no_network_capability():
    """Walked, not eyeballed.

    A clean import list at the top of one file says nothing about what its imports
    import. The closure here is expected to be small; if it grows to include the
    snapshot fetcher, which legitimately uses httpx read-only, this fails and the
    dependency has to be justified rather than absorbed.
    """
    imports, files = _import_closure(_ANNOTATE)

    offenders = sorted(
        module
        for module in imports
        if module in FORBIDDEN_NETWORK_MODULES
        or module.split(".")[0] in {m.split(".")[0] for m in FORBIDDEN_NETWORK_MODULES}
    )
    assert not offenders, (
        f"annotate.py's import closure reaches {offenders}. Files walked: "
        f"{sorted(p.name for p in files)}"
    )
    # The check has to have examined something. A closure of one file that imports
    # nothing would pass vacuously.
    assert len(imports) >= 4, f"only {len(imports)} imports examined: {sorted(imports)}"


def test_no_http_write_verb_exists_in_non_test_code():
    """A future unit cannot add a POST path for this module to reach.

    Scans first-party source for HTTP write verbs on any client object. The
    snapshot fetcher is included in the scan and is expected to be clean: it reads
    the SatNOGS API and never writes to it.
    """
    offenders: list[str] = []
    for path in sorted((_REPO / "pipeline").rglob("*.py")) + sorted(
        (_REPO / "scripts").rglob("*.py")
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"post", "put", "patch", "delete"}
            ):
                offenders.append(
                    f"{path.relative_to(_REPO)}:{node.lineno} .{node.func.attr}()"
                )
    assert not offenders, f"HTTP write verbs found: {offenders}"


def test_a_url_sink_is_refused():
    for bad in [
        "https://network.satnogs.org/api/observations/",
        "http://localhost:8000/annotations",
        "file:///C:/annotations.jsonl",
        "ftp://example.org/notes",
        "s3://bucket/notes.jsonl",
        r"\\fileserver\share\notes.jsonl",
        "//fileserver/share/notes.jsonl",
    ]:
        with pytest.raises(RemoteSinkRefused):
            resolve_store_path(bad)


def test_a_windows_drive_letter_is_not_a_url_scheme():
    """The scheme test must not reject an ordinary local path.

    This asserted the resolved basename of a backslash-separated path, which made it a
    guaranteed failure on the Linux runner the workflow declares. A backslash is an
    ordinary character in a POSIX path, so the basename of a Windows-style path is the
    whole string on Linux and the filename on Windows. The function under test does not
    split paths and never claimed to. What it claims is that a drive letter is not read
    as a one-character URL scheme, and that claim holds identically on both platforms.
    """
    for text in (
        r"D:\annotations\notes.jsonl",
        "C:/Users/x/notes.jsonl",
        "artifacts/annotations/notes.jsonl",
    ):
        # Must not raise. Widening _URL_SCHEME to match a drive letter fails here.
        resolve_store_path(text)

    # The basename is asserted only for the forms that parse identically on both
    # platforms, so this stays a check on the guard rather than on pathlib.
    assert resolve_store_path("artifacts/annotations/notes.jsonl").name == "notes.jsonl"
    assert resolve_store_path("C:/Users/x/notes.jsonl").name == "notes.jsonl"


def test_the_store_refuses_a_url_at_construction(tmp_path):
    with pytest.raises(RemoteSinkRefused):
        AnnotationStore("https://network.satnogs.org/api/")
    # And a local path is accepted, so the guard is not simply refusing everything.
    assert AnnotationStore(tmp_path / "notes.jsonl").path.name == "notes.jsonl"


# ---------------------------------------------------------------------------
# Record validation
# ---------------------------------------------------------------------------


def test_an_annotation_must_name_the_receipt_it_was_made_against():
    """An annotation of "rank 3 disagrees" says nothing about a different ranking."""
    for bad in ["", None, "not-a-digest", "a" * 63, "A" * 64, "g" * 64]:
        with pytest.raises(ValueError, match="receipt_sha256"):
            build_record(
                14740031,
                "DISAGREES_WITH_LABEL",
                receipt_sha256=bad,
                split="chronological",
                rank_at_annotation=3,
            )


def test_an_unknown_decision_is_refused():
    with pytest.raises(ValueError, match="Unknown decision"):
        build_record(
            14740031,
            "LOOKS_FINE_TO_ME",
            receipt_sha256=_RECEIPT_SHA,
            split="chronological",
            rank_at_annotation=1,
        )


def test_a_boolean_is_not_an_observation_id():
    """True is an int in Python, and would silently become observation 1."""
    with pytest.raises(ValueError, match="positive integer"):
        build_record(
            True,
            "AGREES_WITH_LABEL",
            receipt_sha256=_RECEIPT_SHA,
            split="chronological",
            rank_at_annotation=1,
        )


def test_split_is_required():
    with pytest.raises(ValueError, match="split must name"):
        build_record(
            14740031,
            "AGREES_WITH_LABEL",
            receipt_sha256=_RECEIPT_SHA,
            split="",
            rank_at_annotation=1,
        )


def test_digest_ignores_json_formatting():
    a = build_record(
        1, "CANNOT_TELL", receipt_sha256=_RECEIPT_SHA, split="s",
        rank_at_annotation=1, created_at="2026-08-18T00:00:00+00:00",
    )
    b = dict(reversed(list(a.items())))
    assert record_digest(a) == record_digest(b), (
        "the digest must depend on content, not on key order"
    )


# ---------------------------------------------------------------------------
# The append-only hash chain
# ---------------------------------------------------------------------------


def test_the_log_is_append_only_and_chained(tmp_path):
    store = AnnotationStore(tmp_path / "notes.jsonl")
    assert store.head_digest() == GENESIS_SHA256

    first = store.append(
        14740031, "STALE_FREQUENCY_CONFIRMED",
        receipt_sha256=_RECEIPT_SHA, split="chronological", rank_at_annotation=1,
    )
    second = store.append(
        14746118, "AGREES_WITH_LABEL",
        receipt_sha256=_RECEIPT_SHA, split="chronological", rank_at_annotation=2,
    )

    assert first["prev_sha256"] == GENESIS_SHA256
    assert second["prev_sha256"] == first["record_sha256"]
    report = store.verify()
    assert report["intact"] is True
    assert report["n_examined"] == 2


def test_a_changed_mind_is_a_new_record_not_an_edit(tmp_path):
    store = AnnotationStore(tmp_path / "notes.jsonl")
    store.append(
        14740031, "CANNOT_TELL",
        receipt_sha256=_RECEIPT_SHA, split="chronological", rank_at_annotation=1,
    )
    store.append(
        14740031, "DISAGREES_WITH_LABEL",
        receipt_sha256=_RECEIPT_SHA, split="chronological", rank_at_annotation=1,
    )

    assert len(store.read_all()) == 2, "both records are kept"
    assert store.decisions_by_obs()[14740031] == "DISAGREES_WITH_LABEL"
    assert store.verify()["intact"] is True


def test_an_edited_record_is_detected(tmp_path):
    path = tmp_path / "notes.jsonl"
    store = AnnotationStore(path)
    store.append(
        1, "AGREES_WITH_LABEL",
        receipt_sha256=_RECEIPT_SHA, split="s", rank_at_annotation=1,
    )
    store.append(
        2, "AGREES_WITH_LABEL",
        receipt_sha256=_RECEIPT_SHA, split="s", rank_at_annotation=2,
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["decision"] = "DISAGREES_WITH_LABEL"
    lines[0] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = AnnotationStore(path).verify()
    assert report["intact"] is False
    assert 0 in report["broken_digest_indices"]


def test_a_removed_record_is_detected(tmp_path):
    path = tmp_path / "notes.jsonl"
    store = AnnotationStore(path)
    for i in (1, 2, 3):
        store.append(
            i, "AGREES_WITH_LABEL",
            receipt_sha256=_RECEIPT_SHA, split="s", rank_at_annotation=i,
        )

    lines = path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = AnnotationStore(path).verify()
    assert report["intact"] is False
    assert report["broken_link_indices"], "a removed record breaks the chain"


def test_an_empty_log_reports_zero_examined_not_a_pass(tmp_path):
    """Zero records verified is reported as zero, not as a clean bill of health."""
    report = AnnotationStore(tmp_path / "absent.jsonl").verify()
    assert report["n_examined"] == 0
    assert "Zero records examined is reported as such" in report["note"]


def test_a_corrupt_line_fails_loudly(tmp_path):
    path = tmp_path / "notes.jsonl"
    path.write_text('{"obs_id": 1}\nnot json at all\n', encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        AnnotationStore(path).read_all()


def test_summary_counts_every_decision_including_the_unused(tmp_path):
    store = AnnotationStore(tmp_path / "notes.jsonl")
    store.append(
        1, "CANNOT_TELL",
        receipt_sha256=_RECEIPT_SHA, split="s", rank_at_annotation=1,
    )
    summary = store.summarise()

    assert summary["n_records"] == 1
    assert summary["n_observations"] == 1
    assert set(summary["counts_by_decision"]) == set(ANNOTATION_DECISIONS), (
        "an unused decision reports zero rather than being absent, so a reader can "
        "tell 'nobody chose it' from 'it is not an option'"
    )
    assert summary["counts_by_decision"]["CANNOT_TELL"] == 1
    assert summary["counts_by_decision"]["AGREES_WITH_LABEL"] == 0
    assert summary["receipts_referenced"] == [_RECEIPT_SHA]


# ---------------------------------------------------------------------------
# The ratified contract
# ---------------------------------------------------------------------------


_CONTRACT_PATH = _REPO / "contracts" / "annotation_record.schema.json"


def _annotation_validator():
    from jsonschema import validators  # noqa: PLC0415

    schema = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    return validators.validator_for(schema)(schema)


def _valid_record() -> dict:
    return build_record(
        14740031,
        "STALE_FREQUENCY_CONFIRMED",
        receipt_sha256=_RECEIPT_SHA,
        split="chronological",
        rank_at_annotation=1,
        note="Trace sits well off the catalogue downlink.",
        created_at="2026-08-18T01:00:00+00:00",
    )


def test_a_built_record_validates_against_the_contract():
    _annotation_validator().validate(_valid_record())


def test_decision_vocabulary_matches_the_contract():
    schema = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    enum = set(schema["properties"]["decision"]["enum"])
    assert enum == set(ANNOTATION_DECISIONS), (
        f"only in schema: {sorted(enum - set(ANNOTATION_DECISIONS))}, "
        f"only in code: {sorted(set(ANNOTATION_DECISIONS) - enum)}"
    )


@pytest.mark.parametrize(
    "mutate,why",
    [
        (lambda r: r.pop("receipt_sha256"), "no receipt digest"),
        (lambda r: r.update(receipt_sha256=None), "null receipt digest"),
        (lambda r: r.update(receipt_sha256="short"), "malformed receipt digest"),
        (lambda r: r.update(decision="LOOKS_FINE"), "decision outside the vocabulary"),
        (lambda r: r.update(obs_id=0), "non-positive observation id"),
        (lambda r: r.update(obs_id="14740031"), "observation id as a string"),
        (lambda r: r.pop("prev_sha256"), "no chain link"),
        (lambda r: r.update(prev_sha256=None), "null chain link"),
        (lambda r: r.pop("record_sha256"), "no self digest"),
        (lambda r: r.update(split=""), "empty split"),
        (lambda r: r.pop("split"), "no split"),
        (lambda r: r.update(annotator=""), "empty annotator"),
        (lambda r: r.update(schema="SOMETHING_ELSE"), "wrong schema tag"),
        (lambda r: r.update(schema_version="1"), "non-semver version"),
        (lambda r: r.update(rank_at_annotation=0), "rank below one"),
        (lambda r: r.update(exported_to="https://network.satnogs.org"), "unknown key"),
    ],
)
def test_the_contract_refuses_each_broken_shape(mutate, why):
    """Sixteen negative cases, so the contract is known to reject and not merely
    to accept. A schema tested only against valid input is an assertion that the
    happy path parses."""
    record = _valid_record()
    mutate(record)
    assert not _annotation_validator().is_valid(record), f"contract accepted: {why}"


@pytest.mark.parametrize(
    "weaken,why",
    [
        (lambda s: s["required"].remove("receipt_sha256"), "receipt no longer required"),
        (lambda s: s.update(additionalProperties=True), "unknown keys allowed"),
        (
            lambda s: s["properties"]["decision"].pop("enum"),
            "decision vocabulary opened",
        ),
        (
            lambda s: s["properties"]["receipt_sha256"].pop("pattern"),
            "digest format unchecked",
        ),
    ],
)
def test_weakening_the_contract_is_noticed(weaken, why):
    """The mutation discipline applied to the schema itself.

    Each weakening must make at least one negative case pass, which proves the
    corresponding constraint is what was doing the work rather than something else
    in the schema catching the same input by accident.
    """
    from jsonschema import validators  # noqa: PLC0415

    schema = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    weaken(schema)
    weakened = validators.validator_for(schema)(schema)

    broken = [
        {**_valid_record(), "receipt_sha256": "short"},
        {**_valid_record(), "exported_to": "https://network.satnogs.org"},
        {**_valid_record(), "decision": "LOOKS_FINE"},
    ]
    record_without_receipt = _valid_record()
    record_without_receipt.pop("receipt_sha256")
    broken.append(record_without_receipt)

    assert any(weakened.is_valid(r) for r in broken), (
        f"weakening the schema so that {why} changed nothing, so that constraint "
        f"was not the one rejecting these records"
    )
