"""Regression tests for snapshot isolation and the verification mode.

Three defects found by actually running unit A1 against the live API, all fixed
during A1 hardening and pinned here.

1. The manifest was written to, resumed from, and verified against one global
   path (`artifacts/DATASET_MANIFEST.json`) regardless of `--out`. The plan runs
   stage 2 in the background during Wave B while stage 1 is in use, so a second
   snapshot would have loaded the first one's observations as its own resume
   state and emitted a manifest describing files in a directory it does not name.
2. `--target-waterfalls` defaulted to 2300, so omitting it silently began a
   production-scale crawl against a volunteer-run public API.
3. `--verify` ran *after* a full fetch rather than instead of one, so an existing
   snapshot could not be checked without re-crawling. Together with defect 2 a
   bare `--verify` pulled 578 observations and 870 MB before interruption.

None of these tests is marked `network`. That matters more than it looks, because
`conftest.py` blocks socket access in any unmarked test, so a code path that
quietly tried to reach SatNOGS would fail here instead of succeeding in silence
and leaving somebody else's volunteer-run server to absorb the difference. The
socket block is the assertion. The test bodies just aim it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.tracetriage import snapshot


def write_manifest(path: Path, observations: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"observations": observations}), encoding="utf-8")


def test_fetch_mode_requires_end_and_target(tmp_path: Path) -> None:
    """Neither bound may be assumed. A default is how an accidental
    production-scale crawl against somebody else's volunteer-run infrastructure
    begins, quietly, from a command that looked harmless."""
    with pytest.raises(SystemExit) as exc:
        snapshot.main(["--out", str(tmp_path)])
    assert "--end and --target-waterfalls are required" in str(exc.value)


def test_target_waterfalls_has_no_default(tmp_path: Path) -> None:
    args = snapshot._parse_args(["--out", str(tmp_path), "--verify"])
    assert args.target_waterfalls is None
    assert args.end is None


def test_verify_needs_no_end_or_target(tmp_path: Path) -> None:
    """Verification fetches nothing. Demanding a date bound and a target count
    from a command that will not make a single request is how a person ends up
    supplying plausible-looking values and starting the very crawl they were
    trying to avoid."""
    out = tmp_path / "snapA"
    (out / "waterfalls").mkdir(parents=True)
    write_manifest(out / "DATASET_MANIFEST.json", [])
    snapshot.main(["--out", str(out), "--verify"])


def test_verify_reads_the_manifest_from_out_dir(tmp_path: Path) -> None:
    out = tmp_path / "snapA"
    (out / "waterfalls").mkdir(parents=True)
    write_manifest(out / "DATASET_MANIFEST.json", [])
    snapshot.main(["--out", str(out), "--verify"])


def test_verify_does_not_fall_back_to_the_global_artifacts_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression that matters most, because it is silent when it fires: a
    manifest sitting at the old global path must never be used to verify a
    snapshot directory it does not describe. Wrong answers, no error."""
    artifacts = tmp_path / "artifacts"
    write_manifest(artifacts / "DATASET_MANIFEST.json", [{"id": 1, "waterfall_sha256": "0" * 64}])
    monkeypatch.setattr(snapshot, "ARTIFACTS_DIR", artifacts)

    out = tmp_path / "snapB"
    (out / "waterfalls").mkdir(parents=True)

    with pytest.raises(SystemExit) as exc:
        snapshot.main(["--out", str(out), "--verify"])
    assert "nothing to verify" in str(exc.value)


def test_two_snapshots_do_not_share_a_manifest(tmp_path: Path) -> None:
    """Stage 1 and stage 2 coexist. Each carries its own resume index."""
    a = tmp_path / "stage1"
    b = tmp_path / "stage2"
    for d in (a, b):
        (d / "waterfalls").mkdir(parents=True)

    write_manifest(a / "DATASET_MANIFEST.json", [])

    assert (a / "DATASET_MANIFEST.json").exists()
    assert not (b / "DATASET_MANIFEST.json").exists()

    with pytest.raises(SystemExit) as exc:
        snapshot.main(["--out", str(b), "--verify"])
    assert "nothing to verify" in str(exc.value)
