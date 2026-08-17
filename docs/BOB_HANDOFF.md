# Bob handoff

**Read this and `.bob/rules.md` before every task.** Update it before every account rotation and at the end of every session.

---

## Current state

| | |
|---|---|
| **Handoff written** | 2026-08-17, IST |
| **Units completed** | **A0** (`8ef8d1f`), **A1** (`be915b5`), **A2** (`f64deec`), **A3** (`c7ca696`), **A4** (`0f21ce7`), **A5** (`68bac8c`), **A6** (see build log), **A7** (this session) |
| **Account in use** | account 3 |
| **Current wave** | Wave A, complete |
| **Next unit** | **B1: cold-entity splits + physics-conditioned model** |
| **Open failures** | none. Gates 1–3 passed. Gates 4–6 open. 221+ tests pass offline. |
| **Dataset** | stage 1 built and verified: `D:/tracetriage_data/snap-stage1`, 2,727 observations, 2,500 waterfalls, 739 decisive labels |
| **Last commit** | see `git log -1` |

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
  DO NOT infer correction status from metadata fields — they are null for both corrected and uncorrected.

---

### A5 is closed. Read this before A6.

**`pipeline/tracetriage/provenance.py`** is the production provenance module.
Do not regenerate it.  Key facts for any unit that uses it:

- `label_from_obs(obs)` → `ProvenanceRecord`.  Raises `FutureObservationError`
  when `obs["status"] == "future"`.  Never raises for any other input.
- `label_observations(obs_list, *, skip_future=False)` → batch helper.
- `ProvenanceRecord.label_outcome` — `POSITIVE` / `NEGATIVE` / `UNLABELLED`.
- `ProvenanceRecord.labelled_positive` — bool shorthand for `POSITIVE` outcome.
- `ProvenanceRecord.carries_measurable_trace` — bool, separate from the above.
  At provenance time this is always `False` (trace_presence = `UNVETTED`).
  A7 or the model updates it to `MEASURABLE` or `VISIBLE_BUT_UNMEASURABLE`.
- `ProvenanceRecord.vetting_lag_seconds` — seconds between pass end and
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
- `PhysicsResult.uncorrected` — full Doppler S-curve, `half_width_hz = 2000.0`.
- `PhysicsResult.corrected` — near-vertical residual band, `half_width_hz = 200.0`.
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

40 Bobcoins is per trial account, not a project ceiling. The July 28 FAQ removed the single-account limit (`BOBCOIN_BUDGET.md` line 3, `MASTER_PLAN_TRACE_TRIAGE.md` line 154): when coins run out, create another trial with a different email you own and follow the published switch procedure. A rotation is a planned event, not a failure. What costs you is a bad handoff, so the stop-at-3-coins rule and the rotation checklist below are the parts that matter.

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

## Facts already verified. Do not spend coins rediscovering these.

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

Wave A is complete (A0–A7). The seam works. The corridor intersects the trace (gate 3 PASSED). The baseline is calibrated and beats the prior. Wave B builds volume: cold-entity splits, physics feature extraction for all 2,500 waterfalls, and the physics-conditioned HOG model that gate 5 requires.

### What A0 settled, so A1 does not rediscover it

- Five contracts in `contracts/` are `ratified`. `dataset_manifest.schema.json` is the one A1 writes against, and A1's acceptance ("manifest validates against its contract") now has a contract to validate against.
- `jsonschema>=4.23` is installed and declared. The venv has **no `pip`**, it is uv-managed: `uv pip install <pkg>` with `VIRTUAL_ENV` set to the project `.venv`.
- `tests/test_contracts.py` already rejects a manifest that claims `end__lte` or `waterfall_status` as a server-side filter. A1 does not need to re-test those two traps at the schema level, only in the client.
- **Carry into A1:** `client_version` and `client_family` are in the manifest's observation entry but not in its `required` list. Both are nullable, so adding them is free and is what enforces the "keep the raw string" requirement. Do it while writing the emitter.

---

## Rotation checklist

Before the account runs dry, at **3 coins remaining**:

1. Stop starting new features.
2. Run the full test and acceptance suite. Record what passes and what does not.
3. Update this file: completed work, open failures, **exact** next task, changed files, test commands, dataset and model hashes, architectural decisions taken.
4. Update `docs/BOB_BUILD_LOG.md` with the genuine task history, commit SHAs, failures, repairs and actual coin use.
5. Export task history and screenshots to `bob_sessions/`, secrets removed.
6. Commit.

The next account reads this file, reruns the tests, inspects the current code, and continues at the next unfinished unit. **It must not regenerate completed modules.**
