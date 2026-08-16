"""Immutable snapshot builder, unit A1.

CLI
---
    .venv/Scripts/python.exe -m pipeline.tracetriage.snapshot \\
        --end 2026-08-16T00:00:00Z \\
        --target-waterfalls 2300 \\
        --out data/snapshots/stage1/

Fetches public SatNOGS observations up to --end, downloads every waterfall
PNG, and writes an immutable manifest to artifacts/DATASET_MANIFEST.json.

Design rules (all mandatory, from unit A1 acceptance):
  - Raw API JSON is stored per page, sha256'd.
  - Per observation: UTC retrieval time, source URL, sha256 of waterfall bytes,
    CC BY-SA 4.0 license string, schema_version.
  - Resumable: a re-run skips any page and any artifact already stored and
    verified.
  - Manifest validates against contracts/dataset_manifest.schema.json.
  - client_version kept verbatim; client_family strips +N.gSHA and .dirty.
  - 0.4 s between requests; real User-Agent with contact address.
  - Free-space check before stage starts; abort clearly if short.
  - Paging via Link: <...>; rel="next" cursor header only.
  - end= (not end__lte=) for the date bound.
  - waterfall_status filtered client-side (API returns HTTP 400 for it).

Traps (from SATNOGS_API_RECON.md section 4, do NOT touch these):
  - end__lte= is silently ignored by the API. Use bare end= only.
  - waterfall_status= is not a filter; returns HTTP 400. Filter client-side.
  - A bare listing returns future observations with null waterfalls. Always
    date-bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jsonschema

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://network.satnogs.org/api/observations/"
WATERFALL_TIMEOUT = 60          # seconds for waterfall PNG download
API_TIMEOUT = 30                # seconds for metadata calls
REQUEST_INTERVAL = 0.4          # seconds between requests (floor agreed in contract)
USER_AGENT = (
    "tracetriage/0.1 (+https://github.com/Kesav2k04/tracetriage-august-2026;"
    " kesavk659@gmail.com)"
)
LICENSE_STR = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
SCHEMA_VERSION = "0.2.1"
MIN_FREE_BYTES = 6 * 1024 ** 3  # 6 GB safety margin before aborting

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "contracts" / "dataset_manifest.schema.json"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"

log = logging.getLogger("snapshot")

# ---------------------------------------------------------------------------
# Client-version normalisation
# ---------------------------------------------------------------------------

_DIRTY_RE = re.compile(r"[+.][0-9]+\.g[0-9a-f]{6,}(\.dirty)?$|\.dirty$")


def normalise_client_family(raw: str | None) -> str | None:
    """Strip +N.gSHA and .dirty suffixes from a gr-satnogs version string.

    >>> normalise_client_family("2.1.2+1.gcded8f6.dirty")
    '2.1.2'
    >>> normalise_client_family("1.9.3+5.g4ee1234")
    '1.9.3'
    >>> normalise_client_family("2.1.2")
    '2.1.2'
    >>> normalise_client_family(None) is None
    True
    >>> normalise_client_family("") is None
    True
    """
    if not raw:
        return None
    cleaned = _DIRTY_RE.sub("", raw.strip())
    return cleaned if cleaned else None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def make_client(timeout: float = API_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )


def extract_next_cursor(link_header: str | None) -> str | None:
    """Parse the Link: <url>; rel="next" header and return just the cursor
    parameter, or None if there is no next page.

    The API pages via a cursor= query parameter embedded in the Link header.
    We extract only the cursor value so we can construct a clean next URL
    rather than blindly following a link that might carry stale other params.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            m = re.search(r"<([^>]+)>", part)
            if m:
                parsed = urlparse(m.group(1))
                qs = parse_qs(parsed.query)
                cursors = qs.get("cursor")
                if cursors:
                    return cursors[0]
    return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Disk helpers
# ---------------------------------------------------------------------------

def check_free_space(path: Path, required: int = MIN_FREE_BYTES) -> None:
    """Abort clearly if there is not enough free space."""
    usage = shutil.disk_usage(path)
    if usage.free < required:
        gb = usage.free / 1024 ** 3
        need = required / 1024 ** 3
        sys.exit(
            f"ABORT: only {gb:.1f} GB free on {path.anchor}; "
            f"need at least {need:.0f} GB for the snapshot. "
            f"Free space or point --out to a drive with more room. "
            f"Exiting rather than a partial download."
        )


def write_page_json(pages_dir: Path, page_index: int, raw: bytes) -> Path:
    p = pages_dir / f"page_{page_index:05d}.json"
    p.write_bytes(raw)
    return p


def waterfall_path(wf_dir: Path, obs_id: int) -> Path:
    return wf_dir / f"waterfall_{obs_id}.png"


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {}


def save_manifest(manifest_path: Path, doc: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def validate_manifest(doc: dict[str, Any]) -> None:
    schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    validator_cls = jsonschema.validators.validator_for(schema)
    v = validator_cls(schema)
    errors = list(v.iter_errors(doc))
    if errors:
        msgs = "\n".join(f"  {e.json_path}: {e.message}" for e in errors[:5])
        raise RuntimeError(f"Manifest failed schema validation:\n{msgs}")


def build_resume_index(manifest: dict[str, Any]) -> dict[int, str | None]:
    """Return {obs_id: sha256_or_None} for observations already stored."""
    return {
        entry["id"]: entry.get("waterfall_sha256")
        for entry in manifest.get("observations", [])
    }


def build_page_index(manifest: dict[str, Any]) -> set[str]:
    """Return the set of page URLs already fetched."""
    return {p["url"] for p in manifest.get("pages", [])}


# ---------------------------------------------------------------------------
# Waterfall download
# ---------------------------------------------------------------------------

def download_waterfall(
    client: httpx.Client,
    obs_id: int,
    url: str,
    dest: Path,
) -> tuple[str | None, int | None, str | None]:
    """Download a waterfall PNG. Returns (sha256, byte_count, missing_reason).

    missing_reason is None on success; one of the enum values on failure.
    Truncation check: a PNG header is 8 bytes; anything shorter is TRUNCATED.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = client.get(url, timeout=WATERFALL_TIMEOUT)
    except httpx.TimeoutException:
        log.warning("TIMEOUT waterfall obs %d", obs_id)
        return None, None, "TIMEOUT"
    except httpx.HTTPError as exc:
        log.warning("HTTP_ERROR waterfall obs %d: %s", obs_id, exc)
        return None, None, "HTTP_ERROR"

    if r.status_code == 404:
        log.warning("HTTP_404 waterfall obs %d", obs_id)
        return None, None, "HTTP_404"
    if r.status_code != 200:
        log.warning("HTTP_ERROR waterfall obs %d: status %d", obs_id, r.status_code)
        return None, None, "HTTP_ERROR"

    data = r.content
    if len(data) == 0:
        log.warning("ZERO_BYTE waterfall obs %d", obs_id)
        return None, None, "ZERO_BYTE"
    if len(data) < 8:
        log.warning("TRUNCATED waterfall obs %d: only %d bytes", obs_id, len(data))
        return None, None, "TRUNCATED"
    # PNG magic: \x89PNG\r\n\x1a\n
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        log.warning("TRUNCATED waterfall obs %d: not a valid PNG header", obs_id)
        return None, None, "TRUNCATED"

    dest.write_bytes(data)
    digest = sha256_bytes(data)
    log.debug("stored waterfall obs %d  sha=%s  bytes=%d", obs_id, digest[:12], len(data))
    return digest, len(data), None


# ---------------------------------------------------------------------------
# Observation record parsing
# ---------------------------------------------------------------------------

def parse_client_version(obs: dict[str, Any]) -> str | None:
    """Extract the raw client_version string.

    client_version is a top-level field on the observation record as confirmed
    by SATNOGS_API_RECON.md. Return None (not empty string) when absent/empty.
    """
    raw = obs.get("client_version")
    if not raw or not str(raw).strip():
        return None
    return str(raw).strip()


def build_observation_entry(
    obs: dict[str, Any],
    wf_sha256: str | None,
    wf_bytes: int | None,
    wf_missing_reason: str | None,
    retrieved_at: str,
    waterfall_url: str | None,
) -> dict[str, Any]:
    client_version = parse_client_version(obs)
    return {
        "id": obs["id"],
        "source_url": f"https://network.satnogs.org/api/observations/{obs['id']}/",
        "retrieved_at": retrieved_at,
        "waterfall_url": waterfall_url,
        "waterfall_sha256": wf_sha256,
        "waterfall_bytes": wf_bytes,
        "waterfall_missing_reason": wf_missing_reason,
        "waterfall_status": obs.get("waterfall_status"),
        "ground_station": obs.get("ground_station"),
        "norad_cat_id": obs.get("norad_cat_id"),
        "transmitter_uuid": obs.get("transmitter_uuid"),
        "client_version": client_version,
        "client_family": normalise_client_family(client_version),
        "license": LICENSE_STR,
        "license_url": LICENSE_URL,
        "schema_version": SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Core snapshot loop
# ---------------------------------------------------------------------------

def run_snapshot(
    end: str,
    target_waterfalls: int,
    out_dir: Path,
    snapshot_id: str,
    stage: int = 1,
    sampling_design: str = "Single contiguous window ending at --end, stage 1 debug snapshot.",
) -> None:
    """Fetch observations and waterfalls, write the manifest.

    Resumable: if a partial manifest exists, pages and waterfalls already
    stored and verified are skipped entirely.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_dir = out_dir / "pages"
    wf_dir = out_dir / "waterfalls"
    pages_dir.mkdir(exist_ok=True)
    wf_dir.mkdir(exist_ok=True)

    # The manifest is this snapshot's own resume index, so it lives WITH the
    # snapshot. A single global path made every snapshot share one resume state:
    # running stage 2 into a different --out would load stage 1's observations,
    # skip them as already fetched, and then emit a manifest describing files
    # that are not in the directory it names. The plan runs stage 2 in the
    # background during Wave B while stage 1 is in use, so that collision was
    # reachable by design, not hypothetical.
    manifest_path = out_dir / "DATASET_MANIFEST.json"
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    # Disk space check on the target drive (check both dirs)
    check_free_space(out_dir, MIN_FREE_BYTES)

    # Load any existing manifest for resume
    existing = load_manifest(manifest_path)
    resume_obs = build_resume_index(existing)
    fetched_page_urls = build_page_index(existing)

    built_at = existing.get("built_at") or datetime.now(UTC).isoformat()

    log.info(
        "snapshot %s  end=%s  target=%d  resuming from %d obs / %d pages",
        snapshot_id, end, target_waterfalls, len(resume_obs), len(fetched_page_urls),
    )

    pages_list: list[dict[str, Any]] = list(existing.get("pages", []))
    observations_list: list[dict[str, Any]] = list(existing.get("observations", []))

    waterfalls_stored = sum(
        1 for o in observations_list if o.get("waterfall_missing_reason") is None
    )
    waterfalls_missing = sum(
        1 for o in observations_list if o.get("waterfall_missing_reason") is not None
    )

    # Build initial next_url for first (possibly resumed) page
    params: dict[str, Any] = {
        "format": "json",
        "end": end,
    }
    first_url = BASE_URL + "?" + urlencode(params)

    # Determine where to resume paging. If we have pages already, the last
    # page's cursor tells us the next URL to fetch. If no cursor on the last
    # page, fetching is complete (was on the last page already).
    if pages_list:
        last_cursor = pages_list[-1].get("cursor")
        if last_cursor is None:
            # Previous run reached the final page; nothing left to page.
            next_url: str | None = None
        else:
            next_url = BASE_URL + "?" + urlencode({**params, "cursor": last_cursor})
    else:
        next_url = first_url

    page_index = len(pages_list)

    api_client = make_client(API_TIMEOUT)
    wf_client = make_client(WATERFALL_TIMEOUT)

    try:
        while next_url and waterfalls_stored < target_waterfalls:
            # ---- fetch page ----
            if next_url in fetched_page_urls:
                log.debug("skip already-fetched page %s", next_url)
                # Advance cursor from stored page record
                for p in pages_list:
                    if p["url"] == next_url:
                        c = p.get("cursor")
                        next_url = (
                            BASE_URL + "?" + urlencode({**params, "cursor": c})
                            if c else None
                        )
                        break
                continue

            log.info("fetching page %d  url=%s", page_index, next_url)
            time.sleep(REQUEST_INTERVAL)

            try:
                resp = api_client.get(next_url, timeout=API_TIMEOUT)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                log.error("HTTP error %d fetching page: %s", exc.response.status_code, next_url)
                raise

            raw_bytes = resp.content
            page_sha = sha256_bytes(raw_bytes)
            retrieved_at = datetime.now(UTC).isoformat()

            try:
                page_data = json.loads(raw_bytes)
            except json.JSONDecodeError as exc:
                log.error("JSON decode error on page %d: %s", page_index, exc)
                raise

            # Validate the date bound was respected by checking returned records.
            # end__lte= is silently ignored; bare end= works correctly.
            # The assertion below is the regression guard for that trap.
            for rec in page_data if isinstance(page_data, list) else []:
                obs_end = rec.get("end", "")
                if obs_end and obs_end > end:
                    log.error(
                        "DATE BOUND VIOLATED: obs %d has end=%s > cutoff=%s. "
                        "The date filter is not working. Stop.",
                        rec.get("id"), obs_end, end,
                    )
                    raise RuntimeError(
                        f"Observation {rec.get('id')} has end={obs_end} > cutoff={end}. "
                        "The API date bound is not being applied. "
                        "Check that end= (not end__lte=) is in the request."
                    )

            # Store raw page
            page_file = write_page_json(pages_dir, page_index, raw_bytes)
            log.debug("stored page %d -> %s  sha=%s", page_index, page_file.name, page_sha[:12])

            cursor = extract_next_cursor(resp.headers.get("link"))

            n_obs = len(page_data) if isinstance(page_data, list) else 0
            pages_list.append({
                "url": next_url,
                "sha256": page_sha,
                "retrieved_at": retrieved_at,
                "n_observations": n_obs,
                "cursor": cursor,
            })
            fetched_page_urls.add(next_url)

            # ---- process each observation on this page ----
            obs_list = page_data if isinstance(page_data, list) else []
            for obs in obs_list:
                obs_id: int = obs["id"]

                if obs_id in resume_obs:
                    # Already processed in a previous run
                    log.debug("skip already-stored obs %d", obs_id)
                    continue

                obs_retrieved_at = datetime.now(UTC).isoformat()
                wf_url: str | None = obs.get("waterfall") or None

                if not wf_url:
                    entry = build_observation_entry(
                        obs, None, None, "NO_WATERFALL_URL", obs_retrieved_at, None
                    )
                    observations_list.append(entry)
                    resume_obs[obs_id] = None
                    waterfalls_missing += 1
                    log.debug("obs %d: no waterfall URL", obs_id)
                    continue

                # Download waterfall
                dest = waterfall_path(wf_dir, obs_id)
                time.sleep(REQUEST_INTERVAL)
                sha, nbytes, reason = download_waterfall(wf_client, obs_id, wf_url, dest)

                if reason is not None:
                    entry = build_observation_entry(
                        obs, None, None, reason, obs_retrieved_at, wf_url
                    )
                    observations_list.append(entry)
                    resume_obs[obs_id] = None
                    waterfalls_missing += 1
                else:
                    entry = build_observation_entry(
                        obs, sha, nbytes, None, obs_retrieved_at, wf_url
                    )
                    observations_list.append(entry)
                    resume_obs[obs_id] = sha
                    waterfalls_stored += 1

                # Write partial manifest after every observation so resuming
                # after an interrupt loses at most one observation.
                _write_partial_manifest(
                    manifest_path, snapshot_id, stage, built_at, None,
                    end, target_waterfalls, sampling_design,
                    pages_list, observations_list, waterfalls_stored, waterfalls_missing,
                    page_index,
                )

                if waterfalls_stored >= target_waterfalls:
                    log.info("reached target %d waterfalls; stopping.", target_waterfalls)
                    break

            page_index += 1
            next_url = (
                BASE_URL + "?" + urlencode({**params, "cursor": cursor})
                if cursor else None
            )

    finally:
        api_client.close()
        wf_client.close()

    completed_at = datetime.now(UTC).isoformat()

    # Count decisive labels
    decisive = sum(
        1 for o in observations_list
        if o.get("waterfall_status") in ("with-signal", "without-signal")
    )

    manifest_doc = _build_manifest(
        snapshot_id=snapshot_id,
        stage=stage,
        built_at=built_at,
        completed_at=completed_at,
        end=end,
        target_waterfalls=target_waterfalls,
        sampling_design=sampling_design,
        pages_list=pages_list,
        observations_list=observations_list,
        waterfalls_stored=waterfalls_stored,
        waterfalls_missing=waterfalls_missing,
        decisive=decisive,
    )

    validate_manifest(manifest_doc)
    save_manifest(manifest_path, manifest_doc)

    # Unit A1 names artifacts/DATASET_MANIFEST.json as the deliverable path, so
    # mirror the canonical manifest there once the run has actually completed.
    # Only a completed run is mirrored: a partial snapshot must never present
    # itself as the project's current dataset.
    save_manifest(ARTIFACTS_DIR / "DATASET_MANIFEST.json", manifest_doc)

    log.info(
        "done. obs=%d  waterfalls=%d  missing=%d  decisive=%d  pages=%d",
        len(observations_list), waterfalls_stored, waterfalls_missing, decisive, len(pages_list),
    )
    log.info("manifest: %s", manifest_path)


# ---------------------------------------------------------------------------
# Partial manifest writer (called after every observation for resume safety)
# ---------------------------------------------------------------------------

def _write_partial_manifest(
    manifest_path: Path,
    snapshot_id: str,
    stage: int,
    built_at: str,
    completed_at: str | None,
    end: str,
    target_waterfalls: int,
    sampling_design: str,
    pages_list: list[dict[str, Any]],
    observations_list: list[dict[str, Any]],
    waterfalls_stored: int,
    waterfalls_missing: int,
    page_index: int,
) -> None:
    doc = _build_manifest(
        snapshot_id=snapshot_id,
        stage=stage,
        built_at=built_at,
        completed_at=completed_at,
        end=end,
        target_waterfalls=target_waterfalls,
        sampling_design=sampling_design,
        pages_list=pages_list,
        observations_list=observations_list,
        waterfalls_stored=waterfalls_stored,
        waterfalls_missing=waterfalls_missing,
        decisive=None,
    )
    save_manifest(manifest_path, doc)


def _build_manifest(
    *,
    snapshot_id: str,
    stage: int,
    built_at: str,
    completed_at: str | None,
    end: str,
    target_waterfalls: int,
    sampling_design: str,
    pages_list: list[dict[str, Any]],
    observations_list: list[dict[str, Any]],
    waterfalls_stored: int,
    waterfalls_missing: int,
    decisive: int | None,
) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "observations_requested": target_waterfalls,
        "observations_stored": len(observations_list),
        "waterfalls_stored": waterfalls_stored,
        "waterfalls_missing": waterfalls_missing,
        "pages_fetched": len(pages_list),
    }
    if decisive is not None:
        counts["waterfall_status_decisive"] = decisive

    return {
        "snapshot_id": snapshot_id,
        "schema_version": SCHEMA_VERSION,
        "stage": stage,
        "built_at": built_at,
        "completed_at": completed_at,
        "query": {
            "base_url": BASE_URL,
            "end": end,
            "target_waterfalls": target_waterfalls,
            "filters": {},
            "user_agent": USER_AGENT,
            "request_interval_seconds": REQUEST_INTERVAL,
        },
        "counts": counts,
        "sampling_design": sampling_design,
        "license": LICENSE_STR,
        "license_url": LICENSE_URL,
        "pages": pages_list,
        "observations": observations_list,
    }


# ---------------------------------------------------------------------------
# SHA-256 verification
# ---------------------------------------------------------------------------

def verify_sha256(wf_dir: Path, observations: list[dict[str, Any]]) -> list[str]:
    """Verify every stored waterfall's sha256 matches the manifest entry.

    Returns a list of error strings; empty means all OK.
    """
    errors: list[str] = []
    for obs in observations:
        if obs.get("waterfall_missing_reason") is not None:
            continue
        obs_id = obs["id"]
        expected = obs.get("waterfall_sha256")
        if not expected:
            errors.append(f"obs {obs_id}: manifest entry has no sha256 but missing_reason is null")
            continue
        fpath = waterfall_path(wf_dir, obs_id)
        if not fpath.exists():
            errors.append(f"obs {obs_id}: waterfall file missing at {fpath}")
            continue
        actual = sha256_bytes(fpath.read_bytes())
        if actual != expected:
            errors.append(
                f"obs {obs_id}: sha256 mismatch  expected={expected[:12]}  actual={actual[:12]}"
            )
    return errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build an immutable snapshot of public SatNOGS observations.",
    )
    p.add_argument(
        "--end",
        default=None,
        help=(
            "Upper date bound (ISO 8601, UTC). Sent as a bare end= parameter. "
            "Required unless --verify is given."
        ),
    )
    p.add_argument(
        "--target-waterfalls",
        type=int,
        default=None,
        help=(
            "Stop after collecting this many usable waterfall artifacts. "
            "Required unless --verify is given, deliberately: this previously "
            "defaulted to 2300, so any invocation that omitted it silently "
            "began a production-scale crawl against a volunteer-run public API."
        ),
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory for pages/, waterfalls/ and partial manifests.",
    )
    p.add_argument(
        "--snapshot-id",
        default=None,
        help="Snapshot identifier. Defaults to snap-<date>-stage1.",
    )
    p.add_argument(
        "--stage",
        type=int,
        default=1,
        choices=[1, 2],
        help="Stage number (1=debug, 2=stratified). Default: 1.",
    )
    p.add_argument(
        "--sampling-design",
        default="Single contiguous window ending at --end, stage 1 debug snapshot.",
        help="Plain-language description of the sampling strategy.",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Verification mode. Re-hash every stored waterfall in --out against "
            "its manifest entry and exit. Fetches nothing, so --end and "
            "--target-waterfalls are not needed with it."
        ),
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Debug logging.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )

    out_dir = args.out.resolve()

    # --verify is a verification MODE, not a post-fetch step. It used to run
    # after run_snapshot(), which meant there was no way to check an existing
    # snapshot without first completing a full crawl. Combined with the old
    # --target-waterfalls default, a bare --verify pulled 578 observations and
    # 870 MB before it was interrupted.
    if args.verify:
        manifest_path = out_dir / "DATASET_MANIFEST.json"
        if not manifest_path.exists():
            sys.exit(f"no manifest at {manifest_path}; nothing to verify")
        manifest = load_manifest(manifest_path)
        observations = manifest.get("observations", [])
        errors = verify_sha256(out_dir / "waterfalls", observations)
        if errors:
            for e in errors:
                log.error(e)
            sys.exit(f"{len(errors)} sha256 verification failures")
        log.info("all sha256 verified OK across %d observations", len(observations))
        return

    if args.end is None or args.target_waterfalls is None:
        sys.exit("--end and --target-waterfalls are required unless --verify is given")

    snapshot_id = args.snapshot_id or (
        "snap-" + args.end[:10] + f"-stage{args.stage}"
    )

    run_snapshot(
        end=args.end,
        target_waterfalls=args.target_waterfalls,
        out_dir=out_dir,
        snapshot_id=snapshot_id,
        stage=args.stage,
        sampling_design=args.sampling_design,
    )


if __name__ == "__main__":
    main()
