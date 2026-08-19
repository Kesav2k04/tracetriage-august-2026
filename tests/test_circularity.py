"""The circularity analysis has to reproduce the gate before it is allowed to bound it.

`scripts/run_circularity_check.py` exists to say how much of gate 6's lift is guaranteed by
the queue being ranked on the same three quantities the conflict criteria threshold. That is
a claim about the same measurement, so the first thing it must do is recover the published
number from the queue receipt alone. A bounding analysis computed over a different population
would be a different result wearing the gate's name, which is worse than no analysis.

The checks here go in that order: the reproduction first, then the properties of the bound.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "CIRCULARITY_RECEIPT.json"
QUEUE = REPO / "artifacts" / "QUEUE_RECEIPT.json"


def _load_script():
    path = REPO / "scripts" / "run_circularity_check.py"
    spec = importlib.util.spec_from_file_location("run_circularity_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_circularity_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture(scope="module")
def receipt() -> dict:
    if not RECEIPT.exists():
        pytest.skip(
            "artifacts/CIRCULARITY_RECEIPT.json is absent. Run "
            "scripts/run_circularity_check.py."
        )
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def queue() -> dict:
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def test_the_committed_receipt_is_what_the_queue_receipt_produces(script, receipt):
    fresh = script.build()
    a = {k: v for k, v in fresh.items() if k != "generated_at"}
    b = {k: v for k, v in receipt.items() if k != "generated_at"}
    assert a == b, "the committed circularity receipt is stale against QUEUE_RECEIPT.json"


def test_it_reproduces_the_published_lift(receipt, queue):
    """The precondition. Everything else in the file is about a different queue without it."""
    published = queue["gate6"]["per_split"]["chronological"]
    rep = receipt["reproduction"]
    assert rep["matches_the_queue_receipt"] is True
    assert rep["lift_point"] == pytest.approx(published["lift_point"], abs=1e-9)
    assert rep["n_at_budget"] == published["n_queue_conflicts"]
    assert rep["n_population"] == published["replay_episode"]["n_population"]


def test_a_population_that_does_not_match_refuses_to_write(script, tmp_path, monkeypatch):
    """The reproduction check has to be able to fail, or it is a comment.

    Dropping one observation from the population changes the random expectation and the
    published lift is no longer recoverable. The script must stop rather than publish a
    bound computed over a different set.
    """
    doc = json.loads(QUEUE.read_text(encoding="utf-8"))
    doc["queue"] = [
        entry
        for entry in doc["queue"]
        if not (
            entry["waterfall_status"] in ("with-signal", "without-signal")
            and entry["rank"] > 300
        )
    ]
    path = tmp_path / "QUEUE_RECEIPT.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(script, "QUEUE_RECEIPT", path)
    with pytest.raises(SystemExit) as raised:
        script.build()
    assert "reproduce the published lift" in str(raised.value)


def test_every_conflict_criterion_is_mapped_to_a_score_weight(script):
    """An unmapped criterion would leave a shared signal out of the accounting.

    The accounting is the whole point of the file, so a criterion added to the pipeline
    without a weight beside it has to stop the run rather than shrink the total quietly.
    """
    from pipeline.tracetriage.queue import CONFLICT_CRITERIA

    mapped = set(script.SHARED_SIGNALS)
    defined = {c["reason_code"] for c in CONFLICT_CRITERIA}
    assert mapped == defined


def test_the_weights_sum_to_one_with_the_unshared_signal(script):
    shared = sum(v["score_weight"] for v in script.SHARED_SIGNALS.values())
    assert shared + script.UNSHARED_SIGNAL["score_weight"] == pytest.approx(1.0)


def test_the_shared_weight_is_reported_and_is_most_of_the_score(receipt):
    """The finding, asserted rather than described.

    If a future reweighting moved most of the score onto a signal no criterion reads, the
    circularity would be smaller and this test would fail, which is the correct outcome:
    the README sentence it supports would need rewriting.
    """
    shared = receipt["shared_signals"][
        "score_weight_on_quantities_the_target_is_defined_from"
    ]
    independent = receipt["shared_signals"]["score_weight_independent_of_the_target"]
    assert shared + independent == pytest.approx(1.0)
    assert shared >= 0.5, (
        "most of the score no longer sits on quantities the conflict definition reads, so "
        "the README's circularity paragraph overstates the problem and needs rewriting"
    )


def test_the_ceiling_is_the_population_over_the_budget(receipt):
    """An oracle finds every conflict it has room for, so lift saturates at n/budget."""
    rep = receipt["reproduction"]
    ceiling = receipt["ceiling"]
    assert ceiling["max_findable_at_budget"] == min(rep["budget"], rep["n_conflicts"])
    assert ceiling["lift"] == pytest.approx(rep["n_population"] / rep["budget"])
    assert ceiling["lift"] > rep["lift_point"], "the queue cannot beat an oracle"
    assert ceiling["headroom_between_threshold_and_perfection"] == pytest.approx(
        ceiling["lift"] - ceiling["threshold"]
    )


def test_a_random_ordering_scores_one(receipt):
    """The floor. A lift framework that cannot score a shuffle at 1.0 measures nothing."""
    control = receipt["random_ordering_control"]
    assert control["abs_error"] < 0.01, (
        f"random orderings mean {control['mean_lift']}, which is not 1.0, so the lift "
        "statistic itself is biased and no number computed with it can be read"
    )
    assert control["p5"] < 1.0 < control["p95"]


def test_a_saturated_target_is_not_reported_as_a_pass(receipt):
    """The trap this analysis would otherwise walk into.

    When the queue finds every conflict inside the budget, lift equals n_population /
    budget whatever the conflict count was, and the interval around a constant is narrow.
    Printing PASSED there would put the strongest verdict in the file on the least
    information. Saturation gets its own outcome.
    """
    saturated = [
        (name, block)
        for name, block in receipt["targets"].items()
        if block.get("measurable") and block.get("saturated")
    ]
    for name, block in saturated:
        assert block["verdict"] == "NOT_INFORMATIVE", (
            f"{name} found every conflict inside the budget and is reported as "
            f"{block['verdict']}"
        )
        assert block["lift_point"] == pytest.approx(receipt["ceiling"]["lift"])
        assert block["saturation_note"]


def test_the_model_independent_target_is_measured_and_named(receipt):
    """The comparison the whole file exists to publish.

    Two of the three criteria are computed without the model: the fitted offset and the
    flat-row fraction. Restricting the target to them removes the loop that runs from the
    model's own probability into the definition of a find.
    """
    block = receipt["targets"]["model_independent_only"]
    assert block["measurable"], block.get("not_measurable_reason")
    assert set(block["criteria"]) == {"STALE_CATALOGUE_FREQ", "DEAD_CAPTURE"}
    assert block["n_conflicts"] > 0
    lo, hi = block["lift_ci95"]
    assert lo < block["lift_point"] < hi


def test_it_does_not_claim_the_loop_is_closed(receipt):
    """The sentence that keeps this honest has to be in the receipt, not only in a docstring.

    Restricting the target to the two model-free criteria removes one loop and leaves
    another: the score still weights those two quantities at 0.35 and 0.15.
    """
    text = receipt["what_this_does_not_establish"]
    assert "generalises" in text
    assert "0.35" in text and "0.15" in text


def test_it_reads_no_snapshot(receipt):
    """A judge without the 4 GB snapshot has to be able to run this."""
    assert receipt["source"]["needs_the_snapshot"] is False
    assert receipt["source"]["receipt"] == "artifacts/QUEUE_RECEIPT.json"
