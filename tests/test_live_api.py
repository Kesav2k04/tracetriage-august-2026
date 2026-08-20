"""The live endpoint: what it validates, what it caches, and what it may not do.

`api/live.py` is the only part of this project a stranger can make run. Everything else
is a file in a repository or a command someone chose to type. That changes what has to be
true about it, and these are the four things:

1. It measures nothing itself. Every number in a response comes from
   `live.LiveMeasurement.to_dict`, the same serialiser the CLI prints, so the endpoint
   cannot disagree with the command line about a measurement they both name.
2. It refuses garbage before it reaches the engine, and a refusal carries a code.
3. It is read-only, and structurally so: no write verb exists in its module graph.
4. A second reader asking for the same observation within a day pays nothing, because a
   volunteer-run API should not serve the same waterfall twice for one answer.

Nothing here touches the network. The engine is replaced with a stub, which is also what
makes the cache and the rate limiter testable at all: both are about repeated calls, and
a test that measured a real pass twice would be measuring SatNOGS's patience.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
API = REPO / "api" / "live.py"


@pytest.fixture(scope="module")
def api():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("api_live", API)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "14829364",
        14829364,
        " 14829364 ",
    ],
)
def test_an_observation_id_is_accepted_in_the_forms_a_reader_sends(api, raw):
    assert api.parse_obs_id(raw) == 14829364


@pytest.mark.parametrize(
    "raw",
    [
        "",
        None,
        "0",
        "-5",
        "1.5",
        "14829364; DROP TABLE",
        "https://network.satnogs.org/observations/14829364/",
        "9" * 12,
        True,
        [14829364],
    ],
)
def test_anything_that_is_not_an_id_is_refused_with_a_code(api, raw):
    with pytest.raises(api.LiveApiError) as raised:
        api.parse_obs_id(raw)
    assert raised.value.code, "a refusal with no code cannot be shown to a reader"
    assert raised.value.status in (400, 422)


def test_a_body_larger_than_the_cap_is_not_parsed(api):
    assert api.MAX_BODY_BYTES <= 8192, (
        "the only legal body is one integer, so the cap exists to stop an endpoint "
        "reading a megabyte before it decides it does not want it"
    )


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


def test_the_same_observation_is_measured_once(api):
    calls: list[int] = []

    def fake_triage(obs_id, **kwargs):
        calls.append(int(obs_id))

        class Stub:
            def to_dict(self):
                return {"schema": "LIVE_MEASUREMENT", "observation": {"id": int(obs_id)}}

        return Stub()

    # Injected, not patched. The service takes its engine as a constructor argument for
    # exactly this reason, and patching the module attribute would leave a suite that
    # passes while the wiring it is meant to check has been removed.
    service = api.LiveService(triage=fake_triage)

    first = service.measure(14829364)
    second = service.measure(14829364)

    assert calls == [14829364], f"the engine ran {len(calls)} times for one id"
    assert first["measurement"] == second["measurement"]
    assert first["cached"] is False
    assert second["cached"] is True


def test_a_refusal_is_not_cached_as_a_measurement(api):
    """A pass with no stored waterfall may have one an hour later."""

    def fake_triage(obs_id, **kwargs):
        raise api.live_engine.LiveRefusal("NO_WATERFALL", "no image was stored")

    service = api.LiveService(triage=fake_triage)

    with pytest.raises(api.LiveApiError) as raised:
        service.measure(14829364)
    assert raised.value.code == "NO_WATERFALL"
    assert raised.value.status == 422
    assert service.cache.get(14829364) is None


def test_the_cache_is_bounded(api):
    """An endpoint anyone can call cannot hold every observation it is ever asked for."""
    assert api.CACHE_MAX_ENTRIES <= 1024
    assert api.CACHE_TTL_S <= 7 * 86_400


# ---------------------------------------------------------------------------
# Read-only, structurally
# ---------------------------------------------------------------------------

#: Every way this module graph could write somewhere it must not.
#:
#: The permission contract in docs/ACTOR_AND_PERMISSION_CONTRACT.md allows exactly two
#: verbs against SatNOGS: read the public API, download a published waterfall. A POST
#: from this endpoint would be a write with a stranger's request behind it, which is the
#: one failure this project cannot recover from by publishing a receipt.
_WRITE_VERBS = (
    # `.post(` on an HTTP client only. `self.cache.put(...)` is an in-process dict and
    # the first version of this scan flagged it, which is the shape of a rule that looks
    # for a word instead of for the thing the word does.
    r"(?:client|session|httpx|requests|_client)\s*\.post\(",
    r"(?:client|session|httpx|requests|_client)\s*\.put\(",
    r"(?:client|session|httpx|requests|_client)\s*\.patch\(",
    r"(?:client|session|httpx|requests|_client)\s*\.delete\(",
    r"requests\.post",
    r"urlopen\([^)]*data=",
)


def test_no_write_verb_exists_in_the_endpoint_or_its_engine():
    for name in (
        "api/live.py",
        "pipeline/tracetriage/live.py",
        "pipeline/tracetriage/snapshot.py",
    ):
        source = (REPO / name).read_text(encoding="utf-8")
        # Strip comments and docstrings before matching: this test's own explanation of
        # what it forbids used to trip it, which is the shape of a scanner that flags
        # its own fixture.
        stripped = re.sub(r'"""[\s\S]*?"""', "", source)
        stripped = re.sub(r"^\s*#.*$", "", stripped, flags=re.MULTILINE)
        for verb in _WRITE_VERBS:
            assert not re.search(verb, stripped), f"{name} contains {verb}"


def test_the_endpoint_holds_no_credential():
    source = (REPO / "api" / "live.py").read_text(encoding="utf-8")
    for forbidden in ("API_KEY", "SECRET", "TOKEN", "Authorization"):
        assert forbidden not in source, (
            f"{forbidden} appears in the live endpoint. It reads a public API and needs "
            f"nothing, and a secret on the judged deployment is a secret in a build log."
        )


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_the_response_carries_no_second_copy_of_a_measurement(api):
    """A number in two places is a number that can disagree with itself."""

    def fake_triage(obs_id, **kwargs):
        class Stub:
            def to_dict(self):
                return {
                    "schema": "LIVE_MEASUREMENT",
                    "observation": {"id": int(obs_id)},
                    "mode": {"verdict": "UNCORRECTED"},
                    "measurement": {"offset_ppm": 0.5476},
                }

        return Stub()

    service = api.LiveService(triage=fake_triage)
    body = service.measure(14829364)

    envelope = {k: v for k, v in body.items() if k != "measurement"}
    flat = json.dumps(envelope)
    assert "0.5476" not in flat, "the envelope repeats a measured value"
    assert "UNCORRECTED" not in flat, "the envelope repeats the mode verdict"
    # And it says the things only the envelope knows.
    assert body["api"] == api.API_VERSION
    assert "served_at_utc" in body
    assert "cached" in body
