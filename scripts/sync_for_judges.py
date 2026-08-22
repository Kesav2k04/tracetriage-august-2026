"""Generate FOR_JUDGES.md from the receipts, so the page a judge reads cannot go stale.

A submission page is the one document nobody re-derives. It gets written once, early, when
the numbers are provisional, and then the pipeline runs again and the page keeps saying what
it said. This project's receipts live under `artifacts/` and the console reads them; the
judges' page is generated from the same files, and `--check` fails if the committed page
disagrees with them by one character.

    .venv/Scripts/python.exe scripts/sync_for_judges.py
    .venv/Scripts/python.exe scripts/sync_for_judges.py --check

Every number in the output is read from a receipt. Nothing here is typed, including the
counts of what failed, which is the half of a submission page that usually is.
`tests/test_for_judges.py` asserts the page is current and that every repository path it
cites exists and is published by git.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import textwrap

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_console_data import build_gate_summary  # noqa: E402

OUT = REPO / "FOR_JUDGES.md"

from mcp_server import RESOURCES as _MCP_RESOURCES  # noqa: E402
from mcp_server import TOOLS as _MCP_TOOLS  # noqa: E402

TOOL_NAMES = sorted(_MCP_TOOLS)
RESOURCE_URIS = sorted(_MCP_RESOURCES)


def _receipt(name: str) -> dict:
    path = REPO / "artifacts" / name
    if not path.exists():
        raise SystemExit(
            f"artifacts/{name} is missing, and this page quotes it. Run the script that "
            f"writes it rather than generating a page with a hole in it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


dataset = _receipt("DATASET_MANIFEST.json")
splits = _receipt("SPLIT_MANIFEST.json")
queue = _receipt("QUEUE_RECEIPT.json")
fusion = _receipt("FUSION_RECEIPT.json")
explain = _receipt("EXPLAIN_RECEIPT.json")
secrets = _receipt("SECRET_SCAN.json")
attribution = _receipt("ATTRIBUTION_AUDIT.json")
weight = _receipt("REPO_WEIGHT.json")
clone = _receipt("CLEAN_CLONE_TRANSCRIPT.json")
gate4 = _receipt("GATE4_RECEIPT.json")
#: What packing the bundle measured: the commitments it verified, and the one file a
#: reviewer has to be sent. Read here so this page names an archive that exists at a
#: digest somebody can check, rather than describing an instrument nobody can reach.
gate4_bundle = _receipt("GATE4_BUNDLE.json")
agent = _receipt("AGENT_RECEIPT.json")
precedent = _receipt("PRECEDENT_RECEIPT.json")
circularity = _receipt("CIRCULARITY_RECEIPT.json")
# The presentation film, described by the sources that build it. Read here because the
# film was the one deliverable in this repository with no receipt: its length and its
# claim count were typed into a report, and the rendered file sat committed with nothing
# comparing it to anything.
film = _receipt("FILM_RECEIPT.json")
_FILM = film["composition"]
_FILM_CLAIMS = film["claims"]
_REMOTION = json.loads(
    (REPO / "presentation" / "package.json").read_text(encoding="utf-8")
)["dependencies"]["remotion"]

# The precedent study's cold condition is the negative result on this page that a reader is
# most likely to be shown the flattering half of. Both halves are read from the receipt so
# the sentence cannot keep the warm margin after a re-run moves it.
_PRE_WARM = precedent["conditions"]["warm"]["comparisons"]["granite_text_vs_random"]
_PRE_COLD = precedent["conditions"]["cold"]["comparisons"]["granite_text_vs_random"]
# The queue's headline number is bounded by the way the queue was built, and this is the
# bullet that says so. It belongs on the page a judge reads rather than only in the README,
# because it is the strongest piece of self-criticism in the submission and a page that
# omits it is a page that only publishes the parts that flatter.
_CIRC_CEIL = circularity["ceiling"]
_CIRC_FREE = circularity["targets"]["model_independent_only"]
_CIRC_SIGNALS = circularity["shared_signals"]
_CIRC_NAMED = _CIRC_SIGNALS["score_weight_on_quantities_the_definition_names"]
_CIRC_ACTIVE = _CIRC_SIGNALS[
    "score_weight_on_quantities_a_realised_conflict_is_defined_from"
]
_CIRC_INERT = _CIRC_SIGNALS["inert"]
_CIRC_CONTROL = circularity["random_ordering_control"]


def _inert_clause() -> str:
    """The gap between the two weights, or a statement that there is none.

    Both weights are published because they answer different questions, and the
    difference between them is the weight of a criterion that fires on nothing. A
    reader given only the larger number is being told the loop is worse than it is;
    a reader given only the smaller one is being told the definition is tighter than
    it is. Naming the criterion is what makes the pair readable.
    """
    if not _CIRC_INERT:
        return ", and the two are the same because every criterion fires"
    return (
        f", the gap being {' and '.join(_CIRC_INERT)}, which fires on nothing in this "
        "corpus"
    )


def _narrowest_split() -> str:
    """The split with the least room between the threshold and a perfect oracle."""
    measurable = {
        name: block
        for name, block in circularity["ceilings_by_split"].items()
        if block.get("measurable")
    }
    if not measurable:
        return ""
    name, block = min(
        measurable.items(),
        key=lambda kv: kv[1]["headroom_between_threshold_and_perfection"],
    )
    if block["informative"]:
        return ""
    return (
        f" The same analysis runs on every split, and it finds one, `{name}`, where a "
        f"perfect oracle would score {block['ceiling']:.3f}x against the same "
        f"{block['threshold']}x bar: that split's "
        f"{block['published_verdict']} could not have been anything else, and the "
        "receipt marks it not informative rather than reporting it as a result about "
        "generalisation."
    )


CIRCULARITY_BULLET = (
    "- **The queue's lift is partly guaranteed by how the queue was built.** The ranking "
    f"score puts {_CIRC_NAMED * 100:.0f} percent of its weight on the same three "
    "quantities the conflict criteria threshold, and "
    f"{_CIRC_ACTIVE * 100:.0f} percent on the quantities a conflict in this corpus is "
    f"actually defined from{_inert_clause()}, so beating a random ordering is close to "
    "assured by construction. `scripts/run_circularity_check.py` bounds that from the "
    "queue receipt alone, with no snapshot and no model, and reproduces the published "
    "lift before computing anything. A budget of "
    f"{circularity['reproduction']['budget']} over "
    f"{circularity['reproduction']['n_population']} observations holding "
    f"{circularity['reproduction']['n_conflicts']} conflicts caps any ordering at "
    f"{_CIRC_CEIL['lift']:.3f}x, so the whole distance between the "
    f"{_CIRC_CEIL['threshold']}x threshold and a perfect oracle is "
    f"{_CIRC_CEIL['headroom_between_threshold_and_perfection']:.3f}. Counting only the "
    f"{_CIRC_FREE['n_conflicts']} conflicts flagged by the criteria the model does not "
    f"enter, the same ordering scores {_CIRC_FREE['lift_point']:.3f}x with an interval of "
    f"[{_CIRC_FREE['lift_ci95'][0]:.3f}, {_CIRC_FREE['lift_ci95'][1]:.3f}], still "
    f"{_CIRC_FREE['verdict']}. Against that, "
    f"{_CIRC_CONTROL['n_permutations_at_or_above_observed']} of "
    f"{_CIRC_CONTROL['n_permutations']:,} seeded shuffles of the same population matched "
    f"the queue, a permutation p-value of {_CIRC_CONTROL['p_value_permutation']:.4f}, and "
    f"the mean of those shuffles is {_CIRC_CONTROL['mean_lift']} against an expected 1.0, "
    "which is the floor the whole comparison rests on. Every one of them is scored by the "
    "same function gate 6 is measured with, so a defect in it moves these numbers."
    f"{_narrowest_split()} `artifacts/CIRCULARITY_RECEIPT.json` carries all of it."
)

PRECEDENT_BULLET = (
    "- **Similarity stops carrying the outcome once the station is excluded.** Retrieval "
    f"over {precedent['candidate_pool']['observations']} labelled passes agrees with the "
    f"query's own label {_PRE_WARM['challenger_agreement']:.4f} of the time when a "
    # "chance level" was the wrong name for this number. The receipt carries both: a
    # chance level derived from the label mix, and the random arm's measured agreement.
    # This is the second, which is what the margin is computed against, and calling it the
    # first put a 0.5302 where a 0.5313 belonged in the one document a judge is certain to
    # read.
    f"neighbour may come from the same ground station, against a random arm measuring "
    f"{_PRE_WARM['reference_agreement']:.4f} on the same pool, and the adjusted interval "
    f"[{_PRE_WARM['ci_adjusted'][0]:.4f}, {_PRE_WARM['ci_adjusted'][1]:.4f}] clears zero. "
    f"Forbidding the query's own station and satellite drops it to "
    f"{_PRE_COLD['challenger_agreement']:.4f} against the random arm's "
    f"{_PRE_COLD['reference_agreement']:.4f}, and the adjusted interval "
    f"[{_PRE_COLD['ci_adjusted'][0]:.4f}, {_PRE_COLD['ci_adjusted'][1]:.4f}] does not. "
    "`artifacts/PRECEDENT_RECEIPT.json` carries both conditions and the console shows "
    "them in one table."
)

_PRE_GRANITE = precedent["conditions"]["warm"]["arms"]["granite_text"]["agreement_at_k"]
_PRE_KNN = precedent["conditions"]["warm"]["arms"]["numeric_knn"]["agreement_at_k"]
_PRE_MARGIN = precedent["conditions"]["warm"]["comparisons"][
    "granite_text_vs_numeric_knn"
]
_INDEX_RECALL = precedent["vector_index"]["recall_at_k_against_exact_search"]
#: The shared answer key for the two grounding checkers. Read for its counts rather than
#: for its rows: the page says how much the parity test covers, not what it decided.
_GOLDEN = json.loads(
    (REPO / "apps" / "web" / "public" / "data" / "grounding_golden.json").read_text(
        encoding="utf-8"
    )
)
_LANGCHAIN = _receipt("LANGCHAIN_RECEIPT.json")
_LANGFLOW = _receipt("LANGFLOW_RECEIPT.json")
_WATSONX = _receipt("WATSONX_RECEIPT.json")


def _langflow_cell() -> str:
    """What the LangFlow row may say, taken from the run rather than from the file list.

    A flow file on disk is not a claim. What this cell reports is what came back when the
    committed JSON was loaded and executed, and the second flow's outcome is one of three
    words, so a machine with no model runtime produces a row that says so rather than a row
    that quietly drops it.
    """
    grounding = _LANGFLOW["flows"]["grounding"]
    verdicts = ", ".join(
        f"{run['label']} -> {run['verdict']}"
        f"{'/' + run['codes'][0] if run['codes'] else ''}"
        for run in grounding["runs"]
    )
    agent_flow = _LANGFLOW["flows"].get("granite_agent") or {}
    outcome = agent_flow.get("outcome", "absent")
    if outcome == "RAN":
        # "The graph executed" and "the model used the tools" are different claims, and
        # this run separates them: Granite emits its tool call as a `<tool_call>` text
        # block, LangFlow's agent node does not parse that as an invocation, and the answer
        # therefore carries no fact that only a tool could supply. The same model with the
        # same six handlers scores 22 of 24 through this project's own MCP harness. That is
        # a measurement about the client, not about the model, and it is published rather
        # than the row being written as though the agent answered.
        carried = agent_flow.get("answer_carries_the_tool_only_fact")
        tail = (
            f"A second flow binds the six tools to `{agent_flow['model']}` through "
            f"LangFlow's agent node and runs end to end. Its answer "
            + (
                f"carries observation {agent_flow.get('expected_observation_id')}, which is "
                f"reachable only through a tool call."
                if carried
                else (
                    f"does not carry observation "
                    f"{agent_flow.get('expected_observation_id')}, which is reachable only "
                    f"through a tool call: the model emits its call as a `<tool_call>` text "
                    f"block and the agent node does not execute it. The same model and the "
                    f"same six handlers score "
                    f"{_AGENT_TOOLS['correct']['successes']}/"
                    f"{_AGENT_TOOLS['correct']['trials']} through this project's MCP "
                    f"harness, so this is a measurement about the client rather than the "
                    f"model, and it is recorded rather than rounded up."
                )
            )
        )
    elif outcome == "NOT_CHECKED":
        tail = (
            f"A second flow binds the six tools to `{agent_flow.get('model')}` through "
            f"LangFlow's agent node; it is committed and was not executed here, because "
            f"{agent_flow.get('reason', 'the model runtime was unreachable')}."
        )
    else:
        tail = (
            f"A second flow binds the six tools to an agent node and its last run came "
            f"back {outcome}: {agent_flow.get('error_class', 'no class recorded')}."
        )
    return (
        f"Two flows, built from component objects, written out by LangFlow's own "
        f"`Graph.dump()`, then loaded back from those files and run. The grounding flow "
        f"needs no model and no network: {verdicts}. {tail} LangFlow "
        f"{_LANGFLOW['runtime']['langflow']} is not a dependency of this project. "
        f"`artifacts/LANGFLOW_RECEIPT.json`"
    )


def _watsonx_cell() -> str:
    """The watsonx row, and it is allowed to say that nothing ran."""
    attempt = _WATSONX["attempt"]
    outcome = attempt["outcome"]
    common = (
        f"`{_WATSONX['backend']['model_id']}`, one draft about observation "
        f"{_WATSONX['subject']['observation_id']}, put through the same grounding checker "
        f"that decides whether a local draft ships. "
    )
    if outcome == "RAN":
        return (
            common
            + f"The checker returned {attempt['checker']['verdict']}"
            + (f" {attempt['checker']['codes']}" if attempt["checker"]["codes"] else "")
            + ". `artifacts/WATSONX_RECEIPT.json`"
        )
    if outcome == "NOT_CHECKED":
        return (
            common
            + "**NOT_CHECKED in this checkout**: no `WATSONX_API_KEY` is set here, so "
            "nothing was sent and nothing is claimed. The receipt records the attempt "
            "with its date rather than omitting the row. `artifacts/WATSONX_RECEIPT.json`"
        )
    return (
        common
        + f"The last attempt came back {outcome}: {attempt.get('error_class')}. "
        "`artifacts/WATSONX_RECEIPT.json`"
    )


_AGENT_TOOLS = agent["arms"]["tools"]
_AGENT_CONTROL = agent["arms"]["control"]
_AGENT_PAIRED = agent["paired"]

# Bound after the agent aliases, because the LangFlow cell quotes the MCP harness's own
# score as the contrast that makes its finding readable.
_LANGFLOW_CELL = _langflow_cell()
_WATSONX_CELL = _watsonx_cell()

_AGENT_CONTROL_INVENTED = sum(
    1 for row in agent["per_run"] if row["arm"] == "control" and not row["grounded"]
)


gates = build_gate_summary(queue, fusion)
verdicts = [g["verdict"] for g in gates["gates"]]
N_GATES = gates["n_gates"]
N_MET = gates["n_met"]
N_INCONCLUSIVE = verdicts.count("NOT_ESTABLISHED")
N_OPEN = verdicts.count("OPEN")

N_COLD_SPLITS = sum(1 for name in splits["splits"] if name.startswith("cold"))

# The gate-6 threshold lives in the gate's own wording and nowhere else as a number, so it
# is read out of that sentence rather than typed. A wording change fails here loudly, which
# is the behaviour a typed 1.5 would not have.
_threshold = re.search(r"at least ([0-9.]+) times", queue["gate6"]["wording"])
if _threshold is None:
    raise SystemExit(
        "gate 6's wording no longer states its threshold as 'at least N times', so this "
        "page cannot quote it without typing it. Fix the pattern or the wording."
    )
G6_THRESHOLD = _threshold.group(1)

chronological = {s["split"]: s for s in fusion["splits"]}["chronological"]
shipped = chronological["arms"]["image_corridor"]
image_only = chronological["arms"]["image_only"]
g6 = queue["gate6"]["per_split"]["chronological"]
g6_lo, g6_hi = g6["lift_ci95"]
cold = queue["gate6"]["per_split"]["cold_station"]
cold_lo, cold_hi = cold["lift_ci95"]

counts = explain["counts"]
sens = explain["checker_sensitivity"]
freq = explain["hallucinated_downlink_frequency"]
within = explain["run_to_run_stability"]["within_process"]
across = explain["run_to_run_stability"]["across_processes"]
# An empty case list is the success condition for the unit and used to be an IndexError
# at import here, so the page died on the day nothing went wrong.
errors_khz = sorted(abs(c["error_khz"]) for c in freq["cases"])
FREQUENCY_FINDING = (
    f"In {freq['observations_affected']} of {freq['of_observations']} observations the model "
    f"wrote a downlink frequency in megahertz that was not this observation's, wrong by "
    f"{errors_khz[0]:.0f} kHz to {errors_khz[-1]:.0f} kHz. Each invented value lands within "
    f"five percent of that observation's real downlink, which is the finding's own "
    f"definition and also what makes it dangerous: the number looks like the number that "
    f"belongs there. No claim is made about the bands, because the receipt classifies none."
    if errors_khz
    else (
        f"In this run no draft wrote a frequency within five percent of an observation's own "
        f"downlink, over {freq['of_observations']} observations. Earlier runs of the same "
        f"prompt did, so the absence is a property of this freeze rather than of the model."
    )
)
model = explain["model"]

# The offline suite as a clean clone measured it, with the 4 GB snapshot hidden, which is
# the column a judge can actually reproduce. A count from the machine that wrote the code,
# with every cache warm, is the weaker of the two numbers.
_pytest = clone["suite_with_and_without_the_snapshot"]["without"] or {}
N_PASSED = _pytest.get("passed")
N_SKIPPED = _pytest.get("skipped")
N_FAILED = _pytest.get("failed")


def _failed_test_names() -> list[str]:
    """The node ids pytest printed, read back out of the step this row quotes.

    A row that prints passed and skipped and drops failed would be a summary that cannot
    report the one outcome a reader cares about most. The names come from the transcript's
    own output tail rather than from a list kept here, so a different failure renames itself.
    """
    for step in clone["steps"]:
        if step.get("step", "").startswith("offline test suite, snapshot HIDDEN"):
            return [
                line.split()[1]
                for line in step.get("output_tail", [])
                if line.startswith("FAILED ") and len(line.split()) > 1
            ]
    return []
CLONE_TOTAL = clone["summary"]["steps_run"]
CLONE_FAILED = len(clone["summary"]["steps_failed"])
CLONE_OK = CLONE_TOTAL - CLONE_FAILED
CLONE_COMMIT = clone["source_commit"][:7]
CLONE_FAILED_STEPS = ", ".join(clone["summary"]["steps_failed"])

# What the clone had to borrow, read from the transcript rather than described. A run that
# borrows an environment and a run that builds one are different claims, and this page said
# neither until a review pointed out that its headline implied the stronger of the two.

_PREREQ = clone["prerequisites_not_in_the_repository"]


def _prereq_named(fragment: str) -> dict | None:
    for row in _PREREQ:
        if fragment in row["prerequisite"]:
            return row
    return None


CLONE_ENV_CACHE = _prereq_named("uv cache")
CLONE_ENV_BORROWED = _prereq_named("prepared Python environment")
CLONE_NODE = _prereq_named("node_modules")
if (CLONE_ENV_CACHE is None) == (CLONE_ENV_BORROWED is None):
    raise SystemExit(
        "the clean-clone transcript names neither a built environment nor a borrowed one, or "
        f"it names both: {[row['prerequisite'] for row in _PREREQ]}. One of the two has to be "
        "true, and which one it is decides what this page is allowed to say."
    )
#: Where the clone's node_modules came from. Recorded as a block of its own since the check
#: started attempting `npm ci --offline` before falling back to a link, because on a success
#: there is no prerequisite row to read: nothing outside the repository was borrowed.
CLONE_NODE_SOURCE = clone.get("node_modules")
if CLONE_NODE is None and CLONE_NODE_SOURCE is None:
    raise SystemExit(
        "the clean-clone transcript does not record where apps/web/node_modules came from, so "
        "the page cannot disclose it."
    )

def _install_reason() -> str:
    """What the failed offline install actually tripped on, read out of its own output tail.

    "For the reason its own output tail gives" is true and asks the reader to go and get it.
    The reason is one line in a receipt this page already loads, and it changes what the
    failure means: a package whose wheel is not in the local cache is a cold-cache problem,
    and a resolution that cannot be satisfied at all is a different one.
    """
    for step in clone["steps"]:
        if not step.get("step", "").startswith("uv pip install"):
            continue
        tail = " ".join(step.get("output_tail", []))
        missing = re.search(r"Failed to download `([^`]+)`", tail)
        if missing:
            return (
                f", because the wheel for `{missing.group(1)}` is not in the local package "
                "cache and the run refuses the index"
            )
        if "unsatisfiable" in tail:
            return ", because the pinned set could not be resolved from the local cache alone"
        return ""
    return ""


_INSTALL_REASON = _install_reason() if CLONE_ENV_CACHE is None else ""

if CLONE_ENV_CACHE is not None:
    CLONE_ENV_SENTENCE = (
        "The clone built its own Python environment, inside itself, with the network refused, "
        "resolving the pinned set from a local package cache rather than from an index, so a "
        "judge with a cold cache needs one online install before this step reproduces. The "
        "transcript records which cache it read, because a run that resolves from a warm cache "
        "and a run that resolves from nothing are different claims."
    )
else:
    CLONE_ENV_SENTENCE = (
        f"The offline install into the clone did not succeed{_INSTALL_REASON}, so the suite "
        "ran on this machine's interpreter at "
        f"`{CLONE_ENV_BORROWED['python_version']}` against the clone's source tree. The code "
        "under test is the clone's and the environment is not, which is a weaker claim than a "
        "cold-start install and is stated here rather than left to be inferred."
    )

if N_PASSED is None or N_SKIPPED is None or N_FAILED is None:
    raise SystemExit(
        "the clean-clone transcript carries no parsed pytest count for the hidden-snapshot "
        f"pass ({_pytest}), so the number of tests cannot be quoted from it. Re-run "
        "scripts/clean_clone_check.py."
    )

# Failures are named first, before the passes, because that is the order a reader who is
# checking rather than skimming reads them in.
SUITE_RESULT = (
    f"{N_FAILED} failed, {N_PASSED} passed, {N_SKIPPED} skipped"
    if N_FAILED
    else f"{N_PASSED} passed, {N_SKIPPED} skipped, none failed"
)
_FAILED_NAMES = _failed_test_names()
if N_FAILED and not _FAILED_NAMES:
    raise SystemExit(
        f"the clean-clone transcript counts {N_FAILED} failed test(s) in the hidden-snapshot "
        "pass and its output tail names none of them, so this page cannot say which failed. "
        "Re-run scripts/clean_clone_check.py."
    )


_AUDIT_COMMITS = {
    "SECRET_SCAN.json": secrets["commit"],
    "ATTRIBUTION_AUDIT.json": attribution["commit"],
    "REPO_WEIGHT.json": weight["commit"],
}
if len(set(_AUDIT_COMMITS.values())) != 1:
    _seen = {name: value[:7] for name, value in _AUDIT_COMMITS.items()}
    raise SystemExit(
        f"the three release-audit receipts were measured at different commits ({_seen}), so no "
        "single commit can be named for their numbers. Re-run scripts/audit_release.py."
    )
AUDIT_COMMIT = secrets["commit"][:7]


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _clauses(parts: list[tuple[int, str]]) -> str:
    """Join the tally clauses that have a member, dropping the ones that do not.

    Written the day gate 4 was answered, when the sentence became "three came back
    inconclusive and none were never run". A template that always renders every category
    produces a double negative the moment a category empties, and the categories here empty
    as the work succeeds, which is exactly when nobody re-reads the sentence.
    """
    said = [text for count, text in parts if count]
    if not said:
        return "none produced a verdict"
    if len(said) == 1:
        return said[0]
    return f"{', '.join(said[:-1])} and {said[-1]}"


GATE_TALLY_CLAUSE = _clauses(
    [
        (N_MET, f'{N_MET} {_plural(N_MET, "was", "were")} met'),
        (N_INCONCLUSIVE, f"{N_INCONCLUSIVE} came back inconclusive"),
        (N_OPEN, f'{N_OPEN} {_plural(N_OPEN, "was", "were")} never run'),
    ]
)

def _table(rows: list[tuple[str, ...]]) -> str:
    return "\n".join("| " + " | ".join(cells) + " |" for cells in rows)


def _para(text: str, indent: str = "") -> str:
    """One paragraph, wrapped after interpolation.

    Wrapping in the template instead would go ragged the first time a receipt changed the
    width of a number, which is the same reason the README generator wraps its tally.
    """
    # break_on_hyphens=False, because the default split "cold-station" and "read-only"
    # across two lines, and markdown renders that as "cold- station".
    #
    # break_long_words=False for the same reason one step further out. A test node id is one
    # unbreakable token of 86 characters, and the default put a line break inside
    # `tests/test_receipt_digests.py::...`, which markdown renders as "tests/t
    # est_receipt_digests.py" and the page's own path check reads as a file that does not
    # exist. A token wider than the column overhangs it instead, which is the right trade for
    # a document whose tokens are paths.
    return textwrap.fill(
        " ".join(text.split()),
        width=90,
        initial_indent=indent,
        subsequent_indent=indent,
        break_on_hyphens=False,
        break_long_words=False,
    )


#: How many tools the specification records as built and as specified-and-not-built. Both
#: numbers are read out of the specification rather than typed, and the implemented count
#: is now the sum of two sections, because the project registers two MCP servers and the
#: specification has one section each. The evidence section is checked against the registry
#: this script already imports; the live registry is not imported here, because it needs
#: numpy and scipy and this generator runs inside the offline gate.
#: `tests/test_mcp_server.py` checks the live section against the live registry.
_SPEC = (REPO / ".bob" / "TOOL_SPECS.md").read_text(encoding="utf-8")
_SPEC_SECTIONS: dict[str, list[str]] = {}
_heading = None
for _line in _SPEC.splitlines():
    if _line.startswith("## "):
        _heading = _line[3:].strip()
        _SPEC_SECTIONS[_heading] = []
    elif _line.startswith("### ") and _heading is not None:
        _SPEC_SECTIONS[_heading].extend(re.findall(r"`([^`]+)`", _line))
# `Resources` is a subsection of the evidence server, and it names URIs, not tools.
_SPEC_EVIDENCE = set(
    _SPEC_SECTIONS.get("Implemented: `tracetriage-evidence`", [])
) - {"Resources"}
_SPEC_LIVE = set(_SPEC_SECTIONS.get("Implemented: `tracetriage-live`", []))
N_TOOLS_BUILT = len(_SPEC_EVIDENCE) + len(_SPEC_LIVE)
N_TOOLS_UNBUILT = len(set(_SPEC_SECTIONS.get("Specified and not implemented", [])))
if set(TOOL_NAMES) != _SPEC_EVIDENCE:
    raise SystemExit(
        f".bob/TOOL_SPECS.md documents {sorted(_SPEC_EVIDENCE)} for the evidence server "
        f"and it advertises {TOOL_NAMES}. tests/test_mcp_server.py says which."
    )
if not _SPEC_LIVE:
    raise SystemExit(
        ".bob/TOOL_SPECS.md has no `Implemented: `tracetriage-live`` section, so this "
        "page would report the tool count of one server as the count of both."
    )


CHECKS: list[tuple[str, ...]] = [
    # First, and it is the cheapest thing on this page. One command, no model runtime, no
    # GPU, no network, and it prints a real generated sentence next to the refusal it
    # earned. Granite was the strongest AI component here and the hardest one to see: every
    # other subsystem had a command, and the drafts and their verdicts lived in a receipt
    # and on the console, so "show me the model doing something" meant reading JSON.
    (
        "Show me the model doing something",
        "`tracetriage note 14746092`",
        f"The draft `{model['name']}` wrote, the checker's verdict on it, the number it "
        f"invented, and the template that shipped instead. Offline, no model needed: the "
        f"drafts are frozen and the receipt records what the checker decided about each",
    ),
    (
        "Do the tests pass offline?",
        '`pytest -m "not network and not ocr and not llm" -q`',
        # The commit is in the cell rather than only in the prose below the table. A table
        # row is read on its own, and a count of passing tests with no commit beside it
        # reads as a statement about whatever the reader is looking at.
        f"{SUITE_RESULT}, measured in a clean clone of `{CLONE_COMMIT}` with every "
        f"non-loopback socket refused",
    ),
    (
        "Do the tools change what the agent gets right?",
        "`python scripts/run_agent_study.py`",
        f"{_AGENT_TOOLS['correct']['successes']}/{_AGENT_TOOLS['correct']['trials']} with tools "
        f"against {_AGENT_CONTROL['correct']['successes']}/"
        f"{_AGENT_CONTROL['correct']['trials']} without, paired p = "
        f"{_AGENT_PAIRED['exact_p_one_sided']}",
    ),
    (
        "Does the model's own output survive the checker?",
        "`python scripts/run_explanations.py`",
        f"{counts['emitted']} emitted, {counts['refused']} refused, "
        f"{sens['caught_for_the_expected_reason']}/{sens['adversarial_checks']} "
        f"adversarial checks caught, {sens['control_refused']}/{sens['control_checks']} "
        f"clean checks refused",
    ),
    (
        "Can an agent measure something new?",
        "`live_triage_observation` over MCP, or `tracetriage triage <id>`",
        "A measurement of an observation recorded today, from the public SatNOGS API with "
        "no credential, and `live_check_claim` refuses an invented frequency about that "
        "measurement. `docs/BOB_DEMO.md` is the prompt",
    ),
    (
        "Can an agent query the evidence?",
        "`python scripts/mcp_server.py` on stdio",
        f"An MCP handshake, {len(TOOL_NAMES)} tools over committed receipts and "
        f"{len(RESOURCE_URIS)} receipt resources. One tool is the grounding checker",
    ),
    (
        "Does the repository hold together?",
        "`python scripts/gate.py`",
        "The standing gates, one line each",
    ),
]

# The heading counted four while the table carried five, which is the same class of defect
# as a typed number anywhere else here: it stayed right until a row was added.
_NUMBER_WORDS = {
    3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine",
}
N_CHECKS_WORD = _NUMBER_WORDS.get(len(CHECKS), str(len(CHECKS)))

# The heading was fixed and the sentence under the table was not: it said "none of the five"
# while the heading said seven. The count is derived now. The other number in that sentence
# was "the two that name a model", and it is gone rather than derived: which commands can
# reach a model is a property of the scripts, not of the words in the table, so counting
# text would have been a check that agrees with itself. The scripts are named instead, and
# test_for_judges.py already asserts every path this page cites exists and is published.
N_CHECKS_LOWER = N_CHECKS_WORD.lower()

REQUIREMENTS: list[tuple[str, ...]] = [
    ("Problem statement", "`README.md`, first section"),
    ("Solution description", "`README.md`, and the console at the URL in it"),
    (
        "AI approach and architecture",
        "`README.md` architecture section, `pipeline/tracetriage/explain.py`, "
        "`pipeline/tracetriage/granite.py`",
    ),
    (
        "Selected challenge theme",
        "Space exploration. `README.md` states it, and "
        "`artifacts/DATASET_MANIFEST.json` records the snapshot it was built from",
    ),
    (
        "How IBM Bob was used",
        "`docs/BOB_BUILD_LOG.md`, one entry per unit, and `.bob/rules.md` for the "
        "standing rules Bob worked to",
    ),
    (
        "Working prototype",
        "The static console under `apps/web`, deployed from this repository",
    ),
    (
        "Demo or presentation video",
        "`docs/DEMO_SCRIPT.md` is the shot list for the recorded walkthrough, generated "
        "from the receipts so no spoken number can drift from what the console shows. "
        f"`presentation/out/tracetriage-film.mp4` is a rendered {_FILM['seconds']:g} "
        f"second silent film over the same receipts: {_FILM['beats']} cards, {_FILM['frames']} "
        f"frames, and {_FILM_CLAIMS['total']} figures each resolved from a receipt key "
        f"path at build time rather than typed. `artifacts/FILM_RECEIPT.json` records its "
        "digest and `scripts/check_receipt_digests.py`, a standing gate, checks the "
        "committed bytes against it",
    ),
    ("Public repository", "This one"),
]


# The tally, with what the met gates actually were.
#
# This page said "2 were met" and stopped. A judge-seat review named it as the one place
# the submission rounds up: both met gates are PRE_PASSED feasibility checks about dataset
# size and metadata coverage, answered before the first line of pipeline code, and README
# says so plainly two screens away. The page written for judges was the softer one.
_N_PRE_PASSED = sum(1 for g in gates["gates"] if g["verdict"] == "PRE_PASSED")
_N_SUBSTANTIVE = N_GATES - _N_PRE_PASSED
# Which of the met gates are feasibility checks and which are substantive. The distinction
# is the whole honesty of the tally: two of the six were answered before any pipeline code
# existed and counting them alongside a measured pass would inflate the headline. It is
# computed rather than asserted, because it changed the day gate 4 was answered and the
# sentence that asserted it would have gone on saying none passed.
_SUBSTANTIVE_PASSES = sorted(
    g["gate"] for g in gates["gates"] if g["verdict"] == "PASSED"
)


def _met_clause() -> str:
    if not N_MET:
        return "and none of them was"
    if _N_PRE_PASSED == N_MET:
        return (
            f"and the {N_MET} that {_plural(N_MET, 'was', 'were')} met "
            f"{_plural(N_MET, 'is', 'are')} {_plural(N_MET, 'a', 'the')} PRE_PASSED "
            f"feasibility {_plural(N_MET, 'check', 'checks')} answered before any pipeline "
            f"code was written, so of the {_N_SUBSTANTIVE} gates that ask whether the idea "
            f"works, none passed on the split that decides it"
        )
    if not _SUBSTANTIVE_PASSES:
        return "and the receipts name which"
    named = " and ".join(f"gate {n}" for n in _SUBSTANTIVE_PASSES)
    return (
        f"and the split matters: {_N_PRE_PASSED} of the {N_MET} "
        f"{_plural(_N_PRE_PASSED, 'is', 'are')} "
        f"{_plural(_N_PRE_PASSED, 'a', 'the')} PRE_PASSED feasibility "
        f"{_plural(_N_PRE_PASSED, 'check', 'checks')} answered before any pipeline code "
        f"was written, and {len(_SUBSTANTIVE_PASSES)} "
        f"{_plural(len(_SUBSTANTIVE_PASSES), 'is', 'are')} a substantive gate that cleared "
        f"its threshold on the sample it was pre-registered on, {named}. So of the "
        f"{_N_SUBSTANTIVE} gates that ask whether the idea works, "
        f"{len(_SUBSTANTIVE_PASSES)} passed and the rest are reported as they came back"
    )


_MET_CLAUSE = _met_clause()

# Established first, then the gate tally. The reason, in one line: this paragraph used to
# be the third thing on the page and it ended on "none passed", so a judge met four
# inconclusive verdicts before meeting a single measured result. Four blind internal seats
# scored the entry 15.5 of 20 on that reading. No count below moved; the order did, and the
# gate tally is still in this paragraph with the same words it had.
_ESTABLISHED = _para(
    f"""**What was measured and holds, before what did not.** The evidence tools change what
    a local IBM Granite model gets right: {_AGENT_TOOLS["correct"]["successes"]} of
    {_AGENT_TOOLS["correct"]["trials"]} against {_AGENT_CONTROL["correct"]["successes"]} of
    {_AGENT_CONTROL["correct"]["trials"]} with no tools, paired exact one-sided p of
    {_AGENT_PAIRED["exact_p_one_sided"]}. The grounding checker caught
    {sens["caught_for_the_expected_reason"]} of {sens["adversarial_checks"]} planted
    falsehoods and refused {sens["control_refused"]} of {sens["control_checks"]} drafts
    that break no rule, which is the half that makes the first number mean anything. And on
    stations the model never trained on, the review queue finds
    {cold["lift_point"]:.3f} times as many actionable conflicts as random ordering at the same
    budget, interval [{cold_lo:.3f}, {cold_hi:.3f}], clear of its threshold. None of
    those three needed a gate to come back a particular way."""
)

INTRO = _para(
    f"""This page is a map, not a summary. Each claim below names the file that carries the
    evidence and, where it can, the command that regenerates it. The gates it reports are a
    research bar rather than a feature list: a gate is met only when a 95% interval clears
    its threshold, so a point estimate above the bar whose interval straddles it is
    published as a failure. Of the {N_GATES} kill gates declared before the build,
    {GATE_TALLY_CLAUSE}. That tally is read from the receipts
    by the console rather than typed here, {_MET_CLAUSE}. Why the intervals are that wide is
    derived rather than pleaded: on the split gate 6 was pre-registered on, a perfect oracle
    caps at {_CIRC_CEIL["lift"]:.3f} times random against a threshold of 1.5, so the whole
    room any ordering had to win in was
    {_CIRC_CEIL["headroom_between_threshold_and_perfection"]:.3f} wide."""
)

_FAILED_CLAUSE = "" if not CLONE_FAILED else f". What did not: {CLONE_FAILED_STEPS}"

AGENT_PARA = _para(
    f"""The agent layer is measured against a control rather than demonstrated.
    `scripts/run_agent_study.py` puts {agent["tasks"]} questions to the same local model twice,
    once with the five MCP tools available over stdio JSON-RPC and once with no tools at all,
    and grades both against ground truth derived from the files the console ships. With the
    tools: {_AGENT_TOOLS["correct"]["successes"]} of {_AGENT_TOOLS["correct"]["trials"]}
    correct, 95% interval [{_AGENT_TOOLS["correct"]["lower_95"]},
    {_AGENT_TOOLS["correct"]["upper_95"]}], and every number in every answer appeared in
    something the agent had read. Without them: {_AGENT_CONTROL["correct"]["successes"]} of
    {_AGENT_CONTROL["correct"]["trials"]}, with {_AGENT_CONTROL["declined_unknown"]} questions
    declined as unknown and {_AGENT_CONTROL_INVENTED} answers carrying a number nothing
    supported. Of the
    {_AGENT_PAIRED["discordant_pairs"]} questions the arms disagreed on, the tool arm was right
    on {len(_AGENT_PAIRED["tools_only"])}: an exact one-sided p of
    {_AGENT_PAIRED["exact_p_one_sided"]}. Before any model was graded, each question was proved
    answerable in a single tool call, because a question the tools cannot serve would otherwise
    be scored as a failure of the policy."""
)

# What the receipt says, in the receipt's own terms. This used to be two sentences
# asserting that nobody had filled the form in, which is true of exactly one of the four
# verdicts the receipt can carry, on a page whose whole claim is that it is generated
# from the receipts. A verdict this has no wording for stops the sync.
def _gate_power() -> str:
    """The account a reader is owed for every gate that did not come back met.

    A submission with four unmet gates and no measured account of why is indistinguishable
    from one that did not try. This is generated from ``artifacts/GATE_POWER_RECEIPT.json``,
    and ``scripts/run_gate_power.py`` refuses to write that receipt while any unmet gate has
    no named constraint, so a row cannot go quietly missing from this section: the gate that
    produces it fails first.
    """
    power = _receipt("GATE_POWER_RECEIPT.json")
    unmet = [g for g in power["gates"] if not g["met"]]
    if not unmet:
        return _para(
            "Every gate is met. This section used to explain what was outstanding and there "
            "is nothing outstanding, so it is empty rather than kept as decoration."
        )

    exact = sum(1 for g in unmet if g["closure"]["kind"] == "exact")
    out = [
        _para(
            f"{len(unmet)} of the {power['n_gates']} gates did not come back met, and none "
            f"of them is left as a bare verdict. Each carries what actually bound the "
            f"measurement and the condition that would move it, computed from the same "
            f"receipts that decided the verdicts. {exact} of the {len(unmet)} closure "
            f"conditions are exact arithmetic; the rest are projections and are labelled as "
            f"such. Regenerate the lot with "
            f"`.venv/Scripts/python.exe scripts/run_gate_power.py --check`."
        ),
        "",
        _table(
            [
                ("Gate", "Verdict", "What bound it", "What would close it"),
                ("---", "---", "---", "---"),
            ]
            + [
                (
                    str(g["gate"]),
                    f"`{g['verdict']}`",
                    " ".join(g["bound_by_in_one_line"].split()),
                    " ".join(g["closure"]["statement"].split())
                    + ("" if g["closure"]["kind"] == "exact" else " *(projected)*"),
                )
                for g in unmet
            ]
        ),
    ]

    room = next((g for g in power["gates"] if g["gate"] == 6 and "the_room_rule" in g), None)
    if room:
        rule = room["the_room_rule"]
        splits = [s for s in rule["per_split"] if s["measurable"]]
        truncated = rule["splits_whose_interval_is_truncated_by_the_ceiling"]
        out += [
            "",
            _para(
                "**The one finding in this section.** Gate 6's verdict is predicted by the "
                "split it was taken on rather than by the queue. A split's *room* is the "
                "distance between the threshold and the best score any ordering could reach "
                "there, a perfect oracle included. Whether the published interval fits "
                f"inside that room predicts the verdict on {len(splits)} of {len(splits)} "
                "measurable splits, with no exceptions."
            ),
            "",
            _table(
                [
                    (
                        "Split",
                        "Observations",
                        "Oracle ceiling",
                        "Room above 1.5x",
                        "Interval width",
                        "Fits",
                        "Verdict",
                    ),
                    ("---", "---:", "---:", "---:", "---:", ":---:", "---"),
                ]
                + [
                    (
                        f"`{s['split']}`",
                        str(s["n_population"]),
                        f"{s['ceiling']:.3f}",
                        f"{s['room_above_the_threshold']:.3f}",
                        f"{s['interval_width']:.3f}",
                        "yes" if s["interval_fits_in_the_room"] else "no",
                        f"`{s['verdict']}`",
                    )
                    for s in splits
                ]
            ),
            "",
            _para(
                f"On {_and_list(truncated)} the interval's upper bound **is** the ceiling. No "
                f"resampling of those splits can return a number above it, however good the "
                f"ranking is, so the interval there is reporting the arithmetic of the split "
                f"rather than the quality of the ordering. The single split with room to "
                f"spare is the single split that passed. That is why the cold-station result "
                f"is published beside the pre-registered one and never instead of it."
            ),
            "",
            _para(
                "The obvious next thought does not follow, and the counterexample is in this "
                "corpus: `cold_transmitter` holds more observations than `chronological` and "
                "still fails, because its interval came back wider too. So no required sample "
                "size is published for gate 6, only the condition."
            ),
            "",
            _para(
                "Gates 5 and 6 have one closure condition in common and this project will not "
                "take it. Both are short of test rows, and both were fixed before their "
                "results were read. Growing a test set after seeing its verdict is precisely "
                "what pre-registration exists to prevent, so the shortfall is recorded as the "
                "reason those gates stay open rather than as work outstanding."
            ),
        ]
    return "\n".join(out)


def _and_list(names: list[str]) -> str:
    """`a`, `b` and `c`. Two items joined by a comma read as one name with a typo."""
    quoted = [f"`{n}`" for n in names]
    if len(quoted) <= 1:
        return "".join(quoted)
    return f"{', '.join(quoted[:-1])} and {quoted[-1]}"


def _gate4_state(receipt: dict) -> str:
    verdict = receipt.get("verdict")
    arm = receipt.get("arm")
    if verdict == "NOT_RUN" and arm:
        # NOT_RUN with an arm in it is the third state: a review exists and its reviewer is
        # not a person, so it cannot answer a gate titled human decidability. Saying "nobody
        # has filled the form in" here would be the page lying about its own receipt.
        reviewer = arm["reviewer"]
        return (
            f"`artifacts/GATE4_RECEIPT.json` says `NOT_RUN`, and that is about the reviewer "
            f"rather than about the form. The worksheet has been answered end to end and the "
            f"numbers are in the receipt under `arm`: {arm['decisive']} of "
            f"{arm['observations_scored']} first-occurrence observations were decidable, a "
            f"rate of {arm['rate']:.3f}, 95% "
            f"[{arm['rate_lower_bound_95']:.3f}, {arm['rate_upper_bound_95']:.3f}]. The "
            f"reviewer was {reviewer['identity']} That is not a person, so it does not meet "
            f"the gate as written and the gate stays OPEN. What it does establish is that the "
            f"sample as committed supports a decisive judgment on the published instrument "
            f"with every label hidden, which is a different claim and a smaller one."
        )
    if verdict == "NOT_RUN":
        return (
            "`artifacts/GATE4_RECEIPT.json` currently says `NOT_RUN`, with no rate in it, "
            "because nobody has filled the form in. That is a person's afternoon rather "
            "than a code change, and it is reported as OPEN rather than estimated."
        )
    rate = receipt.get("rate")
    lower = receipt.get("rate_lower_bound_95")
    upper = receipt.get("rate_upper_bound_95")
    decisive = receipt.get("decisive")
    scored = receipt.get("observations_scored")
    span = ""
    if lower is not None and upper is not None:
        span = f", 95% [{lower:.3f}, {upper:.3f}]"
    measured = (
        f"`artifacts/GATE4_RECEIPT.json` says `{verdict}`: {decisive} of {scored} "
        f"first-occurrence observations were decidable, a rate of {rate:.3f}{span}"
    )
    if verdict == "PASSED":
        return (
            f"{measured}, and the whole interval clears the threshold. What the gate does "
            f"not establish is anything about a second reader: one person's judgment is "
            f"one person's judgment, and the instrument is reproducible from its seed so "
            f"that a second reader can be run rather than argued about."
        )
    if verdict == "FAILED":
        return (
            f"{measured}, and the whole interval sits under the threshold. The "
            f"pre-registration says what that means and it is not a model result: "
            f"`docs/KILL_GATE.md` reads \"if below 80%, the labelling protocol is the "
            f"problem, not the model\"."
        )
    if verdict == "NOT_ESTABLISHED":
        return (
            f"{measured}, so the interval spans the threshold and the gate is not met. "
            f"The point estimate and the bound are both published rather than the "
            f"friendlier of the two."
        )
    raise SystemExit(
        f"artifacts/GATE4_RECEIPT.json carries verdict {verdict!r} and this page has no "
        f"wording for it. A verdict nobody wrote a sentence for has to stop the sync."
    )


_GATE4_STATE = _gate4_state(gate4)

GATE4_PARA = _para(
    f"""What has not been measured is whether a reviewer reads a generated note faster or
    better than the numbers alone. That is kill gate 4. The instrument for it exists now:
    `scripts/build_gate4_worksheet.py` builds a blinded bundle of
    {gate4["worksheet"]["items"]} items over {gate4["worksheet"]["unique_observations"]}
    observations, {gate4["worksheet"]["repeated_observations"]} of them repeated under a second
    item id so intra-rater agreement falls out of the answers, and it commits one salted
    sha256 per item so the sample provably predates the review. `scripts/score_gate4.py`
    scores the filled form against a {gate4["threshold"]:.2f} threshold using the same exact
    bounds gate 3 reads. {_GATE4_STATE}"""
)

GATE4_HANDOFF_PARA = _para(
    f"""**What it takes to close it, exactly.** The protocol and the review page are
    committed at `apps/web/public/gate4/worksheet.md` and
    `apps/web/public/gate4/review.html`, which the console serves at /gate4/worksheet.md
    and /gate4/review.html, and its evaluation page carries the same handoff. The
    {gate4_bundle["images"]["n"]} plates are not published:
    {gate4_bundle["images"]["bytes"] / 1e6:.0f} MB of full-resolution waterfalls, and every
    way of shrinking them changes what the reviewer is being asked to judge, so they travel
    as one file. `scripts/pack_gate4_bundle.py` re-hashed every image on disk, recomputed
    all {gate4_bundle["commitments_checked"]} commitments against
    `artifacts/GATE4_WORKSHEET.json`, and wrote
    `{gate4_bundle["archive"]["name"]}`: {gate4_bundle["archive"]["bytes"]:,} bytes, sha256
    `{gate4_bundle["archive"]["sha256"][:24]}`. A reviewer checks what arrives against that
    digest, opens the page, answers {gate4_bundle["n_items"]} items and returns one CSV.
    Nothing else is missing, and until that CSV exists the verdict stays as the receipt
    reports it."""
)

SUITE_FAILURE_PARA = (
    _para(
        f"""The first row prints a failure, and it is named here rather than left in the
        transcript: {", ".join(f"`{name}`" for name in _FAILED_NAMES)}. The transcript is the
        record of commit `{CLONE_COMMIT}` and of nothing later, so what this page can honestly
        say about the current tip is only that the command in the table is the way to see it.
        A run of that command on a fresh clone of this commit reproduces the count exactly."""
    )
    if N_FAILED
    else _para(
        """No test failed in that run. The count is published with its zero rather than as a
        pass, because a summary that prints only what went right cannot be read as a summary of
        what happened."""
    )
)

CLONE_PARA = _para(
    f"""The full clean-clone reproduction is `artifacts/CLEAN_CLONE_TRANSCRIPT.json`, taken
    from a fresh clone of commit `{CLONE_COMMIT}` with every non-loopback socket refused:
    {CLONE_OK} of {CLONE_TOTAL} steps succeeded{_FAILED_CLAUSE}. The transcript carries each
    step's exit code and the tail of its output, so the reason is readable rather than
    summarised. The test counts above are from the pass with the snapshot directory hidden,
    which is a judge's case rather than this machine's, and they are the count at that commit
    rather than at the tip of the branch."""
)

_LOCK_DIGEST = (CLONE_NODE_SOURCE or CLONE_NODE)["package_lock_sha256"][:12]

if CLONE_NODE is None:
    _NODE_SENTENCE = (
        "And `apps/web/node_modules` was installed into the clone by `npm ci --offline`, "
        "which builds the locked tree out of npm's own cache without reaching the registry, "
        f"against the lockfile whose sha256 is `{_LOCK_DIGEST}`. A judge whose npm cache is "
        "cold needs one online install before that step reproduces, in the same way the "
        "Python side does."
    )
else:
    _NODE_SENTENCE = (
        "And `apps/web/node_modules` was linked from the source clone rather than installed, "
        "because the offline `npm ci` did not succeed here; the transcript records the "
        f"lockfile's sha256 (`{_LOCK_DIGEST}`) so a reader can check that the borrowed tree "
        "belongs to this repository's pins."
    )

CLONE_LIMITS = _para(
    f"""Two things about that run are worth knowing before it is trusted.
    {CLONE_ENV_SENTENCE} {_NODE_SENTENCE} The socket refusal itself
    is a Python-level patch loaded through `PYTHONPATH`, so it reaches every Python child
    process and constrains nothing else: the Node steps are outside it, and that is a limit of
    the guard rather than a claim about them."""
)

# The build log's entry count, read rather than typed.
#
# The criterion this page's Technical Execution section is scored against begins "Effective
# use of IBM Bob", and that section said nothing about Bob: the evidence was in a separate
# section 100 lines below it, so a judge scoring the criterion read past the answer. The
# count comes from the file because an entry count that is typed is the first thing to go
# stale, and this file gains an entry per accepted unit.
#: A dated unit heading in the build log: a date, the actor, and a unit id.
#:
#: The count this replaces was ``line.startswith("## ")`` minus two structural titles,
#: which is a markdown accident rather than a measurement. It counted "## A3. Doppler
#: correction status resolver" and "## Operator-side hardening", which are undated
#: section titles, and it missed every unit written at "### " depth, which is where the
#: Bob-account units actually live. The number it produced, 60, was neither the number
#: of Bob units nor the number of units: it was the number of second-level headings.
#: Quoting it under "Best Technical Use of IBM Bob" put a heading-level artefact in the
#: one place a judge is asked to score how the tool was used.
_BUILD_LOG_UNIT_RE = re.compile(
    r"^#{2,3}\s+"
    r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w{3,9}\s+\d{4})"  # 2026-08-17 or 17 Aug 2026
    r"\s+IST\s*\|\s*(?P<actor>[^|]+?)\s*\|\s*(?P<unit>[A-Za-z]+\d[\w.-]*)"
)

#: The actor slot when the work ran inside IBM Bob, which is "Account 1" to "Account 3".
#: Anything else in that slot is operator-side: "Operator side, no Bob account",
#: "operator", or a review wave run from Cursor or Claude Code. The distinction is the
#: whole point of the field, and collapsing it would credit Bob with diffs it did not
#: author.
_BOB_ACCOUNT_RE = re.compile(r"^account\s+\d+$", re.I)


def _build_log_units() -> tuple[list[str], list[str]]:
    """The dated units in the build log, split by whether Bob authored them.

    Returns two lists of unit ids. Both are printed: a Bob-primary claim that hides the
    operator-side waves is the same defect in the other direction, and a judge who
    counts the headings themselves must arrive at these two numbers.
    """
    bob: list[str] = []
    operator: list[str] = []
    for line in (
        (REPO / "docs/BOB_BUILD_LOG.md").read_text(encoding="utf-8").splitlines()
    ):
        match = _BUILD_LOG_UNIT_RE.match(line)
        if not match:
            continue
        unit = match.group("unit")
        if _BOB_ACCOUNT_RE.match(match.group("actor").strip()):
            bob.append(unit)
        else:
            operator.append(unit)
    return bob, operator


_BOB_UNITS, _OPERATOR_UNITS = _build_log_units()
N_BUILD_LOG_ENTRIES = len(_BOB_UNITS)
N_OPERATOR_UNITS = len(_OPERATOR_UNITS)
_BOB_UNIT_LIST = ", ".join(_BOB_UNITS)

#: What the old counter reported, kept so the correction is stated rather than quietly
#: applied. A number that moves from 60 to 10 with no explanation reads as a retreat; the
#: same number with its cause reads as a fix.
#:
#: Frozen, and that is the whole point of it. This was a live count of `## ` headings in
#: docs/BOB_BUILD_LOG.md, which is exactly the wrong thing to recompute: the sentence it
#: feeds says the number "used to be" this, and a value that grows with every appended
#: entry is not what it used to be. The published figure had already drifted to 66 and
#: then to 67, neither of which was ever reported as a unit count. A historical value in a
#: generated document has to be a literal, or the document rewrites its own past every
#: time something unrelated is added to the tree.
_OLD_HEADING_COUNT = 60

BOB_TECHNICAL = _para(
    f"""IBM Bob built the load-bearing pipeline, and the log names which units those were
    rather than asserting a total. `docs/BOB_BUILD_LOG.md` carries
    {N_BUILD_LOG_ENTRIES} dated Bob-account units, {_BOB_UNIT_LIST}: the data contracts,
    the immutable snapshot, the waterfall artifact parser, the physics corridor, label
    provenance, the image-only baselines, the end-to-end triage slice, the grouped splits
    with their leakage audit, and the review-value queue with kill gate 6. Each names the
    files it changed, the commands that were run, the Bob task id and what failed before it
    was accepted. A further {N_OPERATOR_UNITS} dated units in the same file are
    operator-side, run from Cursor and Claude Code, and are labelled that way in the actor
    field of their own headings: the console, the calibration and abstention blocks, the
    fusion ladder and the review waves are theirs, not Bob's. That distinction is published
    because the number here used to be {_OLD_HEADING_COUNT}, which was the count of
    second-level markdown headings in the file and not the count of anything anyone did.
    Bob also operates the product: `.bob/mcp.json` registers the evidence server and the
    live measurement server, so a Bob session can measure a pass recorded today and have
    the same grounding checker refuse a sentence about it.
    `.bob/rules.md`, `.bob/TOOL_SPECS.md` and `.bob/mcp.json` are the standing instructions,
    tool contracts and MCP registration each task ran under, tracked so the conditions of
    the work are readable and not only its output. `docs/PRE_BUILD_BASELINE.md` records what
    existed before the first Bob task, so the line between scaffolding and built work is
    auditable rather than asserted."""
)

TECHNICAL = _para(
    f"""The pipeline is measured rather than demonstrated.
    {dataset["counts"]["observations_stored"]} observations from snapshot
    `{dataset["snapshot_id"]}`, {len(splits["splits"])} splits of which {N_COLD_SPLITS} hold
    out stations or transmitters the model never saw, and a fusion arm ladder that reports
    what each stage of evidence adds: Brier {shipped["brier"]:.4f} and AUC
    {shipped["auc"]:.3f} for the shipped arm against {image_only["brier"]:.4f} and
    {image_only["auc"]:.3f} for image evidence alone, in
    `artifacts/FUSION_RECEIPT.json`."""
)

INNOVATION_ONE = _para(
    f"""The interesting part is not that a model writes the note. It is that the note is
    refused. A closed evidence packet of the observation's own fields goes in, and a checker
    requires every numeric token in the draft to be one of the packet's own printed tokens,
    or to equal a packet value at the precision it was printed to, under three unit
    conversions each of which has to carry the unit it produces. {counts["refused"]} of
    {counts["decided_by_the_checker"]} drafts the checker decided on were refused and the
    deterministic template shipped in their place, with the refusal codes on the card."""
)

INNOVATION_TWO = _para(
    f"""{FREQUENCY_FINDING} `artifacts/EXPLAIN_RECEIPT.json` lists each case with the value
    written and the value measured."""
)

INNOVATION_THREE = _para(
    f"""The checker is measured in both directions, because a checker that refuses everything
    catches every adversarial draft and is worthless:
    {sens["caught_for_the_expected_reason"]} of {sens["adversarial_checks"]} adversarial
    checks were refused for the reason they were built to trip, and {sens["control_refused"]}
    of {sens["control_checks"]} clean checks were refused. A check is one draft against one
    observation's packet, so that is {sens["adversarial_drafts_per_observation"]} adversarial
    drafts and {sens["control_drafts_per_observation"]} clean ones against each of
    {sens["observations_measured"]} packets."""
)

CHALLENGE_FIT = _para(
    f"""Space exploration, and specifically the part of it that is unglamorous: a volunteer
    ground station network produces more recordings than anyone can look at, and the labels
    that exist were made by people spending attention. The queue is an attention budget of
    {queue["review_budget"]["n_observations"]} observations, and the physics is not
    decoration. `artifacts/PHYSICS_VALIDATION.json` and
    `scripts/a3_doppler_investigation.py` settle which Doppler corridor model matches the
    recorded waterfalls, with both hypotheses drawn on the same image so a wrong constant is
    visible instead of hidden."""
)

LICENCE = _para(
    f"""The data licence is honoured rather than mentioned:
    `artifacts/ATTRIBUTION_AUDIT.json` checks every one of the
    {attribution["counts"]["media_files_tracked"]} tracked media files for attribution and
    reports {attribution["counts"]["incomplete"]} incomplete."""
)

FEASIBILITY_ONE = _para(
    f"""Nothing here needs a paid service or a hosted model. The reviewer note is written by
    `{model["name"]}` at {model["quantization"]}, {model["parameter_size"]} parameters,
    running locally, and the notes are frozen into a committed fixture so the publisher needs
    no model and no network at all. The MCP server imports nothing outside the standard
    library and is tested with site-packages switched off."""
)

FEASIBILITY_TWO = _para(
    f"""The repository is {weight["tracked_megabytes"]} MB across {weight["tracked_files"]}
    tracked files as of commit `{AUDIT_COMMIT}`, `artifacts/SECRET_SCAN.json` reports
    {secrets["n_findings"]}
    credential-shaped {_plural(secrets["n_findings"], "value", "values")} across the history
    it scanned, and the console is a static export, so hosting it costs nothing."""
)

IMPACT = _para(
    f"""The honest claim is narrow. The queue's lift over random selection on the primary
    chronological split is {g6["lift_point"]:.3f}x with a 95% interval of [{g6_lo:.3f},
    {g6_hi:.3f}], which is above the {G6_THRESHOLD}x threshold as a point estimate and does
    not exclude it, so `artifacts/QUEUE_RECEIPT.json` records {queue["gate6"]["verdict"]}
    rather than a pass. On the cold-station split, where a reviewer meets ground stations the
    model never trained on, the lift is {cold["lift_point"]:.3f}x with an interval of
    [{cold_lo:.3f}, {cold_hi:.3f}], which does clear it."""
)

GATE4_BULLET = (
    _para(
        """- **No person has read the blinded worksheet.** The worksheet has been answered
        and `artifacts/GATE4_RECEIPT.json` carries the numbers under `arm`, but the reviewer
        was a model rather than a person, and this gate is titled blinded *human*
        decidability. So its verdict stays `NOT_RUN`: the arm establishes that the committed
        sample supports a decisive judgment on this instrument with the labels hidden, and it
        cannot establish the thing the gate asks. The bundle is reproducible from its seed,
        so the human arm is a thing that can be run rather than a thing to argue about."""
    )
    if gate4.get("verdict") == "NOT_RUN" and gate4.get("arm")
    else _para(
        """- **Nobody has read the blinded worksheet yet.** `artifacts/GATE4_RECEIPT.json`
        says `NOT_RUN`, which is a fourth outcome beside passed, failed and inconclusive,
        and it carries no rate because there is nothing to compute one from."""
    )
    if gate4.get("verdict") == "NOT_RUN"
    else _para(
        """- **One reader is not a protocol.** The blinded worksheet has been read and
        `artifacts/GATE4_RECEIPT.json` carries the result, but by one reviewer in one
        sitting. The pre-registration asks for the repeated items to be relabelled after a
        delay and this instrument interleaves them in the same sitting at a separation of
        six positions, which is a weaker test of intra-rater agreement than the one that
        was written down. The bundle is reproducible from its seed, so a second reader is
        a thing that can be run rather than a thing to argue about."""
    )
)

STABILITY_BULLET = _para(
    f"""- **Generation is not reproducible.** Same prompt, same weights, temperature zero,
    fixed seed: {within["text_disagreement_rate"] * 100:.0f} percent of drafts differed on a
    repeat inside one process and {across["text_disagreement_rate"] * 100:.0f} percent
    differed across a process boundary after a model unload. The rate at which a repeat
    crossed the checker's accept-or-refuse decision was
    {within["verdict_flip_rate"] * 100:.0f} percent inside one process and
    {across["verdict_flip_rate"] * 100:.0f} percent across one. That is why the drafts are
    frozen and committed rather than generated at build time."""
)

INCONCLUSIVE_BULLET = _para(
    f"""- **{N_INCONCLUSIVE} of the {N_GATES} kill gates came back inconclusive** and are
    published as NOT_ESTABLISHED, which means a measurement was run and its interval did not
    exclude the null, not that it failed and not that it passed."""
)

def _n_console_pages() -> int:
    """How many pages the console's own navigation reaches.

    Counted from the rail rather than from the file tree, because the tree holds routes the
    rail does not link and a page nobody can navigate to is not a page a reader has.
    `tests/test_console_routes.py` holds the README's word for this number to the same
    count, so the three cannot drift apart.
    """
    rail = (REPO / "apps" / "web" / "components" / "Rail.tsx").read_text(encoding="utf-8")
    hrefs = re.findall(r'href:\s*"([^"]+)"', rail)
    if not hrefs:
        raise SystemExit(
            "no rail links found in apps/web/components/Rail.tsx, so this page would "
            "report zero reachable pages as a fact rather than as a broken read."
        )
    return len(hrefs)


#: The technologies this project runs on, each with the measurement that says it is doing
#: something rather than being present. Every number is read from a receipt, including the
#: unflattering ones, because a stack list is the easiest place on a submission page to
#: write a claim nobody checks.
STACK: list[tuple[str, ...]] = [
    (
        "IBM Granite (text)",
        f"`{agent['model']['name']}`, local Ollama",
        f"The agent study. {_AGENT_TOOLS['correct']['successes']}/"
        f"{_AGENT_TOOLS['correct']['trials']} correct with this project's MCP tools "
        f"against {_AGENT_CONTROL['correct']['successes']}/"
        f"{_AGENT_CONTROL['correct']['trials']} without, paired p = "
        f"{_AGENT_PAIRED['exact_p_one_sided']}. `artifacts/AGENT_RECEIPT.json`",
    ),
    (
        "IBM Granite (embeddings)",
        f"`{precedent['embedding_model']['name']}`, local Ollama",
        f"Precedent retrieval, reported the way its receipt reports it: "
        f"{_PRE_GRANITE:.3f} agreement warm against {_PRE_KNN:.3f} for a plain numeric "
        f"nearest-neighbour baseline on the same pool, a margin of "
        f"{_PRE_MARGIN['margin']:.3f} that does not survive the correction for "
        f"{_PRE_MARGIN['n_comparisons']} comparisons",
    ),
    (
        "Vector database",
        f"{precedent['vector_index']['backend']}",
        f"Holds the Granite vectors with station, site and satellite metadata and answers "
        f"the cold condition with a filtered query inside the index. Recall of the exact "
        f"top-{precedent['top_k']} is {_INDEX_RECALL['warm']:.4f} warm and "
        f"{_INDEX_RECALL['cold']:.4f} cold over "
        f"{precedent['vector_index']['queries_compared']['warm']} queries each",
    ),
    (
        "IBM Bob",
        "The build, and then the product",
        f"{N_BUILD_LOG_ENTRIES} dated units in `docs/BOB_BUILD_LOG.md`, each with what "
        f"failed before it was accepted. Bob also operates the finished system: "
        f"`docs/BOB_DEMO.md` is one paste that ranks the queue, refuses an invented "
        f"frequency, measures a pass recorded in the last hour and then refuses a "
        f"sentence about that measurement",
    ),
    (
        "Model Context Protocol",
        "Two stdio servers, registered in `.bob/mcp.json`",
        f"{len(TOOL_NAMES)} tools over committed receipts, {len(_SPEC_LIVE)} that measure "
        f"live, and {len(RESOURCE_URIS)} receipt resources. Read-only, enforced by a walk "
        f"over each server's own source in `tests/test_mcp_server.py`",
    ),
    (
        "The grounding checker, twice",
        "`pipeline/tracetriage/explain.py`, `apps/web/lib/grounding.ts`",
        f"One rule set in Python and in the browser, held to {_GOLDEN['n_rows']} recorded "
        f"decisions over {_GOLDEN['n_observations']} observations by "
        f"`tests/test_grounding_parity.py` and `apps/web/tests/grounding.test.ts`. On any "
        f"observation page a reader can change one digit and watch the refusal appear, "
        f"with no request leaving the page",
    ),
    (
        "SatNOGS API",
        "The corpus, and the live path",
        f"{dataset['counts']['observations_stored']} observations and "
        f"{dataset['counts']['waterfalls_stored']} waterfalls in the frozen snapshot, "
        f"keyless. The live page (`apps/web/app/live/page.tsx`) and the MCP tool "
        f"`live_triage_observation` both measure a pass recorded after that snapshot "
        f"closed, from the same public API, through `api/live.py`",
    ),
    (
        "SGP4 propagation",
        "`pipeline/tracetriage/physics.py`",
        "Every corridor is propagated from the two-line elements in the observation's own "
        "record rather than from today's, so a measurement carries the elements it was "
        "made with and can be redone from the receipt",
    ),
    (
        "IBM Carbon and IBM Plex",
        "`apps/web/app/globals.css`",
        "The palette is generated from Carbon's gray ramp rather than typed: "
        "`scripts/derive_palette.py --check` recomputes every token and every contrast "
        "ratio in it. Plex Sans and Plex Mono are self-hosted, so nothing carrying a "
        "number waits on a third-party request",
    ),
    (
        "LangChain",
        "`pipeline/tracetriage/langchain_tools.py`",
        f"{_LANGCHAIN['n_offered']} of the "
        f"{_LANGCHAIN['n_registered_by_the_mcp_server']} evidence tools, adapted for an "
        f"agent that does not speak MCP. An adapter and not a second implementation: each "
        f"tool calls the function object the MCP server registered, asserted on identity "
        f"in `tests/test_langchain_tools.py`. Through it, `check_claim` came back "
        f"{_LANGCHAIN['exercised']['refusal_through_the_adapter']['verdict']} with "
        f"{_LANGCHAIN['exercised']['refusal_through_the_adapter']['codes'][0]}. "
        f"`artifacts/LANGCHAIN_RECEIPT.json`",
    ),
    (
        "LangFlow",
        "`flows/`, `pipeline/tracetriage/langflow_components.py`",
        _LANGFLOW_CELL,
    ),
    (
        "watsonx.ai",
        "`scripts/run_watsonx_check.py`",
        _WATSONX_CELL,
    ),
    (
        "Remotion",
        "`presentation/`, rendered offline",
        f"The presentation film. {_FILM['beats']} cards, {_FILM['frames']} frames, "
        f"{_FILM['seconds']:g} seconds at {_FILM['fps']} fps, no audio. Every figure on "
        f"screen is resolved from a receipt key path at build time by "
        f"`presentation/src/data.ts`, so a number in the film cannot disagree with the "
        f"artifact it came from: {_FILM_CLAIMS['total']} claims over "
        f"{len(film['reads'])} committed JSON files, of which {_FILM_CLAIMS['drawn']} are "
        f"drawn and "
        f"{_FILM_CLAIMS['read_but_not_drawn']} are read only for cross-checks. Remotion "
        f"{_REMOTION}. `artifacts/FILM_RECEIPT.json`",
    ),
    (
        "Next.js, Vercel, WebGL",
        "`apps/web`, static export",
        f"{_n_console_pages()} pages, no server, no database and no credential, with a "
        f"content security policy whose `connect-src` is `'self'`. The field behind the "
        f"first screen is the ranked queue drawn on the GPU: one point per observation, "
        f"placed by rank, lit by review value, coloured by the criterion that raised it",
    ),
]


# Built here rather than inline in the template, because it reads five receipts and the
# template is already the longest f-string in this repository.
GATE_POWER = _gate_power()

PAGE = f"""# For judges

<!-- Generated by scripts/sync_for_judges.py from the receipts under artifacts/.
     Do not edit by hand: scripts/gate.py and the CI offline-replay job both run this
     script with --check, and both fail if this file and the receipts disagree. -->

TraceTriage ranks SatNOGS satellite radio observations by how much a human reviewer would
learn from opening each one, and it writes the reviewer's first sentence with a local IBM
Granite model whose draft is thrown away unless every number in it traces back to that
observation's own measured fields.

Ground-station networks are how university and cubesat missions are actually operated, and
an unreviewed pass is telemetry nobody read. The decision this serves is the one every
mission-operations queue has: of everything that came down, what does a person open first.

{_ESTABLISHED}

{INTRO}

## {N_CHECKS_WORD} checks worth running first

| Question | Command | What it prints |
|---|---|---|
{_table(CHECKS)}

**None of the {N_CHECKS_LOWER} needs a GPU, a model runtime or a network connection.**
`tracetriage note` reads frozen drafts and the verdicts the checker recorded against them.
`scripts/run_agent_study.py` and `scripts/run_explanations.py` publish from committed
fixtures and talk to a model only under `--freeze`, which is a step for re-measuring rather
than for reading. So a machine with no local runtime reproduces the same numbers this page
prints. `scripts/gate.py` builds the console as one of its steps, so that one wants Node as
well as Python.

`python` above means the interpreter built by the Setup section of `README.md`, which on
this machine is `.venv/Scripts/python.exe`. The offline suite's own pytest options include
`-q`, so a second `-q` suppresses the summary line: that is worth knowing before reading a
run as having collected nothing.

{SUITE_FAILURE_PARA}

{AGENT_PARA}

{CLONE_PARA}

{CLONE_LIMITS}

## Where each submission requirement is answered

| Requirement | Where |
|---|---|
{_table(REQUIREMENTS)}

## The stack, and what each piece is measured doing

Every number in this table is read from a receipt by the generator, including the ones that
weaken a claim. A technology is listed here only if something measures it working.

| Technology | Where it runs | What it is measured doing |
|---|---|---|
{_table(STACK)}

## The judged criteria, and what to look at

The Official Rules score four criteria, each 1 to 5, for a maximum of 20. Each heading
below is a criterion as the rules write it and the line under it is the rules' own wording,
so a scoring sheet and this page read in the same order.

The challenge page states the criteria a second time and lists five, adding **Real-World
Impact** and shortening the fourth to Feasibility. The two lists are answered here rather
than one of them being picked: Real-World Impact has its own heading under the fourth
criterion, so a judge scoring from either list finds their heading and the same evidence
under it.

### Technical Execution

> Effective use of IBM Bob and additional technologies, functional and well-structured
> solution.

{BOB_TECHNICAL}

{TECHNICAL}

Grouped bootstrap intervals group by orbital pass episode, not by image row, because two rows
from one pass are one observation of the sky. `docs/CLAIM_REGISTER.md` carries a row per
published number and `tests/test_claim_drift.py` fails if a number in the README stops
matching its receipt.

### Innovation

> Creativity, originality, and unique application of AI.

{INNOVATION_ONE}

{INNOVATION_TWO}

{INNOVATION_THREE}

### Challenge Fit

> Relevance to the challenge and ability to address real-world problems.

{CHALLENGE_FIT}

{LICENCE}

### Implementation and Feasibility

> Practicality, scalability, and potential for real-world use.

{FEASIBILITY_ONE}

{FEASIBILITY_TWO}

#### Real-World Impact

> Ability to create meaningful value and address real-world needs.

The fifth criterion on the challenge page, which the Official Rules fold into the fourth.
It is given its own heading because a judge working from the challenge page will look for
it, and the evidence is the same either way.

{IMPACT}

{GATE4_PARA}

{GATE4_HANDOFF_PARA}

## Why the gates that are not met are not met

{GATE_POWER}

## What this project does not claim

{STABILITY_BULLET}
- **A grounded note is not a useful note.** Grounding is a property of the numbers in a
  sentence. Nothing here asked a human whether the sentence was worth reading.
{INCONCLUSIVE_BULLET}
{GATE4_BULLET}
- **The physics arm does not beat image evidence on Brier score** by a margin whose interval
  excludes zero. `artifacts/FUSION_RECEIPT.json` gate5 carries the margin and the interval.
{PRECEDENT_BULLET}
{CIRCULARITY_BULLET}

## How IBM Bob was used

`docs/BOB_BUILD_LOG.md` has an entry per unit: what was asked, what came back, what failed and
what repaired it. `.bob/rules.md` is the standing instruction set Bob worked to, and
`.bob/TOOL_SPECS.md` specifies the project's own MCP tools, with the {N_TOOLS_BUILT} that
were built separated from the {N_TOOLS_UNBUILT} that were specified and were not, each of
those naming the script that did its job instead.

## The one thing to read if there is time for one thing

`artifacts/EXPLAIN_RECEIPT.json`. It is the only receipt here that reports a component of this
project failing, in detail, in public, with the failures enumerated and the rate published
rather than tuned away.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the generated page against FOR_JUDGES.md and exit non-zero on any "
        "difference. Writes nothing.",
    )
    args = parser.parse_args(argv)

    if args.check:
        if not OUT.exists():
            print("FOR_JUDGES.md does not exist. Run scripts/sync_for_judges.py.")
            return 1
        current = OUT.read_text(encoding="utf-8")
        if current == PAGE:
            print(f"FOR_JUDGES.md is current: {len(PAGE.splitlines())} lines")
            return 0
        print("FOR_JUDGES.md is stale. Run scripts/sync_for_judges.py.")
        for i, (a, b) in enumerate(
            zip(current.splitlines(), PAGE.splitlines(), strict=False), start=1
        ):
            if a != b:
                print(f"  first difference, line {i}:")
                print(f"    file:     {a.strip()[:120]}")
                print(f"    receipts: {b.strip()[:120]}")
                break
        else:
            print(
                f"  the file has {len(current.splitlines())} lines and the receipts "
                f"produce {len(PAGE.splitlines())}"
            )
        return 1

    OUT.write_text(PAGE, encoding="utf-8", newline="\n")
    print(f"FOR_JUDGES.md written: {len(PAGE.splitlines())} lines")
    print(f"  gates {N_MET}/{N_GATES} met, {N_INCONCLUSIVE} inconclusive, {N_OPEN} open")
    print(f"  offline suite {SUITE_RESULT}, from the clean clone")
    print(f"  notes {counts['emitted']} emitted, {counts['refused']} refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
