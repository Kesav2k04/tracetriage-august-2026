"""Build grouped splits and emit artifacts/SPLIT_MANIFEST.json and
artifacts/LEAKAGE_AUDIT.json.

Usage:
    .venv/Scripts/python.exe scripts/build_splits.py [--seed 42] [--out-dir artifacts]

The script resolves all input paths from the repository root.  It prints a
summary of the per-split composition and physics-arm evaluability, and exits
with code 1 if any leakage check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Repo root (two levels up from scripts/)
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.splits import (  # noqa: E402
    _A3_SUMMARY_PATH,
    _MANIFEST_PATH,
    ASSERTED_NOT_MEASURABLE_HERE,
    _build_obs_table,
    _default_pages_dir,
    _extract_partition_maps,
    build_leakage_audit,
    build_splits,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build grouped splits for TraceTriage B1.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42).")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO / "artifacts",
        help="Output directory for SPLIT_MANIFEST.json and LEAKAGE_AUDIT.json.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_MANIFEST_PATH,
        help="Path to DATASET_MANIFEST.json.",
    )
    parser.add_argument(
        "--pages-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing raw observation page JSONs. Required, either here or "
            "as TRACETRIAGE_PAGES_DIR. There is no in-tree default: the snapshot is 20 "
            "GB and lives outside the repository, and the old default was one machine's "
            "drive letter, which turned a wrong path into a zero-record run."
        ),
    )
    parser.add_argument(
        "--a3-summary",
        type=Path,
        default=_A3_SUMMARY_PATH,
        help="Path to a3_overlays/summary.json.",
    )
    parser.add_argument(
        "--frozen-at",
        default=None,
        help=(
            "Pin frozen_at to this ISO timestamp instead of now. Use it when "
            "rebuilding the artifact to correct a reported field, so the freeze is "
            "not silently re-dated. rebuilt_at always records the write time, and "
            "the four test_id_digests are what prove the partitions did not move."
        ),
    )
    args = parser.parse_args(argv)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Building splits with seed={args.seed} ...")
    print(f"  Manifest:   {args.manifest}")
    # Resolved once, so the printed path is the path that gets read.
    pages_dir = args.pages_dir or _default_pages_dir()
    print(f"  Pages dir:  {pages_dir}")
    print(f"  A3 summary: {args.a3_summary}")
    if args.frozen_at:
        print(f"  frozen_at:  {args.frozen_at} (pinned, this is a rebuild)")
    print()

    try:
        split_manifest = build_splits(
            seed=args.seed,
            manifest_path=args.manifest,
            pages_dir=pages_dir,
            a3_summary_path=args.a3_summary,
            frozen_at=args.frozen_at,
        )
    except RuntimeError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    # Build the leakage audit (needs rows + partition maps)
    rows = _build_obs_table(args.manifest, pages_dir, args.a3_summary)
    partition_maps = _extract_partition_maps(rows, split_manifest)
    leakage_audit = build_leakage_audit(
        rows,
        partition_maps["chronological"],
        partition_maps["cold_station"],
        partition_maps["cold_transmitter"],
        partition_maps["cold_combined"],
        pages_dir=pages_dir,
    )

    # Emit artifacts
    split_path = out_dir / "SPLIT_MANIFEST.json"
    audit_path = out_dir / "LEAKAGE_AUDIT.json"

    split_path.write_text(json.dumps(split_manifest, indent=2), encoding="utf-8")
    audit_path.write_text(json.dumps(leakage_audit, indent=2), encoding="utf-8")

    print(f"Wrote: {split_path}")
    print(f"Wrote: {audit_path}")
    print()

    # Print composition summary
    print("=" * 70)
    print("PER-SPLIT COMPOSITION")
    print("=" * 70)
    for split_name, comp in split_manifest["composition"].items():
        print(f"\n{split_name.upper()}")
        for part_name, stats in sorted(comp.items()):
            n = stats["n_observations"]
            dec = stats["n_with_signal"] + stats["n_without_signal"]
            unc = stats["n_uncorrected"]
            corr = stats["n_corrected"]
            unres = stats["n_unresolved"]
            phys = "EVALUABLE" if stats["physics_evaluable"] else "NOT EVALUABLE (zero uncorrected)"
            print(
                f"  {part_name:14s}  n={n:5d}  decisive={dec:4d}  "
                f"uncorrected={unc}  corrected={corr}  unresolved={unres}  "
                f"physics={phys}"
            )

    # Physics arm report
    print()
    print("=" * 70)
    print("PHYSICS ARM EVALUABILITY REPORT")
    print("=" * 70)
    zero_splits = [
        r for r in split_manifest["physics_arm_report"] if not r["physics_evaluable"]
    ]
    if zero_splits:
        print(f"WARNING: {len(zero_splits)} partition(s) have zero uncorrected observations:")
        for r in zero_splits:
            print(f"  {r['split']}/{r['partition']}: n_uncorrected=0")
    else:
        print("All partitions have at least one uncorrected observation.")

    # Leakage check summary
    print()
    print("=" * 70)
    print("LEAKAGE CHECKS")
    print("=" * 70)
    # BY_DESIGN is not a pass and not a failure. It is a split that never claimed the
    # guarantee, printed with the crossing count it measured, so the exemption can be
    # weighed rather than trusted.
    # ASSERTED_NOT_MEASURABLE_HERE is the third outcome for the one claim this build
    # cannot measure. It prints as an assertion and carries no counts, because a null
    # formatted as 0 is how an unmeasured claim comes to read as a clean measurement.
    status_for = {
        "PASS": "[PASS]",
        "FAIL": "[FAIL]",
        "BY_DESIGN": "[ n/a ]",
        ASSERTED_NOT_MEASURABLE_HERE: "[asrt]",
    }
    failures = [r for r in leakage_audit if r["result"] == "FAIL"]
    for row in leakage_audit:
        status = status_for[row["result"]]
        if row["n_examined"] is None:
            counts = "asserted, not measured here; bound by the test id digests"
        else:
            counts = f"{row['n_violators']:4d} crossing / {row['n_examined']:5d} examined"
        print(f"  {status} {row['check']:38s} {row['split']:17s} {counts}")
    print()
    if failures:
        print("SOME LEAKAGE CHECKS FAILED — see above.", file=sys.stderr)
        return 1

    # The asserted row is counted separately. Folding it into the claimed total is
    # what made a tally of six of six read as six measurements.
    asserted = [r for r in leakage_audit if r["result"] == ASSERTED_NOT_MEASURABLE_HERE]
    claimed = [
        r
        for r in leakage_audit
        if r["guaranteed"] and r["result"] != ASSERTED_NOT_MEASURABLE_HERE
    ]
    exempt = [r for r in leakage_audit if not r["guaranteed"]]
    print(
        f"All {len(claimed)} measured guarantees hold with zero crossings. "
        f"{len(exempt)} check/split pairs are out of scope by design and report "
        "their measured crossing counts above."
    )
    for row in asserted:
        print(
            f"{row['check']} is asserted and not measured here, so it is not one of "
            f"those {len(claimed)}. What binds it is the digest per frozen test set "
            "in the manifest, which a later evaluation has to quote."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
