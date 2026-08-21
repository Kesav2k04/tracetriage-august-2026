"""Cache HOG feature vectors for the decisive corpus.

The image arm costs 3.9 seconds per observation, almost all of it the geometry parse
that finds the crop box. The fusion head needs out-of-fold image scores, which means
fitting the image model once per fold, so an uncached extraction would pay that cost
five times over. Cached once, the ablations in B6 are free.

The crop matters and is not an optimisation. Unit A6 measured that HOG over the full
PNG predicts which of the six busiest ground stations produced an observation at 70.5%
accuracy against a 24.6% majority baseline: the axes, title and colorbar carry station
identity. An observation whose geometry cannot be parsed is recorded as a failure, not
given a full-frame vector.

Writes a float32 matrix and a parallel id list, so a later run can align without
trusting row order.

Usage:
    .venv/Scripts/python.exe scripts/extract_hog_cache.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.baseline import _hog_features  # noqa: E402
from pipeline.tracetriage.splits import (  # noqa: E402
    _default_pages_dir,
    _load_raw_pages,
)

_WATERFALL_DIR = Path("D:/tracetriage_data/snap-stage1/waterfalls")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=_REPO / "artifacts" / "hog_cache")
    args = ap.parse_args(argv)

    raw = _load_raw_pages(_default_pages_dir())
    ids = [
        i for i in sorted(raw)
        if raw[i].get("waterfall_status") in ("with-signal", "without-signal")
    ]
    if args.limit:
        ids = ids[: args.limit]

    print(f"extracting HOG for {len(ids)} decisive observations", flush=True)
    kept_ids: list[int] = []
    vectors: list[np.ndarray] = []
    failures: list[int] = []
    t0 = time.time()

    for n, oid in enumerate(ids, 1):
        path = _WATERFALL_DIR / f"waterfall_{oid}.png"
        vec = _hog_features(path) if path.exists() else None
        if vec is None:
            failures.append(oid)
        else:
            kept_ids.append(oid)
            vectors.append(vec.astype(np.float32))
        if n % 25 == 0:
            rate = (time.time() - t0) / n
            print(
                f"  {n}/{len(ids)}  {rate:.2f}s/obs  eta {(len(ids) - n) * rate / 60:.1f} min",
                flush=True,
            )

    args.out.mkdir(parents=True, exist_ok=True)
    matrix = np.stack(vectors, axis=0) if vectors else np.zeros((0, 0), dtype=np.float32)
    np.save(args.out / "hog.npy", matrix)
    (args.out / "index.json").write_text(
        json.dumps(
            {
                "schema": "HOG_CACHE",
                "schema_version": "0.1.0",
                "n_requested": len(ids),
                "n_cached": len(kept_ids),
                "n_geometry_or_load_failures": len(failures),
                "failed_obs_ids": failures,
                "feature_dim": int(matrix.shape[1]) if matrix.size else 0,
                "elapsed_s": round(time.time() - t0, 1),
                "obs_ids": kept_ids,
                "note": (
                    "Row i of hog.npy belongs to obs_ids[i]. Alignment is by this list, "
                    "never by sorting the corpus again, so a change upstream in which "
                    "observations are decisive cannot silently shift every label by one."
                ),
            },
            indent=1,
        ),
        encoding="utf-8",
        newline="\n",
    )
    print(f"\ncached {len(kept_ids)} vectors of dim {matrix.shape[1] if matrix.size else 0}")
    print(f"failures: {len(failures)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
