# Bob task prompts

Paste-ready units. Each one is scoped to a single acceptance-defined deliverable so Bob spends coins building rather than planning, and so a session that dies mid-wave loses at most one unit.

**How to use:** paste the master prompt once per new trial account. Then paste one unit at a time, in order. Do not paste a whole wave.

**Estimates are risk budgets, not promises.** Actual Bobcoin consumption controls the cutoff. Log the real number in `docs/BOB_BUILD_LOG.md` after each unit and correct the estimate for the next account.

---

## The bar every unit prompt must clear

A vague prompt does not fail cheaply. It burns coins producing something plausible that has to be thrown away, and on a 40-coin account that is the difference between shipping Wave B and not. The Wave A units below were written against these six tests, and **any prompt added for Waves B, C or D must pass all six before it is pasted.**

**1. Falsifiable acceptance.** Every unit ends in checks that can only come back pass or fail. "Tests pass" is not one. "Hz/px within 1% of 123.46 and 80.00 on the two committed fixtures" is. If a reviewer cannot run the check and get a verdict without judgement, rewrite it.

**2. Carries the verified facts inline.** Each unit repeats the specific measurements it depends on, with numbers, rather than pointing at a document and hoping. A0 restates that `client_metadata` is a JSON string. A2 restates both Hz/px values. Redundancy is cheap; a coin spent rediscovering a known fact is not.

**3. Names the trap.** Every unit that has a known failure mode states it and what it costs. A2 says assuming `samp-rate-rx` compresses the corridor from 118 px to 5 px. A6 says beating an uncalibrated baseline proves nothing. A prompt that only describes the happy path invites the exact failure it was meant to avoid.

**4. One deliverable, one seam.** A unit produces one artifact and one testable boundary. A7 is deliberately thin, one observation end to end, because the point is proving the seam before Wave B builds volume on it. Units that bundle two deliverables cannot be resumed cleanly when an account runs dry mid-task.

**5. Blocking dependencies are marked as blocking.** A3 answers the Doppler-correction question and blocks A4, and says so in capitals. An unmarked dependency gets built past, and the rework costs more than the original unit.

**6. States what a failure looks like.** A3 says an ambiguous result must be reported as ambiguous rather than resolved by preference. A7 says a gate-3 failure requires re-verifying the Hz/px derivation before the failure is accepted. Prompts that only define success quietly pressure the model to manufacture it.

### Judging a unit before pasting it

Score it honestly, and rewrite anything scoring below 4:

| Dimension | 5/5 looks like |
|---|---|
| **Quality** | acceptance checks are mechanical, and the unit names its own traps |
| **Impact** | it closes a gate, unblocks a dependency, or removes a load-bearing unknown |
| **Outcome** | the artifact it produces is one a judge could open and verify |

A unit that cannot state which kill gate it advances, or which unknown it removes, is not ready to be pasted. Fix the prompt before spending the coin.

---

## Master prompt (paste once per Bob account)

```text
You are the primary development tool for my solo August 2026 AI Builders Challenge
submission. Read .bob/rules.md and docs/BOB_HANDOFF.md before doing anything else.

Competition:
- Entering only "Advance Space Exploration with AI" (August theme).
- Target: August first place and Grand Prize candidate.
- You must remain the primary development tool and build every load-bearing subsystem.
- Other AI may review or improve bounded areas; you review, test and accept or reject.
- No paid service. All caches, weights and build output on D:\, never C:\.

Project:
TraceTriage is a read-only, physics-conditioned review queue for public SatNOGS
waterfall observations. A reviewer has more observations than they can inspect.
Given a fixed review budget, rank which existing public observations deserve human
review because image evidence, expected corrected Doppler behaviour, metadata and
the current network label disagree or remain uncertain.

Already done before your first task (do not redo):
- Repository at github.com/Kesav2k04/tracetriage-august-2026 (private until the
  code freeze), venv on Python 3.12, full stack installed and import-verified.
- Live API reconnaissance with measured numbers: docs/SATNOGS_API_RECON.md
- Kill-gate status board, 3 of 6 gates pre-measured: docs/KILL_GATE.md
- Hardware profile. There is an RTX 3070 Ti and CUDA torch is installed and
  verified at 14.9x over CPU. USE IT, and guard against a silent CPU fallback.
  16 GB RAM is the binding constraint, so stream every stage: docs/HARDWARE_PROFILE.md
- Every literal submission requirement, quoted, with status: docs/SUBMISSION_CHECKLIST.md
- Draft data contracts you must review and ratify: contracts/
- Doc skeletons, licences, CI config, .gitignore.
Full inventory with the exact boundary: docs/PREPARED_BY_CLAUDE.md

Nothing on the judged path was written for you. Ingestion, physics, model,
calibration, abstention, ranking, evidence UI, tests and release acceptance are
all yours.

Execution rule for every task:
Inspect the repo and handoff first. Do not recreate finished files. Work on one
acceptance-defined unit at a time. Before editing, state the exact files you will
create, the commands you will run, the acceptance checks, and your estimated
Bobcoin risk. Run the tests before reporting completion. Never claim completion
when an artifact, metric or external validation is missing.

Acknowledge by listing what already exists and which unit you are starting.
```

---

# Wave A: snapshot, physics, baseline, first evidence slice

Target: **~14 coins.** Owns the kill gate, data contracts, immutable snapshot, label provenance, first physics overlay, image baseline, and one end-to-end evidence card.

---

### A0. Ratify the data contracts *(~1 coin)*

```text
Read contracts/*.schema.json. They are DRAFTS written before your first task and
are not authoritative until you ratify them.

For each schema: check it against the real field list in
docs/SATNOGS_API_RECON.md section 2, and against what the pipeline will actually
need. Fix anything wrong, add anything missing, delete anything speculative.

Pay particular attention to:
- client_metadata is a JSON-encoded STRING, not a nested object
- center_frequency is null in practice; rx-freq inside client_metadata is the truth
- Hz-per-pixel and the plot bounding box are per-observation, not constants

Then set "status": "ratified" and bump schema_version on each file you accept.

ACCEPTANCE:
- every contracts/*.schema.json has status "ratified" and a version
- a one-paragraph note in docs/BOB_BUILD_LOG.md on what you changed and why
```

---

### A1. Immutable snapshot builder *(~4 coins)*

```text
Build pipeline/tracetriage/snapshot.py: fetch a bounded, reproducible snapshot of
public SatNOGS observations and their waterfall artifacts.

Verified facts, do not rediscover (docs/SATNOGS_API_RECON.md sections 1, 4, 9):
- observations are on network.satnogs.org, NOT db.satnogs.org (that 404s)
- use bare `end=<ISO8601>`; `end__lte=` returns HTTP 200 and is SILENTLY IGNORED
- `waterfall_status=` is NOT a filter (HTTP 400). Filter it client-side.
- page via the cursor in the `Link: <...>; rel="next"` response header
- a bare listing returns FUTURE observations with null waterfalls; always date-bound
- no auth needed; send a real User-Agent with a contact address; 0.4s between requests

SNAPSHOT SIZE IS DECIDED AND STAGED. Do not re-derive it, do not scale it down.
Disk is NOT a constraint (954 GB NVMe, 103 GB free on D:, 1 TB external available).

  Stage 1:  2,500 observations  ~4 GB   ~45 min
  Stage 2: 30,000 observations ~47 GB   ~5 h, run OVERNIGHT

Build stage 1 first and move on. It unblocks kill gates 3, 4 and 5 immediately
and is enough to build and debug every Wave A module. Kick stage 2 off in the
background while you work on Wave B. Resumability (below) is what makes this free.

The arithmetic, from the measured rates in docs/KILL_GATE.md gate 1:
  30,000 observations
  x 92.3% waterfall presence   = ~27,700 waterfalls = ~47 GB at 1.7 MB mean
  x 10.17% without-signal      = ~3,050 decisive NEGATIVES
  x 18.83% with-signal         = ~5,650 decisive POSITIVES
Why not 2,000: it yields ~200 decisive negatives. When whole stations and
transmitters are held out, each cold-entity test set is a fraction of that, and
a grouped bootstrap over a few hundred examples gives intervals too wide to
claim anything. Statistical power on the cold-entity holdouts is the reason for
the size, not completeness for its own sake.

STRATIFY stage 2. Do not just take a bigger contiguous block, which mostly buys
more of the same stations. Spend the size on: multiple time windows (so the
chronological holdout tests real drift), deliberate coverage of rare client
families (at least six exist, 6% of records have NO client version, and the
"unsupported client format" failure state needs real examples), and enough
distinct stations and transmitters reserved for the cold pools that holding
them out still leaves a usable training set. Record the sampling design in the
manifest: a stratified sample described as random is a leakage claim that will
fail review.

MEMORY IS THE REAL CONSTRAINT, NOT DISK. 16 GB RAM. A 47 GB snapshot cannot be
loaded, and neither can a tenth of it. Stream everything: polars.scan_parquet
not read_parquet, batch the images, release arrays between batches. A 9,230-image
RGB stack at 604x1550 is ~26 GB in float32 and does not fit. See
docs/HARDWARE_PROFILE.md.

Check free space before each stage and abort with a clear message if short.
Do not part-download.

Requirements:
- CLI: --end <ISO8601> --target-waterfalls <N> --out data/snapshots/<id>/
  (default N=10000; the flag exists for small test runs, not for shrinking the real one)
- store the RAW json response per page, unmodified, plus a sha256 of each
- store per observation: retrieval timestamp (UTC), source URL, sha256 of the
  waterfall bytes, CC BY-SA 4.0 licence string, schema_version
- resumable: re-running must not re-fetch anything already stored
- write artifacts/DATASET_MANIFEST.json: observation IDs, URLs, hashes, retrieval
  times, licences, counts, schema version, and the exact query used
- normalise client_version (strip +N.g<sha> and .dirty suffixes) into a separate
  client_family column; keep the raw string too

ACCEPTANCE:
- fetch 50 observations end-to-end, twice; second run re-fetches zero pages
- DATASET_MANIFEST.json validates against contracts/dataset_manifest.schema.json
- every stored waterfall's sha256 matches its manifest entry
- tests/test_snapshot.py covers: silently-ignored filter regression (assert a
  bare `end=` bound is actually respected in the returned data), cursor
  exhaustion, a 404 artifact, a truncated download, and resume-after-interrupt
- pytest -m "not network" passes with the network disabled, using fixtures
```

---

### A2. Waterfall artifact parser *(~3 coins)*

```text
Build pipeline/tracetriage/waterfall.py: turn a SatNOGS waterfall PNG into a
calibrated array plus its frequency and time mapping.

This is the unit where a wrong constant silently destroys the project. Read
docs/SATNOGS_API_RECON.md section 7 in full before starting.

Verified, do not assume otherwise:
- the image does NOT span samp-rate-rx. Measured Hz/px was 123.46 on one client
  and 80.00 on another, against a 2.5 MHz sample rate. A ~32x decimation that
  NOTHING in the API reports.
- derive Hz/px from the rendered matplotlib axis ticks, per observation
- the plot box is not the image box: measured x=66..686 (836px client) and
  x=74..677 (832px client); one client renders a colorbar at x=724..755
- images are RGBA PNG. Convert to RGB or the alpha becomes a fourth feature plane.
- height was 1603px in samples but is the TIME axis and must scale with duration

Requirements:
- return: cropped plot array (RGB), plot box, hz_per_px, seconds_per_px,
  centre-frequency pixel column, and a confidence flag on the derivation
- if the axis cannot be read, return an explicit degraded state. Never guess.
- scripts/recon/measure_axis.py has a working detection method; it is recon-grade.
  Write the production version properly and test it.

ACCEPTANCE:
- tests/test_waterfall.py asserts Hz/px within 1% of 123.46 and 80.00 on the two
  fixture layouts, committed to tests/fixtures/
- the crop excludes all axis text and the colorbar (assert on pixel content)
- malformed PNG, blank image, zero-byte file and unknown layout each return a
  named degraded state rather than raising
- a property test: crop box is always strictly inside the image bounds
```

---

### A3. Resolve the Doppler-correction question *(~2 coins)*

```text
BLOCKING RESEARCH UNIT. Do not build the corridor overlay until this is answered.
Nothing downstream is valid if this is wrong, and getting it wrong fabricates
evidence, which is the single worst outcome available to this project.

The question: are SatNOGS waterfalls already Doppler-corrected at capture time?

What is known (docs/SATNOGS_API_RECON.md section 8):
- client_metadata.radio.parameters.doppler-correction-per-sec was null on every
  record inspected
- rigctl-port was populated ("4532") on those same records, which suggests
  correction happened externally via rig control rather than in the flowgraph

Method:
- take 10 observations with waterfall_status = with-signal, across at least 3
  client families and a range of max_altitude
- compute the expected Doppler curve from the stored TLE (the geometry chain is
  already verified to 0.18 deg, see section 10 -- build on it, do not re-verify)
- overlay BOTH hypotheses on each image: (a) full S-curve, uncorrected;
  (b) near-vertical residual corridor, corrected
- look at where the actual trace sits

Deliverable: docs/DOPPLER_CORRECTION_FINDING.md stating which hypothesis holds,
with the 10 overlay images as evidence, the per-client-family breakdown, and an
explicit statement of what remains uncertain.

ACCEPTANCE:
- a stated answer with images, not a hedge
- if the answer differs by client family, that is a finding, report it as one
- if the evidence is genuinely ambiguous, say so and stop; do not pick one
- update .bob/rules.md rule 5 with the resolved fact
```

---

### A4. Physics corridor module *(~3 coins)*

```text
Build pipeline/tracetriage/physics.py: expected-frequency corridor for an
observation, from its own stored metadata. No external TLE lookup, no join.

Already verified, build on it rather than re-testing (section 10):
- the observation's own tle1/tle2 + station_lat/lng/alt + start/end reproduced
  pass geometry to 0.18 deg against the API's reported max_altitude
- range rate flips sign exactly at peak elevation
- a 207s pass at 436.4 MHz gave a 14,631 Hz swing = ~118px at 123.46 Hz/px

Requirements:
- SGP4 propagation, geodetic station position, proper ECI->ECEF (the recon script
  used a first-order GMST adequate only for feasibility; do this properly)
- output the corridor per the finding from A3, with a width band, not a bare line
- validate against the API's own rise_azimuth, set_azimuth and max_altitude on a
  few hundred observations and report the error distribution, not one example
- explicit degraded states: missing TLE, stale TLE (epoch far from pass),
  SGP4 non-zero error code, missing station coords, missing frequency

ACCEPTANCE:
- tests/test_physics.py with fixed-case tests: known pass -> known elevation
  profile, sign flip at TCA, and a deterministic corridor for a frozen input
- max_altitude agreement reported as a distribution over >=200 observations,
  written to artifacts/PHYSICS_VALIDATION.json
- every degraded state returns a named reason code, none raise
- zero network access in the tests
```

---

### A5. Label provenance builder *(~2 coins)*

```text
Build pipeline/tracetriage/provenance.py and docs/LABEL_PROVENANCE.md.

Separate, and never collapse: observation `status`, `waterfall_status`, vetting
user and datetime, automatic ratings, and local annotations.

Rules:
- waterfall_status is SILVER evidence, not truth
- `unknown` stays unlabelled. Never coerce it to a negative.
- a MISSING waterfall is artifact-unusable, NOT a negative example
- measured base rates to carry forward: 29.0% decisive overall, with a 1.85:1
  positive-to-negative imbalance among decisive labels (docs/KILL_GATE.md gate 1)

ACCEPTANCE:
- a provenance record per observation validating against its contract
- tests asserting unknown never becomes a training label and missing-waterfall
  never becomes a negative
- docs/LABEL_PROVENANCE.md explains each label origin and its known failure modes
```

---

### A6. Image-only baseline *(~2 coins)*

```text
Build the first two rungs of the model ladder as the honest baseline everything
later must beat: a centre-energy heuristic, and HOG plus regularised logistic
regression, both CALIBRATED.

Calibration matters here specifically. Gate 5 requires the physics model to beat a
CALIBRATED image-only baseline. Beating an uncalibrated one proves nothing except
that calibration works.

Requirements:
- temporary chronological split only. Do not touch the frozen test set.
- report Brier score, log loss, calibration slope and intercept, reliability plot
- write artifacts/BASELINE_RECEIPT.json with every number and the input hashes

ACCEPTANCE:
- both baselines train and score reproducibly from a fixed seed
- BASELINE_RECEIPT.json exists and its numbers regenerate identically on re-run
- docs/PRIOR_ART_BASELINES.md records what these are and why they are the bar
```

---

### A7. End-to-end evidence card slice *(~3 coins)*

```text
One observation, all the way through: snapshot -> waterfall parse -> physics
corridor -> provenance -> baseline score -> evidence receipt -> rendered card.

Thin but complete. No breadth. The point is proving the seam works before Wave B
builds volume on top of it.

Requirements:
- artifacts/TRIAGE_RECEIPT.json for that one observation, matching its contract
- a rendered card (static is fine) showing: waterfall, corridor, detected trace,
  residual, artifact checks, current API label, provenance, source link,
  deterministic reason codes
- every reason code comes from a fixed rule table, never from a model attribution

ACCEPTANCE:
- the receipt regenerates byte-identically from the same snapshot and seed
- the card renders with the network disabled
- gate 3 can now be evaluated: state whether the corridor intersects the trace
- update docs/KILL_GATE.md gate 3 with the result. If it FAILS, re-verify the
  Hz/px derivation before accepting the failure (section 7 explains why).
```

---

# Wave B: splits, fusion, calibration, abstention

Target: **~14 coins.** Do not start until gates 3, 4 and 5 have recorded results.

- **B1** Grouped split builder and leakage audit. Chronological, cold-station, cold-transmitter, combined. Each transmitter and orbital revolution in exactly one split. Emit `artifacts/SPLIT_MANIFEST.json` and `artifacts/LEAKAGE_AUDIT.json`. Test that a duplicate image cannot cross a split. *(~3)*
- **B2** Fusion head over image, metadata and physics features. Compare against every earlier rung. *(~3)*
- **B3** Calibration on a later time period: temperature and isotonic, pick by measured reliability, not by preference. Multi-seed head ensemble for uncertainty. *(~2)*
- **B4** Selective prediction and abstention, with risk-versus-coverage curves. Conformal only if it earns its place. *(~3)*
- **B5** Out-of-distribution scoring for unseen stations, transmitters, client formats and bands. *(~2)*
- **B6** Ablation harness and cold-entity slices, grouped bootstrap by orbital episode or day. Every rung of the ladder gets an ablation row. Delete what does not earn its place. *(~1)*

Gate 5 closes here. Gate 6 needs B1 plus Wave C.

---

# Wave C: queue, annotation, console

Target: **~14 coins.**

- **C1** Review-value ranking: disagreement, physics conflict, uncertainty, novelty, coverage gaps. *(~3)*
- **C2** Duplicate control and entity-concentration limits, so one noisy station cannot flood the budget. *(~2)*
- **C3** Local annotation. Writes to local storage only. A test must assert no outbound write to SatNOGS is even possible. *(~2)*
- **C4** Active-selection replay against random, FIFO, entropy-only and image-confidence orderings. **Gate 6 closes here.** *(~3)*
- **C5** Static evidence console: Next.js, TypeScript, Carbon. Queue, evidence card, frozen replay, provenance panel, evaluation view. *(~3)*
- **C5b** **Deploy it to Vercel and keep it live.** Not a Wave D task. See the note below. *(~1)*
- **C6** Accessibility and failure states: keyboard operation, contrast, reduced motion, no WebGL, and an explicit degraded state for every failure in the injection list. *(~1)*

> ### Why deployment moved out of Wave D
>
> The rules never say judges will clone and run the repository. They say it must be "publicly accessible so judges can **review and score**" it. For the June 2026 entry the judges opened the deployed app, watched the video, and read the repo. They did not clone it.
>
> So the live URL is the artifact that carries "functional and well-structured solution" and "practicality" for a reviewer with three minutes. Deploy as soon as the console renders one real evidence card, then iterate on a URL that stays up. A link that has been live and improving for ten days is a different artifact from one that appears the night before the deadline.
>
> **This changes nothing about the rigor.** Clean-clone reproduction, offline replay, grouped holdouts and claim-drift tests all still get built in Wave D. They are not for the judges' hands. They are what makes the numbers real, and they cover the case where a judge does clone it. Skipping them to chase the demo would be exactly the compromise this project cannot afford.
>
> The console is already designed to deploy cleanly: static, precomputed replay, no database, no cloud inference, no credentials. Nothing can break in front of a judge because a backend went down.

---

# Wave D: release hardening

Target: **~12 coins.**

- **D1** Failure injection across the full list: malformed image, blank image, missing TLE, stale TLE, absent frequency bins, wrong start offset, multiple traces, network outage, missing model, unsupported client format, empty queue, Granite timeout. Each returns a named degraded state. *(~3)*
- **D2** Claim register and drift tests. Every README and video number maps to a generated receipt, and a mutation test fails when they diverge. *(~2)*
- **D3** Clean-clone reproduction from scratch, network disabled, on a fresh checkout. *(~2)*
- **D4** Secret scan (zero findings) and CC BY-SA attribution audit across every redistributed artifact. *(~1)*
- **D5** Generated documentation, deployment of the static console, video fixture capture. *(~2)*
- **D6** **Final Bob acceptance.** Inspect the release commit, run every acceptance check, repair failures, generate the sign-off receipt. This task must be Bob's, on the release commit, and it is the evidence that Bob owned the judged path. *(~2)*
