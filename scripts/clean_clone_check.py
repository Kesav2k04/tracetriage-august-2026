"""Reproduce this repository from a clean clone, with the network refused.

What this answers: can a judge clone the repository and regenerate the numbers, and if
not, exactly which ones and why. The unit that asked for it named the failure modes to
look for: an artifact that exists only because it was built once and never regenerated, a
script that reads a path outside the repository, a test that passes only because a cache
is warm, and any step that silently reaches the network.

How the network is refused, so the claim is checkable rather than asserted: a
``sitecustomize.py`` is written into the clone and put on ``PYTHONPATH``, so every Python
process started for this run imports it at interpreter startup. It replaces
``socket.socket.connect``, ``connect_ex`` and ``socket.getaddrinfo`` with versions that
raise on any address that is not loopback. Loopback stays open because torch and
multiprocessing use it locally, and blocking it would measure the wrong thing. Node steps
get ``NEXT_TELEMETRY_DISABLED`` and a dead proxy, which is weaker, and the transcript says
so rather than implying parity.

Two prerequisites are deliberately not reinstalled, and both are recorded with their
versions in the transcript rather than hidden:

* The Python environment. The run builds one inside the clone with ``uv venv`` and installs
  into it with ``uv pip install --python <the clone's interpreter> --offline``, so the wheels
  come from the local uv cache and never from an index. A judge with no warm cache needs one
  network install before this reproduces, which is what the transcript records as the
  prerequisite. When that install fails, the source clone's interpreter is used against the
  clone's source tree instead, the transcript says so, and the number that comes out is then
  a statement about this code in isolation rather than about this environment.
* ``apps/web/node_modules``, 425 MB. ``npm ci`` needs the registry. It is linked from the
  source clone so the console steps can run at all, and the transcript names it as a
  prerequisite with the lockfile digest that pins it.

Usage::

    .venv\\Scripts\\python.exe scripts\\clean_clone_check.py --clone-dir D:\\_cleanclone
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]

def _resolve_uv_cache(uv: str | None) -> dict:
    """Where the offline install would look, as a path rather than as a variable name.

    The earlier transcript recorded `UV_CACHE_DIR` or the words "uv's default location",
    which names the setting rather than the thing the run depended on. `UV_CACHE_DIR` is
    unset on this machine and uv's default sits under the user profile on C:, while this
    project keeps its caches on D:, so the offline install resolved against a cache that
    had never seen these wheels and failed on torch. That is a prerequisite not being
    met rather than a defect in the repository, and it is only readable if the path is
    written down.
    """
    if not uv:
        return {"resolved": None, "why": "uv is not on PATH, so nothing resolves it"}
    proc = subprocess.run([uv, "cache", "dir"], capture_output=True, text=True)
    resolved = proc.stdout.strip() or None
    exists = bool(resolved) and Path(resolved).is_dir()
    return {
        "resolved": resolved,
        "exists": exists,
        "from_env": os.environ.get("UV_CACHE_DIR"),
        "why": (
            "the directory --offline resolves wheels from. It is recorded as a path "
            "because the variable name alone does not say which cache a run used, and "
            "two caches on this machine hold different wheel sets."
        ),
    }


_SITECUSTOMIZE = '''\
"""Refuse every outbound socket that is not loopback, and optionally hide the snapshot.

Written by scripts/clean_clone_check.py into a directory OUTSIDE the clone, which is then
put on PYTHONPATH. Outside, because a file added to the clone would be linted, tested and
counted as part of the tree, and the point of a clean clone is that nothing was added.

Two guards:

* The network. connect, connect_ex and getaddrinfo raise on any non-loopback address, so
  a step that reaches out fails loudly instead of quietly succeeding.
* The snapshot, when CLEAN_CLONE_HIDE_SNAPSHOT=1. Every path under the snapshot root
  reports itself absent and refuses to open. That answers a question the presence of the
  4 GB directory on this machine would otherwise hide: what does a judge who does not
  have it actually get when they run the suite.
"""
import builtins
import os
import pathlib
import socket

#: Loopback by address range rather than by a list of three strings. The list refused
#: 127.0.0.2, which is loopback, and accepted the name "localhost" without resolving it. A
#: name cannot be resolved here at all, because this file has replaced the resolver, so
#: exactly one name is allowed and the asymmetry with granite.py's resolve_model_endpoint,
#: which does resolve because it runs online, is deliberate.
_ALLOWED_NAMES = {"localhost", ""}
_SNAPSHOT_ROOT = "d:/tracetriage_data"  # compared after backslashes are normalised


class OfflineViolation(RuntimeError):
    pass


def _host_of(address):
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


def _is_loopback(host):
    text = str(host).strip().strip("[]").lower()
    if text in _ALLOWED_NAMES:
        return True
    if text == "::1":
        return True
    parts = text.split(".")
    if len(parts) == 4 and parts[0] == "127":
        return all(part.isdigit() and 0 <= int(part) <= 255 for part in parts[1:])
    return False


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _connect(self, address, *a, **k):
    host = _host_of(address)
    if not _is_loopback(host):
        raise OfflineViolation(
            f"outbound connect to {host!r} refused: clean-clone run is offline"
        )
    return _real_connect(self, address, *a, **k)


def _connect_ex(self, address, *a, **k):
    host = _host_of(address)
    if not _is_loopback(host):
        raise OfflineViolation(
            f"outbound connect_ex to {host!r} refused: clean-clone run is offline"
        )
    return _real_connect_ex(self, address, *a, **k)


def _getaddrinfo(host, *a, **k):
    if not _is_loopback(host):
        raise OfflineViolation(
            f"DNS lookup of {host!r} refused: clean-clone run is offline"
        )
    return _real_getaddrinfo(host, *a, **k)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo


def _under_snapshot(path):
    try:
        text = str(path).lower().replace("\\\\", "/")
    except Exception:
        return False
    return text.startswith(_SNAPSHOT_ROOT)


if os.environ.get("CLEAN_CLONE_HIDE_SNAPSHOT") == "1":
    _real_exists = pathlib.Path.exists
    _real_is_dir = pathlib.Path.is_dir
    _real_is_file = pathlib.Path.is_file
    _real_iterdir = pathlib.Path.iterdir
    _real_glob = pathlib.Path.glob
    _real_open = builtins.open
    _real_os_exists = os.path.exists

    def _exists(self, *a, **k):
        return False if _under_snapshot(self) else _real_exists(self, *a, **k)

    def _is_dir(self, *a, **k):
        return False if _under_snapshot(self) else _real_is_dir(self, *a, **k)

    def _is_file(self, *a, **k):
        return False if _under_snapshot(self) else _real_is_file(self, *a, **k)

    def _iterdir(self, *a, **k):
        if _under_snapshot(self):
            raise FileNotFoundError(f"{self}: hidden by the clean-clone run")
        return _real_iterdir(self, *a, **k)

    def _glob(self, *a, **k):
        if _under_snapshot(self):
            return iter(())
        return _real_glob(self, *a, **k)

    def _open(file, *a, **k):
        if _under_snapshot(file):
            raise FileNotFoundError(f"{file}: hidden by the clean-clone run")
        return _real_open(file, *a, **k)

    def _os_exists(path):
        return False if _under_snapshot(path) else _real_os_exists(path)

    pathlib.Path.exists = _exists
    pathlib.Path.is_dir = _is_dir
    pathlib.Path.is_file = _is_file
    pathlib.Path.iterdir = _iterdir
    pathlib.Path.glob = _glob
    builtins.open = _open
    os.path.exists = _os_exists
'''

#: Artifacts the clean clone is expected to be able to regenerate, with the command that
#: does it. Anything absent from this list is either snapshot-bound or not generated.
_REGENERABLE: list[tuple[str, list[str]]] = [
    ("README.md", ["scripts/sync_readme_results.py"]),
    ("docs/KILL_GATE.md", ["scripts/sync_kill_gate.py"]),
    (
        "apps/web/public/data/provenance.json",
        ["scripts/build_console_data.py", "--skip-images"],
    ),
]


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    label: str,
    needs: str | None = None,
    count_pytest: bool = False,
) -> dict[str, Any]:
    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True, errors="replace"
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = [line for line in out.strip().splitlines() if line.strip()][-6:]
    print(
        f"  [{'ok ' if proc.returncode == 0 else 'FAIL'}] {label} "
        f"({time.time() - t0:.1f}s)",
        flush=True,
    )
    result: dict[str, Any] = {
        "step": label,
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "seconds": round(time.time() - t0, 1),
        "needs_outside_the_repo": needs,
        "output_tail": tail,
        "offline_violation": "OfflineViolation" in out,
    }
    if count_pytest:
        result["counts"] = _pytest_counts(out)
    return result


#: The marker expression the judged offline gate uses. Kept here as one string so this
#: script, the workflow and scripts/gate.py cannot drift into testing different suites.
#: `llm` is excluded because it needs a model runtime, and a reproduction whose result
#: depends on whether a local service happens to be up is not a reproduction.
#: cmd.exe spells a directory link differently from every other platform.
_IS_WINDOWS = platform.system() == "Windows"

_OFFLINE_MARKERS = "not network and not ocr and not llm"


def _pytest_counts(text: str) -> dict[str, Any]:
    """Pull passed/skipped/failed out of pytest's own summary line, and only that line.

    Two defects, both of which published a number that was not a measurement of this run.

    The first version read the last six lines of output and found nothing: the project's
    pytest options already carry ``-q``, a second one suppresses the summary entirely, and
    warnings occupy the tail, so the comparison of the suite with and without the snapshot
    was two empty objects under a paragraph explaining how to read them.

    The fix for that searched the whole output for ``(\\d+) passed`` and took the first
    match, which is worse, because a failing test prints its own assertion output first. A
    run where ``tests/test_for_judges.py`` failed had the committed judges' page in its
    traceback, that page carries the sentence "1116 passed, 30 skipped, from the clean
    clone", and both columns of the transcript were published as 1116 and 30: numbers copied
    out of the previous run's prose by way of a failure message, matching neither of the two
    suites that had just run. The counts now come from the summary line and nowhere else.
    """
    summary = None
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        # pytest's summary line always carries a duration and at least one outcome count.
        if re.search(r"\bin \d+\.\d+s", stripped) and re.search(
            r"\b\d+ (?:passed|failed|error|errors)\b", stripped
        ):
            summary = stripped
            break
    if summary is None:
        return {
            "unparsed": True,
            "why": (
                "no pytest summary line in the output. The counts are not guessed from "
                "elsewhere in the log, because a failing test can print numbers that look "
                "like a summary."
            ),
        }

    got: dict[str, Any] = {"summary_line": summary}
    for key in ("passed", "skipped", "failed", "error", "xfailed", "deselected"):
        match = re.search(rf"(\d+) {key}", summary)
        if match:
            got[key] = int(match.group(1))
    if len(got) == 1:
        return {
            "unparsed": True,
            "summary_line": summary,
            "why": "a line that looked like a summary carried no outcome count",
        }
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Clean-clone reproduction with the network refused.")
    ap.add_argument("--clone-dir", type=Path, default=Path("D:/_cleanclone"))
    ap.add_argument(
        "--keep",
        action="store_true",
        help="Leave the clone on disk afterwards for inspection.",
    )
    ap.add_argument("--out", type=Path, default=_REPO / "artifacts" / "CLEAN_CLONE_TRANSCRIPT.json")
    args = ap.parse_args(argv)

    clone = args.clone_dir / "tracetriage"
    if args.clone_dir.exists():
        shutil.rmtree(args.clone_dir, ignore_errors=True)
    args.clone_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, Any]] = []
    prerequisites: list[dict[str, Any]] = []
    print("cloning", flush=True)

    # A local clone rather than a fetch from the remote: the point is a tree with nothing
    # in it but tracked files, and a fetch would need the network this run refuses.
    steps.append(
        _run(
            ["git", "clone", "--no-hardlinks", str(_REPO), str(clone)],
            cwd=args.clone_dir,
            env=dict(os.environ),
            label="git clone (local, --no-hardlinks)",
            needs="the source clone. A judge would fetch from GitHub, which needs the network.",
        )
    )
    if not (clone / "pyproject.toml").exists():
        print("clone failed; stopping", flush=True)
        args.out.write_text(
            json.dumps({"steps": steps, "fatal": "clone failed"}, indent=1),
            encoding="utf-8",
        )
        return 1

    # The offline guard, outside the clone so the tree stays exactly what git produced,
    # and on PYTHONPATH so every Python process below imports it at startup.
    guard_dir = args.clone_dir / "offline_guard"
    guard_dir.mkdir(parents=True, exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(guard_dir), str(clone)])
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env["HTTP_PROXY"] = "http://127.0.0.1:1"
    env["HTTPS_PROXY"] = "http://127.0.0.1:1"
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)

    # Build the environment inside the clone, from the warm uv cache, with the network off.
    #
    # The first version of this ran `uv pip install --offline -e .` with no --python, so uv
    # searched PATH, found a chocolatey shim pointing at a c:\python312 that does not exist,
    # and exited 2 in 0.3 seconds without reaching dependency resolution at all. The step was
    # labelled "dependency resolution, offline" and the transcript recorded it as the expected
    # cost of going offline, which converted a local PATH defect into an accepted limitation
    # and left every later step running on this machine's site-packages. Naming the
    # interpreter explicitly is the whole fix.
    uv = shutil.which("uv")
    source_py = str(_REPO / ".venv" / "Scripts" / "python.exe")
    uv_cache = _resolve_uv_cache(uv)
    clone_py = str(
        clone / ".venv" / ("Scripts" if _IS_WINDOWS else "bin") / (
            "python.exe" if _IS_WINDOWS else "python"
        )
    )
    offline_install = None
    if uv:
        steps.append(
            _run(
                [uv, "venv", "--python", source_py, str(clone / ".venv")],
                cwd=clone,
                env=env,
                label="uv venv (an interpreter inside the clone)",
                needs="the source interpreter, copied. uv venv does not reach the network.",
            )
        )
        offline_install = _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                clone_py,
                "--offline",
                "-e",
                ".[dev,onnx]",
            ],
            cwd=clone,
            env=env,
            label="uv pip install --offline -e .[dev,onnx] into the clone's environment",
            needs=(
                "a warm uv cache. --offline resolves from it and never reaches the index, so "
                "this measures whether the pinned set can be rebuilt without the network, "
                "not whether it can be resolved from scratch."
            ),
        )
        steps.append(offline_install)

    installed_in_the_clone = (
        offline_install is not None
        and offline_install["exit_code"] == 0
        and Path(clone_py).exists()
    )
    py = clone_py if installed_in_the_clone else source_py
    if installed_in_the_clone:
        prerequisites.append(
            {
                "prerequisite": "a warm uv cache",
                "why": (
                    "the environment was built inside the clone with --offline, so the "
                    "wheels came from the local cache rather than from an index. A judge "
                    "with no cache needs one network install before this run reproduces."
                ),
                "uv_cache": uv_cache,
                "interpreter": py,
                "python_version": platform.python_version(),
            }
        )
    else:
        prerequisites.append(
            {
                "prerequisite": "a prepared Python environment",
                "why": (
                    "the offline install into the clone did not succeed, so the source "
                    "clone's interpreter and site-packages were used against the clone's "
                    "source tree. That tests the code in isolation and does not test "
                    "dependency resolution, and it means the environment below is this "
                    "machine's rather than the clone's. The failing step's own output tail "
                    "carries the reason; read it rather than assuming the reason was the "
                    "network."
                ),
                "interpreter": py,
                "python_version": platform.python_version(),
                "install_exit_code": (
                    None if offline_install is None else offline_install["exit_code"]
                ),
                "uv_cache": uv_cache,
            }
        )

    # node_modules: linked rather than installed, because npm ci needs the registry.
    src_modules = _REPO / "apps" / "web" / "node_modules"
    dst_modules = clone / "apps" / "web" / "node_modules"
    lock = _REPO / "apps" / "web" / "package-lock.json"
    if src_modules.exists() and not dst_modules.exists():
        # A directory link, spelled the way the host platform spells it. This script is a
        # developer tool that runs where the 4 GB snapshot lives, which is Windows, but a
        # hardcoded cmd.exe here would fail with a confusing exit code somewhere else
        # rather than saying which platform it wanted.
        if _IS_WINDOWS:
            link_cmd = ["cmd", "/c", "mklink", "/J", str(dst_modules), str(src_modules)]
        else:
            link_cmd = ["ln", "-s", str(src_modules), str(dst_modules)]
        link = _run(
            link_cmd,
            cwd=clone,
            env=env,
            label="link apps/web/node_modules from the source clone",
            needs="apps/web/node_modules, 425 MB. npm ci needs the npm registry.",
        )
        steps.append(link)
        prerequisites.append(
            {
                "prerequisite": "apps/web/node_modules",
                "why": "npm ci needs the registry, which this run refuses.",
                "package_lock_sha256": _sha256(lock),
                "package_lock_bytes": lock.stat().st_size if lock.exists() else None,
            }
        )

    print("running the checks in the clone", flush=True)
    pytest_step = _run(
        [py, "-m", "pytest", "-m", _OFFLINE_MARKERS],
        cwd=clone,
        env=env,
        label="offline test suite, snapshot present",
        count_pytest=True,
    )
    steps.append(pytest_step)

    # The same suite with the 4 GB snapshot hidden, which is what a judge has. Without
    # this pass the presence of the directory on this machine would hide every test that
    # only passes because a cache is warm.
    hidden_env = dict(env)
    hidden_env["CLEAN_CLONE_HIDE_SNAPSHOT"] = "1"
    hidden = _run(
        [py, "-m", "pytest", "-m", _OFFLINE_MARKERS],
        cwd=clone,
        env=hidden_env,
        label="offline test suite, snapshot HIDDEN",
        needs=(
            "the interpreter named in prerequisites_not_in_the_repository. This is a judge's "
            "case for the snapshot and not necessarily for the environment, and the earlier "
            "wording claimed nothing at all was needed while the command it recorded beside "
            "it named an interpreter that may sit outside the clone."
        ),
        count_pytest=True,
    )
    steps.append(hidden)

    steps.append(
        _run(
            [py, "-m", "ruff", "check", "."],
            cwd=clone,
            env=env,
            label="lint (ruff check .)",
        )
    )
    steps.append(
        _run(
            [py, "scripts/sync_kill_gate.py", "--check"],
            cwd=clone,
            env=env,
            label="sync_kill_gate.py --check (generated document drift)",
        )
    )
    steps.append(
        _run(
            [py, "scripts/sync_readme_results.py", "--check"],
            cwd=clone,
            env=env,
            label="sync_readme_results.py --check (generated table drift)",
        )
    )
    steps.append(
        _run([py, "scripts/check_contrast.py"], cwd=clone, env=env, label="check_contrast.py")
    )

    # Regeneration, with digests either side. This is the part that catches an artifact
    # that only exists because it was built once.
    regen: list[dict[str, Any]] = []
    for rel, cmd in _REGENERABLE:
        target = clone / rel
        before = _sha256(target)
        step = _run([py, *cmd], cwd=clone, env=env, label=f"regenerate {rel}")
        steps.append(step)
        after = _sha256(target)
        regen.append(
            {
                "artifact": rel,
                "command": " ".join(cmd),
                "exit_code": step["exit_code"],
                "sha256_committed": before,
                "sha256_rebuilt": after,
                "identical": before == after,
            }
        )

    # The console, which is the thing a judge actually opens.
    npx = shutil.which("npx") or "npx"
    web = clone / "apps" / "web"
    if dst_modules.exists():
        steps.append(_run([npx, "tsc", "--noEmit"], cwd=web, env=env, label="npx tsc --noEmit"))
        steps.append(_run([npx, "vitest", "run"], cwd=web, env=env, label="npx vitest run"))
        build = _run([npx, "next", "build"], cwd=web, env=env, label="npx next build")
        steps.append(build)
        out_dir = web / "out"
        build_pages = len(list(out_dir.rglob("index.html"))) if out_dir.exists() else 0
    else:
        build_pages = 0

    # What the clean clone cannot do, by name rather than by failing obscurely.
    snapshot = Path("D:/tracetriage_data/snap-stage1")
    snapshot_bound = [
        {
            "artifact": "artifacts/GATE3_RECEIPT.json",
            "builder": "scripts/run_gate3.py",
            "needs": "the 4 GB snapshot: waterfall PNGs and the page cache",
        },
        {
            "artifact": "artifacts/HERO_NULLS.json",
            "builder": "scripts/export_hero_nulls.py",
            "needs": "the snapshot, via run_gate3's receipt inputs",
        },
        {
            "artifact": "artifacts/corridor_features.json",
            "builder": "scripts/extract_corridor_features.py",
            "needs": "every waterfall PNG in the snapshot",
        },
        {
            "artifact": "artifacts/SPLIT_MANIFEST.json",
            "builder": "pipeline.tracetriage.splits",
            "needs": "the page cache at D:/tracetriage_data/snap-stage1/pages",
        },
        {
            "artifact": "artifacts/SECOND_TRACE_SURVEY.json",
            "builder": "scripts/measure_second_trace.py",
            "needs": "every waterfall PNG in the snapshot",
        },
        {
            "artifact": "apps/web/public/data/cards.json",
            "builder": "scripts/build_console_data.py",
            "needs": "the waterfall PNGs, which is why --skip-images exists",
        },
    ]

    payload = {
        "schema": "CLEAN_CLONE_TRANSCRIPT",
        "schema_version": "0.1.0",
        "run_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_repo": str(_REPO),
        "clone": str(clone),
        "source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO), capture_output=True, text=True
        ).stdout.strip(),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "network": {
            "python_steps": (
                "refused by sitecustomize.py on PYTHONPATH: connect, connect_ex and "
                "getaddrinfo raise on any non-loopback address"
            ),
            "node_steps": (
                "weaker: NEXT_TELEMETRY_DISABLED=1 and a dead proxy. Node does not import "
                "sitecustomize, so this is a deterrent rather than a block, and it is "
                "recorded as such."
            ),
            "loopback": (
                "allowed, because torch and multiprocessing use it locally. Any address in "
                "127.0.0.0/8 and ::1 pass; a hostname passes only if it is literally "
                "localhost, because the guard has replaced the resolver it would need to "
                "check any other name. pipeline/tracetriage/granite.py resolves names and "
                "requires every address to be loopback, which it can do because it runs "
                "with a network."
            ),
            "binds_inside_python_only": (
                "The patch replaces socket methods in the Python process it is imported "
                "into, so it reaches every Python child through PYTHONPATH and constrains "
                "nothing else. A step that shells out to curl, git or node is outside it. "
                "The Node steps are the disclosed instance rather than the only possible one."
            ),
            "how_violations_are_detected": (
                "By scanning each step's output for the guard's exception name, so the list "
                "records a refusal that was printed. A step that caught the exception and "
                "degraded quietly records false, which makes an empty list a statement about "
                "traffic rather than about intent."
            ),
            "violations": [s["step"] for s in steps if s.get("offline_violation")],
        },
        "prerequisites_not_in_the_repository": prerequisites,
        "snapshot_present_on_this_host": snapshot.exists(),
        "cannot_regenerate_without_the_snapshot": snapshot_bound,
        "regenerated": regen,
        "console_build_index_html_files": build_pages,
        "steps": steps,
        "suite_with_and_without_the_snapshot": {
            "with": pytest_step.get("counts"),
            "without": hidden.get("counts"),
            "reading": (
                "Tests that skip or fail only in the second column are tests a judge "
                "cannot run. A skip is honest and a pass that depended on the cache is "
                "not, which is why both columns are published."
            ),
        },
        "summary": {
            "steps_run": len(steps),
            "steps_failed": [s["step"] for s in steps if s["exit_code"] != 0],
            "regenerated_identical": [r["artifact"] for r in regen if r["identical"]],
            "regenerated_differed": [r["artifact"] for r in regen if not r["identical"]],
        },
    }

    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {args.out}")
    print(json.dumps(payload["summary"], indent=1))
    print(json.dumps(payload["network"]["violations"], indent=1))

    if not args.keep:
        # The junction has to go before the tree, or rmtree walks into node_modules.
        if dst_modules.exists():
            if _IS_WINDOWS:
                subprocess.run(
                    ["cmd", "/c", "rmdir", str(dst_modules)], capture_output=True
                )
            else:
                dst_modules.unlink(missing_ok=True)
        shutil.rmtree(args.clone_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
