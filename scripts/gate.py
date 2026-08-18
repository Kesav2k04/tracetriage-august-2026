"""Mechanical verification of a Bob unit. Run this instead of trusting a self-report.

    .venv/Scripts/python.exe scripts/gate.py

Checks the things that apply to every unit, so a unit is never accepted on
"Bob said it passed". Unit-specific acceptance criteria are in BOB_START_HERE.md
section 7 and still need reading; this covers the standing gates.

Three checks were added on 2026-08-19, all of them closing a way for this script to
report green over a real defect. The console had no mechanical cover at all: no type
check, no build and no test runner, while the majority of recent commits touched it.
And nothing rebuilt an artifact and diffed it, so a committed receipt could contradict
the code that wrote it with every gate still passing. A missing apps/web/node_modules
is reported as a failure rather than skipped, because a skipped check that reads as a
pass is the same defect one level up.

Exit code 0 = all standing gates pass. Non-zero = something is wrong.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
WEB = REPO / "apps" / "web"
# npm on Windows is a batch script, so it has to be named with its extension for a
# non-shell subprocess. shutil.which finds whichever form this machine has.
NPM = shutil.which("npm") or "npm"


def run(cmd: list[str], cwd: Path = REPO) -> tuple[int, str]:
    # text=True alone decodes with the Windows ANSI codepage (cp1252 here), which
    # raises UnicodeDecodeError on any byte it does not map. That made the gate
    # crash instead of reporting, and it crashed precisely when it was most
    # needed: a non-ASCII character in a source file is only echoed by pytest
    # when a test in that file FAILS. Decode as UTF-8 and never let an
    # undecodable byte take the gate down.
    p = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def main() -> int:
    print("standing gates\n")
    results = []

    rc, out = run([str(PY), "-m", "pytest", "-m", "not network and not ocr", "-q"])
    tail = out.splitlines()[-1] if out else ""
    results.append(check("offline test suite", rc == 0, tail[:70]))

    rc, out = run([str(PY), "-m", "ruff", "check", "."])
    results.append(check("lint", rc == 0, "" if rc == 0 else out.splitlines()[-1][:70]))

    # The console had no mechanical gate at all: no type check, no build, no tests,
    # while five of the last five commits touched it. It was green, and nothing here
    # would have noticed if it stopped being green. The evaluation page does real work
    # at module scope, so a break there fails the export rather than degrading it.
    if (WEB / "node_modules").is_dir():
        rc, out = run([NPM, "run", "typecheck"], cwd=WEB)
        results.append(
            check(
                "console typecheck",
                rc == 0,
                "" if rc == 0 else out.splitlines()[-1][:70],
            )
        )

        rc, out = run([NPM, "run", "build"], cwd=WEB)
        results.append(
            check(
                "console build",
                rc == 0,
                "" if rc == 0 else out.splitlines()[-1][:70],
            )
        )

        # Vitest covers the pure functions in apps/web/lib. It is a separate check
        # from the build because a type error and a wrong projection are different
        # failures and should not share a line.
        rc, out = run([NPM, "run", "test"], cwd=WEB)
        results.append(
            check(
                "console tests",
                rc == 0,
                "" if rc == 0 else out.splitlines()[-1][:70],
            )
        )
    else:
        # Report it rather than skip it silently. A missing node_modules is a real
        # state of this checkout, and treating it as a pass is how a gate comes to
        # mean nothing.
        results.append(
            check(
                "console typecheck, build and tests",
                False,
                "apps/web/node_modules missing; run npm ci in apps/web",
            )
        )

    # Artifact freshness. Every other check here can pass while a committed artifact
    # disagrees with the code that produced it, which is exactly what happened in D0:
    # LEAKAGE_AUDIT.json kept a PASS the builder could no longer emit, and a test was
    # green because its fixture read that file.
    rc, out = run([str(PY), str(REPO / "scripts" / "check_artifact_freshness.py")])
    results.append(
        check(
            "artifacts match their builders",
            rc == 0,
            "" if rc == 0 else out.splitlines()[-1][:70],
        )
    )

    bad = []
    for f in sorted((REPO / "contracts").glob("*.schema.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            bad.append(f"{f.name}: unparseable ({e})")
            continue
        if str(d.get("status", "")).upper().startswith("DRAFT"):
            bad.append(f"{f.name}: still DRAFT")
    results.append(check("contracts ratified", not bad, "; ".join(bad)[:90] or "all ratified"))

    rc, out = run(["git", "status", "--porcelain"])
    n_dirty = len(out.splitlines())
    results.append(check("working tree committed", out == "", f"{n_dirty} uncommitted"))

    _queue = REPO / "artifacts" / "QUEUE_RECEIPT.json"
    if _queue.exists():
        try:
            _qr = json.loads(_queue.read_text(encoding="utf-8"))
            _g6_verdict = _qr.get("gate6", {}).get("verdict", "MISSING")
            _g6_ok = _g6_verdict in ("PASSED", "NOT_ESTABLISHED", "FAILED", "NOT_MEASURABLE")
        except Exception as _e:
            _g6_verdict = f"parse error: {_e}"
            _g6_ok = False
    else:
        _g6_verdict = "QUEUE_RECEIPT.json not found"
        _g6_ok = False
    results.append(check(
        "gate 6 receipt present and verdict recorded",
        _g6_ok,
        _g6_verdict[:70],
    ))

    rc, out = run([
        "git", "grep", "-lIE",
        r"ghp_[0-9A-Za-z]{36,}|github_pat_[0-9A-Za-z_]{36,}|-----BEGIN [A-Z ]*PRIVATE KEY",
    ])
    # git grep exits 1 when it finds nothing, which is the good case here
    results.append(check("no secrets tracked", out == "", out[:70]))

    log = (REPO / "docs" / "BOB_BUILD_LOG.md").read_text(encoding="utf-8")
    logged = "No Bob tasks have run yet" not in log
    results.append(check("build log has an entry", logged, "" if logged else "log still empty"))

    rc, out = run(["git", "log", "-1", "--format=%an <%ae>%n%b"])
    author_ok = out.startswith("Kesav2k04 <kesavk659@gmail.com>")
    trailer_ok = "Co-Authored-By" not in out and "Generated with" not in out
    results.append(
        check("commit identity clean", author_ok and trailer_ok, out.splitlines()[0][:60])
    )

    passed = sum(results)
    print(f"\n{passed}/{len(results)} standing gates pass")
    if passed < len(results):
        print("\nDo not start the next unit until these are green.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
