"""Cloud Granite on watsonx.ai, kept out of the loopback-only module on purpose.

:mod:`pipeline.tracetriage.granite` is the local runtime and it is loopback-only by
contract: ``tests/test_annotate.py`` proves the destination resolves to 127.0.0.1 before
the request is built, and the annotation store is proved unable to reach it through the
import graph. A cloud POST inside that file would break both arguments at once, because the
guard that makes the exemption safe is the guard that would have to be removed. So this is a
second module with its own write-verb exemption and its own asserted call-site count, and
``granite.py`` is left exactly as it was.

What this buys, and what it does not. The generation is the cheap half of the pipeline; the
half that decides anything is :func:`pipeline.tracetriage.explain.verify_note`, which runs
over the returned text without knowing or caring which backend produced it. So the honest
claim for a watsonx draft is not "the cloud model is better", it is "the same checker that
refuses a local draft inventing a downlink refuses a cloud one". A backend swap that changed
the checker would be worth nothing.

Raw httpx rather than ``ibm-watsonx-ai``. The SDK is a large dependency for two HTTP calls,
and this project publishes its install size (see ``pyproject.toml``): base is 166 MB and the
SDK pulls a resolver tree wider than the measurement path. Two requests written out are also
readable as provenance, which an SDK call is not.

Failure is typed, never text. Every way this can fail (no key, a key IAM rejects, an account
with no Watson Machine Learning instance, a project id the instance does not hold) returns a
named exception, so the runner records a dated skip rather than falling through to a
template and labelling the result watsonx. Inventing text here would make the receipt a lie
about which weights produced a published note, which is the exact failure this project's
whole grounding argument is built to prevent.

The runner is ``scripts/run_watsonx_check.py`` and it writes
``artifacts/WATSONX_RECEIPT.json``. Until 2026-08-22 there was none: this module had no
caller anywhere in the tree, and the sentence below about the variable names living in one
place named a runner, tests and an ``.env.example`` entry that did not exist. Finished code
with nothing calling it is not an integration, and a docstring describing a caller that is
absent is worse than one that says nothing.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

#: IBM Cloud's IAM token endpoint. An API key is exchanged for a bearer token that expires,
#: so this is a call every generation makes rather than a value that can be configured.
IAM_URL = "https://iam.cloud.ibm.com/identity/token"

#: IAM's grant type for an IBM Cloud API key. Spelled out because the urn is not guessable
#: from the docs page title and getting it wrong returns a 400 that reads like a bad key.
IAM_GRANT_TYPE = "urn:ibm:params:oauth:grant-type:apikey"

#: The regional Watson Machine Learning host. Overridable because an instance in eu-de or
#: jp-tok answers on a different host and a wrong region is a 404, not a redirect.
DEFAULT_URL = "https://us-south.ml.cloud.ibm.com"

#: The dated API contract for the text generation endpoint. watsonx requires the version
#: query parameter and rejects the request without it.
API_VERSION = "2023-05-29"

#: Granite 3.1 8B instruct as watsonx serves it. This project's local runtime is
#: granite3.1-dense:8b at Q4, so the two backends are the same model family at different
#: precision. Naming a 4.0 model here would be the easiest sentence to write and the
#: fastest way to lose the technical claim, because nothing in this repository has ever run
#: one.
MODEL_ID = "ibm/granite-3-8b-instruct"

#: Greedy decoding, matching the local backend's settings, so a difference between the two
#: drafts is the model and not the sampler.
DEFAULT_PARAMETERS: dict[str, Any] = {
    "decoding_method": "greedy",
    "max_new_tokens": 220,
    "min_new_tokens": 1,
    "repetition_penalty": 1.0,
}

#: Both calls. IAM is normally sub-second and generation is not, but a single timeout keeps
#: the failure mode one thing rather than two.
TIMEOUT_S = 90.0

#: Environment variable names, in one place, because the runner, the tests and
#: ``.env.example`` all have to agree about them.
ENV_API_KEY = "WATSONX_API_KEY"
ENV_PROJECT_ID = "WATSONX_PROJECT_ID"
ENV_URL = "WATSONX_URL"


class WatsonxError(RuntimeError):
    """Base for every watsonx failure, so a caller can catch the category."""


class CredentialsMissing(WatsonxError):
    """No API key or no project id in the environment.

    Separate from an authentication failure because the two mean different things in a
    receipt: this one says nobody has provisioned an instance, and a 403 says somebody did
    and the key does not carry the entitlement.
    """


class AuthenticationFailed(WatsonxError):
    """IAM rejected the key, or the token it issued does not carry the entitlement."""


class NoInstance(WatsonxError):
    """The token is good and there is no Watson Machine Learning deployment behind it.

    The most common real outcome of a free IBM Cloud account: IAM issues a token happily
    and the ML host answers 404 or "no WML instance" because none was ever created.
    """


class GenerationRefused(WatsonxError):
    """The service answered and the answer holds no usable text."""


@dataclass(frozen=True)
class WatsonxCredentials:
    """What a call needs, read once so a partial configuration fails before any request."""

    api_key: str
    project_id: str
    url: str

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> WatsonxCredentials:
        source = os.environ if env is None else env
        api_key = (source.get(ENV_API_KEY) or "").strip()
        project_id = (source.get(ENV_PROJECT_ID) or "").strip()
        url = (source.get(ENV_URL) or "").strip() or DEFAULT_URL
        missing = [
            name
            for name, value in ((ENV_API_KEY, api_key), (ENV_PROJECT_ID, project_id))
            if not value
        ]
        if missing:
            raise CredentialsMissing(
                f"{' and '.join(missing)} not set. watsonx is optional in this project: "
                f"the required path is the local Granite runtime in granite.py, and the "
                f"grounding checker is the same either way."
            )
        return WatsonxCredentials(api_key=api_key, project_id=project_id, url=url.rstrip("/"))

    def redacted(self) -> dict[str, str]:
        """What a receipt may record. The key never leaves this process."""
        return {
            "url": self.url,
            "project_id": f"{self.project_id[:8]}..." if self.project_id else "",
            "api_key": f"set, {len(self.api_key)} characters",
        }


@dataclass(frozen=True)
class Generation:
    """One completion and everything a receipt needs to say where it came from."""

    text: str
    model_id: str
    backend: str
    url: str
    generated_at: str
    input_token_count: int | None
    generated_token_count: int | None
    stop_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _send(url: str, **kwargs: Any) -> httpx.Response:
    """The single HTTP write-verb call site in this module.

    One helper rather than two inline calls, for the same reason ``granite.py`` has one:
    ``tests/test_annotate.py`` asserts the number of write-verb sites each exempted file
    holds, and an exemption whose size is asserted cannot widen without somebody arguing
    for the new size. Two calls would have made the count two and the argument weaker for
    no gain.

    Spelled ``client.post`` rather than ``client.request`` with the verb as an argument.
    The scanner counts a bare verb string as a write site too, which is correct of it, so
    the argument form would have put three sites in this file for two requests.
    """
    with httpx.Client(timeout=TIMEOUT_S) as client:
        return client.post(url, **kwargs)


def iam_token(credentials: WatsonxCredentials) -> str:
    """Exchange the API key for a bearer token.

    Kept separate from generation so a receipt can say which half failed. "IAM rejected the
    key" and "IAM issued a token and there is no ML instance" are the two most likely
    outcomes on a machine with no provisioned watsonx, and they are different skips.
    """
    try:
        response = _send(
            IAM_URL,
            data={"grant_type": IAM_GRANT_TYPE, "apikey": credentials.api_key},
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    except httpx.HTTPError as exc:
        raise WatsonxError(f"IAM unreachable at {IAM_URL}: {exc}") from exc

    if response.status_code in (400, 401, 403):
        raise AuthenticationFailed(
            f"IAM returned {response.status_code} for the API key: "
            f"{_short(response.text)}"
        )
    if response.status_code >= 400:
        raise WatsonxError(f"IAM returned {response.status_code}: {_short(response.text)}")

    try:
        token = response.json().get("access_token")
    except ValueError as exc:
        raise WatsonxError(f"IAM returned non-JSON: {_short(response.text)}") from exc
    if not isinstance(token, str) or not token:
        raise AuthenticationFailed(
            "IAM returned 200 with no access_token, so there is nothing to authorise with."
        )
    return token


def generate(
    prompt: str,
    *,
    credentials: WatsonxCredentials | None = None,
    model_id: str = MODEL_ID,
    parameters: dict[str, Any] | None = None,
) -> Generation:
    """One completion from watsonx Granite, or a typed failure. Never invented text."""
    creds = WatsonxCredentials.from_env() if credentials is None else credentials
    token = iam_token(creds)
    endpoint = f"{creds.url}/ml/v1/text/generation?version={API_VERSION}"
    payload = {
        "model_id": model_id,
        "input": prompt,
        "project_id": creds.project_id,
        "parameters": dict(DEFAULT_PARAMETERS if parameters is None else parameters),
    }

    try:
        response = _send(
            endpoint,
            content=json.dumps(payload),
            headers={
                "authorization": f"Bearer {token}",
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
    except httpx.HTTPError as exc:
        raise WatsonxError(f"{creds.url} unreachable: {exc}") from exc

    if response.status_code in (401, 403):
        raise AuthenticationFailed(
            f"{endpoint} returned {response.status_code}. The token is valid and does not "
            f"carry watsonx.ai text generation for project "
            f"{creds.project_id[:8]}...: {_short(response.text)}"
        )
    if response.status_code == 404:
        raise NoInstance(
            f"{endpoint} returned 404. Either the region in {ENV_URL} holds no Watson "
            f"Machine Learning instance for this account, or the project id does not "
            f"exist there: {_short(response.text)}"
        )
    if response.status_code >= 400:
        # A wrong project id, an account with no WML plan and a model the instance does not
        # serve all arrive here as a 400. The message is carried through rather than
        # summarised, because which of the three it is decides whether the skip is
        # "provision an instance" or "fix a variable".
        raise NoInstance(
            f"{endpoint} returned {response.status_code}: {_short(response.text)}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise GenerationRefused(f"non-JSON from {endpoint}: {_short(response.text)}") from exc

    results = body.get("results")
    if not isinstance(results, list) or not results:
        raise GenerationRefused(
            f"{endpoint} returned 200 with no results. Keys present: {sorted(body)}."
        )
    first = results[0]
    text = first.get("generated_text")
    if not isinstance(text, str) or not text.strip():
        raise GenerationRefused(
            f"{endpoint} returned a result with no generated_text. "
            f"Keys present: {sorted(first)}."
        )

    return Generation(
        text=text.strip(),
        model_id=model_id,
        backend="watsonx",
        url=creds.url,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        input_token_count=_int_or_none(first.get("input_token_count")),
        generated_token_count=_int_or_none(first.get("generated_token_count")),
        stop_reason=first.get("stop_reason") if isinstance(first.get("stop_reason"), str)
        else None,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _short(text: str, limit: int = 300) -> str:
    """Trim a service error body. The whole body can be an HTML page."""
    collapsed = " ".join((text or "").split())
    return collapsed if len(collapsed) <= limit else collapsed[:limit] + "..."
