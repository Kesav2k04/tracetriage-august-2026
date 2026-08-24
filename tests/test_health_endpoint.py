"""`api/health.py`: the endpoint that says whether the deployed console is this repository.

The claim it makes is a digest, and there are exactly three ways that claim goes wrong.

* The digest is of the wrong bytes. So the digest here is recomputed from the file and
  compared, rather than the response being checked for the presence of a hex string.
* The function is deployed without the file it hashes, because a Python function on Vercel
  gets its own filesystem and not the static export's. That is a `vercel.json` property and
  not a Python one, so it is checked in `vercel.json`.
* The function reports the six gate verdicts against nulls. The first version asked the
  gate records for `id` and `name`; the keys are `gate` and `title`. A wrong dict key does
  not raise, it returns None, and a judge reading six verdicts attached to nothing has no
  way to know whether that means unnamed or unmeasured.

And one property that is not a claim about correctness but about whether the endpoint is
worth having: it has to answer while `api/live.py` is still importing scipy. That is
enforced by running it under an interpreter with no site-packages at all, the same argument
`tests/test_mcp_server.py` makes for the evidence server.
"""

from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HEALTH = REPO / "api" / "health.py"
PROVENANCE = REPO / "apps" / "web" / "public" / "data" / "provenance.json"
VERCEL = REPO / "vercel.json"

sys.path.insert(0, str(REPO / "api"))
import health  # noqa: E402

#: HTTP's line ending, written as its two bytes rather than as an escape. Not a style
#: choice: every scripted edit that put this file together went through a shell heredoc,
#: which ate one backslash, and the surviving single backslash was then read by Python as a
#: real carriage return inside a byte literal. The file looked correct in an editor and
#: failed to parse. Two integers cannot be misread by anything in that chain.
CRLF = bytes([13, 10])


def test_the_digest_is_the_digest_of_the_file_it_names() -> None:
    served = health.payload()["served_data"]
    assert served["present"] is True
    assert served["sha256"] == hashlib.sha256(PROVENANCE.read_bytes()).hexdigest()
    assert served["bytes"] == PROVENANCE.stat().st_size
    assert served["file"] == "apps/web/public/data/provenance.json"


def test_every_gate_verdict_is_attached_to_a_gate() -> None:
    """The wrong-key defect. `None` here would read as unmeasured rather than as a bug."""
    gates = health.payload()["served_data"]["gates"]
    published = json.loads(PROVENANCE.read_text(encoding="utf-8"))["gate_summary"]
    assert gates["total"] == published["n_gates"]
    assert gates["met"] == published["n_met"]
    assert len(gates["verdicts"]) == published["n_gates"]
    for entry in gates["verdicts"]:
        assert entry["gate"] is not None, entry
        assert entry["title"], entry
        assert entry["verdict"] in {"PRE_PASSED", "PASSED", "NOT_ESTABLISHED", "FAILED"}, entry


def test_the_response_says_what_it_did_not_check() -> None:
    """A health endpoint that answers `ok` for things it never touched is worse than none."""
    body = health.payload()
    assert body["status"] == "ok"
    assert any("SatNOGS" in line for line in body["not_checked_here"])
    assert "sha256sum" in body["verify"]["how"]


def test_absent_environment_variables_are_null_and_not_empty_strings() -> None:
    """A CLI deployment has no git metadata. An empty string would read as a blank value."""
    deployment = health.payload()["deployment"]
    assert set(deployment) == {
        "env",
        "region",
        "git_commit_sha",
        "git_commit_ref",
        "deployment_id",
    }
    assert all(value is None or value for value in deployment.values())


class _Connection:
    """A socket-shaped object with no socket in it.

    `tests/conftest.py` replaces `socket.socket` for every test that is not marked
    `network`, which is the reason the offline replay claim means anything. Binding a
    loopback port here would have needed that marker, and the marker would have taken this
    test out of the offline suite: the endpoint's HTTP behaviour would then be unmeasured in
    exactly the run that is supposed to prove the repository stands up on its own. So the
    request is handed to the handler over two BytesIO buffers instead. `makefile` and
    `sendall` are the whole surface `BaseHTTPRequestHandler` uses.
    """

    def __init__(self, request: bytes) -> None:
        self._incoming = io.BytesIO(request)
        self.sent = io.BytesIO()

    def makefile(self, mode: str = "r", *_args, **_kwargs):
        return self._incoming if "r" in mode else self.sent

    def sendall(self, data: bytes) -> None:
        self.sent.write(data)

    def close(self) -> None:
        pass

    def shutdown(self, _how: int) -> None:
        pass


def _request(method: str, path: str, body: bytes = b"") -> bytes:
    """One raw HTTP/1.1 request, assembled from lines rather than written as one blob."""
    lines = [f"{method} {path} HTTP/1.1", "Host: localhost", "Connection: close"]
    if body:
        lines.append(f"Content-Length: {len(body)}")
    head = CRLF.join(line.encode("ascii") for line in lines)
    return head + CRLF + CRLF + body


def _exchange(request: bytes) -> tuple[int, dict[str, str], bytes]:
    """Run one request through the handler and split the raw response."""
    connection = _Connection(request)
    health.handler(connection, ("127.0.0.1", 0), None)
    raw = connection.sent.getvalue()
    head, _, body = raw.partition(CRLF + CRLF)
    lines = head.decode("latin-1").split(CRLF.decode("ascii"))
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()
    return status, headers, body


def test_it_answers_a_get_and_refuses_to_be_written_to() -> None:
    status, headers, body = _exchange(_request("GET", "/api/health/"))
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body)["schema"] == "tracetriage/health"

    status, _, body = _exchange(_request("POST", "/api/health/", b"{}"))
    assert status == 405
    assert json.loads(body)["code"] == "METHOD_NOT_ALLOWED"


def test_it_answers_under_an_interpreter_with_no_installed_packages() -> None:
    """The cold-start claim, run rather than argued.

    `-S` drops site-packages and `-E` drops the ambient environment. The live endpoint
    cannot pass this and is not supposed to: it imports numpy and scipy and takes tens of
    seconds to wake. This one has to answer while that is happening.
    """
    finished = subprocess.run(
        [sys.executable, "-S", "-E", str(HEALTH)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    assert json.loads(finished.stdout)["status"] == "ok"


def test_the_deployment_gives_the_function_the_file_it_hashes() -> None:
    """Without this line in vercel.json the endpoint deploys and reports `present: false`.

    It did. The first version declared the bare path
    `apps/web/public/data/provenance.json`, nothing was bundled, and the deployed function
    answered `present: false` on the one question it exists to answer. `api/live.py` beside
    it declares `pipeline/**` and gets its files, so the pattern has to glob.

    So this asserts two properties rather than a literal string: the pattern contains a glob
    character, and it matches the path of the file the function actually reads. Pinning the
    string is what let the bare path through, because the string was exactly what its author
    intended.
    """
    config = json.loads(VERCEL.read_text(encoding="utf-8"))
    declared = config["functions"]["api/health.py"]
    pattern = declared["includeFiles"]
    assert any(ch in pattern for ch in "*?["), (
        f"includeFiles is {pattern!r}, a bare path. Vercel bundles nothing for it, and the "
        "function deploys reporting present: false."
    )
    target = "apps/web/public/data/provenance.json"
    assert (REPO / target).is_file(), f"{target} is not in the tree, so nothing can include it"
    assert fnmatch.fnmatch(target, pattern) or fnmatch.fnmatch(target, pattern + "/**"), (
        f"includeFiles {pattern!r} does not match {target!r}, which is the file the function "
        "hashes"
    )
    # The console is exported with `trailingSlash: true`, so a link to /api/health/ is what
    # a reader will follow. Vercel routes the function at /api/health.
    sources = {rule["source"] for rule in config["rewrites"]}
    assert "/api/health/" in sources
