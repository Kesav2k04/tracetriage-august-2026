"""Bring the KILL_GATE.md status summary and failure log back to the receipts.

The per-split table at the bottom of the document already matched
artifacts/QUEUE_RECEIPT.json. The status summary at the top and the failure log
entry did not: both carried numbers from an earlier run. A document that states two
different confidence intervals for the same gate is the claim drift this project
audits other people's work for, so the correction is applied here and recorded in the
build log and the claim register rather than quietly overwritten.
"""
import json
import pathlib

receipt = json.loads(
    pathlib.Path("artifacts/QUEUE_RECEIPT.json").read_text(encoding="utf-8")
)
fusion = json.loads(
    pathlib.Path("artifacts/FUSION_RECEIPT.json").read_text(encoding="utf-8")
)

by_split = {s["split"]: s for s in receipt["per_split_summaries"]}
chron = receipt["gate6"]["per_split"]["chronological"]
station = receipt["gate6"]["per_split"]["cold_station"]
g5 = fusion["gate5"]["per_split"]["chronological"]

lift = chron["lift_point"]
ci = chron["lift_ci95"]
n_conf = chron["n_queue_conflicts"]
n_rand = chron["n_random_conflicts"]
n_groups = chron["n_groups"]
examined = chron["n_queue_examined"]
# The decisive test count and the bootstrap group count are two different numbers,
# and the document had been quoting gate 5's 88 for both of gate 6's. Gate 6 runs on
# 87 decisive observations in 87 episodes; gate 5 runs on 88 in 88.
decisive = by_split["chronological"]["n_test_decisive"]
median = chron["bootstrap_median"]
st_lift = station["lift_point"]
st_ci = station["lift_ci95"]

print(f"chronological lift={lift:.3f} ci=[{ci[0]:.3f}, {ci[1]:.3f}] "
      f"conflicts={n_conf} expected={n_rand:.1f} groups={n_groups} examined={examined}")
print(f"cold_station lift={st_lift:.3f} ci=[{st_ci[0]:.3f}, {st_ci[1]:.3f}]")
print(f"gate5 margin={g5['margin']:.5f} ci=[{g5['ci95'][0]:.5f}, {g5['ci95'][1]:.5f}]")

p = pathlib.Path("docs/KILL_GATE.md")
s = p.read_text(encoding="utf-8")

old5 = (
    "| 5 | Physics beats image-only on Brier | strict improvement, chronological "
    "split | **NOT ESTABLISHED. Margin +0.02080, 95% CI -0.01271 to +0.05022 on 88 "
    "test observations across 88 episodes. A narrower arm (image + corridor) does "
    "clear zero and survives correction; the gate as worded does not.** |"
)
new5 = (
    "| 5 | Physics beats image-only on Brier | strict improvement, chronological "
    f"split | **NOT ESTABLISHED. Margin +{g5['margin']:.5f}, 95% CI "
    f"{g5['ci95'][0]:+.5f} to {g5['ci95'][1]:+.5f} on {g5['n_observations']} test "
    f"observations across {g5['n_groups']} episodes. A narrower arm (image + "
    "corridor) does clear zero and survives correction; the gate as worded does "
    "not.** |"
)
assert s.count(old5) == 1, "gate 5 summary row not found"
s = s.replace(old5, new5)

old6 = (
    "| 6 | Queue lift over random | ≥1.5x actionable conflicts at equal budget "
    "| **NOT_ESTABLISHED. Point lift +1.60×, 95% CI [1.00, 1.20] on 88 decisive "
    "test observations across 88 episodes (chronological split, budget 50). CI lies "
    "below threshold; cold_station split PASSED at 3.00×.** |"
)
new6 = (
    "| 6 | Queue lift over random | ≥1.5x actionable conflicts at equal budget "
    f"| **NOT_ESTABLISHED. Point lift {lift:.3f}×, 95% CI [{ci[0]:.3f}, "
    f"{ci[1]:.3f}] on {decisive} decisive test observations across {n_groups} "
    f"episodes (chronological split, budget {examined}). The interval contains the "
    f"1.5× threshold; cold_station PASSED at {st_lift:.3f}×.** |"
)
assert s.count(old6) == 1, "gate 6 summary row not found"
s = s.replace(old6, new6)

# The failure log entry. Rewritten from the receipt, with a note that it was.
old_log_start = (
    "**2026-08-18, gate 6: NOT ESTABLISHED.** The review-value queue's point lift is "
    "1.60x over random"
)
idx = s.index(old_log_start)
end = s.index("Receipt: `artifacts/QUEUE_RECEIPT.json`.", idx) + len(
    "Receipt: `artifacts/QUEUE_RECEIPT.json`."
)
new_log = (
    "**2026-08-18, gate 6: NOT ESTABLISHED.** The review-value queue's point lift is "
    f"{lift:.3f}x over random at budget {examined} on the chronological split "
    f"({n_conf} conflicts against {n_rand:.1f} expected, {decisive} decisive test "
    f"observations across {n_groups} episodes). The 95% grouped bootstrap interval is "
    f"[{ci[0]:.3f}, {ci[1]:.3f}], which contains the 1.5x threshold, so the claim is "
    f"not established. Bootstrap median {median:.3f}. cold_station PASSED at "
    f"{st_lift:.3f}x [{st_ci[0]:.3f}, {st_ci[1]:.3f}] on "
    f"{by_split['cold_station']['n_test_decisive']} decisive observations, which is "
    "the split where a reviewer meets unseen stations, and it does not substitute for "
    "the primary split. cold_transmitter "
    f"{receipt['gate6']['per_split']['cold_transmitter']['lift_point']:.3f}x and "
    "cold_combined "
    f"{receipt['gate6']['per_split']['cold_combined']['lift_point']:.3f}x are both "
    "NOT_ESTABLISHED on intervals containing the threshold. Receipt: "
    "`artifacts/QUEUE_RECEIPT.json`."
)
s = s[:idx] + new_log + s[end:]

correction = """
**2026-08-18, correction to this document.** The status summary at the top of this
file and the failure-log entry above both carried gate numbers from an earlier run,
while the per-split table further down carried the current ones. The summary claimed a
95% interval of [1.00, 1.20] for gate 6 and a cold_station lift of 3.00x; the receipt
says [1.353, 1.755] and 2.253x. Two different intervals for one gate in one document
is exactly the drift this project checks for elsewhere, and it was found by reading the
file against `artifacts/QUEUE_RECEIPT.json` rather than by any gate. The summary and
the log entry are now generated from the receipt by
`scripts/sync_kill_gate.py`, so the next re-run cannot leave them behind. The verdict
was NOT_ESTABLISHED before the correction and is NOT_ESTABLISHED after it: no
conclusion changes, only the numbers supporting it.

A second error came out of the same reading. Gate 6 was described as running on "88
decisive test observations across 88 episodes". It runs on 87 in 87: `n_test_decisive`
and `n_groups` in the queue receipt are both 87, and 88 is gate 5's sample size, which
had been copied across. One observation is not a material difference to the verdict,
and that is the reason it survived: a wrong number that changes nothing is the kind
nobody checks. It is now read from the receipt like the rest of the row.
"""
s = s.rstrip("\n") + "\n" + correction
p.write_text(s, encoding="utf-8")
print("KILL_GATE.md synced to the receipts")
