"""Tests for pipeline/tracetriage/provenance.py — unit A5.

ACCEPTANCE TESTS (from the A5 task prompt):
  1. unknown never becomes a training label
  2. missing-waterfall never becomes a negative
  3. status "future" never enters the label set (raises FutureObservationError)
  4. "labelled_positive" and "carries_measurable_trace" are distinct fields that
     cannot be conflated

All tests run offline (no network marker needed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.tracetriage.provenance import (
    BASE_RATE_DECISIVE_FRACTION,
    BASE_RATE_NEGATIVE_FRACTION,
    BASE_RATE_POSITIVE_FRACTION,
    BASE_RATE_POSITIVE_TO_NEGATIVE,
    ArtifactStatus,
    FutureObservationError,
    LabelOrigin,
    LabelOutcome,
    ProvenanceInvariantError,
    ProvenanceRecord,
    TracePresence,
    label_from_obs,
    label_observations,
    to_receipt_provenance,
)

# ---------------------------------------------------------------------------
# Minimal valid observation factory
# ---------------------------------------------------------------------------

def _obs(
    *,
    obs_id: int = 12345,
    status: str = "good",
    waterfall_status: str | None = "with-signal",
    waterfall: str | None = "https://example.com/wf.png",
    end: str = "2026-07-01T12:30:00Z",
    retrieved_at: str = "2026-07-02T09:00:00Z",
    ground_station: int = 42,
    transmitter_uuid: str | None = "abc-def",
    source_url: str | None = "https://network.satnogs.org/observations/12345/",
) -> dict:
    """Build a minimal observation dict for testing."""
    return {
        "id": obs_id,
        "status": status,
        "waterfall_status": waterfall_status,
        "waterfall": waterfall,
        "end": end,
        "_retrieved_at": retrieved_at,
        "ground_station": ground_station,
        "transmitter_uuid": transmitter_uuid,
        "_source_url": source_url,
    }


# ===========================================================================
# ACCEPTANCE TEST 1: unknown never becomes a training label
# ===========================================================================

class TestUnknownNeverBecomesTrainingLabel:
    """waterfall_status='unknown' must always produce UNLABELLED, never
    POSITIVE or NEGATIVE.  This is the most dangerous coercion failure because
    'unknown' is the majority class in the API.
    """

    def test_unknown_wf_status_is_unlabelled(self):
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert rec.label_outcome == LabelOutcome.UNLABELLED

    def test_unknown_wf_status_is_not_positive(self):
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert rec.label_outcome != LabelOutcome.POSITIVE

    def test_unknown_wf_status_is_not_negative(self):
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert rec.label_outcome != LabelOutcome.NEGATIVE

    def test_unknown_wf_status_not_eligible_for_training(self):
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert not rec.eligible_for_training

    def test_unknown_wf_status_label_origin_is_unvetted(self):
        """Origin must be SATNOGS_UNVET, not SATNOGS_VET."""
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert rec.label_origin == LabelOrigin.SATNOGS_UNVET

    def test_null_wf_status_with_waterfall_is_unlabelled(self):
        """A null waterfall_status (with URL present) is also unlabelled."""
        rec = label_from_obs(_obs(waterfall_status=None, waterfall="https://example.com/wf.png"))
        assert rec.label_outcome == LabelOutcome.UNLABELLED

    def test_unknown_wf_status_raw_preserved_verbatim(self):
        """The raw API value must never be normalised or overwritten."""
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert rec.waterfall_status_raw == "unknown"

    def test_unlabelled_labelled_positive_is_false(self):
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        assert rec.labelled_positive is False

    def test_unknown_obs_status_with_unknown_wf_is_unlabelled(self):
        """obs status='unknown' (observation itself uncertain) + wf='unknown'."""
        rec = label_from_obs(_obs(status="unknown", waterfall_status="unknown"))
        assert rec.label_outcome == LabelOutcome.UNLABELLED


# ===========================================================================
# ACCEPTANCE TEST 2: missing waterfall never becomes a negative
# ===========================================================================

class TestMissingWaterfallNeverBecomesNegative:
    """A null waterfall URL means the artifact is unusable.  It says nothing
    about the signal.  It must NEVER produce a NEGATIVE label.
    """

    def test_missing_waterfall_url_is_unlabelled(self):
        rec = label_from_obs(_obs(waterfall=None))
        assert rec.label_outcome == LabelOutcome.UNLABELLED

    def test_missing_waterfall_url_is_not_negative(self):
        rec = label_from_obs(_obs(waterfall=None))
        assert rec.label_outcome != LabelOutcome.NEGATIVE

    def test_missing_waterfall_artifact_status_is_missing(self):
        rec = label_from_obs(_obs(waterfall=None))
        assert rec.artifact_status == ArtifactStatus.MISSING

    def test_missing_waterfall_not_eligible_for_training(self):
        rec = label_from_obs(_obs(waterfall=None))
        assert not rec.eligible_for_training

    def test_missing_waterfall_label_origin_is_missing(self):
        rec = label_from_obs(_obs(waterfall=None))
        assert rec.label_origin == LabelOrigin.MISSING

    def test_missing_waterfall_with_without_signal_is_still_unlabelled(self):
        """Even if the API somehow claims 'without-signal' with no URL,
        the missing artifact means we cannot confirm the absence — unlabelled.
        """
        rec = label_from_obs(_obs(waterfall=None, waterfall_status="without-signal"))
        assert rec.label_outcome == LabelOutcome.UNLABELLED
        assert rec.label_outcome != LabelOutcome.NEGATIVE

    def test_missing_waterfall_with_signal_is_still_unlabelled(self):
        """Similarly, a 'with-signal' claim with no URL is unverifiable."""
        rec = label_from_obs(_obs(waterfall=None, waterfall_status="with-signal"))
        assert rec.label_outcome == LabelOutcome.UNLABELLED

    def test_missing_waterfall_trace_presence_is_unknown(self):
        rec = label_from_obs(_obs(waterfall=None))
        assert rec.trace_presence == TracePresence.UNKNOWN

    def test_empty_string_waterfall_is_also_missing(self):
        """An empty string URL is treated as absent."""
        rec = label_from_obs(_obs(waterfall=""))
        assert rec.artifact_status == ArtifactStatus.MISSING
        assert rec.label_outcome == LabelOutcome.UNLABELLED

    def test_ProvenanceRecord_cannot_be_constructed_with_missing_artifact_and_negative(self):
        """The structural invariant in __post_init__ prevents this combination
        from being created at all, even if someone bypasses label_from_obs().
        """
        with pytest.raises(ProvenanceInvariantError, match="artifact is missing"):
            ProvenanceRecord(
                observation_id=1,
                obs_status="good",
                waterfall_status_raw="without-signal",
                label_outcome=LabelOutcome.NEGATIVE,
                trace_presence=TracePresence.ABSENT,
                label_origin=LabelOrigin.SATNOGS_VET,
                artifact_status=ArtifactStatus.MISSING,
                labelled_positive=False,
                carries_measurable_trace=False,
                pass_end_utc=None,
                retrieved_at_utc=None,
                vetting_lag_seconds=None,
                ground_station=None,
                transmitter_uuid=None,
                source_url=None,
            )


# ===========================================================================
# ACCEPTANCE TEST 3: status "future" never enters the label set
# ===========================================================================

class TestFutureObservationNeverEntersLabelSet:
    """Future observations have not happened yet.  They carry null waterfalls
    and waterfall_status='unknown' only because the pass has not run.
    They must never be classified as unlabelled training examples.
    """

    def test_future_obs_raises_FutureObservationError(self):
        with pytest.raises(FutureObservationError):
            label_from_obs(_obs(status="future", waterfall=None, waterfall_status="unknown"))

    def test_future_obs_raises_on_label_from_obs(self):
        """Raising is the correct response — silently returning UNLABELLED
        would let future records slip into the dataset at scale.
        """
        future = _obs(status="future", waterfall=None, waterfall_status="unknown")
        with pytest.raises(FutureObservationError):
            label_from_obs(future)

    def test_future_obs_skipped_when_skip_future_true(self):
        """label_observations with skip_future=True silently drops futures."""
        futures = [_obs(obs_id=i, status="future", waterfall=None, waterfall_status="unknown")
                   for i in range(3)]
        results = label_observations(futures, skip_future=True)
        assert results == []

    def test_future_obs_not_skipped_by_default_in_batch(self):
        """Default batch behaviour raises — caller must opt in to skip."""
        futures = [_obs(obs_id=1, status="future", waterfall=None, waterfall_status="unknown")]
        with pytest.raises(FutureObservationError):
            label_observations(futures)

    def test_future_obs_mixed_batch_skipped(self):
        """skip_future only removes futures; real observations are classified."""
        batch = [
            _obs(obs_id=1, status="future", waterfall=None, waterfall_status="unknown"),
            _obs(obs_id=2, status="good", waterfall_status="with-signal"),
            _obs(obs_id=3, status="good", waterfall_status="without-signal"),
        ]
        results = label_observations(batch, skip_future=True)
        assert len(results) == 2
        assert all(r.obs_status != "future" for r in results)

    def test_future_obs_error_message_mentions_observation_id(self):
        """The exception must say which observation triggered it."""
        with pytest.raises(FutureObservationError, match="12345"):
            label_from_obs(_obs(obs_id=12345, status="future", waterfall=None,
                                waterfall_status="unknown"))

    def test_ProvenanceRecord_rejects_future_obs_status(self):
        """__post_init__ catches a future that bypasses label_from_obs()."""
        with pytest.raises(FutureObservationError):
            ProvenanceRecord(
                observation_id=999,
                obs_status="future",
                waterfall_status_raw="unknown",
                label_outcome=LabelOutcome.UNLABELLED,
                trace_presence=TracePresence.UNKNOWN,
                label_origin=LabelOrigin.FUTURE_PASS,
                artifact_status=ArtifactStatus.FUTURE,
                labelled_positive=False,
                carries_measurable_trace=False,
                pass_end_utc=None,
                retrieved_at_utc=None,
                vetting_lag_seconds=None,
                ground_station=None,
                transmitter_uuid=None,
                source_url=None,
            )


# ===========================================================================
# ACCEPTANCE TEST 4: labelled_positive and carries_measurable_trace are
# distinct fields that cannot be conflated
# ===========================================================================

class TestLabelledPositiveVsMeasurableTraceAreDistinct:
    """A3 found that 17 of 24 vetted 'with-signal' observations had no
    measurable narrowband trace (0.7–3.5 sigma).  This test class enforces
    that the two concepts are kept separate at every level.
    """

    def test_with_signal_is_labelled_positive(self):
        """A 'with-signal' observation is labelled positive."""
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        assert rec.labelled_positive is True
        assert rec.label_outcome == LabelOutcome.POSITIVE

    def test_with_signal_trace_presence_is_unvetted_not_measurable(self):
        """At provenance time, the trace has not yet been scored by the model.
        labelled_positive is True; carries_measurable_trace is False.
        These two are independent facts about the same record.
        """
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        assert rec.labelled_positive is True
        assert rec.carries_measurable_trace is False
        # Explicitly: they differ
        assert rec.labelled_positive != rec.carries_measurable_trace

    def test_labelled_positive_and_carries_measurable_trace_are_different_fields(self):
        """The two fields exist independently on the dataclass.  They are both
        accessible, and they are not aliases for the same thing.
        """
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        # Both are boolean attributes
        assert isinstance(rec.labelled_positive, bool)
        assert isinstance(rec.carries_measurable_trace, bool)
        # They are separate fields — deleting one should not affect the other
        # (this just confirms they are independent attribute slots)
        assert hasattr(rec, "labelled_positive")
        assert hasattr(rec, "carries_measurable_trace")

    def test_ProvenanceRecord_with_measurable_true_requires_trace_presence_measurable(self):
        """If carries_measurable_trace=True, trace_presence must be MEASURABLE.
        __post_init__ enforces this.
        """
        with pytest.raises(ProvenanceInvariantError):
            ProvenanceRecord(
                observation_id=1,
                obs_status="good",
                waterfall_status_raw="with-signal",
                label_outcome=LabelOutcome.POSITIVE,
                trace_presence=TracePresence.UNVETTED,  # inconsistent
                label_origin=LabelOrigin.SATNOGS_VET,
                artifact_status=ArtifactStatus.USABLE,
                labelled_positive=True,
                carries_measurable_trace=True,  # says measurable but TP is UNVETTED
                pass_end_utc=None,
                retrieved_at_utc=None,
                vetting_lag_seconds=None,
                ground_station=None,
                transmitter_uuid=None,
                source_url=None,
            )

    def test_ProvenanceRecord_labelled_positive_must_match_label_outcome(self):
        """labelled_positive=True requires label_outcome=POSITIVE."""
        with pytest.raises(ProvenanceInvariantError):
            ProvenanceRecord(
                observation_id=1,
                obs_status="good",
                waterfall_status_raw="with-signal",
                label_outcome=LabelOutcome.NEGATIVE,  # inconsistent
                trace_presence=TracePresence.ABSENT,
                label_origin=LabelOrigin.SATNOGS_VET,
                artifact_status=ArtifactStatus.USABLE,
                labelled_positive=True,  # says positive but LO is NEGATIVE
                carries_measurable_trace=False,
                pass_end_utc=None,
                retrieved_at_utc=None,
                vetting_lag_seconds=None,
                ground_station=None,
                transmitter_uuid=None,
                source_url=None,
            )

    def test_carries_measurable_true_labelled_positive_false_is_valid(self):
        """A measurable trace in a negative-labelled observation is structurally
        valid — the vetter said no signal, but the model found one. This is
        exactly the type of conflict TraceTriage is designed to surface.
        Only possible if someone calls ProvenanceRecord directly post-model;
        label_from_obs never produces this (trace_presence is not MEASURABLE
        at provenance time), but the dataclass must accept it.
        """
        rec = ProvenanceRecord(
            observation_id=1,
            obs_status="good",
            waterfall_status_raw="without-signal",
            label_outcome=LabelOutcome.NEGATIVE,
            trace_presence=TracePresence.MEASURABLE,  # model found something
            label_origin=LabelOrigin.SATNOGS_VET,
            artifact_status=ArtifactStatus.USABLE,
            labelled_positive=False,
            carries_measurable_trace=True,
            pass_end_utc=None,
            retrieved_at_utc=None,
            vetting_lag_seconds=None,
            ground_station=None,
            transmitter_uuid=None,
            source_url=None,
        )
        assert rec.labelled_positive is False
        assert rec.carries_measurable_trace is True

    def test_with_signal_field_names_are_not_synonyms(self):
        """Access both fields and confirm they carry independently set values."""
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        # labelled_positive True, carries_measurable_trace False
        # They are not the same field accessed under two names.
        assert rec.labelled_positive is not rec.carries_measurable_trace


# ===========================================================================
# Positive / negative classification correctness
# ===========================================================================

class TestBasicClassification:

    def test_with_signal_is_positive(self):
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        assert rec.label_outcome == LabelOutcome.POSITIVE

    def test_without_signal_is_negative(self):
        rec = label_from_obs(_obs(waterfall_status="without-signal"))
        assert rec.label_outcome == LabelOutcome.NEGATIVE

    def test_negative_eligible_for_training(self):
        rec = label_from_obs(_obs(waterfall_status="without-signal"))
        assert rec.eligible_for_training is True

    def test_positive_eligible_for_training(self):
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        assert rec.eligible_for_training is True

    def test_without_signal_trace_presence_is_absent(self):
        rec = label_from_obs(_obs(waterfall_status="without-signal"))
        assert rec.trace_presence == TracePresence.ABSENT

    def test_obs_status_stored_verbatim(self):
        rec = label_from_obs(_obs(status="bad"))
        assert rec.obs_status == "bad"

    def test_negative_labelled_positive_is_false(self):
        rec = label_from_obs(_obs(waterfall_status="without-signal"))
        assert rec.labelled_positive is False

    def test_with_signal_artifact_status_is_usable(self):
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        assert rec.artifact_status == ArtifactStatus.USABLE

    def test_wf_status_raw_stored_verbatim_positive(self):
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        assert rec.waterfall_status_raw == "with-signal"

    def test_wf_status_raw_stored_verbatim_negative(self):
        rec = label_from_obs(_obs(waterfall_status="without-signal"))
        assert rec.waterfall_status_raw == "without-signal"


# ===========================================================================
# Vetting lag
# ===========================================================================

class TestVettingLag:

    def test_vetting_lag_computed_correctly(self):
        # end 2026-07-01T12:00:00Z, retrieved 2026-07-02T12:00:00Z = 86400 s
        rec = label_from_obs(_obs(
            end="2026-07-01T12:00:00Z",
            retrieved_at="2026-07-02T12:00:00Z",
        ))
        assert rec.vetting_lag_seconds == pytest.approx(86400.0)

    def test_vetting_lag_none_when_end_missing(self):
        obs = _obs()
        obs.pop("end")
        rec = label_from_obs(obs)
        assert rec.vetting_lag_seconds is None

    def test_vetting_lag_none_when_retrieved_at_missing(self):
        obs = _obs()
        obs.pop("_retrieved_at")
        rec = label_from_obs(obs)
        assert rec.vetting_lag_seconds is None

    def test_recent_unknown_has_small_lag(self):
        """A small vetting lag distinguishes unvetted-recent from ambiguous."""
        rec = label_from_obs(_obs(
            waterfall_status="unknown",
            end="2026-07-01T12:00:00Z",
            retrieved_at="2026-07-01T14:00:00Z",   # 2 hours later
        ))
        assert rec.vetting_lag_seconds == pytest.approx(7200.0)
        assert rec.label_outcome == LabelOutcome.UNLABELLED

    def test_pass_end_utc_timezone_aware(self):
        rec = label_from_obs(_obs(end="2026-07-01T12:00:00Z"))
        assert rec.pass_end_utc is not None
        assert rec.pass_end_utc.tzinfo is not None


# ===========================================================================
# Grouping keys
# ===========================================================================

class TestGroupingKeys:

    def test_ground_station_preserved(self):
        rec = label_from_obs(_obs(ground_station=777))
        assert rec.ground_station == 777

    def test_transmitter_uuid_preserved(self):
        rec = label_from_obs(_obs(transmitter_uuid="xyz-123"))
        assert rec.transmitter_uuid == "xyz-123"

    def test_transmitter_uuid_none_ok(self):
        rec = label_from_obs(_obs(transmitter_uuid=None))
        assert rec.transmitter_uuid is None

    def test_source_url_preserved(self):
        url = "https://network.satnogs.org/observations/99999/"
        rec = label_from_obs(_obs(source_url=url))
        assert rec.source_url == url


# ===========================================================================
# Receipt provenance assembly
# ===========================================================================

class TestToReceiptProvenance:

    def test_required_keys_present(self):
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        prov = to_receipt_provenance(rec)
        for key in ("source_url", "retrieved_at", "license", "api_label", "label_origin"):
            assert key in prov, f"missing key: {key}"

    def test_license_is_cc_by_sa(self):
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        prov = to_receipt_provenance(rec)
        assert prov["license"] == "CC BY-SA 4.0"

    def test_api_label_preserved(self):
        rec = label_from_obs(_obs(waterfall_status="without-signal"))
        prov = to_receipt_provenance(rec)
        assert prov["api_label"] == "without-signal"

    def test_api_label_unknown_preserved(self):
        rec = label_from_obs(_obs(waterfall_status="unknown"))
        prov = to_receipt_provenance(rec)
        assert prov["api_label"] == "unknown"

    def test_artifact_sha256_forwarded(self):
        rec = label_from_obs(_obs())
        sha = "a" * 64
        prov = to_receipt_provenance(rec, artifact_sha256=sha)
        assert prov["artifact_sha256"] == sha

    def test_split_forwarded(self):
        rec = label_from_obs(_obs())
        prov = to_receipt_provenance(rec, split="train")
        assert prov["split"] == "train"

    def test_split_none_when_unset(self):
        rec = label_from_obs(_obs())
        prov = to_receipt_provenance(rec)
        assert prov["split"] is None

    def test_station_id_forwarded(self):
        rec = label_from_obs(_obs(ground_station=55))
        prov = to_receipt_provenance(rec)
        assert prov["station_id"] == 55


# ===========================================================================
# Batch helper
# ===========================================================================

class TestLabelObservations:

    def test_empty_list(self):
        assert label_observations([]) == []

    def test_mixed_batch_correctly_classified(self):
        batch = [
            _obs(obs_id=1, waterfall_status="with-signal"),
            _obs(obs_id=2, waterfall_status="without-signal"),
            _obs(obs_id=3, waterfall_status="unknown"),
            _obs(obs_id=4, waterfall=None),
        ]
        records = label_observations(batch)
        outcomes = {r.observation_id: r.label_outcome for r in records}
        assert outcomes[1] == LabelOutcome.POSITIVE
        assert outcomes[2] == LabelOutcome.NEGATIVE
        assert outcomes[3] == LabelOutcome.UNLABELLED
        assert outcomes[4] == LabelOutcome.UNLABELLED

    def test_future_in_batch_raises_by_default(self):
        batch = [
            _obs(obs_id=1, waterfall_status="with-signal"),
            _obs(obs_id=2, status="future", waterfall=None, waterfall_status="unknown"),
        ]
        with pytest.raises(FutureObservationError):
            label_observations(batch)

    def test_eligible_for_training_count(self):
        """The decisive rate (eligible POSITIVE + NEGATIVE) should be a
        reasonable fraction, not 0% or 100%.
        """
        batch = [
            _obs(obs_id=1, waterfall_status="with-signal"),
            _obs(obs_id=2, waterfall_status="with-signal"),
            _obs(obs_id=3, waterfall_status="without-signal"),
            _obs(obs_id=4, waterfall_status="unknown"),
            _obs(obs_id=5, waterfall=None),
            _obs(obs_id=6, waterfall_status="unknown"),
            _obs(obs_id=7, waterfall_status="without-signal"),
        ]
        records = label_observations(batch)
        eligible = [r for r in records if r.eligible_for_training]
        # 3 decisive out of 7 → ~43% (above the 29% floor from the real data)
        assert 0 < len(eligible) < len(records)


# ===========================================================================
# Base-rate constants
# ===========================================================================

class TestBaseRateConstants:
    """The measured base rates are load-bearing numbers: A6 and downstream
    calibration depend on them being accurate.  Test that they are present
    and consistent with the documented measurements.
    """

    def test_decisive_fraction_is_documented_value(self):
        assert pytest.approx(0.290, abs=1e-6) == BASE_RATE_DECISIVE_FRACTION

    def test_imbalance_is_documented_value(self):
        assert pytest.approx(1.85, abs=1e-6) == BASE_RATE_POSITIVE_TO_NEGATIVE

    def test_imbalance_matches_positive_to_negative_ratio(self):
        ratio = BASE_RATE_POSITIVE_FRACTION / BASE_RATE_NEGATIVE_FRACTION
        # Should be close to 1.85 (documented in kill gate 1)
        assert ratio == pytest.approx(1.85, rel=0.1)

    def test_positive_plus_negative_equals_decisive(self):
        total = BASE_RATE_POSITIVE_FRACTION + BASE_RATE_NEGATIVE_FRACTION
        assert total == pytest.approx(BASE_RATE_DECISIVE_FRACTION, abs=0.005)


# ===========================================================================
# Edge cases and error paths
# ===========================================================================

class TestEdgeCases:

    def test_bad_obs_status_with_signal_is_positive(self):
        """obs_status='bad' is not future — classify normally from wf_status."""
        rec = label_from_obs(_obs(status="bad", waterfall_status="with-signal"))
        assert rec.label_outcome == LabelOutcome.POSITIVE

    def test_failed_obs_status_with_missing_wf_is_unlabelled(self):
        """A failed observation with no waterfall is artifact-unusable."""
        rec = label_from_obs(_obs(status="failed", waterfall=None))
        assert rec.label_outcome == LabelOutcome.UNLABELLED
        assert rec.artifact_status == ArtifactStatus.MISSING

    def test_observation_id_preserved(self):
        rec = label_from_obs(_obs(obs_id=99001))
        assert rec.observation_id == 99001

    def test_provenance_record_is_frozen(self):
        """Frozen dataclass: attributes cannot be reassigned after creation."""
        rec = label_from_obs(_obs(waterfall_status="with-signal"))
        with pytest.raises((TypeError, AttributeError)):  # FrozenInstanceError
            rec.label_outcome = LabelOutcome.NEGATIVE  # type: ignore[misc]

    def test_eligible_for_training_property_matches_enum(self):
        for wf_status, expected in [
            ("with-signal", True),
            ("without-signal", True),
            ("unknown", False),
        ]:
            rec = label_from_obs(_obs(waterfall_status=wf_status))
            assert rec.eligible_for_training == expected

    def test_waterfall_status_raw_is_none_when_missing_artifact(self):
        """When waterfall is missing, wf_status raw is stored but the outcome
        overrides to UNLABELLED regardless.
        """
        rec = label_from_obs(_obs(waterfall=None, waterfall_status=None))
        assert rec.waterfall_status_raw is None
        assert rec.label_outcome == LabelOutcome.UNLABELLED


class TestInvariantsSurviveOptimisedMode:
    """`python -O` removes every assert statement, and pytest never runs with it.

    Written as asserts, the structural invariants below were enforced in every
    environment that tests them and in none of the environments that run the
    pipeline. Under `-O` a record constructed cleanly holding
    `label_outcome=UNLABELLED` with `labelled_positive=True`, which is the exact
    conflation this unit exists to prevent. This test is the only thing that
    catches a regression back to `assert`.
    """

    SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
from pipeline.tracetriage import provenance as pv

kw = dict(
    observation_id=1, obs_status="good", waterfall_status_raw="with-signal",
    label_outcome=pv.LabelOutcome.UNLABELLED,
    trace_presence=pv.TracePresence.ABSENT,
    label_origin=list(pv.LabelOrigin)[0],
    artifact_status=list(pv.ArtifactStatus)[0],
    labelled_positive=True,
    carries_measurable_trace=True,
    pass_end_utc=None, retrieved_at_utc=None, vetting_lag_seconds=None,
    ground_station=None, transmitter_uuid=None, source_url=None,
)
try:
    pv.ProvenanceRecord(**kw)
    print("CONSTRUCTED")
except pv.ProvenanceInvariantError:
    print("BLOCKED")
"""

    def _run(self, optimised: bool) -> str:
        import subprocess
        import sys as _sys

        repo = str(Path(__file__).resolve().parents[1])
        cmd = [_sys.executable]
        if optimised:
            cmd.append("-O")
        cmd += ["-c", self.SCRIPT.format(repo=repo)]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return (out.stdout + out.stderr).strip()

    def test_blocked_in_normal_mode(self):
        assert "BLOCKED" in self._run(optimised=False)

    def test_still_blocked_under_dash_O(self):
        result = self._run(optimised=True)
        assert "BLOCKED" in result, (
            "an inconsistent record was constructed under `python -O`; the "
            f"invariants have regressed to assert statements. Got: {result}"
        )

    def test_no_assert_statements_remain_in_the_invariant_block(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "pipeline" / "tracetriage" / "provenance.py"
        ).read_text(encoding="utf-8")
        post_init = source.split("def __post_init__", 1)[1].split("\n    @property", 1)[0]
        # Statements, not mentions: a comment explaining why asserts are absent
        # must not itself trip this.
        statements = [
            line.strip()
            for line in post_init.splitlines()
            if line.strip().startswith("assert ")
        ]
        assert statements == [], f"invariants regressed to assert: {statements}"
