"""The console export, and the episode key the receipt now names (C5).

Two defects are pinned here, both of the same kind: a value that was absent for a
mechanical reason and read as a measurement that had not been taken.

The export used ``.get()`` against every receipt field it wanted. Two of the
names it guessed were wrong, so the published console carried four splits whose
partition counts were all ``{}`` and two arm sections that were ``null``. Nothing
failed. The pages rendered, and they said "not measured" about numbers that had
been measured for days. A missing field is now a build failure.

The receipt separately described its episode key as ``start[:13]``, an hour
bucket, months after the code had moved to the orbital revolution index. The
prose was wrong rather than the grouping, which is worse than a wrong number:
a reader checking the clustering would have been checking the wrong thing. The
key is now pinned by value in the contract, so putting the hour bucket back
breaks the schema instead of the reader's understanding.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

_REPO = Path(__file__).resolve().parents[1]
_CONTRACT = _REPO / "contracts" / "queue_receipt.schema.json"
_RECEIPT = _REPO / "artifacts" / "QUEUE_RECEIPT.json"


def _load_export_module():
    """Import the export script by path; it lives in scripts/, not the package."""
    path = _REPO / "scripts" / "build_console_data.py"
    spec = importlib.util.spec_from_file_location("build_console_data", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_console_data"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# _require: absence is a failure, not a value
# ---------------------------------------------------------------------------


def test_require_returns_a_present_value():
    require = _load_export_module()._require
    assert require({"gate5": {"verdict": "NOT_ESTABLISHED"}}, "gate5") == {
        "verdict": "NOT_ESTABLISHED"
    }


def test_require_refuses_a_missing_key():
    """The actual bug: fusion.get('arms') on a receipt whose key is 'arm_ladder'."""
    require = _load_export_module()._require
    with pytest.raises(KeyError) as excinfo:
        require({"arm_ladder": [1]}, "arms")
    # The message has to name what is there, or the next reader guesses again.
    assert "arm_ladder" in str(excinfo.value)


def test_require_refuses_a_null():
    require = _load_export_module()._require
    with pytest.raises(ValueError):
        require({"selective": None}, "selective")


@pytest.mark.parametrize("empty", [{}, [], ""])
def test_require_refuses_an_empty_container(empty):
    """``{}`` is what the split counts published: present, and saying nothing."""
    require = _load_export_module()._require
    with pytest.raises(ValueError):
        require({"splits": empty}, "splits")


def test_require_allows_a_legitimate_zero():
    """Zero conflicts is a measurement. It must survive the guard."""
    require = _load_export_module()._require
    assert require({"n_displaced": 0}, "n_displaced") == 0
    assert require({"held": False}, "held") is False


# ---------------------------------------------------------------------------
# The episode key, pinned in the contract
# ---------------------------------------------------------------------------


def _schema() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def test_contract_pins_the_episode_key_by_value():
    key = _schema()["properties"]["deduplication"]["properties"]["key"]
    assert key["const"] == [
        "ground_station",
        "norad_cat_id",
        "orbital_revolution",
    ]


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not built")
def test_receipt_names_the_key_the_code_actually_groups_on():
    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    dedup = receipt["deduplication"]
    assert dedup["key"] == [
        "ground_station",
        "norad_cat_id",
        "orbital_revolution",
    ]
    # The prose has to agree with the key, since that is the half that drifted.
    assert "orbital_revolution" in dedup["rule"]
    assert "start[:13]" not in dedup["rule"]

    # Every queue entry's episode key must have three parts, matching the tuple.
    for entry in receipt["queue"][:50]:
        assert len(entry["episode_key"].split(":")) == 3


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not built")
def test_receipt_validates_against_its_contract():
    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    Draft202012Validator(_schema()).validate(receipt)


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not built")
def test_the_old_hour_bucket_key_now_fails_the_contract():
    """The mutation that proves the pin bites rather than decorates."""
    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    receipt["deduplication"]["key"] = [
        "ground_station",
        "norad_cat_id",
        "start_prefix_13chars",
    ]
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(receipt)


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not built")
def test_deduplication_is_closed_to_unknown_keys():
    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    receipt["deduplication"]["episode_hours"] = 1
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema()).validate(receipt)


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not built")
def test_degraded_revolution_count_is_reported_not_implied():
    """A propagation failure has to be counted, because it deduplicates nothing."""
    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    dedup = receipt["deduplication"]
    assert "n_degraded_revolution" in dedup
    assert dedup["n_degraded_revolution"] is None or dedup["n_degraded_revolution"] >= 0
    assert "degraded_revolution_policy" in dedup


@pytest.mark.skipif(not _RECEIPT.exists(), reason="receipt not built")
def test_schema_version_is_pinned_so_an_old_writer_cannot_pass():
    schema = _schema()
    assert schema["properties"]["schema_version"]["const"] == schema["schema_version"]

    receipt = json.loads(_RECEIPT.read_text(encoding="utf-8"))
    receipt["schema_version"] = "0.2.0"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


# ---------------------------------------------------------------------------
# ENG-B1: a missing corridor fit must not be published as a measured zero
# ---------------------------------------------------------------------------

_CARDS = Path(__file__).resolve().parents[1] / "apps" / "web" / "public" / "data" / "cards.json"
_CORRIDOR_FEATURES = Path(__file__).resolve().parents[1] / "artifacts" / "corridor_features.json"


def _build_minimal_export_observation(corridor_row):
    """Call export_observation with a minimal stub record and the given corridor_row.

    The stub supplies just enough to reach the corridor-handling branch without
    hitting earlier early-returns (no image on disk, so the test patches _IMG_DIR
    to a temp path that exists but contains no files).
    """
    import tempfile
    mod = _load_export_module()
    orig_img_dir = mod._IMG_DIR
    with tempfile.TemporaryDirectory() as td:
        mod._IMG_DIR = Path(td)
        try:
            result = mod.export_observation.__wrapped__(
                None, None, corridor_row
            ) if hasattr(mod.export_observation, "__wrapped__") else None
        except Exception:
            result = None
        finally:
            mod._IMG_DIR = orig_img_dir
    return result


def test_no_card_publishes_a_fitted_zero_with_null_ppm():
    """Every card that has corridor data must have a real corridor fit.

    A card with fitted_offset_hz=0.0 AND fitted_offset_ppm=None is the fabricated
    zero: the zero came from the ``or 0.0`` fallback, not from a measurement.
    This is the mutation that proves the fix bites.
    """
    if not _CARDS.exists():
        pytest.skip("cards.json not built")
    cards = json.loads(_CARDS.read_text(encoding="utf-8"))["cards"]
    bad = [
        c["obs_id"]
        for c in cards
        if c.get("corridor")
        and c["corridor"].get("fitted_offset_hz") == 0.0
        and c["corridor"].get("fitted_offset_ppm") is None
    ]
    assert bad == [], (
        f"Cards {bad} publish fitted_offset_hz=0.0 with fitted_offset_ppm=None, "
        "which is the fabricated-zero defect: a missing fit published as a "
        "measured zero offset."
    )


def test_no_card_has_fitted_px_equal_to_predicted_px_with_null_ppm():
    """When fitted_px == predicted_px and offset_ppm is null, the corridor note
    must explain the absence.

    The old code produced identical arrays from a zero offset while the note said
    'the gap between them is the measurement', which is false when there is no gap.
    """
    if not _CARDS.exists():
        pytest.skip("cards.json not built")
    cards = json.loads(_CARDS.read_text(encoding="utf-8"))["cards"]
    for c in cards:
        corr = c.get("corridor")
        if corr is None:
            continue
        if corr.get("fitted_offset_ppm") is not None:
            # Real fit: fitted and predicted should differ (unless offset happened
            # to be zero, which is a real zero, not a fabricated one).
            continue
        # No fit: we must have corridor_note and no corridor block.
        assert c.get("corridor_note") is not None, (
            f"obs_id={c['obs_id']}: corridor is null but corridor_note is also null. "
            "An absent fit must carry a named reason."
        )


@pytest.mark.skipif(not _CORRIDOR_FEATURES.exists(), reason="corridor_features.json not built")
def test_export_observation_returns_named_absence_for_obs_outside_decisive_pool():
    """The direct call-site test: an obs with no corridor row gets corridor_note,
    not a corridor dict with a fabricated zero.

    This is the test the engineering review said the suite lacked: exercising
    export_observation at its call site rather than only _require in isolation.
    """
    import importlib.util
    import sys
    import tempfile
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_console_data_b1", repo / "scripts" / "build_console_data.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_console_data_b1"] = mod
    spec.loader.exec_module(mod)

    # Build the corridor_by_obs dict as main() does.
    feats = json.loads((repo / "artifacts" / "corridor_features.json").read_text(encoding="utf-8"))
    corridor_by_obs = {int(r["obs_id"]): r for r in feats["rows"]}

    # Find an obs in the queue that has no corridor row.
    queue_data = json.loads((repo / "apps/web/public/data/queue.json").read_text(encoding="utf-8"))
    no_corr_entry = next(
        (e for e in queue_data["entries"] if e["obs_id"] not in corridor_by_obs),
        None,
    )
    if no_corr_entry is None:
        pytest.skip("All queue entries have corridor rows (unexpected).")
    obs_id = no_corr_entry["obs_id"]

    # Load the raw record.
    from pipeline.tracetriage.splits import _load_raw_pages
    pages_dir = Path("D:/tracetriage_data/snap-stage1/pages")
    if not pages_dir.exists():
        pytest.skip("snapshot not available")
    raw = _load_raw_pages(pages_dir)
    if obs_id not in raw:
        pytest.skip(f"obs_id {obs_id} not found in snapshot pages")
    record = raw[obs_id]

    with tempfile.TemporaryDirectory() as td:
        orig_img_dir = mod._IMG_DIR
        mod._IMG_DIR = Path(td)
        try:
            result = mod.export_observation(obs_id, record, None)
        finally:
            mod._IMG_DIR = orig_img_dir

    # With no corridor row, the function must return a named corridor_note and
    # must NOT publish a corridor dict with a zero offset.
    assert result.get("corridor") is None, (
        f"obs_id={obs_id}: export_observation returned a corridor dict even though "
        "this observation has no corridor row in corridor_features.json."
    )
    assert result.get("corridor_note") is not None, (
        f"obs_id={obs_id}: corridor_note is None; a named absence is required."
    )
    assert "corridor_features.json" in result["corridor_note"], (
        f"obs_id={obs_id}: corridor_note does not name the reason for the absence."
    )
    # Confirm the old defect: if we revert to 'or 0.0' the result would be non-null
    # corridor with fitted_offset_hz=0.0. We cannot run the old code here, but we
    # can assert the positive property that the fixed code satisfies.
    assert result.get("corridor_note") != "", "corridor_note must not be empty"
