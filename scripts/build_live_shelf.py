"""Measure recent SatNOGS observations and freeze the results the console can serve.

The judged console is a static export. The live endpoint (`api/live.py`) measures whatever
id a reader types, and it is the answer to "can this thing work on today's data", but it is
also a cold start on a serverless platform and a public API that can be slow at the wrong
moment. A demo that depends on both being fast at the same time is a demo that fails in
front of a judge.

So the console ships a shelf: a handful of observations recorded AFTER the frozen snapshot,
measured with the same `live.triage` function the endpoint and the CLI call, with every
provenance field baked in. Pressing a shelf button shows a real measurement of a pass that
was not in the corpus any model here was built from, instantly and without a network call.
Typing an id measures it now. The shelf is the floor, not the product.

Two rules this script follows because the whole point is that these numbers are real.

**Every attempt is published.** An observation whose axis cannot be read, or whose Doppler
mode does not settle, goes into the receipt with its refusal code. Picking only the pretty
ones and reporting five successes would misrepresent the hit rate of the method, which for
UNRESOLVED alone is most of a real queue.

**Courteous to a volunteer-run API.** One page listing, then two GETs per observation, with
a pause between measurements, and a hard cap on attempts.

    .venv/Scripts/python.exe scripts/build_live_shelf.py --target 6
    .venv/Scripts/python.exe scripts/build_live_shelf.py --check

`--check` re-reads the shelf and the receipt and verifies they agree with each other and
that every shelf id is post-snapshot. It measures nothing, so it is safe in the offline
suite: `tests/test_live_shelf.py` runs it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.tracetriage import live as live_engine  # noqa: E402

SHELF = REPO / "apps" / "web" / "public" / "data" / "live_shelf.json"
RECEIPT = REPO / "artifacts" / "LIVE_SHELF_RECEIPT.json"
MANIFEST = REPO / "artifacts" / "DATASET_MANIFEST.json"

#: Nothing on the shelf may come from the corpus the pipeline was built on.
#:
#: The claim the shelf carries is "this measures a pass nothing here was fitted to", and an
#: observation from inside the snapshot would quietly break it. The cutoff is read from the
#: snapshot manifest rather than typed, so a newer snapshot moves it automatically.
def snapshot_cutoff() -> datetime:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # `completed_at` is when the crawl finished, which is the moment after which no
    # observation could have entered it. `built_at` would be the wrong end of the window:
    # observations kept arriving while the crawl ran.
    for key in ("completed_at", "built_at"):
        raw = manifest.get(key)
        if raw:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    raise SystemExit(
        "the dataset manifest carries no snapshot date, so the shelf cannot prove its "
        f"observations are post-snapshot. Keys present: {sorted(manifest)}"
    )


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def build(target: int, attempts: int, n_nulls: int, pause_s: float) -> int:
    cutoff = snapshot_cutoff()
    print(f"snapshot cutoff: {cutoff.isoformat()}")
    started = datetime.now(UTC)

    rows: list[dict[str, Any]] = []
    tried: list[dict[str, Any]] = []

    with live_engine.make_client() as client:
        listed = live_engine.list_observations(
            client,
            limit=attempts,
            require_waterfall=True,
            end_before=datetime.now(UTC),
        )
        print(f"listed {len(listed)} recent observations with a stored waterfall")

        for row in listed:
            if len(rows) >= target:
                break
            obs_id = int(row["id"])
            start = _parse(row["start"])
            if start <= cutoff:
                tried.append(
                    {
                        "observation_id": obs_id,
                        "outcome": "SKIPPED_IN_SNAPSHOT",
                        "start": row["start"],
                    }
                )
                continue
            print(f"  measuring {obs_id} (started {row['start']}) ...", end="", flush=True)
            try:
                image = live_engine.fetch_waterfall(row["waterfall"], client)
                measurement = live_engine.measure(row, image, n_nulls=n_nulls)
            except live_engine.LiveRefusal as exc:
                print(f" refused: {exc.code}")
                tried.append(
                    {
                        "observation_id": obs_id,
                        "outcome": f"REFUSED_{exc.code}",
                        "start": row["start"],
                        "detail": str(exc),
                    }
                )
                time.sleep(pause_s)
                continue

            payload = measurement.to_dict()
            mode = (payload.get("mode") or {}).get("verdict")
            ppm = (payload.get("measurement") or {}).get("offset_ppm")
            p_value = (payload.get("nulls") or {}).get("p_value")
            print(f" {mode}" + (f", {ppm:.1f} ppm" if isinstance(ppm, float) else ""))
            rows.append(payload)
            tried.append(
                {
                    "observation_id": obs_id,
                    "outcome": "MEASURED",
                    "start": row["start"],
                    "mode": mode,
                    "offset_ppm": ppm,
                    "p_value": p_value,
                    "waterfall_sha256": (payload.get("provenance") or {}).get(
                        "waterfall_sha256"
                    ),
                    "measured_at_utc": (payload.get("provenance") or {}).get(
                        "measured_at_utc"
                    ),
                }
            )
            time.sleep(pause_s)

    if not rows:
        print("nothing measured, so nothing is written", file=sys.stderr)
        return 1

    decisive = [
        r for r in rows if (r.get("mode") or {}).get("verdict") in ("UNCORRECTED", "CORRECTED")
    ]

    shelf = {
        "schema": "LIVE_SHELF",
        "schema_version": 1,
        "built_at_utc": started.isoformat(),
        "snapshot_cutoff_utc": cutoff.isoformat(),
        "engine": {
            "function": "pipeline.tracetriage.live.triage",
            "n_nulls": n_nulls,
            "reading": (
                "The same function the CLI and the live endpoint call. A shelf entry and "
                "a fresh measurement of the same id differ only in when they were taken."
            ),
        },
        "reading": (
            "Every observation here was recorded after the frozen snapshot, so none of it "
            "was available to anything in this repository when the models were fitted. "
            "The numbers were measured at the time each entry records and are served "
            "without a network call. Typing an id on the live page measures it now "
            "instead."
        ),
        "n_observations": len(rows),
        "n_decisive": len(decisive),
        "observations": rows,
    }
    SHELF.write_text(json.dumps(shelf, indent=1) + "\n", encoding="utf-8", newline="\n")

    receipt = {
        "schema": "LIVE_SHELF_RECEIPT",
        "schema_version": 1,
        "unit": "operator",
        "question": (
            "Does the measurement path work on observations recorded after the corpus "
            "was frozen, and at what rate?"
        ),
        "built_at_utc": started.isoformat(),
        "snapshot_cutoff_utc": cutoff.isoformat(),
        "n_nulls": n_nulls,
        "counts": {
            "listed": len(tried),
            "measured": len(rows),
            "decisive": len(decisive),
            "unresolved": len(rows) - len(decisive),
            "refused": len([t for t in tried if t["outcome"].startswith("REFUSED")]),
            "skipped_in_snapshot": len(
                [t for t in tried if t["outcome"] == "SKIPPED_IN_SNAPSHOT"]
            ),
        },
        "attempts": tried,
        "what_this_does_not_measure": (
            "Whether the offsets are correct. A measurement on a post-snapshot pass shows "
            "the path runs end to end on data nothing here was fitted to; it is not a "
            "second validation of the estimator, which kill gate 3 owns and which is "
            "still unbound."
        ),
    }
    RECEIPT.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8", newline="\n")

    print(
        f"\nwrote {SHELF.relative_to(REPO)} ({len(rows)} observations, "
        f"{len(decisive)} decisive) and {RECEIPT.relative_to(REPO)}"
    )
    return 0


def check() -> int:
    if not SHELF.exists() or not RECEIPT.exists():
        print("the shelf or its receipt is missing; run this script without --check")
        return 1
    shelf = json.loads(SHELF.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    cutoff = _parse(shelf["snapshot_cutoff_utc"])
    problems: list[str] = []

    if shelf["n_observations"] != len(shelf["observations"]):
        problems.append("the shelf's count and its list disagree")
    if receipt["counts"]["measured"] != shelf["n_observations"]:
        problems.append("the receipt and the shelf disagree about how many were measured")

    for entry in shelf["observations"]:
        obs = entry.get("observation") or {}
        obs_id = obs.get("id")
        start = obs.get("start")
        if not start:
            problems.append(f"{obs_id} carries no start time")
            continue
        if _parse(start) <= cutoff:
            problems.append(f"{obs_id} started at {start}, inside the snapshot window")
        provenance = entry.get("provenance") or {}
        for field in ("waterfall_sha256", "measured_at_utc"):
            if not provenance.get(field):
                problems.append(f"{obs_id} has no {field}")

    if problems:
        for line in problems:
            print(f"  {line}")
        return 1
    print(
        f"shelf: {shelf['n_observations']} post-snapshot observations, "
        f"{shelf['n_decisive']} decisive, cutoff {shelf['snapshot_cutoff_utc']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=int, default=6, help="How many to put on the shelf.")
    ap.add_argument(
        "--attempts",
        type=int,
        default=18,
        help="How many recent observations to list. A cap on the load this puts on a "
        "volunteer-run API.",
    )
    ap.add_argument("--n-nulls", type=int, default=99)
    ap.add_argument("--pause", type=float, default=0.6, help="Seconds between measurements.")
    ap.add_argument("--check", action="store_true", help="Verify the committed shelf.")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    return build(args.target, args.attempts, args.n_nulls, args.pause)


if __name__ == "__main__":
    raise SystemExit(main())
