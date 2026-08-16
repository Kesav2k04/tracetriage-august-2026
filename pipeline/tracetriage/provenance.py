"""Label provenance module for TraceTriage — unit A5.

Every observation that enters the pipeline carries a provenance record that
tracks where its label came from, why it is or is not eligible for training, and
whether "labelled positive" and "carries a measurable trace" can be asserted
independently.  These two things are NOT the same, and conflating them causes A6
to train against a target it cannot see.

RULES — these are invariants, not guidelines
============================================

1. ``status == "future"``  The observation has not happened yet.  It carries a
   null waterfall and ``waterfall_status == "unknown"`` only because the pass
   has not run.  A future observation must never enter the label set; it would
   become a spurious negative at scale.

2. ``waterfall is None``  The artifact URL is missing.  The observation is
   *artifact-unusable*.  It is NOT a negative label.  A waterfall URL being
   absent says nothing about what the satellite transmitted.

3. ``waterfall_status == "unknown"``  The observation has not been vetted, or a
   vetter found the waterfall ambiguous.  It stays *unlabelled*.  It is NOT a
   negative label.  An unlabelled observation carries information (its prior
   class is not 0%) and must not be discarded as background noise.

4. ``waterfall_status`` is SILVER evidence.  Even "with-signal" does not
   guarantee a measurable narrowband carrier.  A3 measured 24 vetted
   with-signal observations: only 7 carried a trace strong enough to score;
   the other 17 sat between 0.7 and 3.5 sigma.  The ``trace_presence`` field
   records this distinction so downstream code can separate "labelled positive"
   from "model sees something".

5. Vetting lags capture.  A recent observation with ``status == "good"`` and
   ``waterfall_status == "unknown"`` is *unvetted*, not negative.  The
   ``vetting_lag_seconds`` field carries the elapsed time between pass end and
   snapshot retrieval; downstream can use it to distinguish truly unvetted
   records from permanently ambiguous ones.

MEASURED BASE RATES (gate 1, do not re-derive)
===============================================
  Decisive overall:          29.0% of observations
  Imbalance (pos/neg):       1.85 : 1  (positive-to-negative)
  Approx decisive positives: 18.83% of all observations
  Approx decisive negatives: 10.17% of all observations

These are carried forward as named constants for downstream calibration and
imbalance reporting.  They are NOT used to rebalance the label set silently.

PUBLIC API
==========
  ``label_from_obs(obs)`` → ``ProvenanceRecord``
      Classifies one observation.  Raises ``FutureObservationError`` when
      ``status == "future"``.  Never raises for any other input.

  ``ProvenanceRecord``    Frozen dataclass.  All fields described below.

  ``LabelOutcome``        POSITIVE | NEGATIVE | UNLABELLED
  ``TracePresence``       MEASURABLE | VISIBLE_BUT_UNMEASURABLE | ABSENT |
                          UNVETTED | UNKNOWN

SCHEMA NOTE
===========
The ``provenance`` sub-object of ``triage_receipt.schema.json`` (v0.2.1) has
``api_label`` and ``label_origin`` as its first-class fields.  The full
``ProvenanceRecord`` here is a superset; ``to_receipt_provenance(record, ...)``
assembles only the fields the receipt contract requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Measured base rates — carry forward, do not rebalance silently
# ---------------------------------------------------------------------------

BASE_RATE_DECISIVE_FRACTION: float = 0.290       # 29.0%
BASE_RATE_POSITIVE_TO_NEGATIVE: float = 1.85     # imbalance among decisive labels
# Derived:
BASE_RATE_POSITIVE_FRACTION: float = 0.1883      # approx 18.83% of all obs
BASE_RATE_NEGATIVE_FRACTION: float = 0.1017      # approx 10.17% of all obs


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class LabelOutcome(StrEnum):
    """Training-label eligibility for one observation.

    These are the only three states that exist.  There is no implicit fourth
    state.  An observation is either clearly positive, clearly negative, or
    unlabelled and therefore ineligible for the training target.

    Never coerce UNLABELLED to NEGATIVE.  Never infer NEGATIVE from a missing
    waterfall.
    """
    POSITIVE   = "positive"    # waterfall_status == "with-signal"
    NEGATIVE   = "negative"    # waterfall_status == "without-signal"
    UNLABELLED = "unlabelled"  # "unknown" wf_status, missing artifact, or unvetted


class TracePresence(StrEnum):
    """Whether a measurable narrowband trace exists in the waterfall.

    This is SEPARATE from ``LabelOutcome``.  A3 confirmed that "with-signal"
    (labelled positive) does not imply "measurable trace": 17 of 24 vetted
    with-signal observations had no scorable carrier (0.7–3.5 sigma).

    The model in A6 trains against ``LabelOutcome``.  The physics scoring in A7
    intersects against ``MEASURABLE``.  Conflating the two means A6 trains on
    a target the model cannot observe.
    """
    MEASURABLE              = "measurable"               # clear narrowband trace (A3: 7/24)
    VISIBLE_BUT_UNMEASURABLE = "visible_but_unmeasurable" # A3: 17/24 with-signal but <4σ
    ABSENT                  = "absent"                   # no signal, vetted negative
    UNVETTED                = "unvetted"                  # artifact exists but not yet scored
    UNKNOWN                 = "unknown"                  # artifact missing or observation future


class LabelOrigin(StrEnum):
    """Who set the ``waterfall_status`` field.

    SatNOGS vetting is a mix of automatic classifiers and human review.  The
    API does not expose who voted on an individual observation.  This enum
    captures what can be inferred from the fields available.
    """
    SATNOGS_VET    = "satnogs_vet"    # waterfall_status is a decisive vetted value
    SATNOGS_UNVET  = "satnogs_unvet"  # waterfall_status == "unknown": unvetted or ambiguous
    MISSING        = "missing"        # waterfall URL absent — vetting never happened
    FUTURE_PASS    = "future_pass"    # status == "future": observation not yet run


class ArtifactStatus(StrEnum):
    """Usability state of the waterfall PNG artifact."""
    USABLE    = "usable"    # URL present; download and parse may still fail later
    MISSING   = "missing"   # waterfall URL is None or empty in the API record
    FUTURE    = "future"    # observation has not run yet (waterfall cannot exist)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProvenanceInvariantError(ValueError):
    """A structural invariant of a provenance record was violated.

    Deliberately not an ``assert``. Python's ``-O`` flag removes every assert
    statement, and the test suite never runs under ``-O``, so invariants written
    as asserts are enforced in every environment that tests them and in none of
    the environments that matter. Measured before this change: under ``-O`` a
    record constructed cleanly with ``label_outcome=UNLABELLED`` alongside
    ``labelled_positive=True`` and ``trace_presence=ABSENT`` alongside
    ``carries_measurable_trace=True``, which is the exact conflation this unit
    exists to make impossible.
    """


class FutureObservationError(ValueError):
    """Raised when ``label_from_obs`` receives a future observation.

    A future observation must not enter the label pipeline at any stage.  The
    caller must filter them out before calling ``label_from_obs``.  Raising
    ensures that a future record never silently becomes an unlabelled example.
    """


# ---------------------------------------------------------------------------
# Provenance record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProvenanceRecord:
    """Complete label provenance for one SatNOGS observation.

    Attributes
    ----------
    observation_id : int
        SatNOGS observation id.

    obs_status : str
        Raw ``status`` field from the API ("good", "bad", "failed", "unknown",
        "future").  Stored verbatim; never normalised.

    waterfall_status_raw : str | None
        Raw ``waterfall_status`` from the API.  One of "with-signal",
        "without-signal", "unknown", or None.  Never coerced.

    label_outcome : LabelOutcome
        Training-label eligibility.  POSITIVE / NEGATIVE / UNLABELLED.

    trace_presence : TracePresence
        Whether a measurable narrowband trace is present.  SEPARATE from
        ``label_outcome``.  Both fields must be checked independently.

    label_origin : LabelOrigin
        Who set the label.

    artifact_status : ArtifactStatus
        Usability state of the waterfall PNG.

    labelled_positive : bool
        Shorthand: ``label_outcome == LabelOutcome.POSITIVE``.
        A separate field so static analysis and test assertions can reference
        it without importing the enum, and so the distinction from
        ``carries_measurable_trace`` is visible at the dataclass level.

    carries_measurable_trace : bool
        True only when ``trace_presence == TracePresence.MEASURABLE``.
        This is NOT the same as ``labelled_positive``.  Do not use one in place
        of the other.

    pass_end_utc : datetime | None
        Parsed UTC datetime of observation end.  Used to compute vetting lag.

    retrieved_at_utc : datetime | None
        UTC datetime when this record was fetched by the snapshot builder.
        Used to compute vetting lag.

    vetting_lag_seconds : float | None
        Seconds between ``pass_end_utc`` and ``retrieved_at_utc``.  Positive
        means the observation was retrieved after the pass ran (the normal
        case).  None when either timestamp is missing.  Unvetted observations
        with a small lag are qualitatively different from permanently-unknown
        observations: lag lets a downstream stage distinguish them.

    ground_station : int | None
        Station id.  Grouping key for cold-station splits.

    transmitter_uuid : str | None
        Transmitter UUID.  Grouping key for cold-transmitter splits.

    source_url : str | None
        Canonical URL for this observation on SatNOGS Network.
    """

    observation_id: int

    # Raw fields — stored verbatim, never coerced
    obs_status: str
    waterfall_status_raw: str | None

    # Derived label fields
    label_outcome: LabelOutcome
    trace_presence: TracePresence
    label_origin: LabelOrigin
    artifact_status: ArtifactStatus

    # Shorthand booleans — must never be conflated
    labelled_positive: bool
    carries_measurable_trace: bool

    # Timestamps and lag
    pass_end_utc: datetime | None
    retrieved_at_utc: datetime | None
    vetting_lag_seconds: float | None

    # Grouping keys
    ground_station: int | None
    transmitter_uuid: str | None

    # Audit trail
    source_url: str | None

    def __post_init__(self) -> None:
        # Structural invariants. These raise rather than assert: `python -O`
        # strips assert statements, which would leave every check below inert
        # in exactly the runs that are not under test.
        if self.obs_status == "future":
            raise FutureObservationError(
                f"observation {self.observation_id} has status='future'; "
                "future observations must never enter the label set. "
                "Filter them before calling label_from_obs()."
            )
        # labelled_positive must agree with label_outcome
        if self.labelled_positive != (self.label_outcome == LabelOutcome.POSITIVE):
            raise ProvenanceInvariantError(
                "labelled_positive must equal (label_outcome == POSITIVE)"
            )
        # carries_measurable_trace must agree with trace_presence
        if self.carries_measurable_trace != (
            self.trace_presence == TracePresence.MEASURABLE
        ):
            raise ProvenanceInvariantError(
                "carries_measurable_trace must equal (trace_presence == MEASURABLE)"
            )
        # UNLABELLED from a decisive waterfall_status is only allowed when the
        # artifact is missing.  If the artifact is present and waterfall_status
        # is decisive, the outcome must be POSITIVE or NEGATIVE.
        if (
            self.label_outcome == LabelOutcome.UNLABELLED
            and self.waterfall_status_raw in ("with-signal", "without-signal")
            and self.artifact_status != ArtifactStatus.MISSING
        ):
            raise ProvenanceInvariantError(
                "UNLABELLED outcome with a decisive waterfall_status requires "
                "a missing artifact; cannot be UNLABELLED when artifact is "
                "present and waterfall_status is decisive"
            )
        # POSITIVE / NEGATIVE must come from decisive waterfall_status AND a
        # present artifact.
        if self.label_outcome in (LabelOutcome.POSITIVE, LabelOutcome.NEGATIVE):
            if self.waterfall_status_raw not in ("with-signal", "without-signal"):
                raise ProvenanceInvariantError(
                    f"Decisive label requires decisive waterfall_status; "
                    f"got {self.waterfall_status_raw!r}"
                )
            if self.artifact_status == ArtifactStatus.MISSING:
                raise ProvenanceInvariantError(
                    "Cannot assign POSITIVE or NEGATIVE when the artifact is missing"
                )
        # A missing artifact must never produce NEGATIVE
        if (
            self.artifact_status == ArtifactStatus.MISSING
            and self.label_outcome == LabelOutcome.NEGATIVE
        ):
            raise ProvenanceInvariantError(
                "A missing waterfall must never become a NEGATIVE label"
            )

    @property
    def eligible_for_training(self) -> bool:
        """True only for POSITIVE and NEGATIVE outcomes.

        UNLABELLED observations are excluded from the training target.
        They may still be used for semi-supervised or uncertainty estimation,
        but never as a target label.
        """
        return self.label_outcome in (LabelOutcome.POSITIVE, LabelOutcome.NEGATIVE)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def _parse_utc(s: str | None) -> datetime | None:
    """Parse an ISO-8601 UTC string to a timezone-aware datetime, or None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.rstrip("Z").replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _vetting_lag(end: datetime | None, retrieved: datetime | None) -> float | None:
    """Seconds between pass end and snapshot retrieval."""
    if end is None or retrieved is None:
        return None
    return (retrieved - end).total_seconds()


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------

def label_from_obs(obs: dict[str, Any]) -> ProvenanceRecord:
    """Derive a ``ProvenanceRecord`` from one raw SatNOGS observation dict.

    Parameters
    ----------
    obs:
        One observation record as stored in the snapshot, matching
        ``contracts/source_observation.schema.json``.

    Returns
    -------
    ProvenanceRecord

    Raises
    ------
    FutureObservationError
        When ``obs["status"] == "future"``.  Future observations must be
        excluded before calling this function; the caller is responsible for
        the filter.  This exception exists so a future record that slips
        through fails loudly rather than silently becoming an unlabelled
        example.
    """
    obs_id: int = obs["id"]
    obs_status: str = obs.get("status", "unknown")
    wf_status: str | None = obs.get("waterfall_status")
    waterfall_url: str | None = obs.get("waterfall")

    # -----------------------------------------------------------------------
    # Rule 1: future observations are excluded — raise immediately
    # -----------------------------------------------------------------------
    if obs_status == "future":
        raise FutureObservationError(
            f"observation {obs_id} has status='future'; "
            "it has not run yet and must not enter the label pipeline."
        )

    # -----------------------------------------------------------------------
    # Artifact usability
    # -----------------------------------------------------------------------
    artifact_status = (
        ArtifactStatus.USABLE if waterfall_url else ArtifactStatus.MISSING
    )

    # -----------------------------------------------------------------------
    # Rule 2: missing waterfall → artifact-unusable, NEVER negative
    # Rule 3: unknown waterfall_status → unlabelled, NEVER negative
    # -----------------------------------------------------------------------
    if not waterfall_url:
        # Waterfall URL absent — artifact-unusable regardless of wf_status.
        # wf_status may be "unknown" here; that is consistent, but the root
        # reason for exclusion from training is the missing artifact.
        label_outcome = LabelOutcome.UNLABELLED
        trace_presence = TracePresence.UNKNOWN
        label_origin = LabelOrigin.MISSING
    elif wf_status == "with-signal":
        # Rule 4: "with-signal" is human judgment that *something* is visible.
        # It is a labelled positive.  Whether a measurable carrier exists is a
        # separate question answered by the model, not by the vetter.
        label_outcome = LabelOutcome.POSITIVE
        # TracePresence at provenance time is UNVETTED by the model; A7 will
        # update it to MEASURABLE or VISIBLE_BUT_UNMEASURABLE after scoring.
        trace_presence = TracePresence.UNVETTED
        label_origin = LabelOrigin.SATNOGS_VET
    elif wf_status == "without-signal":
        label_outcome = LabelOutcome.NEGATIVE
        trace_presence = TracePresence.ABSENT
        label_origin = LabelOrigin.SATNOGS_VET
    else:
        # wf_status == "unknown" or None (with waterfall URL present)
        # Rule 3: unknown = unvetted / ambiguous; never coerce to negative.
        label_outcome = LabelOutcome.UNLABELLED
        trace_presence = TracePresence.UNVETTED
        label_origin = LabelOrigin.SATNOGS_UNVET

    # -----------------------------------------------------------------------
    # Shorthand booleans — derived, not independently settable
    # -----------------------------------------------------------------------
    labelled_positive = label_outcome == LabelOutcome.POSITIVE
    carries_measurable = trace_presence == TracePresence.MEASURABLE

    # -----------------------------------------------------------------------
    # Vetting lag
    # -----------------------------------------------------------------------
    pass_end_utc = _parse_utc(obs.get("end"))
    retrieved_at_utc = _parse_utc(obs.get("_retrieved_at"))
    lag = _vetting_lag(pass_end_utc, retrieved_at_utc)

    # -----------------------------------------------------------------------
    # Assemble record (post_init validates all structural invariants)
    # -----------------------------------------------------------------------
    return ProvenanceRecord(
        observation_id=obs_id,
        obs_status=obs_status,
        waterfall_status_raw=wf_status,
        label_outcome=label_outcome,
        trace_presence=trace_presence,
        label_origin=label_origin,
        artifact_status=artifact_status,
        labelled_positive=labelled_positive,
        carries_measurable_trace=carries_measurable,
        pass_end_utc=pass_end_utc,
        retrieved_at_utc=retrieved_at_utc,
        vetting_lag_seconds=lag,
        ground_station=obs.get("ground_station"),
        transmitter_uuid=obs.get("transmitter_uuid"),
        source_url=obs.get("_source_url"),
    )


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

def label_observations(
    obs_list: list[dict[str, Any]],
    *,
    skip_future: bool = False,
) -> list[ProvenanceRecord]:
    """Classify a list of observations, returning one record per observation.

    Parameters
    ----------
    obs_list:
        List of raw observation dicts from the snapshot.
    skip_future:
        If True, silently skip ``status == "future"`` observations instead of
        raising.  Use this when the caller wants to pre-filter at batch level.
        Default False — future observations raise ``FutureObservationError``.

    Returns
    -------
    list[ProvenanceRecord]
        One record per non-skipped observation.
    """
    records: list[ProvenanceRecord] = []
    for obs in obs_list:
        if skip_future and obs.get("status") == "future":
            continue
        records.append(label_from_obs(obs))
    return records


# ---------------------------------------------------------------------------
# Receipt assembly helper
# ---------------------------------------------------------------------------

def to_receipt_provenance(
    record: ProvenanceRecord,
    *,
    artifact_sha256: str | None = None,
    split: str | None = None,
) -> dict[str, Any]:
    """Assemble the ``provenance`` sub-object required by
    ``contracts/triage_receipt.schema.json``.

    Parameters
    ----------
    record:
        A ``ProvenanceRecord`` produced by ``label_from_obs``.
    artifact_sha256:
        SHA-256 hex digest of the waterfall PNG used to generate this receipt.
        Matches the snapshot manifest entry.  None when the waterfall is missing.
    split:
        Split assignment: "train", "calibration", or "test".  None before
        splits are frozen.

    Returns
    -------
    dict matching the ``provenance`` schema in triage_receipt.schema.json.
    """
    return {
        "source_url": record.source_url or "",
        "retrieved_at": (
            record.retrieved_at_utc.isoformat() if record.retrieved_at_utc else ""
        ),
        "license": "CC BY-SA 4.0",
        "api_label": record.waterfall_status_raw,
        "label_origin": record.label_origin.value,
        "artifact_sha256": artifact_sha256,
        "split": split,
        "station_id": record.ground_station,
        "transmitter_uuid": record.transmitter_uuid,
    }
