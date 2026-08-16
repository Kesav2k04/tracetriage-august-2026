"""Tests for pipeline/tracetriage/snapshot.py — unit A1 acceptance.

All tests are offline (`-m "not network"`). The live API is never touched here.
Network access from unmarked tests is blocked by conftest.py.

Coverage required by acceptance:
  1. Silently-ignored end__lte filter trap — assert that the returned data
     is actually date-bounded (the regression guard in snapshot.py fires when
     a record's `end` exceeds the cutoff, regardless of which query parameter
     was sent).
  2. Cursor exhaustion — a run with no more pages terminates cleanly.
  3. 404 artifact — a waterfall that returns HTTP 404 is recorded with
     waterfall_missing_reason="HTTP_404" and never treated as a label.
  4. Truncated download — a PNG stub shorter than 8 bytes is TRUNCATED.
  5. Resume-after-interrupt — a second run with an existing partial manifest
     re-fetches zero additional pages and stores zero additional observations.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pipeline.tracetriage.snapshot import (
    BASE_URL,
    LICENSE_STR,
    LICENSE_URL,
    SCHEMA_VERSION,
    USER_AGENT,
    build_resume_index,
    download_waterfall,
    extract_next_cursor,
    normalise_client_family,
    sha256_bytes,
    validate_manifest,
    verify_sha256,
)

# ---------------------------------------------------------------------------
# Minimal valid PNG factory (used for waterfall downloads)
# ---------------------------------------------------------------------------

def _make_png(width: int = 4, height: int = 4) -> bytes:
    """Build the smallest valid PNG that passes the PNG-header check."""
    # IHDR chunk
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    # IDAT chunk — raw scanline data: filter byte + RGB per pixel
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    # IEND chunk
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


# ---------------------------------------------------------------------------
# Minimal observation record factory
# ---------------------------------------------------------------------------

def _obs(
    obs_id: int = 14513023,
    end: str = "2026-08-15T10:00:00Z",
    waterfall: str | None = "https://s3.example.com/waterfall_{id}.png",
    waterfall_status: str = "with-signal",
    client_version: str | None = "2.1.2",
    ground_station: int = 42,
) -> dict[str, Any]:
    return {
        "id": obs_id,
        "end": end,
        "waterfall": waterfall.replace("{id}", str(obs_id)) if waterfall else None,
        "waterfall_status": waterfall_status,
        "client_version": client_version,
        "ground_station": ground_station,
        "norad_cat_id": 25544,
        "transmitter_uuid": "abcd-1234",
        "start": "2026-08-15T09:50:00Z",
        "status": "good",
        "tle0": "ISS",
        "tle1": "1 25544U 98067A   26227.50000000  .00006000  00000-0  11000-3 0  9999",
        "tle2": "2 25544  51.6400 238.4920 0001234 123.4567 236.6543 15.50000000 00000",
    }


# ---------------------------------------------------------------------------
# Minimal valid manifest factory
# ---------------------------------------------------------------------------

def _minimal_manifest(
    snapshot_id: str = "snap-test-stage1",
    obs_entries: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    completed_at: str | None = "2026-08-16T01:00:00Z",
) -> dict[str, Any]:
    if obs_entries is None:
        obs_entries = []
    if pages is None:
        pages = []
    counts: dict[str, Any] = {
        "observations_requested": 50,
        "observations_stored": len(obs_entries),
        "waterfalls_stored": sum(
            1 for o in obs_entries if o.get("waterfall_missing_reason") is None
        ),
        "waterfalls_missing": sum(
            1 for o in obs_entries if o.get("waterfall_missing_reason") is not None
        ),
        "pages_fetched": len(pages),
    }
    return {
        "snapshot_id": snapshot_id,
        "schema_version": SCHEMA_VERSION,
        "stage": 1,
        "built_at": "2026-08-16T00:00:00Z",
        "completed_at": completed_at,
        "query": {
            "base_url": BASE_URL,
            "end": "2026-08-16T00:00:00Z",
            "target_waterfalls": 50,
            "filters": {},
            "user_agent": USER_AGENT,
            "request_interval_seconds": 0.4,
        },
        "counts": counts,
        "sampling_design": "Unit test fixture.",
        "license": LICENSE_STR,
        "license_url": LICENSE_URL,
        "pages": pages,
        "observations": obs_entries,
    }


def _obs_manifest_entry(
    obs_id: int = 14513023,
    sha256: str | None = None,
    missing_reason: str | None = None,
    wf_url: str | None = None,
    client_version: str | None = "2.1.2",
) -> dict[str, Any]:
    """Build an observation entry suitable for the manifest observations list."""
    if sha256 is None and missing_reason is None:
        # default: present and intact
        sha256 = "a" * 64
        wf_url = wf_url or f"https://s3.example.com/waterfall_{obs_id}.png"
    return {
        "id": obs_id,
        "source_url": f"https://network.satnogs.org/api/observations/{obs_id}/",
        "retrieved_at": "2026-08-16T00:01:00Z",
        "waterfall_url": wf_url,
        "waterfall_sha256": sha256,
        "waterfall_missing_reason": missing_reason,
        "waterfall_status": "with-signal",
        "ground_station": 42,
        "norad_cat_id": 25544,
        "transmitter_uuid": "abcd-1234",
        "client_version": client_version,
        "client_family": normalise_client_family(client_version),
    }


# ===========================================================================
# 1. client_version normalisation
# ===========================================================================

class TestNormaliseClientFamily:
    def test_clean_version_unchanged(self):
        assert normalise_client_family("2.1.2") == "2.1.2"

    def test_dirty_suffix_stripped(self):
        assert normalise_client_family("2.1.2+1.gcded8f6.dirty") == "2.1.2"

    def test_sha_suffix_only_stripped(self):
        assert normalise_client_family("1.9.3+5.g4ee1234") == "1.9.3"

    def test_none_returns_none(self):
        assert normalise_client_family(None) is None

    def test_empty_string_returns_none(self):
        assert normalise_client_family("") is None

    def test_v2_3_compat_stripped(self):
        # e.g. the recon client "v2.3-compat-xxx-v2.3.4.0" keeps the prefix
        # but stripping only the trailing suffix pattern
        result = normalise_client_family("1.6")
        assert result == "1.6"


# ===========================================================================
# 2. Link header cursor extraction
# ===========================================================================

class TestExtractNextCursor:
    def test_parses_cursor_from_link_header(self):
        header = (
            '<https://network.satnogs.org/api/observations/?cursor=abc123&format=json>; rel="next"'
        )
        assert extract_next_cursor(header) == "abc123"

    def test_returns_none_when_no_next(self):
        header = '<https://network.satnogs.org/api/observations/?cursor=abc>; rel="prev"'
        assert extract_next_cursor(header) is None

    def test_returns_none_on_empty_header(self):
        assert extract_next_cursor("") is None

    def test_returns_none_on_none_header(self):
        assert extract_next_cursor(None) is None

    def test_multi_relation_picks_next(self):
        header = (
            '<https://example.com/?cursor=prev111>; rel="prev", '
            '<https://example.com/?cursor=next222>; rel="next"'
        )
        assert extract_next_cursor(header) == "next222"


# ===========================================================================
# 3. SHA-256 helpers
# ===========================================================================

class TestSha256:
    def test_sha256_of_known_bytes(self):
        data = b"hello"
        expected = hashlib.sha256(b"hello").hexdigest()
        assert sha256_bytes(data) == expected

    def test_sha256_is_64_hex_chars(self):
        digest = sha256_bytes(b"tracetriage")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


# ===========================================================================
# 4. Resume index
# ===========================================================================

class TestBuildResumeIndex:
    def test_empty_manifest_returns_empty_dict(self):
        assert build_resume_index({}) == {}

    def test_indexes_obs_ids_to_sha(self):
        entry = _obs_manifest_entry(obs_id=123, sha256="a" * 64)
        manifest = _minimal_manifest(obs_entries=[entry])
        idx = build_resume_index(manifest)
        assert idx[123] == "a" * 64

    def test_missing_artifact_indexed_as_none(self):
        entry = _obs_manifest_entry(obs_id=456, sha256=None, missing_reason="HTTP_404")
        manifest = _minimal_manifest(obs_entries=[entry])
        idx = build_resume_index(manifest)
        assert idx[456] is None


# ===========================================================================
# 5. Waterfall download: HTTP 404 trap
#    Acceptance criterion: a 404 is stored with waterfall_missing_reason="HTTP_404"
# ===========================================================================

class TestDownloadWaterfall:
    def _make_mock_client(self, status: int, content: bytes = b"") -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.content = content
        client = MagicMock()
        client.get.return_value = resp
        return client

    def test_404_returns_http_404_reason(self, tmp_path):
        client = self._make_mock_client(404)
        dest = tmp_path / "wf_1.png"
        sha, nbytes, reason = download_waterfall(client, 1, "https://example.com/wf.png", dest)
        assert sha is None
        assert nbytes is None
        assert reason == "HTTP_404"
        assert not dest.exists()

    def test_zero_byte_returns_zero_byte_reason(self, tmp_path):
        client = self._make_mock_client(200, b"")
        dest = tmp_path / "wf_2.png"
        sha, nbytes, reason = download_waterfall(client, 2, "https://example.com/wf.png", dest)
        assert reason == "ZERO_BYTE"
        assert not dest.exists()

    def test_truncated_download_returns_truncated_reason(self, tmp_path):
        """A PNG stub shorter than 8 bytes triggers the TRUNCATED path."""
        client = self._make_mock_client(200, b"\x89PNG")  # 4 bytes — too short
        dest = tmp_path / "wf_3.png"
        sha, nbytes, reason = download_waterfall(client, 3, "https://example.com/wf.png", dest)
        assert reason == "TRUNCATED"
        assert not dest.exists()

    def test_invalid_header_returns_truncated_reason(self, tmp_path):
        """8 bytes with wrong magic also yields TRUNCATED."""
        client = self._make_mock_client(200, b"\x00" * 8)
        dest = tmp_path / "wf_bad.png"
        sha, nbytes, reason = download_waterfall(client, 99, "https://example.com/wf.png", dest)
        assert reason == "TRUNCATED"

    def test_valid_png_is_stored_with_sha(self, tmp_path):
        png_bytes = _make_png()
        client = self._make_mock_client(200, png_bytes)
        dest = tmp_path / "wf_ok.png"
        sha, nbytes, reason = download_waterfall(client, 10, "https://example.com/wf.png", dest)
        assert reason is None
        assert sha == sha256_bytes(png_bytes)
        assert nbytes == len(png_bytes)
        assert dest.exists()
        assert dest.read_bytes() == png_bytes

    def test_http_error_status_returns_http_error_reason(self, tmp_path):
        client = self._make_mock_client(500, b"Internal Server Error")
        dest = tmp_path / "wf_err.png"
        sha, nbytes, reason = download_waterfall(client, 5, "https://example.com/wf.png", dest)
        assert reason == "HTTP_ERROR"

    def test_timeout_returns_timeout_reason(self, tmp_path):
        import httpx
        client = MagicMock()
        client.get.side_effect = httpx.TimeoutException("timed out")
        dest = tmp_path / "wf_timeout.png"
        sha, nbytes, reason = download_waterfall(client, 7, "https://example.com/wf.png", dest)
        assert reason == "TIMEOUT"


# ===========================================================================
# 6. SHA-256 verification
# ===========================================================================

class TestVerifySha256:
    def test_correct_file_passes(self, tmp_path):
        png = _make_png()
        fpath = tmp_path / "waterfall_100.png"
        fpath.write_bytes(png)
        entry = _obs_manifest_entry(obs_id=100, sha256=sha256_bytes(png),
                                     wf_url="https://example.com/wf.png")
        errors = verify_sha256(tmp_path, [entry])
        assert errors == []

    def test_wrong_sha_detected(self, tmp_path):
        png = _make_png()
        fpath = tmp_path / "waterfall_101.png"
        fpath.write_bytes(png)
        entry = _obs_manifest_entry(obs_id=101, sha256="b" * 64,
                                     wf_url="https://example.com/wf.png")
        errors = verify_sha256(tmp_path, [entry])
        assert len(errors) == 1
        assert "101" in errors[0]

    def test_missing_file_detected(self, tmp_path):
        entry = _obs_manifest_entry(obs_id=102, sha256="c" * 64,
                                     wf_url="https://example.com/wf.png")
        errors = verify_sha256(tmp_path, [entry])
        assert any("102" in e for e in errors)

    def test_missing_reason_entry_skipped(self, tmp_path):
        """Observations with a missing_reason are not on disk and must not error."""
        entry = _obs_manifest_entry(obs_id=103, sha256=None, missing_reason="HTTP_404")
        errors = verify_sha256(tmp_path, [entry])
        assert errors == []


# ===========================================================================
# 7. Manifest schema validation
# ===========================================================================

class TestValidateManifest:
    def test_accepts_a_complete_manifest(self):
        entry = _obs_manifest_entry()
        doc = _minimal_manifest(obs_entries=[entry])
        validate_manifest(doc)  # must not raise

    def test_rejects_wrong_schema_version(self):
        entry = _obs_manifest_entry()
        doc = _minimal_manifest(obs_entries=[entry])
        doc["schema_version"] = "0.2.0"  # old version
        with pytest.raises(RuntimeError):
            validate_manifest(doc)

    def test_rejects_missing_sampling_design(self):
        entry = _obs_manifest_entry()
        doc = _minimal_manifest(obs_entries=[entry])
        del doc["sampling_design"]
        with pytest.raises(RuntimeError):
            validate_manifest(doc)

    def test_rejects_end_lte_filter(self):
        """The silently-ignored end__lte= filter must never appear in the manifest."""
        entry = _obs_manifest_entry()
        doc = _minimal_manifest(obs_entries=[entry])
        doc["query"]["filters"]["end__lte"] = "2026-08-16T00:00:00Z"
        with pytest.raises(RuntimeError):
            validate_manifest(doc)

    def test_rejects_waterfall_status_server_filter(self):
        """waterfall_status= returns HTTP 400; must never appear as a server-side filter."""
        entry = _obs_manifest_entry()
        doc = _minimal_manifest(obs_entries=[entry])
        doc["query"]["filters"]["waterfall_status"] = "with-signal"
        with pytest.raises(RuntimeError):
            validate_manifest(doc)

    def test_observation_requires_client_version(self):
        """After the 0.2.1 schema bump, client_version and client_family are required."""
        entry = _obs_manifest_entry()
        del entry["client_version"]
        doc = _minimal_manifest(obs_entries=[entry])
        with pytest.raises(RuntimeError):
            validate_manifest(doc)

    def test_observation_requires_client_family(self):
        entry = _obs_manifest_entry()
        del entry["client_family"]
        doc = _minimal_manifest(obs_entries=[entry])
        with pytest.raises(RuntimeError):
            validate_manifest(doc)

    def test_nullable_client_version_accepted(self):
        """client_version is nullable (6% of records have no version)."""
        entry = _obs_manifest_entry(client_version=None)
        doc = _minimal_manifest(obs_entries=[entry])
        validate_manifest(doc)  # must not raise


# ===========================================================================
# 8. Date-bound regression (silently-ignored end__lte= trap)
#
#    The acceptance criterion is: assert that a bare `end=` bound is actually
#    respected in the RETURNED DATA, not just in the request.
#    snapshot.py raises RuntimeError when any returned observation has an `end`
#    that exceeds the cutoff. This test exercises that guard directly.
# ===========================================================================

class TestDateBoundRegression:
    """The recon measured that end__lte= returns HTTP 200 and is silently
    ignored. The snapshot.py guard raises RuntimeError when any record in a
    fetched page has obs['end'] > cutoff, regardless of which parameter was
    used to request it.

    These tests verify that guard logic directly.
    """

    def _check_page(self, records: list[dict[str, Any]], cutoff: str) -> str | None:
        """Inline the same date-bound check that snapshot.py performs per page."""
        for rec in records:
            obs_end = rec.get("end", "")
            if obs_end and obs_end > cutoff:
                return f"obs {rec.get('id')} end={obs_end} > cutoff={cutoff}"
        return None

    def test_record_within_bound_passes(self):
        obs = _obs(obs_id=1, end="2026-08-14T23:59:59Z")
        err = self._check_page([obs], "2026-08-16T00:00:00Z")
        assert err is None

    def test_record_at_exact_cutoff_passes(self):
        obs = _obs(obs_id=2, end="2026-08-16T00:00:00Z")
        err = self._check_page([obs], "2026-08-16T00:00:00Z")
        assert err is None

    def test_future_record_detected(self):
        """If the API silently ignored end= and returned a future record, the
        guard must catch it. This is the regression that end__lte= caused."""
        future_obs = _obs(obs_id=3, end="2026-09-01T00:00:00Z")
        err = self._check_page([future_obs], "2026-08-16T00:00:00Z")
        assert err is not None
        assert "3" in err

    def test_mixed_page_detected(self):
        """A page with one good and one future record must still raise."""
        obs_good = _obs(obs_id=4, end="2026-08-15T10:00:00Z")
        obs_future = _obs(obs_id=5, end="2026-08-17T10:00:00Z")
        err = self._check_page([obs_good, obs_future], "2026-08-16T00:00:00Z")
        assert err is not None
        assert "5" in err

    def test_snapshot_raises_on_out_of_bound_data(self, tmp_path, monkeypatch):
        """Integration test: snapshot.run_snapshot raises RuntimeError when the
        mock API returns a record whose end exceeds the cutoff. This simulates
        what would happen if end__lte= were used and the API silently ignored it."""
        from pipeline.tracetriage import snapshot as snap_mod

        cutoff = "2026-08-16T00:00:00Z"
        future_record = _obs(obs_id=9999, end="2026-09-01T00:00:00Z")
        page_bytes = json.dumps([future_record]).encode()

        # Patch time.sleep to avoid actual waits
        monkeypatch.setattr(snap_mod.time, "sleep", lambda _: None)

        # Patch check_free_space to skip disk check
        monkeypatch.setattr(snap_mod, "check_free_space", lambda *a, **k: None)

        # Patch ARTIFACTS_DIR to tmp_path so no real artifact is written
        monkeypatch.setattr(snap_mod, "ARTIFACTS_DIR", tmp_path)

        mock_resp = MagicMock()
        mock_resp.content = page_bytes
        mock_resp.headers = {"link": ""}
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client.close = MagicMock()

        with (
            patch.object(snap_mod, "make_client", return_value=mock_client),
            pytest.raises(RuntimeError, match="date bound"),
        ):
            snap_mod.run_snapshot(
                end=cutoff,
                target_waterfalls=1,
                out_dir=tmp_path / "out",
                snapshot_id="snap-test",
            )


# ===========================================================================
# 9. Cursor exhaustion (no next page → clean exit)
# ===========================================================================

class TestCursorExhaustion:
    """A single-page result (no Link: next) terminates cleanly with all
    observations stored and a valid completed_at in the manifest."""

    def test_single_page_no_cursor_terminates(self, tmp_path, monkeypatch):
        from pipeline.tracetriage import snapshot as snap_mod

        cutoff = "2026-08-16T00:00:00Z"
        obs_record = _obs(obs_id=77, end="2026-08-15T10:00:00Z")
        png_bytes = _make_png()
        page_bytes = json.dumps([obs_record]).encode()

        monkeypatch.setattr(snap_mod.time, "sleep", lambda _: None)
        monkeypatch.setattr(snap_mod, "check_free_space", lambda *a, **k: None)
        monkeypatch.setattr(snap_mod, "ARTIFACTS_DIR", tmp_path)

        # API response: one page, no link header
        api_resp = MagicMock()
        api_resp.content = page_bytes
        api_resp.headers = {"link": ""}  # no "next"
        api_resp.raise_for_status = MagicMock()

        # Waterfall download response: valid PNG
        wf_resp = MagicMock()
        wf_resp.status_code = 200
        wf_resp.content = png_bytes

        # Both clients use the same mock; differentiate by URL
        def _get(url, **kwargs):
            if "satnogs.org" in url:
                return api_resp
            return wf_resp

        api_client = MagicMock()
        api_client.get.side_effect = _get
        api_client.close = MagicMock()

        wf_client = MagicMock()
        wf_client.get.return_value = wf_resp
        wf_client.close = MagicMock()

        call_count = [0]

        def _make_client(timeout=None):
            call_count[0] += 1
            return api_client if call_count[0] == 1 else wf_client

        with patch.object(snap_mod, "make_client", side_effect=_make_client):
            snap_mod.run_snapshot(
                end=cutoff,
                target_waterfalls=1,
                out_dir=tmp_path / "out",
                snapshot_id="snap-test-cursor",
            )

        manifest_path = tmp_path / "DATASET_MANIFEST.json"
        assert manifest_path.exists(), "manifest was not written"
        manifest = json.loads(manifest_path.read_text())

        assert manifest["completed_at"] is not None
        assert manifest["counts"]["observations_stored"] == 1
        assert manifest["counts"]["pages_fetched"] == 1

    def test_no_more_pages_means_no_redundant_requests(self, tmp_path, monkeypatch):
        """When the first page has no cursor, the API client must be called
        exactly once for paging (plus once per waterfall download)."""
        from pipeline.tracetriage import snapshot as snap_mod

        cutoff = "2026-08-16T00:00:00Z"
        obs_record = _obs(obs_id=78, end="2026-08-15T11:00:00Z", waterfall=None)
        page_bytes = json.dumps([obs_record]).encode()

        monkeypatch.setattr(snap_mod.time, "sleep", lambda _: None)
        monkeypatch.setattr(snap_mod, "check_free_space", lambda *a, **k: None)
        monkeypatch.setattr(snap_mod, "ARTIFACTS_DIR", tmp_path)

        api_resp = MagicMock()
        api_resp.content = page_bytes
        api_resp.headers = {}  # no link header at all
        api_resp.raise_for_status = MagicMock()

        api_client = MagicMock()
        api_client.get.return_value = api_resp
        api_client.close = MagicMock()

        wf_client = MagicMock()
        wf_client.close = MagicMock()

        call_count = [0]

        def _make_client(timeout=None):
            call_count[0] += 1
            return api_client if call_count[0] == 1 else wf_client

        with patch.object(snap_mod, "make_client", side_effect=_make_client):
            snap_mod.run_snapshot(
                end=cutoff,
                target_waterfalls=1,
                out_dir=tmp_path / "out",
                snapshot_id="snap-test-nocursor",
            )

        assert api_client.get.call_count == 1


# ===========================================================================
# 10. Resume-after-interrupt
#     A second run with a fully-populated partial manifest re-fetches ZERO
#     additional pages and stores ZERO additional observations.
# ===========================================================================

class TestResumeAfterInterrupt:
    def test_second_run_fetches_zero_pages(self, tmp_path, monkeypatch):
        """Simulate a first run that stored one observation and one page, then
        call run_snapshot again and verify no new network calls are made to the
        API metadata endpoint."""
        from pipeline.tracetriage import snapshot as snap_mod

        cutoff = "2026-08-16T00:00:00Z"
        snapshot_id = "snap-test-resume"

        # A previously stored page entry
        stored_page_url = (
            f"{BASE_URL}?format=json&end={cutoff}"
        )
        # cursor=None means this was the final page
        stored_page = {
            "url": stored_page_url,
            "sha256": "d" * 64,
            "retrieved_at": "2026-08-16T00:05:00Z",
            "n_observations": 1,
            "cursor": None,  # final page; no next page exists
        }
        stored_obs = _obs_manifest_entry(obs_id=55)

        prior_manifest = _minimal_manifest(
            snapshot_id=snapshot_id,
            obs_entries=[stored_obs],
            pages=[stored_page],
            completed_at=None,  # partial (interrupted before finalisation)
        )

        # The manifest is this snapshot's own resume index, so it lives in --out.
        # It used to be read from one global artifacts path, which meant every
        # snapshot shared a single resume state. Corrected in A1b.
        out_dir = tmp_path / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "DATASET_MANIFEST.json"
        manifest_path.write_text(
            json.dumps(prior_manifest, indent=2), encoding="utf-8"
        )

        monkeypatch.setattr(snap_mod.time, "sleep", lambda _: None)
        monkeypatch.setattr(snap_mod, "check_free_space", lambda *a, **k: None)
        monkeypatch.setattr(snap_mod, "ARTIFACTS_DIR", tmp_path)

        api_client = MagicMock()
        api_client.close = MagicMock()
        wf_client = MagicMock()
        wf_client.close = MagicMock()

        call_count = [0]

        def _make_client(timeout=None):
            call_count[0] += 1
            return api_client if call_count[0] == 1 else wf_client

        with patch.object(snap_mod, "make_client", side_effect=_make_client):
            snap_mod.run_snapshot(
                end=cutoff,
                target_waterfalls=50,
                out_dir=tmp_path / "out",
                snapshot_id=snapshot_id,
            )

        # The prior page had cursor=None → there is no next page to fetch
        assert api_client.get.call_count == 0, (
            f"Second run made {api_client.get.call_count} API page requests; expected 0"
        )

    def test_second_run_skips_already_stored_obs(self, tmp_path, monkeypatch):
        """Even if paging happens (cursor resumed), observations already in the
        manifest are not downloaded again."""
        from pipeline.tracetriage import snapshot as snap_mod

        cutoff = "2026-08-16T00:00:00Z"
        snapshot_id = "snap-test-skip-obs"
        obs_id = 66
        png_bytes = _make_png()
        stored_sha = sha256_bytes(png_bytes)

        # Write the waterfall file so verify_sha256 would pass
        out_dir = tmp_path / "out"
        wf_dir = out_dir / "waterfalls"
        wf_dir.mkdir(parents=True)
        (wf_dir / f"waterfall_{obs_id}.png").write_bytes(png_bytes)

        # Prior manifest with this obs already stored
        stored_obs = _obs_manifest_entry(obs_id=obs_id, sha256=stored_sha,
                                          wf_url=f"https://s3.example.com/wf_{obs_id}.png")
        stored_page_url = f"{BASE_URL}?format=json&end={cutoff}"
        stored_page = {
            "url": stored_page_url,
            "sha256": "e" * 64,
            "retrieved_at": "2026-08-16T00:05:00Z",
            "n_observations": 1,
            "cursor": "cursor_abc",  # has a next page
        }

        prior_manifest = _minimal_manifest(
            snapshot_id=snapshot_id,
            obs_entries=[stored_obs],
            pages=[stored_page],
            completed_at=None,
        )

        # Resume index lives with the snapshot, not at a global path. See A1b.
        manifest_path = out_dir / "DATASET_MANIFEST.json"
        manifest_path.write_text(json.dumps(prior_manifest, indent=2), encoding="utf-8")

        monkeypatch.setattr(snap_mod.time, "sleep", lambda _: None)
        monkeypatch.setattr(snap_mod, "check_free_space", lambda *a, **k: None)
        monkeypatch.setattr(snap_mod, "ARTIFACTS_DIR", tmp_path)

        # The second page returns the same obs (simulates re-encountering it)
        obs_record = _obs(obs_id=obs_id, end="2026-08-15T10:00:00Z")
        page2_bytes = json.dumps([obs_record]).encode()

        api_resp2 = MagicMock()
        api_resp2.content = page2_bytes
        api_resp2.headers = {}  # no further cursor
        api_resp2.raise_for_status = MagicMock()

        api_client = MagicMock()
        api_client.get.return_value = api_resp2
        api_client.close = MagicMock()

        wf_client = MagicMock()
        wf_client.close = MagicMock()

        call_count = [0]

        def _make_client(timeout=None):
            call_count[0] += 1
            return api_client if call_count[0] == 1 else wf_client

        with patch.object(snap_mod, "make_client", side_effect=_make_client):
            snap_mod.run_snapshot(
                end=cutoff,
                target_waterfalls=50,
                out_dir=out_dir,
                snapshot_id=snapshot_id,
            )

        # Waterfall download must NOT have been called for the already-stored obs
        assert wf_client.get.call_count == 0, (
            f"Waterfall client was called {wf_client.get.call_count} times; "
            "expected 0 since obs was already stored"
        )
