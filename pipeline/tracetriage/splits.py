"""Grouped split builder for TraceTriage (Unit B1).

Produces four split types that are free of station-, transmitter-, and
orbital-revolution-level leakage.  All splits are deterministic given a seed.

Design decisions (recorded here so they appear in the artifact):
- Chronological split: entity-aware.  If a transmitter first appears in the
  cal window, every observation for that transmitter is moved to cal.  Same for
  test.  The guarantee is that *each transmitter UUID appears in exactly one
  partition*.
- Cold-station split: 20% of ground stations assigned to test, 10% to cal,
  remainder to train (seed-controlled random assignment).
- Cold-transmitter split: 20% of transmitters to test, 10% to cal.  NORAD
  cluster (gap ≤ 5 within same international designator prefix) stays together;
  all transmitters for a deployment are placed in the same partition.
- Cold-combined split: test = obs where BOTH the station and the transmitter
  are in their respective cold-held-out sets.  Cal = obs where the station is
  in the cal-station set OR the transmitter is in the cal-tx set (but neither
  is in the test set).  Train = everything else.
- Orbital revolution: computed from TLE mean motion and observation start time
  as floor((start_unix - epoch_unix) / period_s).  Each observation carries its
  revolution index; the no-revolution-across-splits check then applies.

A3 doppler-correction verdict is read from artifacts/a3_overlays/summary.json.
It is NEVER derived from metadata fields (doppler-correction-per-sec,
rigctl-port) because those fields are null / 4532 on BOTH corrected and
uncorrected observations.  Every observation absent from the A3 summary gets
verdict "unresolved".

Duplicate images: checked by waterfall_sha256.  Any observation whose SHA256
already appears in a higher-priority partition is moved to that partition
(not discarded), so the builder never silently drops data.

Excluded fields (not usable as features, documented here):
- waterfall_status / waterfall_status_user / waterfall_status_datetime:
    post-observation human vetting; the target, not a feature.
- vetted_status / vetted_user / vetted_datetime: same.
- retrieved_at: snapshot acquisition time, post-observation.
- waterfall_bytes: correlates with download success, post-observation.
- Any station-aggregate statistic derived from the split (station avg label,
  station decile rank, etc.) would carry future information into training.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths (always resolve from the repo root, never from cwd — per Finding 3)
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO / "artifacts" / "DATASET_MANIFEST.json"
_A3_SUMMARY_PATH = _REPO / "artifacts" / "a3_overlays" / "summary.json"
_PAGES_DIR = Path("D:/tracetriage_data/snap-stage1/pages")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Entity allocation fractions for the single-axis cold splits (train = remainder).
COLD_CAL_FRACTION = 0.10
COLD_TEST_FRACTION = 0.20

#: Entity allocation fractions for the cold-combined split, which needs its own.
#:
#: Cold-combined keeps an observation only where its station tier and its
#: transmitter tier agree, so partition sizes go as the *product* of the two
#: fractions, not their value. Reusing 0.20/0.10 leaves a calibration set of 16
#: observations, which is too small to fit a calibration map on.
#:
#: Measured through the shipped build path at seed 42, decisive labels in brackets.
#: These are not the numbers an isolated draw gives: the tiers are drawn after the
#: other three splits consume the generator, so the entities differ, and a curve
#: measured off to the side would not describe what ships.
#:
#:   test / cal      train          calibration     test          entity checks
#:   0.30 / 0.30      453 (73)       286 (96)        259 (105)     pass
#:   0.28 / 0.22      818 (162)      113 (44)        243 (102)     pass
#:   0.25 / 0.20      945 (188)      110 (49)        183 (76)      pass   <- chosen
#:   0.22 / 0.18     1132 (252)       72 (31)        161 (69)      pass
#:
#: 0.30/0.30 was tried first and rejected: it gave a test set larger than train and
#: only 73 decisive labels to train on, so the cold-combined number would have
#: measured an undertrained model rather than the cost of unseen entities. 0.25/0.20
#: is the largest train that still leaves a usable test set.
#:
#: Two consequences to carry forward, both measured, neither fixed here:
#:
#: 1. Train is 945 observations against chronological's 2,595, so a drop on this
#:    split confounds "unseen entities" with "less training data". B6 separates them
#:    with a size-matched chronological model.
#: 2. Calibration holds 49 decisive labels. Isotonic regression is not admissible on
#:    49 points and neither is picking the calibrator by measured reliability on
#:    them, so B3's choice here is temperature scaling by constraint, not by
#:    comparison.
COMBINED_CAL_FRACTION = 0.20
COMBINED_TEST_FRACTION = 0.25

#: Chronological fractions (applied by entity then by observation count).
CHRON_TRAIN_FRACTION = 0.70
CHRON_CAL_FRACTION = 0.15

#: NORAD gap threshold for rideshare-cluster grouping.
NORAD_CLUSTER_GAP = 5

#: Correction verdicts that carry physics information.
VERDICT_UNCORRECTED = "UNCORRECTED"
VERDICT_CORRECTED = "CORRECTED"
VERDICT_UNRESOLVED = "unresolved"  # lower-case = not in A3 pool or no verdict


# ---------------------------------------------------------------------------
# TLE helpers (inline, no sgp4 dependency at module level)
# ---------------------------------------------------------------------------

def _tle_epoch_to_unix(tle1: str) -> float:
    """Return the Unix timestamp (float) of the TLE epoch from line 1."""
    epoch_field = tle1[18:32].strip()
    yy = int(epoch_field[:2])
    day_frac = float(epoch_field[2:])
    year = 2000 + yy if yy < 57 else 1900 + yy
    jan1 = datetime.datetime(year, 1, 1, tzinfo=datetime.UTC)
    epoch_dt = jan1 + datetime.timedelta(days=day_frac - 1.0)
    return epoch_dt.timestamp()


def _mean_motion_revs_per_day(tle2: str) -> float:
    """Parse mean motion from TLE line 2 (cols 52-62, revs/day)."""
    return float(tle2[52:63].strip())


def orbital_revolution_index(tle1: str, tle2: str, start_iso: str) -> int:
    """Integer orbital revolution index at the start of the observation.

    Defined as floor((start_unix - epoch_unix) / period_s).
    This is a deterministic function of the TLE and observation start time;
    it does not require sgp4 at import time and has no network dependency.
    """
    epoch_unix = _tle_epoch_to_unix(tle1)
    mm = _mean_motion_revs_per_day(tle2)
    if mm <= 0:
        raise ValueError(f"Invalid mean motion {mm} in TLE2: {tle2!r}")
    period_s = 86400.0 / mm
    start_unix = datetime.datetime.fromisoformat(
        start_iso.replace("Z", "+00:00")
    ).timestamp()
    return math.floor((start_unix - epoch_unix) / period_s)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_raw_pages(pages_dir: Path) -> dict[int, dict[str, Any]]:
    """Load all raw observation records keyed by observation id."""
    raw: dict[int, dict[str, Any]] = {}
    for pf in sorted(pages_dir.glob("*.json")):
        for obs in json.loads(pf.read_text(encoding="utf-8")):
            raw[obs["id"]] = obs
    return raw


def _load_a3_verdicts(summary_path: Path) -> dict[int, str]:
    """Return {obs_id: verdict} from the A3 overlay summary.

    Verdicts are: "CORRECTED", "UNCORRECTED", or "UNRESOLVED" (A3's own term).
    We keep them exactly as written in the file.
    """
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {entry["obs_id"]: entry["verdict"] for entry in summary}


def _build_obs_table(
    manifest_path: Path,
    pages_dir: Path,
    a3_summary_path: Path,
) -> list[dict[str, Any]]:
    """Build the enriched observation table used by all split types.

    Each row has:
      id, start_iso, start_unix, ground_station, transmitter_uuid,
      norad_cat_id, waterfall_status, waterfall_sha256,
      tle1, tle2, orbital_revolution, correction_verdict,
      client_family

    Observations whose raw page is not found are omitted with a warning (this
    should not happen on a well-formed stage-1 snapshot).
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_pages = _load_raw_pages(pages_dir)
    a3_verdicts = _load_a3_verdicts(a3_summary_path)

    rows: list[dict[str, Any]] = []
    for mo in manifest["observations"]:
        oid = mo["id"]
        raw = raw_pages.get(oid)
        if raw is None:
            import warnings  # noqa: PLC0415
            warnings.warn(
                f"obs {oid} not found in raw pages; skipped", stacklevel=2
            )
            continue

        tle1 = raw.get("tle1") or ""
        tle2 = raw.get("tle2") or ""
        try:
            rev_idx = orbital_revolution_index(tle1, tle2, raw["start"])
        except Exception:
            rev_idx = -1  # degraded; still placed, checked in leakage audit

        # A3 verdict: read from summary, never inferred from metadata.
        # Observations not in the A3 pool get "unresolved" (lower-case).
        raw_verdict = a3_verdicts.get(oid, VERDICT_UNRESOLVED)
        # Normalise A3's "UNRESOLVED" to our canonical lower-case form.
        correction_verdict: str
        if raw_verdict == VERDICT_UNCORRECTED:
            correction_verdict = VERDICT_UNCORRECTED
        elif raw_verdict == VERDICT_CORRECTED:
            correction_verdict = VERDICT_CORRECTED
        else:
            correction_verdict = VERDICT_UNRESOLVED

        rows.append(
            {
                "id": oid,
                "start_iso": raw["start"],
                "start_unix": datetime.datetime.fromisoformat(
                    raw["start"].replace("Z", "+00:00")
                ).timestamp(),
                "ground_station": mo["ground_station"],
                "transmitter_uuid": mo["transmitter_uuid"],
                "norad_cat_id": mo["norad_cat_id"],
                "waterfall_status": mo["waterfall_status"],
                "waterfall_sha256": mo.get("waterfall_sha256"),
                "tle1": tle1,
                "tle2": tle2,
                "orbital_revolution": rev_idx,
                "correction_verdict": correction_verdict,
                "client_family": mo.get("client_family"),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# NORAD cluster detection
# ---------------------------------------------------------------------------

def _build_norad_clusters(
    norad_ids: set[int],
    gap: int = NORAD_CLUSTER_GAP,
) -> dict[int, int]:
    """Return {norad_id: cluster_representative} where cluster_representative
    is the minimum NORAD ID in the consecutive cluster.

    Two NORADs are in the same cluster if the gap between any two adjacent
    sorted IDs in the cluster is ≤ gap.  Each cluster is represented by its
    smallest member.
    """
    sorted_ids = sorted(norad_ids)
    clusters: dict[int, int] = {}
    cluster_rep = sorted_ids[0]
    prev = sorted_ids[0]
    for nid in sorted_ids:
        if nid - prev > gap:
            cluster_rep = nid
        clusters[nid] = cluster_rep
        prev = nid
    return clusters


# ---------------------------------------------------------------------------
# SHA256 duplicate enforcement
# ---------------------------------------------------------------------------

def _assign_sha256_to_partition(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> dict[int, str]:
    """Enforce no-duplicate-image-across-splits by promoting obs to the
    partition that already holds their SHA256.

    If two observations have the same waterfall_sha256, the earlier one
    (lower obs id) defines the partition; later ones are moved to match.
    Observations with no SHA256 (missing waterfall) are left unchanged.

    Returns a new partition_map (copy) with any reassignments applied.
    """
    sha_to_partition: dict[str, str] = {}
    result = dict(partition_map)

    # Process in observation-id order so the earliest obs wins.
    for row in sorted(rows, key=lambda r: r["id"]):
        sha = row["waterfall_sha256"]
        if not sha:
            continue
        oid = row["id"]
        if sha in sha_to_partition:
            existing_partition = sha_to_partition[sha]
            current_partition = result.get(oid)
            if current_partition != existing_partition:
                result[oid] = existing_partition  # reassign to match
        else:
            sha_to_partition[sha] = result[oid]

    return result


def _exclude_duplicate_images(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> dict[int, str]:
    """Drop later duplicate images to ``excluded`` instead of reassigning them.

    ``_assign_sha256_to_partition`` keeps duplicates together by *moving* the later
    observation to the earlier one's partition. For cold-combined that move is not
    safe: an observation whose station and transmitter tiers agree on "test" would
    be dragged into train because it happens to share a waterfall with a train
    observation, and the entity guarantee that the strict tier match establishes
    would break. Silently, and only on data that contains a duplicate.

    The stage-1 snapshot has 2,500 waterfalls with 2,500 distinct SHA-256 values,
    so this function is currently a no-op and the choice between the two rules
    cannot be observed in the artifact. That is exactly why it is written down: the
    invariant must not depend on the corpus happening to be duplicate-free.

    A duplicate image carries no new information, so excluding it costs nothing an
    intersection split can use. The leakage checks skip excluded observations, so
    the retained copy is still unique across the partitions that matter.
    """
    seen: dict[str, int] = {}
    result = dict(partition_map)
    for row in sorted(rows, key=lambda r: r["id"]):
        sha = row["waterfall_sha256"]
        if not sha:
            continue
        oid = row["id"]
        if result.get(oid) == "excluded":
            continue
        if sha in seen:
            result[oid] = "excluded"
        else:
            seen[sha] = oid
    return result


# ---------------------------------------------------------------------------
# Split builders
# ---------------------------------------------------------------------------

def _build_chronological_split(
    rows: list[dict[str, Any]],
    rng: random.Random,  # noqa: ARG001 – kept for API uniformity
) -> tuple[dict[int, str], dict]:
    """Assign each observation to train / calibration / test by start time,
    grouped by pass episode.

    Algorithm:
    1. Sort observations by start_unix.
    2. Cut at the 70% and 85% time-ordered positions.
    3. Assign each (station, satellite, revolution) episode to the partition its
       earliest observation fell in, so a single pass never straddles the boundary.

    **The grouping key is the episode, not the transmitter, and that is a change
    from the first version.** Grouping by transmitter here collapsed the split:
    measured 2,595 / 78 / 54 against the intended 70 / 15 / 15, leaving 18 decisive
    labels in test. The cause is the corpus, not the code. All 2,727 observations
    come from one evening, so 211 of 613 transmitters are observed on both sides of
    the 70% mark, and "assign each transmitter to the earliest partition it appears
    in" pulls nearly everything into train. A time cut and an entity grouping over
    the same axis are in direct conflict on a single-night corpus, and the entity
    grouping wins by construction.

    Episode grouping resolves it because a pass lasts about ten minutes, so an
    episode almost never straddles a cut: 2,716 episodes over 2,727 observations,
    and the measured split is 1,909 / 408 / 410 with 88 decisive labels in test.

    This split holds out *time*, on entities the model has seen. Holding out
    entities is what the other three splits are for, so a transmitter appearing on
    both sides here is the design rather than a leak, and
    ``no_transmitter_across_splits`` reports its measured crossing count for this
    split instead of claiming the guarantee.

    One caveat that no grouping can fix, carried from A6's audit: a single evening
    cannot demonstrate temporal generalisation however it is ordered. This split's
    value is as the common reference for comparing models on identical data, which
    is what kill gate 5 asks for. It is not evidence that the model survives a
    month.

    Returns (partition_map {obs_id → "train"|"calibration"|"test"},
             meta dict with cut time boundaries).
    """
    sorted_rows = sorted(rows, key=lambda r: r["start_unix"])
    n = len(sorted_rows)
    n_train = int(n * CHRON_TRAIN_FRACTION)
    n_cal = int(n * CHRON_CAL_FRACTION)

    raw_train_ids = {r["id"] for r in sorted_rows[:n_train]}
    raw_cal_ids = {r["id"] for r in sorted_rows[n_train: n_train + n_cal]}
    raw_test_ids = {r["id"] for r in sorted_rows[n_train + n_cal:]}

    # Map obs → raw partition
    raw_map: dict[int, str] = {}
    for oid in raw_train_ids:
        raw_map[oid] = "train"
    for oid in raw_cal_ids:
        raw_map[oid] = "calibration"
    for oid in raw_test_ids:
        raw_map[oid] = "test"

    # Episode-level guarantee: one satellite pass over one station is one sample, so
    # every observation of it lands where its earliest observation landed. Grouping by
    # transmitter here instead is what collapsed the split to 2595/78/54; see the
    # docstring.
    partition_order = {"train": 0, "calibration": 1, "test": 2}
    episode_partition: dict[tuple[int, int, int], str] = {}
    for row in sorted_rows:
        key = (row["ground_station"], row["norad_cat_id"], row["orbital_revolution"])
        p = raw_map[row["id"]]
        known = episode_partition.get(key)
        if known is None or partition_order[p] < partition_order[known]:
            episode_partition[key] = p

    final_map: dict[int, str] = {
        r["id"]: episode_partition[
            (r["ground_station"], r["norad_cat_id"], r["orbital_revolution"])
        ]
        for r in rows
    }

    meta = {
        "n_raw_train": len(raw_train_ids),
        "n_raw_cal": len(raw_cal_ids),
        "n_raw_test": len(raw_test_ids),
        "train_time_start": sorted_rows[0]["start_iso"],
        "train_time_end": sorted_rows[n_train - 1]["start_iso"],
        "cal_time_start": sorted_rows[n_train]["start_iso"],
        "cal_time_end": sorted_rows[n_train + n_cal - 1]["start_iso"],
        "test_time_start": sorted_rows[n_train + n_cal]["start_iso"],
        "test_time_end": sorted_rows[-1]["start_iso"],
    }
    return final_map, meta


def _build_cold_entity_split(
    rows: list[dict[str, Any]],
    rng: random.Random,
    entity_field: str,
    cluster_map: dict[Any, Any] | None = None,
    frac_test: float = COLD_TEST_FRACTION,
    frac_cal: float = COLD_CAL_FRACTION,
) -> dict[int, str]:
    """Assign obs by randomly holding out entities.

    entity_field: "ground_station" or "transmitter_uuid"
    cluster_map: if provided, maps entity_value → cluster_representative;
        all entities in the same cluster are held out together.
    frac_test / frac_cal: fraction of *entities* (not observations) held out.
        Defaults are the single-axis cold fractions; cold-combined passes its own,
        because its partitions go as the product of two fractions.

    frac_test of entities → test
    frac_cal of entities → calibration
    remainder → train

    Returns partition_map {obs_id → "train"|"calibration"|"test"}.
    """
    # Collect unique entities (or cluster representatives)
    entity_to_rep: dict[Any, Any] = {}
    for row in rows:
        val = row[entity_field]
        rep = cluster_map.get(val, val) if cluster_map is not None else val
        entity_to_rep[val] = rep

    unique_reps = sorted(set(entity_to_rep.values()), key=str)
    rng_copy = random.Random(rng.getrandbits(32))  # sub-seed so callers don't consume extra state
    shuffled = list(unique_reps)
    rng_copy.shuffle(shuffled)

    n_reps = len(shuffled)
    n_test_reps = max(1, int(n_reps * frac_test))
    n_cal_reps = max(1, int(n_reps * frac_cal))

    test_reps = set(shuffled[:n_test_reps])
    cal_reps = set(shuffled[n_test_reps: n_test_reps + n_cal_reps])

    rep_to_partition: dict[Any, str] = {}
    for rep in unique_reps:
        if rep in test_reps:
            rep_to_partition[rep] = "test"
        elif rep in cal_reps:
            rep_to_partition[rep] = "calibration"
        else:
            rep_to_partition[rep] = "train"

    return {
        row["id"]: rep_to_partition[entity_to_rep[row[entity_field]]]
        for row in rows
    }


def _build_cold_combined_split(
    rows: list[dict[str, Any]],
    station_partition: dict[int, str],
    tx_partition: dict[int, str],
) -> dict[int, str]:
    """Keep an observation only where its station tier and transmitter tier agree.

    ::

        partition = station tier          if station tier == transmitter tier
                    "excluded"           otherwise

    The tiers passed in must be drawn for this split (see
    ``COMBINED_TEST_FRACTION``), not borrowed from the single-axis cold splits.

    **Why the rule is a strict match, and why two weaker rules failed.**

    Version 1 sent every one-cold-one-warm observation to train, on the reasoning
    that train is the warmer partition. That silently broke both entity
    guarantees: a transmitter in the cold-transmitter test tier observed from a
    train station landed in train, while the same transmitter observed from a test
    station landed in test, so one transmitter sat in two partitions of this
    split. Same argument for stations. The conclusion drawn at the time was that
    ``no_transmitter_across_splits`` and ``no_station_across_splits`` are jointly
    unsatisfiable here. They are not.

    Version 2 excluded the mixed observations but defined calibration as "both
    axes cold, not both test". That still leaks, for a subtler reason: it puts
    (test-station, cal-transmitter) in calibration and (test-station,
    test-transmitter) in test, so a *test-tier station* appears in both. Measured
    on the stage-1 snapshot: 12 transmitters and 4 stations crossed partitions.
    Both entity checks still reported clean, because they were scoped out of this
    split on the version-1 reasoning. A stale exemption hid a live violation, and
    the manifest published ``true`` for both.

    The strict match is what actually holds: a test-tier station only ever appears
    in test or in excluded, never anywhere else, and likewise on both axes for all
    three tiers. Measured: 0 violators on all four leakage checks.

    An excluded observation belongs to no partition of this split. It is not a
    negative, not held out, and not evaluated here; it is unusable for a split that
    requires both axes to be cold together. The other three splits still use it.
    Most of the snapshot lands there (1,489 of 2,727 at seed 42), because most
    observations pair a cold station with a warm transmitter or the reverse. That is
    the arithmetic of an intersection, not a defect.
    """
    result: dict[int, str] = {}
    for row in rows:
        sp = station_partition[row["id"]]
        tp = tx_partition[row["id"]]
        result[row["id"]] = sp if sp == tp else "excluded"
    return result


# ---------------------------------------------------------------------------
# Composition reporting
# ---------------------------------------------------------------------------

def _split_composition(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> dict[str, Any]:
    """Return composition statistics for a single split type.

    Includes: counts per partition, corrected/uncorrected/unresolved breakdown,
    distinct stations, distinct satellites, distinct transmitters, distinct
    days, and distinct (station, day) episodes.
    """
    by_partition: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    id_to_row = {r["id"]: r for r in rows}
    for oid, part in partition_map.items():
        by_partition[part].append(id_to_row[oid])

    result: dict[str, Any] = {}
    for part, part_rows in sorted(by_partition.items()):
        corrections = collections.Counter(r["correction_verdict"] for r in part_rows)
        days = {r["start_iso"][:10] for r in part_rows}
        episodes = {(r["ground_station"], r["start_iso"][:10]) for r in part_rows}
        result[part] = {
            "n_observations": len(part_rows),
            "n_with_signal": sum(1 for r in part_rows if r["waterfall_status"] == "with-signal"),
            "n_without_signal": sum(
                1 for r in part_rows if r["waterfall_status"] == "without-signal"
            ),
            "n_unknown": sum(1 for r in part_rows if r["waterfall_status"] == "unknown"),
            "n_uncorrected": corrections[VERDICT_UNCORRECTED],
            "n_corrected": corrections[VERDICT_CORRECTED],
            "n_unresolved": corrections[VERDICT_UNRESOLVED],
            "physics_evaluable": corrections[VERDICT_UNCORRECTED] > 0,
            "distinct_stations": len({r["ground_station"] for r in part_rows}),
            "distinct_norad_ids": len({r["norad_cat_id"] for r in part_rows}),
            "distinct_transmitters": len({r["transmitter_uuid"] for r in part_rows}),
            "distinct_days": len(days),
            "distinct_station_day_episodes": len(episodes),
        }
    return result


# ---------------------------------------------------------------------------
# Leakage checks
# ---------------------------------------------------------------------------

#: Entity keys the four across-partition checks group by, and the noun used when
#: reporting a count. Adding a check means adding a row here, not a new function.
_ENTITY_KEYS: dict[str, tuple[str, Any]] = {
    "transmitter": ("transmitters", lambda r: r["transmitter_uuid"]),
    "station": ("stations", lambda r: r["ground_station"]),
    "episode": (
        "(station, norad, rev) episodes",
        lambda r: (r["ground_station"], r["norad_cat_id"], r["orbital_revolution"]),
    ),
    "image": ("waterfall SHA-256 values", lambda r: r["waterfall_sha256"] or None),
}


def entity_spread(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
    entity: str,
) -> dict[str, Any]:
    """Count how many entities of one kind straddle a partition boundary.

    Returns the numbers the manifest records, not a sentence:
    ``n_examined``, ``n_entities``, ``n_violators``, ``n_skipped_excluded``,
    ``n_skipped_no_key``, and up to five example violators.

    Two exclusions, both of which have to be reported rather than folded into a
    pass. An observation in the ``excluded`` partition belongs to no partition of
    its split, so it cannot cross one; counting it manufactures a violation that
    does not exist. An observation with no key (no waterfall, hence no SHA-256)
    cannot be compared at all. A check that examined nothing passes trivially, so
    ``n_examined`` travels with every verdict and the contract requires it to be
    positive.
    """
    noun, key_fn = _ENTITY_KEYS[entity]
    spread: dict[Any, set[str]] = collections.defaultdict(set)
    n_examined = 0
    n_skipped_excluded = 0
    n_skipped_no_key = 0

    for row in rows:
        part = partition_map.get(row["id"])
        if part is None or part == "excluded":
            n_skipped_excluded += 1
            continue
        key = key_fn(row)
        if key is None:
            n_skipped_no_key += 1
            continue
        n_examined += 1
        spread[key].add(part)

    violators = {k: sorted(v) for k, v in spread.items() if len(v) > 1}
    return {
        "entity": entity,
        "noun": noun,
        "n_examined": n_examined,
        "n_entities": len(spread),
        "n_violators": len(violators),
        "n_skipped_excluded": n_skipped_excluded,
        "n_skipped_no_key": n_skipped_no_key,
        "examples": [
            {"key": str(k), "partitions": v}
            for k, v in sorted(violators.items(), key=lambda kv: str(kv[0]))[:5]
        ],
        "detail": (
            f"Examined {n_examined} obs, {len(spread)} {noun}. "
            f"Violators: {len(violators)}."
            + (f" Skipped {n_skipped_excluded} excluded." if n_skipped_excluded else "")
            + (f" Skipped {n_skipped_no_key} with no key." if n_skipped_no_key else "")
        ),
    }


#: Every field on a raw SatNOGS observation record, classified by whether a feature
#: may be derived from it. The classification is exhaustive by construction:
#: ``check_field_classification`` fails the build if the snapshot carries a field
#: that is not listed here, because an unclassified field is a leak nobody has ruled
#: out yet. A later snapshot that adds a field therefore stops the freeze rather
#: than quietly admitting it.
#:
#: "identifier" means join key only. An observation id is monotonic with time, so a
#: model given the id as a number can read chronological order off it.
FIELD_CLASSIFICATION: dict[str, tuple[str, str]] = {
    # Identifiers: join and audit only, never features.
    "id": ("identifier", "Monotonic with time; as a feature it encodes chronological order."),
    "sat_id": ("identifier", "Satellite identity, used for grouping."),
    "transmitter_uuid": ("identifier", "Transmitter identity, used for grouping."),
    "ground_station": ("identifier", "Station identity, used for grouping."),
    # Known before or at capture: features may be derived from these.
    "start": ("observation_time", "Scheduled pass start, known at scheduling."),
    "end": ("observation_time", "Scheduled pass end, known at scheduling."),
    "norad_cat_id": ("observation_time", "Target catalogue number, known at scheduling."),
    "station_name": ("observation_time", "Station name, static."),
    "station_lat": ("observation_time", "Station latitude, static."),
    "station_lng": ("observation_time", "Station longitude, static."),
    "station_alt": ("observation_time", "Station altitude, static."),
    "observer": ("observation_time", "Station owner username, static."),
    "tle0": ("observation_time", "TLE name line used for the pass."),
    "tle1": ("observation_time", "TLE line 1 used for the pass; the propagation input."),
    "tle2": ("observation_time", "TLE line 2 used for the pass; the propagation input."),
    "tle_source": ("observation_time", "Which TLE set was used, known at scheduling."),
    "rise_azimuth": ("observation_time", "Predicted geometry, from the TLE at scheduling."),
    "set_azimuth": ("observation_time", "Predicted geometry, computed from the TLE at scheduling."),
    "max_altitude": ("observation_time", "Predicted peak elevation, computed at scheduling."),
    "observation_frequency": ("observation_time", "Commanded receive frequency."),
    "center_frequency": ("observation_time", "Receiver centre frequency. Null in this snapshot."),
    "client_version": ("observation_time", "Capture software version, written at capture."),
    "client_metadata": ("observation_time", "Radio parameters at capture; the true rx-freq."),
    "waterfall": ("observation_time", "URL of the image under test. The input, not a label."),
    "transmitter": ("observation_time", "Transmitter label from the SatNOGS DB."),
    "transmitter_mode": ("observation_time", "Modulation from the DB."),
    "transmitter_type": ("observation_time", "Transmitter type from the DB."),
    "transmitter_baud": ("observation_time", "Symbol rate from the DB."),
    "transmitter_description": ("observation_time", "Free-text description from the DB."),
    "transmitter_downlink_low": ("observation_time", "Downlink frequency from the DB."),
    "transmitter_downlink_high": ("observation_time", "Downlink frequency from the DB."),
    "transmitter_downlink_drift": ("observation_time", "Downlink drift correction from the DB."),
    "transmitter_uplink_low": ("observation_time", "Uplink frequency from the DB."),
    "transmitter_uplink_high": ("observation_time", "Uplink frequency from the DB."),
    "transmitter_uplink_drift": ("observation_time", "Uplink drift correction from the DB."),
    "transmitter_invert": ("observation_time", "Spectral inversion flag from the DB."),
    "transmitter_status": ("observation_time", "Active/inactive status from the DB."),
    "transmitter_unconfirmed": ("observation_time", "Whether the DB entry is unconfirmed."),
    # Produced after the capture: forbidden as features.
    "waterfall_status": ("post_observation", "The label itself: human vetting of the waterfall."),
    "waterfall_status_user": ("post_observation", "Who applied the label."),
    "waterfall_status_datetime": ("post_observation", "When the label was applied."),
    "vetted_status": ("post_observation", "Legacy vetting outcome; a second form of the label."),
    "vetted_user": ("post_observation", "Who vetted."),
    "vetted_datetime": ("post_observation", "When vetting happened."),
    "status": (
        "post_observation",
        "SatNOGS derives this from vetting (good/bad/failed/unknown). It is the label "
        "under another name, and it does not look like one.",
    ),
    "demoddata": (
        "post_observation",
        "Decoded frames from the post-capture pipeline. If frames decoded, the pass "
        "carried signal, so frame count is very close to a perfect label. The most "
        "dangerous field on the record and the one no earlier list mentioned.",
    ),
    "archived": ("post_observation", "Archival pipeline state, set well after capture."),
    "archive_url": ("post_observation", "Archival pipeline state, set well after capture."),
    "payload": (
        "post_observation",
        "URL of the raw recording. The audio itself is legitimate input, but whether "
        "the URL is populated is pipeline state that correlates with outcome.",
    ),
    "transmitter_updated": (
        "post_observation",
        "When the transmitter's DB entry last changed. It can postdate the pass, so it "
        "carries later knowledge about the transmitter, including corrections made "
        "because passes like this one failed.",
    ),
}


def check_field_classification(pages_dir: Path) -> dict[str, Any]:
    """Assert every field on the snapshot's records has a leakage classification.

    Returns the measured counts. ``passed`` is false when the snapshot carries a
    field absent from :data:`FIELD_CLASSIFICATION`, which stops the freeze: the new
    field might be a label in disguise, and nothing here can rule that out.

    This replaces an eight-item "excluded_fields" list that was written by hand and
    asserted true. The record actually carries 50 fields, of which 12 are unsafe.
    The list had missed ``status``, ``demoddata``, ``payload``, ``archived``,
    ``archive_url`` and ``transmitter_updated``.

    Raises ``RuntimeError`` when no records were loaded.  A classification over zero
    records is never a pass: it means the caller supplied the wrong directory or the
    snapshot is empty, and a silent pass would let a vacuous audit reach the artifact.
    """
    raw = _load_raw_pages(pages_dir)
    if not raw:
        raise RuntimeError(
            f"check_field_classification loaded 0 records from {pages_dir!r}. "
            "Supply the correct snapshot pages directory; an empty input is never "
            "a clean classification."
        )
    present = sorted({k for rec in raw.values() for k in rec})
    unclassified = [f for f in present if f not in FIELD_CLASSIFICATION]
    by_class: dict[str, list[str]] = collections.defaultdict(list)
    for field in present:
        if field in FIELD_CLASSIFICATION:
            by_class[FIELD_CLASSIFICATION[field][0]].append(field)

    return {
        "passed": not unclassified,
        "n_examined": len(present),
        "n_records": len(raw),
        "unclassified": unclassified,
        "counts": {k: len(v) for k, v in sorted(by_class.items())},
        "forbidden_fields": sorted(by_class.get("post_observation", [])),
        "forbidden_reasons": {
            f: FIELD_CLASSIFICATION[f][1] for f in sorted(by_class.get("post_observation", []))
        },
        "identifier_fields": sorted(by_class.get("identifier", [])),
        "rationale": (
            "The split manifest emits observation ids and no features, so this file "
            "cannot leak by itself. The classification binds whatever extracts "
            "features next: a feature may be derived only from an observation_time "
            "field. Identifier fields join and group; they are not model inputs."
        ),
    }


#: Which splits claim which entity guarantee, and why the others cannot.
#:
#: One table, read by both the manifest and the audit, so the artifact and its audit
#: cannot disagree about what was promised. They did: the audit said cold_combined
#: was out of scope for two checks while the manifest published a flat ``true`` for
#: both, which reads as "nothing crosses anywhere".
#:
#: A split that holds out stations lets one transmitter appear in several partitions,
#: because that transmitter is observed from stations on both sides of the boundary.
#: That is the design. But "expected here" was written as an exemption with no
#: number attached, and the exemption outlived the reason for it: after the
#: cold_combined builder changed, 12 transmitter and 4 station crossings sat behind a
#: sentence explaining why crossings were expected.
#:
#: So every check runs on every split. A split in ``applies_to`` must measure zero
#: crossings or the build refuses to freeze. A split in ``by_design`` reports its
#: measured crossing count as evidence, and a reader can weigh 213 against the
#: stated reason instead of taking the reason on trust.
CHECK_SCOPES: dict[str, dict[str, Any]] = {
    "no_transmitter_across_splits": {
        "entity": "transmitter",
        "applies_to": ["cold_transmitter", "cold_combined"],
        "by_design": {
            "cold_station": (
                "the held-out entity is the ground station, and one transmitter is "
                "observed from many stations that land on both sides of the boundary."
            ),
            "chronological": (
                "this split holds out time, on entities the model has seen, so a "
                "transmitter observed before and after the cut is the point rather "
                "than a leak. Grouping by transmitter here was tried and collapsed "
                "the split to 2595/78/54, because 211 of 613 transmitters are "
                "observed on both sides of a single evening's 70% mark."
            ),
        },
    },
    "no_station_across_splits": {
        "entity": "station",
        "applies_to": ["cold_station", "cold_combined"],
        "by_design": {
            "chronological": (
                "the cut is by time, on entities the model has seen, so a station "
                "keeps observing across the boundary."
            ),
            "cold_transmitter": (
                "the held-out entity is the transmitter, and one station observes many "
                "transmitters that land on both sides of the boundary."
            ),
        },
    },
    "no_revolution_across_splits": {
        "entity": "episode",
        "applies_to": ["chronological", "cold_station", "cold_transmitter", "cold_combined"],
        "by_design": {},
    },
    "no_duplicate_image_across_splits": {
        "entity": "image",
        "applies_to": ["chronological", "cold_station", "cold_transmitter", "cold_combined"],
        "by_design": {},
    },
}


#: The result a check carries when the build cannot measure its own claim. It is a
#: third outcome beside PASS and BY_DESIGN, and it is the only value that permits a
#: null n_examined: a check that examined nothing must not report a count of
#: something else. test_set_untouched is the only entry that uses it, in both the
#: manifest and the audit, so the two artifacts cannot disagree about what was
#: measured.
ASSERTED_NOT_MEASURABLE_HERE = "ASSERTED_NOT_MEASURABLE_HERE"


def reject_vacuous_checks(leakage_results: dict[str, dict[str, Any]]) -> None:
    """Raise if any check passed without examining anything.

    A check that examined zero records is worth exactly as much as not having the
    check, and it reports the same ``passed: true`` as one that examined 2,727. So an
    empty examination is a failure here, not a pass. The schema enforces the same
    floor on the artifact; this stops the build before the artifact exists.
    """
    vacuous: list[str] = []
    for name, entry in leakage_results.items():
        if entry.get("result") == ASSERTED_NOT_MEASURABLE_HERE:
            # An entry that declares itself unmeasurable here must carry null, not a
            # number. A number in that field is what let an emitted-id count read as
            # the examination behind the claim.
            if entry.get("n_examined") is not None:
                raise RuntimeError(
                    f"Leakage check {name} declares {ASSERTED_NOT_MEASURABLE_HERE} "
                    f"and still reports n_examined={entry.get('n_examined')!r}. A "
                    "check that examined nothing must not publish a count of "
                    "something else."
                )
            continue
        n = entry.get("n_examined")
        if n is None or n < 1:
            vacuous.append(name)
    if vacuous:
        msg = (
            f"Leakage checks examined zero records: {sorted(vacuous)}. A check with "
            "nothing to examine passes trivially and is not evidence. Do not freeze "
            "this manifest."
        )
        raise RuntimeError(msg)


def reject_vacuous_checks_in_audit(audit: list[dict[str, Any]]) -> None:
    """Raise if any PASS row in the audit list examined zero records.

    Counterpart to :func:`reject_vacuous_checks` for the ``list[dict]`` format
    that :func:`build_leakage_audit` produces.  A PASS over zero records is a
    silent pass: it carries no evidence, but it increments whatever tally a reader
    uses to judge completeness.  This is the gate that should have been applied to
    the audit list all along.
    """
    vacuous = [
        r["check"]
        for r in audit
        if r.get("result") == "PASS"
        and (r.get("n_examined") is None or r.get("n_examined") == 0)
    ]
    if vacuous:
        raise RuntimeError(
            f"Leakage audit contains vacuous PASS rows (n_examined is 0 or null): "
            f"{vacuous}. A check with zero examinations proves nothing, and a PASS "
            f"with no count does not say what it examined. Only "
            f"{ASSERTED_NOT_MEASURABLE_HERE} may carry a null."
        )


def _check(rows: list[dict[str, Any]], pm: dict[int, str], entity: str) -> tuple[bool, str]:
    stats = entity_spread(rows, pm, entity)
    return stats["n_violators"] == 0, stats["detail"]


def _check_no_transmitter_across_splits(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> tuple[bool, str]:
    """No transmitter_uuid appears in more than one partition."""
    return _check(rows, partition_map, "transmitter")


def _check_no_station_across_splits(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> tuple[bool, str]:
    """No ground_station appears in more than one partition (cold splits only)."""
    return _check(rows, partition_map, "station")


def _check_no_revolution_across_splits(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> tuple[bool, str]:
    """No (ground_station, norad_cat_id, orbital_revolution) episode appears in
    more than one partition.

    An episode is a single satellite pass over a single ground station.
    The constraint is that two observations of the *same pass at the same station*
    never straddle a split boundary.  Different ground stations observing the same
    orbital revolution are different episodes and may be in different partitions;
    that is the explicit design of the cold-station split.
    """
    return _check(rows, partition_map, "episode")


def _check_no_duplicate_image_across_splits(
    rows: list[dict[str, Any]],
    partition_map: dict[int, str],
) -> tuple[bool, str]:
    """No waterfall_sha256 appears in more than one partition."""
    return _check(rows, partition_map, "image")


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build_splits(
    seed: int = 42,
    manifest_path: Path | None = None,
    pages_dir: Path | None = None,
    a3_summary_path: Path | None = None,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    """Build all four split types and return the split manifest dict.

    The returned dict validates against contracts/split_manifest.schema.json.
    All paths are resolved from the repository root unless overridden.
    """
    manifest_path = manifest_path or _MANIFEST_PATH
    pages_dir = pages_dir or _PAGES_DIR
    a3_summary_path = a3_summary_path or _A3_SUMMARY_PATH

    rows = _build_obs_table(manifest_path, pages_dir, a3_summary_path)

    rng = random.Random(seed)

    # -----------------------------------------------------------------------
    # 1. Chronological split
    # -----------------------------------------------------------------------
    chron_map, chron_meta = _build_chronological_split(rows, rng)
    chron_map = _assign_sha256_to_partition(rows, chron_map)

    # -----------------------------------------------------------------------
    # 2. Cold-station split
    # -----------------------------------------------------------------------
    station_map = _build_cold_entity_split(rows, rng, "ground_station")
    station_map = _assign_sha256_to_partition(rows, station_map)

    # -----------------------------------------------------------------------
    # 3. Cold-transmitter split
    # NORAD cluster: consecutive NORAD IDs (gap ≤ 5) form one cluster.
    # All transmitters whose satellite is in the same cluster go together.
    # This prevents the Finding-2 bias: the rideshare 25052E/H/J (63214/17/18)
    # shares station bias and LO error, so separate calibrations of the same
    # systematic offset must not straddle a split boundary.
    # -----------------------------------------------------------------------
    all_norads = {r["norad_cat_id"] for r in rows}
    norad_clusters = _build_norad_clusters(all_norads)

    # Build transmitter → cluster-representative map via NORAD
    tx_to_cluster: dict[str, int] = {}
    for row in rows:
        tx = row["transmitter_uuid"]
        if tx not in tx_to_cluster:
            tx_to_cluster[tx] = norad_clusters[row["norad_cat_id"]]

    # For the cold-transmitter split we cluster by transmitter uuid but with
    # a "cluster override" that maps a transmitter to the cluster-representative
    # NORAD.  We pass a cluster_map over the transmitter field as tx→cluster_rep.
    transmitter_map = _build_cold_entity_split(
        rows, rng, "transmitter_uuid", cluster_map=tx_to_cluster
    )
    transmitter_map = _assign_sha256_to_partition(rows, transmitter_map)

    # -----------------------------------------------------------------------
    # 4. Cold-combined split
    #
    # Its tiers are drawn fresh, with COMBINED_* fractions, rather than reusing
    # station_map and transmitter_map. An intersection of two 20%/10% tiers leaves
    # 16 calibration observations; see the constant for the measured curve. The
    # draws happen last so the three splits above keep their assignments for a
    # given seed.
    # -----------------------------------------------------------------------
    combined_station_tiers = _build_cold_entity_split(
        rows,
        rng,
        "ground_station",
        frac_test=COMBINED_TEST_FRACTION,
        frac_cal=COMBINED_CAL_FRACTION,
    )
    combined_tx_tiers = _build_cold_entity_split(
        rows,
        rng,
        "transmitter_uuid",
        cluster_map=tx_to_cluster,
        frac_test=COMBINED_TEST_FRACTION,
        frac_cal=COMBINED_CAL_FRACTION,
    )
    combined_map = _build_cold_combined_split(
        rows, combined_station_tiers, combined_tx_tiers
    )
    combined_map = _exclude_duplicate_images(rows, combined_map)

    # -----------------------------------------------------------------------
    # Build partition id lists
    # -----------------------------------------------------------------------
    def _to_ids(pm: dict[int, str]) -> dict[str, list[int]]:
        # "excluded" exists only for cold_combined, where an observation with one
        # cold axis and one warm axis belongs to no partition. It is emitted only
        # when non-empty so the other three splits keep their original shape.
        buckets: dict[str, list[int]] = {
            "train": [], "calibration": [], "test": [], "excluded": [],
        }
        for oid, part in sorted(pm.items()):
            buckets[part].append(oid)
        out = {k: sorted(v) for k, v in buckets.items() if k != "excluded"}
        if buckets["excluded"]:
            out["excluded"] = sorted(buckets["excluded"])
        return out

    splits_obj = {
        "chronological": _to_ids(chron_map),
        "cold_station": _to_ids(station_map),
        "cold_transmitter": _to_ids(transmitter_map),
        "cold_combined": _to_ids(combined_map),
    }

    # -----------------------------------------------------------------------
    # Leakage checks (all must pass — const true in schema)
    # -----------------------------------------------------------------------
    leakage_results: dict[str, dict[str, Any]] = {}

    all_maps = {
        "chronological": chron_map,
        "cold_station": station_map,
        "cold_transmitter": transmitter_map,
        "cold_combined": combined_map,
    }

    for check_name, scope in CHECK_SCOPES.items():
        entity = scope["entity"]
        per_split: dict[str, dict[str, Any]] = {
            name: entity_spread(rows, pm, entity) for name, pm in all_maps.items()
        }
        guaranteed = scope["applies_to"]
        passed = all(per_split[name]["n_violators"] == 0 for name in guaranteed)
        leakage_results[check_name] = {
            "passed": passed,
            "applies_to": guaranteed,
            "n_examined": min(per_split[name]["n_examined"] for name in guaranteed),
            "measured": {
                name: {
                    "n_examined": s["n_examined"],
                    "n_entities": s["n_entities"],
                    "n_violators": s["n_violators"],
                    "n_skipped_excluded": s["n_skipped_excluded"],
                    "n_skipped_no_key": s["n_skipped_no_key"],
                    "guaranteed": name in guaranteed,
                    "examples": s["examples"],
                }
                for name, s in per_split.items()
            },
            "by_design_crossings": {
                name: {
                    "reason": reason,
                    "n_crossing": per_split[name]["n_violators"],
                    "n_examined": per_split[name]["n_examined"],
                }
                for name, reason in scope["by_design"].items()
            },
            "details": [f"{name}: {per_split[name]['detail']}" for name in sorted(per_split)],
        }

    # no_future_feature_in_train: every field on the record must be classified, and
    # an unclassified field fails the freeze rather than being assumed safe.
    field_check = check_field_classification(pages_dir)
    leakage_results["no_future_feature_in_train"] = {
        "passed": field_check["passed"],
        "applies_to": ["chronological", "cold_station", "cold_transmitter", "cold_combined"],
        **{k: v for k, v in field_check.items() if k != "passed"},
    }

    # test_set_untouched. At freeze time this is a statement about process, and a
    # process claim cannot be measured from inside the process. What can be recorded
    # is a digest of each frozen test set, so a later evaluation has to name which
    # frozen set it touched and a silently re-drawn test set stops matching.
    test_digests = {
        name: hashlib.sha256(
            json.dumps(sorted(ids["test"]), separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for name, ids in splits_obj.items()
    }
    leakage_results["test_set_untouched"] = {
        "result": ASSERTED_NOT_MEASURABLE_HERE,
        "applies_to": ["chronological", "cold_station", "cold_transmitter", "cold_combined"],
        # Null by design, and no "passed" key. The count that used to sit here was
        # sum(len(ids["test"])), the number of emitted test ids, which measures a
        # different property under the name of this check. Anyone tallying six of
        # six passes counted this row, and neither the pass nor the number was
        # evidence for the claim above them.
        "n_examined": None,
        "test_id_digests": test_digests,
        "rationale": (
            "Test ids are emitted and never loaded, scored, or inspected during the "
            "build. Unlike the other five this one cannot be proved from here, so it "
            "is not asserted alone: each digest above pins one frozen test set, and "
            "any evaluation that reports a number must quote the digest it scored. A "
            "test set redrawn between freeze and evaluation changes its digest, which "
            "is the failure this records rather than claims away. n_examined is null "
            "because nothing was examined to produce this entry, and a count here "
            "would be a measurement of something else."
        ),
    }

    # Fail fast: if any leakage check failed, surface it clearly
    failed_checks = []
    for _name, _entry in leakage_results.items():
        if _entry.get("result") == ASSERTED_NOT_MEASURABLE_HERE:
            continue  # bound by its digests, not by a pass this build could measure
        if "passed" not in _entry:
            raise RuntimeError(
                f"Leakage check {_name} records neither passed nor "
                f"{ASSERTED_NOT_MEASURABLE_HERE}. An entry that states no outcome "
                "cannot be read as a pass."
            )
        if not _entry["passed"]:
            failed_checks.append(_name)
    if failed_checks:
        msg = f"Leakage checks failed: {failed_checks}. Do not freeze this manifest."
        raise RuntimeError(msg)

    reject_vacuous_checks(leakage_results)

    # -----------------------------------------------------------------------
    # Per-split composition
    # -----------------------------------------------------------------------
    composition = {
        "chronological": _split_composition(rows, chron_map),
        "cold_station": _split_composition(rows, station_map),
        "cold_transmitter": _split_composition(rows, transmitter_map),
        "cold_combined": _split_composition(rows, combined_map),
    }

    # Physics arm evaluability report
    physics_report: list[dict[str, Any]] = []
    for split_name, comp in composition.items():
        for part_name, stats in comp.items():
            physics_report.append(
                {
                    "split": split_name,
                    "partition": part_name,
                    "n_uncorrected": stats["n_uncorrected"],
                    "physics_evaluable": stats["physics_evaluable"],
                    "warning": (
                        "ZERO uncorrected observations: physics arm cannot be "
                        "evaluated on this partition"
                        if not stats["physics_evaluable"]
                        else None
                    ),
                }
            )

    # -----------------------------------------------------------------------
    # Load snapshot_id from manifest
    # -----------------------------------------------------------------------
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_id = manifest_data["snapshot_id"]

    # -----------------------------------------------------------------------
    # Assemble the split manifest
    # -----------------------------------------------------------------------
    split_manifest: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        # frozen_at is pinned when the caller supplies it, because rebuilding this
        # file to correct a reporting field must not re-date the freeze: a reader
        # cannot otherwise tell a corrected artifact from a re-drawn split.
        # rebuilt_at is when the file was last written, which is a different fact,
        # and the test id digests are what prove the partitions did not move.
        "frozen_at": frozen_at or datetime.datetime.now(datetime.UTC).isoformat(),
        "rebuilt_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "build_seed": seed,
        "n_observations": len(rows),
        "sampling_design": (
            "Stage-1 snapshot: 2,727 observations collected chronologically "
            "backwards from 2026-08-10T00:00:00Z, all from a single UTC day "
            "(2026-08-09). "
            "Chronological split: 70/15/15 by time-ordered observation count, grouped "
            "by (station, satellite, revolution) pass episode so no single pass "
            "straddles a cut. It holds out time on entities the model has seen, so "
            "transmitters and stations appear on both sides by design. Grouping it by "
            "transmitter instead was tried and collapsed it to 2,595/78/54, leaving 18 "
            "decisive test labels, because 211 of 613 transmitters are observed on "
            "both sides of a single evening's 70% mark. "
            "Cold-station: 20% of ground stations (by random draw, seed-controlled) "
            "held out for test, 10% for calibration. "
            "Cold-transmitter: 20% of transmitters held out, 10% for calibration; "
            "NORAD rideshare clusters (consecutive NORAD IDs, gap≤5) held out "
            "together to prevent cross-split LO-error bias (Finding 2). "
            "Cold-combined: its own station and transmitter tiers, 25% test and 20% "
            "calibration on each axis, drawn separately from the two splits above. An "
            "observation is kept only where its station tier and its transmitter tier "
            "agree, and is excluded otherwise, so a station or transmitter in the test "
            "tier appears in the test partition or nowhere. 1,489 of 2,727 "
            "observations are excluded, which is the arithmetic of an intersection: "
            "most passes pair a cold station with a warm transmitter or the reverse. "
            "Its training partition is 945 observations against 2,595 for the "
            "chronological split, so a drop measured here confounds unseen entities "
            "with less training data and needs the size-matched control in B6 to "
            "separate them. Its calibration partition carries 49 decisive labels, "
            "which admits temperature scaling and rules out isotonic regression. "
            "Known biases: single-day corpus limits temporal generalisation; "
            "the A3 doppler-correction verdict pool covers only 24 observations "
            "(3 UNCORRECTED, 4 CORRECTED, 17 UNRESOLVED), so the physics-arm "
            "evaluability depends almost entirely on NORAD cluster 63214/63217/63218 "
            "which lands in whichever partition receives ground stations 91 and 1696."
        ),
        "grouping_keys": [
            "ground_station", "transmitter_uuid", "norad_cat_id", "orbital_revolution",
        ],
        "norad_cluster_gap_threshold": NORAD_CLUSTER_GAP,
        "splits": splits_obj,
        # The measured results, not six literal ``True``s. The previous version wrote
        # the booleans by hand next to a scoped audit that said something weaker, so
        # the artifact claimed more than the code had checked.
        "leakage_checks": leakage_results,
        "composition": composition,
        "physics_arm_report": physics_report,
        "chronological_meta": chron_meta,
    }

    return split_manifest


def build_leakage_audit(
    rows: list[dict[str, Any]],
    chron_map: dict[int, str],
    station_map: dict[int, str],
    transmitter_map: dict[int, str],
    combined_map: dict[int, str],
    *,
    pages_dir: Path = _PAGES_DIR,
) -> list[dict[str, Any]]:
    """Build the leakage audit: every check measured on every split.

    Three outcomes, and the third one is the point:

    ``PASS``
        The split claims the guarantee and measured zero crossings.
    ``FAIL``
        The split claims the guarantee and something crossed. The build refuses to
        freeze.
    ``BY_DESIGN``
        The split does not claim the guarantee, and the row carries the *measured*
        crossing count anyway. A reader can see that 213 transmitters cross
        cold_station and judge the stated reason against a number.

    The earlier version wrote ``SCOPE_NOTE`` with a reason and no measurement, and
    reported ``n_examined`` as 2,727 on every row regardless of what each check
    actually looked at. Both are how an exemption outlives its reason: the
    cold_combined notes stayed after the builder changed, so 12 transmitter and 4
    station crossings sat behind a sentence explaining why crossings were expected.
    """
    all_maps = {
        "chronological": chron_map,
        "cold_station": station_map,
        "cold_transmitter": transmitter_map,
        "cold_combined": combined_map,
    }
    audit: list[dict[str, Any]] = []

    for check_name, scope in CHECK_SCOPES.items():
        for split_name, pm in all_maps.items():
            stats = entity_spread(rows, pm, scope["entity"])
            guaranteed = split_name in scope["applies_to"]
            if guaranteed:
                result = "PASS" if stats["n_violators"] == 0 else "FAIL"
                detail = stats["detail"]
            else:
                result = "BY_DESIGN"
                detail = (
                    f"{stats['n_violators']} of {stats['n_entities']} {stats['noun']} "
                    f"cross a partition boundary here, over {stats['n_examined']} "
                    f"observations. Not a leak: {scope['by_design'][split_name]}"
                )
            audit.append(
                {
                    "check": check_name,
                    "split": split_name,
                    "entity": scope["entity"],
                    "guaranteed": guaranteed,
                    "n_examined": stats["n_examined"],
                    "n_entities": stats["n_entities"],
                    "n_violators": stats["n_violators"],
                    "n_skipped_excluded": stats["n_skipped_excluded"],
                    "n_skipped_no_key": stats["n_skipped_no_key"],
                    "result": result,
                    "detail": detail,
                    "examples": stats["examples"],
                }
            )

    # check_field_classification raises RuntimeError when pages_dir loads no records,
    # so a missing snapshot path produces a loud failure rather than a silent pass.
    field_check = check_field_classification(pages_dir)
    audit.append(
        {
            "check": "no_future_feature_in_train",
            "split": "all",
            "entity": "record_field",
            "guaranteed": True,
            "n_examined": field_check["n_examined"],
            "n_entities": field_check["n_examined"],
            "n_violators": len(field_check["unclassified"]),
            "n_skipped_excluded": 0,
            "n_skipped_no_key": 0,
            "result": "PASS" if field_check["passed"] else "FAIL",
            "detail": (
                f"Classified all {field_check['n_examined']} fields on the raw record: "
                f"{field_check['counts']}. "
                f"Forbidden as features: {', '.join(field_check['forbidden_fields'])}. "
                "The manifest emits ids only, so it cannot leak by itself; this binds "
                "feature extraction. An unclassified field fails the freeze."
            ),
            "examples": [{"key": f, "partitions": []} for f in field_check["unclassified"][:5]],
        }
    )
    audit.append(
        {
            "check": "test_set_untouched",
            "split": "all",
            "entity": "process",
            "guaranteed": True,
            # n_examined is null here by design: test ids are emitted, not loaded or
            # inspected, so this build cannot measure test-set integrity from inside
            # itself. The digests below are the mechanism that actually binds it.
            # Reporting the emitted test-id count (as the earlier version did) said
            # nothing about whether the test set was touched; it measured a different
            # property under the name of this check.
            "n_examined": None,
            "n_entities": len(all_maps),
            "n_violators": None,
            "n_skipped_excluded": 0,
            "n_skipped_no_key": 0,
            "result": ASSERTED_NOT_MEASURABLE_HERE,
            "detail": (
                "Test ids are emitted, not loaded, scored, or inspected at build time. "
                "This is the one check that cannot be proved from inside the build, so "
                "the manifest records a digest per frozen test set and any reported "
                "number must quote the digest it scored."
            ),
            "examples": [],
        }
    )

    # Vacuity gate. This calls the shared function rather than repeating its
    # predicate: an inline copy meant the build ran one gate while the tests
    # exercised another, and the two could drift with no failure anywhere.
    reject_vacuous_checks_in_audit(audit)

    return audit


def _extract_partition_maps(
    rows: list[dict[str, Any]],
    split_manifest: dict[str, Any],
) -> dict[str, dict[int, str]]:
    """Reconstruct per-split partition maps from a built manifest (for audit).

    ``excluded`` has to be reconstructed too, even though nothing evaluates it.
    The entity checks look every observation up by id, so an id present in the
    table and absent from the map raises rather than being skipped, and cold
    combined puts 680 observations there.
    """
    result: dict[str, dict[int, str]] = {}
    for split_name, split_data in split_manifest["splits"].items():
        pm: dict[int, str] = {}
        for part in ("train", "calibration", "test", "excluded"):
            for oid in split_data.get(part, []):
                pm[oid] = part
        result[split_name] = pm
    return result
