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
