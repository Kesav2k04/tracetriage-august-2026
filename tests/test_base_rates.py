"""Check the documented base rates against a corpus that actually exists.

`provenance.py` carries four base-rate constants. The tests that shipped with
them assert things like `0.290 == BASE_RATE_DECISIVE_FRACTION`, which compares
a literal to the constant it was copied from. That passes whatever the corpus
turns out to look like, so it pins the constants to nothing. Nothing else in
the codebase reads them either, which is how they stayed unexamined.

The numbers came from a small recon sample. This module checks them against a
real snapshot when one is on disk, and states the sampling error rather than
demanding an exact match: a base rate estimated from a finite sample has a
confidence interval, and a test that ignores it either fails on noise or
passes on anything.

Set `TRACETRIAGE_SNAPSHOT` to point at a snapshot directory. With no snapshot
present these tests skip, so the offline gate stays hermetic.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

from pipeline.tracetriage.provenance import (
    BASE_RATE_DECISIVE_FRACTION,
    BASE_RATE_NEGATIVE_FRACTION,
    BASE_RATE_POSITIVE_FRACTION,
    BASE_RATE_POSITIVE_TO_NEGATIVE,
)

DECISIVE = ("with-signal", "without-signal")


def _snapshot_manifest() -> dict | None:
    """The manifest of a built snapshot, or None when there is not one."""
    candidates: list[Path] = []
    env = os.environ.get("TRACETRIAGE_SNAPSHOT")
    if env:
        candidates.append(Path(env))
    candidates.append(Path("D:/tracetriage_data/snap-stage1"))
    for base in candidates:
        path = base / "DATASET_MANIFEST.json" if base.is_dir() else base
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return None


@pytest.fixture(scope="module")
def corpus() -> dict:
    manifest = _snapshot_manifest()
    if manifest is None:
        pytest.skip("no snapshot on disk; set TRACETRIAGE_SNAPSHOT to run these")
    obs = manifest.get("observations") or []
    if not obs:
        pytest.skip("snapshot manifest carries no observations")
    statuses = [o.get("waterfall_status") for o in obs]
    positive = statuses.count("with-signal")
    negative = statuses.count("without-signal")
    return {
        "n": len(obs),
        "positive": positive,
        "negative": negative,
        "decisive": positive + negative,
        "snapshot_id": manifest.get("snapshot_id"),
    }


def _wilson_interval(k: int, n: int, z: float = 2.576) -> tuple[float, float]:
    """Wilson score interval for a proportion, at 99% by default.

    Wilson rather than the normal approximation because these proportions sit
    near 0.1 to 0.3 with a few hundred successes, where the normal interval is
    noticeably skewed and would put the bound in the wrong place.
    """
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - margin, centre + margin)


@pytest.mark.dataset
class TestDocumentedBaseRatesHoldOnTheCorpus:
    def test_decisive_fraction_is_consistent_with_the_snapshot(self, corpus):
        lo, hi = _wilson_interval(corpus["decisive"], corpus["n"])
        assert lo <= BASE_RATE_DECISIVE_FRACTION <= hi, (
            f"documented decisive fraction {BASE_RATE_DECISIVE_FRACTION:.3f} is "
            f"outside the 99% interval [{lo:.3f}, {hi:.3f}] measured on "
            f"{corpus['n']} observations "
            f"({corpus['decisive']} decisive, {corpus['decisive']/corpus['n']:.3f}). "
            "Re-measure and update the constant rather than widening this test."
        )

    def test_positive_to_negative_imbalance_is_consistent(self, corpus):
        """Expressed as the positive share of decisive labels, which is what
        has a clean interval; a ratio of two counts does not."""
        decisive = corpus["decisive"]
        if decisive < 100:
            pytest.skip(f"only {decisive} decisive labels; interval too wide to test")
        lo, hi = _wilson_interval(corpus["positive"], decisive)
        documented_share = BASE_RATE_POSITIVE_TO_NEGATIVE / (
            1 + BASE_RATE_POSITIVE_TO_NEGATIVE
        )
        assert lo <= documented_share <= hi, (
            f"documented imbalance {BASE_RATE_POSITIVE_TO_NEGATIVE:.2f}:1 means a "
            f"positive share of {documented_share:.3f}, outside the 99% interval "
            f"[{lo:.3f}, {hi:.3f}] from {corpus['positive']}/{decisive} decisive "
            "labels on this corpus."
        )

    def test_derived_fractions_match_the_measured_split(self, corpus):
        for label, documented, measured in (
            ("positive", BASE_RATE_POSITIVE_FRACTION, corpus["positive"]),
            ("negative", BASE_RATE_NEGATIVE_FRACTION, corpus["negative"]),
        ):
            lo, hi = _wilson_interval(measured, corpus["n"])
            assert lo <= documented <= hi, (
                f"documented {label} fraction {documented:.4f} is outside the 99% "
                f"interval [{lo:.4f}, {hi:.4f}] measured on this corpus"
            )

    def test_unknown_is_the_majority_and_must_not_be_trained_on(self, corpus):
        """The fact that dominates every downstream split.

        Most of the corpus carries no decisive label at all. A loader that
        reads `unknown` as `without-signal` inflates the negative class by
        roughly a factor of nine and produces a model that has learned the
        vetting queue rather than the signal.
        """
        unknown = corpus["n"] - corpus["decisive"]
        assert unknown > corpus["decisive"], (
            "this corpus is unexpectedly mostly labelled; the guidance written "
            "for the unlabelled majority needs rechecking"
        )
        inflation = unknown / max(corpus["negative"], 1)
        assert inflation > 1.0


@pytest.mark.dataset
class TestSnapshotIntegrity:
    def test_no_observation_appears_twice(self, corpus):
        """The resume path appends, so a duplicate id means it double-counted."""
        manifest = _snapshot_manifest()
        ids = [o["id"] for o in manifest["observations"]]
        assert len(ids) == len(set(ids)), (
            f"{len(ids) - len(set(ids))} duplicate observation ids in the manifest"
        )

    def test_stored_waterfalls_have_a_hash_and_missing_ones_do_not(self, corpus):
        manifest = _snapshot_manifest()
        for o in manifest["observations"]:
            has_sha = o.get("waterfall_sha256") is not None
            has_reason = o.get("waterfall_missing_reason") is not None
            assert has_sha != has_reason, (
                f"observation {o['id']} has sha={has_sha} and reason={has_reason}; "
                "exactly one must be set"
            )

    def test_counts_block_agrees_with_the_observation_list(self, corpus):
        manifest = _snapshot_manifest()
        counts = manifest.get("counts") or {}
        obs = manifest["observations"]
        stored = sum(1 for o in obs if o.get("waterfall_missing_reason") is None)
        missing = len(obs) - stored
        assert counts.get("observations_stored") == len(obs)
        assert counts.get("waterfalls_stored") == stored
        assert counts.get("waterfalls_missing") == missing
