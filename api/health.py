"""Is the deployment up, and is it this repository.

Two questions, one request. The first is what a health endpoint normally answers. The second
is the one worth having here, and it is the reason this file is not three lines long.

A judge reading a submission has no way to tell whether the site they are looking at was
built from the tree they are reading. Screenshots prove nothing, a commit hash in a README
proves nothing, and `vercel.json` is a file in the repository rather than a statement about
what is running. So this endpoint hashes the copy of `apps/web/public/data/provenance.json`
that was deployed alongside it and returns the digest. Anyone can hash what the CDN serves
at `/data/provenance.json` and compare:

    curl -s https://tracetriage.vercel.app/data/provenance.json | sha256sum
    curl -s https://tracetriage.vercel.app/api/health/

If those two digests agree, the static console and this function came out of one build of
one tree, and the digest in `artifacts/` says which tree. If they disagree, something was
deployed by hand and every number on the console is suspect. That is a check with an
outcome, which is more than a green dot.

Standard library only, and nothing imported from `pipeline/`. The live measurement endpoint
imports numpy, scipy and the fitting code, and its cold start is measured in tens of
seconds; this one has to answer while that is still waking up, or it is not a health check.
The same reason it does no network call: an endpoint that reports the health of SatNOGS is
reporting something this deployment does not control.

Deployed at `/api/health/` next to `api/live.py`. `vercel.json` gives it the one data file
it reads via `includeFiles`, because a Python function on Vercel gets its own filesystem and
not the static export's.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

#: When this process started, so a reader can tell a cold start from a warm one. Module
#: scope on purpose: it is set when the runtime imports the file, which is the cold start.
_STARTED = time.time()

#: The file whose digest is the whole point. Resolved from this file's own location so it
#: works both on Vercel, where the function is rooted at the project directory, and in a
#: checkout, where it is run from anywhere.
_REPO = Path(__file__).resolve().parents[1]
_PROVENANCE = _REPO / "apps" / "web" / "public" / "data" / "provenance.json"

#: Vercel's system environment variables. Present when the project is connected to git and
#: absent on a CLI deployment from a working tree, which is a real difference and is
#: reported as `null` rather than as an empty string that reads like a value.
_ENV_KEYS = (
    "VERCEL_ENV",
    "VERCEL_REGION",
    "VERCEL_GIT_COMMIT_SHA",
    "VERCEL_GIT_COMMIT_REF",
    "VERCEL_DEPLOYMENT_ID",
)


def _env() -> dict[str, str | None]:
    return {key.lower().removeprefix("vercel_"): os.environ.get(key) or None for key in _ENV_KEYS}


def _provenance() -> dict[str, Any]:
    """The digest, and the two facts inside the file worth returning with it.

    Read on every request rather than cached at import. It is 12 KB and the read is what
    proves the file is still there; a digest computed once at cold start and served for an
    hour is a statement about the past.
    """
    if not _PROVENANCE.is_file():
        return {
            "file": "apps/web/public/data/provenance.json",
            "present": False,
            "why_it_matters": (
                "this function was deployed without the data file, so it cannot say "
                "whether the console beside it is this repository. See includeFiles in "
                "vercel.json."
            ),
        }
    raw = _PROVENANCE.read_bytes()
    parsed = json.loads(raw)
    summary = parsed.get("gate_summary", {})
    return {
        "file": "apps/web/public/data/provenance.json",
        "present": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "snapshot_id": parsed.get("snapshot_id"),
        "gates": {
            "met": summary.get("n_met"),
            "total": summary.get("n_gates"),
            # Named rather than counted. A tally of met gates reads better than the
            # result, and the result is that some of these came back not established.
            #
            # The keys are `gate` and `title`, read out of the file rather than guessed:
            # the first version of this asked for `id` and `name`, got None for both, and
            # published a list of six verdicts attached to nothing. A wrong key does not
            # raise. It returns null, which reads as "not measured".
            "verdicts": [
                {
                    "gate": gate.get("gate"),
                    "title": gate.get("title"),
                    "verdict": gate.get("verdict"),
                }
                for gate in summary.get("gates", [])
            ],
        },
    }


def payload() -> dict[str, Any]:
    """The body, as a plain dict so a test can assert on it without a socket."""
    return {
        "schema": "tracetriage/health",
        "schema_version": "0.1.0",
        "status": "ok",
        "now_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "process_uptime_s": round(time.time() - _STARTED, 3),
        "deployment": _env(),
        "served_data": _provenance(),
        "verify": {
            "what": (
                "hash what the CDN serves and compare it with served_data.sha256. Equal "
                "means the console and this function came from one build of one tree."
            ),
            "how": "curl -s https://tracetriage.vercel.app/data/provenance.json | sha256sum",
        },
        "not_checked_here": [
            "SatNOGS reachability, which this deployment does not control",
            "the live measurement endpoint, which has its own cold start and its own "
            "refusal codes: POST /api/live/",
        ],
    }


class handler(BaseHTTPRequestHandler):  # noqa: N801 (the name Vercel's runtime looks for)
    """Lowercase, for the same reason as `api/live.py`: it is the name the runtime imports."""

    server_version = "TraceTriageHealth/1"
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, indent=1).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Never cached. A cached health response is a claim about a deployment that may
        # since have been replaced, which is the one thing this endpoint must not do.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        self._send(200, payload())

    def do_HEAD(self) -> None:  # noqa: N802
        self._send(200, payload())

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _refuse(self) -> None:
        self._send(
            405,
            {
                "ok": False,
                "code": "METHOD_NOT_ALLOWED",
                "detail": "This endpoint reads. GET or HEAD.",
            },
        )

    do_POST = _refuse  # noqa: N815
    do_PUT = _refuse  # noqa: N815
    do_DELETE = _refuse  # noqa: N815
    do_PATCH = _refuse  # noqa: N815

    def log_message(self, fmt: str, *args: Any) -> None:
        """Silence the default stderr access log, which on Vercel is duplicated noise."""


if __name__ == "__main__":
    # Run it standalone to see what a judge would see:
    #     python api/health.py
    print(json.dumps(payload(), indent=1))
