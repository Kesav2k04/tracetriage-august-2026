"""What a motion change costs, measured on two builds of the same site.

    .venv/Scripts/python.exe scripts/serve_dist.py <before-dir> 8201
    .venv/Scripts/python.exe scripts/serve_dist.py apps/web/out 8202
    .venv/Scripts/python.exe scripts/measure_motion_perf.py --out artifacts/MOTION_RECEIPT.json

Lighthouse rather than a hand-rolled probe, for one reason: it is already on this machine,
it applies the same simulated throttling to both conditions, and its numbers are ones a
reader can reproduce without taking this repository's word for how they were taken. Four
metrics, because a motion layer can be paid for in four currencies and reporting one of
them is how a regression ships:

* first contentful paint, what a reader waits for before anything is there;
* largest contentful paint, which a script arriving before the hero moves;
* cumulative layout shift, which an entrance animation that reserves no space pays;
* total blocking time, the main thread the animation is competing for.

Both builds are served by ``scripts/serve_dist.py``, which sends gzip. An uncompressed
static server inflates this site's JavaScript about three times and points the work at
whichever file happens to be largest raw.

**Interleaved, before then after, page by page, round by round.** A machine that gets
busier halfway through a run is otherwise indistinguishable from a change to the page.
Compared as pairs, not as medians. Round n's after is compared with round n's before and
the deltas are reported with their range, because the thing that changes between rounds is
the machine. An A/A control on this harness, both origins serving byte-identical builds,
returned first-paint medians 3 ms apart with a within-condition spread of 0 ms: as medians
that reads as a 3 ms regression, and as pairs it reads as nothing.

What it does not measure: scroll stutter. Lighthouse's blocking time covers load. Frames
dropped while a scroll-driven animation runs are a separate question and
``apps/web/audit/scroll-stutter-probe.js`` answers it, through a driver, over a scripted
scroll.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: The A/A run: both origins serving byte-identical builds, so every paired delta in it
#: is this harness measuring itself. It is the default noise floor because a run with no
#: floor cannot say whether anything it found is a difference, and defaulting to nothing
#: made that the easy path. Produced by this same script pointed at one build twice.
CONTROL = REPO / "artifacts" / "MOTION_AA_CONTROL.json"

#: Both builds, served identically. The names are what the receipt calls them.
CONDITIONS = (("before", "http://127.0.0.1:8201"), ("after", "http://127.0.0.1:8202"))

#: The three pages the motion layer is on: the hero and its corridor plate, the gate page
#: with the longest scroll, and the replay page that runs a clock across four instruments.
PAGES = ("/", "/evaluation/", "/replay/")

ROUNDS = 3

#: Lighthouse's own metric ids, with what each one is for in the receipt.
METRICS = {
    "first-contentful-paint": "fcp_ms",
    "largest-contentful-paint": "lcp_ms",
    "cumulative-layout-shift": "cls",
    "total-blocking-time": "tbt_ms",
    "speed-index": "speed_index_ms",
}


def _lighthouse(url: str, workdir: Path) -> dict[str, Any]:
    """One run, desktop preset, performance only, parsed from the JSON report."""
    binary = shutil.which("lighthouse")
    if binary is None:
        raise SystemExit(
            "lighthouse is not on PATH. It is not a dependency of this project and is "
            "not installed by it: `npm i -g lighthouse`. A measurement that silently "
            "falls back to something else is worse than one that refuses."
        )
    report = workdir / "report.json"
    finished = subprocess.run(  # noqa: S603  (fixed argv, no shell)
        [
            binary,
            url,
            "--preset=desktop",
            "--only-categories=performance",
            "--output=json",
            f"--output-path={report}",
            "--chrome-flags=--headless=new --no-sandbox",
            "--quiet",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if finished.returncode != 0 or not report.exists():
        raise SystemExit(
            f"lighthouse failed on {url}: {finished.stderr.strip()[:400] or 'no output'}"
        )
    payload = json.loads(report.read_text(encoding="utf-8"))
    audits = payload["audits"]
    sample = {name: audits[metric]["numericValue"] for metric, name in METRICS.items()}
    sample["score"] = payload["categories"]["performance"]["score"]
    sample["throttling"] = payload["configSettings"]["throttlingMethod"]
    return sample


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n": len(samples)}
    for name in (*METRICS.values(), "score"):
        values = [s[name] for s in samples]
        out[name] = {
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
        }
    return out


def _paired(runs: list[dict[str, Any]], page: str, metric: str) -> dict[str, Any]:
    """After minus before, round by round, on the same page.

    Paired rather than median against median, because the runs are interleaved on one
    machine and the thing that moves between rounds is the machine. A first A/A control
    on this harness made the point: two byte-identical builds gave first-paint medians
    3 ms apart with a within-condition spread of 0 ms over two rounds, which compared as
    medians reads as a real 3 ms difference and compares as pairs as nothing.

    A delta range that contains zero is not a difference and this says so rather than
    reporting the point estimate on its own.
    """
    deltas = []
    for row in runs:
        if row["page"] != page or row["condition"] != "after":
            continue
        before = next(
            (
                other
                for other in runs
                if other["page"] == page
                and other["condition"] == "before"
                and other["round"] == row["round"]
            ),
            None,
        )
        if before is not None:
            deltas.append(row[metric] - before[metric])
    if not deltas:
        return {"pairs": 0, "median": None, "min": None, "max": None, "contains_zero": None}
    return {
        "pairs": len(deltas),
        "median": round(statistics.median(deltas), 4),
        "min": round(min(deltas), 4),
        "max": round(max(deltas), 4),
        "contains_zero": min(deltas) <= 0 <= max(deltas),
    }


def _floor(control: dict[str, Any] | None, page: str, metric: str) -> float | None:
    """The widest paired delta the A/A control saw for this page and metric.

    Computed from the control's own ``runs`` rather than read out of its
    ``paired_deltas`` block. The derived block is a view and it goes stale: adding the
    lighthouse score to the reported metrics made every existing control missing a floor
    for it, and a missing floor is reported as "no control", which reads as an excuse
    rather than as the measurement that is sitting in the same file. The runs are the
    ground truth and they carry every metric this script records.

    None when there is no control, or when the control has no pairs for this page, and
    that is reported as such rather than as zero. A floor of zero makes every wobble a
    finding, which is the failure the control exists to prevent.
    """
    if not control:
        return None
    runs = control.get("runs") or []
    paired = _paired(runs, page, metric) if runs else None
    if not paired or paired.get("pairs", 0) == 0:
        # Fall back to the derived block, for a control written by an older version of
        # this script that kept the summary and not the runs.
        paired = (control.get("paired_deltas") or {}).get(page, {}).get(metric)
    if not paired or paired.get("pairs", 0) == 0:
        return None
    return max(abs(paired["min"]), abs(paired["max"]))


def _reading(
    runs: list[dict[str, Any]], pages: list[str], control: dict[str, Any] | None
) -> str:
    """One sentence per page, from the paired deltas against the control's own range."""
    lines = []
    for page in pages:
        parts = []
        for metric, label in (
            ("fcp_ms", "first paint"),
            ("lcp_ms", "largest paint"),
            ("cls", "layout shift"),
            ("tbt_ms", "blocking time"),
            # The score last, because it is a weighted function of the four above and on
            # this harness it is dominated by largest contentful paint, the one metric the
            # A/A control showed cannot support a claim. A summary median of 1.00 against
            # 0.99 with nothing beside it reads as a regression that none of the component
            # numbers contain, so the paired delta is published with the rest.
            ("score", "lighthouse performance"),
        ):
            paired = _paired(runs, page, metric)
            if paired["pairs"] == 0:
                continue
            unit = "" if metric in {"cls", "score"} else " ms"
            floor = _floor(control, page, metric)
            delta = paired["median"]
            if floor is None:
                verdict = (
                    "with no A/A control to compare it against, so whether it is a "
                    "difference is not established here"
                )
            elif abs(delta) <= floor:
                verdict = (
                    f"inside the {floor:g}{unit} range the same harness produced on two "
                    f"identical builds, so it is not a difference"
                )
            elif paired["contains_zero"]:
                verdict = (
                    f"larger than the control's {floor:g}{unit}, but the pairs span "
                    f"{paired['min']:+g} to {paired['max']:+g} and contain zero"
                )
            else:
                verdict = (
                    f"outside the control's {floor:g}{unit}, and every one of "
                    f"{paired['pairs']} pairs has the same sign "
                    f"({paired['min']:+g} to {paired['max']:+g})"
                )
            parts.append(f"{label} {delta:+g}{unit}, {verdict}")
        lines.append(f"{page}: " + "; ".join(parts) + ".")
    return " ".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=None, help="write a receipt here")
    ap.add_argument("--rounds", type=int, default=ROUNDS)
    ap.add_argument(
        "--from",
        dest="reuse",
        type=Path,
        default=None,
        help=(
            "recompute the derived blocks from a receipt's stored runs instead of "
            "measuring again. Everything above `runs` in a receipt is a view of it, so a "
            "change to how the numbers are read should not need the browser back. Nothing "
            "is re-measured and no run is invented: if a metric is not in the stored runs "
            "it stays absent."
        ),
    )
    ap.add_argument("--pages", nargs="*", default=list(PAGES))
    ap.add_argument(
        "--control",
        type=Path,
        default=CONTROL,
        help=(
            "an A/A receipt from this harness, both origins serving the same build. Its "
            "paired deltas are the noise floor this run is read against. Pass --control "
            "NONE to run without one, which is what producing a new control looks like."
        ),
    )
    args = ap.parse_args(argv)
    if str(args.control).upper() == "NONE":
        args.control = None
    if args.control and args.out and args.control.resolve() == args.out.resolve():
        # A run whose floor is the file it is about to overwrite is reading its own
        # previous output and calling it a control. The numbers would look plausible and
        # mean nothing, which is the worst combination available.
        raise SystemExit(
            f"--control and --out are the same file ({args.out}). A run cannot be its own "
            f"noise floor. Produce a control with --control NONE and two origins serving "
            f"the same build, then point later runs at it."
        )
    if args.control and not args.control.exists():
        raise SystemExit(
            f"no control at {args.control}. Produce one by serving the same build on both "
            f"ports and running with --control NONE --out {args.control}, or pass "
            f"--control NONE to accept that this run cannot say what is a difference."
        )
    control = (
        json.loads(args.control.read_text(encoding="utf-8")) if args.control else None
    )

    runs: list[dict[str, Any]] = []
    if args.reuse:
        stored = json.loads(args.reuse.read_text(encoding="utf-8"))
        runs = stored.get("runs") or []
        if not runs:
            raise SystemExit(
                f"{args.reuse} carries no runs, so there is nothing to recompute from. A "
                f"receipt without its raw runs can only be re-measured."
            )
        args.pages = sorted({row["page"] for row in runs}, key=list(PAGES).index)
        args.rounds = len({row["round"] for row in runs})
        print(f"recomputing from {len(runs)} stored runs in {args.reuse}")
    with tempfile.TemporaryDirectory() as raw:
        workdir = Path(raw)
        for round_index in range(0 if args.reuse else args.rounds):
            for page in args.pages:
                for condition, origin in CONDITIONS:
                    sample = _lighthouse(origin + page, workdir)
                    runs.append(
                        {"round": round_index, "page": page, "condition": condition}
                        | sample
                    )
                    print(
                        f"  {condition:>6} {page:<14} fcp {sample['fcp_ms']:6.0f}  "
                        f"lcp {sample['lcp_ms']:6.0f}  cls {sample['cls']:.4f}  "
                        f"tbt {sample['tbt_ms']:5.0f}",
                        flush=True,
                    )

    summary = {
        page: {
            condition: _summary(
                [r for r in runs if r["page"] == page and r["condition"] == condition]
            )
            for condition, _ in CONDITIONS
        }
        for page in args.pages
    }
    payload = {
        "schema": "tracetriage/motion-perf",
        "schema_version": "0.1.0",
        "tool": "lighthouse, desktop preset, performance category only",
        "throttling": runs[0]["throttling"] if runs else None,
        "served": "scripts/serve_dist.py, gzip on the text types",
        "interleaved": "before then after, page by page, round by round",
        "rounds": args.rounds,
        "recomputed_from": str(args.reuse) if args.reuse else None,
        "summary": summary,
        "reading": _reading(runs, list(args.pages), control),
        "noise_floor": {
            "source": str(args.control) if args.control else None,
            "reading": (
                "The widest paired delta this harness produced with both origins "
                "serving byte-identical builds. A measured delta inside it is not a "
                "difference. Largest contentful paint has no usable floor here: its "
                "A/A range is wider than any change worth making, so it is reported "
                "and not claimed."
            ),
            "by_page": {
                page: {
                    metric: _floor(control, page, metric)
                    for metric in ("fcp_ms", "lcp_ms", "cls", "tbt_ms", "score")
                }
                for page in args.pages
            },
        },
        "paired_deltas": {
            page: {
                metric: _paired(runs, page, metric)
                for metric in ("fcp_ms", "lcp_ms", "cls", "tbt_ms", "speed_index_ms")
            }
            for page in args.pages
        },
        "what_this_does_not_measure": (
            "scroll stutter. Blocking time covers load. Frames dropped while a "
            "scroll-driven animation runs are a different question and "
            "apps/web/audit/scroll-stutter-probe.js answers it over a scripted scroll."
        ),
        "runs": runs,
    }
    print()
    print(payload["reading"])
    if args.out:
        args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
