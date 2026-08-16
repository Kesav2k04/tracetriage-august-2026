"""Throttle handling for unit A1's snapshot builder.

A stage-1 run died at 1,378 of 2,500 waterfalls on a 429 from the listing
endpoint. Two defects were behind it.

The first is obvious: a 429 raised and ended the run, when it is really an
instruction to wait.

The second is the dangerous one. A throttled *waterfall* was recorded as
HTTP_ERROR, and the resume index treats any recorded observation as done, so
the next run skipped it forever. A transient refusal became a permanent hole
that no rerun would fill, and it was indistinguishable in the manifest from a
waterfall that never existed. Throttling arrives in bursts, so those holes
cluster in time and quietly bias the corpus.

All tests here are offline. No sleeping is done for real: the wait is injected
or patched, so a test that asserts a 300 second backoff still runs instantly.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pipeline.tracetriage.snapshot import (
    CONTRACT_PATH,
    MAX_RETRIES,
    MAX_RETRY_DELAY,
    RETRY_BASE_DELAY,
    TRANSIENT_MISSING_REASONS,
    build_resume_index,
    download_waterfall,
    drop_transient_entries,
    get_with_retry,
    retry_delay,
)


def _make_png(width: int = 4, height: int = 4) -> bytes:
    """Smallest valid PNG that satisfies the header and decode checks."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _resp(status: int, retry_after: str | None = None, content: bytes = b"") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.headers = {"retry-after": retry_after} if retry_after else {}
    r.content = content
    return r


class TestRetryDelay:
    def test_numeric_retry_after_is_honoured(self):
        """The server knows when its window reopens; guessing does not."""
        resp = _resp(429, "17")
        assert retry_delay(0, resp) == 17.0
        assert retry_delay(5, resp) == 17.0

    def test_http_date_retry_after_is_honoured(self):
        resp = _resp(429, format_datetime(datetime.now(UTC) + timedelta(seconds=45)))
        delay = retry_delay(0, resp)
        assert 40.0 <= delay <= 50.0, f"expected about 45s from the HTTP-date, got {delay}"

    def test_past_http_date_clamps_to_zero_not_negative(self):
        resp = _resp(429, format_datetime(datetime.now(UTC) - timedelta(seconds=120)))
        assert retry_delay(0, resp) == 0.0

    def test_unparseable_retry_after_falls_back_to_backoff(self):
        """A bad header must never be read as 'retry immediately'."""
        resp = _resp(429, "soon-ish")
        assert retry_delay(0, resp) == RETRY_BASE_DELAY
        assert retry_delay(2, resp) == RETRY_BASE_DELAY * 4

    def test_backoff_doubles_and_is_capped(self):
        assert retry_delay(0) == RETRY_BASE_DELAY
        assert retry_delay(1) == RETRY_BASE_DELAY * 2
        assert retry_delay(2) == RETRY_BASE_DELAY * 4
        assert retry_delay(40) == MAX_RETRY_DELAY

    def test_absurd_retry_after_is_capped(self):
        """A day-long Retry-After must not hang the run until tomorrow."""
        assert retry_delay(0, _resp(429, "99999")) == MAX_RETRY_DELAY


class TestGetWithRetry:
    def test_429_then_200_succeeds_and_waits_exactly_as_told(self):
        client = MagicMock()
        client.get.side_effect = [_resp(429, "3"), _resp(200)]
        slept: list[float] = []
        resp = get_with_retry(client, "https://x/", 10, sleep=slept.append)
        assert resp.status_code == 200
        assert slept == [3.0]
        assert client.get.call_count == 2

    def test_404_is_not_retried(self):
        """A 404 is an answer, not a delay. Retrying it spends the budget."""
        client = MagicMock()
        client.get.side_effect = [_resp(404)]
        slept: list[float] = []
        resp = get_with_retry(client, "https://x/", 10, sleep=slept.append)
        assert resp.status_code == 404
        assert client.get.call_count == 1
        assert slept == []

    def test_persistent_429_gives_up_and_returns_last_response(self):
        """Bounded, not infinite. A real outage still has to end the run."""
        client = MagicMock()
        client.get.return_value = _resp(429, "1")
        slept: list[float] = []
        resp = get_with_retry(client, "https://x/", 10, sleep=slept.append)
        assert resp.status_code == 429
        assert client.get.call_count == MAX_RETRIES
        assert len(slept) == MAX_RETRIES - 1, "no sleep after the final attempt"

    def test_5xx_is_retried(self):
        client = MagicMock()
        client.get.side_effect = [_resp(503), _resp(200)]
        resp = get_with_retry(client, "https://x/", 10, sleep=lambda _: None)
        assert resp.status_code == 200

    def test_timeout_is_retried_then_reraised(self):
        client = MagicMock()
        client.get.side_effect = httpx.TimeoutException("slow")
        with pytest.raises(httpx.TimeoutException):
            get_with_retry(client, "https://x/", 10, sleep=lambda _: None)
        assert client.get.call_count == MAX_RETRIES


class TestThrottledWaterfall:
    def test_persistent_429_is_throttled_not_http_error(self, tmp_path):
        """The distinction the whole fix rests on.

        THROTTLED is transient and gets retried. HTTP_ERROR was what this path
        used to return, and being indexed as settled it dropped the
        observation from every future run.
        """
        client = MagicMock()
        client.get.return_value = _resp(429)
        dest = tmp_path / "wf.png"
        with patch("pipeline.tracetriage.snapshot.time.sleep"):
            sha, nbytes, reason = download_waterfall(
                client, 1, "https://example.com/wf.png", dest
            )
        assert reason == "THROTTLED"
        assert reason in TRANSIENT_MISSING_REASONS
        assert sha is None and nbytes is None
        assert not dest.exists()

    def test_429_then_good_png_is_stored(self, tmp_path):
        png = _make_png()
        client = MagicMock()
        client.get.side_effect = [_resp(429), _resp(200, content=png)]
        dest = tmp_path / "wf.png"
        with patch("pipeline.tracetriage.snapshot.time.sleep"):
            sha, nbytes, reason = download_waterfall(
                client, 2, "https://example.com/wf.png", dest
            )
        assert reason is None, "a recoverable 429 must not cost the observation"
        assert dest.exists()
        assert sha == hashlib.sha256(png).hexdigest()
        assert nbytes == len(png)

    def test_404_still_settles_permanently(self, tmp_path):
        """Hardening the transient case must not make real absences retryable."""
        client = MagicMock()
        client.get.return_value = _resp(404)
        sha, nbytes, reason = download_waterfall(
            client, 3, "https://example.com/wf.png", tmp_path / "wf.png"
        )
        assert reason == "HTTP_404"
        assert reason not in TRANSIENT_MISSING_REASONS


class TestTransientReasonsAreRetried:
    def _entry(self, obs_id: int, reason: str | None) -> dict[str, Any]:
        return {
            "id": obs_id,
            "waterfall_sha256": None if reason else "a" * 64,
            "waterfall_missing_reason": reason,
        }

    def test_resume_index_excludes_transient_failures(self):
        manifest = {"observations": [
            self._entry(1, None),                 # stored intact
            self._entry(2, "NO_WATERFALL_URL"),   # settled, nothing to fetch
            self._entry(3, "HTTP_404"),           # settled, gone for good
            self._entry(4, "THROTTLED"),          # transient
            self._entry(5, "TIMEOUT"),            # transient
            self._entry(6, "HTTP_ERROR"),         # transient
        ]}
        assert set(build_resume_index(manifest)) == {1, 2, 3}, (
            "transient failures must stay out of the resume index so that the "
            "next run refetches them instead of inheriting the hole"
        )

    def test_drop_transient_entries_prevents_duplicate_records(self):
        """The retry appends a fresh entry, so the stale one has to go."""
        obs = [
            self._entry(1, None),
            self._entry(4, "THROTTLED"),
            self._entry(2, "NO_WATERFALL_URL"),
        ]
        assert [e["id"] for e in drop_transient_entries(obs)] == [1, 2]

    def test_settled_entries_survive_a_resume_untouched(self):
        obs = [self._entry(1, None), self._entry(3, "HTTP_404")]
        assert drop_transient_entries(obs) == obs

    def test_every_transient_reason_is_a_valid_contract_value(self):
        """The enum and the retry set must not drift apart."""
        schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        enum = (schema["properties"]["observations"]["items"]
                ["properties"]["waterfall_missing_reason"]["enum"])
        for reason in TRANSIENT_MISSING_REASONS:
            assert reason in enum, f"{reason} is not a permitted manifest value"
