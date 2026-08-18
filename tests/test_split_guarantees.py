"""Falsifiability tests for the B1 split guarantees, on synthetic rows.

Why a second split test file, and why none of it touches the snapshot.

``tests/test_splits.py`` asserts that the built artifact is clean. That is worth
having, and it is not evidence that the checks work: a check that cannot fail
reports the same clean result on the same clean corpus. The stage-1 snapshot has
2,500 waterfalls with 2,500 distinct SHA-256 values, so the duplicate check has
never had a duplicate to catch, and every entity guarantee currently measures zero
crossings. Nothing there separates "the builder is correct" from "the check is
inert".

So each test below plants the violation and asserts it is caught. Two of them plant
rules this project actually shipped and had to withdraw:

* ``test_sending_mixed_pairs_to_train_puts_one_transmitter_in_two_partitions``
  is version 1 of the cold-combined rule.
* ``test_the_both_cold_calibration_rule_puts_one_station_in_two_partitions``
  is version 2. It survived review because the two checks that would have caught it
  had been scoped out of the split on version 1's reasoning.

Both are kept as executable records. If a future change reintroduces either rule,
these fail rather than the manifest quietly publishing ``true`` again.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from pipeline.tracetriage.splits import (
    ASSERTED_NOT_MEASURABLE_HERE,
    CHECK_SCOPES,
    FIELD_CLASSIFICATION,
    _build_cold_combined_split,
    _exclude_duplicate_images,
    check_field_classification,
    entity_spread,
    reject_vacuous_checks,
    reject_vacuous_checks_in_audit,
)


def _row(
    oid: int,
    station: int,
    tx: str,
    *,
    norad: int = 63214,
    rev: int = 1,
    sha: str | None = None,
) -> dict[str, Any]:
    return {
        "id": oid,
        "ground_station": station,
        "transmitter_uuid": tx,
        "norad_cat_id": norad,
        "orbital_revolution": rev,
        "waterfall_sha256": sha if sha is not None else f"sha{oid}",
    }


#: Two stations and two transmitters in every combination. Station 1 and transmitter
#: "A" are in the test tier; station 2 and transmitter "B" are in train. The two
#: mixed pairs are the whole problem: each is cold on one axis and warm on the other.
_FOUR_PAIRS = [
    _row(1, station=1, tx="A"),  # both cold
    _row(2, station=1, tx="B"),  # cold station, warm transmitter
    _row(3, station=2, tx="A"),  # warm station, cold transmitter
    _row(4, station=2, tx="B"),  # both warm
]
_STATION_TIERS = {1: "test", 2: "test", 3: "train", 4: "train"}
_TX_TIERS = {1: "test", 2: "train", 3: "test", 4: "train"}


class TestColdCombinedIsStrict:
    def test_mixed_pairs_are_excluded_not_reassigned(self) -> None:
        pm = _build_cold_combined_split(_FOUR_PAIRS, _STATION_TIERS, _TX_TIERS)
        assert pm == {1: "test", 2: "excluded", 3: "excluded", 4: "train"}

    def test_both_entity_guarantees_hold_on_the_strict_rule(self) -> None:
        pm = _build_cold_combined_split(_FOUR_PAIRS, _STATION_TIERS, _TX_TIERS)
        for entity in ("station", "transmitter"):
            stats = entity_spread(_FOUR_PAIRS, pm, entity)
            assert stats["n_violators"] == 0, stats
            assert stats["n_examined"] == 2, "the two kept observations"
            assert stats["n_skipped_excluded"] == 2

    def test_sending_mixed_pairs_to_train_puts_one_transmitter_in_two_partitions(
        self,
    ) -> None:
        """Version 1 of the rule. Kept executable so it cannot come back unnoticed."""
        v1 = {}
        for row in _FOUR_PAIRS:
            sp, tp = _STATION_TIERS[row["id"]], _TX_TIERS[row["id"]]
            v1[row["id"]] = "test" if sp == "test" and tp == "test" else "train"

        tx = entity_spread(_FOUR_PAIRS, v1, "transmitter")
        assert tx["n_violators"] == 1, (
            "transmitter A should sit in test (from station 1) and train (from "
            f"station 2). Measured: {tx}"
        )
        assert tx["examples"][0]["partitions"] == ["test", "train"]

        st = entity_spread(_FOUR_PAIRS, v1, "station")
        assert st["n_violators"] == 1, f"station 1 should span test and train: {st}"

    def test_the_both_cold_calibration_rule_puts_one_station_in_two_partitions(
        self,
    ) -> None:
        """Version 2 of the rule: excluded the mixed pairs, still leaked.

        "Both axes cold but not both test" sends (test-station, cal-transmitter) to
        calibration and (test-station, test-transmitter) to test, so a test-tier
        station appears in both. On the real snapshot this crossed 12 transmitters
        and 4 stations while both checks reported clean, because the checks had been
        scoped out of this split.
        """
        rows = [
            _row(1, station=1, tx="A"),  # test station, test transmitter
            _row(2, station=1, tx="C"),  # test station, cal transmitter
        ]
        station_tiers = {1: "test", 2: "test"}
        tx_tiers = {1: "test", 2: "calibration"}

        v2 = {}
        for row in rows:
            sp, tp = station_tiers[row["id"]], tx_tiers[row["id"]]
            if sp == "test" and tp == "test":
                v2[row["id"]] = "test"
            elif sp in ("test", "calibration") and tp in ("test", "calibration"):
                v2[row["id"]] = "calibration"
            else:
                v2[row["id"]] = "excluded"
        assert v2 == {1: "test", 2: "calibration"}, "reproduce version 2 exactly"

        st = entity_spread(rows, v2, "station")
        assert st["n_violators"] == 1, (
            f"station 1 should span test and calibration under version 2: {st}"
        )
        assert st["examples"][0]["partitions"] == ["calibration", "test"]

        strict = _build_cold_combined_split(rows, station_tiers, tx_tiers)
        assert strict == {1: "test", 2: "excluded"}
        assert entity_spread(rows, strict, "station")["n_violators"] == 0


class TestEntitySpreadCanFail:
    """The checks have never seen a violation in this corpus. Plant some."""

    def test_a_planted_transmitter_crossing_is_counted(self) -> None:
        rows = [_row(1, station=1, tx="A"), _row(2, station=2, tx="A")]
        stats = entity_spread(rows, {1: "train", 2: "test"}, "transmitter")
        assert stats["n_violators"] == 1
        assert stats["n_entities"] == 1
        assert stats["n_examined"] == 2

    def test_a_planted_episode_crossing_is_counted(self) -> None:
        """Two observations of one pass at one station must not straddle a boundary."""
        rows = [
            _row(1, station=7, tx="A", norad=99, rev=42),
            _row(2, station=7, tx="B", norad=99, rev=42),
        ]
        stats = entity_spread(rows, {1: "train", 2: "test"}, "episode")
        assert stats["n_violators"] == 1, stats

        same_rev_other_station = [
            _row(1, station=7, tx="A", norad=99, rev=42),
            _row(2, station=8, tx="A", norad=99, rev=42),
        ]
        assert entity_spread(
            same_rev_other_station, {1: "train", 2: "test"}, "episode"
        )["n_violators"] == 0, (
            "two stations watching the same revolution are two episodes, not one "
            "sample; treating them as one would collapse the cold-station split"
        )

    def test_a_planted_duplicate_image_is_counted(self) -> None:
        rows = [_row(1, station=1, tx="A", sha="dup"), _row(2, station=2, tx="B", sha="dup")]
        stats = entity_spread(rows, {1: "train", 2: "test"}, "image")
        assert stats["n_violators"] == 1, stats

    def test_rows_with_no_image_are_reported_not_silently_dropped(self) -> None:
        rows = [_row(1, station=1, tx="A", sha=""), _row(2, station=2, tx="B")]
        stats = entity_spread(rows, {1: "train", 2: "test"}, "image")
        assert stats["n_examined"] == 1
        assert stats["n_skipped_no_key"] == 1
        assert "no key" in stats["detail"]

    def test_excluded_rows_cannot_manufacture_a_crossing(self) -> None:
        """An excluded observation is in no partition, so it cannot cross one."""
        rows = [_row(1, station=1, tx="A"), _row(2, station=1, tx="A")]
        stats = entity_spread(rows, {1: "test", 2: "excluded"}, "station")
        assert stats["n_violators"] == 0
        assert stats["n_examined"] == 1
        assert stats["n_skipped_excluded"] == 1

    def test_an_id_missing_from_the_map_is_skipped_not_crashed(self) -> None:
        rows = [_row(1, station=1, tx="A"), _row(2, station=1, tx="A")]
        stats = entity_spread(rows, {1: "test"}, "station")
        assert stats["n_examined"] == 1
        assert stats["n_skipped_excluded"] == 1


class TestVacuousChecksAreNotPasses:
    def test_a_check_over_an_all_excluded_map_examines_nothing(self) -> None:
        rows = [_row(1, station=1, tx="A"), _row(2, station=2, tx="B")]
        stats = entity_spread(rows, {1: "excluded", 2: "excluded"}, "station")
        assert stats["n_violators"] == 0, "trivially, because it compared nothing"
        assert stats["n_examined"] == 0

    def test_the_build_refuses_a_check_that_examined_nothing(self) -> None:
        with pytest.raises(RuntimeError, match="examined zero records"):
            reject_vacuous_checks(
                {
                    "no_station_across_splits": {"passed": True, "n_examined": 0},
                    "no_revolution_across_splits": {"passed": True, "n_examined": 10},
                }
            )

    def test_a_check_with_no_examined_count_at_all_is_refused(self) -> None:
        with pytest.raises(RuntimeError, match="no_station_across_splits"):
            reject_vacuous_checks({"no_station_across_splits": {"passed": True}})

    def test_positive_counts_are_accepted(self) -> None:
        reject_vacuous_checks({"a": {"passed": True, "n_examined": 1}})


class TestDuplicateImagesInAnIntersectionSplit:
    def test_a_planted_duplicate_goes_to_excluded_not_across_a_tier(self) -> None:
        """The dedup rule must not drag an observation into the wrong tier.

        Promoting the later duplicate to the earlier one's partition is right for the
        single-axis splits and wrong here: it would move a doubly-cold test
        observation into train because it happens to share a waterfall, breaking the
        entity guarantee on data that contains a duplicate. The snapshot contains
        none, so only this test can tell the two rules apart.
        """
        rows = [
            _row(1, station=2, tx="B", sha="dup"),  # both warm -> train
            _row(2, station=1, tx="A", sha="dup"),  # both cold -> test
        ]
        pm = {1: "train", 2: "test"}
        result = _exclude_duplicate_images(rows, pm)
        assert result == {1: "train", 2: "excluded"}
        assert entity_spread(rows, result, "image")["n_violators"] == 0
        assert entity_spread(rows, result, "station")["n_violators"] == 0

    def test_an_already_excluded_row_is_left_alone(self) -> None:
        rows = [_row(1, station=1, tx="A", sha="dup"), _row(2, station=2, tx="B", sha="dup")]
        result = _exclude_duplicate_images(rows, {1: "excluded", 2: "test"})
        assert result == {1: "excluded", 2: "test"}, (
            "an excluded row must not claim a SHA and push the kept copy out"
        )

    def test_rows_without_an_image_are_untouched(self) -> None:
        rows = [_row(1, station=1, tx="A", sha=""), _row(2, station=2, tx="B", sha="")]
        assert _exclude_duplicate_images(rows, {1: "train", 2: "test"}) == {
            1: "train",
            2: "test",
        }


class TestFieldClassificationIsAGate:
    def _pages(self, tmp_path, fields: dict[str, Any]):
        (tmp_path / "page1.json").write_text(
            json.dumps([{"id": 1, **fields}]), encoding="utf-8"
        )
        return tmp_path

    def test_a_field_nobody_classified_fails_the_freeze(self, tmp_path) -> None:
        """A new field on the record might be a label. Nothing here can rule that out.

        The failure mode this closes: a later snapshot adds a field, feature
        extraction picks it up, and the leak is discovered from a suspiciously good
        result rather than from a check.
        """
        pages = self._pages(tmp_path, {"quality_score_added_later": 0.97})
        result = check_field_classification(pages)
        assert result["passed"] is False
        assert result["unclassified"] == ["quality_score_added_later"]

    def test_a_fully_classified_record_passes(self, tmp_path) -> None:
        pages = self._pages(tmp_path, {"start": "x", "status": "good", "demoddata": []})
        result = check_field_classification(pages)
        assert result["passed"] is True
        assert result["unclassified"] == []
        assert result["n_examined"] == 4

    def test_the_label_and_its_aliases_are_all_forbidden(self, tmp_path) -> None:
        """``status`` and ``demoddata`` are the label without looking like it.

        The hand-written list this replaced had six fields, none of them these two.
        ``status`` is derived from vetting; ``demoddata`` holds decoded frames, so a
        frame count answers the question the model is being asked.
        """
        pages = self._pages(
            tmp_path,
            {
                "status": "good",
                "demoddata": [{"payload_demod": "x"}],
                "vetted_status": "good",
                "waterfall_status": "with-signal",
                "payload": "http://example/audio.ogg",
                "archived": True,
                "archive_url": "http://example/a",
                "transmitter_updated": "2026-08-16T00:00:00Z",
                "start": "2026-08-09T00:00:00Z",
            },
        )
        result = check_field_classification(pages)
        assert result["passed"] is True
        forbidden = set(result["forbidden_fields"])
        assert forbidden == {
            "status",
            "demoddata",
            "vetted_status",
            "waterfall_status",
            "payload",
            "archived",
            "archive_url",
            "transmitter_updated",
        }
        assert "start" not in forbidden
        for field in forbidden:
            assert result["forbidden_reasons"][field].strip(), f"{field} has no reason"

    def test_every_classification_is_one_of_three_known_kinds(self) -> None:
        kinds = {kind for kind, _ in FIELD_CLASSIFICATION.values()}
        assert kinds == {"observation_time", "identifier", "post_observation"}

    def test_grouping_keys_are_identifiers_not_features(self) -> None:
        """An observation id is monotonic with time; as a number it leaks order."""
        for field in ("id", "ground_station", "transmitter_uuid", "sat_id"):
            assert FIELD_CLASSIFICATION[field][0] == "identifier", field


class TestCheckScopesAreCoherent:
    def test_every_split_is_either_guaranteed_or_explained(self) -> None:
        all_splits = {"chronological", "cold_station", "cold_transmitter", "cold_combined"}
        for name, scope in CHECK_SCOPES.items():
            covered = set(scope["applies_to"]) | set(scope["by_design"])
            assert covered == all_splits, (
                f"{name} says nothing about {sorted(all_splits - covered)}. A split "
                "that is neither guaranteed nor explained is an unexamined gap."
            )
            assert not (set(scope["applies_to"]) & set(scope["by_design"])), (
                f"{name} both claims and excuses the same split"
            )

    def test_every_exemption_states_a_reason(self) -> None:
        for name, scope in CHECK_SCOPES.items():
            for split, reason in scope["by_design"].items():
                assert len(reason.strip()) > 20, f"{name}/{split}: reason too thin"

    def test_cold_combined_claims_both_entity_guarantees(self) -> None:
        """The regression this file exists for.

        Both checks were once scoped out of cold_combined, and the exemption outlived
        the builder change that made it false.
        """
        assert "cold_combined" in CHECK_SCOPES["no_transmitter_across_splits"]["applies_to"]
        assert "cold_combined" in CHECK_SCOPES["no_station_across_splits"]["applies_to"]


# ---------------------------------------------------------------------------
# ENG-B3: leakage audit absolute path and vacuity gate
# ---------------------------------------------------------------------------


class TestLeakageAuditPathHandling:
    """The leakage audit must not silently pass on a missing or wrong snapshot path.

    The defect: build_leakage_audit called check_field_classification(_PAGES_DIR),
    ignoring the pages_dir the caller named.  If that path was absent, _load_raw_pages
    yielded nothing, and the check returned a PASS over zero records.  The vacuity gate
    reject_vacuous_checks only applied to the manifest's leakage_checks dict and never
    to the audit list.
    """

    @staticmethod
    def _minimal_audit_args(tmp_path):
        """Return rows and partition maps sufficient to run build_leakage_audit.

        entity_spread reads row["id"], not row["obs_id"], so the synthetic rows
        must use the same key the production builder emits.
        """
        rows = [
            {"id": 1, "ground_station": 10, "transmitter_uuid": "A",
             "norad_cat_id": 1, "orbital_revolution": 0,
             "waterfall_sha256": "aa", "a3_verdict": "unresolved"},
            {"id": 2, "ground_station": 20, "transmitter_uuid": "B",
             "norad_cat_id": 2, "orbital_revolution": 0,
             "waterfall_sha256": "bb", "a3_verdict": "unresolved"},
        ]
        pm = {1: "train", 2: "test"}
        return rows, pm, pm, pm, pm

    def test_missing_pages_dir_raises_not_silently_passes(self, tmp_path) -> None:
        """A path that does not exist must raise, not return PASS n_examined=0."""
        from pipeline.tracetriage.splits import build_leakage_audit

        rows, chron, station, tx, combined = self._minimal_audit_args(tmp_path)
        missing = tmp_path / "nonexistent_snapshot" / "pages"
        with pytest.raises(RuntimeError, match="0 records"):
            build_leakage_audit(
                rows, chron, station, tx, combined, pages_dir=missing
            )

    def test_empty_pages_dir_raises_not_silently_passes(self, tmp_path) -> None:
        """An existing but empty directory must also raise."""
        from pipeline.tracetriage.splits import build_leakage_audit

        empty_dir = tmp_path / "empty_pages"
        empty_dir.mkdir()
        rows, chron, station, tx, combined = self._minimal_audit_args(tmp_path)
        with pytest.raises(RuntimeError, match="0 records"):
            build_leakage_audit(
                rows, chron, station, tx, combined, pages_dir=empty_dir
            )

    def test_correct_pages_dir_succeeds(self, tmp_path) -> None:
        """A pages dir with at least one known-classified record completes normally."""
        from pipeline.tracetriage.splits import build_leakage_audit

        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()
        # Write one record using only classified fields so the check passes.
        record = {
            "id": 1,
            "start": "2026-08-09T00:00:00Z",
            "end": "2026-08-09T00:05:00Z",
            "ground_station": 42,
            "transmitter_uuid": "T1",
            "norad_cat_id": 12345,
            "status": "good",
        }
        (pages_dir / "page1.json").write_text(
            json.dumps([record]), encoding="utf-8"
        )
        rows, chron, station, tx, combined = self._minimal_audit_args(tmp_path)
        audit = build_leakage_audit(
            rows, chron, station, tx, combined, pages_dir=pages_dir
        )
        field_row = next((r for r in audit if r["check"] == "no_future_feature_in_train"), None)
        assert field_row is not None
        assert field_row["n_examined"] > 0, (
            "n_examined must be the count of fields on the real records, not zero"
        )

    def test_vacuous_pass_rows_in_audit_are_refused(self, tmp_path) -> None:
        """The vacuity gate must refuse any PASS row with n_examined == 0.

        This tests the gate directly so that it cannot be bypassed by the silent-pass
        path that was the original defect.
        """

        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()
        # Write a record with only classified fields.
        record = {"id": 1, "start": "2026-08-09T00:00:00Z"}
        (pages_dir / "page1.json").write_text(json.dumps([record]), encoding="utf-8")

        # Test the gate directly by constructing an audit list that would trip it.
        # The rows are synthetic; entity_spread always returns positive counts for
        # them so the gate cannot be exercised through a real build call here.
        real_vacuous = [
            {"check": "no_station_across_splits", "split": "chronological",
             "result": "PASS", "n_examined": 0, "n_violators": 0,
             "guaranteed": True, "entity": "station", "n_entities": 0,
             "n_skipped_excluded": 0, "n_skipped_no_key": 0,
             "detail": "synthetic", "examples": []},
        ]
        with pytest.raises(RuntimeError, match="vacuous PASS"):
            reject_vacuous_checks_in_audit(real_vacuous)

    def test_test_set_untouched_row_has_asserted_not_measurable_result(self, tmp_path) -> None:
        """The test_set_untouched row must use the ASSERTED_NOT_MEASURABLE_HERE result.

        The previous version reported PASS with n_examined=1349, measuring a different
        property (emitted test-id count) under the name of this check.
        """
        from pipeline.tracetriage.splits import build_leakage_audit

        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()
        record = {"id": 1, "start": "2026-08-09T00:00:00Z"}
        (pages_dir / "page1.json").write_text(json.dumps([record]), encoding="utf-8")
        rows, chron, station, tx, combined = self._minimal_audit_args(tmp_path)
        audit = build_leakage_audit(
            rows, chron, station, tx, combined, pages_dir=pages_dir
        )
        row = next((r for r in audit if r["check"] == "test_set_untouched"), None)
        assert row is not None
        assert row["result"] == "ASSERTED_NOT_MEASURABLE_HERE", (
            "test_set_untouched must not claim PASS: the build cannot measure "
            "whether the test set was touched from inside the build itself."
        )
        assert row["n_examined"] is None, (
            "n_examined must be None: the emitted test-id count measures a "
            "different property and must not stand in for this one."
        )


class TestVacuityGateCoversTheThirdOutcome:
    """The gate has to cover the null that the third outcome introduced.

    Until test_set_untouched carried a null n_examined, every audit row held an
    integer, so a predicate of ``n_examined == 0`` was complete. Adding null to the
    vocabulary opened a shape the gate accepted: PASS with no count at all, which
    says even less than PASS with a zero. The same commit that added the null had to
    widen the gate, and did not.
    """

    @staticmethod
    def _pass_row(**overrides):
        row = {
            "check": "no_station_across_splits",
            "split": "chronological",
            "result": "PASS",
            "n_examined": 12,
            "n_violators": 0,
            "guaranteed": True,
            "entity": "station",
            "n_entities": 3,
            "n_skipped_excluded": 0,
            "n_skipped_no_key": 0,
            "detail": "synthetic",
            "examples": [],
        }
        row.update(overrides)
        return row

    def test_pass_with_a_null_count_is_refused(self) -> None:
        """A PASS that reports no examination is not evidence of anything."""
        with pytest.raises(RuntimeError, match="0 or null"):
            reject_vacuous_checks_in_audit([self._pass_row(n_examined=None)])

    def test_pass_with_a_zero_count_is_still_refused(self) -> None:
        with pytest.raises(RuntimeError, match="0 or null"):
            reject_vacuous_checks_in_audit([self._pass_row(n_examined=0)])

    def test_a_real_pass_and_the_third_outcome_both_survive(self) -> None:
        """Widening the gate must not make the legitimate null unrepresentable."""
        reject_vacuous_checks_in_audit(
            [
                self._pass_row(),
                self._pass_row(
                    check="test_set_untouched",
                    result=ASSERTED_NOT_MEASURABLE_HERE,
                    n_examined=None,
                    n_violators=None,
                    split="all",
                ),
            ]
        )

    def test_the_build_calls_the_shared_gate_not_a_copy(self, tmp_path, monkeypatch) -> None:
        """build_leakage_audit had an inline copy of the gate's predicate.

        The tests exercised the function while the build ran the copy, so the two
        could drift with nothing failing. This patches the shared function and asserts
        the build path goes through it, which an inline copy cannot satisfy.
        """
        import pipeline.tracetriage.splits as S

        called = []

        def _spy(audit):
            called.append(len(audit))
            raise RuntimeError("shared gate reached")

        monkeypatch.setattr(S, "reject_vacuous_checks_in_audit", _spy)

        pages_dir = tmp_path / "pages"
        pages_dir.mkdir()
        (pages_dir / "page1.json").write_text(
            json.dumps([{"id": 1, "start": "2026-08-09T00:00:00Z"}]), encoding="utf-8"
        )
        rows, chron, station, tx, combined = (
            TestLeakageAuditPathHandling._minimal_audit_args(tmp_path)
        )
        with pytest.raises(RuntimeError, match="shared gate reached"):
            S.build_leakage_audit(rows, chron, station, tx, combined, pages_dir=pages_dir)
        assert called and called[0] > 0, "the gate was called on an empty audit"


class TestManifestAssertionEntry:
    """reject_vacuous_checks has to tell an assertion from a vacuous measurement.

    Both carry no usable count. One is a named absence with digests behind it; the
    other is a check that examined nothing and reported a pass. Treating them alike
    either blocks the honest entry or lets the vacuous one through.
    """

    def test_an_assertion_with_a_null_count_is_not_vacuous(self) -> None:
        reject_vacuous_checks(
            {
                "no_station_across_splits": {"passed": True, "n_examined": 7},
                "test_set_untouched": {
                    "result": ASSERTED_NOT_MEASURABLE_HERE,
                    "n_examined": None,
                },
            }
        )

    def test_an_assertion_that_carries_a_number_is_refused(self) -> None:
        """1349 emitted test ids is a count of a different property.

        This is the shape the artifact published: a check that measured nothing,
        reporting the size of the thing it did not measure.
        """
        with pytest.raises(RuntimeError, match="count of something else"):
            reject_vacuous_checks(
                {
                    "test_set_untouched": {
                        "result": ASSERTED_NOT_MEASURABLE_HERE,
                        "n_examined": 1349,
                    }
                }
            )

    def test_a_measured_check_with_a_null_count_is_refused(self) -> None:
        """A null on a check that claims a pass used to raise TypeError.

        ``v.get("n_examined", 0) < 1`` compares None with an int, so the build died
        with a type error instead of naming the check that reported nothing.
        """
        with pytest.raises(RuntimeError, match="examined zero records"):
            reject_vacuous_checks(
                {"no_station_across_splits": {"passed": True, "n_examined": None}}
            )
