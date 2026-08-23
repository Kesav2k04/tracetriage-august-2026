"""Run mypy over the package and fail on a new error, against a committed baseline.

    .venv/Scripts/python.exe scripts/check_types.py
    .venv/Scripts/python.exe scripts/check_types.py --verbose

The CI job had a step labelled "Type check" that could not turn the build red. It ran
`mypy pipeline` under `continue-on-error: true`, so a judge reading `.github/workflows/ci.yml`
saw a type check in the pipeline and 51 errors went past it every run. `scripts/gate.py`
does not run mypy at all. A step that cannot fail is not a check, and one that looks like a
check is worse than no step, because it is read as evidence.

**Why a baseline rather than zero.** The 51 are annotation debt and `pyproject.toml` already
discloses them. Every one in the classes that could carry a live code path was read: four
`Item "None" of "Corridor | None"` hits in `live.py` that `live.py:629` raises before
reaching, three `int - None` hits in `waterfall.py` behind a comprehension filtered on
`is not None`, and an `int <= None` in `ood.py` from a loose dict value type. The one that
is not annotation debt is `Image.LANCZOS` at `waterfall.py:426` and `baseline.py:583,863`: a
deprecated Pillow alias that is live today, which is why `pillow` now carries an upper
bound. Fixing 51 annotations days before a deadline is a change to 17 files in the
measurement path. Refusing to let the number grow costs nothing and catches the next one.

So this is a ratchet in one direction. More errors than the baseline is a failure that names
them. Fewer is not: it prints the new number and asks for the baseline to be lowered, so a
cleanup does not turn the build red for having improved something.

**The instrument is named.** An error count is a measurement, and mypy's own version decides
it: a checker release that narrows a type reports errors this one does not. The CI step
installs the version below, and a run under a different one prints a note saying so before
it compares, because a count taken with a different instrument is worth reading and worth
labelling.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

#: What `mypy pipeline` reports at the commit this baseline was taken, 2026-08-23.
#:
#: Measured twice: once in the maintainer's environment and once with `easyocr` and
#: `langchain_core` forced to skip, which is how they resolve on the CI runner, because CI
#: installs `[full,dev,onnx]` and neither extra is in it. Both runs report 51, so the
#: number is a property of the code rather than of one machine's site-packages.
BASELINE = 51

#: The mypy the baseline was measured with. Not a pin on the project: `pyproject.toml`
#: bounds mypy below 3, and this records which release produced the number.
MEASURED_WITH = "2.3.1"

#: What the package is, said once. The CI step ran exactly this argument.
TARGET = "pipeline"

_SUMMARY = re.compile(r"^Found (\d+) errors? in (\d+) files?", re.MULTILINE)
_CLEAN = re.compile(r"^Success: no issues found", re.MULTILINE)


def _mypy_version() -> str:
    out = subprocess.run(
        [sys.executable, "-m", "mypy", "--version"],
        cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout
    found = re.search(r"mypy (\d+\.\d+(?:\.\d+)?)", out)
    return found.group(1) if found else out.strip() or "unknown"


def _count(output: str) -> int | None:
    """How many errors mypy reported, or None if it did not get far enough to say.

    An exit code is not enough on its own. mypy exits 2 without checking anything when it
    finds one source file under two module names, which is the failure
    `explicit_package_bases` exists to prevent, and an exit 2 under
    `continue-on-error: true` looked exactly like a clean run for the whole life of that
    step. So the summary line decides, and its absence is a refusal rather than a zero.
    """
    if _CLEAN.search(output):
        return 0
    found = _SUMMARY.search(output)
    return int(found.group(1)) if found else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=int,
        default=BASELINE,
        help=f"the count to compare against (default {BASELINE})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print mypy's whole output even when the count is within the baseline",
    )
    args = parser.parse_args(argv)

    version = _mypy_version()
    if version != MEASURED_WITH:
        print(
            f"[NOTE] mypy {version} here, and the baseline of {args.baseline} was measured "
            f"with {MEASURED_WITH}. A checker release decides an error count, so the two "
            f"numbers may not be comparable. Compared anyway, and this line is the label."
        )

    proc = subprocess.run(
        [sys.executable, "-m", "mypy", TARGET],
        cwd=_REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    count = _count(output)

    if count is None:
        print(
            f"[FAIL] mypy exited {proc.returncode} without reporting a count, so nothing "
            f"was compared. This is the state that looked like a clean run for the whole "
            f"life of the continue-on-error step:"
        )
        for line in output.strip().splitlines()[-8:]:
            print(f"        {line}")
        return 1

    if count > args.baseline:
        print(
            f"[FAIL] mypy reports {count} errors in {TARGET} and the committed baseline is "
            f"{args.baseline}, so {count - args.baseline} of them are new. The baseline "
            f"exists to stop the count growing, not to be raised:"
        )
        for line in output.strip().splitlines():
            if ": error:" in line:
                print(f"        {line}")
        return 1

    if count < args.baseline:
        print(
            f"[PASS] mypy reports {count} errors in {TARGET}, below the baseline of "
            f"{args.baseline}. Lower BASELINE in scripts/check_types.py to {count} so the "
            f"ratchet keeps its grip."
        )
        return 0

    print(f"[PASS] mypy reports {count} errors in {TARGET}, the committed baseline")
    if args.verbose:
        print(output.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
