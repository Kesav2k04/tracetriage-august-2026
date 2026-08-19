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

from mcp_server import TOOLS as _MCP_TOOLS  # noqa: E402

TOOL_NAMES = sorted(_MCP_TOOLS)


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
if CLONE_NODE is None:
    raise SystemExit(
        "the clean-clone transcript does not record where apps/web/node_modules came from, so "
        "the page cannot disclose it."
    )

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
        "The offline install into the clone did not succeed, for the reason its own output "
        "tail gives, so the suite ran on this machine's interpreter at "
        f"`{CLONE_ENV_BORROWED['python_version']}` against the clone's source tree. The code "
        "under test is the clone's and the environment is not, which is a weaker claim than a "
        "cold-start install and is stated here rather than left to be inferred."
    )

if N_PASSED is None or N_SKIPPED is None:
    raise SystemExit(
        "the clean-clone transcript carries no parsed pytest count for the hidden-snapshot "
        f"pass ({_pytest}), so the number of tests cannot be quoted from it. Re-run "
        "scripts/clean_clone_check.py."
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


def _table(rows: list[tuple[str, ...]]) -> str:
    return "\n".join("| " + " | ".join(cells) + " |" for cells in rows)


def _para(text: str, indent: str = "") -> str:
    """One paragraph, wrapped after interpolation.

    Wrapping in the template instead would go ragged the first time a receipt changed the
    width of a number, which is the same reason the README generator wraps its tally.
    """
    return textwrap.fill(
        " ".join(text.split()),
        width=90,
        initial_indent=indent,
        subsequent_indent=indent,
    )


#: How many tools the specification records as built and as specified-and-not-built. The
#: page said five and five, which are the numbers today and are typed.
_SPEC = (REPO / ".bob" / "TOOL_SPECS.md").read_text(encoding="utf-8")
_SPEC_SECTIONS: dict[str, int] = {}
_heading = None
for _line in _SPEC.splitlines():
    if _line.startswith("## "):
        _heading = _line[3:].strip()
        _SPEC_SECTIONS[_heading] = 0
    elif _line.startswith("### ") and _heading is not None:
        _SPEC_SECTIONS[_heading] += 1
N_TOOLS_BUILT = _SPEC_SECTIONS.get("Implemented tools", 0)
N_TOOLS_UNBUILT = _SPEC_SECTIONS.get("Specified and not implemented", 0)
if len(TOOL_NAMES) != N_TOOLS_BUILT:
    raise SystemExit(
        f".bob/TOOL_SPECS.md documents {N_TOOLS_BUILT} implemented tools and the server "
        f"advertises {len(TOOL_NAMES)}. tests/test_mcp_server.py says which."
    )


CHECKS: list[tuple[str, ...]] = [
    (
        "Do the tests pass offline?",
        '`pytest -m "not network and not ocr and not llm" -q`',
        f"{N_PASSED} passed, {N_SKIPPED} skipped, measured in a clean clone with "
        f"every non-loopback socket refused",
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
        "Can an agent query the evidence?",
        "`python scripts/mcp_server.py` on stdio",
        f"An MCP handshake and {len(TOOL_NAMES)} read-only tools, one of which is the "
        f"grounding checker",
    ),
    (
        "Does the repository hold together?",
        "`python scripts/gate.py`",
        "The standing gates, one line each",
    ),
]

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
    ("Public repository", "This one"),
]


INTRO = _para(
    f"""This page is a map, not a summary. Each claim below names the file that carries the
    evidence and, where it can, the command that regenerates it. Of the {N_GATES} kill gates
    declared before the build, {N_MET} {_plural(N_MET, "was", "were")} met,
    {N_INCONCLUSIVE} came back inconclusive and {N_OPEN}
    {_plural(N_OPEN, "was", "were")} never run, and that tally is read from the receipts by
    the console rather than typed here."""
)

_FAILED_CLAUSE = "" if not CLONE_FAILED else f". What did not: {CLONE_FAILED_STEPS}"

GATE4_PARA = _para(
    f"""What has not been measured is whether a reviewer reads a generated note faster or
    better than the numbers alone. That is kill gate 4. The instrument for it exists now:
    `scripts/build_gate4_worksheet.py` builds a blinded bundle of
    {gate4["worksheet"]["items"]} items over {gate4["worksheet"]["unique_observations"]}
    observations, {gate4["worksheet"]["repeated_observations"]} of them repeated under a second
    item id so intra-rater agreement falls out of the answers, and it commits one salted
    sha256 per item so the sample provably predates the review. `scripts/score_gate4.py`
    scores the filled form against a {gate4["threshold"]:.2f} threshold using the same exact
    bounds gate 3 reads. `artifacts/GATE4_RECEIPT.json` currently says `{gate4["verdict"]}`,
    with no rate in it, because nobody has filled the form in. That is a person's afternoon
    rather than a code change, and it is reported as OPEN rather than estimated."""
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

CLONE_LIMITS = _para(
    f"""Two things about that run are worth knowing before it is trusted.
    {CLONE_ENV_SENTENCE} And `apps/web/node_modules` was linked from the source clone rather
    than installed, because `npm ci` needs the registry this run refuses; the transcript
    records the lockfile's sha256 (`{CLONE_NODE["package_lock_sha256"][:12]}`) so a reader can
    check that the borrowed tree belongs to this repository's pins. The socket refusal itself
    is a Python-level patch loaded through `PYTHONPATH`, so it reaches every Python child
    process and constrains nothing else: the Node steps are outside it, and that is a limit of
    the guard rather than a claim about them."""
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

PAGE = f"""# For judges

<!-- Generated by scripts/sync_for_judges.py from the receipts under artifacts/.
     Do not edit by hand: scripts/gate.py and the CI offline-replay job both run this
     script with --check, and both fail if this file and the receipts disagree. -->

TraceTriage ranks SatNOGS satellite radio observations by how much a human reviewer would
learn from opening each one, and it writes the reviewer's first sentence with a local IBM
Granite model whose draft is thrown away unless every number in it traces back to that
observation's own measured fields.

{INTRO}

## Four checks worth running first

| Question | Command | What it prints |
|---|---|---|
{_table(CHECKS)}

`python` above means the interpreter built by the Setup section of `README.md`, which on
this machine is `.venv/Scripts/python.exe`. The offline suite's own pytest options include
`-q`, so a second `-q` suppresses the summary line: that is worth knowing before reading a
run as having collected nothing.

{CLONE_PARA}

{CLONE_LIMITS}

## Where each submission requirement is answered

| Requirement | Where |
|---|---|
{_table(REQUIREMENTS)}

## The judged criteria, and what to look at

### Technical execution

{TECHNICAL}

Grouped bootstrap intervals group by orbital pass episode, not by image row, because two rows
from one pass are one observation of the sky. `docs/CLAIM_REGISTER.md` carries a row per
published number and `tests/test_claim_drift.py` fails if a number in the README stops
matching its receipt.

### Innovation

{INNOVATION_ONE}

{INNOVATION_TWO}

{INNOVATION_THREE}

### Challenge fit

{CHALLENGE_FIT}

{LICENCE}

### Feasibility

{FEASIBILITY_ONE}

{FEASIBILITY_TWO}

### Real-world impact

{IMPACT}

{GATE4_PARA}

## What this project does not claim

{STABILITY_BULLET}
- **A grounded note is not a useful note.** Grounding is a property of the numbers in a
  sentence. Nothing here asked a human whether the sentence was worth reading.
{INCONCLUSIVE_BULLET}
- **Nobody has read the blinded worksheet yet.** `artifacts/GATE4_RECEIPT.json` says
  `NOT_RUN`, which is a fourth outcome beside passed, failed and inconclusive, and it carries
  no rate because there is nothing to compute one from.
- **The physics arm does not beat image evidence on Brier score** by a margin whose interval
  excludes zero. `artifacts/FUSION_RECEIPT.json` gate5 carries the margin and the interval.

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

    OUT.write_text(PAGE, encoding="utf-8")
    print(f"FOR_JUDGES.md written: {len(PAGE.splitlines())} lines")
    print(f"  gates {N_MET}/{N_GATES} met, {N_INCONCLUSIVE} inconclusive, {N_OPEN} open")
    print(f"  offline suite {N_PASSED} passed, {N_SKIPPED} skipped, from the clean clone")
    print(f"  notes {counts['emitted']} emitted, {counts['refused']} refused")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
