"""How gate 3's verdict moves with the presence bar that chose its pool.

`docs/E16_PREREGISTRATION.md` section 5 commits to publishing "the verdict's sensitivity
to `TRACE_Q75_MIN`". A researcher degree of freedom that is named and then not measured is
still a degree of freedom, and the reader has no way to tell whether 3.5 was the one value
that produced the published answer.

Nothing is rescored here. Pool membership at a tighter bar is a strict subset of
membership at a looser one, because the rule is `trace_q75 >= bar` and every other clause
is bar-independent. So one scoring run at the pre-registered bar answers every bar at or
above it exactly, by joining the receipt's per-observation results back onto the pool file
on `obs_id` and recomputing the rate and the exact bound over each subset. Bars below the
scored one are reported as unscored rather than estimated: those pools contain
observations this run never looked at, and a table that quietly dropped them would report
a rate over the wrong denominator.

    python scripts/gate3_sensitivity.py

Writes `artifacts/GATE3_SENSITIVITY.json` and prints the table.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.run_gate3 import rate_lower_bound  # noqa: E402

#: The bars reported. 3.5 is the pre-registered one and is always included by the caller
#: passing it through; the rest bracket it so a reader can see both directions.
DEFAULT_BARS = (2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0)


def verdict_for(
    rate: float | None,
    bound: float | None,
    threshold: float,
    grouped_bound: float | None = None,
) -> str:
    """The same four-way rule `scripts/run_gate3.py` applies, grouping included.

    This used to read only the observation-level bound, so at the pre-registered bar it
    printed PASSED against a receipt saying PASSED_UNGROUPED_ONLY. A robustness table that
    disagrees with the receipt at the published row is not corroboration, it is a second
    opinion from a rule the gate does not use.

    The plan groups before it decides, so a bound that clears over observations and not
    over episodes is reported and not claimed.
    """
    if rate is None or bound is None:
        return "UNMEASURABLE"
    if bound >= threshold:
        if grouped_bound is not None and grouped_bound < threshold:
            return "PASSED_UNGROUPED_ONLY"
        return "PASSED"
    if rate >= threshold:
        return "NOT_ESTABLISHED"
    return "FAILED"


def _day(row: dict) -> str | None:
    start = row.get("start")
    return start[:10] if isinstance(start, str) and len(start) >= 10 else None


def _grouped_bound(subset: list[dict]) -> tuple[float | None, int]:
    """The episode-level bound over one subset, by the gate's own collapsing rule.

    A group counts as discriminating only if every observation in it does, which is what
    `scripts/run_gate3.py` does and is the direction that cannot manufacture a pass.
    """
    by_group: dict[tuple, list[bool]] = {}
    for o in subset:
        key = (o.get("station_id"), _day(o))
        by_group.setdefault(key, []).append(
            bool(o["null_calibration"]["discriminates"])
        )
    flags = [all(v) for v in by_group.values()]
    if not flags:
        return None, 0
    return rate_lower_bound(sum(flags), len(flags)), len(flags)


def measure(
    receipt: dict, pool: dict, bars=DEFAULT_BARS, threshold: float | None = None
) -> dict:
    """One row per bar, over the observations this receipt actually scored."""
    threshold = threshold if threshold is not None else receipt["threshold"]
    scored_bar = (receipt.get("pool") or {}).get("trace_q75_min")

    q75 = {
        r["obs_id"]: r.get("trace_q75")
        for r in pool["observations"]
        if r.get("obs_id") is not None
    }
    scored = [
        o for o in receipt["observations"]
        if (o.get("null_calibration") or {}).get("p_value") is not None
    ]

    rows = []
    for bar in sorted(set(bars) | ({scored_bar} if scored_bar else set())):
        if scored_bar is not None and bar < scored_bar - 1e-9:
            rows.append({
                "trace_q75_min": bar,
                "scored": None,
                "discriminating": None,
                "rate": None,
                "lower_bound_95": None,
                "verdict": "NOT SCORED",
                "why": (
                    f"a bar of {bar} selects observations this run did not score, so a "
                    f"rate over them would have the wrong denominator"
                ),
            })
            continue
        subset = [o for o in scored if (q75.get(o["obs_id"]) or 0.0) >= bar]
        n = len(subset)
        hits = sum(1 for o in subset if o["null_calibration"]["discriminates"])
        rate = hits / n if n else None
        bound = rate_lower_bound(hits, n) if n else None
        gbound, n_groups = _grouped_bound(subset)
        rows.append({
            "trace_q75_min": bar,
            "scored": n,
            "discriminating": hits,
            "rate": rate,
            "lower_bound_95": bound,
            "groups": n_groups,
            "grouped_lower_bound_95": gbound,
            "verdict": verdict_for(rate, bound, threshold, gbound),
            "is_the_pre_registered_bar": scored_bar is not None
            and abs(bar - scored_bar) < 1e-9,
        })

    published = next(
        (r for r in rows if r.get("is_the_pre_registered_bar")), None
    )
    measured = [r for r in rows if r["scored"]]
    verdicts = {r["verdict"] for r in measured}
    return {
        "schema": "gate3_sensitivity/1",
        "generated_by": "scripts/gate3_sensitivity.py",
        "threshold": threshold,
        "scored_at_bar": scored_bar,
        "published_verdict": published["verdict"] if published else None,
        "verdict_is_constant_across_measured_bars": len(verdicts) == 1,
        "distinct_verdicts": sorted(verdicts),
        "note": (
            "No observation is rescored. A tighter bar selects a strict subset of a "
            "looser one, so every row at or above the scored bar is exact. Rows below it "
            "are marked NOT SCORED rather than estimated."
        ),
        "rows": rows,
    }


def as_table(out: dict) -> str:
    lines = [
        "| `TRACE_Q75_MIN` | scored | discriminating | rate | 95% lower bound "
        "| episodes | grouped bound | verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in out["rows"]:
        bar = f"**{r['trace_q75_min']}**" if r.get("is_the_pre_registered_bar") \
            else f"{r['trace_q75_min']}"
        if r["scored"] is None:
            lines.append(f"| {bar} | not scored | | | | | | {r['verdict']} |")
            continue
        gb = r.get("grouped_lower_bound_95")
        lines.append(
            f"| {bar} | {r['scored']} | {r['discriminating']} | "
            f"{r['rate'] * 100:.0f}% | {r['lower_bound_95']:.4f} | "
            f"{r.get('groups', 0)} | {gb:.4f} | {r['verdict']} |"
            if gb is not None
            else f"| {bar} | {r['scored']} | {r['discriminating']} | "
            f"{r['rate'] * 100:.0f}% | {r['lower_bound_95']:.4f} | "
            f"{r.get('groups', 0)} | | {r['verdict']} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", type=pathlib.Path,
                    default=REPO / "artifacts/GATE3_RECEIPT.json")
    ap.add_argument("--pool", type=pathlib.Path,
                    default=REPO / "artifacts/GATE3_POOL.json")
    ap.add_argument("--out", type=pathlib.Path,
                    default=REPO / "artifacts/GATE3_SENSITIVITY.json")
    args = ap.parse_args()

    for path in (args.receipt, args.pool):
        if not path.exists():
            raise SystemExit(f"{path} is not on disk, so there is nothing to measure.")

    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    pool = json.loads(args.pool.read_text(encoding="utf-8"))
    if (receipt.get("pool") or {}).get("name") not in ("pool_a", "pool_b"):
        raise SystemExit(
            f"{args.receipt} was not produced from a pre-registered pool, so there is no "
            "presence bar to vary. Run scripts/run_gate3.py --pool pool_b first."
        )

    out = measure(receipt, pool)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(as_table(out))
    print()
    print(f"wrote {args.out.relative_to(REPO).as_posix()}")
    if out["verdict_is_constant_across_measured_bars"]:
        print(
            f"  the verdict is {out['published_verdict']} at every bar this run can "
            f"measure, so it does not turn on the threshold"
        )
    else:
        print(
            f"  the verdict is NOT constant: {', '.join(out['distinct_verdicts'])}. The "
            f"published one is the pre-registered bar's and this table is why that "
            f"matters"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
