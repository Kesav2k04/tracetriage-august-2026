"""Image-only baseline models for TraceTriage — unit A6.

Two honest baselines, both calibrated, both measured against a prior-only floor.
These are the bar that gate 5 requires the physics-conditioned model to beat.

MODELS
======

1. **CentreEnergy** — the simplest meaningful heuristic.
   Crop the waterfall to the physics-predicted central band (±N columns around
   centre_px) and return the mean pixel brightness in that strip, normalised
   against the full-crop mean.  A signal concentrates energy at the tuned
   frequency; a noise waterfall is flat.  Requires hz_per_px and centre_px from
   the waterfall parser.  Observations where geometry fails are excluded and
   counted.

2. **HogLR** — HOG features + regularised logistic regression.
   Crop to A2's spectrogram box, resize to a fixed size, compute HOG (orientation
   histograms), L2-normalise, and fit a LogisticRegression with L2 penalty.
   The crop is load-bearing, not cosmetic: over the full page HOG identifies the
   ground station at 70.5% against a 24.6% baseline, and cropping removes about
   13 points of that.
   Calibrated via Platt scaling (CalibratedClassifierCV, sigmoid, cv=5).

TRAPS GUARDED AGAINST
=====================
- ``unknown`` waterfall_status is never used as a label (not even as negative).
  Only POSITIVE and NEGATIVE outcomes from label_from_obs() enter any split.
- A missing waterfall URL is not a negative example.  Excluded and counted.
- A failed geometry parse is not a zero-energy score.  Excluded and counted.
- The exclusion table sums to the full corpus size with no residual bucket.
- Accuracy is not reported.  The metrics are Brier score, log loss, calibration
  slope and intercept, and a reliability curve.  The prior-only floor is the
  first row in every table.
- RAM: images are streamed one at a time.  No image array lives in memory across
  multiple observations.
- GPU: HOG and logistic regression are CPU-only (scikit-learn).  The waterfall
  parser's OCR backend avoids CUDA to prevent memory contention.
- A random split would leak because station and transmitter identity carries
  signal. The split here is chronological by each observation's own start time.
  Ordering by observation id was tried and is NOT chronological: it disagrees
  with time order on 27% of adjacent pairs here. Real grouped splits are built
  in B1, and split.audit records what this split cannot show.

SPLIT
=====
Temporary chronological split: sort by the observation's own start time, taken
from its waterfall URL because the manifest stores none and the local filename
carries none. ``floor(0.80 * n_total)`` observations go to train, the remainder
to val. The frozen test set is not touched. Station identity remains learnable
from the spectrogram itself after cropping (57.3% against a 24.6% baseline), so
only a cold-station split can separate signal detection from station
recognition; that is B1.

SEED
====
All randomness is through ``numpy.random.default_rng(seed)`` and
``sklearn`` ``random_state=seed``.  Everything is reproducible from the receipt.

PUBLIC API
==========
  load_labelled(manifest_path, snapshot_dir, seed=42)
      → CorpusData (the split label sets + image paths)

  CentreEnergyBaseline
      .fit(train_data) → self
      .predict_proba(data) → np.ndarray (n, 2)

  HogLrBaseline
      .fit(train_data, seed=42) → self
      .predict_proba(data) → np.ndarray (n, 2)

  evaluate(y_true, proba, y_prior) → EvalMetrics
      Brier score, log loss, calibration slope/intercept, ECE, reliability bins.

  build_exclusion_table(manifest_path) → ExclusionTable
      Counts that sum to the manifest corpus size with no residual.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Temporary chronological split ratio.
TRAIN_FRACTION: float = 0.80

# Centre-energy strip half-width in pixels (derived from typical Hz/px values
# and a ±2 kHz band: at 80 Hz/px that is 25 px, at 123 Hz/px it is 16 px;
# we use 30 to be inclusive across both client families).
CENTRE_ENERGY_HALF_WIDTH_PX: int = 30

# HOG parameters — fixed so the feature dimension is reproducible.
HOG_IMAGE_SIZE: tuple[int, int] = (128, 256)   # (width, height) after resize
HOG_PIXELS_PER_CELL: tuple[int, int] = (8, 8)
HOG_CELLS_PER_BLOCK: tuple[int, int] = (2, 2)
HOG_ORIENTATIONS: int = 9
HOG_MULTICHANNEL: bool = False          # convert to greyscale first

# LogisticRegression regularisation strength (inverse, so smaller = more).
LR_C: float = 0.1
LR_MAX_ITER: int = 1000

# Reliability-curve bins.
N_RELIABILITY_BINS: int = 10


# ---------------------------------------------------------------------------
# Manifest adapter
# ---------------------------------------------------------------------------

def _adapt_obs_for_provenance(obs_row: dict[str, Any]) -> dict[str, Any]:
    """Map a manifest observation record to the shape provenance.label_from_obs expects.

    The snapshot stores a stripped-down record.  provenance.py was written for
    the raw API observation dict.  The keys differ:

      Manifest          →  Provenance
      waterfall_url     →  waterfall         (presence/absence of URL)
      retrieved_at      →  _retrieved_at     (vetting lag)
      (not present)     →  status            (defaults to "good" for past obs)
      (not present)     →  end               (not needed for label, only for lag)

    Observations in this snapshot are all past; none are future.  There is no
    ``status`` field.  provenance.label_from_obs reads ``obs.get("status",
    "unknown")`` and only raises on ``status == "future"``, so mapping to the
    absent-key default is safe.
    """
    return {
        "id":                   obs_row["id"],
        "status":               "good",          # all snapshot obs are past
        "waterfall":            obs_row.get("waterfall_url"),   # URL or None
        "waterfall_status":     obs_row.get("waterfall_status"),
        "_retrieved_at":        obs_row.get("retrieved_at"),
        "end":                  None,             # not in manifest obs record
        "ground_station":       obs_row.get("ground_station"),
        "transmitter_uuid":     obs_row.get("transmitter_uuid"),
        "_source_url":          obs_row.get("source_url"),
    }


# ---------------------------------------------------------------------------
# Exclusion table
# ---------------------------------------------------------------------------

@dataclass
class ExclusionTable:
    """Counts that explain every observation's disposition.

    All counts sum to ``corpus_total``.  No residual bucket.

    Attributes
    ----------
    corpus_total:
        Total observations in the manifest.
    n_missing_url:
        Waterfall URL absent (reason: NO_WATERFALL_URL).  Not a negative.
    n_transient_fail:
        Waterfall fetch failed transiently (THROTTLED, TIMEOUT, HTTP_ERROR).
        Excluded from evaluation; may succeed on a re-run.  Distinguished from
        permanent failures so the exclusion table does not hide retry candidates.
    n_unknown_label:
        ``waterfall_status == "unknown"``.  Never coerced to negative.
    n_positive:
        ``waterfall_status == "with-signal"`` — decisive positive.
    n_negative:
        ``waterfall_status == "without-signal"`` — decisive negative.
    n_geometry_fail_train:
        In training split, decisive but waterfall geometry parse failed.
        Excluded from model training; counted here, never scored as zero.
    n_geometry_fail_val:
        Same for validation split.
    """
    corpus_total: int = 0
    n_missing_url: int = 0
    n_transient_fail: int = 0
    n_unknown_label: int = 0
    n_positive: int = 0
    n_negative: int = 0
    n_geometry_fail_train: int = 0
    n_geometry_fail_val: int = 0

    def check_sum(self) -> None:
        """Raise AssertionError if counts do not sum to corpus_total.

        The geometry fail counts are a sub-partition of the decisive split, not
        a separate bucket.  They explain which decisive observations were
        excluded *after* splitting, not before.  The top-level sum is:
            missing_url + transient_fail + unknown_label + positive + negative
            == corpus_total
        """
        top = (
            self.n_missing_url
            + self.n_transient_fail
            + self.n_unknown_label
            + self.n_positive
            + self.n_negative
        )
        if top != self.corpus_total:
            raise AssertionError(
                f"Exclusion table does not sum to corpus_total: "
                f"{top} != {self.corpus_total}.  "
                f"Counts: missing_url={self.n_missing_url}, "
                f"transient={self.n_transient_fail}, "
                f"unknown={self.n_unknown_label}, "
                f"positive={self.n_positive}, "
                f"negative={self.n_negative}"
            )

    def to_dict(self) -> dict[str, int]:
        return {
            "corpus_total": self.corpus_total,
            "n_missing_url": self.n_missing_url,
            "n_transient_fail": self.n_transient_fail,
            "n_unknown_label": self.n_unknown_label,
            "n_positive": self.n_positive,
            "n_negative": self.n_negative,
            "n_geometry_fail_train": self.n_geometry_fail_train,
            "n_geometry_fail_val": self.n_geometry_fail_val,
        }


_TRANSIENT_REASONS = frozenset({"THROTTLED", "TIMEOUT", "HTTP_ERROR"})


def build_exclusion_table(
    manifest: dict[str, Any],
) -> ExclusionTable:
    """Build the exclusion table from a loaded manifest dict.

    Parameters
    ----------
    manifest:
        Loaded DATASET_MANIFEST.json as a dict.

    Returns
    -------
    ExclusionTable
        Counts that sum to ``len(manifest["observations"])``.
    """
    obs_list = manifest["observations"]
    tbl = ExclusionTable(corpus_total=len(obs_list))

    for obs in obs_list:
        url = obs.get("waterfall_url")
        reason = obs.get("waterfall_missing_reason")
        wf_status = obs.get("waterfall_status")

        if not url:
            if reason in _TRANSIENT_REASONS:
                tbl.n_transient_fail += 1
            else:
                # NO_WATERFALL_URL or any permanent reason
                tbl.n_missing_url += 1
        elif wf_status == "with-signal":
            tbl.n_positive += 1
        elif wf_status == "without-signal":
            tbl.n_negative += 1
        else:
            # "unknown" or any other non-decisive status
            tbl.n_unknown_label += 1

    tbl.check_sum()
    return tbl


# ---------------------------------------------------------------------------
# Corpus split
# ---------------------------------------------------------------------------

@dataclass
class ObsRecord:
    """Everything needed about one decisive, storable observation."""
    obs_id: int
    label: int              # 1 = positive, 0 = negative
    image_path: Path
    waterfall_url: str


@dataclass
class CorpusData:
    """Loaded, split corpus.

    Attributes
    ----------
    train:
        Observations in the training split, the oldest 80% by observation time.
    val:
        Observations in the validation split, the newest 20% by observation time.
    n_train_positive, n_train_negative:
        Label counts in the training split.
    n_val_positive, n_val_negative:
        Label counts in the validation split.
    train_prior:
        Fraction of train decisive labels that are positive.  This is the
        prior-only model's prediction on every validation observation.
    snapshot_id:
        From the manifest header.
    manifest_sha256:
        SHA-256 of the manifest file itself, for receipt traceability.
    exclusion:
        Full exclusion table.
    split_audit:
        What this split does and does not demonstrate: the time span each half
        covers, whether they overlap, and how much of the validation split sits
        on a station or transmitter the model already saw. Reported rather than
        left implicit, because a validation number is only as strong as the
        separation behind it, and on a corpus spanning a single evening that
        separation is thin.
    """
    train: list[ObsRecord]
    val: list[ObsRecord]
    n_train_positive: int
    n_train_negative: int
    n_val_positive: int
    n_val_negative: int
    train_prior: float
    snapshot_id: str
    manifest_sha256: str
    exclusion: ExclusionTable
    split_audit: dict[str, Any] = field(default_factory=dict)


_WATERFALL_TS = re.compile(r"_(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})")


def _observation_time(waterfall_url: str | None) -> str | None:
    """The observation's UTC start as a sortable string, from its source URL.

    SatNOGS serves a waterfall as ``waterfall_<id>_<ISO8601 with dashes>.png``,
    and the manifest records no timestamp of its own, so the URL is the only per
    observation time available without going back to the API. Note that the
    LOCAL filename is ``waterfall_<id>.png`` and carries no time at all, so
    reading the stored path instead silently yields nothing.

    Returns None when the URL carries no timestamp, so the caller can count that
    rather than quietly assume an ordering it does not have.
    """
    if not waterfall_url:
        return None
    m = _WATERFALL_TS.search(waterfall_url)
    if m is None:
        return None
    return f"{m.group(1)}T{m.group(2)}:{m.group(3)}:{m.group(4)}"


def load_labelled(
    manifest_path: Path,
    snapshot_dir: Path,
    *,
    seed: int = 42,
) -> CorpusData:
    """Load the decisive-only, chronologically split corpus from a snapshot manifest.

    Parameters
    ----------
    manifest_path:
        Path to DATASET_MANIFEST.json.
    snapshot_dir:
        Snapshot root directory (parent of ``waterfalls/``).
    seed:
        Random seed (passed through for reproducibility; the chronological split
        is deterministic regardless, but the seed is recorded in the receipt).

    Returns
    -------
    CorpusData

    Notes
    -----
    The split is chronological only: observations sorted ascending by id, the
    oldest ``floor(TRAIN_FRACTION * n_total)`` become training, the remainder
    validation.

    A random split would leak because a few hundred ground stations are spread
    across the corpus and station identity carries signal.  Real grouped
    (cold-station, cold-transmitter, combined) splits are built in B1.  This
    function records that limitation in the returned ``CorpusData``.
    """
    import hashlib  # noqa: PLC0415 — local import to keep module-level deps minimal

    raw = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    manifest: dict[str, Any] = json.loads(raw.decode("utf-8"))

    obs_list: list[dict[str, Any]] = manifest["observations"]
    snapshot_id: str = manifest.get("snapshot_id", "unknown")

    exclusion = build_exclusion_table(manifest)
    waterfalls_dir = snapshot_dir / "waterfalls"

    # Indexed once. The previous version scanned all manifest entries per record
    # to find a URL, which is about 2 million comparisons for 739 records.
    by_id: dict[int, dict[str, Any]] = {o["id"]: o for o in obs_list}

    def _time_of(obs_id: int) -> str | None:
        return _observation_time(by_id.get(obs_id, {}).get("waterfall_url"))

    # Collect decisive observations with a stored waterfall image.
    decisive: list[tuple[int, int, Path]] = []  # (id, label, image_path)
    for obs in obs_list:
        url = obs.get("waterfall_url")
        reason = obs.get("waterfall_missing_reason")
        wf_status = obs.get("waterfall_status")

        if not url or reason is not None:
            continue
        if wf_status not in ("with-signal", "without-signal"):
            continue

        label = 1 if wf_status == "with-signal" else 0
        obs_id = obs["id"]
        img_path = waterfalls_dir / f"waterfall_{obs_id}.png"
        if not img_path.exists():
            # Should not happen if the manifest is consistent with the disk, but
            # log it rather than crashing.
            logger.warning("Image not found for obs %d: %s", obs_id, img_path)
            continue
        decisive.append((obs_id, label, img_path))

    # Sort by the observation's own timestamp, not by id.
    #
    # Ascending id was used for this and described in the receipt as a
    # chronological split. It is not one. Measured on this corpus, id order
    # disagrees with time order on 27% of adjacent pairs, and the resulting
    # halves overlap in time by more than five hours: the "later" split ran
    # 18:16 to 23:53 while the "earlier" one ran 14:34 to 23:51. A split that
    # interleaves is a quasi-random split wearing a temporal label, which
    # overstates what the validation number demonstrates.
    #
    # The manifest carries no observation timestamp, so it comes from the
    # waterfall filename, which SatNOGS builds as
    # waterfall_<id>_<ISO8601 with dashes>.png. Anything unparseable sorts last
    # under its id rather than being silently dropped, and the count is logged.
    n_no_timestamp = sum(1 for t in decisive if _time_of(t[0]) is None)
    if n_no_timestamp:
        logger.warning(
            "%d of %d decisive observations have no parseable timestamp; "
            "they sort last and the split is that much less temporal",
            n_no_timestamp, len(decisive),
        )
    decisive.sort(key=lambda t: (_time_of(t[0]) or "9999", t[0]))

    n_total = len(decisive)
    split_idx = math.floor(TRAIN_FRACTION * n_total)

    def _to_records(rows: list[tuple[int, int, Path]]) -> list[ObsRecord]:
        records = []
        for obs_id, label, img_path in rows:
            entry = by_id.get(obs_id, {})
            records.append(
                ObsRecord(
                    obs_id=obs_id,
                    label=label,
                    image_path=img_path,
                    waterfall_url=entry.get("waterfall_url") or "",
                )
            )
        return records

    train_rows = decisive[:split_idx]
    val_rows = decisive[split_idx:]

    train_records = _to_records(train_rows)
    val_records = _to_records(val_rows)

    n_train_pos = sum(r.label for r in train_records)
    n_train_neg = len(train_records) - n_train_pos
    n_val_pos = sum(r.label for r in val_records)
    n_val_neg = len(val_records) - n_val_pos

    train_prior = n_train_pos / max(len(train_records), 1)

    def _span(rows: list[tuple[int, int, Path]]) -> tuple[str | None, str | None]:
        ts = sorted(t for t in (_time_of(r[0]) for r in rows) if t)
        return (ts[0], ts[-1]) if ts else (None, None)

    tr_lo, tr_hi = _span(train_rows)
    va_lo, va_hi = _span(val_rows)

    def _field(rows, key):
        return {by_id.get(r[0], {}).get(key) for r in rows}

    stations_tr = _field(train_rows, "ground_station")
    tx_tr = _field(train_rows, "transmitter_uuid")
    val_seen_station = sum(
        1 for r in val_rows if by_id.get(r[0], {}).get("ground_station") in stations_tr
    )
    val_seen_tx = sum(
        1 for r in val_rows if by_id.get(r[0], {}).get("transmitter_uuid") in tx_tr
    )

    split_audit: dict[str, Any] = {
        "ordered_by": "observation start time parsed from the waterfall filename",
        "n_without_timestamp": n_no_timestamp,
        "train_time_range": [tr_lo, tr_hi],
        "val_time_range": [va_lo, va_hi],
        "time_ranges_overlap": bool(tr_hi and va_lo and tr_hi > va_lo),
        "n_val_on_a_station_seen_in_train": val_seen_station,
        "n_val_on_a_transmitter_seen_in_train": val_seen_tx,
        "n_val": len(val_rows),
        "caveat": (
            "This corpus covers a single evening, so a temporal split cannot "
            "demonstrate temporal generalisation however it is ordered. Most of "
            "the validation split also sits on ground stations the model trained "
            "on. Treat the validation numbers as in-distribution. Cold-station, "
            "cold-transmitter and combined splits are B1's job and are what any "
            "generalisation claim has to rest on."
        ),
        "station_identifiability": {
            "task": "predict which of the 6 busiest ground stations produced an "
                    "observation, from HOG features alone, 5-fold CV on 309 "
                    "decisive observations",
            "majority_class_baseline": 0.246,
            "accuracy_full_image": 0.705,
            "accuracy_cropped_to_spectrogram": 0.573,
            "reading": (
                "Cropping to the spectrogram removes about 13 points of this, "
                "which was the axes, tick labels and colorbar. The remaining gap "
                "over the baseline is in the spectrogram itself: a station's "
                "noise floor, bandwidth and RFI environment are genuinely "
                "visible. So no crop makes station identity unlearnable, and a "
                "split that lets a station appear on both sides cannot separate "
                "signal detection from station recognition. This is the measured "
                "reason B1's cold-station split is required rather than "
                "preferable."
            ),
        },
    }

    return CorpusData(
        split_audit=split_audit,
        train=train_records,
        val=val_records,
        n_train_positive=n_train_pos,
        n_train_negative=n_train_neg,
        n_val_positive=n_val_pos,
        n_val_negative=n_val_neg,
        train_prior=train_prior,
        snapshot_id=snapshot_id,
        manifest_sha256=manifest_sha256,
        exclusion=exclusion,
    )


# ---------------------------------------------------------------------------
# Image loading helpers
# ---------------------------------------------------------------------------

def _load_grey_crop(
    image_path: Path,
    *,
    target_size: tuple[int, int] | None = None,
) -> np.ndarray | None:
    """Load a waterfall PNG as a greyscale float32 array, optionally resized.

    Returns None on any load error (allows a caller to skip rather than crash).
    Converts RGBA → RGB → L to avoid colour plane leakage.
    """
    try:
        pil = Image.open(image_path)
        if pil.mode == "RGBA":
            bg = Image.new("RGB", pil.size, (255, 255, 255))
            bg.paste(pil, mask=pil.split()[3])
            pil = bg
        pil = pil.convert("L")   # greyscale
        if target_size is not None:
            pil = pil.resize(target_size, Image.LANCZOS)
        arr = np.array(pil, dtype=np.float32) / 255.0
        return arr
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot load image %s: %s", image_path, exc)
        return None


# ---------------------------------------------------------------------------
# Centre-energy heuristic
# ---------------------------------------------------------------------------

def centre_strip_score(
    crop_arr: np.ndarray,
    strip_x0: int,
    strip_x1: int,
) -> float | None:
    """Mean row-normalised intensity inside a column strip. Unbounded.

    Split out from image loading so the measurement can be tested on arrays with
    a known answer, without an OCR backend in the way. That separation is the
    point: the version this replaced could only be exercised end to end, so a
    fault in the arithmetic looked like a fact about the data.

    Each row is z-scored against its own median and MAD before the strip is
    measured. A pass brightens as the satellite closes range, so raw row means
    carry a vertical gradient that has nothing to do with the tuned frequency,
    and A3 measured that removing it is the difference between seeing a carrier
    and seeing the gradient. Nothing is normalised along the time axis, because
    that would delete a stationary carrier, which is exactly the shape a
    Doppler-corrected capture leaves.

    Higher means more energy at the tuned frequency. A signal on a SatNOGS
    waterfall is BRIGHT, established in A3 by locating carriers at 32 to 54
    sigma with an argmax over luminance.

    Returned unbounded on purpose. An earlier version computed
    ``1 - strip_mean / full_mean`` and clipped to [0, 1]. Measured on this
    corpus every value of that expression is negative, about -0.11 for both
    classes, so the clip pinned all 591 training observations to exactly 0.0.
    The feature became a constant, the model had one input value for every
    sample, and its Brier score landed exactly on the prior. That reads as "the
    feature is not discriminative" when the real fault was that the feature was
    never computed. Platt scaling wants an unbounded score and works out offset
    and direction by itself, so no squashing belongs here.
    """
    if crop_arr.size == 0 or strip_x1 <= strip_x0:
        return None
    lum = crop_arr.astype(np.float32)
    med = np.median(lum, axis=1, keepdims=True)
    mad = np.median(np.abs(lum - med), axis=1, keepdims=True) * 1.4826
    z = (lum - med) / np.maximum(mad, 1e-6)
    score = float(z[:, strip_x0:strip_x1].mean())
    return score if math.isfinite(score) else None


@dataclass
class CentreEnergyBaseline:
    """Mean row-normalised intensity in the central frequency strip.

    A signal concentrates energy near the tuned frequency; a noise waterfall is
    spatially flat along the frequency axis. Each row is z-scored against its own
    median and MAD first, so the brightness gradient that changing range puts
    into every pass does not compete with the thing being measured. The raw score
    is unbounded and becomes a probability through Platt scaling.

    Requires the waterfall parser (EasyOCR) to extract hz_per_px and centre_px.
    Observations where parsing fails are excluded from scoring (not scored zero).

    Parameters
    ----------
    half_width_px:
        Half-width of the central strip in pixels.  Default: CENTRE_ENERGY_HALF_WIDTH_PX.
    seed:
        Random seed for the calibrator.
    """
    half_width_px: int = CENTRE_ENERGY_HALF_WIDTH_PX
    seed: int = 42
    _calibrator: Any = field(default=None, repr=False, compare=False)
    _train_raw_scores: list[float] = field(default_factory=list, repr=False, compare=False)
    _train_labels: list[int] = field(default_factory=list, repr=False, compare=False)
    _n_geometry_fail: int = 0

    def _score_one(self, image_path: Path) -> float | None:
        """Return the centre-energy ratio for one image, or None on geometry fail.

        Uses the waterfall parser to get crop_box and centre_px.
        Falls back to geometric centre if centre_px is None (e.g. no rx_freq).
        Returns None only when the parser reports a hard degraded state (no
        crop_box / no hz_per_px).
        """
        geom = _geometry_of(image_path)

        # If geometry failed, exclude this observation.
        if geom.degraded is not None or geom.crop_box is None or geom.hz_per_px is None:
            return None

        crop = geom.crop_box
        arr = _load_grey_crop(image_path)
        if arr is None:
            return None

        # Clamp crop to image dimensions.
        h, w = arr.shape
        cx0 = max(0, min(crop.x0, w - 1))
        cx1 = max(cx0 + 1, min(crop.x1, w))
        cy0 = max(0, min(crop.y0, h - 1))
        cy1 = max(cy0 + 1, min(crop.y1, h))

        crop_arr = arr[cy0:cy1, cx0:cx1]
        if crop_arr.size == 0:
            return None

        # Determine the centre column within the crop array.
        # centre_px is crop-relative when present (see waterfall._compute_centre_px).
        cen = (
            float(geom.centre_px)
            if geom.centre_px is not None
            else crop_arr.shape[1] / 2.0
        )

        # Centre strip columns (clamp to crop width).
        strip_x0 = max(0, int(cen) - self.half_width_px)
        strip_x1 = min(crop_arr.shape[1], int(cen) + self.half_width_px + 1)
        if strip_x1 <= strip_x0:
            return None

        return centre_strip_score(crop_arr, strip_x0, strip_x1)

    def fit(self, train_data: list[ObsRecord]) -> CentreEnergyBaseline:
        """Compute raw scores on training data and fit a Platt-scaling calibrator."""
        from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

        raw_scores: list[float] = []
        labels: list[int] = []
        n_fail = 0

        for rec in train_data:
            s = self._score_one(rec.image_path)
            if s is None:
                n_fail += 1
                continue
            raw_scores.append(s)
            labels.append(rec.label)

        self._n_geometry_fail = n_fail
        self._train_raw_scores = raw_scores
        self._train_labels = labels

        if len(set(labels)) < 2 or len(labels) < 10:
            logger.warning(
                "CentreEnergy: too few labelled train samples (%d) for calibration",
                len(labels),
            )
            self._calibrator = None
            return self

        # Fit Platt scaling (logistic regression on the raw score).
        scores_arr = np.array(raw_scores).reshape(-1, 1)
        labels_arr = np.array(labels)
        lr = LogisticRegression(C=1.0, max_iter=1000, random_state=self.seed)
        lr.fit(scores_arr, labels_arr)
        self._calibrator = lr
        return self

    def predict_proba(
        self,
        data: list[ObsRecord],
        *,
        return_geometry_fail_count: bool = False,
    ) -> tuple[np.ndarray, np.ndarray, int]:
        """Score observations, returning calibrated P(positive).

        Returns
        -------
        proba : np.ndarray shape (N,)
            Calibrated probability of positive for each scorable observation.
        indices : np.ndarray shape (N,) int
            Indices into ``data`` for which a score was produced.
        n_fail : int
            Number of observations skipped due to geometry failure.
        """
        proba_list: list[float] = []
        indices: list[int] = []
        n_fail = 0

        for i, rec in enumerate(data):
            s = self._score_one(rec.image_path)
            if s is None:
                n_fail += 1
                continue
            if self._calibrator is not None:
                p = float(self._calibrator.predict_proba([[s]])[0, 1])
            else:
                # Fallback: raw score as probability.
                p = s
            proba_list.append(p)
            indices.append(i)

        return np.array(proba_list, dtype=np.float32), np.array(indices, dtype=int), n_fail


# ---------------------------------------------------------------------------
# HOG feature extractor
# ---------------------------------------------------------------------------

def _geometry_of(image_path: Path):
    """Parse one waterfall's geometry, once per path per process.

    Both baselines need the same crop box for the same image, so without a cache
    every observation is OCR'd twice and a stage-1 run spends about 42 minutes
    where 21 will do. At stage 2's 30,000 images that difference stops being a
    convenience. Keyed on the path string because Path hashes fine but the cache
    is clearer read as a string key.

    pass_duration_s only feeds seconds_per_px, which neither baseline reads, so a
    fixed positive value is correct here rather than merely tolerated.
    """
    return _parse_cached(str(image_path))


@cache
def _parse_cached(image_path_str: str):
    from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: PLC0415

    return parse_waterfall(
        Path(image_path_str),
        observation_id=0,
        pass_duration_s=200.0,
    )


def _hog_features(image_path: Path) -> np.ndarray | None:
    """Extract HOG features from the spectrogram region of a waterfall PNG.

    Returns a 1-D float64 feature vector, or None when the image cannot be
    loaded or its geometry cannot be parsed.

    **The crop is not optional.** This function used to pass the whole PNG to
    HOG, axes, tick labels, title and colorbar included, while the module
    docstring said "the cropped spectrogram". Measured on this corpus, HOG over
    the full image predicts which of the six busiest ground stations produced an
    observation at 70.5% accuracy against a 24.6% majority-class baseline. The
    furniture around the plot carries station identity, and 129 of the 148
    validation observations sit on a station seen in training, so a model reading
    it can score well by recognising the station rather than by finding a signal.

    Cropping to A2's ``crop_box`` is what A2 is for. It costs a geometry parse
    per image, and an observation whose geometry fails is excluded and counted by
    the caller rather than fed a full-frame feature vector, which would quietly
    reintroduce exactly the leak this removes.
    """
    try:
        from skimage.feature import hog  # noqa: PLC0415
    except ImportError:
        logger.error("scikit-image not installed; HOG features unavailable")
        return None

    geom = _geometry_of(image_path)
    if geom.degraded is not None or geom.crop_box is None:
        return None

    full = _load_grey_crop(image_path)
    if full is None:
        return None

    h, w = full.shape
    cb = geom.crop_box
    x0 = max(0, min(cb.x0, w - 1))
    x1 = max(x0 + 1, min(cb.x1, w))
    y0 = max(0, min(cb.y0, h - 1))
    y1 = max(y0 + 1, min(cb.y1, h))
    cropped = full[y0:y1, x0:x1]
    if cropped.size == 0:
        return None

    # Resize the crop, not the page. Image.fromarray needs 8-bit here because
    # _load_grey_crop already scaled to [0, 1].
    pil = Image.fromarray((np.clip(cropped, 0.0, 1.0) * 255).astype(np.uint8))
    arr = np.array(
        pil.resize(HOG_IMAGE_SIZE, Image.LANCZOS), dtype=np.float32
    ) / 255.0

    try:
        feats = hog(
            arr,
            orientations=HOG_ORIENTATIONS,
            pixels_per_cell=HOG_PIXELS_PER_CELL,
            cells_per_block=HOG_CELLS_PER_BLOCK,
            feature_vector=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("HOG failed for %s: %s", image_path, exc)
        return None

    # L2-normalise to remove overall brightness differences.
    norm = float(np.linalg.norm(feats))
    if norm > 0:
        feats = feats / norm
    return feats.astype(np.float64)


@dataclass
class HogLrBaseline:
    """HOG features + regularised logistic regression, calibrated.

    Parameters
    ----------
    seed:
        Controls sklearn random state for reproducibility.
    """
    seed: int = 42
    _model: Any = field(default=None, repr=False, compare=False)
    _n_geometry_fail_train: int = 0

    def fit(self, train_data: list[ObsRecord]) -> HogLrBaseline:
        """Extract HOG features from training images and fit calibrated LR.

        Calibration via CalibratedClassifierCV with sigmoid (Platt) and
        stratified 5-fold, which is the standard for small medical/science
        classification tasks.
        """
        from sklearn.calibration import CalibratedClassifierCV  # noqa: PLC0415
        from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
        from sklearn.preprocessing import StandardScaler  # noqa: PLC0415

        feats_list: list[np.ndarray] = []
        labels: list[int] = []
        n_fail = 0

        logger.info("HogLR: extracting features from %d train observations", len(train_data))
        for i, rec in enumerate(train_data):
            if i % 100 == 0 and i > 0:
                logger.info("  %d / %d", i, len(train_data))
            f = _hog_features(rec.image_path)
            if f is None:
                n_fail += 1
                continue
            feats_list.append(f)
            labels.append(rec.label)

        self._n_geometry_fail_train = n_fail

        if len(feats_list) < 10 or len(set(labels)) < 2:
            logger.warning(
                "HogLR: too few training samples (%d) for fitting", len(feats_list)
            )
            self._model = None
            return self

        X = np.stack(feats_list, axis=0)
        y = np.array(labels, dtype=int)

        # Standard-scale the HOG vectors (they are already L2-normalised but
        # per-component scale differences still matter for regularisation).
        scaler = StandardScaler()
        X = scaler.fit_transform(X)

        base_lr = LogisticRegression(
            C=LR_C,
            max_iter=LR_MAX_ITER,
            solver="saga",
            random_state=self.seed,
            class_weight="balanced",  # handles the 1.67:1 imbalance without silently ignoring it
        )
        # CalibratedClassifierCV with sigmoid = Platt scaling.
        # cv=5: 5 stratified folds on training data only.
        calibrated = CalibratedClassifierCV(base_lr, method="sigmoid", cv=5)
        calibrated.fit(X, y)

        # Bundle scaler and calibrated model together.
        self._model = (scaler, calibrated)
        logger.info("HogLR: fit complete")
        return self

    def predict_proba(
        self,
        data: list[ObsRecord],
    ) -> tuple[np.ndarray, np.ndarray, int]:
        """Score observations with calibrated probability.

        Returns
        -------
        proba : np.ndarray shape (N,)
            Calibrated P(positive).
        indices : np.ndarray shape (N,) int
            Indices into ``data`` for which a score was produced.
        n_fail : int
            Feature extraction failures (image unreadable etc.).
        """
        proba_list: list[float] = []
        indices: list[int] = []
        n_fail = 0

        for i, rec in enumerate(data):
            f = _hog_features(rec.image_path)
            if f is None:
                n_fail += 1
                continue
            if self._model is None:
                proba_list.append(0.5)
            else:
                scaler, calibrated = self._model
                f_scaled = scaler.transform(f.reshape(1, -1))
                p = float(calibrated.predict_proba(f_scaled)[0, 1])
                proba_list.append(p)
            indices.append(i)

        return np.array(proba_list, dtype=np.float32), np.array(indices, dtype=int), n_fail


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------

@dataclass
class EvalMetrics:
    """Evaluation metrics for a calibrated probabilistic classifier.

    All metrics are on decisive labelled observations.  Unlabelled observations
    are never used for evaluation — not as positives, not as negatives.

    Attributes
    ----------
    n_scored:
        Number of observations that received a score (i.e. not excluded).
    brier_score:
        Mean squared error between predicted probability and true label.
        Lower is better.  A prior-only model (always predicting the base rate)
        sets the floor.
    log_loss:
        Log loss (binary cross-entropy).  Lower is better.
    calibration_slope:
        Slope of a logistic regression of true labels on log-odds of predicted
        probability.  1.0 = perfectly calibrated.  < 1 = overconfident.  > 1 =
        underconfident.
    calibration_intercept:
        Intercept of the same regression.  0 = no systematic offset.
    reliability_bins:
        N_RELIABILITY_BINS pairs (mean_predicted, fraction_positive) for the
        reliability (calibration) curve.
    ece:
        Expected calibration error (weighted mean of |bin_mean - bin_frac|).
    """
    model_name: str
    n_scored: int
    n_excluded: int
    brier_score: float
    log_loss: float
    calibration_slope: float
    calibration_intercept: float
    reliability_bins: list[dict[str, float]]
    ece: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "n_scored": self.n_scored,
            "n_excluded": self.n_excluded,
            "brier_score": self.brier_score,
            "log_loss": self.log_loss,
            "calibration_slope": self.calibration_slope,
            "calibration_intercept": self.calibration_intercept,
            "reliability_bins": self.reliability_bins,
            "ece": self.ece,
        }


_EPS = 1e-7


def evaluate(
    y_true: np.ndarray,
    proba: np.ndarray,
    model_name: str,
    n_total_val: int,
) -> EvalMetrics:
    """Compute evaluation metrics.

    Parameters
    ----------
    y_true:
        Binary labels (0/1) for scored observations.
    proba:
        Predicted P(positive) for those observations.
    model_name:
        Label for the receipt.
    n_total_val:
        Total validation observations (including excluded ones); used to compute
        n_excluded.
    """
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

    n = len(y_true)
    n_excluded = n_total_val - n

    if n == 0:
        return EvalMetrics(
            model_name=model_name,
            n_scored=0,
            n_excluded=n_excluded,
            brier_score=float("nan"),
            log_loss=float("nan"),
            calibration_slope=float("nan"),
            calibration_intercept=float("nan"),
            reliability_bins=[],
            ece=float("nan"),
        )

    p = np.clip(proba, _EPS, 1.0 - _EPS).astype(np.float64)
    y = y_true.astype(np.float64)

    # Brier score.
    brier = float(np.mean((p - y) ** 2))

    # Log loss.
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    # Calibration slope and intercept via logistic regression of labels on log-odds.
    log_odds = np.log(p / (1 - p)).reshape(-1, 1)
    cal_lr = LogisticRegression(C=1e6, max_iter=1000, random_state=0)
    cal_lr.fit(log_odds, y_true)
    cal_slope = float(cal_lr.coef_[0, 0])
    cal_intercept = float(cal_lr.intercept_[0])

    # Reliability bins.
    bins = np.linspace(0.0, 1.0, N_RELIABILITY_BINS + 1)
    rel_bins: list[dict[str, float]] = []
    ece_num = 0.0
    ece_den = 0.0
    for i in range(N_RELIABILITY_BINS):
        lo, hi = bins[i], bins[i + 1]
        mask = (p >= lo) & (p < hi) if i < N_RELIABILITY_BINS - 1 else (p >= lo) & (p <= hi)
        if mask.sum() == 0:
            continue
        mean_pred = float(p[mask].mean())
        frac_pos = float(y[mask].mean())
        n_bin = int(mask.sum())
        rel_bins.append({
            "bin_lower": round(float(lo), 4),
            "bin_upper": round(float(hi), 4),
            "mean_predicted": round(mean_pred, 6),
            "fraction_positive": round(frac_pos, 6),
            "n": n_bin,
        })
        ece_num += abs(mean_pred - frac_pos) * n_bin
        ece_den += n_bin

    ece = float(ece_num / ece_den) if ece_den > 0 else float("nan")

    return EvalMetrics(
        model_name=model_name,
        n_scored=n,
        n_excluded=n_excluded,
        brier_score=round(brier, 6),
        log_loss=round(ll, 6),
        calibration_slope=round(cal_slope, 6),
        calibration_intercept=round(cal_intercept, 6),
        reliability_bins=rel_bins,
        ece=round(ece, 6),
    )


def prior_only_metrics(
    y_true: np.ndarray,
    train_prior: float,
    model_name: str,
    n_total_val: int,
) -> EvalMetrics:
    """Compute metrics for the prior-only model (always predict train base rate).

    This is the floor.  Any model that cannot beat this on Brier score has
    learned nothing.
    """
    proba = np.full(len(y_true), fill_value=train_prior, dtype=np.float32)
    return evaluate(y_true, proba, model_name, n_total_val)
