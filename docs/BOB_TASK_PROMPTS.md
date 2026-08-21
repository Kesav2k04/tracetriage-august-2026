# Bob task prompts

Paste-ready units. Each one is scoped to a single acceptance-defined deliverable so Bob spends credits building rather than planning, and so a session that dies mid-wave loses at most one unit.

**How to use:** paste the master prompt once per new trial account. Then paste one unit at a time, in order. Do not paste a whole wave.

**Estimates are risk budgets, not promises.** Actual build credit consumption controls the cutoff. Log the real number in `docs/BOB_BUILD_LOG.md` after each unit and correct the estimate for the next account.

---

## The bar every unit prompt must clear

A vague prompt does not fail cheaply. It burns credits producing something plausible that has to be thrown away, and on a 40-credit account that is the difference between shipping Wave B and not. The Wave A units below were written against these six tests, and **any prompt added for Waves B, C or D must pass all six before it is pasted.**

**1. Falsifiable acceptance.** Every unit ends in checks that can only come back pass or fail. "Tests pass" is not one. "Hz/px within 1% of 123.46 and 80.00 on the two committed fixtures" is. If a reviewer cannot run the check and get a verdict without judgement, rewrite it.

**2. Carries the verified facts inline.** Each unit repeats the specific measurements it depends on, with numbers, rather than pointing at a document and hoping. A0 restates that `client_metadata` is a JSON string. A2 restates both Hz/px values. Redundancy is cheap; a credit spent rediscovering a known fact is not.

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

A unit that cannot state which kill gate it advances, or which unknown it removes, is not ready to be pasted. Fix the prompt before spending the credit.

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
- Kill-gate status board: docs/KILL_GATE.md. Gates 1 and 2 pre-measured, gate 3
  measured and PASSED, gates 4, 5 and 6 open. Gate 4 is an operator task.
- Hardware profile. There is an RTX 3070 Ti and CUDA torch is installed and
  verified at 14.9x over CPU. USE IT, and guard against a silent CPU fallback.
  16 GB RAM is the binding constraint, so stream every stage: docs/HARDWARE_PROFILE.md
- Every literal submission requirement, quoted, with status: kept outside this repository. It reasons about how judges score and when to make this repository public, which is strategy rather than evidence, and `README.md` plus `FOR_JUDGES.md` answer every requirement a reader of the tree needs answered.
- Six data contracts, all ratified. Do not re-ratify them: contracts/
- Doc skeletons, licences, CI config, .gitignore.
Full inventory with the exact boundary: docs/PRE_BUILD_BASELINE.md

Nothing on the judged path was written for you. Ingestion, physics, model,
calibration, abstention, ranking, evidence UI, tests and release acceptance are
all yours.

Execution rule for every task:
Inspect the repo and handoff first. Do not recreate finished files. Work on one
acceptance-defined unit at a time. Before editing, state the exact files you will
create, the commands you will run, the acceptance checks, and your estimated
build credit risk. Run the tests before reporting completion. Never claim completion
when an artifact, metric or external validation is missing.

Acknowledge by listing what already exists and which unit you are starting.
```

---

# Wave A: snapshot, physics, baseline, first evidence slice

Target: **~14 credits.** Owns the kill gate, data contracts, immutable snapshot, label provenance, first physics overlay, image baseline, and one end-to-end evidence card.

---

### A0. Ratify the data contracts *(~1 credit)*

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

### A1. Immutable snapshot builder *(~4 credits)*

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

### A2. Waterfall artifact parser *(~3 credits)*

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

### A3. Resolve the Doppler-correction question *(~2 credits)*

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

### A4. Physics corridor module *(~3 credits)*

```text
Build pipeline/tracetriage/physics.py: the expected-frequency corridor for an
observation, from its own stored metadata. No external TLE lookup, no join.

A3 IS ANSWERED AND IT CHANGES THIS UNIT. Read docs/DOPPLER_CORRECTION_FINDING.md
before writing code. The short version:

- SatNOGS waterfalls are SOMETIMES Doppler corrected and sometimes not. Of 24
  vetted with-signal observations, 4 were corrected (vertical carrier within
  about a kilohertz of the tuned frequency, 32.4 to 54.2 sigma) and 3 were
  uncorrected (energy on the predicted curve, 15.1 to 25.1 sigma).
- NO METADATA FIELD SEPARATES THEM. doppler-correction-per-sec was null and
  rigctl-port was 4532 on all 24 records, in both groups. Do not key the
  corridor on metadata. It cannot work.
- So the corridor is TWO shapes, not one: a swept curve and a near-vertical
  residual band. Emit both, each with a width band, and let the caller decide.
  A7 and the model use the disagreement between them; collapsing to one shape
  early destroys the signal the whole product ranks on.

Already verified, build on it rather than re-testing:
- the observation's own tle1/tle2 + station_lat/lng/alt + start/end reproduced
  pass geometry to 0.18 deg against the API's reported max_altitude
- range rate flips sign exactly at peak elevation
- a 207s pass at 436.4 MHz gave a 14,631 Hz swing = ~118px at 123.46 Hz/px
- rx-freq lives in client_metadata.radio.parameters and client_metadata is a
  JSON-encoded STRING, not an object

THREE TRAPS, each of which cost real time in A3:

1. Time runs BOTTOM TO TOP on a SatNOGS waterfall. The top row is the END of the
   pass. Measured off observation 14740031: the 200 s tick sits at y=258 and the
   50 s tick at y=1228.
2. The plotted frequency axis runs AGAINST the Doppler sign. With Doppler
   positive when the satellite approaches, the trace moves the other way on the
   rendered axis.
3. Those two errors CANCEL. A Doppler curve is near odd-symmetric about closest
   approach, so having both wrong scores 25 sigma and draws an overlay that
   looks correct. Never confirm an orientation by looking at a picture. If you
   need to confirm one, scan both options and report the margin between them.

Also: do NOT assume the corridor is centred on rx-freq. The three uncorrected
traces sat 14.0, 2.4 and 1.8 kHz off the predicted curve. Carry a free constant
offset as an explicit parameter with a stated search range.

Requirements:
- SGP4 propagation, geodetic station position, proper ECI->ECEF (the recon
  script used a first-order GMST adequate only for feasibility; do this properly)
- output BOTH corridor shapes per observation, each with a width band, plus the
  named degraded states: missing TLE, stale TLE (epoch far from pass), SGP4
  non-zero error code, missing station coords, missing frequency
- validate against the API's own rise_azimuth, set_azimuth and max_altitude on
  at least 200 observations and report the error DISTRIBUTION, not one example

RATE LIMIT WARNING. The public API throttled this project twice, at 1551 s and
3419 s, and each block costs an hour of waiting rather than a credit. For 200
observations you need about 8 listing pages and ZERO waterfall downloads, since
geometry validation needs only the record. Page with the Link: rel="next" cursor
(id__lt and end__lte are accepted with HTTP 200 and silently ignored), space
requests 2 s apart, and CACHE every page to disk on the way in so a rerun costs
nothing. scripts/a3_doppler_investigation.py already does all of this; copy its
approach rather than reinventing it.

ACCEPTANCE:
- tests/test_physics.py with fixed-case tests: known pass -> known elevation
  profile, sign flip at TCA, and a deterministic corridor for a frozen input
- a test that fails if the time direction or the frequency sign is flipped
- max_altitude agreement reported as a distribution over >=200 observations,
  written to artifacts/PHYSICS_VALIDATION.json
- every degraded state returns a named reason code, none raise
- zero network access in the tests
- scripts/gate.py passes 7/7 before you report completion
```

---

### A5. Label provenance builder *(~2 credits)*

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

MEASURED IN A3, AND EACH ONE IS A LABEL TRAP:

1. A bare listing returns FUTURE observations. One A3 attempt pulled 200
   consecutive records with status "future", waterfall null and
   waterfall_status "unknown". Those are not unlabelled examples, they are
   observations that have not happened yet. Exclude them explicitly and test it.
   If they reach the label set they become fake negatives at scale.
2. Vetting lags capture. A recent observation with status "good" and
   waterfall_status "unknown" is UNVETTED, not negative, and the gap is a
   function of how long ago the pass ran. Record the vetting lag per record.
3. `with-signal` is a human judgement that something is visible, not a
   guarantee that a measurable carrier is present. A3 measured 24 vetted
   with-signal observations and only 7 carried a narrowband trace strong
   enough to score at all; the other 17 sat between 0.7 and 3.5 sigma. So the
   29.0% decisive rate is NOT a 29% measurable rate. Provenance must let a
   later stage tell "labelled positive" apart from "measurable", because A6's
   baseline will otherwise train against a target it cannot see.

Also verified and not worth a credit to rediscover: `client_metadata` is a
JSON-encoded STRING, not an object. `end__lte=` and `id__lt=` are accepted with
HTTP 200 and silently ignored; page with the Link: rel="next" cursor.
`waterfall_status=` as a query filter returns HTTP 400; filter it client-side.

RATE LIMIT WARNING. The public API throttled this project twice, at 1551 s and
3419 s, and a block costs an hour of waiting rather than a credit. If this unit
needs live records, cache every page to disk on the way in and reuse the cache;
scripts/a3_doppler_investigation.py already does this. Prefer working from
artifacts already on disk.

ACCEPTANCE:
- a provenance record per observation validating against its contract
- tests asserting unknown never becomes a training label and missing-waterfall
  never becomes a negative
- a test asserting a status "future" record never enters the label set
- a test asserting "labelled positive" and "carries a measurable trace" are
  distinct fields that cannot be conflated
- docs/LABEL_PROVENANCE.md explains each label origin and its known failure modes
- scripts/gate.py passes 7/7 before you report completion
```

---

### A6. Image-only baseline *(~2 credits)*

```text
Build the first two rungs of the model ladder as the honest baseline everything
later must beat: a centre-energy heuristic, and HOG plus regularised logistic
regression, both CALIBRATED.

The dataset is built and verified. It lives at D:\tracetriage_data\snap-stage1
with waterfalls/ beside it, and DATASET_MANIFEST.json is the only source of
truth for what exists. Every sha256 in it was re-verified against the bytes on
disk. What it holds:

  2,727 observations, 2,500 waterfalls stored, 227 with no waterfall URL
  739 decisive labels (27.1%): 462 with-signal, 277 without-signal, 1.67:1
  1,988 unknown (72.9%)
  271 ground stations, 526 satellites, 613 transmitters
  chronological, ending 2026-08-10T00:00:00Z, no stratification

Read the counts from the manifest anyway. Numbers pasted into a prompt go stale
and the manifest does not.

Calibration matters here specifically. Gate 5 requires the physics model to beat
a CALIBRATED image-only baseline. Beating an uncalibrated one proves nothing
except that calibration works.

SIX TRAPS, EACH MEASURED, EACH WITH A COST:

1. Most of this corpus carries no label at all. waterfall_status is "unknown" on
   roughly seven observations in ten. Reading "unknown" as "without-signal"
   turns 277 negatives into 2,265, inflating that class more than sevenfold, and
   produces a model that has learned which observations a human got round to
   vetting rather than anything about signals. Use
   provenance.label_from_obs and drop every UNLABELLED record from both training
   and evaluation. Do not invent a label for them.

2. A missing waterfall is not a negative. Some observations have no waterfall
   URL at all, and ArtifactStatus.MISSING means the artifact is unusable, which
   is a different fact from "no signal was present".

3. Some missing reasons are transient. THROTTLED, TIMEOUT and HTTP_ERROR mean
   the server refused for now, not that the artifact is bad. Exclude them and
   count them separately from the permanent reasons, so the exclusion table
   distinguishes "not fetched" from "not usable".

4. Train against labelled_positive. Never against carries_measurable_trace.
   A3 measured this: of 24 vetted with-signal observations, only 7 carried a
   narrowband trace a whole-path matched filter could find at all. "with-signal"
   is a human saying something is visible, not a promise that a narrow carrier
   exists. Training against MEASURABLE trains against a target that is invisible
   in most positive examples. provenance.py keeps these as two separate fields
   for exactly this reason; do not collapse them.

5. The geometry parse is allowed to fail, and a failure is not a prediction.
   The centre-energy heuristic needs hz_per_px and crop_box from A2, which
   degrade by design when the axis cannot be read. An observation whose geometry
   failed must be excluded and counted, never scored as zero energy. A silent
   zero here reads as a confident negative.

6. Accuracy is meaningless at this imbalance. Among the 739 decisive labels the
   split is 1.67 positives per negative, so a model that answers "positive"
   every time scores 62.5 percent and has learned nothing. Report Brier score,
   log loss, calibration slope and intercept, and a reliability curve.

REQUIREMENTS:
- temporary chronological split only. Do not touch the frozen test set; B1
  builds the real splits. Note in the receipt that a random split would leak,
  because a few hundred ground stations are spread across the corpus and station
  identity carries signal.
- report a prior-only model as the floor: predict the training base rate for
  every observation. A baseline that cannot beat that on Brier score has learned
  nothing, and the receipt must say so plainly if that is what happened.
- measure the base rates from the manifest and record them. The constants in
  provenance.py are a prior from a recon sample, not a measurement of this
  corpus; tests/test_base_rates.py checks the two against each other.
- write artifacts/BASELINE_RECEIPT.json with every number, the snapshot id, the
  manifest sha256, the seed, and an exclusion table whose counts sum to the
  corpus size.

ACCEPTANCE:
- both baselines train and score reproducibly from a fixed seed
- BASELINE_RECEIPT.json exists and its numbers regenerate identically on re-run
- the exclusion counts sum to the number of observations in the manifest, with
  no residual bucket
- the prior-only floor is reported next to both baselines
- docs/PRIOR_ART_BASELINES.md records what these are and why they are the bar
```

---

### A7. End-to-end evidence card slice *(~3 credits)*

```text
One observation, all the way through: snapshot -> waterfall parse -> physics
corridor -> provenance -> baseline score -> evidence receipt -> rendered card.

Thin but complete. No breadth. The point is proving the seam works before Wave B
builds volume on top of it. Everything you need is already built and committed:
A1 snapshot, A2 waterfall parser, A4 physics corridor, A5 provenance, A6
baseline. Do not rebuild any of them. Read docs/BOB_HANDOFF.md first.

CHOOSE THE OBSERVATION DELIBERATELY. Gate 3 asks whether the corridor intersects
the trace, and that question is only answerable on an observation where the
trace was actually located. A3 measured 7 of them and wrote every number to
artifacts/a3_overlays/summary.json, a list of 24 records keyed on obs_id with
verdict, sigma_vertical, sigma_curved and frequency_axis_sign on each. The seven
with a verdict other than UNRESOLVED are:

  CORRECTED    14746118 (sv 54.2), 14745602 (53.3), 14746048 (37.0), 14746055 (32.4)
  UNCORRECTED  14740031 (sc 25.1), 14745929 (15.9), 14745664 (15.1)

Pick one and say which and why. 14740031 is the strongest uncorrected case, so
the corridor has a curve to intersect; 14745602 is a corrected one whose carrier
intensity rises and falls with elevation across the pass. An observation A3
recorded as UNRESOLVED cannot answer gate 3, and choosing one silently turns a
null result into an apparent failure.

SEVEN TRAPS, EACH ALREADY PAID FOR ONCE:

1. Time runs BOTTOM TO TOP. The top row of a SatNOGS waterfall is the END of the
   pass. Read off the axis of 14740031: the tick labelled 200 s sits at y=258
   and 50 s at y=1228.

2. The plotted frequency axis runs AGAINST the Doppler sign. A4 carries this as
   AXIS_SIGN_CONVENTION = -1.

3. Those two errors CANCEL. A Doppler curve is near odd-symmetric about closest
   approach, so having both wrong scores 25 sigma and the overlay looks correct
   to the eye. A visual check cannot catch it. If you touch either convention,
   the thing that catches you is the apparent frequency drift against real time:
   +85 Hz/s is not a Doppler shift any orbit can produce.

4. Correction status varies per observation and NO metadata field reveals it.
   doppler-correction-per-sec is null and rigctl-port is 4532 on captures that
   are plainly corrected and on captures that are plainly not. Read the status
   for your chosen observation from A3's summary.json; do not infer it.

5. The corrected corridor half-width is 1200 Hz, not 200. It was 200, which
   contained none of the four corrected carriers A3 measured, whose within-pass
   wander is 77, 639, 639 and 1935 Hz. Do not "tighten" it without a
   measurement that says so.

6. A failed geometry parse is a named degraded state, never a fabricated number.
   The same rule the baselines follow: exclude and count, do not substitute.

7. Reason codes come from a fixed rule table. Never from a model attribution,
   never from a saliency map, never phrased as though the model explained itself.

REQUIREMENTS:
- artifacts/TRIAGE_RECEIPT.json for that one observation, matching
  contracts/triage_receipt.schema.json
- the baseline probability comes from the CALIBRATED model in
  artifacts/BASELINE_RECEIPT.json whose beats_floor entry is true. A model that
  does not beat the prior-only floor is not a comparison target; read the
  receipt rather than assuming which one that is.
- a rendered card (static is fine) showing: waterfall, corridor, detected trace,
  residual, artifact checks, current API label, provenance, source link,
  deterministic reason codes
- reuse pipeline.tracetriage.baseline._geometry_of for the parse; it caches, and
  parsing the same image twice costs a minute of OCR for nothing

ACCEPTANCE:
- the receipt regenerates from the same snapshot and seed with every number
  identical. Regenerate it to prove that; do not hand-edit an artifact to match
  a code change. A6 was hand-patched after its runner changed and the receipt
  then described code that had never produced it.
- the card renders with the network disabled
- gate 3 is evaluated: state whether the corridor intersects the trace, with the
  numbers, for the named observation
- update docs/KILL_GATE.md gate 3 with the result. If it FAILS, re-verify the
  Hz/px derivation before accepting the failure, because a wrong Hz/px moves the
  corridor bodily and fails a gate that is not actually failing.
```

---

## A7b-INT: integration review of the gate-3 measurement (NOT RUN, superseded)

> **Decision, 17 August 2026: this unit was skipped.** The operator chose to move
> Bob straight to Wave B rather than spend 2 credits on an acceptance review of the
> gate-3 repair. The three findings that constrain Wave B were folded into the B1
> prompt instead (`BOB_PASTE_2_B1.txt`), so Bob is told the corrected-corridor
> result rather than asked to ratify it.
>
> What this costs, recorded rather than argued: the gate-3 repair is the one piece
> of load-bearing work on the judged path that Bob did not build and did not
> accept. Bob built the module it replaced. If a judge asks who wrote the gate-3
> statistic, the honest answer is the operator, reviewed by a second AI, not Bob.
> Everything else in Wave A is Bob's.
>
> The unit below is kept unrun so the decision is inspectable and so it can still
> be handed to Bob later if credits allow.

### Original unit text

**This is an enhancement-loop unit, not a build unit.** You built A7 (`5d9b323`).
An operator-side review found the gate-3 check could not fail and replaced it.
Commit `c22433f`. Your job is to review that change, run it, and either accept it
or reject it with a reason. Do not rebuild it, and do not accept it on the
strength of this description. Estimated **2 credits.**

### What was wrong with your A7

Read `D:\IBM August Challenge\A7_VERIFICATION_2026-08-17.md` first. The short
version, all of it measured:

1. `_check_corridor_intersects` computed `trace_half_width_hz = 3 * hz_per_px / 2`
   and compared it against `half_w`. Both sides are constants. The left is a
   matched-filter kernel width, 116 to 192 Hz across the two client layouts; the
   right is a hardcoded 1200 or 2000 Hz. The check returned True for all seven of
   A3's decisive observations and cannot return False for any normal waterfall.
2. It reported 1/1 = 100% against a 70% threshold. One observation cannot
   measure a rate.
3. The comment justified the pass with "A3 measured max deviation 140 Hz" and
   then admitted A3 does not store per-row deviations. That number is a comment
   in `physics.py` and a literal in `tests/test_physics.py:760`, never a
   measurement.
4. `corridor_for_obs` was called without a frequency offset, so the corridor sat
   at rx-freq. A3's stored `curved_offset_hz` for obs 14740031 is -13,985 Hz
   against a corridor whose outer edge is 10,303 Hz from rx-freq. The trace was
   3,682 Hz outside the band, so the honest reading of your own artifact is a
   miss by 7x the half-width.
5. Geometry came from `baseline._geometry_of`, which omits `rx_freq_hz`.
   `waterfall.py:795` only attempts `centre_px` when a receiver frequency is
   supplied, so `centre_px` was None and the corridor could not have been placed
   on the image even in principle.
6. `target_consistency` used `min(1, sigma_curved / sigma_vertical)` for every
   observation. That is right only for an uncorrected pass. For a corrected pass
   the vertical trace IS the evidence, so it inverts. It scored the four
   corrected observations 0.046 to 0.648 and saturated the three uncorrected at
   exactly 1.000. Obs 14746048 carries a 37.0 sigma vertical trace and was rated
   0.046, the least consistent of the set.
7. `model_checksum` hashed `BASELINE_RECEIPT.json`, not `hoglr_model.pkl`.
8. `_A3_VERDICT_TABLE` was hardcoded while its comment claimed it read
   `summary.json`, and it had drifted: 14746055 listed UNCORRECTED where A3
   records CORRECTED.
9. A7 shipped zero tests.

### Your acceptance checks

Run each. Report the actual output, not a summary of it.

1. `python scripts/gate.py` reaches 7/7.
2. `python -m pytest -m "not network" -q` passes. Expect 406 passed, 1 xfailed.
3. `python scripts/run_gate3.py` reproduces `artifacts/GATE3_RECEIPT.json`:
   verdict PASSED, 3 testable, 4 not testable, discriminating rate 1.000, and
   p = 0.005 with 0 of 200 nulls reaching the truth on each of 14740031,
   14745664 and 14745929.
4. Run it twice. Everything except `generated_at` must be byte-identical.
5. Mutation check, and this is the one that matters. Make the residual a
   constant again:
   in `pipeline/tracetriage/corridor_fit.py`, replace the body of the
   `resid_out.append(...)` line with `resid_out.append(3.0 * hz_per_px / 2.0)`.
   `tests/test_corridor_fit.py::test_coverage_falls_as_the_trace_moves_off_the_curve`
   must fail with `[1.0, 1.0, 1.0, 1.0]`. Revert it.
6. Second mutation: in `px_to_offset_hz`, drop `/ AXIS_SIGN_CONVENTION`. Three
   tests must fail. Revert it.
7. `artifacts/TRIAGE_RECEIPT.json` validates against
   `contracts/triage_receipt.schema.json`, and its `model_checksum` equals
   `sha256(artifacts/hoglr_model.pkl)`. Check that by hand.

### Judgement calls to accept or reject on their merits

You are the one who decides these. Each is a defensible choice, not an obvious
one, and rejecting any of them is a legitimate outcome if you can say why.

1. **The offset bound is 50 ppm of the downlink.** A fitted constant frequency
   offset is necessary, because a cubesat oscillator drifts and the SatNOGS
   transmitter frequency is community-maintained. But the bound decides how much
   discriminating power survives: A3's own scan allowed plus or minus 76.9 kHz,
   which is 9.3x the Doppler swing and lets the curve land anywhere. Is 50 ppm
   right? At 400 MHz it is 20 kHz against a 17 kHz swing, so the offset range
   still exceeds the signal. Argue it or tighten it.
2. **The gate statistic is a null-calibrated p-value, not per-row coverage.**
   Per-row detection at 4.0 robust z finds 2.1% of rows on obs 14740031, because
   the trace integrates to significance along the path while no single row
   clears the floor. So coverage is reported as a diagnostic and the gate reads
   the path statistic. Is that the right instrument, and is `min_detect_frac`
   still meaningful if the gate does not use it?
3. **Four of seven observations are declared NOT TESTABLE.** The corrected
   corridor is identically 0 Hz, a vertical line with a free offset, so it
   predicts no shape and every null reproduces it. This is the largest claim in
   the change: it says the physics has predictive content only on uncorrected
   captures, which is a minority of observations. Check `physics.py` and confirm
   the corrected corridor really is all zeros. If it is, this belongs in the
   README's limitations, and Wave B's fusion design has to account for it.
4. **The nulls are time permutations, and time reversal was rejected** because
   A3 showed a Doppler curve is near odd-symmetric about closest approach. Are
   permutations plus the four scaled swings enough? A permuted curve is jagged,
   so a skeptic can say the test rewards smoothness. The scaled-swing controls
   are the answer to that, and they hold shape fixed while varying magnitude.
   Judge whether they close it.
5. **`target_consistency` maps through `x / (1 + x)` instead of clipping at
   1.0.** Keeps resolution above a ratio of 1 rather than saturating. Check the
   value moved from 1.000 to 0.899 on obs 14740031 and that nothing downstream
   assumed the clip.

### Then

- Append your task to `docs/BOB_BUILD_LOG.md` in the existing format: task,
  files, commands, tests, failures, repairs, credits, commit SHA, Bob task ID.
- If you accept, say so and record which of the five judgement calls you
  independently agree with, and any you would change later.
- If you reject any part, say exactly what and why, and fix it yourself.
- Collect your Bob task ID before the session closes. `REGISTRY.md` needs it.

### Do not

- Do not re-report gate 3 as 1/1, and do not restore the constant check.
- Do not widen a corridor or a bound to make something pass. If a number fails,
  that is a result.
- Do not describe the corrected-corridor exclusion as a pass.

---

# Wave B: splits, fusion, calibration, abstention

Target: **~14 credits.** Do not start until gates 3, 4 and 5 have recorded results.

- **B1** Grouped split builder and leakage audit. Chronological, cold-station, cold-transmitter, combined. Each transmitter and orbital revolution in exactly one split. Emit `artifacts/SPLIT_MANIFEST.json` and `artifacts/LEAKAGE_AUDIT.json`. Test that a duplicate image cannot cross a split. *(~3)*
- **B2** Fusion head over image, metadata and physics features. Compare against every earlier rung. *(~3)*
- **B3** Calibration on a later time period: temperature and isotonic, pick by measured reliability, not by preference. Multi-seed head ensemble for uncertainty. *(~2)*
- **B4** Selective prediction and abstention, with risk-versus-coverage curves. Conformal only if it earns its place. *(~3)*
- **B5** Out-of-distribution scoring for unseen stations, transmitters, client formats and bands. *(~2)*
- **B6** Ablation harness and cold-entity slices, grouped bootstrap by orbital episode or day. Every rung of the ladder gets an ablation row. Delete what does not earn its place. *(~1)*

Gate 5 closes here. Gate 6 needs B1 plus Wave C.

---

# Wave C: queue, annotation, console

Target: **~14 credits.**

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

Target: **~12 credits.**

- **D1** Failure injection across the full list: malformed image, blank image, missing TLE, stale TLE, absent frequency bins, wrong start offset, multiple traces, network outage, missing model, unsupported client format, empty queue, Granite timeout. Each returns a named degraded state. *(~3)*
- **D2** Claim register and drift tests. Every README and video number maps to a generated receipt, and a mutation test fails when they diverge. *(~2)*
- **D3** Clean-clone reproduction from scratch, network disabled, on a fresh checkout. *(~2)*
- **D4** Secret scan (zero findings) and CC BY-SA attribution audit across every redistributed artifact. *(~1)*
- **D5** Generated documentation, deployment of the static console, video fixture capture. *(~2)*
- **D6** **Final Bob acceptance.** Inspect the release commit, run every acceptance check, repair failures, generate the sign-off receipt. This task must be Bob's, on the release commit, and it is the evidence that Bob owned the judged path. *(~2)*
