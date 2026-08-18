"""Contract-level tests.

Two jobs. First, every contracts/*.schema.json must be a legal JSON Schema and must
be ratified, so a malformed contract fails here instead of failing later inside a
snapshot run. Second, the invariants that used to live only in ``description`` text
are exercised directly: a schema that documents a rule it does not enforce is
documentation, and the rules below are the ones whose silent violation would be
expensive (a wrong pixel mapping, a leaky split, an unexplained abstention).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema.validators import validator_for

REPO = Path(__file__).resolve().parents[1]
CONTRACT_DIR = REPO / "contracts"
CONTRACTS = sorted(CONTRACT_DIR.glob("*.schema.json"))
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

EXPECTED = {
    "annotation_record",
    "dataset_manifest",
    "fusion_receipt",
    "queue_receipt",
    "source_observation",
    "split_manifest",
    "triage_receipt",
    "waterfall_geometry",
}


def load(name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def validator(name: str):
    schema = load(name)
    return validator_for(schema)(schema)


def is_valid(name: str, doc: dict[str, Any]) -> bool:
    return validator(name).is_valid(doc)


def test_every_expected_contract_exists() -> None:
    assert {p.name.removesuffix(".schema.json") for p in CONTRACTS} == EXPECTED


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_schema_is_legal_json_schema(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    validator_for(schema).check_schema(schema)


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_schema_is_ratified_and_versioned(path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema.get("status") == "ratified"
    assert SEMVER.match(str(schema.get("schema_version", "")))


# --- ENG-S1: closed roots and pinned document versions -----------------------
#
# Six of the eight contracts had an open root and only two pinned the version a
# document claims, so a receipt written by an older script validated against the
# current schema and was read as current. The two tests below are the structural
# form of that finding: an open root is now a decision that has to be written down,
# and a version property that is not a const fails.

# Documents that carry the version under an underscored name because the record is
# an upstream shape and the underscore marks the fields we add to it.
VERSION_PROPERTY = {"source_observation": "_schema_version"}

# Contracts with a committed artifact, so the document can be checked against the
# schema rather than against a fixture written to agree with it.
COMMITTED_DOCUMENTS = {
    "fusion_receipt": "artifacts/FUSION_RECEIPT.json",
    "queue_receipt": "artifacts/QUEUE_RECEIPT.json",
    "triage_receipt": "artifacts/TRIAGE_RECEIPT.json",
    "dataset_manifest": "artifacts/DATASET_MANIFEST.json",
    "split_manifest": "artifacts/SPLIT_MANIFEST.json",
}


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_schema_root_is_closed_or_says_why_it_is_not(path: Path) -> None:
    """An open root is allowed, but only as a stated decision.

    ``additionalProperties: false`` at the root is what stops a key nothing declares
    from travelling in a receipt unnoticed. One contract legitimately cannot close:
    ``source_observation`` describes a SatNOGS API record that upstream extends
    without telling us, so closing it would turn a new upstream field into a failed
    build. That case declares ``open_root_reason`` instead, which is a sentence a
    reader can disagree with rather than an omission nobody sees.
    """
    schema = json.loads(path.read_text(encoding="utf-8"))
    name = path.name.removesuffix(".schema.json")
    if schema.get("additionalProperties") is False:
        assert "open_root_reason" not in schema, (
            f"{name}: closed root and an open-root reason are contradictory"
        )
        return
    reason = schema.get("open_root_reason")
    assert isinstance(reason, str) and len(reason) > 80, (
        f"{name}: the root is open with no stated reason. Either close it with "
        '"additionalProperties": false, or declare open_root_reason saying which '
        "documents would break if it were closed."
    )


@pytest.mark.parametrize("path", CONTRACTS, ids=lambda p: p.name)
def test_document_version_is_pinned_to_the_contract_version(path: Path) -> None:
    """The version a document claims must be a const, and must be this contract's.

    A ``{"type": "string"}`` version accepts any version, and a semver ``pattern``
    proves only that the string is shaped like a version. Both were present before
    this test: they check the format of the claim and never the claim.
    """
    schema = json.loads(path.read_text(encoding="utf-8"))
    name = path.name.removesuffix(".schema.json")
    prop = VERSION_PROPERTY.get(name, "schema_version")
    declared = schema.get("properties", {}).get(prop)
    assert declared is not None, f"{name}: no {prop} property, so a document cannot claim a version"
    assert "const" in declared, (
        f"{name}: {prop} is not pinned with a const, so a document written against "
        "any earlier version of this contract still validates"
    )
    assert declared["const"] == schema["schema_version"], (
        f"{name}: {prop} pins {declared['const']!r} while the contract is at "
        f"{schema['schema_version']!r}. Bumping one without the other is how a "
        "document comes to claim a version that never existed."
    )


@pytest.mark.parametrize("name,rel", sorted(COMMITTED_DOCUMENTS.items()))
def test_committed_document_validates_and_claims_the_pinned_version(
    name: str, rel: str
) -> None:
    """The committed artifact, not a fixture, against the current contract.

    A fixture written beside a schema tends to agree with it. These are the files a
    judge opens.
    """
    doc = json.loads((REPO / rel).read_text(encoding="utf-8"))
    schema = load(name)
    errors = sorted(validator(name).iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        where = "/".join(str(x) for x in errors[0].absolute_path)
        raise AssertionError(f"{rel}: {errors[0].message} at /{where}")
    prop = VERSION_PROPERTY.get(name, "schema_version")
    assert doc.get(prop) == schema["schema_version"], (
        f"{rel} claims {doc.get(prop)!r} against contract {schema['schema_version']!r}"
    )


@pytest.mark.parametrize("name,rel", sorted(COMMITTED_DOCUMENTS.items()))
def test_an_older_version_or_an_undeclared_root_key_is_rejected(
    name: str, rel: str
) -> None:
    """The reviewer's two mutations, as a test.

    Both of these validated before ENG-S1: a receipt claiming a prehistoric version,
    and a receipt carrying a root key the contract never heard of. The second is the
    one that matters in practice, because that is how a second copy of a field
    (``gate5_FINAL_v2``) gets published beside the real one.
    """
    doc = json.loads((REPO / rel).read_text(encoding="utf-8"))
    prop = VERSION_PROPERTY.get(name, "schema_version")

    stale = dict(doc)
    stale[prop] = "0.0.1-prehistoric"
    assert not is_valid(name, stale), f"{rel}: an older version still validates"

    junked = dict(doc)
    junked["gate5_FINAL_v2"] = {"verdict": "PASSED"}
    assert not is_valid(name, junked), f"{rel}: an undeclared root key still validates"


# --- waterfall_geometry: null exactly when derivation failed -----------------

PLOT_BOX = {"x0": 66, "y0": 60, "x1": 686, "y1": 1560}
CROP_BOX = {"x0": 67, "y0": 61, "x1": 685, "y1": 1559}


def geometry(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "observation_id": 14513023,
        "image_width": 836,
        "image_height": 1603,
        "plot_box": PLOT_BOX,
        "crop_box": CROP_BOX,
        "hz_per_px": 123.46,
        "seconds_per_px": 0.5,
        "centre_px": 310.0,
        "derivation": "axis_ticks",
        "derivation_confidence": 1.0,
        "degraded": None,
    }
    doc.update(overrides)
    return doc


def test_geometry_accepts_a_clean_derivation() -> None:
    assert is_valid("waterfall_geometry", geometry())


def test_geometry_accepts_a_named_failure() -> None:
    failed = geometry(
        crop_box=None,
        hz_per_px=None,
        seconds_per_px=None,
        centre_px=None,
        derivation="failed",
        derivation_confidence=None,
        degraded="NO_AXIS_DETECTED",
    )
    assert is_valid("waterfall_geometry", failed)


def test_geometry_rejects_success_without_hz_per_px() -> None:
    doc = geometry()
    del doc["hz_per_px"]
    assert not is_valid("waterfall_geometry", doc)


def test_geometry_rejects_success_with_null_hz_per_px() -> None:
    assert not is_valid("waterfall_geometry", geometry(hz_per_px=None))


def test_geometry_rejects_failure_that_keeps_a_pixel_mapping() -> None:
    doc = geometry(derivation="failed", degraded="NO_AXIS_DETECTED")
    assert not is_valid("waterfall_geometry", doc)


def test_geometry_rejects_failure_without_a_reason_code() -> None:
    doc = geometry(
        crop_box=None,
        hz_per_px=None,
        seconds_per_px=None,
        centre_px=None,
        derivation="failed",
        derivation_confidence=None,
        degraded=None,
    )
    assert not is_valid("waterfall_geometry", doc)


def test_geometry_rejects_a_per_family_constant_fallback() -> None:
    """Hz/px varied 54% across three images and was never measured as stable
    within a client family, so there is deliberately no fallback mode."""
    assert not is_valid("waterfall_geometry", geometry(derivation="client_family_fallback"))


def test_geometry_allows_null_centre_px_on_a_good_derivation() -> None:
    """rx-freq is absent on the 6% of records with no client_metadata. That
    blocks centre_px without invalidating a correctly read axis."""
    assert is_valid("waterfall_geometry", geometry(centre_px=None))


# --- split_manifest: a recorded leakage failure must not validate ------------


_ALL_SPLITS = ["chronological", "cold_station", "cold_transmitter", "cold_combined"]


def split_manifest(**overrides: Any) -> dict[str, Any]:
    partition = {"train": [1, 2], "calibration": [3], "test": [4]}

    def check(applies_to: list[str] | None = None) -> dict[str, Any]:
        return {
            "passed": True,
            "applies_to": applies_to or _ALL_SPLITS,
            "n_examined": 4,
        }

    def assertion() -> dict[str, Any]:
        """test_set_untouched, the one entry the build cannot measure."""
        return {
            "result": "ASSERTED_NOT_MEASURABLE_HERE",
            "applies_to": _ALL_SPLITS,
            "n_examined": None,
            "test_id_digests": {name: "a" * 64 for name in _ALL_SPLITS},
            "rationale": "Test ids are emitted, never loaded or scored here.",
        }

    doc: dict[str, Any] = {
        # Required as of split_manifest 0.5.0. A fixture that omits it would
        # pass a test the artifact cannot pass.
        "schema_version": "0.5.0",
        "snapshot_id": "snap-2026-08-17-stage1",
        "frozen_at": "2026-08-17T00:00:00Z",
        "sampling_design": "Chronological block, stations reserved for cold pools.",
        "grouping_keys": ["ground_station", "transmitter_uuid"],
        "splits": {name: partition for name in _ALL_SPLITS},
        "leakage_checks": {
            "no_transmitter_across_splits": check(
                ["chronological", "cold_transmitter", "cold_combined"]
            ),
            "no_station_across_splits": check(["cold_station", "cold_combined"]),
            "no_revolution_across_splits": check(),
            "no_duplicate_image_across_splits": check(),
            "no_future_feature_in_train": check(),
            "test_set_untouched": assertion(),
        },
    }
    doc.update(overrides)
    return doc


def test_split_manifest_accepts_a_clean_freeze() -> None:
    assert is_valid("split_manifest", split_manifest())


def test_split_manifest_rejects_a_failed_leakage_check() -> None:
    doc = split_manifest()
    doc["leakage_checks"]["no_duplicate_image_across_splits"]["passed"] = False
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_a_bare_boolean_leakage_check() -> None:
    """A check must say which splits it covers, so a bare true is not enough.

    Schema 0.2.1 accepted ``true`` here. That is how the artifact came to assert
    "no transmitter crosses" while its own audit exempted two split types, and why
    a stale exemption could hide 12 real crossings without invalidating the file.
    """
    doc = split_manifest()
    doc["leakage_checks"]["no_transmitter_across_splits"] = True
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_a_check_that_examined_nothing() -> None:
    """A check with nothing to examine passes for free, so zero is invalid."""
    doc = split_manifest()
    doc["leakage_checks"]["no_station_across_splits"]["n_examined"] = 0
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_a_pass_on_the_unmeasurable_check() -> None:
    """test_set_untouched cannot claim a pass, because nothing measured it.

    Schema 0.3.0 accepted ``passed: true`` with ``n_examined: 1349`` here, and
    1349 is the count of emitted test ids: a different property than whether
    those ids were touched. Both halves are now unrepresentable.
    """
    doc = split_manifest()
    doc["leakage_checks"]["test_set_untouched"] = {
        "passed": True,
        "applies_to": _ALL_SPLITS,
        "n_examined": 1349,
    }
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_an_assertion_that_carries_a_count() -> None:
    """A count under a null-only field is a measurement of something else."""
    doc = split_manifest()
    doc["leakage_checks"]["test_set_untouched"]["n_examined"] = 1349
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_an_assertion_that_carries_a_pass() -> None:
    """passed is forbidden on the assertion, not merely discouraged."""
    doc = split_manifest()
    doc["leakage_checks"]["test_set_untouched"]["passed"] = True
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_an_assertion_with_no_digests() -> None:
    """The digests are the mechanism that replaces the missing measurement.

    Drop them and the entry is a bare sentence, which is what the third outcome
    exists to avoid. Fewer than four is also invalid: one per frozen test set.
    """
    doc = split_manifest()
    del doc["leakage_checks"]["test_set_untouched"]["test_id_digests"]
    assert not is_valid("split_manifest", doc)

    doc = split_manifest()
    doc["leakage_checks"]["test_set_untouched"]["test_id_digests"] = {
        "chronological": "b" * 64
    }
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_an_assertion_with_a_bad_digest() -> None:
    """A digest that is not 64 hex characters cannot pin anything."""
    doc = split_manifest()
    doc["leakage_checks"]["test_set_untouched"]["test_id_digests"]["cold_station"] = "nope"
    assert not is_valid("split_manifest", doc)


def test_split_manifest_rejects_a_check_with_no_scope() -> None:
    doc = split_manifest()
    del doc["leakage_checks"]["no_revolution_across_splits"]["applies_to"]
    assert not is_valid("split_manifest", doc)

    doc = split_manifest()
    doc["leakage_checks"]["no_revolution_across_splits"]["applies_to"] = []
    assert not is_valid("split_manifest", doc)


def test_split_manifest_accepts_an_excluded_partition() -> None:
    """cold_combined leaves observations in no partition; that has to be expressible."""
    doc = split_manifest()
    doc["splits"]["cold_combined"] = {
        "train": [1], "calibration": [2], "test": [3], "excluded": [4, 5],
    }
    assert is_valid("split_manifest", doc)


def test_split_manifest_requires_a_sampling_design() -> None:
    doc = split_manifest()
    del doc["sampling_design"]
    assert not is_valid("split_manifest", doc)


# --- triage_receipt: abstain carries its reason ------------------------------


def receipt(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "observation_id": 14513023,
        # Required as of triage_receipt 0.3.0.
        "schema_version": "0.3.0",
        "snapshot_id": "snap-2026-08-17-stage1",
        "model_checksum": "a" * 64,
        "generated_at": "2026-08-17T00:00:00Z",
        "evidence": {"artifact_usable": True, "physics_available": True},
        "scores": {"calibrated_probability": 0.61},
        "decision": "flag_for_review",
        "reason_codes": ["CORRIDOR_MISS"],
        "provenance": {
            "source_url": "https://network.satnogs.org/observations/14513023/",
            "retrieved_at": "2026-08-16T00:00:00Z",
            "license": "CC BY-SA 4.0",
            "api_label": "with-signal",
            "label_origin": "satnogs_vet",
        },
    }
    doc.update(overrides)
    return doc


def test_receipt_accepts_a_complete_card() -> None:
    assert is_valid("triage_receipt", receipt())


def test_receipt_rejects_an_empty_evidence_object() -> None:
    assert not is_valid("triage_receipt", receipt(evidence={}))


def test_receipt_rejects_abstain_without_a_reason() -> None:
    assert not is_valid("triage_receipt", receipt(decision="abstain"))


def test_receipt_accepts_abstain_with_a_reason() -> None:
    doc = receipt(decision="abstain", abstention_reason="OOD_STATION")
    assert is_valid("triage_receipt", doc)


# --- dataset_manifest: the traps from the recon are encoded -------------------


def manifest(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "snapshot_id": "snap-2026-08-17-stage1",
        "schema_version": "0.2.1",
        "stage": 1,
        "built_at": "2026-08-17T00:00:00Z",
        "completed_at": "2026-08-17T00:45:00Z",
        "query": {
            "base_url": "https://network.satnogs.org/api/observations/",
            "end": "2026-08-16T00:00:00Z",
            "target_waterfalls": 2300,
            "filters": {"status": "good"},
            "user_agent": "tracetriage/0.1 (kesavk659@gmail.com)",
            "request_interval_seconds": 0.4,
        },
        "counts": {
            "observations_requested": 2500,
            "observations_stored": 1,
            "waterfalls_stored": 1,
            "waterfalls_missing": 0,
        },
        "sampling_design": "Single contiguous window, stage 1 debug snapshot.",
        "license": "CC BY-SA 4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "pages": [
            {
                "url": "https://network.satnogs.org/api/observations/?end=2026-08-16",
                "sha256": "b" * 64,
                "retrieved_at": "2026-08-17T00:00:01Z",
                "n_observations": 1,
            }
        ],
        "observations": [
            {
                "id": 14513023,
                "source_url": "https://network.satnogs.org/api/observations/14513023/",
                "retrieved_at": "2026-08-17T00:00:02Z",
                "waterfall_url": "https://s3.eu-central-1.wasabisys.com/waterfall.png",
                "waterfall_sha256": "c" * 64,
                "waterfall_missing_reason": None,
                "ground_station": 42,
                "client_version": "2.1.2",
                "client_family": "2.1.2",
            }
        ],
    }
    doc.update(overrides)
    return doc


def test_manifest_accepts_a_complete_snapshot() -> None:
    assert is_valid("dataset_manifest", manifest())


def test_manifest_rejects_the_silently_ignored_end_filter() -> None:
    """end__lte= returns HTTP 200 and is ignored by the API, so a manifest may
    never claim it as the date bound."""
    doc = manifest()
    doc["query"]["filters"]["end__lte"] = "2026-08-16T00:00:00Z"
    assert not is_valid("dataset_manifest", doc)


def test_manifest_rejects_waterfall_status_as_a_server_side_filter() -> None:
    """The API returns HTTP 400 for it. It is applied client-side."""
    doc = manifest()
    doc["query"]["filters"]["waterfall_status"] = "with-signal"
    assert not is_valid("dataset_manifest", doc)


def test_manifest_rejects_a_hash_on_a_missing_artifact() -> None:
    doc = manifest()
    doc["observations"][0]["waterfall_missing_reason"] = "HTTP_404"
    assert not is_valid("dataset_manifest", doc)


def test_manifest_accepts_a_named_missing_artifact() -> None:
    doc = manifest()
    doc["observations"][0].update(
        waterfall_url=None, waterfall_sha256=None, waterfall_missing_reason="NO_WATERFALL_URL"
    )
    doc["counts"].update(waterfalls_stored=0, waterfalls_missing=1)
    assert is_valid("dataset_manifest", doc)


def test_manifest_requires_a_sampling_design() -> None:
    doc = manifest()
    del doc["sampling_design"]
    assert not is_valid("dataset_manifest", doc)


# ---------------------------------------------------------------------------
# fusion_receipt: the artifact carrying kill gate 5's verdict
# ---------------------------------------------------------------------------


def _comparison(**overrides: Any) -> dict[str, Any]:
    base = {
        "margin": 0.02,
        "ci95": [0.007, 0.034],
        "direction": "challenger_better",
        "distinguishable": True,
        "challenger_better": True,
        "n_observations": 88,
        "n_groups": 88,
        "n_boot": 4000,
        "seed": 42,
    }
    base.update(overrides)
    return base


def _ablation_outcome(**overrides: Any) -> dict[str, Any]:
    base = {
        "blocks": {
            "corridor": {"decision": "RETAIN", "better_on": ["chronological"], "worse_on": []}
        },
        "shipped_blocks": ["image", "corridor"],
        "shipped_arm": "image_corridor",
        "shipped_arm_was_measured": True,
    }
    base.update(overrides)
    return base


def fusion_receipt(**overrides: Any) -> dict[str, Any]:
    base = {
        "schema": "FUSION_RECEIPT",
        "schema_version": "0.1.0",
        "generated_at": "2026-08-17T22:00:00Z",
        "snapshot_id": "snap-stage1",
        "seed": 42,
        "split_manifest_sha256": "a" * 64,
        "arm_ladder": [
            {"name": "image_only", "blocks": ["image"]},
            {"name": "image_corridor", "blocks": ["image", "corridor"]},
        ],
        "gate5": {
            "verdict": "NOT_ESTABLISHED",
            "statement": (
                "The margin is positive but the interval spans zero on 88 observations, "
                "so the gate is not met."
            ),
            "challenger": "physics_conditioned",
            "reference": "image_only",
        },
        "ablation_conclusion": {
            "rules": {"nominal": "n", "multiplicity_corrected": "c"},
            "deciding_rule": "multiplicity_corrected",
            "nominal": _ablation_outcome(),
            "multiplicity_corrected": _ablation_outcome(),
            "rules_disagree_on": [],
            "shipped_blocks": ["image", "corridor"],
            "min_train_for_verdict": 300,
            "min_train_justification": (
                "Set from the size-matched control: below this the verdict measures the "
                "sample size rather than the block."
            ),
            "splits_used": ["chronological"],
            "splits_below_training_floor": ["cold_combined"],
            "caveat": (
                "The retain decision reads test-set comparisons, so the shipped arm's "
                "Brier is optimistic by an amount this corpus cannot measure."
            ),
        },
        "splits": [
            {
                "split": "chronological",
                "degraded": None,
                "counts": {"train": 530, "calibration": 121, "test": 88},
                "arms": {
                    "image_only": {
                        "brier": 0.1495,
                        "auc": 0.842,
                        "ece": 0.0482,
                        "calibration_slope": 1.14,
                        "calibrator": "temperature",
                    }
                },
                "comparisons": {"image_corridor_vs_image_only": _comparison()},
            }
        ],
    }
    base.update(overrides)
    return base


def test_fusion_receipt_accepts_the_real_artifact() -> None:
    """The shipped receipt must validate, not just a fixture shaped like it."""
    path = CONTRACT_DIR.parent / "artifacts" / "FUSION_RECEIPT.json"
    if not path.exists():
        pytest.skip("no receipt generated in this checkout")
    doc = json.loads(path.read_text(encoding="utf-8"))
    v = validator("fusion_receipt")
    errors = sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))
    assert not errors, "\n".join(
        f"{list(e.absolute_path)}: {e.message}" for e in errors[:10]
    )


def test_fusion_receipt_accepts_a_clean_fixture() -> None:
    assert is_valid("fusion_receipt", fusion_receipt())


def test_fusion_receipt_rejects_a_two_valued_direction() -> None:
    """The whole reason ``direction`` is an enum.

    A boolean verdict reports an interval lying entirely below zero as an absence of
    difference. That hides a measured harm behind a null, and the operator's own first
    version of this bootstrap did exactly that.
    """
    doc = fusion_receipt()
    doc["splits"][0]["comparisons"]["x"] = _comparison(direction=False)
    assert not is_valid("fusion_receipt", doc)
    doc["splits"][0]["comparisons"]["x"] = _comparison(direction="better")
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_decisive_comparison_with_no_interval() -> None:
    doc = fusion_receipt()
    doc["splits"][0]["comparisons"]["x"] = _comparison(ci95=None)
    assert not is_valid("fusion_receipt", doc), (
        "a comparison cannot claim a direction while reporting no interval"
    )


def test_fusion_receipt_rejects_a_margin_with_no_group_count() -> None:
    """An interval over observations rather than episodes is too narrow.

    The only way a reader can tell which was done is to see both counts, so a comparison
    that omits the episode count is rejected.
    """
    doc = fusion_receipt()
    bad = _comparison()
    del bad["n_groups"]
    doc["splits"][0]["comparisons"]["x"] = bad
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_unmeasurable_without_a_reason() -> None:
    doc = fusion_receipt()
    doc["splits"][0]["comparisons"]["x"] = _comparison(
        direction="unmeasurable", ci95=None
    )
    assert not is_valid("fusion_receipt", doc), (
        "'unmeasurable' without a note is indistinguishable from a tie downstream"
    )
    doc["splits"][0]["comparisons"]["x"] = _comparison(
        direction="unmeasurable",
        ci95=None,
        note="Only 3 of 4000 resamples produced a finite statistic.",
        n_usable_resamples=3,
    )
    assert is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_bare_gate_verdict() -> None:
    """A verdict must carry the sentence that qualifies it."""
    doc = fusion_receipt()
    doc["gate5"]["statement"] = "PASSED"
    assert not is_valid("fusion_receipt", doc)
    del doc["gate5"]["statement"]
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_an_unknown_verdict() -> None:
    """NOT_ESTABLISHED and FAILED are separate outcomes and neither is a free-text field."""
    doc = fusion_receipt()
    doc["gate5"]["verdict"] = "MOSTLY_PASSED"
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_an_infeasible_ceiling_with_no_reason() -> None:
    doc = fusion_receipt()
    doc["splits"][0]["selective"] = {
        "ceilings": [{"chosen_on_calibration": {"feasible": False, "target_risk": 0.05}}]
    }
    assert not is_valid("fusion_receipt", doc), (
        "'no threshold found' must not be readable as 'no threshold needed'"
    )
    doc["splits"][0]["selective"]["ceilings"][0]["chosen_on_calibration"]["reason"] = (
        "No threshold holds risk at or below 0.050 while keeping at least 5% of rows."
    )
    assert is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_feasible_ceiling_never_verified_on_test() -> None:
    """A ceiling chosen on calibration and not verified is a promise, not a measurement."""
    doc = fusion_receipt()
    doc["splits"][0]["selective"] = {
        "ceilings": [
            {
                "chosen_on_calibration": {
                    "feasible": True,
                    "target_risk": 0.05,
                    "threshold": 0.8375,
                }
            }
        ]
    }
    assert not is_valid("fusion_receipt", doc)
    doc["splits"][0]["selective"]["ceilings"][0]["achieved_on_test"] = {"held": True}
    assert is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_correction_that_cannot_express_a_harm() -> None:
    """``direction_adjusted`` is required for the reason the DROP branch went dead.

    A correction reporting only ``survives_correction`` as a one-sided boolean makes a
    surviving harm unrepresentable, and a rule reading it treats the missing correction as
    an absent harm.
    """
    doc = fusion_receipt()
    doc["splits"][0]["multiplicity_adjusted"] = {
        "image_corridor_vs_image_only": {
            "n_comparisons": 7,
            "ci_adjusted": [0.003, 0.039],
            "survives_correction": True,
        }
    }
    assert not is_valid("fusion_receipt", doc)
    doc["splits"][0]["multiplicity_adjusted"]["image_corridor_vs_image_only"][
        "direction_adjusted"
    ] = "challenger_better"
    assert is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_novelty_ratio_with_no_state() -> None:
    """A null ratio from an empty cell differs from one from a zero denominator.

    On a cold split every test row is novel by construction, so the unflagged cell is
    empty and the axis carries no contrast. Without the state field that reads as a failed
    measurement.
    """
    doc = fusion_receipt()
    doc["splits"][0]["ood"] = {
        "risk_by_novelty": {
            "unseen_station": {
                "flagged": {"n": 76},
                "unflagged": {"n": 0},
                "risk_ratio": None,
                "informative": False,
            }
        }
    }
    assert not is_valid("fusion_receipt", doc)
    doc["splits"][0]["ood"]["risk_by_novelty"]["unseen_station"]["risk_ratio_state"] = (
        "one cell was empty"
    )
    assert is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_an_ablation_hiding_that_the_rules_disagree() -> None:
    doc = fusion_receipt()
    del doc["ablation_conclusion"]["rules_disagree_on"]
    assert not is_valid("fusion_receipt", doc)
    doc = fusion_receipt()
    del doc["ablation_conclusion"]["nominal"]
    assert not is_valid("fusion_receipt", doc), (
        "reporting only the applied rule would conceal that another rule disagrees"
    )


def test_fusion_receipt_rejects_a_shipped_arm_with_no_measured_flag() -> None:
    """A selected combination nothing fitted has no interval behind its score."""
    doc = fusion_receipt()
    del doc["ablation_conclusion"]["multiplicity_corrected"]["shipped_arm_was_measured"]
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_training_floor_with_no_justification() -> None:
    """A threshold excluding a split from the decision needs a measured reason."""
    doc = fusion_receipt()
    doc["ablation_conclusion"]["min_train_justification"] = "because"
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_shipped_score_with_no_caveat() -> None:
    doc = fusion_receipt()
    del doc["ablation_conclusion"]["caveat"]
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_result_with_no_split_digest() -> None:
    """Without the digest a receipt cannot be tied to the splits that produced it."""
    doc = fusion_receipt()
    del doc["split_manifest_sha256"]
    assert not is_valid("fusion_receipt", doc)
    doc = fusion_receipt(split_manifest_sha256="not-a-digest")
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_clean_split_with_no_results() -> None:
    """Neither a result nor a stated reason is how a silent failure passes as a run."""
    doc = fusion_receipt()
    del doc["splits"][0]["arms"]
    assert not is_valid("fusion_receipt", doc)


def test_fusion_receipt_rejects_a_degraded_split_that_does_not_say_why() -> None:
    doc = fusion_receipt()
    doc["splits"][0] = {
        "split": "cold_combined",
        "degraded": "TOO_FEW_DECISIVE_LABELS",
        "counts": {"train": 5, "calibration": 2, "test": 1},
    }
    assert not is_valid("fusion_receipt", doc)
    doc["splits"][0]["note"] = "Fewer than 20 decisive labels cannot support a comparison."
    assert is_valid("fusion_receipt", doc)
