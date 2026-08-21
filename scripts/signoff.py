"""Run every acceptance check in the repository at one commit and publish the result.

The last unit of the wave asks a narrow question: is the commit a judge will read actually
green, measured at that commit rather than remembered from three commits ago. The standing
gate answers most of it and it runs one check per line with no record left behind, so an
answer given in a terminal a week before submission is not evidence of anything.

This runs the standing gate, the acceptance checks the gate does not cover, and the release
audit, and writes `artifacts/SIGNOFF_RECEIPT.json` naming each check, the command that ran
it, its exit code and a line of its output. Three things it does deliberately:

**Three outcomes, not two.** A check that could not run here is `NOT_CHECKED` with a stated
reason. Folding it into `FAILED` manufactures a regression and folding it into `PASSED` is a
lie; the live-console check is the one that needs this, because it is the only check that
needs the network. The verdict counts them separately and refuses to sign while any check has
failed.

**The audit is re-run, not read.** `scripts/audit_release.py` writes three receipts that
carry the strongest claims in the repository, and at the start of this unit they had last been
measured fifteen files earlier. A sign-off that reads a stale receipt is worth less than no
sign-off.

**The receipt cannot name the commit it lands in.** Committing it moves HEAD past what it
measured, which is inherent, so it records `measured_at_commit` and says so in its own text
rather than implying it measured itself. `tests/test_signoff.py` asserts the recorded commit
is HEAD or its immediate parent, which is the strongest true statement available.

Usage::

    .venv/Scripts/python.exe scripts/signoff.py
    .venv/Scripts/python.exe scripts/signoff.py --check-live   (adds the deployed console)
    .venv/Scripts/python.exe scripts/signoff.py --fast         (skips the slowest three)

Exit 0 means signed. Exit 1 means at least one check failed and the receipt says which.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PY = REPO / ".venv" / "Scripts" / "python.exe"
WEB = REPO / "apps" / "web"
NPM = shutil.which("npm") or "npm"
RECEIPT = REPO / "artifacts" / "SIGNOFF_RECEIPT.json"

SCHEMA_VERSION = "0.1.0"

#: The deployed console. Checked only under --check-live, because every other check here runs
#: with the network down and mixing the two would make one failure look like the other.
LIVE_URL = "https://tracetriage.vercel.app"

#: The receipts this run writes. Everything else being dirty is a failure, and the list is
#: explicit so a new receipt has to be added here on purpose rather than covered by a glob.
_WRITTEN_BY_THIS_RUN = (
    "SIGNOFF_RECEIPT.json",
    "SECRET_SCAN.json",
    "ATTRIBUTION_AUDIT.json",
    "REPO_WEIGHT.json",
)

PASSED = "PASSED"
FAILED = "FAILED"
NOT_CHECKED = "NOT_CHECKED"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, errors="replace"
    ).stdout.strip()


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, float]:
    started = time.monotonic()
    # The standing gate checks that a signed receipt exists. This run is what writes it, so
    # the gate omits that one row when it sees this flag and says so in its output. Without
    # it the first sign-off in a repository could never be produced: the gate would fail on
    # the absence of the file the run is about to create.
    env = dict(os.environ, TRACETRIAGE_SIGNOFF_IN_PROGRESS="1")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
    )
    return proc.returncode, (proc.stdout + proc.stderr), time.monotonic() - started


def _last_useful_line(out: str) -> str:
    for line in reversed(out.splitlines()):
        if line.strip():
            return line.strip()[:160]
    return ""


class Sheet:
    """The checks, in the order they ran, with what each one produced."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(
        self,
        name: str,
        command: list[str] | None,
        status: str,
        detail: str,
        seconds: float | None = None,
        why_not_checked: str | None = None,
    ) -> None:
        assert status in (PASSED, FAILED, NOT_CHECKED)
        if status == NOT_CHECKED and not why_not_checked:
            raise ValueError(
                f"{name} was recorded NOT_CHECKED with no reason. A check that could not run "
                "has to say why, or it reads as one that was skipped for convenience."
            )
        self.rows.append(
            {
                "check": name,
                "command": " ".join(command) if command else None,
                "status": status,
                "detail": detail,
                "seconds": round(seconds, 1) if seconds is not None else None,
                "why_not_checked": why_not_checked,
            }
        )
        mark = {PASSED: "ok  ", FAILED: "FAIL", NOT_CHECKED: "----"}[status]
        print(f"  [{mark}] {name}" + (f"  {detail}" if detail else ""))

    def run(self, name: str, cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
        rc, out, secs = _run(cmd, cwd)
        self.record(
            name,
            cmd,
            PASSED if rc == 0 else FAILED,
            _last_useful_line(out),
            secs,
        )
        return rc, out

    def counts(self) -> dict[str, int]:
        return {
            status: sum(1 for r in self.rows if r["status"] == status)
            for status in (PASSED, FAILED, NOT_CHECKED)
        }


def _console_pages() -> int:
    out = WEB / "out"
    return len(list(out.rglob("index.html"))) if out.is_dir() else 0


def _check_live(sheet: Sheet, enabled: bool) -> None:
    if not enabled:
        sheet.record(
            "deployed console responds",
            None,
            NOT_CHECKED,
            "",
            why_not_checked=(
                "needs the network, and every other check in this run is offline. Re-run "
                "with --check-live from a networked machine before submitting."
            ),
        )
        return
    started = time.monotonic()
    try:
        with urllib.request.urlopen(LIVE_URL, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            code = response.status
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        sheet.record(
            "deployed console responds",
            None,
            FAILED,
            f"{LIVE_URL} did not answer: {type(exc).__name__}",
            time.monotonic() - started,
        )
        return
    ok = code == 200 and "TraceTriage" in body
    sheet.record(
        "deployed console responds",
        None,
        PASSED if ok else FAILED,
        f"HTTP {code}, {len(body):,} bytes from {LIVE_URL}",
        time.monotonic() - started,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Final acceptance, on the release commit.")
    parser.add_argument(
        "--check-live",
        action="store_true",
        help="also request the deployed console. Needs the network.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help=(
            "skip the standing gate, the console build and the history half of the secret "
            "scan. For iterating on this script; never for a sign-off."
        ),
    )
    args = parser.parse_args(argv)

    commit = _git("rev-parse", "HEAD")
    print(f"final acceptance at {commit[:8]}\n")
    sheet = Sheet()

    # 1. The standing gate, whole. It is the check that already covers most of the list, and
    #    running it here rather than trusting a remembered run is the point of the unit.
    if args.fast:
        sheet.record(
            "standing gates",
            [str(PY), "scripts/gate.py"],
            NOT_CHECKED,
            "",
            why_not_checked="--fast was passed. A sign-off run must not use it.",
        )
    else:
        sheet.run("standing gates", [str(PY), str(REPO / "scripts" / "gate.py")])

    # 2. The acceptance checks named in the unit that the standing gate does not run.
    sheet.run("contrast pairs", [str(PY), str(REPO / "scripts" / "check_contrast.py"), "-v"])
    sheet.run(
        "kill gate document matches its receipts",
        [str(PY), str(REPO / "scripts" / "sync_kill_gate.py"), "--check"],
    )

    # 3. The console, measured rather than assumed. `next build` is the slow one, so its
    #    page count is read off the emitted tree rather than parsed out of the log.
    if (WEB / "node_modules").is_dir():
        sheet.run("console typecheck", [NPM, "run", "typecheck"], cwd=WEB)
        sheet.run("console tests", [NPM, "run", "test"], cwd=WEB)
        if args.fast:
            sheet.record(
                "console build",
                [NPM, "run", "build"],
                NOT_CHECKED,
                "",
                why_not_checked="--fast was passed.",
            )
        else:
            rc, out, build_seconds = _run([NPM, "run", "build"], cwd=WEB)
            pages = _console_pages()
            sheet.record(
                "console build",
                [NPM, "run", "build"],
                PASSED if rc == 0 and pages > 0 else FAILED,
                f"{pages} index.html files emitted to apps/web/out",
                build_seconds,
            )
    else:
        for name in ("console typecheck", "console tests", "console build"):
            sheet.record(
                name,
                None,
                NOT_CHECKED,
                "",
                why_not_checked="apps/web/node_modules is absent, so no console step can run",
            )

    # 4. The release audit, re-run here rather than read. Its three receipts had last been
    #    measured fifteen files before this unit opened, which is the E6a finding recurring.
    audit_cmd = [str(PY), str(REPO / "scripts" / "audit_release.py")]
    if args.fast:
        audit_cmd.append("--skip-history")
    rc, out, audit_seconds = _run(audit_cmd)
    audits = {}
    for name in ("SECRET_SCAN", "ATTRIBUTION_AUDIT", "REPO_WEIGHT"):
        path = REPO / "artifacts" / f"{name}.json"
        audits[name] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    clean = (
        rc == 0
        and audits["SECRET_SCAN"] is not None
        and audits["SECRET_SCAN"]["clean"] is True
        and audits["ATTRIBUTION_AUDIT"]["clean"] is True
    )
    sheet.record(
        "release audit re-run at this commit",
        audit_cmd,
        PASSED if clean else FAILED,
        (
            f"{audits['SECRET_SCAN']['n_findings']} secret findings, "
            f"{len(audits['ATTRIBUTION_AUDIT']['incomplete_files'])} files short of their "
            f"attribution, {audits['REPO_WEIGHT']['tracked_megabytes']} MB tracked"
            if audits["SECRET_SCAN"]
            else "the audit wrote no receipt"
        ),
        audit_seconds,
    )

    # 5. The commit itself. A green tree at a commit nobody can identify is not a sign-off.
    author = _git("log", "-1", "--format=%an <%ae>")
    body = _git("log", "-1", "--format=%b")
    identity_ok = author == "Kesav2k04 <kesavk659@gmail.com>" and "Co-Authored-By" not in body
    sheet.record(
        "commit identity", ["git", "log", "-1"], PASSED if identity_ok else FAILED, author
    )

    dirty = [line for line in _git("status", "--porcelain").splitlines() if line.strip()]
    # The four receipts this run writes are the only files allowed to be dirty here. They are
    # named one by one rather than matched by a pattern: a pattern over `artifacts/` would
    # hide a receipt the run did not write, which is the thing this check is for. The first
    # version named only the sign-off and failed on the three the release audit had just
    # rewritten, which is the check being right about a question asked in the wrong order.
    unexpected = [d for d in dirty if not any(name in d for name in _WRITTEN_BY_THIS_RUN)]
    sheet.record(
        "working tree committed",
        ["git", "status", "--porcelain"],
        PASSED if not unexpected else FAILED,
        (
            f"{len(unexpected)} uncommitted apart from the {len(_WRITTEN_BY_THIS_RUN)} "
            "receipts this run writes"
            + (f": {', '.join(d.strip()[:60] for d in unexpected[:4])}" if unexpected else "")
        ),
    )

    _check_live(sheet, args.check_live)

    counts = sheet.counts()
    signed = counts[FAILED] == 0
    doc = {
        "schema": "SIGNOFF_RECEIPT",
        "schema_version": SCHEMA_VERSION,
        "measured_at_commit": commit,
        "measured_at_commit_date": _git("show", "-s", "--format=%cI", "HEAD"),
        "note_on_the_commit": (
            "This receipt is written at the commit named above and then committed, so the "
            "commit it lands in is one later. It cannot name that one, and saying so is "
            "better than implying it measured itself."
        ),
        "commits_behind_head_when_written": 0,
        "verdict": "SIGNED" if signed else "NOT_SIGNED",
        "counts": counts,
        "checks": sheet.rows,
        "what_a_not_checked_row_means": (
            "The check could not run in this environment and its row says why. It is neither "
            "a pass nor a failure: folding it into either would misreport the run."
        ),
    }
    RECEIPT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")

    print(
        f"\n{counts[PASSED]} passed, {counts[FAILED]} failed, "
        f"{counts[NOT_CHECKED]} not checked. Verdict: {doc['verdict']}."
    )
    print(f"written to {RECEIPT.relative_to(REPO).as_posix()}")
    if not signed:
        print("\nThe receipt names what failed. Repair it and re-run; do not edit the receipt.")
    return 0 if signed else 1


if __name__ == "__main__":
    sys.exit(main())
