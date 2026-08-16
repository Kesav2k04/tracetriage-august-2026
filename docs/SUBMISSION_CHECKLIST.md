# Submission checklist

Every row quotes the requirement **verbatim** from `Challenge_Details.md` and names the artifact that satisfies it. Nothing here is inferred. Where the source document contradicts itself, both readings are recorded and the stricter one is targeted.

**Deadline: 31 August 2026, 11:59 PM ET.** That is 32 August 09:29 IST. Do not plan against a local-midnight assumption.

---

## The four literal requirements

Quoted from `Challenge_Details.md` lines 94 to 110.

### 1. "A working prototype or proof of concept using IBM Bob (required primary development tool)"

| | |
|---|---|
| Artifact | the running TraceTriage console plus the pipeline behind it |
| Evidence Bob was primary | `docs/BOB_BUILD_LOG.md`, `docs/BOB_HANDOFF.md`, `bob_sessions/` |
| Boundary proof | `docs/PREPARED_BY_CLAUDE.md` |
| Status | **in progress.** A0 ratified the five data contracts and was accepted at A0b-INT (commit `3df6f98`, 2026-08-16 18:42 IST). 7/7 standing gates, 34 tests. Bob is at unit **A1**, the snapshot builder. `pipeline/tracetriage/` is still empty, so no judged-path code exists yet. |

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
| Problem statement | yes |
| Solution description | yes |
| AI approach and architecture | yes |
| Selected challenge theme | yes ("Advance Space Exploration with AI") |
| How IBM Bob was used | yes (skeleton; fills in as the build log grows) |

Official Rules line 199 states a shorter list: "Problem statement, AI/technical approach, Solution description". **The five-item list is the superset, so target it.** Where a document disagrees with itself, satisfy the stricter reading.

Repository: **https://github.com/Kesav2k04/tracetriage-august-2026**, created 2026-08-16, **currently PRIVATE**.

Naming follows the June 2026 convention (`decisionlens-june-2026`), which placed 2nd.

> **Flip it to public before the deadline.** This is a hard eligibility line: "Your GitHub repository and video link must be publicly accessible so judges can review and score your submission." Private now protects the approach from other August entrants during the build; changing visibility does **not** alter commit dates, so the day-by-day Bob history stays visible to judges either way. Target the flip for the code freeze, roughly 28 August, and then verify from a logged-out browser.

### 4. "A published project submission page on the challenge platform"

| Required element | Status |
|---|---|
| Project and team member details | not started |
| Link to your GitHub repository | blocked on the repo existing |
| "A publicly accessible demo or presentation video (maximum 3 minutes)" | not started; 180-second cut is storyboarded in the master plan |

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

| # | Item | Status | Blocking |
|---|---|---|---|
| 1 | Working prototype via Bob | in progress | A0 accepted, Bob at A1 |
| 1b | Release gate: two blind internal judges score >=18/20, no criterion below 4 | **not started, not tracked anywhere else** | needs 1, and two people who have not seen the build |
| 2 | SkillsBuild certificate | **not started** | nothing. Do it this week. |
| 3a | Public GitHub repo | created, **private**, 4 commits pushed | flip to public at freeze (~28 Aug) |
| 3b | README with all five sections | drafted | fills in as results land |
| 4a | Submission page | not started | needs 1, 3, 4b |
| 4b | Video, max 3 minutes, public | not started | needs a working replay |
| 5 | Deployed live URL | not started | not a literal requirement, but it is what judges opened last time |
| 6 | Repo and video checked from logged-out browser | not done | final week |

Items 2 and 3a are the only ones that need no code. Neither depends on Bob. Clearing them now removes two deadline risks for roughly an hour of work.
