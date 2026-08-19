"""The only module in this repository that issues an HTTP write verb (unit E1).

Everything else here reads. The snapshot fetcher reads the SatNOGS API, the annotation
store refuses any sink that is not a local path, and ``tests/test_annotate.py`` asserts
that no ``.post()``, ``.put()``, ``.patch()`` or ``.delete()`` call exists anywhere in
first-party code. Running a local IBM Granite model needs one POST, because that is the
shape of the runtime's API, so that rule now carries a named exemption instead of being
quietly deleted:

* the exemption is this file and no other, and the test asserts this file contains
  **exactly one** write-verb call site, so it cannot grow without the count changing,
* the destination is proved to be loopback before the request is built, by
  :func:`resolve_model_endpoint`, which refuses any other host the way
  :func:`~pipeline.tracetriage.annotate.resolve_store_path` refuses a URL sink,
* nothing that touches SatNOGS or the annotation store imports this module, and
  ``tests/test_explain.py`` walks the verifier's import closure to prove the part that
  decides whether a generated note may ship has no network capability at all.

The reason for the guard is not hypothetical. An endpoint read from configuration is one
typo away from sending a reviewer's evidence packet to a third party, and the packet
carries station identifiers and coordinates. A model that runs on this machine cannot do
that, and the only way to be sure the model runs on this machine is to refuse to speak to
anything else.

Determinism, measured and absent. Temperature is zero, top-p is one and the seed is
fixed, which is the whole of what this API offers, and it is not enough: repeating the same
twenty-five prompts inside one process changed eighteen of fifty drafts, and repeating them
in a fresh process after asking the runtime to unload the model changed forty-two of
seventy-five. Around one repeat in nine crossed the grounding checker's accept or refuse
decision. One earlier freeze produced no differences at all across seventy-five repeats, so
the instability is itself variable and cannot be designed around by retrying.

The consequence is architectural rather than a caveat. Text that a reviewer is shown has to
be committed, not regenerated, so ``scripts/run_explanations.py`` freezes the drafts into
``tests/fixtures/granite_notes.json`` and every later step reads that file. The receipt
records the model digest, the prompt digest and the digest of each frozen draft, and the
offline test suite replays the fixture rather than calling the model at all.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx

#: The runtime's default. Overridable, but only within the loopback constraint.
DEFAULT_ENDPOINT = "http://127.0.0.1:11434"

#: The model this project generates with. Named in full so the receipt and the code
#: cannot disagree about which weights produced a published note.
MODEL = "granite3.1-dense:8b"

#: Threaded into the sampler. Fixed on the expectation that it would make a re-run
#: reproduce the text, which it does not: see the measurement above. It stays fixed
#: because a varying seed would add a second source of difference to a run that
#: already has one nobody has isolated.
SEED = 7

#: Enough for four sentences and not enough for a page. A note that runs long is a note
#: the reviewer will not read, and every extra token is another chance to invent a number.
MAX_TOKENS = 220

#: Generation must not outlive a reviewer's patience or a build step's timeout.
TIMEOUT_S = 120.0


class RemoteModelRefused(ValueError):
    """Raised when a model endpoint is not on the loopback interface."""


class ModelUnavailable(RuntimeError):
    """Raised when the local runtime is not answering. Callers degrade, they do not guess."""


def resolve_model_endpoint(endpoint: str = DEFAULT_ENDPOINT) -> str:
    """Return ``endpoint`` if it is loopback, otherwise refuse.

    ``localhost`` is resolved rather than trusted, because a hosts-file entry can point it
    anywhere, and a name that resolves off-machine is exactly the case this guard exists
    for. Every resolved address has to be loopback, not merely the first one.
    """
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteModelRefused(
            f"A model endpoint must be an http(s) URL on this machine. Got "
            f"{endpoint!r} with scheme {parsed.scheme!r}."
        )
    host = parsed.hostname
    if not host:
        raise RemoteModelRefused(f"A model endpoint must name a host. Got {endpoint!r}.")

    try:
        addresses = {ip_address(host)}
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)
        except OSError as exc:  # pragma: no cover - depends on the resolver
            raise RemoteModelRefused(
                f"A model endpoint must resolve to a loopback address. {host!r} did not "
                f"resolve: {exc}."
            ) from exc
        addresses = {ip_address(info[4][0]) for info in infos}

    remote = sorted(str(a) for a in addresses if not a.is_loopback)
    if remote or not addresses:
        raise RemoteModelRefused(
            f"A model endpoint must be on the loopback interface. {endpoint!r} resolves to "
            f"{remote or 'nothing'}. Generated notes carry station identifiers and "
            f"coordinates, so the model runs here or it does not run."
        )
    return endpoint


@dataclass(frozen=True)
class ModelIdentity:
    """What produced a note, in enough detail to re-derive it or to explain a difference."""

    name: str
    digest: str
    parameter_size: str
    quantization: str
    context_length: int

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "digest": self.digest,
            "parameter_size": self.parameter_size,
            "quantization": self.quantization,
            "context_length": self.context_length,
        }


def model_identity(endpoint: str = DEFAULT_ENDPOINT, model: str = MODEL) -> ModelIdentity:
    """Read the installed model's identity from the runtime. A GET, and a required one.

    Publishing a note without recording which weights wrote it makes the note
    unreproducible, and this project's whole argument is that a published claim names the
    artifact it came from.
    """
    base = resolve_model_endpoint(endpoint)
    try:
        response = httpx.get(f"{base}/api/tags", timeout=15.0)
        response.raise_for_status()
        tags = response.json()
    except Exception as exc:
        raise ModelUnavailable(
            f"The local model runtime at {base} is not answering: {exc}. Notes are "
            f"generated by a model on this machine, so with no runtime there is nothing "
            f"to generate with and the deterministic note ships instead."
        ) from exc

    for entry in tags.get("models", []):
        if entry.get("name") == model:
            details = entry.get("details", {})
            return ModelIdentity(
                name=model,
                digest=str(entry.get("digest", "")),
                parameter_size=str(details.get("parameter_size", "")),
                quantization=str(details.get("quantization_level", "")),
                context_length=int(details.get("context_length", 0)),
            )
    installed = sorted(str(e.get("name")) for e in tags.get("models", []))
    raise ModelUnavailable(
        f"{model!r} is not installed at {base}. Installed: {installed}. Pull it with "
        f"`ollama pull {model}` or accept the deterministic note."
    )


#: The embedding model, separate from the generator on purpose: a 278M embedding model and an
#: 8B instruct model are different weights doing different jobs, and a receipt that named one
#: for both would be wrong about whichever it was not.
EMBED_MODEL = "granite-embedding:278m"


def _post(path: str, payload: dict, *, endpoint: str, timeout: float) -> dict:
    """The single HTTP write-verb call site in this repository.

    Both the generator and the embedder go through here. Adding a second ``httpx.post``
    elsewhere in this module would be the cheaper edit and it would also make the claim in
    the claim register false: ``tests/test_annotate.py`` asserts that this file holds exactly
    one write site, and an exemption whose size is asserted is the only kind that cannot widen
    quietly. The loopback guard runs before the URL is built, once, for both callers.
    """
    base = resolve_model_endpoint(endpoint)
    try:
        response = httpx.post(
            f"{base}{path}",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise ModelUnavailable(f"{path} failed against {base}: {exc}") from exc


def embed(
    text: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = EMBED_MODEL,
) -> list[float]:
    """One embedding vector for one string, from the local runtime.

    Returns the raw vector rather than a normalised one. Normalisation belongs to whatever
    computes a similarity, so that a caller reading these vectors back from a fixture cannot
    accidentally compare a normalised vector against an unnormalised one.
    """
    body = _post(
        "/api/embeddings", {"model": model, "prompt": text}, endpoint=endpoint, timeout=TIMEOUT_S
    )
    vector = body.get("embedding")
    if not isinstance(vector, list) or not vector:
        raise ModelUnavailable(
            f"The runtime returned no embedding for a {len(text)}-character string. "
            f"Keys present: {sorted(body)}."
        )
    return [float(x) for x in vector]


def generate(
    prompt: str,
    *,
    endpoint: str = DEFAULT_ENDPOINT,
    model: str = MODEL,
    seed: int = SEED,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """One completion, greedy, from the local runtime."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": seed,
            "num_predict": max_tokens,
        },
    }
    body = _post("/api/generate", payload, endpoint=endpoint, timeout=TIMEOUT_S)

    text = body.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ModelUnavailable(
            f"The runtime returned no text for a {len(prompt)}-character prompt. "
            f"Keys present: {sorted(body)}."
        )
    return text.strip()
