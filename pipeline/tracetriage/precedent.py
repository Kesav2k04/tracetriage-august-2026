"""Precedent retrieval: the passes most like this one, and what the network decided about them.

A reviewer opening an observation has one question the queue cannot answer: has anything like
this been seen before, and what happened then. That is a retrieval problem, and it is the one
place in this project where a vector index earns its keep. It is also the easiest place in the
project to fool yourself, for two reasons.

The first is that the label is carried by entity identity. Some ground stations are misconfigured
for weeks and every pass they record is empty; some satellites are dead. A retriever that finds
neighbours from the same station recovers the label at a rate that looks like understanding and
is really a lookup of who recorded it. So every measurement here is reported under two
conditions: **warm**, where any other observation may be retrieved, and **cold**, where a
candidate must come from a different ground station *and* a different satellite. The cold number
is the one that says whether similarity carries the label across entities, which is the case a
reviewer meets when a new station appears.

The second is that the snapshot's own fields leak the answer. ``status`` is the network's overall
verdict on the observation, ``demoddata`` is a list of decoded frames, and either one settles
whether a signal was present without looking at the waterfall. :data:`FORBIDDEN_FIELDS` names
them and :func:`render_card` is tested to contain none of them, because a retrieval study built
on a leaked label is not a weak study, it is a different study with a flattering answer.

Four arms, so the embedding has something to beat:

* ``granite_text`` embeds the rendered card with a local IBM Granite embedding model
* ``numeric_knn`` uses the same information as standardised numbers with Euclidean distance
* ``same_station`` returns the station's own most recent passes, which is what a human does
* ``random`` draws uniformly from the same candidate pool, which fixes the chance level

``same_station`` is undefined under the cold condition by construction, and it is reported as
null with that reason rather than as a zero.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

#: Fields that answer the question the study asks. None of them may reach the rendered card or
#: the numeric features, and a test walks the rendered text for every one.
FORBIDDEN_FIELDS = (
    "status",
    "waterfall_status",
    "demoddata",
    "archive_url",
    "archived",
    "payload",
    "vetted_status",
    "vetted_user",
)

#: The label values the study can measure agreement over. "unknown" is excluded from queries and
#: from candidates, because agreeing with an absent label is not a measurement.
DECISIVE_LABELS = ("with-signal", "without-signal")

ARMS = ("granite_text", "numeric_knn", "same_station", "random")
CONDITIONS = ("warm", "cold")

#: Fixed before the first retrieval. Five is what a reviewer can read at a glance, and the
#: metric is the mean over the five rather than a hit at one, so a single lucky neighbour cannot
#: carry an arm.
TOP_K = 5


@dataclass(frozen=True)
class Observation:
    """One pass, reduced to what a retriever is allowed to see."""

    obs_id: int
    label: str
    station: int | None
    satellite: int | None
    start: str | None
    card: str
    features: tuple[float, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "obs_id": self.obs_id,
            "label": self.label,
            "station": self.station,
            "satellite": self.satellite,
            "start": self.start,
        }


def _hours(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        a = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = _dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (b - a).total_seconds() / 3600.0


def _local_hour(start: str | None, longitude: float | None) -> float | None:
    """Local solar hour, because a pass at local noon and one at local midnight differ.

    A UTC hour would be a property of where the station is rather than of when the pass was,
    which is the kind of feature that looks predictive and is really a station id in disguise.
    """
    if not start:
        return None
    try:
        stamp = _dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        return None
    offset = 0.0 if longitude is None else float(longitude) / 15.0
    return (stamp.hour + stamp.minute / 60.0 + offset) % 24.0


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def render_card(row: dict[str, Any]) -> str:
    """The text a retriever may embed: what and where and when, never what happened.

    Entity names stay in on purpose. The cold condition removes same-entity candidates by
    filtering, so the honest comparison is between a retriever that may use identity when
    identity is available and the same retriever when it is not. Stripping the names instead
    would answer a question nobody asked.
    """
    frequency = _number(row.get("center_frequency")) or _number(
        row.get("observation_frequency")
    )
    elevation = _number(row.get("max_altitude"))
    duration = _hours(row.get("start"), row.get("end"))
    latitude = _number(row.get("station_lat"))
    longitude = _number(row.get("station_lng"))
    hour = _local_hour(row.get("start"), longitude)
    lines = [
        f"Ground station {row.get('station_name') or 'unnamed'}"
        f" (id {row.get('ground_station')}) at latitude"
        f" {'unknown' if latitude is None else f'{latitude:.1f}'} and longitude"
        f" {'unknown' if longitude is None else f'{longitude:.1f}'}.",
        f"Satellite catalogue number {row.get('norad_cat_id')}, transmitter"
        f" {row.get('sat_id') or 'unknown'}.",
        f"Receiver frequency"
        f" {'unknown' if frequency is None else f'{frequency / 1e6:.3f} MHz'}.",
        f"Maximum elevation"
        f" {'unknown' if elevation is None else f'{elevation:.1f} degrees'}.",
        f"Pass length {'unknown' if duration is None else f'{duration * 60:.0f} minutes'}.",
        f"Local hour at the station"
        f" {'unknown' if hour is None else f'{hour:.1f}'}.",
    ]
    return " ".join(lines)


#: The numeric arm's feature order, published so the receipt can name it.
FEATURE_NAMES = (
    "frequency_mhz",
    "max_elevation_deg",
    "pass_minutes",
    "station_latitude",
    "station_longitude",
    "local_hour_sin",
    "local_hour_cos",
)


def features_of(row: dict[str, Any]) -> tuple[float, ...]:
    """The same information the card carries, as numbers, with the hour on a circle.

    A raw local hour puts 23.9 and 0.1 at opposite ends of the axis, which is a boundary the
    physics does not have, so the hour enters as a sine and cosine pair.
    """
    frequency = _number(row.get("center_frequency")) or _number(
        row.get("observation_frequency")
    )
    longitude = _number(row.get("station_lng"))
    hour = _local_hour(row.get("start"), longitude)
    angle = 0.0 if hour is None else 2 * math.pi * hour / 24.0
    duration = _hours(row.get("start"), row.get("end"))
    return (
        0.0 if frequency is None else frequency / 1e6,
        _number(row.get("max_altitude")) or 0.0,
        0.0 if duration is None else duration * 60.0,
        _number(row.get("station_lat")) or 0.0,
        0.0 if longitude is None else longitude,
        0.0 if hour is None else math.sin(angle),
        0.0 if hour is None else math.cos(angle),
    )


def observations_from(rows: Iterable[dict[str, Any]]) -> list[Observation]:
    """Every decisively labelled pass in the snapshot, reduced and ordered by id."""
    out: list[Observation] = []
    for row in rows:
        label = row.get("waterfall_status")
        if label not in DECISIVE_LABELS:
            continue
        out.append(
            Observation(
                obs_id=int(row["id"]),
                label=str(label),
                station=(
                    None if row.get("ground_station") is None else int(row["ground_station"])
                ),
                satellite=(
                    None if row.get("norad_cat_id") is None else int(row["norad_cat_id"])
                ),
                start=row.get("start"),
                card=render_card(row),
                features=features_of(row),
            )
        )
    out.sort(key=lambda obs: obs.obs_id)
    return out


def standardise(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    """Zero mean and unit variance per column, computed over the pool that is searched.

    A column of zeros stays zeros rather than becoming NaN, which is what dividing by a zero
    standard deviation would do, and a NaN in one column silently removes every other column
    from the distance.
    """
    if not vectors:
        return []
    width = len(vectors[0])
    means = [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]
    variances = [
        sum((v[i] - means[i]) ** 2 for v in vectors) / max(1, len(vectors) - 1)
        for i in range(width)
    ]
    scales = [math.sqrt(var) if var > 0 else 1.0 for var in variances]
    return [[(v[i] - means[i]) / scales[i] for i in range(width)] for v in vectors]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def is_candidate(query: Observation, other: Observation, condition: str) -> bool:
    """Who may be retrieved for whom, which is the whole design of the cold condition."""
    if other.obs_id == query.obs_id:
        return False
    if condition == "warm":
        return True
    if condition != "cold":
        raise ValueError(f"unknown condition {condition!r}")
    if query.station is not None and other.station == query.station:
        return False
    return not (query.satellite is not None and other.satellite == query.satellite)


def top_k_exact(
    query: Observation,
    pool: Sequence[Observation],
    vectors: dict[int, Sequence[float]],
    condition: str,
    *,
    metric: str = "cosine",
    k: int = TOP_K,
) -> list[int]:
    """Exact search, which is also the reference the vector index is checked against."""
    scored: list[tuple[float, int]] = []
    query_vector = vectors[query.obs_id]
    for other in pool:
        if not is_candidate(query, other, condition):
            continue
        vector = vectors[other.obs_id]
        if metric == "cosine":
            score = -cosine(query_vector, vector)
        elif metric == "euclidean":
            score = euclidean(query_vector, vector)
        else:
            raise ValueError(f"unknown metric {metric!r}")
        scored.append((score, other.obs_id))
    scored.sort(key=lambda pair: (pair[0], pair[1]))
    return [obs_id for _, obs_id in scored[:k]]


def top_k_same_station(
    query: Observation,
    pool: Sequence[Observation],
    condition: str,
    *,
    k: int = TOP_K,
) -> list[int] | None:
    """The station's own most recent other passes, or None when the condition forbids them.

    None rather than an empty list, and never a zero score: under the cold condition this arm
    has no definition at all, and reporting it as a failure would invent a comparison.
    """
    if condition == "cold":
        return None
    same = [
        other
        for other in pool
        if is_candidate(query, other, condition)
        and other.station is not None
        and other.station == query.station
    ]
    same.sort(key=lambda obs: (obs.start or "", obs.obs_id), reverse=True)
    return [obs.obs_id for obs in same[:k]]


def top_k_random(
    query: Observation,
    pool: Sequence[Observation],
    condition: str,
    rng: random.Random,
    *,
    k: int = TOP_K,
) -> list[int]:
    """The chance level, drawn from exactly the pool the other arms searched."""
    candidates = [other.obs_id for other in pool if is_candidate(query, other, condition)]
    if len(candidates) <= k:
        return candidates
    return rng.sample(candidates, k)


def agreement(query_label: str, retrieved: Sequence[int], labels: dict[int, str]) -> float | None:
    """The share of the retrieved neighbours carrying the query's own label.

    None when nothing was retrieved, because a mean over an empty set is not zero agreement.
    """
    if not retrieved:
        return None
    return sum(1 for obs_id in retrieved if labels[obs_id] == query_label) / len(retrieved)


def chance_level(labels: Sequence[str]) -> float:
    """The agreement a uniform draw is expected to reach, from the label mix alone.

    Published beside the random arm so the two can be compared: the random arm is a measurement
    with sampling error and this is its expectation, and a large gap between them means the
    candidate pools are not what the arm thought they were.
    """
    total = len(labels)
    if not total:
        return 0.0
    return sum((labels.count(name) / total) ** 2 for name in DECISIVE_LABELS)


def digest_of(texts: Iterable[str]) -> str:
    """One digest over the rendered cards, so a rebuild can be compared without the vectors."""
    sha = hashlib.sha256()
    for text in texts:
        sha.update(text.encode("utf-8"))
        sha.update(b"\x00")
    return sha.hexdigest()


def digest_of_vectors(vectors: Iterable[Sequence[float]]) -> str:
    """A digest over the embedding matrix, rounded, so it survives a float round trip.

    Six decimal places: enough that a different model or a different prompt changes the digest,
    coarse enough that writing the vectors to JSON and reading them back does not.
    """
    sha = hashlib.sha256()
    for vector in vectors:
        sha.update(json.dumps([round(float(x), 6) for x in vector]).encode("utf-8"))
    return sha.hexdigest()
