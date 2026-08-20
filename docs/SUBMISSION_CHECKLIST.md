# Submission checklist

Every row quotes the requirement **verbatim** from `Challenge_Details.md` and names the artifact that satisfies it. Nothing here is inferred. Where the source document contradicts itself, both readings are recorded and the stricter one is targeted.

**Deadline: 31 August 2026, 11:59 PM ET.** That is 1 September 09:29 IST. Do not plan against a local-midnight assumption.

---

## The four literal requirements

Quoted from `Challenge_Details.md` lines 94 to 110.

### 1. "A working prototype or proof of concept using IBM Bob (required primary development tool)"

| | |
|---|---|
| Artifact | the running TraceTriage console plus the pipeline behind it |
| Evidence Bob was primary | `docs/BOB_BUILD_LOG.md` (every accepted unit, dated, with the files it changed), `docs/BOB_HANDOFF.md`, `.bob/rules.md`, `.bob/TOOL_SPECS.md`, `.bob/mcp.json`. `bob_sessions/` was removed in E0: it held a single `.gitkeep`, git does not publish an empty directory, and a pointer that resolves to nothing on GitHub is worse than an absence that is named. The README says so in `## How IBM Bob was used`. |
| Boundary proof | `docs/PRE_BUILD_BASELINE.md` |
| Status | **built.** Waves A to E are closed. The pipeline ingests, parses, fits, scores, ranks and explains; the console is deployed and live; 19 standing gates pass; 1,315 offline tests pass with none skipped and 4 deselected by marker of 1,319 collected; a clean clone with every non-loopback socket refused completes 15 of its 16 steps and the one that fails is an offline package install, disclosed with its cause. `artifacts/SIGNOFF_RECEIPT.json` records the final acceptance at `4d380b4`: 10 checks, 10 passed, none failed and none not checked, including a live probe of the deployed console. |

Official Rules line 197 phrases the same requirement as "Use of IBM Bob as the **core component** of all project submissions", and explicitly permits watsonx, Granite, LangFlow and Docling **in addition**. Granite is already planned as a conditional component.

### 2. "Every team member must complete at least one IBM Bob-related course or webinar on IBM SkillsBuild and upload their completion certificate as proof"

| | |
|---|---|
| Artifact | completion certificate PDF, uploaded to the submission page |
| Status | **not started. Solo entry, so one certificate.** |

This is a **hard eligibility gate, not a scoring item.** No certificate means the entry is not judged at all, regardless of how good the build is. It has nothing to do with Bob's work queue, so it can be done any evening this week. Do it early.

### 3. "A public GitHub repository with a clear README"

Required README sections, quoted:

| Required section | Present in `README.md`? |
|---|---|
| Problem statement | yes, `## Problem statement` |
| Solution description | yes, `## Solution description` |
| AI approach and architecture | yes, `## AI approach and architecture`, 13 numbered pipeline steps |
| Selected challenge theme | yes, `## Selected challenge theme`: "Advance Space Exploration with AI" |
| How IBM Bob was used | yes, `## How IBM Bob was used`, with `docs/BOB_BUILD_LOG.md` behind it |

`## The IBM stack, and where each piece is` names all five IBM components with the file that
carries each, because four of them were used and never claimed.

Official Rules line 199 states a shorter list: "Problem statement, AI/technical approach, Solution description". **The five-item list is the superset, so target it.** Where a document disagrees with itself, satisfy the stricter reading.

Repository: **https://github.com/Kesav2k04/tracetriage-august-2026**, created 2026-08-16, **currently PRIVATE**.

Naming follows the June 2026 convention (`decisionlens-june-2026`), which placed 2nd.

> **Flip it to public before the deadline.** This is a hard eligibility line: "Your GitHub repository and video link must be publicly accessible so judges can review and score your submission." Private now protects the approach from other August entrants during the build; changing visibility does **not** alter commit dates, so the day-by-day Bob history stays visible to judges either way. Target the flip for **25 August**, which is the date the running status below also carries, and then verify every judge-facing link from a logged-out browser: the repository root, `FOR_JUDGES.md`, and the three documents the console's footer links to on the repository rather than serving as raw markdown.

### 4. "A published project submission page on the challenge platform"

| Required element | Status |
|---|---|
| Project and team member details | not started. Kesav Jayakumar, single entrant |
| Link to your GitHub repository | `https://github.com/Kesav2k04/tracetriage-august-2026`, created and pushed, **private until 25 August** |
| "A publicly accessible demo or presentation video (maximum 3 minutes)" | not recorded. `docs/DEMO_SCRIPT.md` is the shot list: 7 shots, 160 s against the 180 s ceiling, generated from the receipts so no spoken number can drift from what the console shows |

> "**Important: Your GitHub repository and video link must be publicly accessible so judges can review and score your submission.**"

Both must be public **before** the deadline, and both must be checked from a logged-out browser. A repo that is public but whose video is unlisted-and-broken, or a video that requires sign-in, fails this line.

---

## What judges actually did last time

For DecisionLens (June 2026, 2nd place) the judges **did not clone the repository and run it.** They opened the deployed Vercel app, watched the video, read the repository and the solution statement, and scored what the project solves.

That is lived evidence about the review path, and it changes priority:

**A live, working deployed URL carries more scoring weight than clean-clone reproduction**, even though a deployed URL is not a literal requirement anywhere in the rules. It is the thing that makes "Technical Execution: functional and well-structured solution" and "Implementation & Feasibility: practicality" concrete for someone who has three minutes and twenty submissions to get through.

Consequences for the build:

1. **Deploy early and keep it live**, rather than deploying in the last week. A URL that has been up and iterated for ten days is a different artifact from one that appeared the night before.
2. **The deployed app must be self-sufficient.** TraceTriage is already designed as a static console over precomputed replay artifacts, with no database, no cloud inference and no credentials, which is exactly the shape that deploys cleanly and cannot break in front of a judge because a backend went down.
3. **The landing state must answer "what does this solve" in one screen.** A judge who opens the URL cold, with no context, must see the decision the product serves before they see any architecture.
4. **Clean-clone reproduction and offline replay still get built.** They are not for the judges' hands, they are the evidence that the numbers are real, and they protect against the one judge who does clone it.

Vercel worked last time, is free, and handles static Next.js. Keep it.

---

## Judging criteria: the document contradicts itself

| Source | Criteria listed |
|---|---|
| Marketing section, line 60 | Technical Execution, Innovation, Challenge Fit, Feasibility, **and Real-World Impact** (five) |
| **Official Rules, section 6, line 203** | Technical Execution, Innovation, Challenge Fit, **Implementation & Feasibility** (four, 1 to 5 each, **max 20 points**) |

**The Official Rules bind**: section 6 states the scale explicitly, and "Decisions of Judges and Sponsor are final and binding." The internal gates in `MASTER_PLAN_TRACE_TRIAGE.md` use the four-criteria, 20-point model, which is correct.

Do not ignore Real-World Impact though. It is not a separate score, but it is the substance of "Challenge Fit: relevance to the challenge and **ability to address real-world problems**". Same content, folded into a different box.

Verbatim definitions to write against:

- **Technical Execution:** "Effective use of IBM Bob and additional technologies, functional and well-structured solution."
- **Innovation:** "Creativity, originality, and unique application of AI."
- **Challenge Fit:** "Relevance to the challenge and ability to address real-world problems."
- **Implementation & Feasibility:** "Practicality, scalability, and potential for real-world use."

Note what is **not** in any official definition: calibration, ablations, grouped holdouts, conformal prediction. Those are how this project earns "functional and well-structured" and "practicality" against strong competition. They are the means, not the rubric. **The video and the README must speak in the judges' vocabulary, not the evaluation harness's.**

---

## Eligibility and scope, from the Official Rules

| Rule | Line | Bearing on this entry |
|---|---|---|
| Student, 18+, at an institution of higher education | 174 to 180 | confirm before submitting |
| "LIMIT ONE (1) SUBMISSION PER INDIVIDUAL" | 192 | one entry |
| "A Team cannot submit more than one (1) Project per monthly challenge" | 192 | August theme only, not Wildcard |
| "The Submission must be written in English" | 192 | applies to README, video narration, submission page |
| Contest period ends 31 August 2026 | 187 | |
| Participants retain IP in their Solution | 226 | MIT plus CC BY-SA is fine |
| Submissions "are not confidential" | 228 | keep the opponent analysis and master plan **outside** the public repo |

That last row is live right now: `MASTER_PLAN_TRACE_TRIAGE.md` and `Ultimate_Opponents_DeepDive.md` sit in `D:\IBM August Challenge\`, one level **above** the repository, so they are not tracked and will not publish. Keep it that way.

---

## Running status

Last checked 2026-08-20, after D15i.

| # | Item | Status | Blocking |
|---|---|---|---|
| 1 | Working prototype via Bob | **done** | Waves A to E closed, sign-off SIGNED |
| 1b | Release gate: two blind internal judges score >=18/20, no criterion below 4 | **run 2026-08-20 and NOT MET.** Four blind seats scored 16, 15, 16 and 15, a mean of 15.5 against a bar of 18, and three of four put Implementation & Feasibility at 3 against a floor of 4. Every seat scored Technical Execution 4 and Innovation 4. The defects they found are closed in D15g, including a landing-page number that could not be true and four wrong intervals in `docs/CLAIM_REGISTER.md`. The scoring, the agreement between seats and what they asked for are in `docs/BOB_BUILD_LOG.md` under D15g | **kill gate 4.** Three of four seats named running it as the single change that would buy the most, and it is the reason the weakest criterion is weak. The blinded 72-item worksheet exists and commits to its sample in advance: `scripts/build_gate4_worksheet.py` builds it and `scripts/score_gate4.py` scores it |
| 2 | SkillsBuild certificate | **not started** | nothing but an evening. It is a hard eligibility gate: no certificate means the entry is not judged at all |
| 3a | Public GitHub repo | created, **private** | flip to public on 25 August, then verify from a logged-out browser |
| 3b | README with all five sections | **done**, all five present and generated where they quote a number | nothing |
| 4a | Submission page | not started | needs 3a and 4b |
| 4b | Video, max 3 minutes, public | not started; `docs/DEMO_SCRIPT.md` is the shot list, 7 shots and 160 s of the 180 s ceiling, with every spoken number read from a receipt | needs a recording pass |
| 5 | Deployed live URL | **done and live**, https://tracetriage.vercel.app, git-connected so every push redeploys. The sign-off checks it responds | nothing |
| 6 | Repo and video checked from logged-out browser | not done | needs 3a and 4b |

**Four items remain and none of them is code:** the SkillsBuild certificate, making the
repository public, recording the video, and publishing the submission page, which needs the
other three first. Item 6 is the check that follows them.

**A fifth is optional and worth more than it costs.** Item 1b failed on Implementation &
Feasibility, and every seat that scored it 3 gave the same reason: nobody has asked a human
whether the queue helps. Kill gate 4 is the instrument for that question, it is built, its
sample is committed in advance so it cannot be chosen after the fact, and filling in the
worksheet is one person's afternoon. It is the only remaining item that could change a
score rather than an eligibility state.

Item 2 is the one with teeth. The certificate is an eligibility condition rather than a
scoring one, so a submission that scores well without it is not scored at all, and it is
the only remaining item whose cost is measured in hours rather than minutes.
