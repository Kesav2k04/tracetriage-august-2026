# Bob handoff

**Read this and `.bob/rules.md` before every task.** Update it before every account rotation and at the end of every session.

---

## Current state

| | |
|---|---|
| **Handoff written** | 2026-08-20, IST, after D14d and the sign-off |
| **Waves completed** | **A** (A0 to A7), **B** (B1 to B6), **C** (C1 to C7h), **D** (D0 to D14), **E** (E0 to E8) |
| **Current wave** | **None. Wave D is closed.** Every unit the D prompt asked for is committed: the review-closing work (D0, D0b, D0c and the passes named D1 to D7), failure injection (D8, D8b), the `[UNMEASURED]` accounting (D9), the clean-clone reproduction (D10), secrets and attribution (D11), generated documentation and the demo script (D12, D12a), final acceptance with a sign-off receipt (D13, D13a, D13b), and a review pass from a judge's seat (D14 to D14d) that closed ten findings, put two unreachable console pages back in the navigation and re-ran the clean clone at the release commit. |
| **What remains** | Two things outside the repository: record the demo video against `docs/DEMO_SCRIPT.md`, and make the repository public on 25 August. One thing that needs a single look once it is public: the CI badge at the top of `README.md` reports the last run of `.github/workflows/ci.yml` on `main`, and no session here can query the Actions API to see what it says. Nothing in the tree is waiting on any of the three. |
| **Numbering** | The committed entries named D1 to D7 are review-closing passes and are **not** the prompt's units D1 to D6. The prompt's units are numbered from D8 onward in the build log: D8 is its D1 (failure injection), D9 its D2, D10 its D3, D11 its D4, D12 its D5, D13 its D6. |
| **Open failures** | none. **1,288** offline tests collected and all pass, 4 deselected, no expected failures. Lint clean. **103** console tests pass under vitest across 6 files. `npx tsc --noEmit` clean. `npx next build` emits **32** `index.html` files. `scripts/gate.py` green on **18 of 18** standing gates. |
| **Kill gates** | 2 of 6 met. 1 and 2 PRE_PASSED, 3 and 5 and 6 NOT_ESTABLISHED, 4 **OPEN and never run**, with its instrument built in E6: `scripts/build_gate4_worksheet.py` produces a blinded 72-item bundle committed to in advance, and `artifacts/GATE4_RECEIPT.json` reads `NOT_RUN` with no rate. |
| **Console** | Next.js 15 static export, deployed and live at https://tracetriage.vercel.app. Six pages: queue, evaluation, agent, precedent, replay, provenance. |
| **Dataset** | stage 1 built and verified: `D:/tracetriage_data/snap-stage1`, **2,727** observations, 2,500 waterfalls, **739** decisive labels. The API pages on disk hold 2,750 rows, 23 more than the dataset, because the ingest stopped at its waterfall target part-way through a page it had already written whole. **Every count in this repository is over the 2,727.** Two scripts read the pages unfiltered and published 2,750 and 743; both filter against `artifacts/DATASET_MANIFEST.json` since D14. |
| **Last commit** | see `git log -1`. `artifacts/SIGNOFF_RECEIPT.json` names the commit the final acceptance measured. |

**The clean-clone reproduction is `artifacts/CLEAN_CLONE_TRANSCRIPT.json`.** Measured at
`f35b005`: **15 of 16 steps**, both pytest passes green, 1,286 with the snapshot present and
1,256 with 30 skipped when it is hidden. The one failing step is the offline `uv pip install`,
which fails because a wheel is not in the local package cache and the run refuses the index.
Making it pass needs the full pinned set warmed into a cache the run can reach; C: has 5.3 GB
free and moving the cache to D: would make the receipt depend on a shell variable nobody sets
persistently, so the failure is disclosed with its cause instead. `scripts/sync_for_judges.py`
reads the missing package name out of the step's own output tail.

### Five documents are generated. Do not hand-edit any of them.

| Document | Generator | `--check` in the gate |
|---|---|---|
| `README.md` results tables **and** the gate status block between its two `<!-- ... gate status -->` markers | `scripts/sync_readme_results.py` | yes |
| `docs/KILL_GATE.md` | `scripts/sync_kill_gate.py` | yes |
| `FOR_JUDGES.md` | `scripts/sync_for_judges.py` | yes |
| `docs/REFERENCE.md` | `scripts/sync_docs.py` | yes |
| `docs/DEMO_SCRIPT.md` | `scripts/sync_demo.py` | yes |

`apps/web/public/data/` is generated in its entirety by `scripts/build_console_data.py`, and
`artifacts/HERO_NULLS.json` by `scripts/export_hero_nulls.py`. `scripts/check_artifact_freshness.py`
rebuilds them into a scratch directory and diffs, and the gate runs it.

**Run the gate before every commit.** Three separate defects in Wave D were commits that
looked finished and left a generated document one run behind: a stale `provenance.json` after
the release audit was re-run, a stale `FOR_JUDGES.md` after the clean-clone transcript moved,
and a stale `docs/REFERENCE.md` after one line was added to `scripts/signoff.py`. Each was
caught by a clean clone or by the gate afterwards rather than before, and each cost a repair
commit.

**The sign-off is `scripts/signoff.py`.** It runs the standing gate, the acceptance checks the
gate does not cover, and the release audit at one commit, and writes
`artifacts/SIGNOFF_RECEIPT.json` naming each check and its result. Re-run it at any commit that
is meant to be a release: the receipt records what it measured and the gate requires it to be
present and `SIGNED`. It has three outcomes rather than two, so a check that could not run here
is `NOT_CHECKED` with a stated reason instead of being folded into a pass or a failure.

### Read this before D0

Two independent reviews of A, B and C are committed as `docs/REVIEW_SPACE.md`
(5 BLOCKING, 9 SERIOUS, 11 MINOR) and `docs/REVIEW_ENGINEERING.md` (3 BLOCKING, **11**
SERIOUS, 13 MINOR). The engineering review's own summary line says ten and the file
carries eleven headings; C7h recorded that and this line said ten until D0c. Corrected
totals across both documents: 8 BLOCKING, 20 SERIOUS, 24 MINOR, 52 findings.

**State as of D0c: every BLOCKING and every SERIOUS finding is closed.** What is not:
ten MINOR findings in the engineering review are closed by nothing and cited nowhere,
`:498`, `:555`, `:565`, `:587`, `:598`, `:614`, `:626`, `:641`, `:652` and `:684`, and two
more, `:528` and `:543`, were closed incidentally with no record saying so. The wave's
acceptance covers BLOCKING and SERIOUS, so these do not hold the unit open.

The pattern for any finding is unchanged: reproduce it, fix it, add a test that fails
without the fix, record it in the build log and the claim register. See the C7f entry, and
see D0c for what happens when the test is skipped because no framework existed yet.

**Gate 3 moved from PASSED to NOT_ESTABLISHED on 2026-08-18.** Its three testable
observations all discriminate, and 3 of 3 cannot establish a 70% rate: the exact
one-sided 95% Clopper-Pearson lower bound is 0.3684, and 9 of 9 would be needed. The
per-observation measurements did not change and every sigma reproduced to six decimal
places. Do not reinstate the point-estimate comparison; `tests/test_gate3_bound.py`
fails against it.

**Two documents are generated and must not be hand-edited.** `docs/KILL_GATE.md`
(status summary and failure log) by `scripts/sync_kill_gate.py`, and `README.md`
(results tables) by `scripts/sync_readme_results.py`. Run the first with `--check` to
detect drift without writing. It is idempotent as of C7f; the earlier version could
only run once, which is recorded in the KILL_GATE failure log.

**The opening frame and the palette are both checked, not styled.** The plate on the
home page draws gate 3's real null corridors; `scripts/export_hero_nulls.py` writes
nothing unless seven statistics reproduce `artifacts/GATE3_RECEIPT.json` to 1e-9, and
`scripts/build_console_data.py` raises if `artifacts/HERO_NULLS.json` is absent rather
than shipping a frame with no nulls in it. The neutral palette carries an indigo cast
expressed in OKLCH at Carbon's own lightness values, so no contrast ratio moved by
more than 0.03; `scripts/check_contrast.py` recomputes all 26 pairs and
`tests/test_contrast.py` fails the suite if one drops below its floor. Do not pick a
colour by eye here.

**Three gate verdicts on the console come from their receipts** (3, 5 and 6) and three
are literals in `scripts/build_console_data.py` (1, 2 and 4) because they have no
receipt. An unknown verdict raises rather than being silently counted as unmet.

---

### The stage-1 dataset exists. Read this before A6.

Built with `pipeline.tracetriage.snapshot`, chronological back from
2026-08-10T00:00:00Z, no stratification. Every sha256 re-verified against the
bytes on disk with `--verify`.

| | |
|---|---|
| Observations | 2,727 |
| Waterfalls stored | 2,500 |
| No waterfall URL | 227 (all permanent; zero transient failures) |
| Decisive labels | 739, 27.1% |
| with-signal | 462 |
| without-signal | 277 |
| unknown | 1,988, 72.9% |
| Ground stations | 271 |
| Satellites | 526 |
| Transmitters | 613 |

**The dominant fact is the unlabelled majority.** Nearly three observations in
four carry no decisive label. Reading `unknown` as `without-signal` inflates
the negative class about sevenfold and yields a model that has learned which
observations a human got round to vetting.

**The base-rate constants in `provenance.py` are a prior, not a measurement of
this corpus.** `tests/test_base_rates.py` checks them against the built
snapshot through a Wilson interval; all four hold at 99% on 2,727 observations.
`BASE_RATE_POSITIVE_FRACTION` holds by 0.0004 and will need re-measuring when
stage 2 tightens the interval.

**A1 was hardened for throttling after this run.** A 429 now pauses and obeys
`Retry-After` instead of ending the run, and `THROTTLED`, `TIMEOUT` and
`HTTP_ERROR` are transient reasons that a later run retries rather than
burying. Any unit reading the manifest must treat those three as "not fetched",
never as "no signal".

---

### A7 is closed. Read this before B1.

**`scripts/run_triage_slice.py`** is the seam runner. Do not recreate it.
**`scripts/render_evidence_card.py`** is the card renderer. Do not recreate it.
**`artifacts/TRIAGE_RECEIPT.json`** is the receipt for obs 14740031. Do not hand-edit it.
**`artifacts/hoglr_model.pkl`** is the pickled HOG-LR model (scaler + CalibratedClassifierCV).
Regenerate it only by re-running `run_baseline.py --save-model`.

Key facts for B1:
- Gate 3 PASSED: corridor intersects trace for obs 14740031, residual_hz=185.6 < half_width_hz=2000.
- The calibrated baseline (HOG-LR, Brier=0.1516) is the comparison target for gate 5.
- The BASELINE_RECEIPT model_checksum = `e0912b14…` (SHA-256 of `artifacts/BASELINE_RECEIPT.json`).
- `run_triage_slice.py` loads `artifacts/hoglr_model.pkl` for deterministic scoring; re-runs produce identical numbers.
- A3 correction status for obs 14740031 is UNCORRECTED (read from `artifacts/a3_overlays/summary.json`).
  DO NOT infer correction status from metadata fields: they are null for both corrected and uncorrected.

---

### A5 is closed. Read this before A6.

**`pipeline/tracetriage/provenance.py`** is the production provenance module.
Do not regenerate it.  Key facts for any unit that uses it:

- `label_from_obs(obs)` → `ProvenanceRecord`.  Raises `FutureObservationError`
  when `obs["status"] == "future"`.  Never raises for any other input.
- `label_observations(obs_list, *, skip_future=False)` → batch helper.
- `ProvenanceRecord.label_outcome`: `POSITIVE` / `NEGATIVE` / `UNLABELLED`.
- `ProvenanceRecord.labelled_positive`: bool shorthand for `POSITIVE` outcome.
- `ProvenanceRecord.carries_measurable_trace`: bool, separate from the above.
  At provenance time this is always `False` (trace_presence = `UNVETTED`).
  A7 or the model updates it to `MEASURABLE` or `VISIBLE_BUT_UNMEASURABLE`.
- `ProvenanceRecord.vetting_lag_seconds`: seconds between pass end and
  snapshot retrieval.  Small lag = unvetted recent.  None when timestamps missing.
- `to_receipt_provenance(record, *, artifact_sha256, split)` → dict assembling
  the `provenance` sub-object of `contracts/triage_receipt.schema.json`.
- Base rate constants: `BASE_RATE_DECISIVE_FRACTION = 0.290`,
  `BASE_RATE_POSITIVE_TO_NEGATIVE = 1.85`.  Do not rebalance silently.

The four structural invariants enforced by `__post_init__`:
1. `status == "future"` → `FutureObservationError` (never enters label set)
2. `ArtifactStatus.MISSING` + `LabelOutcome.NEGATIVE` → `AssertionError`
3. `carries_measurable_trace=True` requires `trace_presence=MEASURABLE`
4. `labelled_positive=True` requires `label_outcome=POSITIVE`

---

### A4 is closed. Read this before A5.

**`pipeline/tracetriage/physics.py`** is the production corridor module.  Do
not regenerate it.  Key facts for any unit that uses it:

- `corridor_for_obs(obs)` → `PhysicsResult`.  Never raises; all failures return
  a named `degraded` reason code.
- `PhysicsResult.uncorrected`: full Doppler S-curve, `half_width_hz = 2000.0`.
- `PhysicsResult.corrected`: near-vertical residual band, `half_width_hz = 200.0`.
- `AXIS_SIGN_CONVENTION = -1`: positive Doppler → LEFT on the rendered axis.
- `corridor_columns(corridor, hz_per_px, centre_px, image_height)` → pixel
  columns per image row.  Accepts a `freq_offset_hz` argument (search range
  `±FREQ_OFFSET_SEARCH_HZ = ±20 kHz`).
- Validation on 200 observations: median abs error 0.21°, p99 0.61°, 99.5%
  within 1°.  Full distribution in `artifacts/PHYSICS_VALIDATION.json`.
- Degraded reason codes: `MISSING_TLE`, `STALE_TLE`, `SGP4_ERROR`,
  `MISSING_STATION`, `MISSING_FREQ`.

---

### A5 is closed. Read this before touching provenance.py

`ProvenanceRecord` keeps `labelled_positive` and `carries_measurable_trace` as
separate fields with separate enums, which is what A6 needs: A3 measured that
only 7 of 24 vetted `with-signal` observations carry a trace anything can score,
so a baseline trained on "labelled positive" is trained on a target that is
absent from two thirds of its positives.

**Invariants raise, they never assert.** `python -O` strips assert statements
and no suite runs under `-O`, so five of the six invariants shipped enforced
only in the environments that test them. Under `-O` a record constructed
cleanly with `label_outcome=UNLABELLED` alongside `labelled_positive=True`.
`TestInvariantsSurviveOptimisedMode` now runs that construction in a subprocess
under `-O` and fails if it succeeds. Do not convert any invariant back to an
assert, here or anywhere else on the judged path.

### A4 is closed. Read this before touching physics.py

A4's acceptance has been run live and **it passes**: 199 of 200 observations
succeed against the API's own `max_altitude`, median absolute error 0.21 deg,
p99 0.61 deg, 99.5% within 1 deg, the one failure a named `STALE_TLE`. Both
corridor shapes are emitted and every degraded path returns a reason code.

The orientation guards are real, not decorative: flipping the time mapping fails
three tests and flipping the use of the sign constant fails three more. One test
only asserts `AXIS_SIGN_CONVENTION == -1`, which is a tautology, but behavioural
tests sit beside it, so the constant cannot be misused silently.

**Corridor widths are measurements now, and must stay that way.** The corrected
half-width shipped at 200 Hz, copied from A3 where that number was a line drawn
on an overlay, not a tolerance. The four corrected carriers A3 measured wander
77, 639, 639 and 1935 Hz within their own pass, so 200 Hz contained none of
them and would have failed kill gate 3 for a reason that is not real. It is
1200 Hz, and `TestCorridorWidthsAreMeasured` fails if it shrinks back.

### A3 is closed. Read this before building the corridor in A4

**The answer is BOTH.** Corrected and uncorrected captures both occur in the
public network, and **no metadata field distinguishes them**:
`doppler-correction-per-sec` was null and `rigctl-port` was `4532` on all 24
observations measured, in both groups. 4 corrected across 4 stations, 4
satellites and 3 bands; 3 uncorrected across 3 satellites and 2 stations; 17
carried no measurable narrowband trace. Full method, margins and open questions:
**`docs/DOPPLER_CORRECTION_FINDING.md`**. Evidence: 24 overlays in
`artifacts/a3_overlays/`.

So A4's corridor must handle both shapes and must infer correction status from
the image. Do not key it on metadata, and do not assume the corridor is centred
on `rx-freq`: the uncorrected traces sat 14.0, 2.4 and 1.8 kHz off it.

**Two calibration facts. Do not re-derive them, and do not check them by eye.**

- **Time runs bottom to top.** The top row is the END of the pass. Measured off
  observation 14740031: the `200` s tick at y=258, the `50` s tick at y=1228.
- **The plotted frequency axis runs against the Doppler sign.** Scanned, not
  assumed; all three uncorrected observations agreed, at 25.1 against 2.0 sigma,
  15.1 against 1.2, and 15.9 against 1.4.

These two errors cancel, because a Doppler curve is near odd-symmetric about
closest approach. The first implementation had both wrong, scored 25 sigma and
looked correct in its overlay. **A visual check cannot catch this class of
defect.** If A4 needs to confirm an orientation, scan it and report the margin.

**Do not touch `scripts/a3_doppler_investigation.py` or re-run it casually.**
The public API throttled this project twice, at 1551 s and 3419 s. Pages and
waterfalls are cached under `.a3_cache/`, so a rerun reproduces every number
from the same bytes at no request cost, but only while that cache exists.

### A1 is closed. Read this before touching snapshot.py

A1's acceptance has been run live and **it passes**: 52 observations, 50 waterfalls, 3 pages in 56 s, and a second run resuming in 0.42 s with zero pages re-fetched.

Additional hardening was done on the operator's side in commit `931d2cd`. **Do not overwrite, revert or regenerate it.** Three defects were fixed:

1. The manifest and the resume index were written to and read from one global path regardless of `--out`. Stage 2 running in the background during Wave B would have loaded stage 1's observations as its own resume state and emitted a manifest describing files in a directory it does not name. The manifest now lives in `--out` and is mirrored to `artifacts/DATASET_MANIFEST.json` only on completion.
2. `--target-waterfalls` defaulted to 2300, so omitting it began a production-scale crawl. Now required unless `--verify` is given.
3. `--verify` ran after a full fetch rather than instead of one. It is now a mode that fetches nothing.

Two `TestResumeAfterInterrupt` cases were repointed at the snapshot directory, and `scripts/gate.py` now decodes subprocess output as UTF-8, because the Windows ANSI codepage crashed it whenever a test failed.

**Do not re-run a large snapshot casually.** Investigating those defects already put 578 observations and 870 MB of load on SatNOGS. Always pass `--target-waterfalls` explicitly.

**Start each unit in a fresh chat.** Paste the master prompt from `docs/BOB_TASK_PROMPTS.md`, then the unit prompt.

### A2 is closed. Read this before touching waterfall.py

A2's acceptance has been run live and **it passes**: 52 tests, 135 offline tests, Hz/px within 1% on both client layouts (0.245% error on 836px, 0.233% on 832px), all schema-valid, all degraded states named. Gate 7/7.

Key facts:
- `pipeline/tracetriage/waterfall.py` is the production parser. EasyOCR is used for tick label reading (inverted 4× image, sign from position not from OCR). `EASYOCR_MODULE_PATH=D:/cache/easyocr/model` must be set or model weights must exist at that path. `download_enabled=False`, no runtime downloads.
- `contracts/waterfall_geometry.schema.json` is now 0.2.2: `plot_box` is nullable (was 0.2.1 where it was type `"object"` only).
- The OCR reader is module-level cached. First call per process takes ~5s to load the model; subsequent calls are fast. This is acceptable for batch processing.
- **Do not redo the axis detection.** The two measured layouts (836px at 123.46 Hz/px, 832px at 80.00 Hz/px) are reproduced within 1% by the OCR-based approach.

Additional hardening in `038ed1a`. **Do not overwrite it.** EasyOCR's weights are not in the repository, so as delivered the project's two most important numbers could only be checked on one machine. With the import blocked, four tests failed outright and two skipped, including the crop-content checks. Reading the axis glyphs needs a neural model; deriving Hz/px from what was read does not, and those are separable steps.

- `easyocr` is now declared as an optional `ocr` extra, not an undeclared import. A clean clone installs and runs without it.
- `parse_waterfall` takes an optional `ocr_results`. The reading of both fixtures is committed to `tests/fixtures/ocr_labels.json`, regenerated by `scripts/dump_ocr_fixture.py`, and the Hz/px derivation is asserted against it. The full offline suite passes with `easyocr` absent: 135 passed.
- A committed cache can rot into numbers that agree only with themselves, so an `ocr`-marked test runs the live model where weights exist and fails if it stops reading what the cache claims.
- `scripts/gate.py` and CI both exclude the `ocr` marker. **Run `pytest -m ocr` yourself whenever you touch the OCR path**, because the gate will not.

### Budget

40 build credits is per trial account, not a project ceiling. The July 28 FAQ removed the single-account limit (`BUILD_BUDGET.md` line 3, `MASTER_PLAN_TRACE_TRIAGE.md` line 154): when credits run out, create another trial with a different email you own and follow the published switch procedure. A rotation is a planned event, not a failure. What costs you is a bad handoff, so the stop-at-3-credits rule and the rotation checklist below are the parts that matter.

---

## What exists right now

**Two production modules exist and both are closed.** `pipeline/tracetriage/snapshot.py` (A1, the immutable snapshot builder) and `pipeline/tracetriage/waterfall.py` (A2, the pixel-mapping parser). Do not regenerate either. Everything below this line describes the scaffold that predates them and is still accurate.

Working and verified:

- Python **3.12.13** venv at `.venv`, with the full stack installed and every import confirmed: polars 1.43.2, pyarrow 25.0.1, numpy 2.5.2, scipy 1.18.0, Pillow 12.3.0, opencv 5.0.0, **sgp4 2.27**, **torch 2.13.0+cpu**, torchvision 0.28.0, scikit-learn 1.9.0, scikit-image 0.26.0, httpx, tenacity, matplotlib, onnxruntime 1.28.0, pytest 9.1.1.
- `pytest -m "not network"` passes. `conftest.py` blocks socket access in unmarked tests, so the offline-replay claim is enforced rather than asserted.
- CI at `.github/workflows/ci.yml`: clean clone, offline suite, claim drift, secret scan.
- Six contracts in `contracts/`, all ratified. Do not re-ratify them.
- Doc skeletons, MIT `LICENSE`, `DATA_LICENSE.md`, `.gitignore`, `.env.example`.

Exhaustive inventory with the boundary: **`docs/PRE_BUILD_BASELINE.md`**.

---

## Facts already verified. Do not spend credits rediscovering these.

Full method and numbers: `docs/SATNOGS_API_RECON.md`. The short version:

**API shape.** Observations are on `network.satnogs.org`; `db.satnogs.org/api/observations/` returns 404. No authentication needed. Every field the physics needs is on the observation record, so no join is required.

**Two filters that lie.** `end__lte=` returns HTTP 200 and is **silently ignored**; use bare `end=`. `waterfall_status=` is **not a filter** and returns HTTP 400; filter it client-side. A bare listing returns future observations with null waterfalls.

**Coverage, measured over 600 observations.** TLE 100%, client_metadata 94.0%, waterfall URL 92.3%, decisive `waterfall_status` 29.0%. 211 stations, 197 transmitters, 179 NORAD IDs. `center_frequency` is **null in practice**: use `client_metadata.radio.parameters.rx-freq`, and note `client_metadata` is a JSON-encoded **string**.

**The pixel mapping, which is the expensive one.** The waterfall does **not** span `samp-rate-rx`. Measured **123.46 Hz/px** on one client and **80.00 Hz/px** on another, against a 2.5 MHz sample rate, roughly a 32x decimation that nothing in the API reports. Assuming the sample rate compresses the Doppler corridor from ~118 px to ~5 px. The plot box is also not the image box: x=66..686 on one client, x=74..677 on another, with a colorbar at x=724..755 on the first.

**Geometry is proven.** An observation's own stored TLE plus station coordinates reproduced pass geometry to **0.18 degrees** against the API's own `max_altitude`, with the range-rate sign flipping exactly at peak elevation. Build on this rather than re-verifying it.

---

## Decisions already taken. Do not re-open these.

- **Snapshot is staged: 2,500 observations (~4 GB) then 30,000 (~47 GB).** Decided 2026-08-16 15:40 IST. Disk is not a constraint (103 GB free on D:, 1 TB external available). Stage 1 unblocks gates 3 to 5 in about 45 minutes; stage 2 runs overnight while you work on Wave B, and reaches ~3,050 decisive negatives, which is what the cold-entity holdouts need for usable bootstrap intervals. Task A1 carries the arithmetic and the stratification requirement.
- **Use the GPU.** RTX 3070 Ti, 8 GB VRAM, `torch 2.13.0+cu126` installed and verified, **14.9x measured** over CPU. CI stays CPU on purpose. Guard against a silent CPU fallback: a run that lands on CPU still finishes, just fifteen times slower, and says nothing. See `docs/HARDWARE_PROFILE.md`.
- **16 GB RAM is the binding constraint, not disk.** Stream every stage. A full image tensor stack is ~26 GB in float32 and will not fit.
- **Concept is settled.** TraceTriage, August Space theme. Do not re-select the concept, re-research competitors, or reconsider the rejected PassCast design.
- **Python 3.12**, not the machine's 3.14, for wheel coverage across opencv, scikit-image and onnxruntime.

## The one blocking unknown

**Are SatNOGS waterfalls already Doppler-corrected at capture?**

`doppler-correction-per-sec` was null on every record inspected, while `rigctl-port` was populated, which points to correction happening externally through rig control. If corrected, model the residual around a near-vertical corridor. If uncorrected, expect the full S-curve.

These produce completely different overlays, and choosing wrong fabricates evidence. **Task A3 exists solely to answer this, and it blocks A4.** Do not build the corridor overlay before it is settled.

---

## Kill gate position

Three of six gates pre-measured. See `docs/KILL_GATE.md` for thresholds and evidence.

- Gate 1 (volume and entity spread): pre-passed on feasibility, closes when your snapshot exists
- Gate 2 (metadata coverage): **pre-passed**, 86.3% worst-case against an 80% floor
- Gate 3 (corridor intersects trace): open, highest risk, closes at task A7
- Gates 4, 5, 6: open, need the snapshot

> If gate 3 fails, **re-verify the Hz/px derivation before accepting the failure.** The wrong constant makes a working corridor look like a vertical line.

---

## Exact next task

In a **fresh Bob chat**: paste the master prompt from `docs/BOB_TASK_PROMPTS.md`, then unit **B1: cold-entity splits + physics-conditioned model**.

Wave A is complete (A0 to A7). The seam works. The corridor intersects the trace (gate 3 PASSED). The baseline is calibrated and beats the prior. Wave B builds volume: cold-entity splits, physics feature extraction for all 2,500 waterfalls, and the physics-conditioned HOG model that gate 5 requires.

### What A0 settled, so A1 does not rediscover it

- Five contracts in `contracts/` are `ratified`. `dataset_manifest.schema.json` is the one A1 writes against, and A1's acceptance ("manifest validates against its contract") now has a contract to validate against.
- `jsonschema>=4.23` is installed and declared. The venv has **no `pip`**, it is uv-managed: `uv pip install <pkg>` with `VIRTUAL_ENV` set to the project `.venv`.
- `tests/test_contracts.py` already rejects a manifest that claims `end__lte` or `waterfall_status` as a server-side filter. A1 does not need to re-test those two traps at the schema level, only in the client.
- **Carry into A1:** `client_version` and `client_family` are in the manifest's observation entry but not in its `required` list. Both are nullable, so adding them is free and is what enforces the "keep the raw string" requirement. Do it while writing the emitter.

---

## Rotation checklist

Before the account runs dry, at **3 credits remaining**:

1. Stop starting new features.
2. Run the full test and acceptance suite. Record what passes and what does not.
3. Update this file: completed work, open failures, **exact** next task, changed files, test commands, dataset and model hashes, architectural decisions taken.
4. Update `docs/BOB_BUILD_LOG.md` with the genuine task history, commit SHAs, failures, repairs and actual credit use.
5. Export task history and screenshots to `bob_sessions/`, secrets removed.
6. Commit.

The next account reads this file, reruns the tests, inspects the current code, and continues at the next unfinished unit. **It must not regenerate completed modules.**


---

## Failure injection: what D8 left

`docs/DEGRADED_STATE_RECON.md` maps all twelve modes to the reason the code emits, with
file and line, and to the test that asserts it. Read it before touching this. As of D8:

- Six modes have a test that asserts the exact reason, in `tests/test_failure_injection.py`.
- Six were already covered in the module they belong to, anchored in that file's docstring.
- **All twelve now have a named reason and a test.** The last one, the multiple-trace mode,
  landed in D8b as `corridor_fit.second_trace_evidence`, with the incidence measured in
  `artifacts/SECOND_TRACE_SURVEY.json`: 10 of 182 measurable decisive observations, where
  543 of 743 cannot be measured at all because fewer than eight rows carry a pixel at
  `z_min`. It is **not** wired into the feature matrix, on purpose: that route runs through
  `corridor_features.json` and `features.py` and would require a refit, which moves the
  numbers behind gates 5 and 6.
- Eleven reason constants can be emitted with nothing asserting them, listed in the recon
  document. A rename or a lost branch on any of those passes the suite today.
