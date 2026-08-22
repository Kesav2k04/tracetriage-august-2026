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
import os
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

#: What `scripts/check_artifact_freshness.py` prints when the snapshot it rebuilds from is
#: not configured in this environment. Matched on the printed line rather than on an exit
#: code, because that outcome is not a failure and must not exit non-zero. The constant is
#: `SKIP_PREFIX` at the other end and `tests/test_freshness_outcomes.py` asserts the two
#: are still the same string, so a rename cannot quietly turn every skip back into a FAIL.
_FRESHNESS_SKIP = "[SKIP]"


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
    """Print one row, and never fail while doing it.

    `run` decodes subprocess output as UTF-8, and on Windows this script's own stdout is
    cp1252 whenever it is redirected to a file. A failing row whose detail carried a
    character cp1252 cannot encode therefore raised UnicodeEncodeError *inside the print*,
    so the gate died with a traceback at the row it was trying to report and said nothing
    about the other rows. It happened on the first presentation-test failure, because
    vitest draws its summary with box characters: the one row that had something to say was
    the one that could not say it.

    Encoding-safe now, and the substitution is visible rather than silent.
    """
    line = f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else "")
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    return ok


def main() -> int:
    print("standing gates\n")
    results = []

    rc, out = run([str(PY), "-m", "pytest", "-m", "not network and not ocr and not llm", "-q"])
    tail = out.splitlines()[-1] if out else ""
    results.append(check("offline test suite", rc == 0, tail[:70]))

    rc, out = run([str(PY), "-m", "ruff", "check", "."])
    # A non-zero exit with no output is not a lint finding: it is ruff failing to run,
    # or being killed. Indexing the last line of nothing made the whole gate a
    # traceback, so a run that could not be measured reported as no run at all.
    lint_tail = out.splitlines()[-1][:70] if out.strip() else f"ruff did not report (exit {rc})"
    results.append(check("lint", rc == 0, "" if rc == 0 else lint_tail))

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

    # The README results table is generated from the receipts by
    # scripts/sync_readme_results.py, and until D3 that script was referenced by
    # nothing: not here, not in CI, not by a test. The table stayed correct only while
    # someone remembered to run it, and the drift test beside it compared metric names
    # rather than values, so an edited number passed the whole suite.
    rc, out = run([str(PY), str(REPO / "scripts" / "sync_readme_results.py"), "--check"])
    results.append(
        check(
            "README results match the receipts",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The judges' page is generated from the receipts for the same reason as the README
    # table, and it is the file most likely to be read and least likely to be re-derived.
    rc, out = run([str(PY), str(REPO / "scripts" / "sync_for_judges.py"), "--check"])
    results.append(
        check(
            "judges' page matches the receipts",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The reference page maps every artifact to what writes it and what checks it, and it
    # is generated from the tree rather than maintained, so a script added without a
    # docstring or a receipt nothing rebuilds shows up here instead of in a judge's diff.
    rc, out = run([str(PY), str(REPO / "scripts" / "sync_docs.py"), "--check"])
    results.append(
        check(
            "reference page matches the tree",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The throughput receipt is the only place the repository answers whether this would
    # keep up with the network, and every figure in it is derived from other artifacts.
    # It goes stale the moment the snapshot or either timed stage is re-run.
    rc, out = run([str(PY), str(REPO / "scripts" / "measure_throughput.py"), "--check"])
    results.append(
        check(
            "throughput receipt matches its inputs",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The architecture diagram names a module and a receipt per stage, and both are
    # checked against the tree before it is drawn. An ASCII block could describe a
    # pipeline that no longer existed; this cannot, but only if something re-runs it.
    rc, out = run(
        [str(PY), str(REPO / "scripts" / "build_architecture_diagram.py"), "--check"]
    )
    results.append(
        check(
            "architecture diagram matches the pipeline",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The shot list quotes measured numbers into a public, unversioned video. It is the one
    # document here where a stale figure cannot be corrected after submission.
    rc, out = run([str(PY), str(REPO / "scripts" / "sync_demo.py"), "--check"])
    results.append(
        check(
            "demo script matches the receipts",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The circularity bound is computed from QUEUE_RECEIPT.json alone, so it goes stale the
    # moment the queue is re-run. It is the one analysis in the repository whose whole value
    # is that it describes the same measurement the gate reports, and a stale copy would
    # describe a different one under the same heading.
    rc, out = run([str(PY), str(REPO / "scripts" / "run_circularity_check.py"), "--check"])
    results.append(
        check(
            "circularity bound matches the queue receipt",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # Four of the six gates are unmet, and the account of why is generated from the same
    # receipts that decided them. It goes stale for the same reason the circularity bound
    # does, and it fails harder: a closure condition computed against last week's interval
    # is a number telling a reader what would fix a gate that has since moved. The script
    # also refuses to write at all if an unmet gate comes out with no binding constraint,
    # so this step is what keeps "every gate has a reason" a checked property.
    rc, out = run([str(PY), str(REPO / "scripts" / "run_gate_power.py"), "--check"])
    results.append(
        check(
            "every unmet gate has a current, named reason",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The link preview card carries two verdicts and a permutation count, drawn from the
    # receipts. It is the one published surface nobody looks at while working, so a stale
    # one would sit in every shared link showing a number the console no longer holds.
    rc, out = run([str(PY), str(REPO / "scripts" / "build_og_image.py"), "--check"])
    results.append(
        check(
            "link preview card matches the receipts",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The LangChain adapter's receipt. Its freshness was guarded by
    # tests/test_langchain_tools.py and by nothing here, which made it the one judge-facing
    # generator outside this gate's own --check sweep. A test is a real guard; being the
    # only exception to a sweep is how an exception outlives its reason.
    rc, out = run([str(PY), str(REPO / "scripts" / "run_langchain_check.py"), "--check"])
    results.append(
        check(
            "langchain receipt matches the adapter",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The watsonx receipt. Its whole point is that it records one of three outcomes with a
    # date, so --check has to tolerate the outcome differing between a machine with
    # credentials and one without, and it does: it reports which one is committed rather
    # than treating either as wrong.
    rc, out = run([str(PY), str(REPO / "scripts" / "run_watsonx_check.py"), "--check"])
    results.append(
        check(
            "watsonx receipt matches this tree",
            rc == 0,
            "" if rc == 0 else out.strip().splitlines()[0][:70],
        )
    )

    # The LangFlow flows, and this one is a third outcome rather than a pass or a fail.
    #
    # LangFlow is deliberately not a dependency: it resolves several hundred packages and
    # pins against versions the measurement path is fixed to. So on a machine without the
    # separate environment there is no question to ask, and reporting that as a FAIL would
    # manufacture a regression on every clean clone. The runner exits with a message naming
    # the two commands that create the environment, and that string is what distinguishes
    # "cannot be measured here" from "measured and wrong".
    rc, out = run([str(PY), str(REPO / "scripts" / "run_langflow_check.py"), "--check"])
    if rc != 0 and "No interpreter with LangFlow was found" in out:
        print(
            "  [ -- ] langflow flows match their receipt  "
            "omitted: .venv-langflow is not present in this checkout."
        )
    else:
        results.append(
            check(
                "langflow flows match their receipt",
                rc == 0,
                "" if rc == 0 else out.strip().splitlines()[0][:70],
            )
        )

    # Every digest a receipt records for a tracked file, against that file.
    #
    # Added after QUEUE_RECEIPT.json and FUSION_RECEIPT.json were both found publishing a
    # split_manifest_sha256 that no committed file produces: the value was the manifest with
    # CRLF endings, taken on a Windows tree before git normalised the file, and nothing
    # re-derived it. Two receipts, one console page and a claim in the film carried it, and
    # all 26 rows here were green. Nothing else in this repository compares a recorded hash
    # to the bytes git actually publishes.
    rc, out = run([str(PY), str(REPO / "scripts" / "check_receipt_digests.py")])
    lines = [line for line in out.strip().splitlines() if line.strip()]
    results.append(
        check(
            "receipt digests match the files they name",
            rc == 0,
            (lines[-1] if lines else "") if rc == 0 else next(
                (line.strip()[7:] for line in lines if line.strip().startswith("[FAIL]")),
                "",
            )[:70],
        )
    )

    # The presentation film, and the same third outcome for the same reason.
    #
    # 453 checks live in presentation/test/claims.test.ts and none of them ran here until
    # now: they were reachable only by remembering to cd into the package. That is how a
    # figure goes stale inside an mp4 that no diff can read. Two commands, because they
    # fail differently. `npm test` walks every key path the film prints and re-resolves it
    # against the receipt; `npm run report -- --check` fails if REPORT.md's claim table is
    # no longer what src/data.ts produces.
    #
    # Omitted rather than failed when the package has no node_modules, because a clean
    # clone has not run `npm install` there and a FAIL row would be a regression nobody
    # caused. The tally counts checks that were performed.
    presentation = REPO / "presentation"
    if not (presentation / "node_modules").is_dir():
        print(
            "  [ -- ] presentation film matches its receipts  "
            "omitted: presentation/node_modules is not present. Run npm install there."
        )
    else:
        for label, argv in (
            ("presentation film matches its receipts", [NPM, "test", "--silent"]),
            (
                "film report and receipt match presentation/src",
                [NPM, "run", "report", "--silent", "--", "--check"],
            ),
        ):
            rc, out = run(argv, cwd=presentation)
            lines = [line for line in out.strip().splitlines() if line.strip()]
            results.append(
                check(label, rc == 0, "" if rc == 0 else (lines[-1] if lines else "")[:70])
            )

    # Artifact freshness. Every other check here can pass while a committed artifact
    # disagrees with the code that produced it, which is exactly what happened in D0:
    # LEAKAGE_AUDIT.json kept a PASS the builder could no longer emit, and a test was
    # green because its fixture read that file.
    #
    # Three outcomes, and the third one is neither. That check rebuilds every artifact from
    # the 20 GB snapshot, which is not in every checkout, and it used to report a missing
    # snapshot as "the builder itself does not run": a FAIL row for a question nobody could
    # ask here, on a tree where nothing was stale. It now exits 0 with a [SKIP] line, and
    # the row is omitted rather than counted green, so the tally at the bottom stays the
    # number of checks that were actually performed.
    rc, out = run([str(PY), str(REPO / "scripts" / "check_artifact_freshness.py")])
    not_configured = next(
        (line for line in out.splitlines() if line.startswith(_FRESHNESS_SKIP)), None
    )
    if not_configured:
        reason = not_configured[len(_FRESHNESS_SKIP) :].strip()
        print(f"  [ -- ] artifacts match their builders  omitted: {reason[:110]}")
    else:
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

    # The sign-off receipt. Its content is asserted by tests/test_signoff.py, which skip when
    # the file is absent, so presence is checked here instead: a deleted receipt has to fail
    # something rather than quieting six tests. Freshness is not checked here on purpose. The
    # receipt is written at one commit and committed at the next, so requiring it to name HEAD
    # would fail on every commit after the one that published it. Re-running
    # scripts/signoff.py at the release commit is what makes it current.
    # The sign-off receipt. Its content is asserted by tests/test_signoff.py, which skip when
    # the file is absent, so presence is checked here instead: a deleted receipt has to fail
    # something rather than quieting six tests. Freshness is deliberately not checked. The
    # receipt is written at one commit and committed at the next, so requiring it to name HEAD
    # would fail on every commit after the one that published it. Re-running
    # scripts/signoff.py at the release commit is what makes it current.
    _signoff = REPO / "artifacts" / "SIGNOFF_RECEIPT.json"
    if os.environ.get("TRACETRIAGE_SIGNOFF_IN_PROGRESS"):
        # scripts/signoff.py runs this gate and writes that receipt afterwards, so asking
        # whether it exists mid-run asks the wrong question and would make the first sign-off
        # in a repository impossible. The row is omitted rather than counted green, and the
        # omission is printed, because a check quietly treated as passing is the defect this
        # file exists to prevent.
        print(
            "  [ -- ] sign-off receipt present and signed  omitted: this gate is running "
            "inside scripts/signoff.py, which writes that receipt after it"
        )
    else:
        if _signoff.exists():
            _sd = json.loads(_signoff.read_text(encoding="utf-8"))
            _sok = _sd.get("verdict") == "SIGNED" and _sd.get("counts", {}).get("FAILED") == 0
            _sdetail = f"{_sd.get('verdict')} at {str(_sd.get('measured_at_commit'))[:8]}"
        else:
            _sok = False
            _sdetail = "artifacts/SIGNOFF_RECEIPT.json is absent. Run scripts/signoff.py."
        results.append(check("sign-off receipt present and signed", _sok, _sdetail))

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
