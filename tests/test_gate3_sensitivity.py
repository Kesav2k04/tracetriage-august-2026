"""The sensitivity table has to agree with the receipt it describes, or it is noise.

`docs/E16_PREREGISTRATION.md` names `TRACE_Q75_MIN` as a researcher degree of freedom and
promises the verdict's sensitivity to it. A table that disagreed with the published
receipt at the published bar, or that quietly estimated bars nothing was scored at, would
be worse than not publishing one: it would look like a robustness check and function as
cover.

Five properties, each tested against the way it could actually go wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.gate3_sensitivity import as_table, measure, verdict_for
from scripts.run_gate3 import rate_lower_bound

REPO = Path(__file__).resolve().parent.parent
RECEIPT = REPO / "artifacts" / "GATE3_RECEIPT.json"
POOL = REPO / "artifacts" / "GATE3_POOL.json"


def _synthetic(n=60, bar=3.5, discriminates_from=40):
    """A pool and receipt whose discrimination sits in the high-`trace_q75` tail."""
    receipt = {
        "threshold": 0.70,
        "pool": {"name": "pool_b", "trace_q75_min": bar},
        "observations": [
            {
                "obs_id": i,
                "null_calibration": {
                    "p_value": 0.005,
                    "discriminates": i >= discriminates_from,
                },
            }
            for i in range(n)
        ],
    }
    pool = {"observations": [{"obs_id": i, "trace_q75": bar + i * 0.1} for i in range(n)]}
    return receipt, pool


def test_a_tighter_bar_never_scores_more_observations():
    """Membership is `trace_q75 >= bar`, so the counts have to be monotone.

    A join that lost rows, or a comparison written the wrong way round, shows up here
    and nowhere else: every individual row would still look plausible.
    """
    receipt, pool = _synthetic()
    rows = [r for r in measure(receipt, pool)["rows"] if r["scored"] is not None]
    counts = [r["scored"] for r in rows]
    assert counts == sorted(counts, reverse=True), (
        f"scored counts {counts} are not monotone decreasing in the bar"
    )


def test_a_bar_below_the_scored_one_is_never_given_a_number():
    """The denominator would be wrong, and a wrong denominator reads as a result.

    A looser bar selects observations this run never scored. Reporting a rate over only
    the ones it happens to have is a rate over a biased subset of that pool, and it is
    the number a reader would most want to trust.
    """
    receipt, pool = _synthetic(bar=3.5)
    for row in measure(receipt, pool, bars=(2.0, 2.5, 3.0, 3.5))["rows"]:
        if row["trace_q75_min"] < 3.5:
            assert row["verdict"] == "NOT SCORED"
            assert row["scored"] is None
            assert row["rate"] is None
            assert row["lower_bound_95"] is None
            assert "denominator" in row["why"]


def test_the_published_bar_reproduces_the_receipts_own_numbers():
    """The one row that must not drift.

    At the pre-registered bar this table is recomputing exactly what the receipt already
    published. If those two ever disagree, one of them is wrong and a reader has no way
    to tell which.
    """
    receipt, pool = _synthetic()
    out = measure(receipt, pool)
    row = next(r for r in out["rows"] if r.get("is_the_pre_registered_bar"))

    scored = [
        o for o in receipt["observations"]
        if o["null_calibration"]["p_value"] is not None
    ]
    hits = sum(1 for o in scored if o["null_calibration"]["discriminates"])
    assert row["scored"] == len(scored)
    assert row["discriminating"] == hits
    assert row["lower_bound_95"] == pytest.approx(rate_lower_bound(hits, len(scored)))
    assert out["published_verdict"] == row["verdict"]


def test_a_verdict_that_turns_on_the_threshold_is_reported_as_such():
    """The finding this table exists to make impossible to hide.

    With discrimination concentrated in the tail, a tight bar passes and the
    pre-registered one does not. Publishing the rows and calling the check clean would
    be the failure: the summary field has to say the verdict is not constant.
    """
    receipt, pool = _synthetic(discriminates_from=40)
    out = measure(receipt, pool, bars=(3.5, 5.0, 8.0))
    assert out["verdict_is_constant_across_measured_bars"] is False
    assert out["distinct_verdicts"] == ["FAILED", "PASSED"]
    assert out["published_verdict"] == "FAILED", (
        "the published verdict must be the pre-registered bar's, not the best one"
    )


def test_a_stable_verdict_says_so():
    """The other direction, so the flag is not just always False."""
    receipt, pool = _synthetic(discriminates_from=0)
    out = measure(receipt, pool, bars=(3.5, 5.0, 8.0))
    assert out["verdict_is_constant_across_measured_bars"] is True
    assert out["distinct_verdicts"] == ["PASSED"]


def test_the_verdict_rule_matches_the_gate_scripts_own():
    """Two implementations of one rule is how a table starts contradicting a receipt."""
    assert verdict_for(1.0, 0.8, 0.70) == "PASSED"
    assert verdict_for(1.0, 0.36, 0.70) == "NOT_ESTABLISHED"
    assert verdict_for(0.5, 0.30, 0.70) == "FAILED"
    assert verdict_for(None, None, 0.70) == "UNMEASURABLE"


def test_the_table_marks_which_bar_was_pre_registered():
    """A reader who cannot see which row is the published one has six rates and no gate."""
    receipt, pool = _synthetic()
    table = as_table(measure(receipt, pool))
    assert "**3.5**" in table


@pytest.mark.skipif(
    not (RECEIPT.exists() and POOL.exists()), reason="gate 3 has not been run on a pool"
)
def test_the_shipped_table_agrees_with_the_shipped_receipt():
    """The same check as above, against whatever is actually in the tree."""
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    if (receipt.get("pool") or {}).get("name") not in ("pool_a", "pool_b"):
        pytest.skip("the committed receipt predates the pre-registered pools")
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    out = measure(receipt, pool)
    row = next(r for r in out["rows"] if r.get("is_the_pre_registered_bar"))
    assert row["scored"] == receipt["observations_scored"]
    assert row["verdict"] == receipt["verdict"]
    assert row["lower_bound_95"] == pytest.approx(
        receipt["rate_lower_bound_95"], abs=5e-5
    )
