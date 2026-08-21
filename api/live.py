"""One read-only HTTP endpoint that measures the observation a reader names.

`pipeline/tracetriage/live.py` can already measure an observation recorded an hour ago.
Nothing a judge opens in a browser could reach it. The console is `output: "export"`, a
directory of files with no server behind it, and that is deliberate: nothing can break in
front of a reader because a backend went down. But a static export cannot propagate an
orbit, and SatNOGS serves waterfalls without an `Access-Control-Allow-Origin` header, so a
browser cannot fetch the image either. The measurement has to happen somewhere with a
Python process in it.

This is that somewhere, and it is as thin as it can be. It does not measure anything. It
validates an observation id, calls `live.triage`, and serialises what comes back with
`LiveMeasurement.to_dict`, which is the same serialiser `tracetriage triage --json`
prints. **There is no second copy of any number here.** No field is recomputed, no value is
rounded for display, and there is no convenience summary block duplicating the mode or the
ppm at the top of the envelope, because a number that lives in two places is a number that
can disagree with itself. What the endpoint adds is the envelope: whether the answer came
from cache, when it was served, and which engine call produced it.

**Read-only, and structurally so.** Every outbound request in the module graph below this
handler is a GET, there is no credential to hold, and `tests/test_live_api.py` greps this
file and `pipeline/tracetriage/{live,snapshot}.py` for write verbs and fails if one appears.
The permission boundary is `docs/ACTOR_AND_PERMISSION_CONTRACT.md`: read the public API,
download published waterfalls, compute locally. Nothing else.

**A refusal is not an error.** `live.LiveRefusal` carries a named code because an
observation with no stored waterfall, or a TLE that will not propagate, is a state of the
world rather than a broken server. Those come back as HTTP 422 with the code intact, so a
reader sees NO_WATERFALL and not a 500. A measurement that ran and could not settle the
Doppler mode is a different thing again: that is HTTP 200 with a complete measurement whose
`mode.verdict` is UNRESOLVED and whose `nulls.not_tested` names which branch declined. Both
are published. Neither is dressed up.

Two ways to run it, one implementation:

    python api/live.py --port 8787            # standalone, for local testing
    POST /api/live {"obs_id": 14836679}       # Vercel Python function, same file

The Vercel runtime looks for a `handler` subclassing `BaseHTTPRequestHandler`, which is why
there is no web framework here. A framework would add a dependency to a function whose
dependency set is already 187 MB of numpy and scipy against a 250 MB ceiling, and it would
not remove a single line below.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote_plus

# The repository root, so `pipeline.tracetriage` imports the same way it does from a
# checkout. Vercel copies the files named by `functions["api/live.py"].includeFiles` in
# vercel.json into the function bundle preserving this layout, and the cwd inside a Python
# function is not promised to be the project root. Deriving it from `__file__` is the only
# form that holds both here and there.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pipeline.tracetriage import live as live_engine  # noqa: E402

API_VERSION = "LIVE_API/1"

# 24 h, from the brief. A waterfall image never changes once the network has stored it and
# the measurement is seeded (`corridor_fit.Thresholds.seed`), so a second call on the same
# id inside a day cannot produce a different answer. It can only cost the volunteers who
# run the network another image transfer.
CACHE_TTL_S = 86_400
# Bounded so a scripted walk of ids cannot grow the process without limit. Oldest entry
# out first.
CACHE_MAX_ENTRIES = 256

# One waterfall download plus one corridor fit measured 14.7 s end to end on the first
# post-snapshot id tried, on a laptop, cold. The budget is that with room for a slow
# transfer, and it is the number `maxDuration` in vercel.json has to clear.
MEASURE_BUDGET_S = 55.0
# Handed to httpx for the record fetch and the image fetch. `live.make_client` defaults to
# 30 s and the image fetch asks for 60 s inside `live.fetch_waterfall`; this only sets the
# client-wide floor.
CLIENT_TIMEOUT_S = 30.0

# Per-caller and whole-instance limits. The point is not to stop an attacker, which a
# per-instance counter cannot do on a serverless platform where the next request may land
# in a new process. The point is that a judge holding down a button, or a crawler that
# found the route, cannot turn this endpoint into a load generator pointed at volunteer
# infrastructure.
RATE_WINDOW_S = 60.0
RATE_PER_CLIENT = 6
RATE_PER_INSTANCE = 20
# One measurement at a time per instance, for the same reason: two concurrent requests are
# two concurrent image downloads and two corridor fits on one CPU.
MEASURE_SLOT_WAIT_S = 20.0

# A POST body carrying one integer does not need more than this, and reading an unbounded
# Content-Length into memory is how a small handler becomes a memory limit.
MAX_BODY_BYTES = 4_096
# Observation ids are around 14.8 million as of August 2026. Nine digits is four orders of
# magnitude of headroom and still refuses a pasted phone number before it becomes a request
# to someone else's API.
_OBS_ID_RE = re.compile(r"^[0-9]{1,9}$")


class LiveApiError(Exception):
    """A typed refusal to answer, with the status and code the caller will see.

    Every path out of this module that is not a measurement raises one of these, so there
    is exactly one place that turns a failure into a response body and no path that can
    reach a caller as a traceback.
    """

    def __init__(self, status: int, code: str, detail: str, *, kind: str = "request",
                 extra: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {detail}")
        self.status = status
        self.code = code
        self.detail = detail
        self.kind = kind
        self.extra = extra or {}

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "api": API_VERSION,
            "ok": False,
            "error": {"kind": self.kind, "code": self.code, "detail": self.detail},
        }
        body["error"].update(self.extra)
        return body


def parse_obs_id(raw: Any) -> int:
    """The one gate an observation id passes through, whatever route it arrived on.

    Shared by the JSON body and the query string on purpose. Two parsers is two sets of
    accepted inputs, and the looser one decides what actually reaches the network.

    `bool` is excluded explicitly because `True` is an `int` in Python and
    `int(True) == 1` would send a request for observation 1 to a volunteer-run API on
    behalf of a caller who posted `{"obs_id": true}`.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise LiveApiError(400, "MISSING_OBS_ID",
                           "an observation id is required, as obs_id")
    if isinstance(raw, bool):
        raise LiveApiError(400, "BAD_OBS_ID",
                           "an observation id must be a positive integer, not a boolean")
    if isinstance(raw, int):
        text = str(raw)
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        raise LiveApiError(
            400, "BAD_OBS_ID",
            f"an observation id must be a positive integer, not {type(raw).__name__}")
    if not _OBS_ID_RE.match(text):
        raise LiveApiError(
            400, "BAD_OBS_ID",
            "an observation id must be a positive integer of at most 9 digits, "
            f"and {text[:32]!r} is not")
    value = int(text)
    if value <= 0:
        raise LiveApiError(400, "BAD_OBS_ID",
                           "an observation id must be greater than zero")
    return value


class _Cache:
    """Answers by observation id, for `ttl_s`, oldest evicted first.

    In-process, which is the honest description of what it is. On Vercel each function
    instance has its own, so a cache hit is likely under a burst and not promised across a
    cold start, and the response says which one it was rather than implying a shared store.
    """

    def __init__(self, ttl_s: float = CACHE_TTL_S, max_entries: int = CACHE_MAX_ENTRIES,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl_s = ttl_s
        self._max = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[int, tuple[float, dict[str, Any]]] = {}

    def get(self, obs_id: int) -> dict[str, Any] | None:
        now = self._clock()
        with self._lock:
            hit = self._entries.get(obs_id)
            if hit is None:
                return None
            stored_at, payload = hit
            if now - stored_at >= self._ttl_s:
                del self._entries[obs_id]
                return None
            return payload

    def put(self, obs_id: int, payload: dict[str, Any]) -> None:
        with self._lock:
            self._entries.pop(obs_id, None)
            self._entries[obs_id] = (self._clock(), payload)
            while len(self._entries) > self._max:
                # Insertion-ordered, so the first key is the least recently stored.
                oldest = next(iter(self._entries))
                del self._entries[oldest]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class _RateLimiter:
    """A fixed window per caller and a second one across the instance.

    Two counters rather than one because they answer different questions. The per-caller
    window stops one reader from looping; the instance window stops a hundred readers from
    doing it together, which the per-caller window cannot see.
    """

    def __init__(self, window_s: float = RATE_WINDOW_S, per_client: int = RATE_PER_CLIENT,
                 per_instance: int = RATE_PER_INSTANCE,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._window_s = window_s
        self._per_client = per_client
        self._per_instance = per_instance
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}
        self._all: list[float] = []

    def check(self, client_key: str) -> None:
        now = self._clock()
        floor = now - self._window_s
        with self._lock:
            self._all = [t for t in self._all if t > floor]
            mine = [t for t in self._hits.get(client_key, []) if t > floor]
            # Callers that have gone quiet are dropped here rather than on a timer, so the
            # table cannot grow once per distinct address seen.
            self._hits = {k: v for k, v in self._hits.items() if any(t > floor for t in v)}
            if len(mine) >= self._per_client:
                raise LiveApiError(
                    429, "RATE_LIMITED",
                    f"at most {self._per_client} measurements per "
                    f"{int(self._window_s)} s from one caller",
                    kind="rate_limit",
                    extra={"retry_after_s": max(1, int(mine[0] + self._window_s - now))})
            if len(self._all) >= self._per_instance:
                raise LiveApiError(
                    429, "RATE_LIMITED_UPSTREAM_COURTESY",
                    f"this instance is at its own ceiling of {self._per_instance} "
                    f"measurements per {int(self._window_s)} s, which exists to keep a "
                    "burst here from becoming a burst against a volunteer-run API",
                    kind="rate_limit",
                    extra={"retry_after_s":
                           max(1, int(self._all[0] + self._window_s - now))})
            mine.append(now)
            self._hits[client_key] = mine
            self._all.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._all.clear()


class LiveService:
    """Validate, rate-limit, cache, measure. The whole endpoint minus the HTTP.

    `triage` is injected so the tests can drive every branch, including the refusals and
    the cache, without a request leaving the machine. CI must never touch SatNOGS: a suite
    that depends on a volunteer network being up is a suite that reports the network's
    weather as this repository's health.
    """

    def __init__(self, *, triage: Callable[..., Any] | None = None,
                 cache: _Cache | None = None, limiter: _RateLimiter | None = None,
                 n_nulls: int | None = None, label_reader: str = "auto",
                 slot_wait_s: float = MEASURE_SLOT_WAIT_S) -> None:
        self._triage = triage or live_engine.triage
        self.cache = cache if cache is not None else _Cache()
        self.limiter = limiter if limiter is not None else _RateLimiter()
        # Both default to what `cli.cmd_triage` passes: `--nulls` unset and the label
        # reader left at `live.triage`'s own default. That is not a preference, it is the
        # condition under which this endpoint's numbers equal the CLI's numbers on the same
        # id, which is the only claim it makes.
        self._n_nulls = n_nulls
        self._label_reader = label_reader
        self._slot = threading.Semaphore(1)
        self._slot_wait_s = slot_wait_s

    def measure(self, raw_obs_id: Any, *, client_key: str = "local") -> dict[str, Any]:
        obs_id = parse_obs_id(raw_obs_id)

        cached = self.cache.get(obs_id)
        if cached is not None:
            # Rate limiting deliberately comes after the cache lookup. A cached answer
            # costs no upstream request and no CPU, so refusing to serve it would protect
            # nothing and would make a reader reloading the page look like abuse.
            return self._envelope(obs_id, cached, cached=True)

        self.limiter.check(client_key)

        if not self._slot.acquire(timeout=self._slot_wait_s):
            raise LiveApiError(
                503, "BUSY",
                "another measurement is running on this instance and one waterfall fit at "
                "a time is the limit; try again in a few seconds",
                kind="capacity", extra={"retry_after_s": 5})
        started = time.monotonic()
        try:
            measurement = self._run(obs_id)
        finally:
            self._slot.release()

        payload = measurement.to_dict()
        self.cache.put(obs_id, payload)
        envelope = self._envelope(obs_id, payload, cached=False)
        envelope["engine"]["elapsed_s"] = round(time.monotonic() - started, 3)
        return envelope

    def _run(self, obs_id: int) -> Any:
        """The one call that reaches the network, with every failure given a name."""
        try:
            return self._triage(obs_id, n_nulls=self._n_nulls,
                                label_reader=self._label_reader)
        except live_engine.LiveRefusal as exc:
            # A named state of the world. 422 rather than 500: the server worked, the
            # observation cannot be measured, and the code says which.
            raise LiveApiError(422, exc.code, exc.detail or str(exc), kind="refusal",
                               extra={"observation_id": obs_id}) from exc
        except LiveApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Everything else is either SatNOGS being unreachable or a bug here, and a
            # caller cannot tell those apart from a traceback anyway. The type and message
            # go to the log; the response carries neither, because an exception string can
            # hold a filesystem path.
            print(f"live api: measurement of {obs_id} failed: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            raise LiveApiError(
                502, "UPSTREAM_UNAVAILABLE",
                "the measurement could not be completed. The public SatNOGS API was "
                "unreachable or answered in a shape this build does not expect. Nothing "
                "was written anywhere, and the frozen shelf on /live still holds "
                "measurements taken earlier.",
                kind="upstream", extra={"observation_id": obs_id}) from exc

    def _envelope(self, obs_id: int, payload: dict[str, Any], *,
                  cached: bool) -> dict[str, Any]:
        """The measurement, unchanged, plus how it got here.

        `measurement` is `LiveMeasurement.to_dict()` verbatim. The fields the brief asks
        for by name all live inside it and are not copied out: `provenance.measured_at_utc`,
        `provenance.waterfall_sha256`, `pass.tle_epoch_age_days`, `mode.verdict`,
        `measurement.offset_ppm`, `nulls.p_value`, and `nulls.not_tested` when the null
        test did not run.
        """
        return {
            "api": API_VERSION,
            "ok": True,
            "observation_id": obs_id,
            "cached": cached,
            "served_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "engine": {
                "function": "pipeline.tracetriage.live.triage",
                "cli_equivalent": f"tracetriage triage {obs_id} --json",
                "n_nulls": self._n_nulls,
                "label_reader": self._label_reader,
                "cache_ttl_s": CACHE_TTL_S,
            },
            "measurement": payload,
        }


# The instance the HTTP handler uses. Module level so a warm serverless instance keeps its
# cache between requests, which is the only place caching buys anything there.
SERVICE = LiveService()


def _client_key(headers: Any, fallback: str) -> str:
    """Which caller this is, for the rate limiter only.

    `x-forwarded-for` is the address Vercel puts the real client in; behind no proxy it is
    absent and the socket address is the answer. It is used as an opaque bucket key and is
    not logged, stored, or attached to any measurement.
    """
    fwd = headers.get("x-forwarded-for") if headers else None
    if fwd:
        return fwd.split(",")[0].strip()
    real = headers.get("x-real-ip") if headers else None
    return (real or fallback or "unknown").strip()


class handler(BaseHTTPRequestHandler):  # noqa: N801 (the name Vercel's runtime looks for)
    """POST an id, GET an id, or ask what the endpoint is.

    Lowercase class name on purpose: `@vercel/python` imports the module and looks for a
    module-level `handler` that subclasses `BaseHTTPRequestHandler`. Renaming it to
    `LiveHandler` builds and deploys cleanly and then 500s on every request, which is a
    failure that only appears in production.
    """

    server_version = "TraceTriageLive/1"
    # HTTP/1.1 so `Content-Length` is honoured and a keep-alive connection is not closed
    # under a local test client mid-body.
    protocol_version = "HTTP/1.1"

    service: LiveService = SERVICE

    # ---------------- responses ----------------

    def _send(self, status: int, body: dict[str, Any], *,
              cacheable: bool = False) -> None:
        raw = json.dumps(body, indent=1).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        # The console is a static export that may be served from a different origin than
        # this function during local development, and the data behind it is public
        # CC BY-SA community data with no credential involved. There is nothing here for
        # an origin restriction to protect.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cacheable:
            self.send_header("Cache-Control",
                             f"public, max-age={CACHE_TTL_S}, "
                             f"stale-while-revalidate=3600")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _fail(self, exc: LiveApiError) -> None:
        if "retry_after_s" in exc.extra:
            # Sent as a header as well as in the body so a generic client backs off
            # without having to understand this envelope.
            self.send_response(exc.status)
            body = json.dumps(exc.to_body(), indent=1).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Retry-After", str(exc.extra["retry_after_s"]))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self._send(exc.status, exc.to_body())

    # ---------------- routes ----------------

    def _path(self) -> tuple[str, dict[str, str]]:
        raw = self.path or "/"
        path, _, query = raw.partition("?")
        params: dict[str, str] = {}
        for part in query.split("&"):
            if not part:
                continue
            key, _, value = part.partition("=")
            params[unquote_plus(key)] = unquote_plus(value)
        # Trailing slashes are on for the static console (`trailingSlash: true`), so this
        # route can be reached either way and both spellings have to mean the same thing.
        return path.rstrip("/") or "/", params

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        # The path itself is not routed on. Vercel already decided which function got the
        # request, and the standalone server has exactly one endpoint, so a second
        # decision here could only disagree with the first.
        _, params = self._path()
        if "obs_id" not in params and "id" not in params:
            self._send(200, self._describe())
            return
        raw = params.get("obs_id", params.get("id"))
        self._measure(raw, cacheable=True)

    def do_POST(self) -> None:  # noqa: N802
        try:
            length_header = self.headers.get("content-length") or "0"
            try:
                length = int(length_header)
            except ValueError:
                raise LiveApiError(400, "BAD_CONTENT_LENGTH",
                                   "content-length must be an integer") from None
            if length > MAX_BODY_BYTES:
                raise LiveApiError(
                    413, "BODY_TOO_LARGE",
                    f"this endpoint takes one observation id, so the body is capped at "
                    f"{MAX_BODY_BYTES} bytes")
            raw_body = self.rfile.read(length) if length > 0 else b""
            if not raw_body:
                raise LiveApiError(400, "MISSING_OBS_ID",
                                   "post a JSON body of the form {\"obs_id\": 14836679}")
            try:
                parsed = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise LiveApiError(400, "BAD_JSON",
                                   "the body is not valid UTF-8 JSON") from None
            if not isinstance(parsed, dict):
                raise LiveApiError(400, "BAD_JSON",
                                   "the body must be a JSON object with an obs_id field")
            raw = parsed.get("obs_id", parsed.get("id"))
        except LiveApiError as exc:
            self._fail(exc)
            return
        self._measure(raw, cacheable=False)

    def _measure(self, raw: Any, *, cacheable: bool) -> None:
        key = _client_key(self.headers, self.client_address[0] if self.client_address
                          else "local")
        try:
            body = type(self).service.measure(raw, client_key=key)
        except LiveApiError as exc:
            self._fail(exc)
            return
        self._send(200, body, cacheable=cacheable)

    def _describe(self) -> dict[str, Any]:
        """What this endpoint is, for anyone who opens it in a browser."""
        return {
            "api": API_VERSION,
            "ok": True,
            "service": "TraceTriage live measurement",
            "what_it_does":
                "Measures one public SatNOGS observation now: propagates the pass from "
                "the record's own TLE, reads the frequency axis off the waterfall's "
                "rendered tick labels, fits a bounded frequency offset and calibrates it "
                "against that pass's own scrambled-Doppler null distribution.",
            "usage": {
                "post": "POST / with {\"obs_id\": 14836679}",
                "get": "GET /?obs_id=14836679",
            },
            "equivalent_cli": "tracetriage triage <obs_id> --json",
            "response":
                "The measurement is LiveMeasurement.to_dict() verbatim under "
                "`measurement`. Nothing is recomputed or reformatted here.",
            "outcomes": {
                "200": "a measurement, which may itself read UNRESOLVED with a reason",
                "422": "a named refusal: NOT_FOUND, NO_WATERFALL, NO_CENTRE, PHYSICS_*",
                "400": "the observation id is not a positive integer",
                "429": "rate limited, per caller and per instance",
                "502": "the public SatNOGS API was unreachable",
            },
            "permissions":
                "Read-only. Unauthenticated public API, no account, no credential, no "
                "write path. See docs/ACTOR_AND_PERMISSION_CONTRACT.md.",
            "data_licence":
                "Observation metadata and waterfall imagery are SatNOGS community data, "
                "CC BY-SA 4.0. See DATA_LICENSE.md.",
            "rate_limit": {
                "per_caller": f"{RATE_PER_CLIENT} per {int(RATE_WINDOW_S)} s",
                "per_instance": f"{RATE_PER_INSTANCE} per {int(RATE_WINDOW_S)} s",
                "cache_ttl_s": CACHE_TTL_S,
            },
        }

    def do_HEAD(self) -> None:  # noqa: N802
        self._send(200, self._describe())

    def do_PUT(self) -> None:  # noqa: N802
        self._reject_method()

    def do_DELETE(self) -> None:  # noqa: N802
        self._reject_method()

    def do_PATCH(self) -> None:  # noqa: N802
        self._reject_method()

    def _reject_method(self) -> None:
        self._fail(LiveApiError(
            405, "METHOD_NOT_ALLOWED",
            f"{self.command} is not a method this endpoint has. It reads: POST or GET.",
            kind="request"))

    def log_message(self, fmt: str, *args: Any) -> None:
        """One line per request on stderr, with no query string and no address.

        The default logs `self.path`, which carries the observation id, and the client
        address. Neither belongs in a log for a service that stores nothing about who
        asked.
        """
        print(f"live api: {self.command} -> {args[1] if len(args) > 1 else '?'}",
              file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    """The standalone server, which is the same handler with a socket under it.

    This exists so the endpoint can be exercised against the real API before anything is
    deployed. A worker whose numbers are only checkable in production is a worker whose
    numbers are not checked.
    """
    parser = argparse.ArgumentParser(
        prog="api/live.py",
        description="Serve pipeline.tracetriage.live.triage over HTTP, read-only.")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 by default: this is a development server and "
                             "binding it to every interface is not the default anyone "
                             "should have to opt out of")
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"live api on http://{args.host}:{args.port}/  "
          f"POST {{\"obs_id\": <id>}} or GET /?obs_id=<id>", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
