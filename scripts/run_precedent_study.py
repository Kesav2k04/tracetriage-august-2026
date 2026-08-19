"""Retrieve precedent for every labelled pass, four ways, and measure whether it carries a label.

    .venv/Scripts/python.exe scripts/run_precedent_study.py --freeze   # embeds and retrieves
    .venv/Scripts/python.exe scripts/run_precedent_study.py            # republishes from the
                                                                       # frozen retrievals

The question is whether a vector index over what is knowable *before* opening a waterfall finds
neighbours whose recorded outcome matches the query's. Four arms answer it, so the embedding has
something to beat: an IBM Granite embedding of a rendered card, the same information as
standardised numbers under Euclidean distance, the station's own most recent passes, which is
what a human does, and a uniform draw from the same candidate pool, which fixes the chance level.

Two conditions, and the difference between them is the whole point. **Warm** lets any other
observation be retrieved. **Cold** requires a different ground station *and* a different
satellite, because the label in this corpus is partly a property of who recorded it: a
misconfigured station produces empty waterfalls for weeks. An arm that scores well warm and at
chance cold has learned who, not what, and that is worth knowing rather than hiding.

The vector index is a real one. `chromadb` holds the Granite vectors with station and satellite
metadata and answers the cold condition with a filtered query; the exact cosine search runs
beside it and the receipt publishes the recall of the index against exact search, because an
approximate index that quietly returns different neighbours would change the measurement without
changing the code.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.fusion import (  # noqa: E402
    grouped_bootstrap_statistic_difference,
)
from pipeline.tracetriage.precedent import (  # noqa: E402
    ARMS,
    CONDITIONS,
    DECISIVE_LABELS,
    FEATURE_NAMES,
    FORBIDDEN_FIELDS,
    TOP_K,
    Observation,
    agreement,
    chance_level,
    digest_of,
    digest_of_vectors,
    observations_from,
    standardise,
    top_k_exact,
    top_k_random,
    top_k_same_station,
)

FIXTURE = REPO / "tests" / "fixtures" / "precedent_retrievals.json"
RECEIPT = REPO / "artifacts" / "PRECEDENT_RECEIPT.json"
CONSOLE_IDS = REPO / "apps" / "web" / "public" / "data" / "cards.json"

#: Comparisons this study makes against the random arm and between the two model arms, counted
#: so the bootstrap can widen for them. Three arms against random in the warm condition, two in
#: the cold one, and Granite against the numeric baseline in both.
N_COMPARISONS = 7

SEED = 11


def _load_snapshot(snapshot: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in sorted((snapshot / "pages").glob("*.json")):
        rows.extend(json.loads(page.read_text(encoding="utf-8")))
    return rows


def _mean(values: list[float]) -> float:
    return float(np.mean(values)) if values else float("nan")


def freeze(snapshot: Path, fixture: Path) -> dict[str, Any]:
    """Embed, index, retrieve, and write down everything a scorer needs and nothing more."""
    from pipeline.tracetriage.granite import EMBED_MODEL, embed, model_identity

    rows = _load_snapshot(snapshot)
    pool = observations_from(rows)
    if len(pool) < 50:
        raise SystemExit(
            f"only {len(pool)} decisively labelled observations in {snapshot}; the study needs "
            f"the stage-1 snapshot"
        )

    leaked = [
        field
        for field in FORBIDDEN_FIELDS
        for obs in pool
        if field in obs.card
    ]
    if leaked:
        raise SystemExit(
            f"the rendered cards mention {sorted(set(leaked))}, which answer the question this "
            f"study asks. Nothing is embedded until the card is clean."
        )

    print(f"embedding {len(pool)} cards with {EMBED_MODEL}")
    vectors: dict[int, list[float]] = {}
    for index, obs in enumerate(pool, start=1):
        vectors[obs.obs_id] = embed(obs.card, model=EMBED_MODEL)
        if index % 100 == 0:
            print(f"  {index}/{len(pool)}")

    numeric = dict(
        zip(
            [obs.obs_id for obs in pool],
            standardise([obs.features for obs in pool]),
            strict=True,
        )
    )

    rng = random.Random(SEED)
    retrievals: dict[str, dict[str, dict[str, list[int] | None]]] = {
        condition: {arm: {} for arm in ARMS} for condition in CONDITIONS
    }
    for condition in CONDITIONS:
        for obs in pool:
            retrievals[condition]["granite_text"][str(obs.obs_id)] = top_k_exact(
                obs, pool, vectors, condition, metric="cosine"
            )
            retrievals[condition]["numeric_knn"][str(obs.obs_id)] = top_k_exact(
                obs, pool, numeric, condition, metric="euclidean"
            )
            retrievals[condition]["same_station"][str(obs.obs_id)] = top_k_same_station(
                obs, pool, condition
            )
            retrievals[condition]["random"][str(obs.obs_id)] = top_k_random(
                obs, pool, condition, rng
            )
        print(f"  retrieved {condition}")

    index_check = _check_the_vector_index(pool, vectors, retrievals)

    # The console ships 25 observations. Their precedent lists are frozen here so the page can
    # show them without an index, a model or a snapshot.
    console_ids = [
        int(card["obs_id"])
        for card in json.loads(CONSOLE_IDS.read_text(encoding="utf-8"))["cards"]
    ]
    by_id = {obs.obs_id: obs for obs in pool}
    console = {
        str(obs_id): {
            condition: [
                {
                    "obs_id": neighbour,
                    "label": by_id[neighbour].label,
                    "station": by_id[neighbour].station,
                    "satellite": by_id[neighbour].satellite,
                    "start": by_id[neighbour].start,
                }
                for neighbour in (
                    retrievals[condition]["granite_text"].get(str(obs_id)) or []
                )
            ]
            for condition in CONDITIONS
        }
        for obs_id in console_ids
        if obs_id in by_id
    }

    payload = {
        "schema": "PRECEDENT_RETRIEVALS",
        "schema_version": 1,
        "snapshot": snapshot.name,
        "embedding_model": model_identity(model=EMBED_MODEL).as_dict(),
        "top_k": TOP_K,
        "seed": SEED,
        "feature_names": list(FEATURE_NAMES),
        "cards_sha256": digest_of(obs.card for obs in pool),
        "vectors_sha256": digest_of_vectors(vectors[obs.obs_id] for obs in pool),
        "observations": [obs.as_json() for obs in pool],
        "retrievals": retrievals,
        "vector_index": index_check,
        "console_precedent": console,
    }
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"froze {len(pool)} observations into {fixture}")
    return payload


def _check_the_vector_index(
    pool: list[Observation],
    vectors: dict[int, list[float]],
    retrievals: dict[str, dict[str, dict[str, list[int] | None]]],
) -> dict[str, Any]:
    """Ask a real vector database the same questions and report where it disagrees.

    An approximate index is allowed to disagree with exact search. What is not allowed is for
    the disagreement to be invisible: the measurement in this receipt is computed from exact
    search, and this is the number that says how far a reader relying on the index would be
    from it.
    """
    try:
        import chromadb
    except ImportError:
        return {
            "backend": "not installed",
            "reading": (
                "chromadb is an optional extra. The measurement below is exact cosine search, "
                "which is what the receipt reports either way, so this is a missing check "
                "rather than a missing result."
            ),
        }

    client = chromadb.EphemeralClient()
    collection = client.create_collection(
        "precedent", metadata={"hnsw:space": "cosine"}
    )
    collection.add(
        ids=[str(obs.obs_id) for obs in pool],
        embeddings=[vectors[obs.obs_id] for obs in pool],
        metadatas=[
            {"station": obs.station or -1, "satellite": obs.satellite or -1}
            for obs in pool
        ],
    )

    overlap: dict[str, list[float]] = {condition: [] for condition in CONDITIONS}
    for condition in CONDITIONS:
        for obs in pool:
            where = None
            if condition == "cold":
                where = {
                    "$and": [
                        {"station": {"$ne": obs.station or -1}},
                        {"satellite": {"$ne": obs.satellite or -1}},
                    ]
                }
            found = collection.query(
                query_embeddings=[vectors[obs.obs_id]],
                n_results=TOP_K + 1,
                where=where,
            )
            ids = [int(x) for x in found["ids"][0] if int(x) != obs.obs_id][:TOP_K]
            exact = retrievals[condition]["granite_text"][str(obs.obs_id)] or []
            if not exact:
                continue
            overlap[condition].append(len(set(ids) & set(exact)) / len(exact))

    return {
        "backend": f"chromadb {chromadb.__version__}, cosine, in memory",
        "recall_at_k_against_exact_search": {
            condition: round(_mean(values), 4) for condition, values in overlap.items()
        },
        "queries_compared": {condition: len(values) for condition, values in overlap.items()},
        "reading": (
            "The share of the exact top-5 that the index also returned, per query, averaged. "
            "The cold condition is answered by a metadata filter on station and satellite "
            "inside the index rather than by filtering afterwards, so this also checks that "
            "the filter and the exclusion rule agree."
        ),
    }


def score(frozen: dict[str, Any]) -> dict[str, Any]:
    """Everything the receipt reports, computed from the frozen retrievals alone."""
    observations = [
        Observation(
            obs_id=int(row["obs_id"]),
            label=row["label"],
            station=row["station"],
            satellite=row["satellite"],
            start=row["start"],
            card="",
            features=(),
        )
        for row in frozen["observations"]
    ]
    labels = {obs.obs_id: obs.label for obs in observations}
    by_id = {obs.obs_id: obs for obs in observations}

    per_condition: dict[str, Any] = {}
    for condition in CONDITIONS:
        arms: dict[str, Any] = {}
        per_query: dict[str, dict[int, float]] = {}
        for arm in ARMS:
            values: list[float] = []
            queries: list[int] = []
            undefined = 0
            for obs in observations:
                retrieved = frozen["retrievals"][condition][arm].get(str(obs.obs_id))
                if retrieved is None:
                    undefined += 1
                    continue
                value = agreement(obs.label, retrieved, labels)
                if value is None:
                    undefined += 1
                    continue
                values.append(value)
                queries.append(obs.obs_id)
            per_query[arm] = dict(zip(queries, values, strict=True))
            arms[arm] = {
                "queries_scored": len(values),
                "queries_undefined": undefined,
                "agreement_at_k": None if not values else round(_mean(values), 4),
                "neighbours_per_query": TOP_K,
            }
            if arm == "same_station" and condition == "cold":
                arms[arm]["not_applicable"] = (
                    "The cold condition excludes candidates from the query's own station, so "
                    "this arm has no definition here. Reported as null rather than as zero "
                    "agreement, which would be a measurement nobody made."
                )
        per_condition[condition] = {
            "arms": arms,
            "chance_level": round(chance_level([obs.label for obs in observations]), 4),
            "comparisons": _compare(per_query, by_id, condition),
        }

    return {
        "conditions": per_condition,
        "candidate_pool": {
            "observations": len(observations),
            "labels": {
                name: sum(1 for obs in observations if obs.label == name)
                for name in DECISIVE_LABELS
            },
            "stations": len({obs.station for obs in observations}),
            "satellites": len({obs.satellite for obs in observations}),
        },
    }


def _compare(
    per_query: dict[str, dict[int, float]],
    by_id: dict[int, Observation],
    condition: str,
) -> dict[str, Any]:
    """Every arm against the random arm, and Granite against the numeric baseline.

    The statistic is a per-query mean, so it resamples with the same grouped bootstrap the
    fusion unit uses for its non-averageable statistics rather than a second implementation of
    the same idea. Groups are the query's ground station: two queries from one station share a
    receiver, a horizon and an operator, and treating them as independent is the mistake that
    made an earlier interval in this project too narrow.
    """
    out: dict[str, Any] = {}
    pairs = [("granite_text", "random"), ("numeric_knn", "random"), ("granite_text", "numeric_knn")]
    if condition == "warm":
        pairs.insert(2, ("same_station", "random"))

    for challenger, reference in pairs:
        shared = sorted(set(per_query[challenger]) & set(per_query[reference]))
        if len(shared) < 30:
            out[f"{challenger}_vs_{reference}"] = {
                "measurable": False,
                "why": f"only {len(shared)} queries have both arms defined",
            }
            continue
        challenger_values = np.array([per_query[challenger][q] for q in shared], dtype=float)
        reference_values = np.array([per_query[reference][q] for q in shared], dtype=float)
        groups = np.array(
            [by_id[q].station if by_id[q].station is not None else -1 for q in shared]
        )
        labels = np.array([1 if by_id[q].label == DECISIVE_LABELS[0] else 0 for q in shared])

        result = grouped_bootstrap_statistic_difference(
            lambda values, _labels, _groups: float(np.mean(values)),
            challenger_values,
            reference_values,
            labels,
            groups,
            n_boot=10_000,
            seed=SEED,
            lower_is_better=False,
            n_comparisons=N_COMPARISONS,
        )
        if result["ci95"] is None:
            # The bootstrap's own third outcome: too few finite resamples to form an interval.
            # It is a statement about the resampling and it must not read as a tie.
            out[f"{challenger}_vs_{reference}"] = {
                "measurable": False,
                "why": result["note"],
                "queries": len(shared),
                "usable_resamples": int(result["n_usable_resamples"]),
            }
            continue
        out[f"{challenger}_vs_{reference}"] = {
            "measurable": True,
            "queries": len(shared),
            "challenger_agreement": round(float(np.mean(challenger_values)), 4),
            "reference_agreement": round(float(np.mean(reference_values)), 4),
            "margin": round(float(result["margin"]), 4),
            "ci95": [round(float(v), 4) for v in result["ci95"]],
            "ci_adjusted": [round(float(v), 4) for v in result["ci_adjusted"]],
            "adjusted_confidence": round(float(result["adjusted_confidence"]), 4),
            "n_comparisons": int(result["n_comparisons"]),
            "survives_correction": bool(result["survives_correction"]),
            "n_groups": int(result["n_groups"]),
            "n_observations": int(result["n_observations"]),
            "degenerate_resamples": int(result["n_degenerate_resamples"]),
            "direction": result["direction"],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--snapshot", type=Path, default=Path("D:/tracetriage_data/snap-stage1"))
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--out", type=Path, default=RECEIPT)
    args = ap.parse_args(argv)

    if args.freeze:
        freeze(args.snapshot, args.fixture)

    if not args.fixture.exists():
        raise SystemExit(
            f"{args.fixture} does not exist. Run with --freeze, which needs the snapshot and a "
            f"local embedding model."
        )
    frozen = json.loads(args.fixture.read_text(encoding="utf-8"))
    import hashlib

    payload = {
        "schema": "PRECEDENT_RECEIPT",
        "schema_version": 1,
        "unit": "E8",
        "question": (
            "Do the passes most similar to this one, by what is knowable before the waterfall is "
            "opened, carry the same recorded outcome more often than chance?"
        ),
        "design": (
            "Four retrieval arms over the same candidate pool, under two conditions. Warm allows "
            "any other observation. Cold requires a different ground station and a different "
            "satellite, because in this corpus the outcome is partly a property of who recorded "
            "it. Agreement at 5 is the mean over queries of the share of retrieved neighbours "
            "carrying the query's own label."
        ),
        "embedding_model": frozen["embedding_model"],
        "top_k": frozen["top_k"],
        "feature_names": frozen["feature_names"],
        "vector_index": frozen["vector_index"],
        "cards_sha256": frozen["cards_sha256"],
        "vectors_sha256": frozen["vectors_sha256"],
        "frozen_retrievals_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
        **score(frozen),
        "what_this_does_not_measure": [
            "Whether a reviewer shown these neighbours decides faster or better. That is kill "
            "gate 4's territory and it is still open.",
            "Whether the label a neighbour carries is correct. The network's waterfall_status is "
            "a silver label, and agreement with it is agreement with the network rather than "
            "with the sky.",
            "Anything about the images. Every arm here sees only what is knowable before the "
            "waterfall is opened, which is the point, and it means none of these arms is a "
            "detector.",
        ],
    }
    args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    for condition in CONDITIONS:
        arms = payload["conditions"][condition]["arms"]
        chance = payload["conditions"][condition]["chance_level"]
        line = ", ".join(
            f"{arm} {arms[arm]['agreement_at_k']}" for arm in ARMS
        )
        print(f"{condition}: {line} (chance {chance})")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
