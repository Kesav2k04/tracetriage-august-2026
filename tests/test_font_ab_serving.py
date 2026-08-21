"""The font A/B harness cannot leave a server behind, and cannot hold the export open.

The defect this pins. `scripts/build_font_ab.py` built three conditions and then printed
three shell commands of the form `cd <dir> && python -m http.server <port>`. Nothing owned
their lifetime, so one run on 2026-08-21 left six of them alive on ports 8101, 8102 and
8103. That is a nuisance on its own. The expensive part is the `cd`: a process whose working
directory is inside `apps/web/out` holds a Windows handle on that directory, so the next
`next build` failed with `EBUSY: resource busy or locked, rmdir` and the standing "console
build" gate went red for a reason with nothing to do with the console.

Two properties are asserted, and they are different claims. That the server dies on every
exit path is about lifetime; that the directory is handed to the handler rather than entered
is about the handle. Fixing only the first would still fail the next build for as long as a
run lasted, and fixing only the second would still leak a port.

Most of the work happens in a child interpreter. `conftest.py` blocks `socket.socket` in any
unmarked test, which is the right default and makes it impossible to bind a listener here,
and the subject of this test is a listener. So the child does the binding, makes its own
assertions against a real port, and reports them through its exit code: the parent asserts
on that. A child process also settles the survivor question by construction, since anything
it left running dies with it.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "scripts" / "build_font_ab.py"

#: Run in a child interpreter, one argument for the repository and one for a directory with
#: an index.html in it. Prints OK and exits 0, or prints what it found and exits 1. Written
#: as a script rather than as a test body because a listener cannot be bound from inside the
#: suite: see the module docstring.
_CHILD = '''
import http.client
import importlib.util
import os
import pathlib
import socket
import sys

repo, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location(
    "build_font_ab", repo / "scripts" / "build_font_ab.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

problems = []


def answered(port):
    """A real GET against a real port. The body proves it served the right directory."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/index.html")
        return b"served-from-here" in connection.getresponse().read()
    except OSError:
        return False
    finally:
        connection.close()


def free(port):
    """True when nothing is listening. The assertion after every exit path."""
    probe = socket.socket()
    probe.settimeout(2)
    try:
        probe.connect(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def a_free_port():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    holder.close()
    return port


class Boom(RuntimeError):
    pass


cwd_at_start = os.getcwd()

# 1. The ordinary path. It serves, the working directory does not move, and the port is
#    free again the moment the block ends.
with harness._served(root, 0) as httpd:
    clean_port = httpd.server_address[1]
    if not answered(clean_port):
        problems.append("clean: the server did not answer a GET")
    if os.getcwd() != cwd_at_start:
        problems.append("clean: the working directory moved into the served tree")
if not free(clean_port):
    problems.append("clean: something is still listening after the block ended")

# 2. The path that leaked. An exception out of the middle of a measurement is the ordinary
#    way a harness ends, and it must take the server with it.
raised = {}
try:
    with harness._served(root, 0) as httpd:
        raised["port"] = httpd.server_address[1]
        if not answered(raised["port"]):
            problems.append("exception: the server did not answer a GET")
        raise Boom("the harness failed mid-run")
except Boom:
    pass
else:
    problems.append("exception: the exception did not propagate to the caller")
if not free(raised["port"]):
    problems.append("exception: the port survived an exception")

# 3. Ctrl-C. KeyboardInterrupt is not an Exception, so an `except Exception:` teardown
#    would pass tests 1 and 2 and still leak every server a person ever interrupted.
interrupted = {}
try:
    with harness._served(root, 0) as httpd:
        interrupted["port"] = httpd.server_address[1]
        raise KeyboardInterrupt
except KeyboardInterrupt:
    pass
if not free(interrupted["port"]):
    problems.append("interrupt: the port survived a Ctrl-C")

# 4. All three conditions at once, and then the same set with the last port already taken.
#    A set of servers is all or nothing: a run that served two of three would measure a
#    comparison with no floor, and the two it did bind would outlive the failure.
ports = [a_free_port() for _ in range(3)]
harness.PORTS = dict(zip(("after", "before", "nokit"), ports))
built = root.parent / "conditions"
for name in harness.PORTS:
    (built / name).mkdir(parents=True, exist_ok=True)
    (built / name / "index.html").write_bytes(b"served-from-here")

with harness._serve_all(built) as origins:
    if sorted(origins) != ["after", "before", "nokit"]:
        problems.append(f"serve_all: served {sorted(origins)}")
    for port in ports:
        if free(port):
            problems.append(f"serve_all: nothing listening on {port}")
for port in ports:
    if not free(port):
        problems.append(f"serve_all: {port} survived the block")

blocker = socket.socket()
blocker.bind(("127.0.0.1", ports[2]))
blocker.listen(1)
try:
    with harness._serve_all(built):
        problems.append("serve_all: bound a port that was already taken")
except OSError:
    pass
finally:
    blocker.close()
for port in ports[:2]:
    if not free(port):
        problems.append(f"serve_all: {port} was left behind when a later bind failed")

print("; ".join(problems) if problems else "OK")
sys.exit(1 if problems else 0)
'''


def test_no_server_outlives_a_run_on_any_exit_path(tmp_path):
    """A real server on a real port, torn down on all three ways out of the block."""
    root = tmp_path / "served"
    root.mkdir()
    (root / "index.html").write_bytes(b"served-from-here")
    child = tmp_path / "exercise_served.py"
    child.write_text(_CHILD, encoding="utf-8")

    finished = subprocess.run(  # noqa: S603  (fixed argv, no shell)
        [sys.executable, str(child), str(REPO), str(root)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    # stdout only. `SimpleHTTPRequestHandler` logs every request to stderr, so a verdict
    # read off both streams is a verdict mixed with an access log.
    verdict = (finished.stdout or "").strip()
    context = f"{verdict}\nstderr: {(finished.stderr or '').strip()[-600:]}"
    assert finished.returncode == 0, context
    assert verdict == "OK", context


def _literal_text(node: ast.AST) -> str:
    """The literal half of a string node, interpolations dropped.

    The instruction is an f-string built from two adjacent literals, so `-m http.server`
    and `--directory` land in different `Constant` nodes of one `JoinedStr`. Reading the
    parts separately would look at half a command each.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


def _serve_instructions() -> list[str]:
    """Every string in the harness that spells an `http.server` invocation, prose excluded.

    Parsed rather than grepped, and the docstrings are subtracted. The first version of
    this test read the file line by line and failed on the module docstring, which quotes
    the broken command to explain why it is broken. A scanner that cannot tell a command
    from a sentence about a command reports the fix as the defect.
    """
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    prose: set[int] = set()
    nested: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                prose.add(id(first.value))
        if isinstance(node, ast.JoinedStr):
            nested.update(id(part) for part in ast.walk(node) if part is not node)
    return [
        text
        for node in ast.walk(tree)
        if id(node) not in prose
        and id(node) not in nested
        and "-m http.server" in (text := _literal_text(node))
    ]


def test_the_printed_instruction_does_not_enter_the_directory_it_serves():
    """The `cd` is the part that failed the console build, so the print is what is read.

    A behavioural test cannot reach this: the leaked handle came from a shell command this
    script printed for a person to run, and nothing in the process that printed it holds
    anything. What is checkable is that the instruction no longer tells anyone to stand
    inside an export, and that it names the flag which makes standing there unnecessary.
    """
    instructions = _serve_instructions()
    assert instructions, "the serve instruction has gone; this test is checking nothing"
    for text in instructions:
        assert "cd " not in text, (
            f"the printed instruction still enters the directory it serves: {text!r}. A "
            f"process whose working directory is inside apps/web/out holds a Windows handle "
            f"on it, and the next next build fails with EBUSY on rmdir."
        )
        assert "--directory" in text, (
            f"the printed instruction serves without --directory: {text!r}. Without it, "
            f"http.server serves the working directory, which is the whole defect."
        )


def test_serving_refuses_a_condition_that_was_never_built(tmp_path):
    """A missing condition is a refusal, not a server and a silent gap.

    `_serve_all` raises on the first condition with no index.html, which is before it has
    bound anything, so this one needs no socket and runs inside the suite. Serving an empty
    directory would hand the measurement harness 404s, and those read as a broken page
    rather than as a missing build.
    """
    harness = _load_harness()
    with pytest.raises(SystemExit, match="never built"), harness._serve_all(tmp_path):
        pass


def _load_harness():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_font_ab", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
