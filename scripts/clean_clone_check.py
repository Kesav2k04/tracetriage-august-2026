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

* The Python environment. ``uv pip install`` needs an index or a warm uv cache, and this
  script tries the offline install first and records whether it worked. When it does not,
  the source clone's interpreter is used against the clone's source tree, which tests the
  code in isolation and not the dependency resolution.
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

_ALLOWED = {"127.0.0.1", "::1", "localhost"}
_SNAPSHOT_ROOT = "d:/tracetriage_data"  # compared after backslashes are normalised


class OfflineViolation(RuntimeError):
    pass


def _host_of(address):
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _connect(self, address, *a, **k):
    host = _host_of(address)
    if host not in _ALLOWED:
        raise OfflineViolation(
            f"outbound connect to {host!r} refused: clean-clone run is offline"
        )
    return _real_connect(self, address, *a, **k)


def _connect_ex(self, address, *a, **k):
    host = _host_of(address)
    if host not in _ALLOWED:
        raise OfflineViolation(
            f"outbound connect_ex to {host!r} refused: clean-clone run is offline"
        )
    return _real_connect_ex(self, address, *a, **k)


def _getaddrinfo(host, *a, **k):
    if str(host) not in _ALLOWED:
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
    """Pull passed/skipped/failed out of pytest's summary line.

    This read the last six lines of output and published whatever it found, which was
    nothing: the project's pytest options already carry ``-q``, a second one suppresses the
    summary line entirely, and warnings occupy the tail. The comparison of the suite with
    and without the snapshot was therefore two empty objects under a paragraph explaining
    how to read them. Searching the whole output and refusing to return an empty result is
    the fix; an unparsed run now says so instead of looking like a run with no tests.
    """
    got: dict[str, Any] = {}
    for key in ("passed", "skipped", "failed", "error", "xfailed", "deselected"):
        match = re.search(rf"(\d+) {key}", text)
        if match:
            got[key] = int(match.group(1))
    if not got:
        return {"unparsed": True, "why": "no pytest summary line in the output"}
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

    # Try the honest thing first: resolve dependencies with the network off.
    uv = shutil.which("uv")
    offline_install = None
    if uv:
        offline_install = _run(
            [uv, "pip", "install", "--offline", "-e", "."],
            cwd=clone,
            env=env,
            label="uv pip install --offline -e . (dependency resolution, offline)",
        )
        steps.append(offline_install)

    py = str(_REPO / ".venv" / "Scripts" / "python.exe")
    if offline_install is None or offline_install["exit_code"] != 0:
        prerequisites.append(
            {
                "prerequisite": "a prepared Python environment",
                "why": (
                    "uv pip install --offline could not resolve the dependency set in the "
                    "clone, so the source clone's interpreter and site-packages were used "
                    "against the clone's source tree. This tests the code in isolation and "
                    "does not test dependency resolution."
                ),
                "interpreter": py,
                "python_version": platform.python_version(),
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
        needs="nothing: this is the judge's case",
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
            "loopback": "allowed, because torch and multiprocessing use it locally",
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
