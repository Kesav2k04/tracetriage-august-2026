"""Grow gate 3's testable pool from the frozen snapshot, with two selection rules.

Gate 3 asks whether the expected Doppler corridor lands on a visible trace. It was
measured on the 3 uncorrected captures in A3's 24-observation live sample, and 3 of 3
discriminated. A perfect rate at n = 3 has an exact one-sided 95% lower bound of
``0.05 ** (1/3) = 0.368`` against a 0.70 bar, so the gate read NOT_ESTABLISHED on the
count rather than on the measurements. The first n whose perfect rate clears 0.70 is 9.

That was the state this script was written to change. The verdict it produced is in
``artifacts/GATE3_RECEIPT.json`` and is not restated here, because a docstring that
names a result is a second copy of it and the copy is the one that goes stale.

The snapshot already on disk holds 2,500 waterfalls. Nothing has to be fetched, and no
threshold in gate 3 moves. What this script does is decide which observations are
*testable*, and that decision is the whole methodological problem, so it is worth being
blunt about it.

## Why there are two pools

A3 labelled an observation ``UNCORRECTED`` when the predicted Doppler corridor scored at
least ``SIGMA_MARGIN`` above a vertical line: ``sigma_curved - sigma_vertical >= 3.0``.
That is a statement about how well the corridor fits. Selecting the pool on it and then
asking whether the corridor discriminates is selection on a quantity correlated with the
outcome, and a rate measured that way is partly a measurement of the selection.

So this builds two pools and ``docs/E16_PREREGISTRATION.md``, committed before any of
this ran, says which one decides the gate:

``pool_a`` (corridor-selected)
    A3's own rule, unchanged, so the larger run is comparable with the n = 3 result.

``pool_b`` (the pre-registered pool)
    Entry uses no Doppler prediction at all. An observation is in when a trace is
    visible by a detector that never sees the corridor, and the vertical hypothesis
    does not fit. Both statistics are computed from the image and the axis calibration
    only.

The corridor-free presence statistic is ``trace_q75``: the 75th percentile of the
per-row maximum robust z-score over the spectrogram interior. Taking a percentile rather
than the maximum requires the trace to be there through at least a quarter of the pass,
so one bright row of interference does not admit an observation.

Where the bar sits was got wrong once and the wrong reasoning is worth keeping. The first
value was 6.0, argued from the maximum of W independent Gaussian columns sitting near
``sqrt(2 ln W)``, about 3.7 at these widths. Measured, the noise ceiling under this
normalisation is near 2.0, and 6.0 excluded observation 14740031, whose matched filter
reaches 25 sigma on the same image. The bar is read off the measured distribution
instead. That distribution involves no corridor and no gate result, so setting it is a
decision about the detector rather than about the answer, and every observation's
``trace_q75`` is written out whether it is selected or not so the choice can be audited
and the result's sensitivity to it published.

Usage::

    .venv/Scripts/python.exe scripts/build_gate3_pool.py \\
        --snapshot D:/tracetriage_data/snap-stage1 \\
        --out artifacts/GATE3_POOL.json

    .venv/Scripts/python.exe scripts/build_gate3_pool.py --limit 20   # a timing probe

Output
------
``artifacts/GATE3_POOL.json`` holds one record per observation examined, with the fields
``scripts/run_gate3.py`` reads (``obs_id``, ``verdict``, ``sigma_curved``,
``sigma_vertical``, ``curved_offset_hz``) plus the corridor-free statistics and the two
pool memberships. It is a superset of A3's summary shape, so the gate runner reads it
without a change.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Set before numpy is imported, or the libraries have already read their own defaults.
# Each worker examines one image at a time and gains nothing from an internal thread
# pool; eight workers each spawning one would oversubscribe every core on the machine.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.tracetriage.doppler_mode import (  # noqa: E402
    MIN_PREDICTED_SWING_HZ,
    SIGMA_MIN,
    matched_filter,
    predicted_swing_hz,
    verdict_from_scores,
)
from pipeline.tracetriage.physics import (  # noqa: E402
    client_family,
    corridor_for_obs,
    rx_freq_of,
)
from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: E402

logger = logging.getLogger("gate3_pool")

#: Written explicitly so the partial file is LF on every platform, matching the
#: receipt beside it and the repository's .gitattributes.
NEWLINE = "\n"

#: The corridor-free presence bar. Set from the marginal distribution of ``trace_q75``
#: over the whole snapshot, which is bimodal, and fixed in
#: ``docs/E16_PREREGISTRATION.md`` before gate 3 was run on the pool it selects. The
#: first value tried was 6.0, reasoned from sqrt(2 ln W) for W columns of Gaussian noise.
#: That reasoning is wrong for this normalisation: measured over 12 observations the
#: noise ceiling is near 2.0 and 6.0 excluded a trace whose matched filter reaches 25
#: sigma. The number below is read off the antimode of the measured distribution instead,
#: which is a decision about the detector taken with no corridor and no gate result in it.
TRACE_Q75_MIN = 3.5

#: Which row-percentile the presence statistic reads. The 75th requires the trace to be
#: there for at least a quarter of the pass rather than in one bright row.
TRACE_PERCENTILE = 75.0

#: Rows within this many pixels of the crop edge are dropped, matching A3.
EDGE_MARGIN_PX = 2

#: The smallest MAD a row can have and still carry a z-score. ``lum`` is the mean of
#: three uint8 channels, so its quantisation step is 1/3 and the smallest MAD an
#: informative row can show is that step scaled by the same 1.4826.
#:
#: This exists because the first version floored the divisor at 1e-6 instead. A row with
#: no variation at all, a blank or saturated line with nothing in it, has MAD exactly 0,
#: so the floor turned it into z of order 1e8 and put the emptiest row in the image above
#: every real trace in it. On the first full build the 75th percentile of pool B reached
#: 22,666,664 and the maximum 89,000,000, against a real matched-filter detection at 25.
#: The statistic was inverted precisely where it degenerated, and it inflates only
#: upward, so it could add observations to pool B and never remove one.
#:
#: A row with no measurable variation is not evidence of a trace. It is dropped from the
#: percentile rather than floored, and the count is written to the record so a reader can
#: see how much of each image this removed.
MIN_ROW_MAD = (1.0 / 3.0) * 1.4826


def _normalised_rows(rgb: np.ndarray, crop_box) -> tuple[np.ndarray, np.ndarray]:
    """Per-row robust z-scores over the spectrogram interior, and which rows carry one.

    The same normalisation A3 and ``corridor_fit`` use: each row against its own median
    and MAD, so the vertical brightness gradient a changing range puts into every pass
    does not decide anything, and nothing is normalised along time, which would delete a
    stationary carrier and hand the answer to one hypothesis.

    The second return is the mask of rows whose MAD clears ``MIN_ROW_MAD``. A row below
    it has no spread to measure against, so the ratio it produces is an artifact of the
    divisor and not a z-score. See ``MIN_ROW_MAD`` for what that cost before it was
    caught.
    """
    x0 = crop_box.x0 + EDGE_MARGIN_PX
    x1 = crop_box.x1 - EDGE_MARGIN_PX
    y0 = crop_box.y0 + EDGE_MARGIN_PX
    y1 = crop_box.y1 - EDGE_MARGIN_PX
    lum = rgb[y0:y1, x0:x1].astype(np.float32).mean(axis=2)
    med = np.median(lum, axis=1, keepdims=True)
    mad = np.median(np.abs(lum - med), axis=1, keepdims=True) * 1.4826
    measurable = (mad[:, 0] >= MIN_ROW_MAD)
    return (lum - med) / np.maximum(mad, MIN_ROW_MAD), measurable


def trace_presence(
    zs: np.ndarray, measurable: np.ndarray | None = None
) -> dict[str, float] | None:
    """How strongly a trace is visible, with no Doppler prediction anywhere in it.

    Returns the percentile the pool rule reads plus the maximum and the median, so a
    reader can see the shape of the row-peak distribution rather than one number chosen
    from it, and the count of rows that had no spread to measure against.

    ``None`` when no row is measurable. That is an image with nothing in it, and the
    honest answer is that the statistic could not be taken, not that it came back low:
    ``in_pool_b`` already treats a missing ``trace_q75`` as out.
    """
    if measurable is None:
        measurable = np.ones(zs.shape[0], dtype=bool)
    dropped = int(zs.shape[0] - int(measurable.sum()))
    if not measurable.any():
        return None
    peaks = zs[measurable].max(axis=1)
    return {
        "trace_q75": float(np.percentile(peaks, TRACE_PERCENTILE)),
        "trace_median": float(np.median(peaks)),
        "trace_max": float(peaks.max()),
        "n_rows": int(peaks.size),
        "n_rows_unmeasurable": dropped,
    }


def in_pool_b(record: dict[str, Any], trace_q75_min: float = TRACE_Q75_MIN) -> bool:
    """Pool B's membership rule, as a function of one finished record.

    A function rather than an expression inside ``examine`` for two reasons. It is the
    claim ``docs/E16_PREREGISTRATION.md`` section 3 is built on, so it is worth being
    readable in one place and testable without an image. And it lets ``--recut`` re-derive
    the pool at another threshold from a finished run, which is how the sensitivity of the
    verdict to ``TRACE_Q75_MIN`` gets published rather than described.

    Three conditions, none of which reads how well the corridor fits:

    - the predicted swing, computed from the orbit and the receive frequency before the
      image is opened, is large enough to tell a curve from a vertical line;
    - a trace is visible by the per-row presence statistic;
    - a vertical line does not fit, which is the corridor-free test for a capture the
      station Doppler-corrected, whose corridor is identically 0 Hz and predicts nothing.
    """
    swing = record.get("predicted_swing_hz")
    q75 = record.get("trace_q75")
    vertical = record.get("sigma_vertical")
    if swing is None or q75 is None or vertical is None:
        return False
    return bool(
        swing >= MIN_PREDICTED_SWING_HZ
        and q75 >= trace_q75_min
        and vertical < SIGMA_MIN
    )


def compute_doppler_curve(obs: dict) -> tuple[list[float], list[float], list[float]]:
    """(fracs, doppler_hz, elevations) across the pass, from the record's own TLE.

    Lifted from ``scripts/a3_doppler_investigation.py`` rather than imported, because
    that module's import path pulls in the live HTTP client and this run touches no
    network. Positive Doppler is approach, which is the higher received frequency and so
    the right-hand side of the axis.
    """
    from sgp4.api import Satrec, jday  # type: ignore[import]

    sat = Satrec.twoline2rv(obs["tle1"], obs["tle2"])
    start_dt = datetime.fromisoformat(obs["start"].replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(obs["end"].replace("Z", "+00:00"))
    duration_s = (end_dt - start_dt).total_seconds()
    if duration_s <= 0:
        raise ValueError(f"pass duration is {duration_s} s")

    lat = float(obs["station_lat"])
    lon = float(obs["station_lng"])
    alt_km = float(obs.get("station_alt") or 0.0) / 1000.0
    rx_hz = rx_freq_of(obs)
    if not rx_hz:
        raise ValueError("no receive frequency on the record")

    n = 120
    fracs: list[float] = []
    doppler: list[float] = []
    elevations: list[float] = []
    c = 299_792_458.0

    for i in range(n):
        frac = i / (n - 1)
        when = start_dt.timestamp() + frac * duration_s
        moment = datetime.fromtimestamp(when, tz=UTC)
        jd, fr = jday(
            moment.year, moment.month, moment.day,
            moment.hour, moment.minute, moment.second + moment.microsecond / 1e6,
        )
        err, r, v = sat.sgp4(jd, fr)
        if err != 0:
            raise ValueError(f"sgp4 error {err}")
        site, site_v = _site_eci(lat, lon, alt_km, jd, fr)
        rel = np.array(r) - site
        rel_v = np.array(v) - site_v
        rng = float(np.linalg.norm(rel))
        if rng <= 0:
            raise ValueError("degenerate range")
        range_rate_km_s = float(np.dot(rel, rel_v) / rng)
        fracs.append(frac)
        doppler.append(-range_rate_km_s * 1000.0 / c * rx_hz)
        elevations.append(_elevation_deg(rel, lat, lon, jd, fr))

    return fracs, doppler, elevations


def _gmst(jd: float, fr: float) -> float:
    """Greenwich mean sidereal time in radians, IAU 1982."""
    t = (jd + fr - 2451545.0) / 36525.0
    sec = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    return (sec % 86400.0) / 240.0 * np.pi / 180.0


def _site_eci(lat_deg: float, lon_deg: float, alt_km: float, jd: float, fr: float):
    """Station position and velocity in the same true-equator frame sgp4 returns."""
    f = 1.0 / 298.257223563
    a = 6378.137
    lat = np.radians(lat_deg)
    theta = _gmst(jd, fr) + np.radians(lon_deg)
    cc = 1.0 / np.sqrt(1.0 + f * (f - 2.0) * np.sin(lat) ** 2)
    sq = (1.0 - f) ** 2 * cc
    ach = (a * cc + alt_km) * np.cos(lat)
    ash = (a * sq + alt_km) * np.sin(lat)
    pos = np.array([ach * np.cos(theta), ach * np.sin(theta), ash])
    omega = 7.292115146706979e-5
    vel = np.array([-omega * pos[1], omega * pos[0], 0.0])
    return pos, vel


def _elevation_deg(rel, lat_deg: float, lon_deg: float, jd: float, fr: float) -> float:
    lat = np.radians(lat_deg)
    theta = _gmst(jd, fr) + np.radians(lon_deg)
    up = np.array([np.cos(lat) * np.cos(theta), np.cos(lat) * np.sin(theta), np.sin(lat)])
    rng = float(np.linalg.norm(rel))
    return float(np.degrees(np.arcsin(float(np.dot(rel, up)) / rng))) if rng else 0.0


def load_snapshot(snapshot: Path) -> list[dict[str, Any]]:
    """Every observation record in the snapshot's pages, in page then row order."""
    rows: list[dict[str, Any]] = []
    for page in sorted((snapshot / "pages").glob("*.json")):
        payload = json.loads(page.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else payload.get("results", [])
        rows.extend(records)
    return rows


def examine(
    obs: dict[str, Any], snapshot: Path, trace_q75_min: float = TRACE_Q75_MIN
) -> dict[str, Any]:
    """One observation, end to end, returning a record even when it cannot be measured.

    A refusal is a row with ``status`` set to why, never a silent drop: the denominator
    of the pool is as much a claim as its numerator.
    """
    obs_id = obs["id"]
    record: dict[str, Any] = {
        "obs_id": obs_id,
        "family": client_family(obs),
        "station": obs.get("ground_station"),
        "station_name": obs.get("station_name"),
        "norad_cat_id": obs.get("norad_cat_id"),
        "transmitter_uuid": obs.get("transmitter_uuid"),
        "start": obs.get("start"),
        "max_altitude": obs.get("max_altitude"),
        "rx_freq_hz": rx_freq_of(obs),
        "waterfall_status": obs.get("waterfall_status"),
        "observation_status": obs.get("status"),
    }

    img = snapshot / "waterfalls" / f"waterfall_{obs_id}.png"
    if not img.is_file():
        return record | {"status": "no_waterfall", "verdict": "UNRESOLVED"}

    phys = corridor_for_obs(obs)
    if phys.degraded is not None:
        return record | {"status": f"physics_{phys.degraded}", "verdict": "UNRESOLVED"}
    duration_s = phys.pass_duration_s or 200.0

    # The orbit before the image. ``verdict_from_scores`` returns UNRESOLVED whenever the
    # predicted swing is under the floor, whatever the matched filter says, so an
    # observation that fails here cannot reach either pool and the axis OCR on it would
    # be paid for and discarded. Same rule and same outcome, an order of magnitude less
    # work across a snapshot where most passes are too short or too low to be told apart.
    try:
        curve_fracs, curve_hz, els = compute_doppler_curve(obs)
    except Exception as exc:  # noqa: BLE001
        return record | {"status": f"physics_failed: {exc}", "verdict": "UNRESOLVED"}
    swing = predicted_swing_hz(curve_hz)
    record["predicted_swing_hz"] = swing
    record["sgp4_max_elevation_deg"] = max(els) if els else None
    if swing < MIN_PREDICTED_SWING_HZ:
        # Not "ok": this returns before `parse_waterfall`, so the image is never opened.
        # Calling it ok put observations into `counts.measurable` that nothing measured.
        # `in_pool_b` carries the same swing floor, so these are out at every threshold
        # and the short circuit costs the pool nothing.
        return record | {
            "status": "swing_below_floor",
            "verdict": "UNRESOLVED",
            "reason": (
                f"predicted swing is only {swing:,.0f} Hz, too small to tell the two "
                f"shapes apart"
            ),
            "pool_a": False,
            "pool_b": False,
        }

    try:
        geom = parse_waterfall(
            image_data=img.read_bytes(),
            observation_id=obs_id,
            pass_duration_s=duration_s,
            rx_freq_hz=record["rx_freq_hz"],
        )
    except Exception as exc:  # noqa: BLE001 - one bad image may not stop the run
        return record | {"status": f"geometry_failed: {exc}", "verdict": "UNRESOLVED"}
    if geom.degraded is not None or geom.crop_box is None or not geom.hz_per_px:
        return record | {"status": f"geometry_{geom.degraded}", "verdict": "UNRESOLVED"}

    record |= {
        "derivation": getattr(geom, "derivation", None),
        "hz_per_px": geom.hz_per_px,
        "centre_px": geom.centre_px,
        "pass_duration_s": duration_s,
    }

    from PIL import Image

    with Image.open(img) as im:
        rgb = np.asarray(im.convert("RGB"))
    zs, measurable = _normalised_rows(rgb, geom.crop_box)

    # Corridor-free first, and recorded for every observation whether it is selected or
    # not, so the pool rule can be re-run at another threshold from this file alone.
    presence = trace_presence(zs, measurable)
    if presence is None:
        # Every row in the crop is flat. There is nothing in this image for a trace to
        # be present or absent in, so the statistic is refused rather than returned low,
        # and it carries a status like every other refusal above. `_recut` keys on
        # status == "ok", so this stays out of the pool at any threshold.
        return record | {
            "status": "no_measurable_rows",
            "verdict": "UNRESOLVED",
            "reason": "no row in the crop has the spread to carry a z-score",
            "n_rows_unmeasurable": int(zs.shape[0]),
            "pool_a": False,
            "pool_b": False,
        }
    record |= presence

    centre = geom.centre_px if geom.centre_px is not None else geom.crop_box.width() / 2.0
    scores = matched_filter(zs, centre, geom.hz_per_px, curve_fracs, curve_hz)
    verdict, reason, summary = verdict_from_scores(scores, swing)
    summary.pop("per_width", None)
    record |= summary
    record |= {"status": "ok", "verdict": verdict, "reason": reason}

    # Pool A is A3's rule verbatim. Pool B never reads sigma_curved.
    record["pool_a"] = verdict == "UNCORRECTED"
    record["pool_b"] = in_pool_b(record, trace_q75_min)
    return record


#: Set once per worker process so every task does not re-resolve it.
_WORKER_STATE: dict[str, Any] = {}


def _examine_one(task: tuple[dict[str, Any], str, float]) -> dict[str, Any]:
    """One observation, in a worker process. Never raises: a crash here loses the pass.

    An exception inside a pool worker kills the task and, depending on how it is
    surfaced, the run. A failure is a record with a status like every other refusal, so
    the denominator survives whatever one bad image does.
    """
    obs, snapshot, bar = task
    try:
        return examine(obs, Path(snapshot), bar)
    except Exception as exc:  # noqa: BLE001
        return {
            "obs_id": obs.get("id"),
            "status": f"worker_failed: {type(exc).__name__}: {exc}",
            "verdict": "UNRESOLVED",
            "pool_a": False,
            "pool_b": False,
        }


def _partial_path(out: Path) -> Path:
    """Where finished records land as they are produced.

    JSON Lines rather than JSON, because a list has to be closed to be valid and a run
    that dies mid-write should still leave every completed record readable.
    """
    return out.with_suffix(out.suffix + ".partial.jsonl")


def _resume(partial: Path) -> dict[int, dict[str, Any]]:
    """Whatever a previous run finished, keyed by observation id.

    A truncated final line is dropped rather than repaired: the observation it belongs to
    is simply re-examined.
    """
    done: dict[int, dict[str, Any]] = {}
    if not partial.is_file():
        return done
    for line in partial.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("obs_id") is not None:
            done[int(row["obs_id"])] = row
    return done


def _recut(path: Path, trace_q75_min: float) -> int:
    """Re-derive pool B at another presence bar, from a finished run's own numbers.

    Pool A is left exactly as it was: it is A3's label and has nothing to do with this
    threshold. Rewriting it here would silently make the two pools move together.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["observations"]
    before = sum(1 for r in rows if r.get("pool_b"))
    for row in rows:
        row["pool_b"] = row.get("status") == "ok" and in_pool_b(row, trace_q75_min)
    after = sum(1 for r in rows if r.get("pool_b"))

    payload["trace_q75_min"] = trace_q75_min
    payload["counts"]["pool_b"] = after
    payload["counts"]["in_both"] = sum(
        1 for r in rows if r.get("pool_a") and r.get("pool_b")
    )
    payload["recut_at"] = datetime.now(UTC).isoformat()
    path.write_text(
        _dump(payload),
        encoding="utf-8",
        newline="\n",
    )
    print(f"recut {path} at trace_q75 >= {trace_q75_min}")
    print(f"  pool B {before} -> {after}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, default=Path("D:/tracetriage_data/snap-stage1"))
    ap.add_argument("--out", type=Path, default=REPO / "artifacts" / "GATE3_POOL.json")
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="examine only the first N observations, for a timing probe",
    )
    ap.add_argument(
        "--trace-q75-min",
        type=float,
        default=TRACE_Q75_MIN,
        help=(
            "the corridor-free presence bar. Exposed so the pool can be recut from a "
            "finished run without re-examining 2,500 images, and so the result's "
            "sensitivity to it can be published rather than asserted"
        ),
    )
    ap.add_argument(
        "--recut",
        action="store_true",
        help=(
            "do not open any image. Read the pool file at --out, recompute pool_b from "
            "the statistics already recorded there at --trace-q75-min, and write it back. "
            "This is how the verdict's sensitivity to the presence bar is produced"
        ),
    )
    ap.add_argument(
        "--jobs",
        type=int,
        default=8,
        help=(
            "worker processes. The per-observation work is pure CPU over one image, so "
            "it parallelises exactly. 1 runs in this process, which is what a debugger "
            "wants"
        ),
    )
    ap.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "delete the partial file first. Without this a run resumes from whatever a "
            "previous one finished, which is the point of the partial file"
        ),
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    if args.recut:
        return _recut(args.out, args.trace_q75_min)

    observations = load_snapshot(args.snapshot)
    if args.limit:
        observations = observations[: args.limit]
    logger.info("snapshot records: %d", len(observations))

    partial = _partial_path(args.out)
    if args.fresh and partial.exists():
        partial.unlink()
    done = _resume(partial)
    if done:
        logger.info("resuming: %d records already on disk in %s", len(done), partial.name)

    todo = [obs for obs in observations if int(obs["id"]) not in done]
    logger.info("to examine: %d", len(todo))

    if todo:
        tasks = [(obs, str(args.snapshot), args.trace_q75_min) for obs in todo]
        with partial.open("a", encoding="utf-8", newline=NEWLINE) as sink:
            if args.jobs == 1:
                produced = (_examine_one(task) for task in tasks)
                for i, row in enumerate(produced, 1):
                    sink.write(json.dumps(row) + NEWLINE)
                    sink.flush()
                    done[int(row["obs_id"])] = row
                    if i % 100 == 0:
                        logger.info("  %d/%d examined", i, len(tasks))
            else:
                with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                    for i, row in enumerate(
                        pool.map(_examine_one, tasks, chunksize=4), 1
                    ):
                        sink.write(json.dumps(row) + NEWLINE)
                        sink.flush()
                        done[int(row["obs_id"])] = row
                        if i % 100 == 0:
                            logger.info("  %d/%d examined", i, len(tasks))

    # Snapshot order, not completion order, so two runs that split the work differently
    # still produce byte-identical output.
    records = [done[int(obs["id"])] for obs in observations if int(obs["id"]) in done]

    ok = [r for r in records if r.get("status") == "ok"]
    pool_a = [r for r in ok if r.get("pool_a")]
    pool_b = [r for r in ok if r.get("pool_b")]

    payload = {
        "schema": "GATE3_POOL",
        "schema_version": 1,
        "generated_by": "scripts/build_gate3_pool.py",
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot": str(args.snapshot).replace("\\", "/"),
        "pre_registration": "docs/E16_PREREGISTRATION.md",
        "unit": "one record per snapshot observation examined, selected or not",
        "trace_q75_min": args.trace_q75_min,
        "selection": {
            "pool_a": (
                "A3's rule verbatim: verdict_from_scores returns UNCORRECTED, which "
                "means sigma_curved - sigma_vertical >= SIGMA_MARGIN. Corridor-selected, "
                "published for comparability with the n = 3 result and not the gate."
            ),
            "pool_b": (
                f"No Doppler prediction anywhere in the rule: predicted swing >= "
                f"{MIN_PREDICTED_SWING_HZ:.0f} Hz, trace_q75 >= {args.trace_q75_min} and "
                f"sigma_vertical < {SIGMA_MIN}. The swing is a property of the "
                f"prediction rather than of the image, so it cannot be influenced by "
                f"whether the corridor matches. This is the pre-registered pool."
            ),
            "trace_q75": (
                f"the {TRACE_PERCENTILE:.0f}th percentile of the per-row maximum robust "
                f"z-score over the spectrogram interior. Under noise the maximum of W "
                f"columns sits near sqrt(2 ln W), about 3.7 at these widths."
            ),
        },
        "counts": {
            "examined": len(records),
            "measurable": len(ok),
            "pool_a": len(pool_a),
            "pool_b": len(pool_b),
            "in_both": sum(1 for r in ok if r.get("pool_a") and r.get("pool_b")),
            "by_status": _tally(records, "status"),
            "by_verdict": _tally(ok, "verdict"),
        },
        "observations": records,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        _dump(payload),
        encoding="utf-8",
        newline="\n",
    )

    print(f"wrote {args.out}")
    print(f"  examined  {len(records)}")
    print(f"  measurable {len(ok)}")
    print(f"  pool A (corridor-selected) {len(pool_a)}")
    print(f"  pool B (pre-registered)    {len(pool_b)}")
    return 0


def _json_safe(node, path: str = "", found: list[str] | None = None):
    """Non-finite floats become null, and where each one was is recorded.

    `json.dumps` writes `NaN`, which is not JSON. This file carried one, inherited into
    `artifacts/GATE3_RECEIPT.json`, and made both unreadable by `jq`, by `JSON.parse` and
    by the presentation film's build. Every other consumer here is Python, so nothing had
    noticed for as long as the pool had existed.

    A NaN means the statistic could not be computed for that observation. JSON spells that
    null. The conversion is reported because a file that turned numbers into nulls quietly
    would be a worse artifact than one that refuses to write.
    """
    if found is None:
        found = []
    if isinstance(node, dict):
        return {k: _json_safe(v, f"{path}.{k}", found) for k, v in node.items()}
    if isinstance(node, list):
        return [_json_safe(v, f"{path}[{i}]", found) for i, v in enumerate(node)]
    if isinstance(node, float) and not math.isfinite(node):
        found.append(f"{path} = {node}")
        return None
    return node


def _dump(payload) -> str:
    non_finite: list[str] = []
    payload = _json_safe(payload, "", non_finite)
    if non_finite:
        print(
            f"  {len(non_finite)} non-finite value(s) written as null, because JSON has "
            f"no NaN: {', '.join(non_finite[:8])}"
            + (" ..." if len(non_finite) > 8 else "")
        )
    return json.dumps(payload, indent=1, sort_keys=False, allow_nan=False) + "\n"


def _tally(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key))
        # A geometry or physics message carries the observation's own detail, which
        # would make every row its own bucket. The prefix is the category.
        value = value.split(":", 1)[0]
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


if __name__ == "__main__":
    raise SystemExit(main())
