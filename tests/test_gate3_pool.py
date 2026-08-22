"""The gate 3 pool builder, and the one property the whole unit rests on.

``docs/E16_PREREGISTRATION.md`` says pool B is selected without reading the corridor's fit
to the image. That is the claim that makes a larger n worth having: A3's ``UNCORRECTED``
label is ``sigma_curved - sigma_vertical >= 3.0``, so building the testable pool from it
and then asking whether the corridor discriminates measures the selection as much as the
ranker.

A sentence in a document cannot enforce that. The test below reads the source of the
membership expression and fails if ``sigma_curved`` appears anywhere in it, so the
independence is a property of the code rather than of the prose describing the code.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
BUILDER = REPO / "scripts" / "build_gate3_pool.py"
RUNNER = REPO / "scripts" / "run_gate3.py"
POOL = REPO / "artifacts" / "GATE3_POOL.json"
PREREG = REPO / "docs" / "E16_PREREGISTRATION.md"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def builder():
    return _load(BUILDER, "build_gate3_pool")


@pytest.fixture(scope="module")
def runner():
    return _load(RUNNER, "run_gate3")


# --------------------------------------------------------------------------------------
# The independence claim, enforced against the source rather than described.
# --------------------------------------------------------------------------------------


def test_pool_b_membership_never_reads_the_corridor_fit(builder):
    """The property `docs/E16_PREREGISTRATION.md` section 3 is built on.

    Read off ``in_pool_b``'s own AST rather than off prose or a substring search: the
    module computes ``sigma_curved`` a few lines away for pool A, so grepping the file
    would fail for the wrong reason, and grepping the rule would pass the moment someone
    renamed a variable.
    """
    tree = ast.parse(inspect.getsource(builder.in_pool_b))
    names = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    } | {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    forbidden = {"sigma_curved", "sigma_curved_by_sign", "curved_offset_hz", "verdict"}
    assert not (names & forbidden), (
        f"pool_b's membership reads {sorted(names & forbidden)}, which is the corridor's "
        "own fit. That makes the pool corridor-selected and the rate partly a measurement "
        "of the selection, which is the thing E16 exists to avoid."
    )


def test_examine_delegates_pool_b_to_that_rule_and_computes_it_nowhere_else(builder):
    """Otherwise the test above guards a function nothing calls."""
    source = inspect.getsource(builder.examine)
    assert 'record["pool_b"] = in_pool_b(record, trace_q75_min)' in source
    tree = ast.parse(inspect.getsource(builder))
    # `<name>["pool_b"] = ...` only. The first version of this matched any subscript
    # ending in "pool_b" and so caught `payload["counts"]["pool_b"] = after`, which is a
    # tally and not a membership, and failed on it.
    assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Subscript)
            and isinstance(t.value, ast.Name)
            and isinstance(t.slice, ast.Constant)
            and t.slice.value == "pool_b"
            for t in node.targets
        )
    ]
    assert len(assigns) == 2, (
        f"expected pool_b to be assigned in examine and in _recut, found {len(assigns)}"
    )
    for node in assigns:
        called = {
            n.func.id
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "in_pool_b" in called, (
            "a pool_b assignment in this module does not go through in_pool_b, so the "
            f"independence check does not cover it (line {node.lineno})"
        )


def test_the_rule_is_a_pure_function_of_the_three_statistics(builder):
    """It has to be, or --recut would disagree with the run it recuts."""
    ok = {"predicted_swing_hz": 20000.0, "trace_q75": 5.0, "sigma_vertical": 2.0}
    assert builder.in_pool_b(ok) is True
    assert builder.in_pool_b(ok | {"predicted_swing_hz": 100.0}) is False
    assert builder.in_pool_b(ok | {"trace_q75": 1.0}) is False
    assert builder.in_pool_b(ok | {"sigma_vertical": 40.0}) is False
    # A record that could not be measured is not silently admitted.
    assert builder.in_pool_b({}) is False
    # And it moves with the bar, which is what the sensitivity table needs.
    assert builder.in_pool_b(ok, trace_q75_min=6.0) is False


def test_recut_moves_pool_b_and_leaves_pool_a_alone(builder, tmp_path):
    """Pool A is A3's label. A recut that touched it would make the pools move together."""
    path = tmp_path / "GATE3_POOL.json"
    rows = [
        {"obs_id": 1, "status": "ok", "predicted_swing_hz": 20000.0,
         "trace_q75": 4.0, "sigma_vertical": 2.0, "pool_a": True, "pool_b": True},
        {"obs_id": 2, "status": "ok", "predicted_swing_hz": 20000.0,
         "trace_q75": 8.0, "sigma_vertical": 2.0, "pool_a": False, "pool_b": True},
        {"obs_id": 3, "status": "no_waterfall", "pool_a": False, "pool_b": False},
    ]
    path.write_text(
        json.dumps({"trace_q75_min": 3.5, "counts": {"pool_a": 1, "pool_b": 2},
                    "observations": rows}),
        encoding="utf-8",
    )
    builder._recut(path, 6.0)

    payload = json.loads(path.read_text(encoding="utf-8"))
    got = payload["observations"]
    assert [r["pool_b"] for r in got] == [False, True, False]
    assert [r["pool_a"] for r in got] == [True, False, False]
    assert payload["counts"]["pool_b"] == 1
    assert payload["trace_q75_min"] == 6.0


def test_pool_a_does_read_the_corridor_fit_so_the_two_are_not_the_same_rule(builder):
    """The contrast, asserted so a refactor cannot quietly make both pools identical."""
    source = inspect.getsource(builder.examine)
    assert 'record["pool_a"] = verdict == "UNCORRECTED"' in source, (
        "pool A is no longer A3's label, so it is no longer the comparable pool the "
        "pre-registration says it is"
    )


# --------------------------------------------------------------------------------------
# The presence statistic.
# --------------------------------------------------------------------------------------


def test_trace_presence_rises_with_a_planted_trace(builder):
    """A detector that returns the same number for noise and for a signal detects nothing."""
    rng = np.random.default_rng(0)
    noise = rng.normal(size=(200, 600))
    quiet = builder.trace_presence(noise)

    planted = noise.copy()
    for row in range(200):
        planted[row, 100 + row] = 12.0
    loud = builder.trace_presence(planted)

    assert loud["trace_q75"] > quiet["trace_q75"] + 5.0
    assert quiet["n_rows"] == loud["n_rows"] == 200


def test_one_bright_row_does_not_admit_an_observation(builder):
    """Why the statistic is a percentile and not the maximum.

    Interference in a handful of rows is not a trace. The maximum cannot tell the two
    apart and the 75th percentile can, which is the whole reason for the choice.
    """
    rng = np.random.default_rng(1)
    zs = rng.normal(size=(200, 600))
    zs[3:8, 250] = 40.0

    stats = builder.trace_presence(zs)
    assert stats["trace_max"] > 30.0
    assert stats["trace_q75"] < builder.TRACE_Q75_MIN, (
        "five bright rows out of 200 cleared the presence bar, so the bar is reading "
        "the maximum in all but name"
    )


def test_the_presence_bar_sits_above_what_noise_produces(builder):
    """The number in the pre-registration, checked against simulated noise.

    ``TRACE_Q75_MIN`` was set at 3.5 after 6.0 was measured to be wrong. This fails if a
    later edit drops it into the range pure noise reaches at these image widths.
    """
    rng = np.random.default_rng(2)
    ceiling = max(
        builder.trace_presence(rng.normal(size=(200, 600)))["trace_q75"] for _ in range(20)
    )
    assert ceiling < builder.TRACE_Q75_MIN, (
        f"the bar is {builder.TRACE_Q75_MIN} and noise alone reaches {ceiling:.2f}"
    )


# --------------------------------------------------------------------------------------
# The selector the gate runner uses.
# --------------------------------------------------------------------------------------


def test_a_bare_list_is_still_read_as_the_a3_summary(runner, tmp_path):
    """The default path, unchanged, so the committed receipt is reproducible."""
    path = tmp_path / "summary.json"
    path.write_text(
        json.dumps([
            {"obs_id": 1, "verdict": "UNCORRECTED"},
            {"obs_id": 2, "verdict": "CORRECTED"},
            {"obs_id": 3, "verdict": "UNRESOLVED"},
        ]),
        encoding="utf-8",
    )
    rows, meta = runner._select_pool(path, "a3")
    assert [r["obs_id"] for r in rows] == [1, 2]
    assert meta["decides_the_gate"] is True
    assert meta["pre_registration"] is None


def test_a_pool_file_selects_on_the_membership_flag_not_the_verdict(runner, tmp_path):
    """The point of the flag: an UNRESOLVED observation can be a pool B member.

    A3's verdict word says whether the corridor beat a vertical line. Pool B's question
    is whether a trace is visible at all, so the two disagree by design and a selector
    that fell back to the verdict would silently rebuild pool A.
    """
    path = tmp_path / "GATE3_POOL.json"
    path.write_text(
        json.dumps({
            "trace_q75_min": 3.5,
            "counts": {"pool_b": 2},
            "selection": {"pool_b": "the corridor-free rule"},
            "observations": [
                {"obs_id": 1, "verdict": "UNRESOLVED", "pool_a": False, "pool_b": True},
                {"obs_id": 2, "verdict": "UNCORRECTED", "pool_a": True, "pool_b": True},
                {"obs_id": 3, "verdict": "CORRECTED", "pool_a": False, "pool_b": False},
            ],
        }),
        encoding="utf-8",
    )
    rows, meta = runner._select_pool(path, "pool_b")
    assert [r["obs_id"] for r in rows] == [1, 2]
    assert meta["rule"] == "the corridor-free rule"
    assert meta["trace_q75_min"] == 3.5
    assert meta["n_examined"] == 3

    rows_a, meta_a = runner._select_pool(path, "pool_a")
    assert [r["obs_id"] for r in rows_a] == [2]
    assert meta_a["decides_the_gate"] is False, (
        "pool A is corridor-selected, so a receipt built from it must not present itself "
        "as the gate"
    )


def test_asking_for_a_pool_the_file_does_not_carry_stops_the_run(runner, tmp_path):
    """Silently selecting nothing would publish a gate over an empty sample."""
    path = tmp_path / "summary.json"
    path.write_text(json.dumps([{"obs_id": 1, "verdict": "UNCORRECTED"}]), encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        runner._select_pool(path, "pool_b")
    assert "build_gate3_pool.py" in str(caught.value)


# --------------------------------------------------------------------------------------
# The pre-registration, and the committed pool if there is one.
# --------------------------------------------------------------------------------------


def test_the_pre_registration_names_the_thresholds_the_code_uses(builder):
    """A pre-registration that drifts from the code it constrains constrains nothing."""
    text = PREREG.read_text(encoding="utf-8")
    assert str(builder.TRACE_Q75_MIN) in text or "TRACE_Q75_MIN" in text
    for phrase in (
        "Pool B decides the gate",
        "0.70",
        "5.0 null standard deviations",
        "recorded as failed",
    ):
        assert phrase in text, f"the pre-registration no longer says: {phrase}"


def test_the_pre_registration_predates_the_gate_receipt_in_git():
    """The claim on its first line, checked against history rather than trusted.

    A pre-registration written after the result is a report. This compares the commit
    that added the document against the commit that last changed the gate 3 receipt, and
    only runs where both are committed.
    """
    def committed_at(path: str, first: bool) -> str | None:
        args = ["git", "log", "--format=%ct", "--", path]
        if first:
            args.insert(2, "--diff-filter=A")
        done = subprocess.run(args, cwd=REPO, capture_output=True, text=True, check=False)
        stamps = [line for line in done.stdout.split() if line]
        if not stamps:
            return None
        return stamps[-1] if first else stamps[0]

    prereg = committed_at("docs/E16_PREREGISTRATION.md", first=True)
    if prereg is None:
        pytest.skip("the pre-registration is not committed yet")
    receipt = committed_at("artifacts/GATE3_RECEIPT.json", first=False)
    if receipt is None:
        pytest.skip("no committed gate 3 receipt to compare against")

    # Only meaningful once the receipt has been rebuilt from a pool. Before that the
    # receipt predates the document legitimately, because it is the n = 3 result.
    if not POOL.exists():
        pytest.skip("no pool has been built, so the receipt is still the n = 3 run")
    assert int(prereg) <= int(receipt), (
        "docs/E16_PREREGISTRATION.md was committed after the gate 3 receipt it is "
        "supposed to constrain, so it is a report and not a pre-registration"
    )


def test_the_committed_pool_records_every_observation_it_examined():
    """The denominator is a claim too. A pool that drops its refusals cannot be audited."""
    if not POOL.exists():
        pytest.skip("no pool has been built in this checkout")
    payload = json.loads(POOL.read_text(encoding="utf-8"))
    rows = payload["observations"]
    assert payload["counts"]["examined"] == len(rows)
    assert sum(payload["counts"]["by_status"].values()) == len(rows)
    assert payload["counts"]["pool_b"] == sum(1 for r in rows if r.get("pool_b"))
    assert payload["counts"]["pool_a"] == sum(1 for r in rows if r.get("pool_a"))
    for row in rows:
        assert "status" in row, row.get("obs_id")
        if row["status"] == "ok":
            assert "trace_q75" in row, (
                f"obs {row['obs_id']} was measurable and carries no presence statistic, "
                "so the pool cannot be recut at another threshold from this file"
            )
