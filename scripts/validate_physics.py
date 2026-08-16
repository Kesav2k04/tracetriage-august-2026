"""A4 physics validation: max_altitude agreement over ≥200 observations.

Fetches live observation records from the SatNOGS API, computes the physics
corridor for each, and compares the SGP4-derived max_elevation_deg against the
API-reported max_altitude field.  Writes the error distribution to
artifacts/PHYSICS_VALIDATION.json.

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

from pipeline.tracetriage.physics import corridor_for_obs  # noqa: E402

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
OUT_PATH = REPO / "artifacts" / "PHYSICS_VALIDATION.json"

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
            cached_hdr.write_text(json.dumps(headers), encoding="utf-8")
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

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "end_date_filter": END_DATE,
        "n_observations_fetched": len(observations),
        "distribution": dist,
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

    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
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


if __name__ == "__main__":
    main()
