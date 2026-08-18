# Wave D prompt

Paste the block below into a fresh account, in a new chat, as the first message.
It restates everything the builder needs, because a new account has no memory of A, B
or C.

Units are named A, B, C and D. Nothing else is named.

Current as of 2026-08-19, after D2. Wave C is closed and Wave D is in progress:
working tree clean, every standing gate green (12 of 12 as of D2, which added the
console checks and artifact freshness), 818 offline tests collected with 817 passing
and one declared expected failure. The gate prints its own count, so read that
rather than this sentence.

---

```text
You are the primary development tool for my solo August 2026 AI Builders Challenge
submission. Read .bob/rules.md, docs/BOB_HANDOFF.md and docs/BOB_BUILD_LOG.md before
doing anything else. The build log is long; read the C5, C6, C7, C7f and C7g entries
at minimum, because they describe the state you are inheriting.

Some work was done additionally on my side. Do not overwrite it and do not drop it.

COMPETITION
- Entering only "Advance Space Exploration with AI" (August theme).
- Target: August first place and Grand Prize candidate.
- You are the primary development tool and you build every load-bearing subsystem.
- Other tools may review or improve bounded areas. You review, test, and accept or
  reject their work on its merits.
- No paid service. All caches, weights and build output on D:\, never C:\.
- Deadline 31 August 23:59 ET. The repository is private until 25 August and public
  after that, so nothing lands in it that a judge does not need.

PROJECT
TraceTriage is a read-only, physics-conditioned review queue for public SatNOGS
waterfall observations. A reviewer has more observations than they can inspect. Given
a fixed review budget, it ranks which existing public observations deserve human
review because the image evidence, the expected Doppler behaviour, the metadata and
the current network label disagree or remain uncertain.

The distinguishing property of this submission is that it is checkable. Every number
on the console and in the README is generated from a committed receipt under
artifacts/ and carries a row in docs/CLAIM_REGISTER.md. Gates that came back
inconclusive are published as NOT_ESTABLISHED. A gate that was never run is published
as OPEN. Do not repair a weak result by rewording it. If you find a claim this project
cannot support, retract it in the claim register and say so in the build log.

WHERE THE WORK STANDS

Waves A, B and C are complete and committed on main. Six kill gates were asked. Two
are met, three came back inconclusive, one was never run:

  1 dataset volume and entity spread   PRE_PASSED
  2 metadata coverage for the corridor PRE_PASSED
  3 corridor intersects a visible trace NOT_ESTABLISHED. All 3 testable observations
                                        discriminate, and 3 of 3 cannot establish a
                                        70% rate: the exact one-sided 95% lower bound
                                        is 0.368, and 9 of 9 would be needed. It was
                                        withdrawn from PASSED on 18 Aug because the
                                        check compared a point estimate against the
                                        bar. tests/test_gate3_bound.py fails against
                                        the old comparison. Do not reinstate it.
  4 blinded human decidability          OPEN, never run
  5 physics beats image-only on Brier   NOT_ESTABLISHED, interval spans zero
  6 queue lift over random              NOT_ESTABLISHED on the primary split,
                                        PASSED on cold-station

Dataset: D:/tracetriage_data/snap-stage1, snapshot id snap-20260817-stage1, 2,727
observations, 2,500 waterfalls, 739 decisive labels, 271 stations, 526 satellites.
Every sha256 re-verified against the bytes on disk. It is outside the repository on
purpose and it is about 4 GB.

The static console is deployed and live at https://tracetriage.vercel.app. It is a
Next.js 15 static export: no server, no database, no runtime fetch of data, no
credentials. It makes exactly one class of third-party request, added in C7d: two
licensed typefaces from Adobe Fonts, 43,598 bytes cold, plus a five-byte licence
counter. Adobe's terms forbid self-hosting the files, so this cannot be closed by
moving them. It is disclosed with its measured byte count on the provenance page and
in the colophon, and the content security policy names both hosts. Do not restate the
old absolute claim that the site requests nothing from another origin: it was true
until C7d and is not true now. The narrowed claim is that no DATA is requested from
another origin.

Four instruments on one clock sit on each observation page: the waterfall with the
fitted corridor, a polar sky track, a ground track with the horizon circle, and
elevation and Doppler against time. 779 offline tests are collected: 778 pass, and 1
is a declared expected failure that task D2 below implements. Lint is clean,
typecheck is clean, next build produces 33 pages.

FIVE THINGS ARE GENERATED. DO NOT HAND-EDIT THEM.

  docs/KILL_GATE.md      status summary and failure log, by scripts/sync_kill_gate.py.
                         Run it with --check to detect drift without writing; it exits
                         1 on drift. It is idempotent as of C7f. The first version
                         could only run once, which is recorded in that file's own
                         failure log, and tests/test_kill_gate_sync.py now asserts
                         idempotence and asserts each generated row against its
                         receipt.
  README.md              the results tables, by scripts/sync_readme_results.py.
  apps/web/public/data/  the whole directory, by scripts/build_console_data.py. It
                         raises rather than shipping an absence as a measurement.
  artifacts/HERO_NULLS.json
                         by scripts/export_hero_nulls.py. See below.
  the gate tally         gates 3, 5 and 6 are read from their receipts by
                         build_gate_summary. Gates 1, 2 and 4 are literals because
                         they have no receipt, and the code says so. An unknown
                         verdict raises rather than being counted as unmet.

TWO THINGS ADDED IN C7g THAT ARE CHECKED, NOT STYLED

The home page opens on a plate: one real waterfall, the Doppler corridor fitted to it,
and six of the two hundred null corridors it was scored against. The nulls on screen
are the nulls that were scored. scripts/export_hero_nulls.py re-runs gate 3's own fit
outside the scoring path and writes nothing unless seven statistics reproduce
artifacts/GATE3_RECEIPT.json to 1e-9. tests/test_hero_nulls.py checks the artifact
against the receipt independently of the generator. It costs zero client JavaScript:
the reveal is CSS stroke-dashoffset against pathLength=1.

Three coordinate spaces exist on that image and mixing them is silent. The source PNG
is 836 by 1603; parse_waterfall crops the plot region to 620 by 1540, which is the
shipped image and the viewBox every overlay shares; normalised_rows then trims
EDGE_MARGIN_PX from each side, leaving the 1532 by 612 array the matched filter
walked. Using the source height where the card uses the crop displaced the drawn
corridor by 235.7 px, which is 29 kHz against a 17.3 kHz Doppler swing. The exporter
measures that residual every run and refuses to write above half a pixel.

The neutral palette carries an indigo cast expressed in OKLCH at IBM Carbon's own
lightness values, so no contrast ratio moved by more than 0.03 and every accessibility
result C6 measured still holds. scripts/check_contrast.py recomputes all 26 pairs
straight out of globals.css and tests/test_contrast.py fails the suite if one drops
below its floor. Do not pick a colour by eye here. NOT_ESTABLISHED stays grey, for the
two published standards recorded in C7, and a test fails if it turns amber again.

THREE DOCUMENTATION DEFECTS FOUND IN C7, ALL FIXED. KNOW ABOUT THEM.

  - KILL_GATE.md published two different confidence intervals for gate 6 in one file.
    That is why its summary is generated now.
  - README.md's results table listed measured metrics as [UNMEASURED] long after they
    were measured. That is why its tables are generated now.
  - The pre-registration stated 88 observations in 87 episodes at a mean group size of
    1.000, which is arithmetically impossible. Gate 5 scores 88 decisive observations
    of the test partition; gate 6 scores 87, because the queue deduplicates 410 rows
    to 407 and one removed row was decisive. Keep those two numbers distinct.

FILES THAT ALREADY EXIST. DO NOT RECREATE THEM.

  pipeline/tracetriage/   snapshot.py, waterfall.py, physics.py, provenance.py,
                          baseline.py, corridor_fit.py, splits.py
  scripts/                run_baseline.py, run_fusion.py, run_queue.py, run_gate3.py,
                          run_triage_slice.py, build_splits.py, build_console_data.py,
                          render_evidence_card.py, validate_physics.py, annotate.py,
                          explainer_corridor.py, extract_corridor_features.py,
                          extract_hog_cache.py, sync_kill_gate.py,
                          sync_readme_results.py, export_hero_nulls.py,
                          check_contrast.py, gate.py
  artifacts/              DATASET_MANIFEST.json, SPLIT_MANIFEST.json,
                          LEAKAGE_AUDIT.json, BASELINE_RECEIPT.json,
                          FUSION_RECEIPT.json, QUEUE_RECEIPT.json, GATE3_RECEIPT.json,
                          TRIAGE_RECEIPT.json, PHYSICS_VALIDATION.json,
                          HERO_NULLS.json, hoglr_model.pkl, a3_overlays/
  apps/web/components/    WaterfallViewer, WaterfallCanvas, SkyPlot, GroundTrack,
                          PassTimeSeries, PassReplay, QueueTable, RiskCoverage,
                          CorridorHero, Icon, Rail, Nav, Colophon, ui

HOW TO RUN THINGS

  .venv\Scripts\python.exe -m pytest -q            the offline suite, about 160 s
  .venv\Scripts\python.exe scripts\gate.py         every standing gate
  .venv\Scripts\python.exe scripts\check_contrast.py -v
  .venv\Scripts\python.exe scripts\sync_kill_gate.py --check
  cd apps\web && npx tsc --noEmit -p tsconfig.json
  cd apps\web && npx next build                    33 pages, static export to out\

The virtual environment has no pip. It is uv-managed: use uv pip install. Install
torch from the CUDA index (--index-url https://download.pytorch.org/whl/cu126); a
plain install silently gives a CPU-only build that measured 14.9x slower here. Keep CI
on CPU so the clean-clone claim holds without a GPU. Disk and GPU are not the
constraint on this machine; 16 GB of RAM is, so stream parquet with scan_parquet and
never read_parquet.

Stop and hand back when 3 build credits remain. The budget document is
docs/BUILD_BUDGET.md.

YOUR WAVE: D, release hardening. Seven units, in order. Do not start a unit until the
previous one's acceptance checks are green. Update docs/BOB_BUILD_LOG.md and
docs/BOB_HANDOFF.md at the end of every unit, and commit before starting the next one,
because scripts/gate.py fails on an uncommitted tree.

D0. ACT ON THE TWO EXPERT REVIEWS
Two independent reviews of A, B and C were commissioned before Wave D opened: one from
a flight-dynamics and observational-science standpoint, one from a staff engineering
standpoint. They are committed as docs/REVIEW_SPACE.md (5 BLOCKING, 9 SERIOUS, 11
MINOR) and docs/REVIEW_ENGINEERING.md. Read both in full.

Count the engineering review's findings yourself rather than trusting its summary
line. That line says "Three BLOCKING, ten SERIOUS, thirteen MINOR" and the file
carries three, ELEVEN and thirteen headings. The extra SERIOUS is real and is not
covered by the stated count, so a wave that works to the summary line finishes one
finding short and reports itself complete. The space review's own count is correct at
5, 9 and 11. Verify both with a grep before you plan, and record the corrected counts
in the build log.

One BLOCKING finding is already closed and it is the pattern for the rest. Gate 3 was
marked PASSED by a comparison that could not return False, and the C7f build log entry
records the reproduction, the fix, the test that fails without it, the claim-register
retraction, and a second defect found while closing it. Seven BLOCKING and twenty
SERIOUS remain, on the corrected counts.

One more thing was fixed ahead of you, and it changes how you handle SPACE-B4. The
plate on the home page carried its limitation sentence as typed prose: it asserted
that all three testable observations discriminate at a lower bound of 0.368, and read
neither number from anywhere. Adding margin_over_best_null to the discriminates
criterion can drop an observation from that count, and the sentence would have become
false with every test still green. Those figures now come from artifacts/HERO_NULLS.json,
which carries gate 3's verdict fields, and tests/test_hero_nulls.py asserts them
against the receipt. So after any change to run_gate3.py you must re-run
scripts/export_hero_nulls.py and then scripts/build_console_data.py, in that order, or
the suite will tell you.

For every BLOCKING finding: reproduce it first, then fix it, then add a test that
fails without the fix. For every SERIOUS finding: either fix it, or record in the
build log why it is not a defect, with the measurement that shows it. Do not mark a
finding resolved on the strength of your own reading of the code. A finding is
resolved when a test fails without the fix.

Some findings will be wrong. Reviewers assert things. Check each one against the code
and the receipts before you change anything, and say plainly in the build log which
findings you rejected and on what evidence.

Acceptance: every BLOCKING finding has a failing-without-the-fix test. Every SERIOUS
finding has either a fix or a recorded rebuttal with a measurement. The build log names
the findings you rejected. Every retraction has a claim-register row.

D1. FAILURE INJECTION ACROSS THE FULL LIST
Every one of these must produce a NAMED degraded state, never a blank frame, a zero, or
a silent success: malformed image, blank image, missing TLE, stale TLE beyond the age
threshold, absent frequency bins, wrong start offset, multiple traces in one waterfall,
network unavailable, missing model artifact, unsupported client image format, empty
queue after filtering, and a request that times out.

The rule that matters: an absence must never be published as a measurement. A missing
value is a named reason, not a null and not a zero. Two absences were published as
measurements earlier in this project (four splits shipped with empty partition counts,
and two model arms shipped as null), and scripts/build_console_data.py grew a _require
helper because of it. Extend that discipline, do not weaken it.

A third case worth naming: a check that cannot fail is the same defect wearing
different clothes. Gate 3 compared a constant against a constant and passed on every
input. When you add a degraded-state test, mutate the input and confirm the test goes
red.

Acceptance: a test per failure mode, each asserting the specific named reason rather
than merely that no exception escaped. A test that only asserts "did not crash" does
not count. The console's degraded-state table on the provenance page counts itself from
the shipped cards; keep that property.

D2. CLAIM REGISTER AND DRIFT TESTS
tests/test_claim_drift.py exists and works, but it has two gaps.

First, it asserts that every metric name in the README has a register row. It does not
compare a quoted value against its artifact: mutating the AUC row from 0.875 to 0.999
leaves the suite green. The README says so in its own status line. Close it.

Second, a row whose value reads exactly [UNMEASURED] is skipped. That is correct for a
genuinely unmeasured metric and it also means a README where every cell said
[UNMEASURED] would pass while telling a reader nothing was measured, which is what the
README did until C7. Close the gap without removing the hatch: assert that every
[UNMEASURED] row names the gate or the reason it is unmeasured, and that the count of
[UNMEASURED] rows matches the count of gates recorded as OPEN or not run.

tests/test_kill_gate_sync.py and tests/test_hero_nulls.py are the pattern: both mutate
a value and assert the check goes red.

Acceptance: the xfail marker in tests/test_claim_drift.py is removed because the test
is implemented and passing. A receipt mutation fails the suite. A README number with no
register row fails the suite, which it already does; keep it.

D3. CLEAN-CLONE REPRODUCTION, NETWORK DISABLED
Clone the repository to a fresh directory. Disable the network. Reproduce every receipt
and the console build from scratch. Record what was needed that the repository does not
contain, and either commit it or document it as a prerequisite with a version.

This is the unit most likely to find something real. Look specifically for: an artifact
that only exists because it was built earlier and never regenerated, a script that
reads a path outside the repository, a test that passes only because a cache is warm,
and any step that silently reaches the network. scripts/run_gate3.py and
scripts/export_hero_nulls.py both default to --snapshot D:/tracetriage_data/snap-stage1,
which is outside the repository; the engineering review already flags a hardcoded
absolute path in the leakage audit as BLOCKING. Decide and document what a clean clone
can and cannot regenerate without the 4 GB snapshot, and make the ones it cannot say so
by name rather than failing obscurely.

Acceptance: a transcript of the clean run committed under artifacts/, every receipt
regenerated with matching digests where the pipeline is deterministic, and any
non-determinism named with its cause rather than tolerated silently.

D4. SECRET SCAN AND ATTRIBUTION AUDIT
Zero secrets tracked. Every redistributed artifact carries its CC BY-SA 4.0
attribution: the SatNOGS observation imagery is contributed by volunteer ground
stations and the licence requires attribution and share-alike. Audit every image, every
derived thumbnail, the explainer video (which is derived from one observation's
exported corridor), and the home page plate (which redistributes observation 14740031
under a colour map).

While you are here, audit repository weight against the judge's point of view. The
tracked tree is about 30 MB, of which roughly 18 MB is artifacts/a3_overlays/*.png.
Those overlays are the visual evidence for the A3 Doppler correction finding, so do not
delete them without saying what replaces them as evidence. Report what is tracked that
a judge does not need, with sizes, and propose rather than assume.

Acceptance: a scan receipt with zero findings, and an attribution table that names
every redistributed file and the observation it came from.

D5. GENERATED DOCUMENTATION AND THE DEMO
The console is already deployed and live; that is not this unit's job. This unit is
generated documentation that cannot fall out of step with the code, and the demo
capture.

For the demo, build to these constraints, which come from the competition's own
guidance rather than from taste: under three minutes, open with the pitch rather than
the architecture, show the thing running against real input and real output, follow one
flow end to end rather than touring features, and do not narrate over slides.

Two sequences are available and both are already built. The home page plate is the
stronger opening: the fitted corridor arrives among six corridors built from the same
observation's own Doppler values, none of which fit, with p = 0.005 and 0 of 200 nulls
reaching it. The observation page is the stronger middle: one clock driving four
instruments, where scrubbing the pass puts the Doppler zero crossing at the instant
elevation peaks and range is shortest. End on the queue reorder and the honest verdict.

Acceptance: documentation generated from the code and the receipts, a demo under three
minutes, and every number spoken or shown in it present in the claim register.

D6. FINAL ACCEPTANCE, ON THE RELEASE COMMIT
Inspect the release commit. Run every acceptance check in the repository. Repair what
fails. Generate the sign-off receipt. This unit must be yours, on the release commit,
and it is the evidence that you owned the judged path.

Acceptance: scripts/gate.py green on every standing gate, the full offline suite
green, scripts/check_contrast.py at 26 of 26, scripts/sync_kill_gate.py --check clean,
npx tsc --noEmit clean, npx next build producing 33 pages, the console deploying from
the release commit, and a sign-off receipt that names each check and its result.

STANDING RULES, ALL WAVES

- Contracts before code. A schema is ratified before the script that writes against it
  runs. A receipt that violates its contract must never reach disk. schema_version is
  pinned by const so a receipt from an older script cannot validate as current.
- Determinism. Fixed seeds, recorded. A re-run that changes a number must be explained,
  not shrugged at.
- Grouped evaluation, never random. Holdouts are chronological, cold-station,
  cold-transmitter, and cold on both. Bootstrap intervals are over pass episodes and
  over ground stations, and the reported interval is the union of the two.
- A threshold is read off an interval, never off a point estimate. That is what gate 3
  got wrong. If a sample cannot resolve the bar, the verdict is NOT_ESTABLISHED.
- Absences are named, never defaulted. No null standing in for a measurement, no zero
  standing in for an absence, no empty container published as a result.
- Every number in a document is generated from a receipt or marked [UNMEASURED] with
  its reason.
- Anything described as generated must be idempotent. Run it twice; the second run
  writes identical bytes or the description is false.
- Git identity: every commit is authored as Kesav2k04 <kesavk659@gmail.com> and nothing
  else. Never add a Co-Authored-By trailer. Never pass --author. Never set a
  repository-local user.email that differs from the global one.
- Writing: no em dashes or en dashes anywhere in prose; use a full stop, comma, colon
  or parentheses. Do not use these words: delve, leverage as a verb, utilize, robust,
  seamless, elevate, unlock, embark, cutting-edge, pivotal, foster, myriad, meticulous,
  holistic, transformative, empower, streamline, facilitate, intricate, vibrant,
  curated, bespoke, boasts. Do not use these patterns: "It's important to note", "In
  conclusion", "When it comes to", "Not only X but also Y", "more than just", "At the
  end of the day". Never claim writing is original, human or undetectable.
- Naming: work units are A, B, C and D. Do not name any tool, model or assistant
  anywhere in a commit message, document, comment, receipt or report.
- The build allowance is called a build credit, and the budget document is
  docs/BUILD_BUDGET.md.
- Do not weaken a gate to pass it. A gate that would have killed the project is worth
  more than one that could not.

START WITH: read the two review documents, list every BLOCKING and SERIOUS finding with
your first assessment of whether it is real, and tell me which ones you intend to fix
first. Do not change code until you have reproduced a finding.
```

---

## Notes for me, not for the paste

- D0 did not exist in the earlier Wave D outline. It was added because the two expert
  reviews were commissioned at the end of C, and their findings are the highest-value
  work available at the start of D: they are defects in shipped code found by people
  looking for defects. One BLOCKING is closed already, in C7f, and the prompt points at
  that entry as the worked example so the pattern does not have to be described twice.
- D5 lost the deployment task, which moved into C. The demo constraints in D5 come from
  the competition's published guidance (under three minutes, open with the pitch, show
  it running, one flow, no slide narration) rather than from preference.
- D4 grew a repository-weight audit because the repository goes public on 25 August and
  18 MB of A3 overlays is the largest single thing in it. It is framed as propose, not
  delete, because those overlays are the evidence for a load-bearing finding.
- The review documents are committed as of `42288a4`, so D0 has something to read.
- The gate tally, the test counts and the generated-file list in the paste block are
  current as of `372028a`. Re-check them against `scripts/gate.py` and `pytest -q`
  before pasting if any further work lands first.
