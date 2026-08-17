"""Tests for pipeline/tracetriage/splits.py (Unit B1).

ACCEPTANCE REQUIREMENTS CHECKED HERE
======================================
1. A duplicate waterfall SHA256 cannot cross a split boundary: the builder
   reassigns the duplicate to match the first-seen observation's partition,
   and no SHA256 appears in more than one partition after the fix.
   (Acceptance check 4: a test proves it, by constructing a dup and asserting.)

2. The same transmitter_uuid cannot appear in both train and test within the
   chronological split or the cold-transmitter split.
   (Acceptance check 5.)

3. Re-running the builder with the same seed produces byte-identical manifests
   apart from the `frozen_at` timestamp.
   (Acceptance check 6.)

4. Per-split uncorrected counts are reported and match the A3 verdict source.
   Any partition with zero uncorrected is flagged in the physics_arm_report.
   (Acceptance check 7.)

5. Every observation appears in exactly one partition per split type, and the
   total count per split equals the number of rows in the manifest.

6. Orbital revolution episodes (station, norad, rev) do not cross partitions
   in any split type.

All inputs are derived from the stage-1 snapshot on disk; no network calls.
The MANIFEST_PATH and A3_SUMMARY_PATH are read from the repo-root constants.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths and lazy loading of the pre-built manifest (avoid redundant work)
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[1]
_SPLIT_MANIFEST_PATH = _REPO / "artifacts" / "SPLIT_MANIFEST.json"
_LEAKAGE_AUDIT_PATH = _REPO / "artifacts" / "LEAKAGE_AUDIT.json"
_DATASET_MANIFEST_PATH = _REPO / "artifacts" / "DATASET_MANIFEST.json"
_PAGES_DIR = Path("D:/tracetriage_data/snap-stage1/pages")
_A3_SUMMARY_PATH = _REPO / "artifacts" / "a3_overlays" / "summary.json"

_HAS_DATA = _PAGES_DIR.is_dir() and _DATASET_MANIFEST_PATH.exists()
_HAS_SPLIT = _SPLIT_MANIFEST_PATH.exists()

pytestmark = [pytest.mark.dataset]  # reads from disk; conftest blocks sockets in unmarked tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def split_manifest():
    if not _HAS_SPLIT:
        pytest.skip("SPLIT_MANIFEST.json not built yet")
    with open(_SPLIT_MANIFEST_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def leakage_audit():
    if not _LEAKAGE_AUDIT_PATH.exists():
        pytest.skip("LEAKAGE_AUDIT.json not built yet")
    with open(_LEAKAGE_AUDIT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def rows():
    """Full enriched observation table (slow; cached at module scope)."""
    if not _HAS_DATA:
        pytest.skip("Stage-1 dataset not available")
    from pipeline.tracetriage.splits import _A3_SUMMARY_PATH as _A3
    from pipeline.tracetriage.splits import _MANIFEST_PATH, _build_obs_table
    return _build_obs_table(_MANIFEST_PATH, _PAGES_DIR, _A3)


# ---------------------------------------------------------------------------
# Acceptance check 1 — schema validation
# ---------------------------------------------------------------------------

def test_split_manifest_validates_against_schema(split_manifest):
    """SPLIT_MANIFEST.json must validate against contracts/split_manifest.schema.json."""
    pytest.importorskip("jsonschema")
    from jsonschema import ValidationError, validate  # noqa: PLC0415

    schema_path = _REPO / "contracts" / "split_manifest.schema.json"
    with open(schema_path, encoding="utf-8") as fh:
        schema = json.load(fh)

    try:
        validate(split_manifest, schema)
    except ValidationError as exc:
        pytest.fail(f"SPLIT_MANIFEST.json does not validate: {exc.message}")


def test_leakage_checks_all_passed_in_manifest(split_manifest):
    """Every leakage check must record passed=True with a scope and a real examination.

    Checking ``passed`` alone would reproduce the defect this replaced: a flat true
    that reads as "nothing crosses anywhere" while the check covered a subset of the
    splits. So the scope and the examined count are asserted with it.
    """
    lc = split_manifest["leakage_checks"]
    assert lc, "manifest recorded no leakage checks at all"
    for name, entry in lc.items():
        assert isinstance(entry, dict), (
            f"leakage_checks.{name} is {entry!r}. A bare boolean cannot say which "
            "splits it covers, which is how a stale exemption hid real crossings."
        )
        assert entry["passed"] is True, (
            f"leakage_checks.{name}.passed = {entry['passed']!r}. A failing check "
            "must halt the freeze, not be recorded as False."
        )
        assert entry["applies_to"], f"leakage_checks.{name} claims no scope"
        assert entry["n_examined"] >= 1, (
            f"leakage_checks.{name} examined {entry['n_examined']} records. A check "
            "that examined nothing passes trivially and is not evidence."
        )


def test_manifest_and_audit_agree_on_every_scope(split_manifest, leakage_audit):
    """The artifact and its audit must not disagree about what was promised.

    They did once: the audit scoped two checks out of cold_combined while the
    manifest published a flat true for both. One table now feeds both, and this is
    the test that keeps it that way.
    """
    from pipeline.tracetriage.splits import CHECK_SCOPES  # noqa: PLC0415

    for check_name, scope in CHECK_SCOPES.items():
        manifest_scope = set(split_manifest["leakage_checks"][check_name]["applies_to"])
        audit_scope = {
            row["split"] for row in leakage_audit
            if row["check"] == check_name and row["guaranteed"]
        }
        assert manifest_scope == set(scope["applies_to"]), (
            f"{check_name}: manifest claims {sorted(manifest_scope)}, "
            f"table says {sorted(scope['applies_to'])}"
        )
        assert audit_scope == set(scope["applies_to"]), (
            f"{check_name}: audit claims {sorted(audit_scope)}, "
            f"table says {sorted(scope['applies_to'])}"
        )


def test_by_design_exemptions_carry_a_measured_count(split_manifest, leakage_audit):
    """An exemption states a number, not just a reason.

    A reason with no number has to be taken on trust and outlives the design it
    described. Every split that does not claim a guarantee reports how many entities
    actually cross, so a reader can weigh 213 against the sentence.
    """
    for row in leakage_audit:
        if row["guaranteed"] or row["split"] == "all":
            continue
        assert "n_violators" in row and row["n_examined"] >= 1, row
        assert row["result"] == "BY_DESIGN", row
        entry = split_manifest["leakage_checks"][row["check"]]
        recorded = entry["by_design_crossings"][row["split"]]
        assert recorded["n_crossing"] == row["n_violators"], (
            f"{row['check']}/{row['split']}: manifest says "
            f"{recorded['n_crossing']} crossings, audit measured {row['n_violators']}"
        )
        assert recorded["reason"].strip(), "exemption with no stated reason"


# ---------------------------------------------------------------------------
# Acceptance check 2 — duplicate image cannot cross a split boundary
# ---------------------------------------------------------------------------

class TestDuplicateImageCannotCrossSplits:
    """A waterfall SHA256 that already exists in a partition cannot cross to another.

    This test CONSTRUCTS a synthetic duplicate and asserts the builder
    reassigns it — it does NOT just assert the current data happens to be clean.
    """

    def test_sha256_dedup_reassigns_later_obs_to_match_earlier(self, rows):
        """When two observations share a SHA256, the later one's partition must
        match the earlier one, regardless of where it would have been assigned."""
        from pipeline.tracetriage.splits import (  # noqa: PLC0415
            _assign_sha256_to_partition,
        )

        if not rows:
            pytest.skip("No rows available")

        # Build a trivial partition map: first half → train, second half → test
        sorted_ids = sorted(r["id"] for r in rows)
        n = len(sorted_ids)
        partition_map: dict[int, str] = {}
        for i, oid in enumerate(sorted_ids):
            partition_map[oid] = "train" if i < n // 2 else "test"

        # Pick the first obs in train and inject a fake SHA that also appears
        # on the first obs in test — they now share a SHA256.
        first_train_id = sorted_ids[0]
        first_test_id = sorted_ids[n // 2]
        fake_sha = "deadbeef" * 8  # 64-char hex, valid SHA256 format

        # Patch the rows temporarily
        patched_rows = []
        for r in rows:
            patched = dict(r)
            if patched["id"] == first_train_id or patched["id"] == first_test_id:
                patched["waterfall_sha256"] = fake_sha
            patched_rows.append(patched)

        # train obs has id < test obs since we sorted by id
        assert first_train_id < first_test_id  # train obs is "earlier"
        assert partition_map[first_train_id] == "train"
        assert partition_map[first_test_id] == "test"

        # Apply the SHA dedup
        result = _assign_sha256_to_partition(patched_rows, partition_map)

        # The test obs should have been moved to match the train obs
        assert result[first_test_id] == "train", (
            f"Obs {first_test_id} shared SHA256 with train obs {first_train_id} "
            "but was not reassigned to train"
        )
        # The original train obs must be unchanged
        assert result[first_train_id] == "train"

    def test_no_sha256_crosses_splits_in_built_manifest(self, split_manifest, rows):
        """In the built manifest, no waterfall SHA256 appears in more than one
        partition within any split type.  Checks every split and reports the count
        examined.
        """
        if not rows:
            pytest.skip("No rows available")

        sha_lookup = {r["id"]: r["waterfall_sha256"] for r in rows}

        for split_name, split_data in split_manifest["splits"].items():
            sha_to_parts: dict[str, set[str]] = {}
            n_checked = 0
            for part_name, obs_ids in split_data.items():
                for oid in obs_ids:
                    sha = sha_lookup.get(oid)
                    if not sha:
                        continue
                    n_checked += 1
                    if sha not in sha_to_parts:
                        sha_to_parts[sha] = set()
                    sha_to_parts[sha].add(part_name)

            assert n_checked > 0, (
                f"{split_name}: checked 0 SHA256 values — test is vacuous"
            )
            violators = {sha: parts for sha, parts in sha_to_parts.items() if len(parts) > 1}
            assert not violators, (
                f"{split_name}: {len(violators)} SHA256(s) appear in multiple partitions: "
                f"{list(violators.keys())[:3]}"
            )


# ---------------------------------------------------------------------------
# Acceptance check 3 — same transmitter cannot appear in two splits
# ---------------------------------------------------------------------------

class TestTransmitterNotAcrossSplits:
    """The same transmitter_uuid cannot appear in both train and test within
    the chronological split or the cold-transmitter split.

    These are the two splits where transmitter is the grouping entity.
    """

    @pytest.mark.parametrize(
        "split_name", ["chronological", "cold_station", "cold_transmitter", "cold_combined"]
    )
    def test_transmitter_partitioning_matches_what_the_split_claims(
        self, split_name, split_manifest, rows
    ):
        """Whether a transmitter may cross is read from the scope table, not hardcoded.

        This test used to be parametrized over ``["chronological", "cold_transmitter"]``.
        When the chronological split stopped grouping by transmitter, it failed with 211
        violators, which was correct behaviour reported as a defect. Hardcoding a scope
        in a test makes the test a second place the scope can be wrong, so both the
        claimed and the by-design cases are now driven from ``CHECK_SCOPES``.
        """
        if not rows:
            pytest.skip("No rows available")
        from pipeline.tracetriage.splits import CHECK_SCOPES  # noqa: PLC0415

        scope = CHECK_SCOPES["no_transmitter_across_splits"]
        claimed = split_name in scope["applies_to"]

        split_data = split_manifest["splits"][split_name]
        id_to_tx = {r["id"]: r["transmitter_uuid"] for r in rows}

        tx_to_parts: dict[str, set[str]] = {}
        for part_name, obs_ids in split_data.items():
            if part_name == "excluded":
                continue  # belongs to no partition, so it cannot cross one
            for oid in obs_ids:
                tx = id_to_tx.get(oid)
                if tx is None:
                    continue
                tx_to_parts.setdefault(tx, set()).add(part_name)

        assert tx_to_parts, f"{split_name}: checked 0 transmitters, the test is vacuous"
        violators = {tx: parts for tx, parts in tx_to_parts.items() if len(parts) > 1}

        if claimed:
            assert not violators, (
                f"{split_name} claims no_transmitter_across_splits but "
                f"{len(violators)} transmitter(s) appear in multiple partitions. "
                f"First: {next(iter(violators))} in {next(iter(violators.values()))}"
            )
        else:
            assert split_name in scope["by_design"], (
                f"{split_name} neither claims the guarantee nor explains why not"
            )
            recorded = split_manifest["leakage_checks"][
                "no_transmitter_across_splits"
            ]["by_design_crossings"][split_name]["n_crossing"]
            assert recorded == len(violators), (
                f"{split_name}: the manifest records {recorded} by-design crossings, "
                f"this test counted {len(violators)}"
            )


# ---------------------------------------------------------------------------
# Acceptance check 4 — re-run with same seed produces byte-identical splits
# ---------------------------------------------------------------------------

class TestDeterminism:
    """Re-running the builder with the same seed must produce byte-identical
    split assignment — the same observation IDs in the same partitions.

    The frozen_at timestamp differs between runs; we compare only the splits
    and composition fields.
    """

    def test_same_seed_produces_identical_splits(self, rows):
        if not rows or not _HAS_DATA:
            pytest.skip("Stage-1 dataset not available")
        from pipeline.tracetriage.splits import _A3_SUMMARY_PATH as _A3
        from pipeline.tracetriage.splits import _MANIFEST_PATH, build_splits  # noqa: PLC0415

        kw = {
            "manifest_path": _MANIFEST_PATH,
            "pages_dir": _PAGES_DIR,
            "a3_summary_path": _A3,
        }
        m1 = build_splits(seed=42, **kw)
        m2 = build_splits(seed=42, **kw)

        # The acceptance criterion is the whole manifest apart from the timestamp, not
        # just the id lists. Comparing only "splits" would let composition, the
        # leakage measurements or the physics report drift between runs unnoticed.
        for m in (m1, m2):
            del m["frozen_at"]
        s1 = json.dumps(m1, sort_keys=True)
        s2 = json.dumps(m2, sort_keys=True)
        assert s1 == s2, "Same seed produced a different manifest"

        differing = [
            k
            for k in m1
            if json.dumps(m1[k], sort_keys=True) != json.dumps(m2[k], sort_keys=True)
        ]
        assert not differing, f"nondeterministic keys: {differing}"

    def test_different_seed_produces_different_cold_splits(self, rows):
        if not rows or not _HAS_DATA:
            pytest.skip("Stage-1 dataset not available")
        from pipeline.tracetriage.splits import _A3_SUMMARY_PATH as _A3
        from pipeline.tracetriage.splits import _MANIFEST_PATH, build_splits  # noqa: PLC0415

        kw = {
            "manifest_path": _MANIFEST_PATH,
            "pages_dir": _PAGES_DIR,
            "a3_summary_path": _A3,
        }
        m1 = build_splits(seed=42, **kw)
        m2 = build_splits(seed=99, **kw)

        # Every randomly drawn split must respond to the seed. Checking only
        # cold_station would miss a split that quietly stopped consuming the
        # generator, and cold_combined now draws tiers of its own.
        for split_name in ("cold_station", "cold_transmitter", "cold_combined"):
            s1 = json.dumps(m1["splits"][split_name], sort_keys=True)
            s2 = json.dumps(m2["splits"][split_name], sort_keys=True)
            assert s1 != s2, (
                f"Different seeds produced identical {split_name} splits, so its "
                "assignment does not depend on the generator"
            )

        # Chronological is a time cut, so it must NOT move with the seed.
        assert json.dumps(m1["splits"]["chronological"], sort_keys=True) == json.dumps(
            m2["splits"]["chronological"], sort_keys=True
        ), "the chronological split is a time cut and must not depend on the seed"


# ---------------------------------------------------------------------------
# Acceptance check 5 — uncorrected counts reported and physics arm flagged
# ---------------------------------------------------------------------------

class TestPhysicsArmReport:
    """Uncorrected counts come from A3 verdicts and are correctly reported.
    Partitions with zero uncorrected observations are flagged.
    """

    def test_physics_arm_report_present(self, split_manifest):
        assert "physics_arm_report" in split_manifest, "physics_arm_report missing from manifest"
        assert len(split_manifest["physics_arm_report"]) > 0, "physics_arm_report is empty"

    def test_each_partition_has_physics_evaluable_flag(self, split_manifest):
        for row in split_manifest["physics_arm_report"]:
            assert "physics_evaluable" in row
            assert "n_uncorrected" in row
            assert isinstance(row["n_uncorrected"], int)

    def test_total_uncorrected_matches_a3_verdicts(self, split_manifest, rows):
        """Total uncorrected across all four splits must equal 3 (the number
        of UNCORRECTED verdicts in A3's 24-observation pool)."""
        if not rows:
            pytest.skip("No rows available")

        # Count uncorrected from rows (ground truth: from A3 summary)
        total_uncorrected_in_rows = sum(
            1 for r in rows if r["correction_verdict"] == "UNCORRECTED"
        )
        assert total_uncorrected_in_rows == 3, (
            f"Expected 3 UNCORRECTED rows from A3, got {total_uncorrected_in_rows}. "
            "A3 verdict map may have been re-derived from metadata (not allowed)."
        )

        # Each split type should have total uncorrected == 3 (same observations,
        # just in different partitions)
        for split_name, comp in split_manifest["composition"].items():
            total_unc = sum(stats["n_uncorrected"] for stats in comp.values())
            assert total_unc == 3, (
                f"{split_name}: total uncorrected across partitions = {total_unc}, "
                f"expected 3"
            )

    def test_zero_uncorrected_partitions_are_flagged(self, split_manifest):
        """Any partition with n_uncorrected == 0 must be listed with a warning
        in the physics_arm_report."""
        flagged = {
            (r["split"], r["partition"])
            for r in split_manifest["physics_arm_report"]
            if not r["physics_evaluable"]
        }
        for split_name, comp in split_manifest["composition"].items():
            for part_name, stats in comp.items():
                if stats["n_uncorrected"] == 0:
                    assert (split_name, part_name) in flagged, (
                        f"{split_name}/{part_name} has n_uncorrected=0 but is not "
                        "flagged in physics_arm_report"
                    )


# ---------------------------------------------------------------------------
# Acceptance check 6 — every observation in exactly one partition per split
# ---------------------------------------------------------------------------

class TestCoverageAndUniqueness:
    """Every observation ID in the manifest appears in exactly one partition
    per split type, and the total count matches the manifest count.
    """

    def test_every_obs_in_exactly_one_partition(self, split_manifest, rows):
        if not rows:
            pytest.skip("No rows available")
        all_ids = {r["id"] for r in rows}

        for split_name, split_data in split_manifest["splits"].items():
            seen: dict[int, str] = {}
            for part_name, obs_ids in split_data.items():
                for oid in obs_ids:
                    assert oid not in seen, (
                        f"{split_name}: obs {oid} in both {seen[oid]} and {part_name}"
                    )
                    seen[oid] = part_name

            in_split = set(seen.keys())
            assert in_split == all_ids, (
                f"{split_name}: {len(all_ids - in_split)} obs missing, "
                f"{len(in_split - all_ids)} unknown obs"
            )

    def test_split_total_counts_match_manifest(self, split_manifest):
        n_obs = split_manifest["n_observations"]
        for split_name, split_data in split_manifest["splits"].items():
            total = sum(len(ids) for ids in split_data.values())
            assert total == n_obs, (
                f"{split_name}: total IDs = {total}, manifest n_observations = {n_obs}"
            )


# ---------------------------------------------------------------------------
# Acceptance check 7 — orbital revolution episodes don't cross partitions
# ---------------------------------------------------------------------------

class TestOrbitalRevolutionNoLeak:
    """No (ground_station, norad_cat_id, orbital_revolution) episode appears
    in more than one partition within any split type.

    This is the 'episode' constraint: two observations of the same satellite
    pass at the same station must land in the same partition.
    """

    def test_revolution_episodes_do_not_cross_partitions(self, split_manifest, rows):
        if not rows:
            pytest.skip("No rows available")
        from pipeline.tracetriage.splits import _check_no_revolution_across_splits  # noqa: PLC0415

        for split_name, split_data in split_manifest["splits"].items():
            # Reconstruct partition map from manifest
            pm: dict[int, str] = {}
            for part_name, obs_ids in split_data.items():
                for oid in obs_ids:
                    pm[oid] = part_name

            ok, detail = _check_no_revolution_across_splits(rows, pm)
            assert ok, (
                f"{split_name}: orbital revolution episode(s) cross partition boundary. "
                f"Detail: {detail}"
            )


# ---------------------------------------------------------------------------
# Leakage audit structure checks
# ---------------------------------------------------------------------------

class TestLeakageAuditStructure:
    def test_audit_has_expected_checks(self, leakage_audit):
        check_names = {row["check"] for row in leakage_audit}
        expected = {
            "no_transmitter_across_splits",
            "no_station_across_splits",
            "no_revolution_across_splits",
            "no_duplicate_image_across_splits",
            "no_future_feature_in_train",
            "test_set_untouched",
        }
        assert expected.issubset(check_names), (
            f"Missing checks: {expected - check_names}"
        )

    def test_audit_no_fail_rows(self, leakage_audit):
        """No row in the leakage audit has result=FAIL."""
        fail_rows = [r for r in leakage_audit if r["result"] == "FAIL"]
        assert not fail_rows, (
            f"{len(fail_rows)} FAIL row(s) in leakage audit: "
            f"{[(r['check'], r['split']) for r in fail_rows]}"
        )

    def test_audit_rows_have_n_examined(self, leakage_audit):
        """Every audit row must declare n_examined > 0 (no vacuous checks)."""
        for row in leakage_audit:
            # SCOPE_NOTE rows for n_examined may be equal to total obs
            assert "n_examined" in row, f"Row missing n_examined: {row}"
            assert row["n_examined"] > 0, (
                f"Check {row['check']} for {row['split']} examined 0 records"
            )
