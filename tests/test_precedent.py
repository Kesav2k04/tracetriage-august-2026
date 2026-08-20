"""Precedent retrieval, tested where a retrieval study fools itself (unit E8).

Three ways this study could have produced a good number and meant nothing, each with a test:
the rendered card could carry the label it is trying to predict, the cold condition could fail
to exclude the entity it is named for, and the random arm could be drawn from a different pool
than the arms it is the control for. A fourth, the one that is hardest to see, is a metric that
counts an undefined arm as a zero: `same_station` has no meaning under the cold condition, and a
mean that folded it in would have manufactured a comparison.

Everything here runs offline from the frozen retrievals. The chroma test skips without the
optional extra and says so.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from run_precedent_study import score  # noqa: E402

from pipeline.tracetriage.precedent import (  # noqa: E402
    ARMS,
    CONDITIONS,
    DECISIVE_LABELS,
    FORBIDDEN_FIELDS,
    TOP_K,
    Observation,
    agreement,
    chance_level,
    cosine,
    digest_of,
    euclidean,
    features_of,
    is_candidate,
    observations_from,
    render_card,
    standardise,
    top_k_exact,
    top_k_random,
    top_k_same_station,
)

FIXTURE = REPO / "tests" / "fixtures" / "precedent_retrievals.json"
RECEIPT = REPO / "artifacts" / "PRECEDENT_RECEIPT.json"
STUDY = REPO / "scripts" / "run_precedent_study.py"


@pytest.fixture(scope="module")
def frozen() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def receipt() -> dict[str, Any]:
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _row(**kwargs: Any) -> dict[str, Any]:
    row = {
        "id": 1,
        "waterfall_status": "with-signal",
        "ground_station": 10,
        "norad_cat_id": 20,
        "sat_id": "AAAA-1111",
        "station_name": "abc",
        "station_lat": 12.5,
        "station_lng": -30.25,
        "center_frequency": 437_500_000,
        "max_altitude": 42.0,
        "start": "2026-08-01T10:00:00Z",
        "end": "2026-08-01T10:08:00Z",
        "status": "good",
        "demoddata": [{"payload_demod": "x"}],
        "archive_url": "https://example.invalid/a.ogg",
    }
    row.update(kwargs)
    return row


# ---------------------------------------------------------------------------
# The leak
# ---------------------------------------------------------------------------


def test_the_rendered_card_never_carries_the_answer():
    """status and demoddata each settle the label without opening the waterfall."""
    card = render_card(_row())
    for field in FORBIDDEN_FIELDS:
        assert field not in card, f"the card names {field}"
    assert "good" not in card, "the network's own verdict is in the card"
    assert "with-signal" not in card


def test_every_frozen_card_digest_covers_every_observation(frozen):
    """The digest is what a rebuild is compared against, so it has to cover the whole pool."""
    observations = frozen["observations"]
    assert len(observations) == len({row["obs_id"] for row in observations})
    assert len(frozen["cards_sha256"]) == 64
    assert len(frozen["vectors_sha256"]) == 64
    assert digest_of([]) != frozen["cards_sha256"]


def test_the_labels_in_the_pool_are_only_the_decisive_ones(frozen):
    labels = {row["label"] for row in frozen["observations"]}
    assert labels <= set(DECISIVE_LABELS)
    assert labels == set(DECISIVE_LABELS), "one class is missing, so agreement is not measurable"


# ---------------------------------------------------------------------------
# The conditions
# ---------------------------------------------------------------------------


def test_the_cold_condition_excludes_the_entities_it_is_named_for():
    query = Observation(1, "with-signal", 10, 20, None, "", ())
    same_station = Observation(2, "with-signal", 10, 99, None, "", ())
    same_satellite = Observation(3, "with-signal", 99, 20, None, "", ())
    elsewhere = Observation(4, "with-signal", 99, 98, None, "", ())

    assert is_candidate(query, same_station, "warm")
    assert is_candidate(query, same_satellite, "warm")
    assert not is_candidate(query, query, "warm")

    assert not is_candidate(query, same_station, "cold")
    assert not is_candidate(query, same_satellite, "cold")
    assert is_candidate(query, elsewhere, "cold")


def test_an_unknown_condition_raises_rather_than_defaulting_to_warm():
    query = Observation(1, "with-signal", 10, 20, None, "", ())
    other = Observation(2, "with-signal", 10, 20, None, "", ())
    with pytest.raises(ValueError):
        is_candidate(query, other, "tepid")


def test_the_frozen_cold_retrievals_hold_the_rule(frozen):
    """The rule in code and the rule in the frozen data are two different claims."""
    by_id = {int(row["obs_id"]): row for row in frozen["observations"]}
    checked = 0
    for arm in ARMS:
        for obs_id, retrieved in frozen["retrievals"]["cold"][arm].items():
            if retrieved is None:
                continue
            query = by_id[int(obs_id)]
            for neighbour in retrieved:
                row = by_id[neighbour]
                assert row["station"] != query["station"], f"{arm}: same station retrieved"
                assert row["satellite"] != query["satellite"], f"{arm}: same satellite"
                checked += 1
    assert checked > 1000, f"only {checked} cold neighbours checked, so the scan proved little"


def test_no_arm_retrieves_the_query_itself(frozen):
    for condition in CONDITIONS:
        for arm in ARMS:
            for obs_id, retrieved in frozen["retrievals"][condition][arm].items():
                if retrieved is None:
                    continue
                assert int(obs_id) not in retrieved, f"{arm}/{condition} retrieved the query"


# ---------------------------------------------------------------------------
# The arms
# ---------------------------------------------------------------------------


def test_the_random_arm_draws_from_the_same_pool_as_the_others():
    """A control drawn from a different pool measures the pool, not the arms."""
    pool = [
        Observation(i, "with-signal" if i % 2 else "without-signal", i % 3, i % 5, None, "", ())
        for i in range(1, 40)
    ]
    query = pool[0]
    rng = random.Random(0)
    drawn = top_k_random(query, pool, "cold", rng)
    exact = top_k_exact(
        query,
        pool,
        {obs.obs_id: [float(obs.obs_id)] for obs in pool},
        "cold",
        metric="euclidean",
    )
    allowed = {obs.obs_id for obs in pool if is_candidate(query, obs, "cold")}
    assert set(drawn) <= allowed
    assert set(exact) <= allowed
    assert len(drawn) == TOP_K


def test_the_same_station_arm_is_undefined_cold_rather_than_zero():
    pool = [Observation(i, "with-signal", 7, i, f"2026-08-0{i}", "", ()) for i in range(1, 9)]
    warm = top_k_same_station(pool[0], pool, "warm")
    assert warm is not None and len(warm) == TOP_K
    assert top_k_same_station(pool[0], pool, "cold") is None


def test_the_same_station_arm_returns_that_station_and_the_recent_ones_first():
    pool = [
        Observation(1, "with-signal", 7, 1, "2026-08-01T00:00:00Z", "", ()),
        Observation(2, "with-signal", 7, 2, "2026-08-05T00:00:00Z", "", ()),
        Observation(3, "with-signal", 8, 3, "2026-08-09T00:00:00Z", "", ()),
    ]
    assert top_k_same_station(pool[0], pool, "warm") == [2]


def test_agreement_is_none_for_an_empty_retrieval_rather_than_zero():
    labels = {2: "with-signal", 3: "without-signal"}
    assert agreement("with-signal", [], labels) is None
    assert agreement("with-signal", [2, 3], labels) == 0.5
    assert agreement("with-signal", [2], labels) == 1.0


def test_the_chance_level_is_the_label_mix_and_the_random_arm_lands_on_it(receipt):
    """The label mix comes from the receipt's own pool, not from a count typed here.

    It was typed, as 464 and 279. Restricting the pool to the observations the dataset
    manifest stores moved it to 462 and 277, and the typed version failed on the fourth
    decimal of a chance level rather than on anything about the study. A count written
    beside a corpus that can change is a count that will disagree with it.
    """
    pool = receipt["candidate_pool"]["labels"]
    labels = ["with-signal"] * pool["with-signal"] + ["without-signal"] * pool["without-signal"]
    assert len(labels) == receipt["candidate_pool"]["observations"]
    expected = chance_level(labels)
    assert round(expected, 4) == receipt["conditions"]["warm"]["chance_level"]
    measured = receipt["conditions"]["warm"]["arms"]["random"]["agreement_at_k"]
    assert abs(measured - expected) < 0.05, (
        f"the random arm measured {measured} where the label mix predicts {expected:.4f}. A gap "
        f"means the candidate pools are not what the arm thought they were."
    )


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def test_standardising_a_constant_column_leaves_it_alone_instead_of_producing_nan():
    rows = [(1.0, 5.0), (2.0, 5.0), (3.0, 5.0)]
    out = standardise(rows)
    assert all(row[1] == 0.0 for row in out)
    assert abs(sum(row[0] for row in out)) < 1e-12


def test_the_local_hour_is_circular_so_midnight_is_not_far_from_one_minute_past():
    late = features_of(_row(start="2026-08-01T23:50:00Z", station_lng=0.0))
    early = features_of(_row(start="2026-08-02T00:10:00Z", station_lng=0.0))
    noon = features_of(_row(start="2026-08-01T12:00:00Z", station_lng=0.0))
    near = euclidean(late[-2:], early[-2:])
    far = euclidean(late[-2:], noon[-2:])
    assert near < far / 5, f"midnight and one minute past are {near:.3f} apart, noon is {far:.3f}"


def test_cosine_and_euclidean_agree_about_what_is_closest_when_they_should():
    query = [1.0, 0.0]
    same = [2.0, 0.0]
    other = [0.0, 1.0]
    assert cosine(query, same) == pytest.approx(1.0)
    assert cosine(query, other) == pytest.approx(0.0)
    assert euclidean(query, other) > euclidean(query, [1.0, 0.1])


def test_observations_from_drops_the_unlabelled_and_sorts_by_id():
    rows = [
        _row(id=3, waterfall_status="with-signal"),
        _row(id=1, waterfall_status="unknown"),
        _row(id=2, waterfall_status="without-signal"),
    ]
    out = observations_from(rows)
    assert [obs.obs_id for obs in out] == [2, 3]


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------


def test_the_committed_receipt_is_what_the_frozen_retrievals_produce(tmp_path):
    """No snapshot, no model, no index: the published numbers regenerate from what is committed."""
    out = tmp_path / "PRECEDENT_RECEIPT.json"
    finished = subprocess.run(
        [sys.executable, str(STUDY), "--out", str(out)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(
        RECEIPT.read_text(encoding="utf-8")
    )


def test_the_receipt_scores_what_the_fixture_holds(frozen, receipt):
    again = score(frozen)
    assert again["candidate_pool"] == receipt["candidate_pool"]
    for condition in CONDITIONS:
        for arm in ARMS:
            assert (
                again["conditions"][condition]["arms"][arm]["agreement_at_k"]
                == receipt["conditions"][condition]["arms"][arm]["agreement_at_k"]
            )


def test_the_cold_condition_is_reported_even_though_it_is_the_weaker_result(receipt):
    """The finding this unit exists to publish rather than to bury."""
    warm = receipt["conditions"]["warm"]["comparisons"]["granite_text_vs_random"]
    cold = receipt["conditions"]["cold"]["comparisons"]["granite_text_vs_random"]
    assert warm["measurable"] and cold["measurable"]
    assert warm["margin"] > cold["margin"]
    # Whatever the numbers become on a re-freeze, the corrected interval and the direction have
    # to be published for both conditions, and the direction has to follow the interval.
    for row in (warm, cold):
        assert len(row["ci_adjusted"]) == 2
        assert row["n_comparisons"] >= 5
        if row["direction"] == "challenger_better":
            assert row["ci95"][0] > 0
        elif row["direction"] == "indistinguishable":
            assert row["ci95"][0] <= 0 <= row["ci95"][1]


def test_the_same_station_arm_is_null_in_the_cold_condition_with_its_reason(receipt):
    cold = receipt["conditions"]["cold"]["arms"]["same_station"]
    assert cold["agreement_at_k"] is None
    assert "no definition" in cold["not_applicable"]
    assert cold["queries_undefined"] == receipt["candidate_pool"]["observations"]


def test_the_receipt_names_the_embedding_model_and_the_features(receipt):
    assert "granite" in receipt["embedding_model"]["name"]
    assert len(receipt["feature_names"]) >= 5
    assert receipt["top_k"] == TOP_K


def test_the_receipt_states_what_it_does_not_measure(receipt):
    text = " ".join(receipt["what_this_does_not_measure"]).lower()
    assert "gate 4" in text
    assert "silver label" in text


def test_the_bootstrap_groups_by_station_rather_than_by_observation(receipt):
    """Two passes from one station share a receiver and a horizon."""
    for condition in CONDITIONS:
        for name, row in receipt["conditions"][condition]["comparisons"].items():
            if not row["measurable"]:
                continue
            assert row["n_groups"] < row["n_observations"], (
                f"{condition}/{name} resampled {row['n_groups']} groups over "
                f"{row['n_observations']} observations, which is an observation-level bootstrap"
            )


# ---------------------------------------------------------------------------
# The vector index
# ---------------------------------------------------------------------------


def test_the_index_agreed_with_exact_search_when_it_was_present(receipt):
    index = receipt["vector_index"]
    if index["backend"] == "not installed":
        pytest.skip(
            "chromadb is an optional extra and the freeze ran without it, which the receipt says"
        )
    for condition, recall in index["recall_at_k_against_exact_search"].items():
        assert recall > 0.9, f"{condition}: the index returned {recall} of the exact top-5"
        assert index["queries_compared"][condition] > 100


def test_a_real_index_returns_the_exact_neighbours_for_a_small_pool():
    """The cross-check, live, on a pool small enough that exact search is the truth."""
    chromadb = pytest.importorskip("chromadb", reason="the vector extra is not installed")
    rng = random.Random(3)
    pool = [
        Observation(i, "with-signal", i % 4, i % 7, None, "", ())
        for i in range(1, 40)
    ]
    vectors = {obs.obs_id: [rng.random() for _ in range(16)] for obs in pool}

    client = chromadb.EphemeralClient()
    collection = client.create_collection("small-pool", metadata={"hnsw:space": "cosine"})
    collection.add(
        ids=[str(obs.obs_id) for obs in pool],
        embeddings=[vectors[obs.obs_id] for obs in pool],
        metadatas=[{"station": obs.station, "satellite": obs.satellite} for obs in pool],
    )
    query = pool[0]
    found = collection.query(
        query_embeddings=[vectors[query.obs_id]],
        n_results=TOP_K + 1,
        where={
            "$and": [
                {"station": {"$ne": query.station}},
                {"satellite": {"$ne": query.satellite}},
            ]
        },
    )
    ids = [int(x) for x in found["ids"][0] if int(x) != query.obs_id][:TOP_K]
    exact = top_k_exact(query, pool, vectors, "cold", metric="cosine")
    assert ids == exact, "the index and exact search disagree on a pool this size"


def test_the_cold_condition_excludes_the_site_and_not_only_the_station_id():
    """Nine sites in this pool carry more than one station id.

    The reason written down for the cold condition is that a misconfigured station produces
    empty waterfalls for weeks, and that is a property of a physical site and its operator.
    The filter compared ground_station integers, so a site running four receivers under four
    ids satisfied "a different station" while being the same dish on the same roof. 22.76% of
    Granite's cold neighbours came from the query's own site against 0.89% for a random draw.
    Both the rendered card and the numeric feature vector carry the coordinates, so both
    model arms could find them.
    """
    here = (49.232, -121.759)
    query = Observation(1, "with-signal", 10, 20, None, "", (), site=here)
    second_id_same_roof = Observation(2, "with-signal", 4825, 99, None, "", (), site=here)
    elsewhere = Observation(3, "with-signal", 99, 98, None, "", (), site=(51.5, -0.1))
    no_position = Observation(4, "with-signal", 98, 97, None, "", (), site=None)

    assert is_candidate(query, second_id_same_roof, "warm")
    assert not is_candidate(query, second_id_same_roof, "cold"), (
        "a second station id at the same coordinates is the same receiving site, which is "
        "what the cold condition was written to exclude"
    )
    assert is_candidate(query, elsewhere, "cold")
    assert is_candidate(query, no_position, "cold"), (
        "a row with no position does not share a site with anything, and excluding it would "
        "punish a missing field rather than a real overlap"
    )


def test_a_query_with_no_position_is_not_excluded_from_everything():
    """An absent site must not collide with another absent site.

    If None equalled None the rule would exclude every unpositioned row from every other
    unpositioned row, which is an exclusion nobody asked for, silently shrinking the cold
    candidate pool for exactly the rows with the least metadata.
    """
    a = Observation(1, "with-signal", 10, 20, None, "", (), site=None)
    b = Observation(2, "with-signal", 11, 21, None, "", (), site=None)
    assert is_candidate(a, b, "cold")


def test_the_frozen_cold_retrievals_hold_the_site_rule(frozen):
    """The rule in code and the rule in the frozen data are two different claims."""
    by_id = {int(row["obs_id"]): row for row in frozen["observations"]}
    checked = 0
    with_a_site = 0
    for arm in ARMS:
        for obs_id, retrieved in frozen["retrievals"]["cold"][arm].items():
            if retrieved is None:
                continue
            query = by_id[int(obs_id)]
            for neighbour in retrieved:
                row = by_id[neighbour]
                if query.get("site") is not None:
                    with_a_site += 1
                    assert row.get("site") != query["site"], (
                        f"{arm}: retrieved a neighbour at the query's own site "
                        f"{query['site']} under the cold condition"
                    )
                checked += 1
    assert checked > 1000, f"only {checked} cold neighbours checked, so the scan proved little"
    assert with_a_site > 1000, (
        f"only {with_a_site} of the cold neighbours were checked against a query that has a "
        "site, so this scan says almost nothing about the rule it is testing"
    )


def test_the_cold_condition_census_is_published_with_its_counts(receipt):
    """The size of the gap that closed, so a reader is not asked to take it on trust."""
    census = receipt["cold_condition"]
    assert census.get("measurable") is not False, census.get("why")
    assert census["n_sites_with_more_than_one_station_id"] > 0
    assert (
        census["n_station_ids_at_those_sites"]
        > census["n_sites_with_more_than_one_station_id"]
    )
    assert census["n_pairs_the_site_rule_excludes_that_the_id_rule_did_not"] > 0
    assert "site" in " ".join(census["excludes"]).lower()
    assert "station" in " ".join(census["excludes"]).lower()


def test_the_comparison_count_is_derived_from_the_comparisons_that_are_made():
    """A hand-maintained Bonferroni denominator is a silent correctness bug waiting.

    N_COMPARISONS was the literal 7, set 300 lines above the list it counted. It was right,
    and nothing tied it to the list: adding one pair would have left every published
    ci_adjusted too narrow and every survives_correction computed at the wrong alpha, with
    the suite green, because the only guard asserted the count was at least 5.
    """
    import run_precedent_study as study

    expected = (
        len(study._pairs("warm"))
        + len(study._pairs("cold"))
        + len(study.CROSS_CONDITION_ARMS)
    )
    assert expected == study.N_COMPARISONS


def test_every_published_comparison_is_counted_in_the_family(receipt):
    """The count in the receipt has to match the number of comparisons in the receipt."""
    made = 0
    for condition in CONDITIONS:
        made += len(receipt["conditions"][condition]["comparisons"])
    made += len(receipt["cross_condition_comparisons"])
    counted = {
        row["n_comparisons"]
        for condition in CONDITIONS
        for row in receipt["conditions"][condition]["comparisons"].values()
        if row.get("measurable")
    } | {
        row["n_comparisons"]
        for row in receipt["cross_condition_comparisons"].values()
        if row.get("measurable")
    }
    assert len(counted) == 1, f"the family size is not agreed across comparisons: {counted}"
    assert counted.pop() == made, (
        f"the receipt publishes {made} comparisons and corrects for a different number, so "
        "every adjusted interval in it is the wrong width"
    )


def test_the_warm_cold_drop_is_measured_rather_than_read_off_two_intervals(receipt):
    """The claim the register makes, tested as the difference it is.

    "Similarity carries the outcome when the station is allowed, and stops carrying it when
    it is not" is a statement about warm minus cold. It was asserted from one interval
    excluding zero and another spanning it, which is not a test of the difference: two wide
    intervals can show that pattern with no real drop at all. The paired per-query
    difference is the comparison, and it is corrected in the same family as the rest.
    """
    row = receipt["cross_condition_comparisons"]["granite_text_warm_vs_cold"]
    assert row["measurable"], row.get("why")
    assert row["queries"] > 500
    assert row["n_groups"] > 50, "the difference is grouped by station like everything else"
    lo, hi = row["ci95"]
    assert lo <= row["margin"] <= hi
    adj_lo, adj_hi = row["ci_adjusted"]
    assert adj_lo <= lo and adj_hi >= hi, "the corrected interval must not be narrower"
    assert row["survives_correction"] is ((adj_lo > 0) or (adj_hi < 0))
    assert row["margin"] == pytest.approx(
        row["warm_agreement"] - row["cold_agreement"], abs=5e-4
    )


def test_the_cross_condition_reading_says_which_way_it_fell(receipt):
    """A verdict a reader can act on, generated from the number rather than written once."""
    row = receipt["cross_condition_comparisons"]["granite_text_warm_vs_cold"]
    reading = row["reading"]
    assert f"{row['margin']:.4f}" in reading
    assert str(row["n_comparisons"]) in reading
    if row["survives_correction"]:
        assert "excludes zero" in reading
    else:
        assert "spans zero" in reading
