"""A4 physics validation: max_altitude and azimuth agreement over >=200 observations.

Fetches live observation records from the SatNOGS API, computes the physics
corridor for each, and compares the SGP4-derived geometry against the API's own
reported values.  Writes both distributions to artifacts/PHYSICS_VALIDATION.json.

Two references, and they are not equally sharp:

  - ``max_altitude`` is an integer on all 200 cached records. A uniform rounding
    error on [-0.5, 0.5] has mean absolute value 0.250 and standard deviation
    0.289, and the measured distribution is mean absolute 0.243 with a signed
    standard deviation of 0.363. So this comparison bounds the elevation error at
    roughly half a degree and cannot resolve anything finer: most of what it
    reports is the reference's own rounding. It was published as evidence of
    agreement to 0.243 degrees, which claims a resolution the reference does not
    have. The artifact now says so in ``reference_quantisation``.

  - ``rise_azimuth`` and ``set_azimuth`` are unrounded and present on all 200
    records, and they were never validated against, although the project's own
    recon document required it. They are the only independent check available on
    the azimuth convention and the local East/North/Up basis. They are also the
    check that could have caught the geocentric-versus-geodetic up-vector defect
    that unit C7 fixed: the elevation comparison could not see it in the mean
    (1.4 sigma) or in the variance (variance ratio 1.035 against an F critical
    value near 1.28), because integer rounding is larger than the defect.

Both counterfactuals are computed rather than described, because an agreement
with no scale is not a measurement: swapping the atan2 arguments and mirroring the
azimuth both stay in the artifact beside the real numbers.

Uses the same caching strategy as scripts/a3_doppler_investigation.py:
  - Pages are cached under .a3_cache/ (or A3_CACHE_DIR env var) so a rerun
    costs no requests and reproduces the same numbers from the same bytes.
  - Requests are spaced at least REQUEST_INTERVAL seconds apart.
  - Rate-limit responses (HTTP 429) are handled with Retry-After + a cap.

The validation requires NO waterfall downloads — geometry validation needs only
the observation metadata record, not the PNG.

Usage
-----
    .venv\\Scripts\\python.exe scripts\\validate_physics.py

Output
------
    artifacts/PHYSICS_VALIDATION.json

Environment
-----------
    A3_CACHE_DIR    path to the page cache (default: .a3_cache/)
    A4_END_DATE     observation end date filter (default: 2026-08-10T00:00:00Z)
    A4_TARGET_OBS   minimum valid observations to collect (default: 200)
    A4_MAX_PAGES    maximum API pages to fetch (default: 30)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.physics import (  # noqa: E402
    TLE_MAX_EPOCH_AGE_DAYS,
    corridor_for_obs,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://network.satnogs.org/api/observations/"
USER_AGENT = (
    "tracetriage/0.1 (+https://github.com/Kesav2k04/tracetriage-august-2026;"
    " kesavk659@gmail.com)"
)
REQUEST_INTERVAL = 2.0
RETRY_DELAYS = [5, 15, 45]
MAX_SLEEP_ON_429 = 120.0

CACHE_DIR = Path(os.environ.get("A3_CACHE_DIR") or (REPO / ".a3_cache"))
# Overridable so the freshness check can rebuild into a scratch directory and diff
# the result against the committed file without overwriting it.
OUT_PATH = Path(os.environ.get("A4_OUT_PATH") or REPO / "artifacts" / "PHYSICS_VALIDATION.json")

END_DATE = os.environ.get("A4_END_DATE", "2026-08-10T00:00:00Z")
TARGET_OBS = int(os.environ.get("A4_TARGET_OBS", "200"))
MAX_PAGES = int(os.environ.get("A4_MAX_PAGES", "30"))


# ---------------------------------------------------------------------------
# API helpers (same approach as a3_doppler_investigation.py)
# ---------------------------------------------------------------------------


class Throttled(Exception):
    pass


def _cache_path(key: str) -> Path:
    p = CACHE_DIR / "a4_validation_pages" / END_DATE.replace(":", "").replace("-", "")
    p.mkdir(parents=True, exist_ok=True)
    return p / key


def _get(url: str, timeout: float = 60.0) -> tuple[bytes, dict]:
    headers = {"User-Agent": USER_AGENT}
    last_exc: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt:
            wait = RETRY_DELAYS[attempt - 1]
            print(f"  retry {attempt}: waiting {wait}s")
            time.sleep(wait)
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 30))
                if retry_after > MAX_SLEEP_ON_429:
                    raise Throttled(
                        f"rate limited for another {retry_after:.0f}s "
                        f"({retry_after / 60:.1f} min)"
                    )
                print(f"  429, Retry-After={retry_after:.0f}s")
                time.sleep(retry_after + 1)
                continue
            resp.raise_for_status()
            return resp.content, dict(resp.headers)
        except httpx.TimeoutException as exc:
            last_exc = exc
            print(f"  timeout: {exc}")
    raise RuntimeError(f"all retries exhausted for {url}: {last_exc}")


def _next_cursor(link_header: str | None) -> str | None:
    from urllib.parse import parse_qs, urlparse
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        start, end = part.find("<"), part.find(">")
        if start == -1 or end == -1:
            continue
        qs = parse_qs(urlparse(part[start + 1:end]).query)
        if qs.get("cursor"):
            return qs["cursor"][0]
    return None


# ---------------------------------------------------------------------------
# Fetch observation records (metadata only; no waterfall downloads)
# ---------------------------------------------------------------------------


def fetch_observations(target: int, max_pages: int) -> list[dict]:
    """Page the API collecting records that have TLE + station + max_altitude.

    max_altitude is the API's own reported peak elevation: this is the field
    we validate against, so we only keep records where it is non-null.
    """
    params = {"format": "json", "end": END_DATE}
    url = API_BASE + "?" + urlencode(params)

    collected: list[dict] = []
    seen: set[int] = set()
    page_index = 0

    print(f"Fetching observation records for geometry validation (end={END_DATE})")
    while url and len(collected) < target and page_index < max_pages:
        cached = _cache_path(f"page_{page_index:03d}.json")
        cached_hdr = _cache_path(f"page_{page_index:03d}.headers.json")

        if cached.exists() and cached_hdr.exists():
            raw = cached.read_bytes()
            headers = json.loads(cached_hdr.read_text(encoding="utf-8"))
            print(f"  page {page_index}: cache ({len(collected)} collected so far)")
        else:
            raw, headers = _get(url)
            cached.write_bytes(raw)
            cached_hdr.write_text(json.dumps(headers), encoding="utf-8", newline="\n")
            print(f"  page {page_index}: fetched ({len(collected)} collected so far)")
            time.sleep(REQUEST_INTERVAL)

        page = json.loads(raw)
        if not page:
            break
        page_index += 1

        for obs in page:
            oid = obs.get("id")
            if oid in seen:
                continue
            seen.add(oid)
            # Need TLE, station coords, timing and the API max_altitude for validation.
            if not (obs.get("tle1") and obs.get("tle2")):
                continue
            if obs.get("max_altitude") is None:
                continue
            # Skip future observations (null waterfalls, no geometry to validate)
            if obs.get("status") == "future":
                continue
            collected.append(obs)

        cursor = _next_cursor(headers.get("link") or headers.get("Link"))
        if not cursor:
            break
        url = API_BASE + "?" + urlencode({**params, "cursor": cursor})

    print(f"  collected {len(collected)} records with max_altitude across "
          f"{page_index} page(s)")
    return collected


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------


def _wrapped_difference(a: float, b: float) -> float:
    """Signed difference between two bearings, in (-180, 180].

    Plain subtraction is wrong here: a rise at 359.8 degrees against a reported 0.1
    is 0.3 degrees apart, not 359.7, and the unwrapped form would report the one
    pass that crosses north as the largest error in the set.
    """
    return (a - b + 180.0) % 360.0 - 180.0


def _distribution(name: str, values: list[float]) -> dict:
    """Signed and absolute statistics for one bearing comparison."""
    if not values:
        return {"comparison": name, "n": 0, "note": "no records carried this field"}
    arr = np.asarray(values, dtype=float)
    absolute = np.abs(arr)
    return {
        "comparison": name,
        "n": int(arr.size),
        "mean_signed_deg": float(arr.mean()),
        "sd_signed_deg": float(arr.std(ddof=1)) if arr.size > 1 else None,
        "median_abs_deg": float(np.median(absolute)),
        "p95_abs_deg": float(np.percentile(absolute, 95)),
        "max_abs_deg": float(absolute.max()),
        "pct_within_1deg": float(100.0 * np.mean(absolute <= 1.0)),
        "pct_within_3deg": float(100.0 * np.mean(absolute <= 3.0)),
    }


def validate_azimuths(observations: list[dict]) -> dict:
    """Compare pass_geometry azimuth at rise and set against the API's own fields.

    The API reports rise_azimuth and set_azimuth unrounded, so unlike max_altitude
    this comparison is limited by the physics rather than by the reference. Both
    counterfactuals are measured here too: an azimuth computed with the atan2
    arguments swapped, and one mirrored about north. Without them a median error of
    0.27 degrees is a number with nothing to compare it to.
    """
    from pipeline.tracetriage.physics import (  # noqa: PLC0415
        geodetic_normal,
        pass_geometry,
        station_ecef,
    )

    rise: list[float] = []
    setting: list[float] = []
    swapped: list[float] = []
    mirrored: list[float] = []
    n_missing = 0

    for obs in observations:
        if obs.get("rise_azimuth") is None or obs.get("set_azimuth") is None:
            n_missing += 1
            continue
        try:
            lat = float(obs["station_lat"])
            lon = float(obs["station_lng"])
            alt = float(obs["station_alt"])
            start_dt = datetime.fromisoformat(str(obs["start"]).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(obs["end"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            n_missing += 1
            continue

        geometry = pass_geometry(
            obs["tle1"], obs["tle2"], start_dt, end_dt,
            station_ecef(lat, lon, alt), geodetic_normal(lat, lon),
        )
        if not geometry.fracs:
            n_missing += 1
            continue

        first = geometry.azimuth_deg[0]
        last = geometry.azimuth_deg[-1]
        reported_rise = float(obs["rise_azimuth"])
        reported_set = float(obs["set_azimuth"])
        rise.append(_wrapped_difference(first, reported_rise))
        setting.append(_wrapped_difference(last, reported_set))
        # atan2(east, north) becomes atan2(north, east), which is 90 - azimuth.
        swapped.append(_wrapped_difference(90.0 - first, reported_rise))
        # Mirrored about north: clockwise becomes anticlockwise.
        mirrored.append(_wrapped_difference(-first, reported_rise))

    return {
        "reference": (
            "SatNOGS rise_azimuth and set_azimuth, which are unrounded, unlike "
            "max_altitude. This is the only independent check on the azimuth "
            "convention and the local East/North/Up basis, and it is the check that "
            "could have caught the geocentric up-vector defect the elevation "
            "comparison could not resolve."
        ),
        "n_missing_field_or_geometry": n_missing,
        "rise": _distribution("pass_geometry azimuth[0] vs rise_azimuth", rise),
        "set": _distribution("pass_geometry azimuth[-1] vs set_azimuth", setting),
        "counterfactuals": {
            "why": (
                "An agreement reported without the size of a wrong answer has no "
                "scale. Both of these are convention errors a reader might suspect, "
                "measured on the same records."
            ),
            "atan2_arguments_swapped": _distribution(
                "90 - azimuth[0] vs rise_azimuth", swapped
            ),
            "azimuth_mirrored_about_north": _distribution(
                "-azimuth[0] vs rise_azimuth", mirrored
            ),
        },
    }


def validate(observations: list[dict]) -> dict:
    """Compute corridors and measure max_altitude agreement.

    Returns a result dict ready for JSON serialisation.
    """
    errors_deg: list[float] = []
    records: list[dict] = []
    degraded_counts: dict[str, int] = {}
    n_success = 0
    n_degraded = 0

    for i, obs in enumerate(observations, 1):
        oid = obs.get("id")
        reported_max_alt = float(obs["max_altitude"])

        result = corridor_for_obs(obs)

        if result.degraded:
            n_degraded += 1
            degraded_counts[result.degraded] = degraded_counts.get(result.degraded, 0) + 1
            records.append({
                "obs_id": oid,
                "status": "degraded",
                "reason": result.degraded,
                "reported_max_alt_deg": reported_max_alt,
            })
            continue

        assert result.uncorrected is not None  # type narrowing
        sgp4_max_alt = result.uncorrected.max_elevation_deg
        error_deg = sgp4_max_alt - reported_max_alt
        abs_error = abs(error_deg)
        errors_deg.append(abs_error)
        n_success += 1

        records.append({
            "obs_id": oid,
            "status": "ok",
            "reported_max_alt_deg": reported_max_alt,
            "sgp4_max_alt_deg": round(sgp4_max_alt, 4),
            "error_deg": round(error_deg, 4),
            "abs_error_deg": round(abs_error, 4),
            "tca_frac": round(result.uncorrected.tca_frac, 6),
            # A culmination at the edge of the recorded window means sgp4_max_alt_deg is a
            # window boundary value rather than a pass maximum, so the row compares a
            # different quantity from the API's pass maximum. Flagged per record, because
            # a boundary case that reads as an ordinary agreement is the shape that makes
            # a distribution look better than the measurement supports.
            "culmination_inside_window": bool(
                0.001 < result.uncorrected.tca_frac < 0.999
            ),
            "tle_epoch_age_days": (
                round(result.tle_epoch_age_days, 3)
                if result.tle_epoch_age_days is not None else None
            ),
        })

        if i % 25 == 0:
            print(f"  [{i}/{len(observations)}] obs {oid}: "
                  f"sgp4={sgp4_max_alt:.2f}° api={reported_max_alt:.1f}° "
                  f"err={error_deg:+.2f}°")

    # Distribution statistics
    arr = np.asarray(errors_deg) if errors_deg else np.array([float("nan")])
    dist: dict = {
        "n_success": n_success,
        "n_degraded": n_degraded,
        "n_total": len(observations),
        "degraded_by_reason": degraded_counts,
        "mean_abs_error_deg": float(np.mean(arr)) if n_success else None,
        "median_abs_error_deg": float(np.median(arr)) if n_success else None,
        "p90_abs_error_deg": float(np.percentile(arr, 90)) if n_success else None,
        "p95_abs_error_deg": float(np.percentile(arr, 95)) if n_success else None,
        "p99_abs_error_deg": float(np.percentile(arr, 99)) if n_success else None,
        "max_abs_error_deg": float(np.max(arr)) if n_success else None,
        "pct_within_1deg": (
            float(100.0 * np.mean(arr <= 1.0)) if n_success else None
        ),
        "pct_within_2deg": (
            float(100.0 * np.mean(arr <= 2.0)) if n_success else None
        ),
        "pct_within_5deg": (
            float(100.0 * np.mean(arr <= 5.0)) if n_success else None
        ),
    }

    # How much of the distribution rests on rows whose culmination the window actually
    # contains. Publishing the flag per record and not the effect would leave a reader to
    # recompute the thing the flag exists to raise.
    inside = [
        r["abs_error_deg"] for r in records
        if r.get("status") == "ok" and r.get("culmination_inside_window")
    ]
    boundary = [
        r["obs_id"] for r in records
        if r.get("status") == "ok" and not r.get("culmination_inside_window")
    ]
    inside_arr = np.asarray(inside) if inside else np.array([float("nan")])
    dist["culmination_window"] = {
        "n_inside": len(inside),
        "n_at_boundary": len(boundary),
        "obs_at_boundary": boundary,
        "median_abs_error_deg_inside": float(np.median(inside_arr)) if inside else None,
        "max_abs_error_deg_inside": float(np.max(inside_arr)) if inside else None,
        "note": (
            "A row whose culmination sits at the edge of the recorded window compares an "
            "SGP4 window maximum against an API pass maximum, which are different "
            "quantities. The rows are counted rather than dropped, and the median beside "
            "them is over the rows that do contain their culmination, so the effect of "
            "excluding them is visible instead of argued."
        ),
    }

    # What the reference can and cannot resolve. Every max_altitude in the corpus is
    # an integer, so most of the distribution above is the API's rounding rather than
    # this project's error, and quoting 0.243 degrees as agreement claims a resolution
    # the reference does not have.
    reported = [
        float(obs["max_altitude"])
        for obs in observations
        if obs.get("max_altitude") is not None
    ]
    n_integer = sum(1 for v in reported if abs(v - round(v)) < 1e-9)
    dist["reference_quantisation"] = {
        "field": "max_altitude",
        "n_reported": len(reported),
        "n_integer_valued": n_integer,
        "all_integer": n_integer == len(reported) and bool(reported),
        "uniform_rounding_mean_abs_deg": 0.25,
        "uniform_rounding_sd_deg": 0.2887,
        "implication": (
            "The reference is quantised to one degree, so this comparison bounds the "
            "elevation error at roughly half a degree and cannot resolve anything "
            "finer. The measured mean absolute error is close to the 0.250 a pure "
            "rounding error would give on its own, so agreement here is evidence "
            "against a gross error and not evidence of tenth-of-a-degree accuracy. "
            "The azimuth comparison beside it is the unrounded one."
        ),
    }

    # The epoch-age distribution, so a reader can see whether the staleness threshold
    # is doing any work. It is not: the threshold is a bound on how wrong a corridor
    # may be, and nothing in this corpus is near it. Publishing the distribution is
    # what stops that being an assumption.
    ages = [
        r["tle_epoch_age_days"]
        for r in records
        if r.get("tle_epoch_age_days") is not None
    ]
    if ages:
        age_arr = np.asarray(ages, dtype=float)
        dist["tle_epoch_age"] = {
            "n": int(age_arr.size),
            "min_days": float(age_arr.min()),
            "median_days": float(np.median(age_arr)),
            "max_days": float(age_arr.max()),
            "n_over_1_day": int((age_arr > 1.0).sum()),
            "threshold_days": TLE_MAX_EPOCH_AGE_DAYS,
            "n_over_threshold": int((age_arr > TLE_MAX_EPOCH_AGE_DAYS).sum()),
            "note": (
                "The threshold is derived from the corridor half-width and the "
                "measured peak Doppler slope, and on this corpus it is inert: the "
                "oldest epoch here is far inside it. A threshold nothing has been "
                "near is a bound rather than a filter, and it has never been "
                "exercised on real data at its own boundary."
            ),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "end_date_filter": END_DATE,
        "n_observations_fetched": len(observations),
        "distribution": dist,
        "azimuth_agreement": validate_azimuths(observations),
        "observations": records,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        observations = fetch_observations(TARGET_OBS, MAX_PAGES)
    except Throttled as exc:
        sys.exit(
            f"API rate-limited before enough records were fetched: {exc}.\n"
            f"Cached pages are under {CACHE_DIR}; a rerun continues from there."
        )

    if len(observations) < TARGET_OBS:
        print(
            f"WARNING: only {len(observations)} records collected against a "
            f"target of {TARGET_OBS}.  Increase A4_MAX_PAGES or wait for more "
            f"records to become available.  Validation will run on what was collected."
        )

    print(f"\nValidating {len(observations)} observations...")
    result = validate(observations)
    dist = result["distribution"]

    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="\n")
    print(f"\nWrote {OUT_PATH}")

    print("\n--- max_altitude error distribution ---")
    print(f"  n_success : {dist['n_success']}")
    print(f"  n_degraded: {dist['n_degraded']} ({dist['degraded_by_reason']})")
    print(f"  mean abs error : {dist['mean_abs_error_deg']:.4f}°")
    print(f"  median abs err : {dist['median_abs_error_deg']:.4f}°")
    print(f"  p90  abs error : {dist['p90_abs_error_deg']:.4f}°")
    print(f"  p95  abs error : {dist['p95_abs_error_deg']:.4f}°")
    print(f"  p99  abs error : {dist['p99_abs_error_deg']:.4f}°")
    print(f"  max  abs error : {dist['max_abs_error_deg']:.4f}°")
    print(f"  within  1 deg  : {dist['pct_within_1deg']:.1f}%")
    print(f"  within  2 deg  : {dist['pct_within_2deg']:.1f}%")
    print(f"  within  5 deg  : {dist['pct_within_5deg']:.1f}%")
    quant = dist["reference_quantisation"]
    print(
        f"  reference      : {quant['n_integer_valued']}/{quant['n_reported']} "
        f"max_altitude values are integers"
    )
    if quant["all_integer"]:
        print(
            "                   so this bounds the error near half a degree and "
            "resolves nothing finer"
        )

    az = result["azimuth_agreement"]
    print("\n--- azimuth agreement (unrounded reference) ---")
    for key in ("rise", "set"):
        d = az[key]
        if not d.get("n"):
            print(f"  {key:5s}: no records")
            continue
        print(
            f"  {key:5s}: n={d['n']} mean={d['mean_signed_deg']:+.3f}deg "
            f"median abs={d['median_abs_deg']:.3f}deg "
            f"max abs={d['max_abs_deg']:.3f}deg "
            f"within 1deg={d['pct_within_1deg']:.1f}%"
        )
    for name, d in az["counterfactuals"].items():
        if name == "why" or not isinstance(d, dict) or not d.get("n"):
            continue
        print(f"  counterfactual {name}: median abs={d['median_abs_deg']:.1f}deg")


if __name__ == "__main__":
    main()
