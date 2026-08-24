<div align="center">

<img src="apps/web/public/og.png" alt="TraceTriage: a review queue, and the measurement that says how much it is worth. Three results at one size: Granite answering 22 of 24 with the evidence tools against 2 of 24 without, PASSED; the pre-registered split at 1.58x, NOT ESTABLISHED because the interval straddles the bar; and held-out stations at 2.25x, PASSED." width="820">

# TraceTriage

### Which satellite passes are worth a reviewer's time.

**Open a pass, and you see the waterfall a volunteer would squint at with the orbit's own
Doppler corridor drawn over it, the offset in hertz, and the reason this pass is above the
next one. Type any observation id and the same physics measures it live, in about twenty
seconds, from the public SatNOGS API.**

[![CI](https://github.com/Kesav2k04/tracetriage-august-2026/actions/workflows/ci.yml/badge.svg)](https://github.com/Kesav2k04/tracetriage-august-2026/actions/workflows/ci.yml)
[![Live console](https://img.shields.io/badge/live-tracetriage.vercel.app-fca50a?style=flat-square)](https://tracetriage.vercel.app/)
[![Judges start here](https://img.shields.io/badge/judges-start%20here-fca50a?style=flat-square)](https://tracetriage.vercel.app/start/)
[![Android APK](https://img.shields.io/badge/Android-signed%20APK-fca50a?style=flat-square)](../../releases/latest)
<br>
[![Built with IBM Bob](https://img.shields.io/badge/built%20with-IBM%20Bob-0f62fe?style=flat-square)](docs/BOB_BUILD_LOG.md)
[![IBM Granite](https://img.shields.io/badge/IBM%20Granite-3.1%208B%2C%20local-0f62fe?style=flat-square)](pipeline/tracetriage/granite.py)
[![IBM Carbon](https://img.shields.io/badge/IBM%20Carbon-design%20system-0f62fe?style=flat-square)](apps/web/app/globals.css)
[![MCP](https://img.shields.io/badge/MCP-2%20servers%2C%2012%20tools%2C%2011%20read--only-8a3ffc?style=flat-square)](docs/USE_WITH_YOUR_AGENT.md)
[![Offline](https://img.shields.io/badge/offline-8%20of%208%20pages-8a3ffc?style=flat-square)](artifacts/OFFLINE_RECEIPT.json)

**[Live console](https://tracetriage.vercel.app/)** &nbsp;·&nbsp;
**[Judges start here](https://tracetriage.vercel.app/start/)** &nbsp;·&nbsp;
**[Narrated film, 3 min](presentation/out/tracetriage-film.mp4)** &nbsp;·&nbsp;
**[Android APK](../../releases/latest)** &nbsp;·&nbsp;
**[Use it from your agent](docs/USE_WITH_YOUR_AGENT.md)**

*AI Builders Challenge with IBM Bob · August 2026 · theme: Advance Space Exploration with AI*

</div>

> In a 600-observation sample of the public SatNOGS network, **426 carried no decisive human
> verdict at all.** Ground-station networks are how university and cubesat missions are
> actually operated, and an unreviewed pass is telemetry nobody read. There is no shortage of
> observations. There is a shortage of attention, and nothing tells a volunteer where to spend
> it.

---

## Judge quick access

No account, no keys, nothing to install for any row in this table.

| To check | Open this |
|---|---|
| That it works at all | **[the live console](https://tracetriage.vercel.app/)**, then a queue row |
| That the measurement is real, not a fixture | **[the live page](https://tracetriage.vercel.app/live/)**: type `14740031`, wait ~20 s |
| That the deployment is this repository | **[`/api/health/`](https://tracetriage.vercel.app/api/health/)**, whose `sha256` equals `curl -s https://tracetriage.vercel.app/data/provenance.json \| sha256sum` |
| Every claim against its receipt | **[`FOR_JUDGES.md`](FOR_JUDGES.md)**, one section per judged criterion |
| The gates that did not pass | **[`docs/KILL_GATE.md`](docs/KILL_GATE.md)**, and [below](#where-the-gates-landed-and-why) |
| What IBM Bob built, task by task | **[`docs/BOB_BUILD_LOG.md`](docs/BOB_BUILD_LOG.md)** |
| That the repository holds together | `python scripts/gate.py`, one line per standing check |

The five sections the submission asks for: [Problem statement](#problem-statement) ·
[Solution description](#solution-description) ·
[AI approach and architecture](#ai-approach-and-architecture) ·
[Selected challenge theme](#selected-challenge-theme) ·
[How IBM Bob was used](#how-ibm-bob-was-used). Feasibility and real-world impact have their
own headings further down, and `FOR_JUDGES.md` answers all five with the command that
regenerates each number.

---

## What it decides, in one picture

```mermaid
flowchart LR
  OBS["A SatNOGS pass<br/>waterfall image + record"]
  IMG["What the image shows<br/>detected trace"]
  ORB["What the orbit predicts<br/>SGP4 Doppler corridor"]
  CMP{"Do they<br/>agree?"}
  TOP["Top of the queue<br/>with the reason and the fields"]
  LOW["Further down<br/>or an abstention with a code"]
  REV(["A human decides.<br/>Nothing is written back."])

  OBS --> IMG --> CMP
  OBS --> ORB --> CMP
  CMP -- "no, and both are measurable" --> TOP
  CMP -- "yes, or the evidence is insufficient" --> LOW
  TOP --> REV
  LOW --> REV
```


---

## Problem statement

The SatNOGS network publishes ground-station radio observations of satellites. Each one
produces a waterfall image, a spectrogram of received power over frequency and time, and
volunteers review these by eye to decide whether a satellite was actually heard.

There are far more observations than there is human attention. In a 600-observation sample
measured on 2026-08-16, **71% carried no decisive human waterfall verdict at all** (426 of
600 were `unknown`; `docs/SATNOGS_API_RECON.md`). The backlog is not a storage problem. It is
an attention-allocation problem.

A student researcher or a volunteer with forty minutes faces one concrete decision: **which
observations, out of thousands, deserve those forty minutes?** Reviewing in arrival order
spends the budget on the easy and the already-obvious. What is worth a human's time is the
subset where the evidence disagrees with itself: the image looks like signal but the orbital
geometry says the satellite was below the horizon, or the network label says nothing was heard
but a trace sits exactly where physics predicts it.

### The gap this ranks on

Both rows are published SatNOGS waterfalls, unmodified on the left and annotated on the right
by `scripts/a3_doppler_investigation.py`. The record cannot tell them apart. The image can.

<table>
<tr>
<td width="50%"><img src="artifacts/a3_overlays/overlay_14746118.png" alt="Observation 14746118: the received energy follows a straight vertical line, and the predicted uncorrected Doppler curve drawn in red misses it entirely." width="100%"></td>
<td width="50%"><img src="artifacts/a3_overlays/overlay_14740031.png" alt="Observation 14740031: the received energy follows the predicted Doppler curve drawn in red, sweeping across about 16 kHz, while the corrected-hypothesis corridor drawn in magenta sits empty." width="100%"></td>
</tr>
<tr>
<td><b>14746118, corrected.</b> The trace is a straight vertical line: 54.2 sigma against
7.3 for the swept curve. The station's software had already removed the Doppler shift
before writing the image, and nothing in the observation record says so.</td>
<td><b>14740031, uncorrected.</b> The trace follows the predicted curve across about 16 kHz:
25.1 sigma against 2.8 for the best vertical line. The same fields, the same client,
the opposite convention.</td>
</tr>
</table>

A detector that assumes one of these two shapes is wrong on the other half of the corpus, and
the observation record gives it no way to choose. Method and open questions:
**`docs/DOPPLER_CORRECTION_FINDING.md`**.

## Selected challenge theme

**Advance Space Exploration with AI.** The theme asks for solutions that turn data-heavy space
operations into insight-driven ones and make space more accessible. SatNOGS is open,
volunteer-run space infrastructure whose bottleneck is human review capacity. Spending scarce
reviewer attention where it changes an outcome is directly that problem.

## Solution description

TraceTriage ranks a read-only review queue over observations that already exist. Each row
carries an evidence card showing:

- the waterfall image as published
- the **expected corrected-centre corridor**, the frequency band where a real signal from that
  satellite should appear, computed from the observation's own stored TLE, station
  coordinates, timing and receiver metadata
- the detected trace and its residual against that corridor
- artifact-quality checks, and the current SatNOGS label with where that label came from
- a calibrated confidence score, or an explicit **abstention with a reason code** when the
  evidence is not sufficient

The queue puts disagreement and uncertainty at the top, subject to duplicate control and
station and transmitter diversity so a single noisy station cannot flood the budget.

**What this system will never do.** It does not vote on SatNOGS, does not change any public
label, does not schedule or control a station, and does not hold a write credential. It does
not claim confirmed satellite identity, decoded telemetry, mission success, or official
endorsement. The boundary is specified in `docs/ACTOR_AND_PERMISSION_CONTRACT.md` and enforced
by test rather than by convention.

The strongest statement this project is permitted to make, once the evidence exists, is:

> On a frozen chronological sample of public SatNOGS observations, TraceTriage concentrated
> independently reviewable label or physics conflicts near the top of a fixed review budget
> while abstaining when the evidence was insufficient.

## AI approach and architecture

Every layer has to earn its place through an ablation. A component that does not improve
calibration or queue utility is deleted rather than defended, and three of the results below
are deletions.

<img src="docs/architecture.svg" alt="Ten pipeline stages running top to bottom. A frozen SatNOGS snapshot feeds SGP4 physics, then four frozen splits. Two evidence channels run side by side: image processing into features, and a bounded corridor fit into a calibrated image-only baseline arm. Both feed a small calibrated fusion head, then calibration with out-of-distribution detection and abstention, then the review-value queue. The queue feeds a Granite reviewer note and a read-only evidence agent, and both feed the static console. Every box names the module that implements it and the receipt it writes." width="904">

`scripts/build_architecture_diagram.py` draws that from the tree. It refuses to draw a box
until the module and the receipt that box names both exist, and refuses to draw an edge into a
stage nothing produces, so a renamed stage fails the standing gate rather than leaving a
picture of a pipeline this repository no longer has.

**The pipeline, in the order it runs.** Every stage writes a file the next one reads.

| # | Stage | What it does | Where |
|---|---|---|---|
| 1 | Snapshot | Freezes SatNOGS metadata and waterfalls with a SHA-256, a retrieval time and the licence per file. Nothing downstream reaches the network. | `scripts/recon` |
| 2 | Contracts | Each stage's output schema is ratified before the script that writes against it runs. | `contracts/` |
| 3 | Physics | SGP4 from the TLE current at observation start, Doppler from range rate, mapped to pixel columns through the image's own frequency axis. | `pipeline/tracetriage/physics.py` |
| 4 | Splits | Four holdouts: chronological, cold-station, cold-transmitter, cold on both. Each transmitter and each orbital revolution stays in one partition. | `pipeline/tracetriage/splits.py` |
| 5 | Model ladder | Four rungs, from a centre-energy heuristic to a fusion head over image, metadata and physics. A rung that does not beat the one below on a grouped bootstrap is dropped. | `artifacts/FUSION_RECEIPT.json` |
| 6 | Calibration | Fitted on a later time period than training, then a selective-prediction curve trading a risk ceiling against coverage. | `artifacts/FUSION_RECEIPT.json` |
| 7 | Queue | Ranks the test partition, deduplicates repeats of one pass episode, and measures lift against random, first-in-first-out and image-only uncertainty at the same budget. | `scripts/run_queue.py` |
| 8 | Console | Projects the receipts into the site's JSON, refusing to substitute a null for a field it could not find. | `scripts/build_console_data.py` |
| 9 | Reviewer note | Builds a closed 26-field evidence packet and sends it to a local Granite model. The only HTTP write verb here, and it refuses any destination that is not loopback. | `pipeline/tracetriage/granite.py` |
| 10 | Evidence server | Seven MCP tools over the receipts, six read-only and one that runs the standing gate. No dependency outside the standard library. | `scripts/mcp_server.py` |

Four decisions in this architecture are worth stating on their own, because each one changed a
published number.

**Evaluation is grouped, never random**, because random image splits leak station, satellite
and rendering patterns. Intervals are bootstrapped over orbital episodes or ground stations,
never image rows, and the reported interval is the union of the two. **Labels are silver, not
truth**: `waterfall_status` is weak supervision, and unknowns stay unlabelled rather than being
coerced into a negative class.

**Granite writes the first sentence, and a checker refuses most of what it writes.** Of 25
cards, 10 drafts were accepted and 15 refused on 17 violations. In **9 of the 25** Granite
wrote a downlink frequency that was not this observation's, wrong by 10 kHz to 1215 kHz, and
every invented value landed **within five percent** of the real one. That is the shape that
matters: on telemetry the difference between 437.05 MHz and 437.06 MHz is the difference
between a satellite and nothing, which is why the checker compares every numeric token against
the packet instead of scoring the sentence.

**The agent is measured against a control.** `pipeline/tracetriage/agent.py` drives five MCP
tools from the local Granite model over real stdio JSON-RPC, and `scripts/run_agent_study.py`
puts 24 questions to it twice, once with the tools and once with none. With them, **22 of 24
correct**; without them, **2 of 24**; of the 20 questions the arms disagreed on, the tool arm
was right on 20, an exact one-sided p of 1e-06.

<details>
<summary><b>What those four results do not establish</b>, in the words the receipts use</summary>

The control declined **18 of its 24** as unknown rather than guessing, because the answers are
stored values it has no other route to. So the agent study measures whether the policy reaches
for the tools and reports what they return, not whether tools make a model cleverer. The 24
questions are lookups with a single correct token, chosen so grading is mechanical, and a
reviewer's real question is not.

The grounding checker is measured in both directions, because a checker that refuses
everything catches every adversarial draft: **525 of 525** adversarial checks refused for the
reason they were built to trip, and **0 of 175** clean checks refused. Both figures are a
multiplication and are worth reading as one: 21 adversarial drafts and 7 clean ones, each run
against all 25 packets. So 525 of 525 says the checker fires where it was built to fire, not
that it caught 525 independent attacks. The number that is not constructed is the 9 of 25 real
drafts above. Generation is not reproducible at temperature zero, so the text a reviewer sees
is frozen into a committed fixture and the disagreement rate is published beside it.

Precedent search is the third deletion. A Granite embedding of each evidence card goes head to
head against seven standardised numbers over 739 decisively labelled observations. Warm, where
any other observation may be retrieved, the embedding wins by a margin whose interval clears
zero. Cold, where the query's own station, physical site and satellite are all forbidden, it
does not. The console carries both columns at the same weight.

None of this measures whether an accepted note is useful. Grounding is a property of the
numbers in a sentence, not of the sentence being worth reading.

Receipts: `artifacts/EXPLAIN_RECEIPT.json`, `artifacts/AGENT_RECEIPT.json`,
`artifacts/PRECEDENT_RECEIPT.json`.

</details>

### The IBM stack, and what each piece is measured doing

A technology is listed only if something here measures it working, and every row names the file
to open.

| Piece | What it does | Where |
|---|---|---|
| **IBM Bob** | Primary development tool. Built the ingestion, physics, parser, splits and queue. | `docs/BOB_BUILD_LOG.md` |
| **IBM Granite 3.1 dense 8B** | Writes the reviewer's first sentence, locally, at temperature zero. A grounding checker refuses more of its drafts than it accepts. | `pipeline/tracetriage/granite.py` |
| **IBM Granite embedding 278m** | Retrieves precedents, measured against seven standardised numbers and indistinguishable from them. | `pipeline/tracetriage/precedent.py` |
| **IBM Carbon** | The console's design system, and it owns the structure: the Gray 100 ramp, the type scale, the 8px steps, the motion curves. | `apps/web/app/globals.css` |
| **IBM Plex** | Sans and Mono, self-hosted. Every face that carries a measurement is served from this origin. | `apps/web/app/layout.tsx` |
| **Model Context Protocol** | Two stdio servers, 12 tools. Read-only enforced by an AST walk over each server's own source: no write verb in either, no network import in the offline one. | `scripts/mcp_server.py` |
| **LangChain** | 6 evidence tools as `StructuredTool`s, for an agent that does not speak MCP. An adapter, not a second implementation: object identity with the MCP handlers is asserted. | `pipeline/tracetriage/langchain_tools.py` |
| **LangFlow** | Two flows built from component objects, dumped by LangFlow itself, then loaded back and executed. The grounding flow needs no model and no network. | `flows/` |
| **watsonx.ai** | Optional text-generation backend through the same grounding checker. With no credential the receipt records a dated `NOT_CHECKED` rather than a pass. | `pipeline/tracetriage/watsonx.py` |

Three of those rows are results rather than choices: Granite's drafts are refused more often
than accepted, the embedding does not beat seven numbers, and watsonx is `NOT_CHECKED` here
because no IBM Cloud credential is set.

## How IBM Bob was used

IBM Bob is the primary development tool for this project and built the load-bearing pipeline:
**10 dated Bob-account units**, A7, A6, A5, A0, A0b-INT, A1, A2, A4, B1 and C1, covering the
data contracts, the immutable snapshot, the waterfall artifact parser, the physics corridor,
label provenance, the image-only baselines, the end-to-end triage slice, the grouped splits
with their leakage audit, and the review-value queue with kill gate 6.

A further 49 dated units are operator-side, run from Cursor and Claude Code, and are labelled
that way in the actor field of their own headings: the console, the calibration and abstention
blocks, the fusion ladder and the review waves are theirs, not Bob's. 47 are in
`docs/OPERATOR_BUILD_LOG.md` and 2 stay beside the Bob units whose gaps they closed. Both
counts are read out of the logs rather than typed here.

Bob's work is recorded rather than asserted:

- `docs/BOB_BUILD_LOG.md` maps each Bob task to files, commits, tests, failures, repairs and
  actual build credit consumed.
- `.bob/rules.md`, `.bob/TOOL_SPECS.md` and `.bob/mcp.json` are the standing instructions, tool
  contracts and MCP wiring each Bob task ran under, so the conditions of the work are readable
  and not just its output. Of the 16 tools the specification describes, it separates
  the 12 tools that exist from the
  4 that were specified and were not, naming the script that did each of those jobs instead.
- A final Bob task inspects the release commit, runs the acceptance suite, repairs failures and
  writes `artifacts/SIGNOFF_RECEIPT.json`, naming each check, its command, its exit code and a
  line of its output. It has three outcomes rather than two: a check that could not run in that
  environment is `NOT_CHECKED` with a stated reason, and the verdict refuses to sign while any
  check has failed.

`docs/PRE_BUILD_BASELINE.md` lists exactly what existed before Bob's first task, so the line
between scaffolding and Bob's work is auditable rather than implied.


---

## What it produced

<!-- generated by scripts/sync_readme_results.py: what it produced, do not edit -->
**What it produced.** Four things that can be opened rather than taken on trust. Every
figure below is read out of a receipt under `artifacts/` by the script that writes this
block, so none of it can drift from the study it came from.

- **A ranked review queue over 407 observations**, live on the console, each row carrying
  the reason it is there and the measured fields that reason was computed from. Nothing is
  written back to SatNOGS: the queue is a reading order, and a human decides.
- **An agent that answers questions about that evidence over MCP.** `granite3.1-dense:8b`,
  running locally at Q4_K_M and temperature 0, answers 22 of 24 correctly with five
  read-only tools and 2 of 24 with none. One-sided exact p = 1e-06 over 20 discordant
  pairs. The control arm is the point: the tools are measured, not demonstrated.
- **A grounding checker that refuses most of what the model writes.** Of 25 drafts, 10
  were emitted and 15 refused. Against 525 adversarial drafts it caught 525, and against
  175 clean ones it refused 0. A published sentence is one no rule could fault, not one
  the model was confident about.
- **A precedent search on `granite-embedding:278m`**, put head to head against seven
  standardised numbers under a condition built to take its advantage away, and reported
  indistinguishable in both. A result that went the other way is published the same size
  as one that did not.
<!-- end what it produced -->

---

## Where the gates landed, and why

Six kill gates with numeric thresholds were written down before anything was measured. A gate
is met only when a 95% interval clears its threshold, so a point estimate above the bar whose
interval straddles it is a failure here.

<!-- generated by scripts/sync_readme_results.py: gate status, do not edit -->
**Status: six kill gates were written down, with their thresholds, before any of them was
measured.** They are a research bar rather than a feature list, and they are stricter than
anything this challenge asks for: a gate is met only when a 95% interval clears its
threshold, so a point estimate above the bar whose interval straddles the bar is published
as a failure. Two of the six asked whether the project was feasible at all and were
answered before the first line of pipeline code. Gate 6 does clear its threshold on the
held-out cold-station split, at 2.253x. That is reported, and it is not substituted for
the split the gate was pre-registered on. **On the split each of the remaining four was
pre-registered on, one passed, two came back inconclusive and one cleared the bar over
observations and not over independent episodes.** Why the intervals are that wide is
measured rather than pleaded, and it is the paragraph after the tables.

**Feasibility, decided in advance.**

| # | Gate | Threshold | Verdict |
|---|---|---|---|
| 1 | Dataset volume and entity spread | ≥2,000 mature waterfalls, ≥12 transmitters, ≥30 stations | **PRE_PASSED** |
| 2 | Metadata coverage for the corridor | ≥80% of the sample computable | **PRE_PASSED** |

**Substantive, and the reason the rest of this file is worth reading.**

| # | Gate | Threshold | Verdict | What came back |
|---|---|---|---|---|
| 3 | Corridor intersects a visible trace | ≥70% of reviewed positives | **PASSED_UNGROUPED_ONLY** | 224 of 289 testable observations discriminate, and the exact one-sided 95% lower bound on that rate is 0.731 |
| 4 | Blinded human decidability | ≥80% of a balanced sample decidable | **PASSED** | 60 of 60 first-occurrence plates decidable by one person under commitment, rate 1.0000, exact one-sided 95% lower bound 0.9513. The reviewer is the author, so this is blinded and not independent, and intra-rater agreement is the weaker number at 8 of 12 repeated plates |
| 5 | Physics beats image-only on Brier | strict improvement, chronological split | **NOT_ESTABLISHED** | margin +0.02079 on the shipped arm, 95% CI -0.01301 to +0.05036, which contains zero |
| 6 | Queue lift over random | ≥1.5x actionable conflicts at equal budget | **NOT_ESTABLISHED** | 1.582x, 95% CI [1.353, 1.740], which contains the threshold. On the held-out cold-station split the same queue **PASSED** at 2.253x |

An interval that spans a threshold is not a measurement of nothing. On the split gate 6
was pre-registered on, 0 of 2,000 random orderings of the same 87 observations found as
many actionable conflicts inside the review budget as this queue did, a permutation
p-value of 0.0005. The interval spans 1.5 because the scale is short: a budget of 50 over
87 observations holding 22 conflicts caps every possible ordering, a perfect oracle
included, at 1.740x. The gate is still not met, and the whole room any ordering had to
meet it in was 0.240 wide.

Inconclusive is reported as `NOT_ESTABLISHED` rather than rounded into a pass, and the gate
that was never run is reported as `OPEN` rather than omitted. Gate 3 was `PASSED` until 2026-08-18, when the rate it claimed was re-derived with an
exact interval and moved to `NOT_ESTABLISHED` on three observations. It reads
`PASSED_UNGROUPED_ONLY` now, on a pool of 303 selected by a rule that never fits a
corridor: the observation-level bound clears the bar and the bound over independent
(station, date) episodes does not. `docs/KILL_GATE.md` carries every entry rather than the
history being quietly rewritten.

Every number in this README is generated from a frozen artifact under `artifacts/` and
carries a row in `docs/CLAIM_REGISTER.md`. `tests/test_claim_drift.py` compares each quoted
value against the artifact it came from rather than merely checking a register row exists:
editing the AUC row from 0.875 to 0.999 turns three tests red. `tests/test_readme_claims.py`
does the same for the paths and images this file names, because an existence claim is as
checkable as a number.
<!-- end gate status -->

<!-- generated by scripts/sync_readme_results.py: why the gates landed there, do not edit -->
**3 of the 6 gates are not met, and none of them is left without an account.** Each row
below names what actually bound the measurement and the condition that would move it,
computed from the same receipts that decided the verdicts by `scripts/run_gate_power.py`.
2 of the 3 were settled by exact arithmetic and 1 was a projection, and they are labelled
so the difference survives being quoted.

| Gate | Verdict | What bound it | What would close it |
|---|---|---|---|
| 3 | **PASSED_UNGROUPED_ONLY** | 289 of 303 testable observations scored, 224 discriminating. The exact bound is 0.731 against a 0.7 bar. | Not more episodes. This corpus has 68 independent (station, date) episodes, which already exceeds the 9 all-discriminating episodes that would clear a 0.7 bar on their own, and 32 of the 68 discriminate on every capture, putting the grouped bound at 0.366. Clearing 0.7 at 68 episodes takes 55 of them, and at 54 the bound is 0.697. The observation-level bound clears 0.7 at 0.731; the plan's rule is to group, so the observation-level pass is reported and not claimed. |
| 5 | **NOT_ESTABLISHED** | 88 test observations. The interval's lower arm is 1.63 times the margin it has to clear. | About 233 test observations at the same margin, against the 88 this split has. That is 2.6 times the chronological test set. *(projected)* |
| 6 | **NOT_ESTABLISHED** | 87 observations at a budget of 50 cap every ordering at 1.740x, leaving 0.240 of room for an interval 0.387 wide. | A split whose room exceeds the interval it produces. cold_station already does: room 2.673 against an interval 1.939 wide, and it passed at 2.253. |

**Gate 6's verdict is decided by the split, not by the queue, and that is measurable.**
Define the room a split gives a verdict as the distance between the threshold and the best
score any ordering could reach there, a perfect oracle included. Whether the published
interval fits inside that room predicts the verdict on 4 of 4 measurable splits, with no
exceptions.

| Split | Observations | Oracle ceiling | Room above 1.5x | Interval width | Fits | Verdict |
|---|---:|---:|---:|---:|:---:|---|
| `chronological` | 87 | 1.740 | 0.240 | 0.387 | no | **NOT_ESTABLISHED** |
| `cold_combined` | 76 | 1.520 | 0.020 | 0.447 | no | **NOT_ESTABLISHED** |
| `cold_station` | 217 | 4.173 | 2.673 | 1.939 | yes | **PASSED** |
| `cold_transmitter` | 95 | 1.900 | 0.400 | 0.558 | no | **NOT_ESTABLISHED** |

On `chronological` and `cold_combined` the interval's upper bound **is** the ceiling: no
resampling of that split can return a number above it, however good the ranking is. An
interval truncated by the arithmetic of its own split is not measuring the ranker. The one
split with room to spare is the one split that passed, which is why the cold-station
result is reported beside the pre-registered one rather than instead of it.

The obvious extrapolation does not follow, and this corpus contains its counterexample:
`cold_transmitter` holds more observations than `chronological` and still fails, because
its interval came back wider too. So no required sample size is published for gate 6, only
the condition.
<!-- end why the gates landed there -->

## Measured results

<details>
<summary><b>Established, with receipts. The two Doppler rows above, plus the metadata that cannot reveal correction status.</b></summary>

These are generated from frozen artifacts and registered in `docs/CLAIM_REGISTER.md`.

| Metric | Value | Receipt |
|---|---|---|
| Corrected and uncorrected captures both occur | 4 corrected, 3 uncorrected, 17 undecidable, of 24 vetted `with-signal` observations | `artifacts/a3_overlays/summary.json` |
| Metadata cannot reveal correction status | `doppler-correction-per-sec` null and `rigctl-port` `4532` on 24 of 24, in both groups | `artifacts/a3_overlays/summary.json` |
| Strongest corrected match | vertical carrier at 54.2 sigma against 7.3 for the swept curve | `artifacts/a3_overlays/overlay_14746118.png` |
| Strongest uncorrected match | swept curve at 25.1 sigma against 2.8 for the best vertical line | `artifacts/a3_overlays/overlay_14740031.png` |
| Observations with no measurable narrowband trace | 17 of 24 vetted `with-signal`, scoring 0.7 to 3.5 sigma | `artifacts/a3_overlays/summary.json` |
| Pass geometry against reported max_altitude | median 0.22 deg, p99 0.53 deg, 99.5% within 1 deg, 199 of 200. The reference is integer-valued on all 200 records, so this bounds the error near half a degree and resolves nothing finer | `artifacts/PHYSICS_VALIDATION.json` |
| Pass azimuth against reported rise and set azimuth | median 0.27 deg at rise and 0.27 deg at set, max 1.96 deg, 100% within 3 deg, on an unrounded reference. Swapping the atan2 arguments gives 93.9 deg and mirroring the azimuth gives 27.0 deg | `artifacts/PHYSICS_VALIDATION.json` |
| Frequency axis direction, re-measured per observation | the shipped convention wins on all 3 observations where it is measurable; the other 4 are corrected passes whose flat corridor cannot orient an axis at all. It was measured on 2 of the 20 client families in the dataset. The constant applies where a waterfall was rendered, which is 2,500 of the 2,727 stored observations: 1,004 of those come from a measured family and 1,496 inherit it. Over all 2,727 rows the figures are 1,023 and 1,704, and both pairs are published because the second counts 227 observations with no image | `artifacts/GATE3_RECEIPT.json` |

The first two rows are the reason this project exists, and they are shown rather than
described [above](#the-gap-this-ranks-on).

</details>

### Measured, with receipts

Every cell below is read from a receipt under `artifacts/` and registered in
`docs/CLAIM_REGISTER.md`. Of the 6 kill gates, 3 were met and 3 came back inconclusive.
The rows for the gates that produced no number say so rather than being left out.

<details>
<summary><b>14 measured rows, every one read from a receipt. Brier 0.1292 against 0.1495 image-only, queue lift 1.582x NOT_ESTABLISHED, cold-station 2.253x PASSED, gate 4 PASSED at 60 of 60.</b></summary>

| Metric | Value | Receipt |
|---|---|---|
| Brier score, chronological holdout | 0.1292 for the shipped arm, against 0.1495 image-only and 0.2085 for a prior-only floor | `artifacts/FUSION_RECEIPT.json` |
| AUC, chronological holdout | 0.875, against 0.842 image-only | `artifacts/FUSION_RECEIPT.json` |
| Calibration slope and intercept | 1.483 and -0.246, ECE 0.0713 | `artifacts/FUSION_RECEIPT.json` |
| Selective risk near 80% coverage | 0.0857 at 79.5% coverage | `artifacts/FUSION_RECEIPT.json` |
| Queue lift over random, chronological | 1.582x, 95% CI [1.353, 1.740], **NOT_ESTABLISHED** against a 1.5x threshold | `artifacts/QUEUE_RECEIPT.json` |
| Queue lift over image-only uncertainty | 1.582x against 1.186x at the same budget | `artifacts/QUEUE_RECEIPT.json` |
| Queue lift over first-in-first-out | 1.582x against 1.107x | `artifacts/QUEUE_RECEIPT.json` |
| Cold-station holdout | **PASSED**, 2.253x, 95% CI [1.920, 3.859] | `artifacts/QUEUE_RECEIPT.json` |
| Cold-transmitter holdout | 1.656x, 95% CI [1.336, 1.894], NOT_ESTABLISHED | `artifacts/QUEUE_RECEIPT.json` |
| Cold station and transmitter together | 1.292x, 95% CI [1.073, 1.520], NOT_ESTABLISHED | `artifacts/QUEUE_RECEIPT.json` |
| Physics beats image-only on Brier | **NOT ESTABLISHED**. Margin +0.02079, interval spans zero | `artifacts/FUSION_RECEIPT.json` gate5 |
| Shipped ranker against what the ablation recommends | They disagree. The queue ranks with `image_corridor` and the corrected rule recommends `image_only`. The block without corrected support is `corridor`, kept because the same arm's risk-coverage margin is +0.05736 with a corrected interval of +0.01192 to +0.11887, which does clear zero | `artifacts/FUSION_RECEIPT.json` ablation_conclusion |
| Granite text embedding against seven standardised numbers | Indistinguishable in both conditions. Warm margin +0.0260, adjusted interval [-0.0169, +0.0660]; cold margin +0.0168, [-0.0406, +0.0783]. Both span zero over 739 queries resampled by 116 ground stations | `artifacts/PRECEDENT_RECEIPT.json` |
| Blinded human decidability rate | **PASSED**. 60 of 60 first-occurrence observations decidable, rate 1.0000, exact one-sided 95% [0.9513, 1.0000] against a 0.80 threshold. Intra-rater agreement is 8 of 12 repeated plates, which is the weaker of the two numbers and no claim rests on it | `artifacts/GATE4_RECEIPT.json` |

</details>

### Still unmeasured, and named as such

<details>
<summary><b>One row, named rather than left out: human minutes per confirmed finding.</b></summary>

| Metric | Value | Why |
|---|---|---|
| Human minutes per confirmed finding | `[UNMEASURED]` | Half of it is now measured and the other half is not. One reviewer spent 47.1 minutes over 72 blinded plates, a median of 25.0 seconds each. Turning that into minutes per confirmed finding needs the share of opened observations that carry something, and no study here measures it on a human who opened them. |

</details>

### What the queue's own construction guarantees

The ranking score and the definition of a conflict are not independent, and the size of
that problem is measured rather than described. The score is 0.40 x disagreement + 0.35 x
safe offset magnitude + 0.15 x flat-row fraction + 0.10 x ensemble uncertainty, and the
three conflict criteria threshold the first three of those same quantities. 90% of the
score's weight sits on quantities the definition names and 75% on quantities a conflict in
this corpus is actually defined from, the gap being DEAD_CAPTURE, which fires on nothing
here. Either way a lift above 1.0 is close to guaranteed by construction.
`scripts/run_circularity_check.py` bounds it from `artifacts/CIRCULARITY_RECEIPT.json`,
reading the queue receipt and nothing else: no snapshot, no network, no model. It
reproduces the published 1.5818x from that file before computing anything.

<details>
<summary><b>7 questions about how much room the measurement had, and what the answers bound.</b></summary>

| Question | Answer |
|---|---|
| What is the most any ordering could score here? | 1.740x. A budget of 50 over 87 observations holding 22 conflicts caps a perfect oracle there, so the whole distance between the 1.5x threshold and perfection is 0.240 |
| How much of that did the queue get? | 20 of the 22 an oracle would have found, which is 91% of the ceiling |
| What happens with the model taken out of the target? | 1.557x, 95% CI [1.264, 1.740], **NOT_ESTABLISHED**, counting only the 19 conflicts flagged by the two criteria the model does not enter, of which DEAD_CAPTURE flags nothing here, so the restriction reduces to one criterion |
| And with only the model's own disagreement? | 1.740x over 3 conflicts, reported as **NOT_INFORMATIVE** rather than as a pass: the queue found all 3 inside the budget, and a saturated lift equals population over budget whatever the count was |
| How often does a random ordering match the queue? | 0 times in 2,000 seeded shuffles of the same population, a permutation p-value of 0.0005, which is the smallest this test can report at 2,000 permutations |
| Does the statistic score a shuffle at 1.0? | 0.9992 over the same 2,000 permutations, 5th to 95th percentile 0.712 to 1.265. Each one is scored by `compute_lift`, the function gate 6 itself is measured with, so a defect in it moves this number |
| Which split has the least room to be measured in? | `cold_combined`: 20 conflicts in 76 observations at a budget of 50 caps every ordering at 1.520x against a 1.5x bar. That is 0.020 of room and a published **NOT_ESTABLISHED**, so its verdict is a fact about the budget and the receipt marks it not informative |

</details>

That the queue generalises. Restricting the target to the criteria the model does not
enter removes one loop and leaves another: on this corpus that restriction reduces to
STALE_CATALOGUE_FREQ alone, whose defining quantity the score weights at 0.35. The other
model-independent criterion, DEAD_CAPTURE, fires on nothing in this corpus, so a reader
following its 0.15 weight is following a loop that does not exist in the data. The honest
reading is that this measurement is a check on internal consistency and on the size of the
space the gate was set in, not an independent test of the ranking.

The queue's headline result is inconclusive, and that is the honest reading:
1.582x is above the 1.5x threshold as a point estimate,
but its interval contains 1.5, so the evidence does not exclude a queue that clears the
bar by nothing. It also sits entirely above 1.0, so the ranking is not nothing either.
The cold-station split, the one where a reviewer meets stations the model never trained
on, does clear the threshold. It does not substitute for the primary split and is not
presented as if it did.

## Feasibility

Whether this could be run by the people whose problem it is, on the hardware they have.

| Question | Answer | Where |
|---|---|---|
| What does it cost to run? | Nothing per observation. No cloud inference on any judged path: Granite runs locally, the console is a static export, and the one serverless function is 220 lines of Python on a free tier. | `vercel.json`, `api/live.py` |
| Does it keep up with the network? | The dominant measured stage is the corridor fit, at **68,702 observations a day on one core** against **6,380** a day arriving from the network. Read the caveats and not the ratio: the network rate is extrapolated from a 9.4-hour span, the timing covers two stages, and the core count is a division rather than a measured speed-up. | `artifacts/THROUGHPUT_RECEIPT.json`, `docs/SCALABILITY.md` |
| How big is the install? | 166 MB for the base install. The `full` extra that reproduces every receipt is 4,643 MB and is an extra for that reason. Measuring one live observation needs neither. | `pyproject.toml` |
| Can it be used without a mouse? | Measured rather than intended. `scripts/check_contrast.py` recomputes all 26 rendered colour pairs against WCAG AA, and `tests/test_console_accessibility.py` parses all 34 built pages for keyboard reachability and an accessible name on every control. Both run in the standing gate. | `docs/DESIGN_SYSTEM.md` |
| Who would deploy it, and when? | A station operator or a university ground-station team, on a laptop, this week: `pip install -e .` then `tracetriage triage <id>`. It writes nothing back to SatNOGS and holds no credential, so adopting it needs nobody's permission. | [Run it yourself](#run-it-yourself) |
| What breaks it at scale? | Waterfall bytes, not compute. A 10,000-observation snapshot is roughly 17 GB of PNG, which is the constraint the recon document names before the first download rather than after. | `docs/SATNOGS_API_RECON.md` |

## Real-World Impact

The measured problem is that most passes are never decisively reviewed, and the people it
costs are the ones running small missions on shared, volunteer-built infrastructure.

- **The backlog is real and it is the norm, not a corner case.** 426 of 600 consecutive
  observations carry no decisive human verdict. Those 600 come from **211 distinct ground
  stations**, so this is a property of the network rather than of one station's habits.
- **An unreviewed pass is not a missing image, it is missing information.** For a cubesat team,
  a pass that nobody confirmed is a beacon they cannot count as heard. That decides whether a
  spacecraft is declared alive, whether a frequency licence report has evidence behind it, and
  whether a student's thesis has data.
- **What changes with a ranked queue.** On ground stations the queue was never fitted to, a
  fixed review budget finds **2.253x** as many independently reviewable conflicts as reviewing
  the same number of passes at random, 95% CI [1.920, 3.859]. On the pre-registered
  chronological split the same measurement is 1.582x and inconclusive. Both are published at
  the same size, because the honest impact claim is the pair and not the better half.
- **Nothing has to be added to the network for this to work on it.** Every input is already
  published under CC BY-SA: the observation's own stored TLE, its timing and its receiver
  metadata. That is why the same code measures a pass recorded an hour ago and one from the
  frozen snapshot.
- **The finding outlives the queue.** Whether a station's software already removed the Doppler
  shift is not recorded anywhere in the observation record and is measurable from the image at
  54.2 sigma against 7.3. Any project that fits a shape to a SatNOGS waterfall needs that
  distinction, and `docs/DOPPLER_CORRECTION_FINDING.md` states it in a form somebody else can
  use without this repository.

What it does not claim: that a reviewer's minutes per confirmed finding improve. Half that
number is measured (25.0 seconds median per plate over 72 blinded plates) and half is not, and
the unmeasured half is [named as such above](#measured-results) rather than estimated.

## Where it runs

One engine, six surfaces. Every row is reachable now, with no account.

| Surface | What it is | Where |
|---|---|---|
| **Web console** | 8 routes, 34 pre-rendered pages, no database and no credentials. Seven of the eight fetch nothing at runtime. | [tracetriage.vercel.app](https://tracetriage.vercel.app/) |
| **Installable, offline** | Add to Home Screen on Android or iOS, no store account. All 8 pages of the rail render with the network switched off, in the console's own fonts, measured in a browser rather than asserted. | `artifacts/OFFLINE_RECEIPT.json` |
| **Android app** | Signed APK on the releases page. Three screens: the ranked queue, the fitted Doppler corridor drawn over the waterfall, and a live measurement of any observation id. | [`mobile/`](mobile/README.md) |
| **Live measurement** | One Python serverless function measures an observation recorded today from the public API. | `api/live.py` |
| **Health and provenance** | `/api/health/` returns the SHA-256 of the `provenance.json` this deployment serves, so a judge can prove the site is this repository rather than take a screenshot's word for it. | `api/health.py` |
| **Two MCP servers and a CLI** | 12 tools, 11 read-only, registered in `.mcp.json` so a clone needs no configuration. Plus a LangChain adapter over the same function objects and two LangFlow flows. | `docs/USE_WITH_YOUR_AGENT.md` |

Eight pages: a start page mapping each judged criterion to the page answering it, the review
queue, a live console measuring an observation recorded in the last few hours, the evaluation
with every gate including the ones that did not pass, the agent study beside its control arm,
the precedent study with the condition that takes its result away, the baseline orderings the
queue has to beat, and the provenance of each number. The eighth is the live console, and it is
the one exception to "fetches nothing": it calls `api/live.py`, which fetches one waterfall from
the public SatNOGS API on demand and measures it. No number this project was scored on comes
from that path.

The last row is the one to weigh for an AI-builders submission: the surfaces that matter here
are the ones an agent can drive, and this exposes the same measurements to a human, to a phone
and to somebody else's model over a protocol.

## Run it yourself

Python 3.12, Node 24 and [uv](https://docs.astral.sh/uv/). No service, no key, no model
download for the judged path.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[full,dev,onnx]"   # .venv/Scripts/python.exe on Windows
.venv/bin/python -m pytest -m "not network and not ocr and not llm"
```

That pytest selector is the offline replay and it is the gate. `ocr` needs the `[ocr]` extra
and the weights easyocr reads, and `llm` needs the local model runtime, neither of which exists
on a clean runner, so a run including them would fail for reasons that say nothing about the
replay path. Everything that publishes a number runs inside it.
`.github/workflows/ci.yml` runs the whole path on Ubuntu and is the version to copy; commands
elsewhere in this repository use the Windows interpreter path because that is the machine they
were recorded on.

The console is separate and needs no Python:

```bash
cd apps/web && npm ci && npm run build
```

**One live measurement, in about twenty seconds:**

```bash
pip install -e .
tracetriage triage 14740031          # measure an observation recorded today
tracetriage station 1696 --budget 6  # a station's own frequency error, across satellites
```

**From your own agent**, with no credential. `.mcp.json` at the root registers both servers,
so a clone has them with nothing to configure.
[`docs/USE_WITH_YOUR_AGENT.md`](docs/USE_WITH_YOUR_AGENT.md) has a config block for Claude
Code, Claude Desktop, Cursor, Windsurf and Zed.

| Server | Answers from | Auto-approved, and what asks first |
|---|---|---|
| `tracetriage-evidence` | the receipts committed here, offline | 7 tools, read-only enforced by parsing its own imports. `alwaysAllow` covers the six that only read: `queue_top`, `queue_size`, `observation`, `check_claim`, `gate_status`, `receipt`. `run_acceptance` runs the standing gate, which writes the console build, so it asks |
| `tracetriage-live` | the public SatNOGS API, now | 5 tools. `alwaysAllow` covers `live_list_observations`, `live_triage_observation` and `live_check_claim`; `live_rank_observations` and `live_station` measure up to 10 and up to 6 observations at two HTTP fetches each, so they ask first |

The live tools carry a `live_` prefix because a number measured this minute and a number this
project was scored on must not be confusable by an agent reading a tool result.

## How this repository keeps itself honest

Every number in this file is generated from a frozen artifact under `artifacts/` and carries a
row in `docs/CLAIM_REGISTER.md`. Three mechanisms do most of the work:

- **Claims are compared against artifacts, not against a register.** `tests/test_claim_drift.py`
  reads each quoted value out of the receipt it came from. Editing the AUC row from 0.875 to
  0.999 turns three tests red.
- **Six documents are generated and fail the gate when they drift.** Each generator takes
  `--check`, which regenerates into memory and exits non-zero on any difference.
- **`scripts/gate.py` runs every standing check in one command and prints its own tally**, and
  `scripts/signoff.py` refuses to sign a release while any of them has failed.

What CI rebuilds on a clean Ubuntu clone, and how the console is stopped from showing a number
the receipts do not carry, is in
[`FOR_JUDGES.md`](FOR_JUDGES.md#seven-checks-worth-running-first).

## Scope, and what is already done elsewhere

SatNOGS already assigns observation and waterfall statuses. Public projects already classify
waterfalls with CNNs. STRF-based tooling already extracts Doppler traces. **TraceTriage claims
novelty for none of those.**

The contribution it defends, measured against the three rungs in
`docs/PRIOR_ART_BASELINES.md` and the ten-arm ladder in `artifacts/FUSION_RECEIPT.json`, is the
combination of calibrated selective prediction, expected residual geometry fused with image
evidence, explicit label-provenance and disagreement analysis, queue ranking by measured review
value, per-observation evidence receipts, and evaluation by findings per fixed review budget
under temporal and entity holdouts.

If the physics does not improve probability quality, or the queue does not beat random ordering
at the same budget, the correct outcome is to stop and document the failure. That is what
`docs/KILL_GATE.md` is.

## Further reading

| Document | What is in it |
|---|---|
| [`FOR_JUDGES.md`](FOR_JUDGES.md) | The judged criteria one by one, with the command that regenerates each claim |
| [`docs/KILL_GATE.md`](docs/KILL_GATE.md) | Every gate in full, including the failure log and the verdict that was withdrawn |
| [`docs/DOPPLER_CORRECTION_FINDING.md`](docs/DOPPLER_CORRECTION_FINDING.md) | The finding this project rests on: the record cannot tell you whether a waterfall was Doppler corrected, and the image can |
| [`docs/CLAIM_REGISTER.md`](docs/CLAIM_REGISTER.md) | Every published claim, its receipt and the test that checks it |
| [`docs/PRIOR_ART_BASELINES.md`](docs/PRIOR_ART_BASELINES.md) | What is already done elsewhere, and the three rungs this project has to clear instead |
| [`docs/SCALABILITY.md`](docs/SCALABILITY.md) | Whether it keeps up with the network, measured, with the four things the measurement does not cover |
| [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md) | Why the palette is derived from the data rather than chosen, and the two accessibility defects that derivation caught |
| [`docs/ACTOR_AND_PERMISSION_CONTRACT.md`](docs/ACTOR_AND_PERMISSION_CONTRACT.md) | What this system is permitted to do, enforced by test |
| [`docs/USE_WITH_YOUR_AGENT.md`](docs/USE_WITH_YOUR_AGENT.md) | Both MCP servers, with a config block per client |
| [`mobile/README.md`](mobile/README.md) | The Android client, how to build it, and how to check what signed the APK |
| [`presentation/REPORT.md`](presentation/REPORT.md) | What the film claims, card by card, with the receipt key each figure was resolved from |

## Licence

Code: MIT, see `LICENSE`. SatNOGS data and derived artifacts: CC BY-SA 4.0, see
`DATA_LICENSE.md`.

Author: Kesav2k04 <kesavk659@gmail.com>
