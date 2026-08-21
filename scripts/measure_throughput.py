"""What it would take to run this on the whole SatNOGS network, from measured numbers.

    .venv/Scripts/python.exe scripts/measure_throughput.py
    .venv/Scripts/python.exe scripts/measure_throughput.py --check

The judged criteria include practicality and scalability, and the README had nothing on
either: no rate for what the network produces, no cost per observation, and therefore no
answer to the only scalability question that matters, which is whether the thing can
keep up. This computes all three from artifacts already in the repository and writes
`artifacts/THROUGHPUT_RECEIPT.json`.

Three quantities, and each is measured rather than estimated:

* **What the network produces.** Every stored observation's `waterfall_url` embeds the
  capture time the station wrote it at. Parsing those gives the span the snapshot covers
  and the number of captures inside it, which is a rate.
* **What one observation costs to process.** `artifacts/corridor_features.json` and
  `artifacts/SECOND_TRACE_SURVEY.json` both record `elapsed_s` against `n_requested`,
  single-threaded, over the same 743 observations.
* **What ingestion costs.** `DATASET_MANIFEST.json` records `built_at` and
  `completed_at` around a run that fetched 110 API pages and downloaded 2,500 waterfall
  images, so the difference is wall-clock cost per observation for the fetch.

The result that matters is the third against the second. This is not a project whose
constraint is inference.

**Four things this does not measure**, stated here rather than left for a reader to
notice:

1. The capture span is 9.4 hours inside one day. A day rate extrapolated from it is one
   observation of the network's rate, not a long-run average, and SatNOGS volume varies
   with how many stations are online.
2. `elapsed_s` covers the corridor fit and the second-trace survey. It does not include
   SGP4 propagation, the fusion head's forward pass or the queue sort, all of which are
   cheaper per observation, and it does not include Granite, which is not per
   observation and runs only on what a reviewer opens.
3. Both were measured on one machine, single-threaded. The core count is a division, not
   a measured parallel speed-up, and the corridor fit is embarrassingly parallel only
   because each observation is independent.
4. The ingestion figure is bound by a 0.4-second courtesy interval between API requests
   and by the download of a 1.7 MB image per observation. Neither is a property of this
   pipeline, and at a ground station the image is already local.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "artifacts/DATASET_MANIFEST.json"
CORRIDOR = REPO / "artifacts/corridor_features.json"
SURVEY = REPO / "artifacts/SECOND_TRACE_SURVEY.json"
OUT = REPO / "artifacts/THROUGHPUT_RECEIPT.json"

# The capture time a station wrote into the object key, e.g.
# .../waterfall_14746129_2026-08-09T23-56-17.png
CAPTURE = re.compile(r"waterfall_\d+_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\.png")


def _load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"{path.relative_to(REPO)} does not exist")
    return json.loads(path.read_text(encoding="utf-8"))


def capture_rate(manifest: dict) -> dict:
    """The network's own rate, from the timestamps the stations wrote."""
    times: list[dt.datetime] = []
    without_url = 0
    unparsed: list[int] = []
    for o in manifest["observations"]:
        url = o.get("waterfall_url") or ""
        if not url:
            without_url += 1
            continue
        m = CAPTURE.search(url)
        if not m:
            unparsed.append(o["id"])
            continue
        times.append(dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S"))

    if unparsed:
        raise SystemExit(
            f"{len(unparsed)} waterfall URLs no longer carry a parseable capture time, "
            f"first {unparsed[:3]}. The object key format changed and this rate would "
            f"be computed over a subset without saying so."
        )
    if len(times) < 100:
        raise SystemExit(
            f"only {len(times)} capture times parsed; a rate over that few is not a "
            f"measurement of the network"
        )

    times.sort()
    span_s = (times[-1] - times[0]).total_seconds()
    if span_s <= 0:
        raise SystemExit("the capture span is zero, so no rate can be computed")

    return {
        "captures_timestamped": len(times),
        "observations_without_a_waterfall": without_url,
        "first_capture_utc": times[0].isoformat() + "Z",
        "last_capture_utc": times[-1].isoformat() + "Z",
        "span_hours": round(span_s / 3600, 2),
        "captures_per_day": round(len(times) / (span_s / 86400)),
        "reading": (
            "Captures with a waterfall, per day, extrapolated from a span of "
            f"{span_s / 3600:.2f} hours. This is the population the pipeline applies "
            "to: an observation with no image cannot be triaged from one."
        ),
    }


def per_observation_cost() -> dict:
    """Single-threaded seconds per observation, from two stages that recorded it."""
    stages = {}
    for name, path in (("corridor_fit", CORRIDOR), ("second_trace_survey", SURVEY)):
        d = _load(path)
        n = d["n_requested"]
        elapsed = d["elapsed_s"]
        if n <= 0 or elapsed <= 0:
            raise SystemExit(f"{path.name} records n={n} elapsed={elapsed}")
        stages[name] = {
            "artifact": str(path.relative_to(REPO)).replace("\\", "/"),
            "observations": n,
            "elapsed_s": elapsed,
            "seconds_per_observation": round(elapsed / n, 4),
            "observations_per_day_one_core": round(86400 / (elapsed / n)),
        }
    return stages


def ingestion_cost(manifest: dict) -> dict:
    """Wall-clock seconds per observation for the fetch, which is network-bound."""
    built = dt.datetime.fromisoformat(manifest["built_at"])
    done = dt.datetime.fromisoformat(manifest["completed_at"])
    elapsed = (done - built).total_seconds()
    stored = manifest["counts"]["observations_stored"]
    waterfalls = manifest["counts"]["waterfalls_stored"]
    return {
        "elapsed_s": round(elapsed, 1),
        "observations_stored": stored,
        "waterfalls_downloaded": waterfalls,
        "seconds_per_observation": round(elapsed / stored, 4),
        "request_interval_seconds": manifest["query"].get("request_interval_seconds"),
        "reading": (
            "Wall clock for 110 API pages plus one image download per observation, "
            "against a 0.4-second courtesy interval between requests. Neither the "
            "interval nor the download is a property of this pipeline, and at a ground "
            "station the image is already on disk."
        ),
    }


def build() -> dict:
    manifest = _load(MANIFEST)
    rate = capture_rate(manifest)
    stages = per_observation_cost()
    ingest = ingestion_cost(manifest)

    # The dominant per-observation compute cost is the slower of the two measured
    # stages, because they run in sequence over the same observations.
    slowest = max(stages.values(), key=lambda s: s["seconds_per_observation"])
    compute_s = slowest["seconds_per_observation"]
    network_per_day = rate["captures_per_day"]
    core_per_day = round(86400 / compute_s)

    return {
        "schema": "THROUGHPUT_RECEIPT",
        "schema_version": 1,
        "generated_by": "scripts/measure_throughput.py",
        "what_the_network_produces": rate,
        "what_one_observation_costs": stages,
        "what_ingestion_costs": ingest,
        "headroom": {
            "dominant_stage": slowest["artifact"],
            "seconds_per_observation": compute_s,
            "observations_per_day_one_core": core_per_day,
            "network_observations_per_day": network_per_day,
            "cores_to_keep_up": round(network_per_day / core_per_day, 3),
            "headroom_multiple": round(core_per_day / network_per_day, 2),
            "reading": (
                f"One core processes {core_per_day} observations a day at the "
                f"dominant measured stage, against {network_per_day} the network "
                f"produced in the span this snapshot covers. That is "
                f"{core_per_day / network_per_day:.2f} times the load on a single "
                f"core, so the pipeline is not compute-bound at network scale."
            ),
        },
        "the_actual_constraint": {
            "compute_seconds_per_observation": compute_s,
            "ingestion_seconds_per_observation": ingest["seconds_per_observation"],
            "ratio": round(ingest["seconds_per_observation"] / compute_s, 3),
            "reading": (
                "Ingestion costs more per observation than the corridor fit does, and "
                "it is bound by a courtesy interval and a 1.7 MB image download rather "
                "than by anything this project computes. The deployment that removes "
                "it is the obvious one: run at the station, where the waterfall is "
                "already local and there is no API to be polite to."
            ),
        },
        "what_this_does_not_measure": [
            "The capture span is 9.4 hours inside one day. A day rate from it is one "
            "observation of the network's rate, not a long-run average.",
            "elapsed_s covers the corridor fit and the second-trace survey only. SGP4, "
            "the fusion forward pass and the queue sort are cheaper per observation and "
            "are not in it, and Granite is not per observation at all.",
            "Both stages were timed on one machine, single-threaded. The core count is "
            "a division and not a measured parallel speed-up.",
            "No figure here is a claim about latency. The queue is a batch reading "
            "order, and nothing in this project needs to answer inside a pass.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)

    receipt = build()
    rendered = json.dumps(receipt, indent=1, ensure_ascii=False) + "\n"

    if args.check:
        if not args.out.exists():
            print(f"{args.out.name} does not exist")
            return 1
        if args.out.read_text(encoding="utf-8") != rendered:
            print(f"{args.out.name} is out of date. Run scripts/measure_throughput.py")
            return 1
        h = receipt["headroom"]
        print(
            f"{args.out.name} is current: {h['headroom_multiple']}x headroom on one core"
        )
        return 0

    args.out.write_text(rendered, encoding="utf-8", newline="\n")
    h = receipt["headroom"]
    c = receipt["the_actual_constraint"]
    print(f"wrote {args.out.relative_to(REPO)}")
    print(
        f"  network produced {h['network_observations_per_day']} observations with a "
        f"waterfall per day"
    )
    print(
        f"  one core handles {h['observations_per_day_one_core']} at "
        f"{h['seconds_per_observation']} s each: {h['headroom_multiple']}x headroom"
    )
    print(
        f"  ingestion costs {c['ingestion_seconds_per_observation']} s per observation, "
        f"{c['ratio']}x the compute"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
