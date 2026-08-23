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


class _Box:
    """The two attributes `_normalised_rows` reads off a crop box."""

    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    def width(self):
        return self.x1 - self.x0


def _image(rows, cols, rng):
    """A uint8 RGB image of gaussian noise, which is what the builder is handed."""
    lum = np.clip(rng.normal(loc=110.0, scale=18.0, size=(rows, cols)), 0, 255)
    return np.repeat(lum[:, :, None].astype(np.uint8), 3, axis=2)


def test_a_flat_row_is_not_the_strongest_evidence_in_the_image(builder):
    """The defect that cost a whole pool build, tested from the pixels.

    `_normalised_rows` divided by `np.maximum(mad, 1e-6)`. A row with no variation has
    MAD exactly 0, so the floor turned the emptiest row in an image into z of order 1e8
    and put it above every real trace. Measured on the first full build, pool B's 75th
    percentile reached 22,666,664 against a real matched-filter detection at 25.

    A z-score matrix cannot reach this, because the bug is in how the matrix is made.
    This starts from an image and plants the degenerate rows in it.
    """
    rng = np.random.default_rng(11)
    rgb = _image(240, 600, rng)
    rgb[80:160, :, :] = 200  # a third of the pass, perfectly flat

    zs, measurable = builder._normalised_rows(rgb, _Box(0, 0, 600, 240))
    assert measurable.sum() == 236 - 80, (
        "the flat block should be the only unmeasurable part of this image"
    )

    stats = builder.trace_presence(zs, measurable)
    assert stats["trace_q75"] < builder.TRACE_Q75_MIN, (
        f"80 flat rows produced trace_q75 {stats['trace_q75']:.3g} on an image with no "
        "trace in it, so a blank waterfall would enter the pool ahead of a real one"
    )
    assert stats["n_rows_unmeasurable"] == 80
    assert stats["n_rows"] == 156, "the flat rows are still in the percentile"


def test_an_image_with_nothing_in_it_refuses_the_statistic(builder):
    """No measurable row is not a low score. It is no measurement.

    Returning 0.0 here would be a number that reads as "checked, no trace", and this
    pool's rule keys on the statistic being absent, not small.
    """
    rgb = np.full((120, 400, 3), 17, dtype=np.uint8)
    zs, measurable = builder._normalised_rows(rgb, _Box(0, 0, 400, 120))
    assert not measurable.any()
    assert builder.trace_presence(zs, measurable) is None


def test_a_flat_image_cannot_enter_the_pool(builder):
    """The membership rule's side of the same defect."""
    assert not builder.in_pool_b(
        {
            "predicted_swing_hz": 50_000.0,
            "trace_q75": None,
            "sigma_vertical": 0.1,
        }
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

    # Only meaningful once the receipt itself came from a pre-registered pool. This used
    # to key on whether a pool file existed in the working tree, which is a proxy for the
    # wrong thing: building a pool opened the guard while the committed receipt was still
    # the n = 3 run, so the test failed for the one reason that is not a defect. The
    # receipt records which pool produced it, and that is the question being asked.
    receipt_path = REPO / "artifacts" / "GATE3_RECEIPT.json"
    pool_name = None
    if receipt_path.exists():
        pool_name = (
            json.loads(receipt_path.read_text(encoding="utf-8")).get("pool") or {}
        ).get("name")
    if pool_name in (None, "a3"):
        pytest.skip(
            "the committed receipt is the n = 3 A3 run, which predates the document "
            "legitimately"
        )
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
    # Every row that could enter the pool at some other threshold has to carry the
    # statistic the threshold reads, or the file cannot be recut from itself. That is
    # every row whose image was read and measured, and no others: an observation ruled
    # out by the swing floor is out at every threshold, and one whose crop has no row
    # with any spread has no statistic to record.
    recuttable = {"ok"}
    for row in rows:
        assert "status" in row, row.get("obs_id")
        if row["status"] in recuttable:
            assert "trace_q75" in row, (
                f"obs {row['obs_id']} was measured and carries no presence statistic, "
                "so the pool cannot be recut at another threshold from this file"
            )
            assert row["trace_q75"] < 1e4, (
                f"obs {row['obs_id']} reports trace_q75 {row['trace_q75']:.3g}. A z-score "
                "that large is a divisor collapsing, not a trace: see MIN_ROW_MAD in "
                "scripts/build_gate3_pool.py for the run where flat rows outscored a real "
                "detection by six orders of magnitude"
            )
        else:
            assert "trace_q75" not in row, (
                f"obs {row['obs_id']} has status {row['status']!r} and a presence "
                "statistic, so one of the two is wrong about whether it was measured"
            )


def test_the_receipt_was_scored_against_the_pool_that_is_committed():
    """The selection story and the numbers have to come from one population.

    `_select_pool` copies the pool file's counts into the receipt. Nothing compared them
    back to the file, so a pool rebuilt after the run, or a receipt carried over from a
    different build, would leave every generated surface describing a selection that did
    not produce the rate beside it.

    The counts stand in for a digest, which would have needed the scoring run repeated to
    add. A pool differing in any observation almost certainly differs in one of these.
    """
    receipt_path = REPO / "artifacts" / "GATE3_RECEIPT.json"
    if not (receipt_path.exists() and POOL.exists()):
        pytest.skip("no receipt or no pool in this checkout")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    meta = receipt.get("pool")
    if not meta or meta.get("name") not in ("pool_a", "pool_b"):
        pytest.skip("the committed receipt predates the pre-registered pools")

    pool = json.loads(POOL.read_text(encoding="utf-8"))
    assert meta["source"].endswith("GATE3_POOL.json"), meta["source"]
    assert meta["n_examined"] == len(pool["observations"]), (
        "the receipt was scored against a pool with a different number of observations "
        "than the one committed here"
    )
    assert meta["n_selected"] == sum(
        1 for r in pool["observations"] if r.get(meta["name"])
    ), (
        f"the receipt selected {meta['n_selected']} observations and the committed pool "
        f"flags a different number as {meta['name']}"
    )
    assert meta.get("pool_counts") == pool["counts"], (
        "the counts the receipt carries are not the counts in the committed pool file"
    )
    assert meta.get("trace_q75_min") == pool["trace_q75_min"], (
        "the receipt and the pool disagree about the presence bar that selected it"
    )


def test_the_receipt_scored_every_observation_its_pool_selected():
    """A silent drop between selection and scoring changes the denominator.

    `run_gate3.py` skips an observation whose waterfall is missing or whose geometry is
    degraded, and each skip is a warning nobody reads. If the scored count can fall below
    the selected count without anything saying so, the published rate is over a subset
    chosen by whatever happened to fail, which is not the pre-registered pool.
    """
    receipt_path = REPO / "artifacts" / "GATE3_RECEIPT.json"
    if not receipt_path.exists():
        pytest.skip("no receipt in this checkout")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    meta = receipt.get("pool")
    if not meta or meta.get("name") not in ("pool_a", "pool_b"):
        pytest.skip("the committed receipt predates the pre-registered pools")

    selected = meta["n_selected"]
    reported = len(receipt["observations"])
    assert reported == selected, (
        f"the pool selected {selected} observations and the receipt reports {reported}. "
        "Every selected observation has to appear, including the ones that could not be "
        "scored, or the denominator is decided by which images happened to fail."
    )


def test_the_pool_is_enumerated_from_the_manifest_not_from_the_pages(builder, tmp_path):
    """The denominator is the stored dataset, and a page row the dataset dropped is not in it.

    The ingest fetched whole cursor pages and stopped at its waterfall target part-way
    through the last one, which had already been written complete. So `pages/*.json` holds
    rows the snapshot never stored, and enumerating the pages counted 23 of them into
    `counts.examined`, into `pool.n_examined` in the gate receipt, and into the sentence
    "the pools are drawn from 2,750 observations, the whole snapshot" in
    `docs/KILL_GATE.md`, beside a receipt printing 2,727 for the same corpus.

    The fixture below is the same shape at three rows instead of 2,750.
    """
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "page_00000.json").write_text(
        json.dumps([{"id": 11, "start": "a"}, {"id": 12, "start": "b"}]),
        encoding="utf-8",
    )
    (pages / "page_00001.json").write_text(
        json.dumps([{"id": 13, "start": "c"}]), encoding="utf-8"
    )
    manifest = tmp_path / "DATASET_MANIFEST.json"
    manifest.write_text(
        json.dumps({"observations": [{"id": 11}, {"id": 12}]}), encoding="utf-8"
    )

    rows = builder.load_snapshot(tmp_path, manifest)
    assert [r["id"] for r in rows] == [11, 12], (
        "observation 13 is on disk and is not in the manifest, so it is not part of the "
        "dataset and must not reach the pool's denominator"
    )


def test_a_manifest_id_with_no_page_row_stops_the_run(builder, tmp_path):
    """A short enumeration is a broken snapshot, not a smaller corpus.

    `run_precedent_study._load_snapshot` refuses on the same condition for the same
    reason: a pool quietly built over fewer observations than the manifest freezes is not
    comparable with any other number in the repository, and the difference is small enough
    to go unnoticed.
    """
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "page_00000.json").write_text(json.dumps([{"id": 11}]), encoding="utf-8")
    manifest = tmp_path / "DATASET_MANIFEST.json"
    manifest.write_text(
        json.dumps({"observations": [{"id": 11}, {"id": 99}]}), encoding="utf-8"
    )

    with pytest.raises(SystemExit) as caught:
        builder.load_snapshot(tmp_path, manifest)
    assert "would not be the corpus" in str(caught.value)


def test_the_committed_pool_examined_the_stored_dataset_and_nothing_else():
    """The artifact, against the manifest that froze the corpus.

    Two published denominators differing by 23 is what this pins. `counts.examined` must be
    the manifest's `observations_stored`, and every stored observation without a waterfall
    on disk must be counted as `no_waterfall`, which is the manifest's own
    `waterfalls_missing`.
    """
    if not POOL.exists():
        pytest.skip("no pool in this checkout")
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    manifest_path = REPO / "artifacts" / "DATASET_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    stored = manifest["counts"]["observations_stored"]
    assert pool["counts"]["examined"] == stored, (
        f"the pool examined {pool['counts']['examined']} observations and the manifest "
        f"stores {stored}. One corpus, one denominator."
    )
    assert len(pool["observations"]) == stored
    ids = {int(r["obs_id"]) for r in pool["observations"]}
    assert ids == {int(o["id"]) for o in manifest["observations"]}
    assert pool["counts"]["by_status"]["no_waterfall"] == manifest["counts"][
        "waterfalls_missing"
    ], (
        "a stored observation with no waterfall on disk is exactly the manifest's "
        "waterfalls_missing, so these two counts cannot disagree"
    )
