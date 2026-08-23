"""The comparison arm, and the sensitivity table, neither of which any test read.

`docs/REFERENCE.md` prints **none** in the tests column for an artifact nothing reads, and
it printed it for `artifacts/GATE3_POOL_A_RECEIPT.json` and
`artifacts/GATE3_SENSITIVITY.json`. Both are shipped, both are cited in
`docs/CLAIM_REGISTER.md`, and both carry the numbers that make the pre-registration mean
anything.

Pool A is the arm that would have passed. `docs/E16_PREREGISTRATION.md` section 5 commits
to publishing it beside pool B precisely because the difference between them is the size of
the selection effect: pool A is chosen on `sigma_curved - sigma_vertical >= 3.0`, which is a
corridor result, and pool B is chosen without ever fitting a corridor. An arm that quietly
became the published one, or a comparison that stopped being generated, is the single most
valuable thing an unscrupulous version of this project could do, so it is the thing worth
testing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
POOL_B = REPO / "artifacts" / "GATE3_RECEIPT.json"
POOL_A = REPO / "artifacts" / "GATE3_POOL_A_RECEIPT.json"
SENSITIVITY = REPO / "artifacts" / "GATE3_SENSITIVITY.json"
KILL_GATE = REPO / "docs" / "KILL_GATE.md"

needs_both = pytest.mark.skipif(
    not (POOL_A.exists() and POOL_B.exists()),
    reason="both gate 3 arms have not been scored",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@needs_both
def test_the_two_arms_are_the_two_pools_the_preregistration_named():
    """Neither receipt may quietly be the other's pool."""
    assert _load(POOL_B)["pool"]["name"] == "pool_b"
    assert _load(POOL_A)["pool"]["name"] == "pool_a"


@needs_both
def test_only_pool_b_decides_the_gate():
    """The published verdict comes from the corridor-free pool, whatever pool A says.

    Pool A clears the bar on this corpus, over observations and over episodes. If the
    receipts ever stopped saying which one decides, the honest reading and the flattering
    one would be indistinguishable from the artifacts alone.
    """
    assert _load(POOL_B)["pool"]["decides_the_gate"] is True
    assert _load(POOL_A)["pool"]["decides_the_gate"] is False


@needs_both
def test_the_deciding_arm_is_the_one_selected_without_a_corridor():
    """`decides_the_gate` has to sit on the arm whose rule reads no corridor.

    Asserting the flag alone would pass if the flags were swapped. The rule text is the
    independent statement of which pool is which, and `tests/test_gate3_pool.py` checks
    the rule against the source by AST.
    """
    rule = _load(POOL_B)["pool"]["rule"].lower()
    assert "no doppler prediction" in rule
    for forbidden in ("sigma_curved", "sigma_curved_by_sign", "curved_offset_hz"):
        assert forbidden not in rule, (
            f"the deciding pool's rule mentions {forbidden}, which is a corridor result"
        )


@needs_both
def test_the_selection_effect_is_reported_and_is_not_zero():
    """The number E16 exists to produce.

    A corridor-selected pool and a corridor-free one measuring the same rate would mean
    the circularity concern was unfounded, which would be a finding. They do not, and the
    gap is what the pre-registration promised to publish.
    """
    a, b = _load(POOL_A), _load(POOL_B)
    gap = a["discriminating_rate"] - b["discriminating_rate"]
    assert gap > 0.05, (
        f"the corridor-selected pool measures {a['discriminating_rate']:.4f} and the "
        f"corridor-free one {b['discriminating_rate']:.4f}, a gap of {gap:.4f}. If that "
        "has collapsed, the selection effect is no longer what E16 reported and the "
        "claim register row needs remeasuring rather than this threshold moving."
    )


@needs_both
def test_the_kill_gate_page_publishes_both_arms():
    """Publishing only the arm that decides would leave the comparison unanswerable."""
    text = KILL_GATE.read_text(encoding="utf-8")
    a, b = _load(POOL_A), _load(POOL_B)
    for receipt, label in ((a, "pool A"), (b, "pool B")):
        rate = f"{receipt['discriminating_rate'] * 100:.0f}%"
        assert rate in text, f"{label}'s rate {rate} does not appear in docs/KILL_GATE.md"
    assert a["verdict"] in text, "pool A's verdict is not published beside pool B's"


# ---------------------------------------------------------------------------
# The sensitivity table.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (SENSITIVITY.exists() and POOL_B.exists()),
    reason="the sensitivity sweep has not been run",
)
def test_the_shipped_sensitivity_file_agrees_with_the_shipped_receipt():
    """The committed artifact, not a recomputation of it.

    `tests/test_gate3_sensitivity.py` recomputes the table from the receipt and compares.
    That checks the function. This checks the file on disk, which is what a reader opens
    and what `docs/CLAIM_REGISTER.md` cites, and which a stale run would leave behind.
    """
    s, b = _load(SENSITIVITY), _load(POOL_B)
    assert s["published_verdict"] == b["verdict"]
    assert s["threshold"] == b["threshold"]
    assert s["scored_at_bar"] == b["pool"]["trace_q75_min"]

    row = next(r for r in s["rows"] if r.get("is_the_pre_registered_bar"))
    assert row["scored"] == b["observations_scored"]
    assert row["verdict"] == b["verdict"]
    assert row["lower_bound_95"] == pytest.approx(b["rate_lower_bound_95"], abs=5e-5)
    assert row["groups"] == b["entity_grouping"]["groups_scored"]


@pytest.mark.skipif(not SENSITIVITY.exists(), reason="the sensitivity sweep has not run")
def test_a_bar_below_the_scored_one_is_never_given_a_rate_on_disk():
    """A looser bar selects observations this run never scored.

    Reporting a rate over only the ones it happens to have is a rate over a biased subset
    of that pool, and it is the row a sceptical reader would most want to trust.
    """
    s = _load(SENSITIVITY)
    below = [r for r in s["rows"] if r["trace_q75_min"] < s["scored_at_bar"]]
    assert below, "the sweep no longer covers a bar below the one that was scored"
    for row in below:
        assert row["rate"] is None
        assert row["lower_bound_95"] is None
        assert row["verdict"] == "NOT SCORED"


@pytest.mark.skipif(not SENSITIVITY.exists(), reason="the sensitivity sweep has not run")
def test_the_rate_is_stable_even_where_the_verdict_is_not():
    """What the sweep is for: separating a moving measurement from a shrinking sample.

    The verdict changes at a tighter bar. Whether that means the finding is fragile or
    only that the interval widened on fewer observations is the question, and the rate
    across the measured bars answers it.
    """
    s = _load(SENSITIVITY)
    rates = [r["rate"] for r in s["rows"] if r["rate"] is not None]
    counts = [r["scored"] for r in s["rows"] if r["scored"] is not None]
    assert len(rates) >= 4, "too few measured bars to say anything about stability"
    assert max(rates) - min(rates) < 0.15, (
        f"the discriminating rate moves from {min(rates):.3f} to {max(rates):.3f} across "
        "the sweep, so a verdict that changes with the bar can no longer be attributed "
        "to sample size alone and the published reading needs revisiting"
    )
    assert counts == sorted(counts, reverse=True), (
        f"scored counts {counts} are not monotone decreasing in the bar, so the rows are "
        "not nested subsets and the comparison across them is not exact"
    )
