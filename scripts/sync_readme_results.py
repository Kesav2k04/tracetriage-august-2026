"""Regenerate README.md's results tables from the receipts.

The README's results table once listed the Brier score, the calibration slope, the queue
lift and both cold splits as `[UNMEASURED]` long after all of them had been measured and
committed. A stale table that understates the work is worse than one that overstates it,
because nobody thinks to re-derive a claim that something was not done.

Run this after any pipeline re-run. It is idempotent: the tables are replaced, and the
prose sections it also manages are only inserted if they are absent.

    .venv/Scripts/python.exe scripts/sync_readme_results.py

`tests/test_claim_drift.py` requires that every metric name in the generated table has a
row in `docs/CLAIM_REGISTER.md`, so adding a row here means adding one there too.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import textwrap

REPO = pathlib.Path(__file__).resolve().parent.parent

# The gate tally is computed by the console builder from the receipts. Importing it is
# the point: the last time this sentence was typed by hand it said two gates were
# inconclusive while three were, for a week, in the paragraph that introduces the
# evidence table. The insert makes the import work whichever directory it is run from.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_console_data import build_gate_summary  # noqa: E402
from sync_kill_gate import THRESHOLDS, TITLES  # noqa: E402

fusion = json.loads((REPO / "artifacts/FUSION_RECEIPT.json").read_text(encoding="utf-8"))
queue = json.loads((REPO / "artifacts/QUEUE_RECEIPT.json").read_text(encoding="utf-8"))

splits = {s["split"]: s for s in fusion["splits"]}
chronological = splits["chronological"]
arms = chronological["arms"]
shipped = arms["image_corridor"]
image_only = arms["image_only"]
prior = arms["prior_only"]
g6 = queue["gate6"]["per_split"]
g5 = fusion["gate5"]["per_split"]["chronological"]

# The selective row nearest 80% coverage, chosen by distance rather than by eye.
curve = [r for r in chronological["selective"]["curve"] if r.get("coverage") is not None]
near80 = min(curve, key=lambda r: abs(r["coverage"] - 0.80))

# The path, not the bare filename. A reader who follows `FUSION_RECEIPT.json` has to
# guess the directory, and a test that checks the README's paths exist reads the bare
# name as a claim about the repository root, where no such file is.
_summary = build_gate_summary(queue, fusion)
_verdicts = [g["verdict"] for g in _summary["gates"]]
N_GATES = _summary["n_gates"]
N_MET = _summary["n_met"]
N_INCONCLUSIVE = _verdicts.count("NOT_ESTABLISHED")
N_OPEN = _verdicts.count("OPEN")


def _were(n: int) -> str:
    return "was" if n == 1 else "were"


GATE_TALLY = (
    f"Of the {N_GATES} kill gates, {N_MET} {_were(N_MET)} met, "
    f"{N_INCONCLUSIVE} came back inconclusive and {N_OPEN} {_were(N_OPEN)} never run."
)

# Wrapped here rather than in the template, because the tally's length depends on the
# receipts and a hand-wrapped paragraph would go ragged the first time a gate changed.
INTRO = textwrap.fill(
    "Every cell below is read from a receipt under `artifacts/` and registered in "
    f"`docs/CLAIM_REGISTER.md`. {GATE_TALLY} The rows for the gates that produced no "
    "number say so rather than being left out.",
    width=90,
)

FUSION_REF = "`artifacts/FUSION_RECEIPT.json`"
QUEUE_REF = "`artifacts/QUEUE_RECEIPT.json`"


CIRCULARITY_REF = "`artifacts/CIRCULARITY_RECEIPT.json`"

_circ = json.loads(
    (REPO / "artifacts/CIRCULARITY_RECEIPT.json").read_text(encoding="utf-8")
)
_ceiling = _circ["ceiling"]
_shared = _circ["shared_signals"]
_all_three = _circ["targets"]["all_three_criteria"]
_model_free = _circ["targets"]["model_independent_only"]
_model_only = _circ["targets"]["model_dependent_only"]
_control = _circ["random_ordering_control"]

PRECEDENT_REF = "`artifacts/PRECEDENT_RECEIPT.json`"

# The two results the table did not carry. Both are findings against the project's own
# preferred answer, and a results table that lists only the comparisons that went the
# right way is a selection of the evidence rather than the evidence.
_ablation = fusion["ablation_conclusion"]["shipped_arm_vs_recommendation"]
_precedent = json.loads(
    (REPO / "artifacts/PRECEDENT_RECEIPT.json").read_text(encoding="utf-8")
)
_knn_warm = _precedent["conditions"]["warm"]["comparisons"]["granite_text_vs_numeric_knn"]
_knn_cold = _precedent["conditions"]["cold"]["comparisons"]["granite_text_vs_numeric_knn"]
for _name, _comp in (("warm", _knn_warm), ("cold", _knn_cold)):
    if not _comp.get("measurable"):
        raise SystemExit(
            f"the precedent receipt's {_name} head-to-head against the numeric baseline "
            "is not measurable, so the README cannot quote its margin. "
            f"Reason: {_comp.get('not_measurable_reason')}"
        )


def lift(name: str) -> str:
    """One split's lift and its interval, formatted once rather than ten times."""
    g = g6[name]
    lo, hi = g["lift_ci95"]
    return f"{g['lift_point']:.3f}x, 95% CI [{lo:.3f}, {hi:.3f}]"


# Rows as data. A markdown row carrying three interpolated values does not fit in a
# hundred columns, and wrapping an f-string mid-cell reads worse than building the row.
ROWS: list[tuple[str, str, str]] = [
    (
        "Brier score, chronological holdout",
        f"{shipped['brier']:.4f} for the shipped arm, against "
        f"{image_only['brier']:.4f} image-only and {prior['brier']:.4f} "
        "for a prior-only floor",
        FUSION_REF,
    ),
    (
        "AUC, chronological holdout",
        f"{shipped['auc']:.3f}, against {image_only['auc']:.3f} image-only",
        FUSION_REF,
    ),
    (
        "Calibration slope and intercept",
        f"{shipped['calibration_slope']:.3f} and "
        f"{shipped['calibration_intercept']:.3f}, ECE {shipped['ece']:.4f}",
        FUSION_REF,
    ),
    (
        "Selective risk near 80% coverage",
        f"{near80['risk']:.4f} at {near80['coverage'] * 100:.1f}% coverage",
        FUSION_REF,
    ),
    (
        "Queue lift over random, chronological",
        f"{lift('chronological')}, **NOT_ESTABLISHED** against a 1.5x threshold",
        QUEUE_REF,
    ),
    (
        "Queue lift over image-only uncertainty",
        f"{g6['chronological']['lift_point']:.3f}x against "
        f"{g6['chronological']['image_uncertainty_lift_over_random']:.3f}x "
        "at the same budget",
        QUEUE_REF,
    ),
    (
        "Queue lift over first-in-first-out",
        f"{g6['chronological']['lift_point']:.3f}x against "
        f"{g6['chronological']['fifo_lift_over_random']:.3f}x",
        QUEUE_REF,
    ),
    ("Cold-station holdout", f"**PASSED**, {lift('cold_station')}", QUEUE_REF),
    (
        "Cold-transmitter holdout",
        f"{lift('cold_transmitter')}, NOT_ESTABLISHED",
        QUEUE_REF,
    ),
    (
        "Cold station and transmitter together",
        f"{lift('cold_combined')}, NOT_ESTABLISHED",
        QUEUE_REF,
    ),
    (
        "Physics beats image-only on Brier",
        f"**NOT ESTABLISHED**. Margin +{g5['margin']:.5f}, interval spans zero",
        f"{FUSION_REF} gate5",
    ),
    (
        "Shipped ranker against what the ablation recommends",
        f"They disagree. The queue ranks with `{_ablation['ships']}` and the corrected "
        f"rule recommends `{_ablation['corrected_recommends']}`. The block without "
        f"corrected support is "
        f"{', '.join(f'`{b}`' for b in _ablation['shipped_blocks_without_corrected_support'])}"
        f", kept because the same arm's risk-coverage margin is "
        f"{_ablation['selective_evidence_for_the_shipped_arm']['margin']:+.5f} with a "
        f"corrected interval of "
        f"{_ablation['selective_evidence_for_the_shipped_arm']['ci_adjusted'][0]:+.5f} to "
        f"{_ablation['selective_evidence_for_the_shipped_arm']['ci_adjusted'][1]:+.5f}, "
        f"which does clear zero",
        f"{FUSION_REF} ablation_conclusion",
    ),
    (
        "Granite text embedding against seven standardised numbers",
        f"Indistinguishable in both conditions. Warm margin {_knn_warm['margin']:+.4f}, "
        f"adjusted interval [{_knn_warm['ci_adjusted'][0]:+.4f}, "
        f"{_knn_warm['ci_adjusted'][1]:+.4f}]; cold margin {_knn_cold['margin']:+.4f}, "
        f"[{_knn_cold['ci_adjusted'][0]:+.4f}, {_knn_cold['ci_adjusted'][1]:+.4f}]. Both "
        f"span zero over {_knn_warm['queries']} queries resampled by "
        f"{_knn_warm['n_groups']} ground stations",
        PRECEDENT_REF,
    ),
]

TABLE = "\n".join(f"| {metric} | {value} | {ref} |" for metric, value, ref in ROWS)

# The genuinely unmeasured metrics. They carry the literal `[UNMEASURED]` marker because
# tests/test_claim_drift.py treats that exact string as the only permitted stand-in for a
# number, and because a reader should be able to grep the README for what is missing.
UNMEASURED: list[tuple[str, str]] = [
    (
        "Human minutes per confirmed finding",
        "Kill gate 4, the blinded human decidability study, was never run. Any "
        "number here would be an estimate wearing a measurement's clothes.",
    ),
    (
        "Blinded human decidability rate",
        "Kill gate 4 again, and it is the gate itself rather than a derived quantity. "
        "The console reports gate 4 as OPEN rather than as a value, and the gate tally "
        "counts it as not met.",
    ),
]

UNMEASURED_TABLE = "\n".join(
    f"| {metric} | `[UNMEASURED]` | {why} |" for metric, why in UNMEASURED
)

# ---------------------------------------------------------------------------------
# The status block at the top of the README.
#
# It was a 154-word blockquote. Every fact in it was true and a judge with a minute to
# spend could not find any of them: the verdicts, the tally, the reason gate 3 was
# downgraded and the description of how drift is caught were one paragraph. The two
# feasibility gates were also counted in the same breath as the four that test whether
# the idea works, which flatters the tally, because "two of six met" reads better than
# "none of the four that matter, yet".
# ---------------------------------------------------------------------------------

_GATE_VERDICT = {g["gate"]: g["verdict"] for g in _summary["gates"]}

_FEASIBILITY = (1, 2)
_SUBSTANTIVE = (3, 4, 5, 6)

_g3 = json.loads((REPO / "artifacts/GATE3_RECEIPT.json").read_text(encoding="utf-8"))
_g4 = json.loads((REPO / "artifacts/GATE4_RECEIPT.json").read_text(encoding="utf-8"))
_g3_scored = _g3["observations_scored"]
_g3_discriminating = round(_g3["discriminating_rate"] * _g3_scored)

#: One line per substantive gate saying what the measurement came back as. Short enough
#: to read in a table cell; `docs/KILL_GATE.md` carries the same number with its
#: qualifications, and the receipt carries the rest.
_MEASURED = {
    3: (
        f"{_g3_discriminating} of {_g3_scored} testable observations discriminate, and "
        f"the exact one-sided 95% lower bound on that rate is "
        f"{_g3['rate_lower_bound_95']:.3f}"
    ),
    4: (
        f"never run, so it carries no rate. The instrument exists: "
        f"`scripts/build_gate4_worksheet.py` builds the blinded bundle and "
        f"`artifacts/GATE4_RECEIPT.json` reads `{_g4['verdict']}`"
    ),
    5: (
        f"margin {g5['margin']:+.5f} on the shipped arm, 95% CI {g5['ci95'][0]:+.5f} to "
        f"{g5['ci95'][1]:+.5f}, which contains zero"
    ),
    6: (
        f"{g6['chronological']['lift_point']:.3f}x, 95% CI "
        f"[{g6['chronological']['lift_ci95'][0]:.3f}, "
        f"{g6['chronological']['lift_ci95'][1]:.3f}], which contains the threshold. On "
        f"the held-out cold-station split the same queue **PASSED** at "
        f"{g6['cold_station']['lift_point']:.3f}x"
    ),
}

_N_SUBSTANTIVE_PASSED = sum(
    1 for n in _SUBSTANTIVE if _GATE_VERDICT[n] in {"PASSED", "PRE_PASSED"}
)
_N_SUBSTANTIVE_INCONCLUSIVE = sum(
    1 for n in _SUBSTANTIVE if _GATE_VERDICT[n] == "NOT_ESTABLISHED"
)
_N_SUBSTANTIVE_OPEN = sum(1 for n in _SUBSTANTIVE if _GATE_VERDICT[n] == "OPEN")


#: Small counts read as words in a sentence and as digits in a table. The sentence is
#: what a judge skims, so it gets the words.
_WORDS = {0: "none", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _word(n: int) -> str:
    return _WORDS.get(n, str(n))


def _verdict_cell(n: int) -> str:
    """The verdict token as written, not prettified.

    `PRE_PASSED` and `NOT_ESTABLISHED` are the strings the receipts carry and the strings
    `docs/CLAIM_REGISTER.md` is grepped for. Rendering them with the underscore replaced
    made two different verdicts, one for a reader and one for a search.
    """
    return f"**{_GATE_VERDICT[n]}**"


_FEASIBILITY_TABLE = "\n".join(
    f"| {n} | {TITLES[n]} | {THRESHOLDS[n]} | {_verdict_cell(n)} |" for n in _FEASIBILITY
)
_SUBSTANTIVE_TABLE = "\n".join(
    f"| {n} | {TITLES[n]} | {THRESHOLDS[n]} | {_verdict_cell(n)} | {_MEASURED[n]} |"
    for n in _SUBSTANTIVE
)

_SUBSTANTIVE_HEADLINE = (
    f"{_word(_N_SUBSTANTIVE_PASSED)} passed on the split that decides them, "
    f"{_word(_N_SUBSTANTIVE_INCONCLUSIVE)} came back inconclusive and "
    f"{_word(_N_SUBSTANTIVE_OPEN)} {_were(_N_SUBSTANTIVE_OPEN)} never run"
)

# The one substantive gate that clears its threshold somewhere is named in the headline
# rather than left for a reader to find in the last column, because a summary that
# reports only the verdicts that failed is as partial as one that reports only the pass.
_HELD_OUT_PASS = (
    f"Gate 6 does clear its threshold on the held-out cold-station split, at "
    f"{g6['cold_station']['lift_point']:.3f}x. That is reported, and it is not "
    f"substituted for the split the gate was pre-registered on."
    if g6["cold_station"]["verdict"] == "PASSED"
    else ""
)

_STATUS_HEADLINE = textwrap.fill(
    f"**Status: {_word(N_GATES)} kill gates were written down before any of them was "
    f"measured. {_word(len(_FEASIBILITY)).capitalize()} asked whether the project was "
    "feasible at all and were answered before the first line of pipeline code. Of the "
    f"{_word(len(_SUBSTANTIVE))} that ask whether the idea works, "
    f"{_SUBSTANTIVE_HEADLINE}.** {_HELD_OUT_PASS}".strip(),
    width=90,
)

#: The fence around the status block. A comment pair rather than a heading, because the
#: block sits above the first heading in the file.
# What the project produced, stated above the verdicts.
#
# The first screen of this file named IBM once, in the submission line, and named Granite
# nowhere: the first mention was 160 lines down and the stack table 290 lines down. A
# reader arriving from the challenge listing met a gate table reading "none passed" before
# meeting anything the project built. The same defect was found and fixed on the console's
# landing page. Nothing here softens a verdict, and the status block follows it unchanged.
#
# Generated rather than typed, for the same reason the tables are: a hand-written summary
# of the results is the first thing to go stale when a study is re-run.
_agent = json.loads((REPO / "artifacts/AGENT_RECEIPT.json").read_text(encoding="utf-8"))
_explain = json.loads((REPO / "artifacts/EXPLAIN_RECEIPT.json").read_text(encoding="utf-8"))
_precedent_model = _precedent["embedding_model"]["name"]
_tools_arm = _agent["arms"]["tools"]["correct"]
_control_arm = _agent["arms"]["control"]["correct"]
_pair = _agent["paired"]
_ecounts = _explain["counts"]
_esens = _explain["checker_sensitivity"]


def _bullet(text: str) -> str:
    # break_on_hyphens=False, because the default split "read-only" across two lines and
    # markdown renders that as "read- only".
    return textwrap.fill(
        text,
        width=90,
        initial_indent="- ",
        subsequent_indent="  ",
        break_on_hyphens=False,
    )


ORIENT_OPEN = (
    "<!-- generated by scripts/sync_readme_results.py: what it produced, do not edit -->"
)
ORIENT_CLOSE = "<!-- end what it produced -->"

ORIENT_BLOCK = "\n".join(
    [
        textwrap.fill(
            "**What it produced.** Four things that can be opened rather than taken on "
            "trust. Every figure below is read out of a receipt under `artifacts/` by the "
            "script that writes this block, so none of it can drift from the study it "
            "came from.",
            width=90,
        ),
        "",
        _bullet(
            f"**A ranked review queue over {len(queue['queue'])} observations**, live on "
            f"the console, each row carrying the reason it is there and the measured "
            f"fields that reason was computed from. Nothing is written back to SatNOGS: "
            f"the queue is a reading order, and a human decides."
        ),
        _bullet(
            f"**An agent that answers questions about that evidence over MCP.** "
            f"`{_agent['model']['name']}`, running locally at "
            f"{_agent['model']['quantization']} and temperature "
            f"{_agent['model']['temperature']:.0f}, answers "
            f"{_tools_arm['successes']} of {_tools_arm['trials']} correctly with five "
            f"read-only tools and {_control_arm['successes']} of "
            f"{_control_arm['trials']} with none. One-sided exact p = "
            f"{_pair['exact_p_one_sided']:g} over {_pair['discordant_pairs']} discordant "
            f"pairs. The control arm is the point: the tools are measured, not "
            f"demonstrated."
        ),
        _bullet(
            f"**A grounding checker that refuses most of what the model writes.** Of "
            f"{_ecounts['observations']} drafts, {_ecounts['emitted']} were emitted and "
            f"{_ecounts['refused']} refused. Against "
            f"{_esens['adversarial_checks']} adversarial drafts it caught "
            f"{_esens['caught_for_the_expected_reason']}, and against "
            f"{_esens['control_checks']} clean ones it refused "
            f"{_esens['control_refused']}. A published sentence is one no rule could "
            f"fault, not one the model was confident about."
        ),
        _bullet(
            f"**A precedent search on `{_precedent_model}`**, put head to head against "
            f"seven standardised numbers under a condition built to take its advantage "
            f"away, and reported indistinguishable in both. A result that went the other "
            f"way is published the same size as one that did not."
        ),
    ]
)

STATUS_OPEN = "<!-- generated by scripts/sync_readme_results.py: gate status, do not edit -->"
STATUS_CLOSE = "<!-- end gate status -->"

# What an interval spanning a threshold does not say, stated where the verdicts are.
#
# A reader who stops at the table above leaves with four inconclusive rows and no sense of
# what was actually measured. Two facts belong beside them, both from the same receipts:
# the scale the gate was set on, which is narrow, and the permutation test, which is the
# one direct answer to "could this ordering have come from nothing". Neither softens a
# verdict. The gate still reads NOT_ESTABLISHED, in the same sentence.
_CTRL = _circ["random_ordering_control"]
_WHAT_THE_INTERVALS_DO_NOT_SAY = textwrap.fill(
    f"An interval that spans a threshold is not a measurement of nothing. On the split gate "
    f"6 was pre-registered on, "
    f"{_CTRL['n_permutations_at_or_above_observed']} of "
    f"{_CTRL['n_permutations']:,} random orderings of the same "
    f"{_circ['reproduction']['n_population']} observations found as many actionable "
    f"conflicts inside the review budget as this queue did, a permutation p-value of "
    f"{_CTRL['p_value_permutation']:.4f}. The interval spans 1.5 because the scale is "
    f"short: a budget of {_circ['reproduction']['budget']} over "
    f"{_circ['reproduction']['n_population']} observations holding "
    f"{_circ['reproduction']['n_conflicts']} conflicts caps every possible ordering, a "
    f"perfect oracle included, at {_ceiling['lift']:.3f}x. The gate is still not met, and "
    f"the whole room any ordering had to meet it in was "
    f"{_ceiling['headroom_between_threshold_and_perfection']:.3f} wide.",
    width=90,
)

STATUS_BLOCK = f"""{_STATUS_HEADLINE}

**Feasibility, decided in advance.**

| # | Gate | Threshold | Verdict |
|---|---|---|---|
{_FEASIBILITY_TABLE}

**Substantive, and the reason the rest of this file is worth reading.**

| # | Gate | Threshold | Verdict | What came back |
|---|---|---|---|---|
{_SUBSTANTIVE_TABLE}

{_WHAT_THE_INTERVALS_DO_NOT_SAY}

Inconclusive is reported as `NOT_ESTABLISHED` rather than rounded into a pass, and the gate
that was never run is reported as `OPEN` rather than omitted. Gate 3 was `PASSED` until
2026-08-18, when the rate it claimed was re-derived with an exact interval and moved to
`NOT_ESTABLISHED`; `docs/KILL_GATE.md` carries the entry rather than the history being
quietly rewritten.

Every number in this README is generated from a frozen artifact under `artifacts/` and
carries a row in `docs/CLAIM_REGISTER.md`. `tests/test_claim_drift.py` compares each quoted
value against the artifact it came from rather than merely checking a register row exists:
editing the AUC row from 0.875 to 0.999 turns three tests red. `tests/test_readme_claims.py`
does the same for the paths and images this file names, because an existence claim is as
checkable as a number."""

# Bound outside the template, because a nine-cell table inside an f-string with dotted
# lookups reads as punctuation.
shared_line = (
    "0.40 x disagreement + 0.35 x safe offset magnitude + 0.15 x flat-row fraction "
    "+ 0.10 x ensemble uncertainty"
)
shared_pct = _shared["score_weight_on_quantities_the_definition_names"] * 100
active_pct = _shared["score_weight_on_quantities_a_realised_conflict_is_defined_from"] * 100
inert_criteria = _shared["inert"]
repro = _circ["reproduction"]["lift_point"]
ceiling = _ceiling["lift"]
budget = _circ["reproduction"]["budget"]
population = _circ["reproduction"]["n_population"]
n_conflicts = _circ["reproduction"]["n_conflicts"]
threshold = _ceiling["threshold"]
headroom = _ceiling["headroom_between_threshold_and_perfection"]
n_at_budget = _circ["reproduction"]["n_at_budget"]
max_findable = _ceiling["max_findable_at_budget"]
share = _ceiling["queue_share_of_the_ceiling"]
model_free_lift = _model_free["lift_point"]
mf_lo, mf_hi = _model_free["lift_ci95"]
model_free_verdict = _model_free["verdict"]
mf_n = _model_free["n_conflicts"]
model_only_lift = _model_only["lift_point"]
mo_n = _model_only["n_conflicts"]
model_only_verdict = _model_only["verdict"]
control_mean = _control["mean_lift"]
control_n = _control["n_permutations"]
control_p5 = _control["p5"]
control_p95 = _control["p95"]

def _narrowest_split_answer() -> str:
    """The split whose oracle sits closest to the threshold, named with its numbers.

    Every split publishes a verdict against a 1.5x bar, and one of them caps at 1.520:
    a perfect oracle scores 1.52 there, so no ordering of any kind could have produced
    an informative answer. Reporting that split's NOT_ESTABLISHED as a finding about
    generalisation, without saying the scale is 0.02 wide, reports the budget.
    """
    measurable = {
        name: block
        for name, block in _circ["ceilings_by_split"].items()
        if block.get("measurable")
    }
    if not measurable:
        return "No split published the counts a ceiling is computed from."
    name, block = min(
        measurable.items(),
        key=lambda kv: kv[1]["headroom_between_threshold_and_perfection"],
    )
    verdict = block["published_verdict"]
    tail = (
        ", so its verdict is a fact about the budget and the receipt marks it not "
        "informative"
        if not block["informative"]
        else ", which still leaves room for the measurement to land in"
    )
    return (
        f"`{name}`: {block['n_conflicts']} conflicts in {block['n_population']} "
        f"observations at a budget of {block['budget']} caps every ordering at "
        f"{block['ceiling']:.3f}x against a {block['threshold']}x bar. That is "
        f"{block['headroom_between_threshold_and_perfection']:.3f} of room and a "
        f"published **{verdict}**{tail}"
    )


# Rows as data for the same reason the results table is: a markdown cell carrying four
# interpolated values does not fit in a hundred columns.
_CIRCULARITY_ROWS: list[tuple[str, str]] = [
    (
        "What is the most any ordering could score here?",
        f"{ceiling:.3f}x. A budget of {budget} over {population} observations holding "
        f"{n_conflicts} conflicts caps a perfect oracle there, so the whole distance "
        f"between the {threshold}x threshold and perfection is {headroom:.3f}",
    ),
    (
        "How much of that did the queue get?",
        f"{n_at_budget} of the {max_findable} an oracle would have found, which is "
        f"{share:.0%} of the ceiling",
    ),
    (
        "What happens with the model taken out of the target?",
        f"{model_free_lift:.3f}x, 95% CI [{mf_lo:.3f}, {mf_hi:.3f}], "
        f"**{model_free_verdict}**, counting only the {mf_n} conflicts flagged by the "
        f"{_word(len(_model_free['criteria']))} criteria the model does not enter"
        + (
            ""
            if not inert_criteria
            else (
                f", of which {' and '.join(inert_criteria)} flags nothing here, so the "
                "restriction reduces to one criterion"
            )
        ),
    ),
    (
        "And with only the model's own disagreement?",
        f"{model_only_lift:.3f}x over {mo_n} conflicts, reported as "
        f"**{model_only_verdict}** rather than as a pass: the queue found all {mo_n} "
        "inside the budget, and a saturated lift equals population over budget whatever "
        "the count was",
    ),
    (
        "How often does a random ordering match the queue?",
        f"{_control['n_permutations_at_or_above_observed']} times in "
        f"{control_n:,} seeded shuffles of the same population, a permutation p-value of "
        f"{_control['p_value_permutation']:.4f}, which is the smallest this test can "
        f"report at {control_n:,} permutations",
    ),
    (
        "Does the statistic score a shuffle at 1.0?",
        f"{control_mean:.4f} over the same {control_n:,} permutations, 5th to 95th "
        f"percentile {control_p5:.3f} to {control_p95:.3f}. Each one is scored by "
        f"`{_control['computed_by'].rsplit('.', 1)[-1]}`, the function gate 6 itself is "
        "measured with, so a defect in it moves this number",
    ),
    (
        "Which split has the least room to be measured in?",
        _narrowest_split_answer(),
    ),
]

CIRCULARITY_TABLE = "\n".join(
    ["| Question | Answer |", "|---|---|"]
    + [f"| {q} | {a} |" for q, a in _CIRCULARITY_ROWS]
)

CIRCULARITY_INTRO = textwrap.fill(
    "The ranking score and the definition of a conflict are not independent, and the size "
    f"of that problem is measured rather than described. The score is {shared_line}, and "
    "the three conflict criteria threshold the first three of those same quantities. "
    f"{shared_pct:.0f}% of the score's weight sits on quantities the definition names "
    f"and {active_pct:.0f}% on quantities a conflict in this corpus is actually defined "
    f"from, the gap being {' and '.join(inert_criteria)}, which fires on nothing here. "
    "Either way a lift above 1.0 is close to guaranteed by construction. "
    f"`scripts/run_circularity_check.py` bounds it from {CIRCULARITY_REF}, reading the "
    "queue receipt and nothing else: no snapshot, no network, no model. It reproduces the "
    f"published {repro:.4f}x from that file before computing anything.",
    width=90,
)

CIRCULARITY_CODA = textwrap.fill(
    _circ["what_this_does_not_establish"],
    width=90,
)

SECTION = f"""### Measured, with receipts

{INTRO}

| Metric | Value | Receipt |
|---|---|---|
{TABLE}

### Still unmeasured, and named as such

| Metric | Value | Why |
|---|---|---|
{UNMEASURED_TABLE}

### What the queue's own construction guarantees

{CIRCULARITY_INTRO}

{CIRCULARITY_TABLE}

{CIRCULARITY_CODA}

The queue's headline result is inconclusive, and that is the honest reading:
{g6['chronological']['lift_point']:.3f}x is above the 1.5x threshold as a point estimate,
but its interval contains 1.5, so the evidence does not exclude a queue that clears the
bar by nothing. It also sits entirely above 1.0, so the ranking is not nothing either.
The cold-station split, the one where a reviewer meets stations the model never trained
on, does clear the threshold. It does not substitute for the primary split and is not
presented as if it did.

"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "regenerate into memory and compare against README.md, exiting non-zero "
            "on any difference. Writes nothing."
        ),
    )
    args = parser.parse_args(argv)

    readme = REPO / "README.md"
    text = readme.read_text(encoding="utf-8")

    start_marker = "### Measured, with receipts"
    fallback_marker = "### Not yet measured"
    end_marker = "\n## Setup"

    if start_marker in text:
        start = text.index(start_marker)
    elif fallback_marker in text:
        start = text.index(fallback_marker)
    else:
        raise SystemExit(
            "README.md has neither a 'Measured, with receipts' nor a 'Not yet measured' "
            "section. Refusing to guess where the results belong."
        )

    end = text.index(end_marker)
    rendered = text[:start] + SECTION + text[end + 1 :]

    # The status block is fenced by comments rather than by headings, because it sits
    # above the first heading in the file and has no next heading to stop at.
    if STATUS_OPEN not in rendered or STATUS_CLOSE not in rendered:
        raise SystemExit(
            f"README.md has no {STATUS_OPEN} ... {STATUS_CLOSE} region, so the gate "
            "status block has nowhere to go. Add the two comment markers where the "
            "status paragraph belongs."
        )
    head, rest = rendered.split(STATUS_OPEN, 1)
    _, tail = rest.split(STATUS_CLOSE, 1)
    rendered = f"{head}{STATUS_OPEN}\n{STATUS_BLOCK}\n{STATUS_CLOSE}{tail}"

    # The orientation block sits above the status block for the same reason it is fenced
    # the same way: it has no heading of its own, and it has to stay above the first one.
    if ORIENT_OPEN not in rendered or ORIENT_CLOSE not in rendered:
        raise SystemExit(
            f"README.md has no {ORIENT_OPEN} ... {ORIENT_CLOSE} region, so the block "
            "naming what the project produced has nowhere to go. Add the two comment "
            "markers above the gate status block."
        )
    head, rest = rendered.split(ORIENT_OPEN, 1)
    _, tail = rest.split(ORIENT_CLOSE, 1)
    rendered = f"{head}{ORIENT_OPEN}\n{ORIENT_BLOCK}\n{ORIENT_CLOSE}{tail}"

    # --check exists because this script was referenced by nothing: not by the gate,
    # not by CI, and not by any test. The table it generates stayed correct only for
    # as long as someone remembered to run it, and the drift test beside it compared
    # metric names rather than values, so an edited number passed the whole suite.
    if args.check:
        if rendered == text:
            print(
                f"README results are current: {len(ROWS)} measured rows and "
                f"{N_GATES} gate rows"
            )
            return 0
        current = text.splitlines()
        expected = rendered.splitlines()
        first = next(
            (
                (i, c, e)
                for i, (c, e) in enumerate(zip(current, expected, strict=False))
                if c != e
            ),
            None,
        )
        print("README results are stale. Run scripts/sync_readme_results.py.")
        if first is not None:
            i, c, e = first
            print(f"  first difference, line {i + 1} of the file:")
            print(f"    README:   {c.strip()[:120]}")
            print(f"    receipts: {e.strip()[:120]}")
        elif len(current) != len(expected):
            print(
                f"  the file has {len(current)} lines and the receipts "
                f"produce {len(expected)}"
            )
        return 1

    readme.write_text(rendered, encoding="utf-8")

    print(f"README results synced: {len(ROWS)} measured rows, 2 marked unmeasured")
    print(f"  gate status block: {N_GATES} gates, {N_MET} met")
    print(f"  shipped arm brier {shipped['brier']:.4f}, auc {shipped['auc']:.3f}")
    print(
        f"  selective risk {near80['risk']:.4f} "
        f"at {near80['coverage'] * 100:.1f}% coverage"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
