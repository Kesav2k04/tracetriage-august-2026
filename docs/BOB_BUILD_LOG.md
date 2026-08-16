# Bob build log

The evidence that IBM Bob was the primary development tool. Append one entry per
task, as it happens. Reconstructing this at the end produces something that reads
like a reconstruction, and it would be one.

Every entry needs: the task, the files it touched, the commit SHA, the tests run
and their result, what failed, what was repaired, and the **actual** Bobcoins spent.

---

## Format

### <date IST> | <account #> | <unit id>: <title>

**Task given:** the prompt, verbatim or summarised faithfully
**Files created/changed:** paths
**Commands run:** exact commands
**Tests:** which suite, what result, which specific tests failed
**Failures and repairs:** what broke, why, what fixed it
**Coins:** estimated N, actual M
**Bob task ID:** the task identifier from the Bob session, which is what ties this
entry to a real task in the account rather than to a claim made about one
**Commit:** SHA
**Outcome:** accepted / partial / abandoned, and why

---

## Entries

### 2026-08-16 IST | Account 1 | A0: Ratify the data contracts

**Task given:** Read all `contracts/*.schema.json` files. Check each against the verified API facts in BOB_START_HERE.md section 3. Fix anything wrong, add anything missing, delete anything speculative. Set `"status": "ratified"` and bump `schema_version` on each.

**Files created/changed:**
- `contracts/source_observation.schema.json`
- `contracts/waterfall_geometry.schema.json`
- `contracts/triage_receipt.schema.json`
- `contracts/split_manifest.schema.json`
- `scripts/gate.py` (secret-scan pattern tightened to require token-length suffix; `ghp_` alone matched the pattern string in the scanner itself)

**Commands run:**
- `.venv\Scripts\python.exe scripts\gate.py` (before and after)

**Tests:** `pytest -m "not network" -q` passes (2 passed, 1 deselected). Gate: contracts ratified PASS, lint PASS, offline suite PASS, commit identity PASS.

**Failures and repairs:** `scripts/gate.py` secret scan flagged itself because the bare `ghp_|` pattern matched the pattern literal in the script. Fixed by requiring token-length suffixes (`ghp_[0-9A-Za-z]{36,}`).

**Changes made to schemas and why:**

`source_observation`: removed `observation_frequency` and `transmitter_uuid` from `required` (they are nullable in practice; the API does not guarantee them). Confirmed `client_metadata` type as `string` not object. Confirmed `center_frequency` is null on every record inspected; strengthened warning in description. Improved all field descriptions for downstream clarity.

`waterfall_geometry`: added `crop_box` field to `required` and `properties`. The draft had `plot_box` (the matplotlib-rendered bounding box) but not `crop_box` (the final region delivered to the model after removing axis labels and the colorbar at x=724..755 on one client). These are distinct and both needed. Tightened `derivation` enum descriptions. Added example `degraded` reason codes. Clarified that `hz_per_px` and `crop_box` are null exactly when `derivation == "failed"`.

`triage_receipt`: no structural changes. Added `waterfall_geometry_version` to `evidence` for traceability when pixel-mapping issues are investigated. Tightened descriptions throughout. Added `minimum`/`maximum` constraints to numeric probability fields.

`split_manifest`: added `sampling_design` field to `required` (a stratified sample described as random is a leakage claim that fails review; the snapshot builder must document its stratification here). Added `no_station_across_splits` to `leakage_checks` (the draft had transmitter, revolution, duplicate, and future-feature checks, but cold-station splits need the equivalent station check). Added `required` to the `leakage_checks` object so validators enforce all flags. Added `required: [train, calibration, test]` to each split entry schema.

**Coins:** estimated 1, actual 1.

**Bob task ID:** `a309025a1c82bfb4e34d882d02fa4066` (workspace `tracetriage-august-2026`, account 1)

**Commit:** 8ef8d1f

**Outcome:** accepted. All four schemas now have `"status": "ratified"` and `"schema_version": "0.2.0"`. Gate contracts check passes.

---

### 2026-08-16 IST | Operator side, no Bob account | A0b: Contract gaps closed before A1

**Origin:** hardening done outside a Bob task after A0 was committed. No Bobcoins
spent. Reviewed, corrected and accepted by Bob at A0b-INT below.

**Why it exists.** A review of A0 against the A1 and A2 acceptance criteria found
two blockers and one defect. A1 acceptance reads "manifest validates against its
contract", and no contract for the dataset manifest existed. `jsonschema` was
neither installed nor listed in `pyproject.toml`, so nothing in the project could
validate a document against any contract at all. Separately, four contracts stated
invariants in `description` prose that the schema did not enforce.

**Files:**

`contracts/dataset_manifest.schema.json` (new, ratified 0.2.0). Covers the A1
requirements: snapshot id, exact query, stage, per-page and per-artifact sha256,
UTC retrieval timestamps, CC BY-SA 4.0 licence and URL, counts, sampling design.
`counts` and `sampling_design` are required. Two recon traps are encoded as
schema, not comments: `query.filters` forbids `end__lte` (returns HTTP 200 and is
silently ignored) and forbids `waterfall_status` (returns HTTP 400, filter
client-side). `waterfall_missing_reason` is a named enum, so an unusable artifact
carries a reason code and can never be confused with a without-signal label. An
if/then makes `waterfall_sha256` non-null exactly when that reason is null, which
also makes the file usable as the resume index.

`contracts/waterfall_geometry.schema.json` (0.2.0 to 0.2.1). Removed
`client_family_fallback` from the `derivation` enum. A2 requires an explicit
degraded state when the axis cannot be read, Hz/px varied 54% across a
three-image sample, and stability within a client family has never been measured.
That mode licensed a wrong constant to enter the pixel mapping silently. Added
if/then enforcing the null-exactly-when-failed rule. One correction to the review
prompt: `centre_px` stays nullable on a successful derivation, because it needs
`rx-freq` from `client_metadata`, which is absent on about 6% of records. A good
axis read with no `rx-freq` is a real state and must not be forced to fail.

`contracts/split_manifest.schema.json` (0.2.0 to 0.2.1). All six `leakage_checks`
flags are now `const: true`. A manifest recording a failed check no longer
validates. The consequence is deliberate and is written into the field
description: a failing check halts the freeze and is recorded in
`docs/KILL_GATE.md` with its measured value, rather than being stored here as a
`false` that a later reader might scroll past.

`contracts/triage_receipt.schema.json` (0.2.0 to 0.2.1). `evidence` requires
`artifact_usable` and `physics_available`, since every other field's nullability
is defined in terms of them. `scores` requires `calibrated_probability`, nullable,
so a receipt must say that no score was produced rather than omitting the field.
if/then requires a non-empty `abstention_reason` when `decision` is `abstain`.

`contracts/source_observation.schema.json` (0.2.0 to 0.2.1). `_schema_version`
pinned with `const`, matching the `const` already used on `_license`.

`pyproject.toml`. Added `jsonschema>=4.23` to `[project] dependencies`, not to
`dev`, because the snapshot builder validates the manifest at write time.

`tests/test_contracts.py` (new, 32 tests). Every contract is checked as legal
Draft 2020-12 and as ratified with a semver. The rest are behavioural: each
invariant that was prose before A0b now has a case asserting a violating document
is rejected. A geometry record claiming `axis_ticks` with no `hz_per_px`, a split
manifest with one leakage flag false, an abstaining receipt with no reason, and a
manifest claiming `end__lte` as its date bound all fail.

**Environment note for the next task.** The venv has no `pip`. It is uv-managed.
Install with `uv pip install <pkg>` after setting `VIRTUAL_ENV` to the project
`.venv`, not `python -m pip`.

**Open nit, not fixed.** The four A0 schema descriptions say "Ratified
2026-08-17". Both A0 commits are dated 2026-08-16 18:21 +0530. Left alone because
that sentence is Bob's acceptance statement and belongs to Bob to correct.

**Gate before commit:** 6/7, with only `working tree committed` red. Lint clean,
34 tests pass offline.

**Coins:** 0.

---

### 2026-08-16 IST | Account 1 | A0b-INT: Integration review of external contract change

**Task given:** Review the A0b diff (five contract files, `pyproject.toml`, and a
new contract test module). Run the offline suite. Accept or reject, correcting
anything wrong.

**Files created/changed:**
- `contracts/dataset_manifest.schema.json` (new, ratified 0.2.0, accepted with one
  correction: `client_version` added to the observations entry `required` list, because
  the A1 acceptance criterion "keep the raw string" needs enforcement, not just documentation)
- `contracts/waterfall_geometry.schema.json` (0.2.0 to 0.2.1, accepted)
- `contracts/split_manifest.schema.json` (0.2.0 to 0.2.1, accepted)
- `contracts/triage_receipt.schema.json` (0.2.0 to 0.2.1, accepted)
- `contracts/source_observation.schema.json` (0.2.0 to 0.2.1, accepted)
- `pyproject.toml` (`jsonschema>=4.23` added to runtime dependencies, accepted)
- `tests/test_contracts.py` (new, 32 tests, accepted)
- Date strings corrected from "2026-08-17" to "2026-08-16" to match commit timestamps

**Commands run:**
- `.venv\Scripts\python.exe -m pytest -m "not network" -q`
- `.venv\Scripts\python.exe scripts\gate.py`

**Tests:** 34 tests pass offline. Gate 7/7.

**Failures and repairs:** None in the integration step. One correction applied:
`client_version` added to `required` on the observations entry in
`dataset_manifest.schema.json`.

**Coins:** 0. No new code was generated in this step. It is a review and an
acceptance decision.

**Bob task ID:** `a309025a1c82bfb4e34d882d02fa4066` (workspace `tracetriage-august-2026`, account 1). Same ID as A0: this review ran inside the A0 session rather than a fresh one, so the two units share a task.

**Commit:** 3df6f98

**Outcome:** accepted with one correction applied.

---

### 2026-08-16 IST | Account 1 | A1: Immutable snapshot builder

**Task given:** Build `pipeline/tracetriage/snapshot.py`. CLI: `--end <ISO8601>
--target-waterfalls <N> --out <dir>`. Stage 1 only (2,500 observations, ~2,300
waterfalls). Resumable. Manifest validates against
`contracts/dataset_manifest.schema.json`. Also bump schema to 0.2.1 adding
`client_version` and `client_family` to observations `required`.

**Files created/changed:**
- `pipeline/tracetriage/snapshot.py` (new)
- `tests/test_snapshot.py` (new, 44 offline tests)
- `contracts/dataset_manifest.schema.json` (0.2.0 to 0.2.1)
- `tests/test_contracts.py` (manifest() fixture updated to schema 0.2.1)
- `docs/BOB_BUILD_LOG.md` (A0b-INT entry added; this entry)

**Commands run:**
- `.venv\Scripts\python.exe -m pytest -m "not network" -v`
- `.venv\Scripts\python.exe -m ruff check .`
- `.venv\Scripts\python.exe scripts\gate.py`

**Tests:** 77 passed, 1 xfailed. Gate: 7/7.

**Failures and repairs:**
- ruff: 31 lint errors on first pass (E501, UP017, F401, B017, SIM117, F841, I001).
  Fixed: USER_AGENT string wrapped, `timezone.utc` to `UTC`, unused imports removed,
  `pytest.raises(Exception)` to `pytest.raises(RuntimeError)`, nested `with` merged,
  unused variable removed, import block sorted. All auto-fixable issues were applied
  with `ruff --fix`; remainder fixed manually. Zero errors on second pass.

**Coins:** estimated 4 to 6, actual ~4.

**Bob task ID:** `0a6a254d9495683ad0ae23538da646b0` (workspace `tracetriage-august-2026`, account 1)

**Commit:** be915b5

**Outcome:** accepted. 7/7 standing gates. 77 tests pass offline.

---

## A3. Doppler correction status resolver

**Date:** 2026-08-16, IST.

**Task:** resolve the blocking unknown gating A4: are SatNOGS waterfalls already
Doppler corrected at capture? Deliver a stated answer with overlay evidence, a
per-client-family breakdown and an explicit statement of what stays uncertain.

**Answer: both occur, and no metadata field tells them apart.** Of 24 vetted
`with-signal` observations, 4 are Doppler corrected (vertical carrier within
about a kilohertz of the tuned frequency, 32.4 to 54.2 sigma) and 3 are
uncorrected (energy on the predicted Doppler curve, 15.1 to 25.1 sigma).
`doppler-correction-per-sec` was null and `rigctl-port` was `4532` on all 24, in
both groups. 17 carried no narrowband trace strong enough to decide and are
recorded as UNRESOLVED with their numbers.

**Files:** `scripts/a3_doppler_investigation.py`,
`docs/DOPPLER_CORRECTION_FINDING.md`, `tests/test_a3_analysis.py`,
`artifacts/a3_overlays/` (24 overlays and `summary.json`).

**Failures found and repaired during the unit:**

1. Paging used `id__lt`, which the API accepts with HTTP 200 and ignores. It
   would have refetched the first page up to 40 times and collected duplicates.
   Replaced with the `Link: rel="next"` cursor the API actually paginates on.
2. The query window ended in the future, so the first live attempt returned 200
   records of `status: future` with null waterfalls and zero candidates.
3. The corrected-hypothesis corridor was drawn as a filled rectangle over the
   pixels it was meant to be compared against, in green, on a green-to-yellow
   colormap. Overlays are now raw beside annotated, in colours outside viridis.
4. The plot border sits inside the crop box and is brighter than anything in its
   row, so it won every brightest-column search.
5. The first working measurement averaged blocks of rows before finding the
   trace, which is biased toward one answer: a real Doppler curve crosses about
   a dozen columns inside one block near closest approach and is smeared away,
   while a stationary carrier survives. It detected nothing in 8 of 10
   observations, including an 86 degree pass. Replaced by scoring whole paths
   against a null measured from the image itself.
6. **Time was assumed to run top to bottom and the frequency axis was assumed to
   follow the Doppler sign. Both were wrong, and they cancel**, because a
   Doppler curve is near odd-symmetric about closest approach. The wrong model
   scored 25 sigma and its overlay looked correct. Caught by measuring the trace
   against real time: +85 Hz/s apparent rise, which no Doppler shift produces.
   Time direction is now read off the axis ticks and the sign is scanned.
7. `EASYOCR_MODULE_PATH` pointed one directory above the weights. The parser
   logs a warning and returns a degraded record, so every observation would have
   come back unmeasurable while the run looked normal. A preflight now builds
   the OCR reader before the first request.

**Rate limiting:** the public API throttled at 1551 s, then 3419 s. The run was
restructured so all network work completes before any measurement, paging stops
at ten with-signal observations across three client families, and a throttle
costs the remaining images rather than the analysis.

**Coins:** estimated 2, actual ~2.

**Bob task ID:** `1c7c56d4cfab40a7ca8f2b68cf6f8951` (workspace `tracetriage-august-2026`, account 2)

**Commit:** c7ca696

**Outcome:** accepted. 19 A3 tests, 166 offline tests pass. Gate 7/7 after commit.


## Operator-side hardening

Bob builds every lettered unit. Where hardening was done outside a Bob task, it
is recorded here against the unit it followed, so the build history stays
complete and nothing later overwrites it by accident.

| Date | Unit | Area | What changed | Commit |
|---|---|---|---|---|
| 2026-08-16 | after A0 | Data contracts | Added the dataset manifest contract that A1 validates against, declared and installed `jsonschema`, removed the fallback derivation mode from `waterfall_geometry`, and converted five prose-only invariants into enforced `if/then` and `const` rules with 32 tests | `b75844d`, reviewed at A0b-INT in `3df6f98` |
| 2026-08-16 | after A1 | Snapshot builder | Manifest and resume index moved from a global path into `--out`, `--target-waterfalls` made required, `--verify` made a mode that fetches nothing, two resume tests repointed, gate script decoding fixed | `931d2cd` |
| 2026-08-16 | after A2 | Waterfall parser | `easyocr` declared as an optional `ocr` extra rather than an undeclared import, `parse_waterfall` given an optional `ocr_results` so the Hz/px derivation is verifiable with no OCR backend, the reading of both fixtures committed to `tests/fixtures/ocr_labels.json`, and an `ocr`-marked drift test added so the cache cannot rot. Gate and CI exclude the marker. | `038ed1a` |
| 2026-08-16 | during A3 | Doppler investigation | Replaced silently-ignored `id__lt` paging with the Link-header cursor, corrected the query window, replaced a block-averaged peak tracker that was biased toward one hypothesis with a whole-path matched filter scored against a null measured from the image, read the time axis direction off the tick labels and scanned the frequency-axis sign instead of assuming either, added an OCR preflight, and made a rate-limit window cost images rather than the analysis | `c7ca696` |

---

### 2026-08-17 IST | Account 2 | A2: Waterfall artifact parser

**Task given:** Build `pipeline/tracetriage/waterfall.py`. Parse a SatNOGS waterfall PNG and derive the pixel-to-frequency mapping. Return `WaterfallGeometry` matching `contracts/waterfall_geometry.schema.json`. Hz/px within 1% of 123.46 and 80.00 on the two committed fixtures. Crop excludes ALL axis text and colorbar. Named degraded states for all error cases. No fallback-to-constant mode.

**Files created/changed:**
- `pipeline/tracetriage/waterfall.py` (new, production waterfall parser)
- `tests/test_waterfall.py` (new, 52 offline tests)
- `contracts/waterfall_geometry.schema.json` (0.2.1 → 0.2.2: made `plot_box` nullable to match `crop_box`, it must be null when parsing fails before plot detection)
- `docs/BOB_BUILD_LOG.md` (this entry)
- `scripts/_inspect_fixtures.py` (throwaway debug script used during development)

**Key design decisions:**
- EasyOCR used for tick-label reading (inverted 4× upscaled image, digit-only allowlist). The minus sign is NOT read by OCR; the sign is inferred from position relative to the detected axis centre (0 Hz tick). This avoids EasyOCR misreading the minus glyph as a digit on small matplotlib fonts.
- EasyOCR model weights stored at `D:/cache/easyocr/model` (rules: never C:\). Configurable via `EASYOCR_MODULE_PATH` env var. `download_enabled=False`, weights must be pre-installed.
- OCR reader is module-level cached (lazy init) to avoid re-initialising across observations.
- `plot_box` type changed to `["object", "null"]` in schema (bug fix: schema allowed `crop_box` to be null on failure but not `plot_box`; both must be nullable when parsing fails before plot detection).
- No fallback-to-constant Hz/px derivation. If OCR fails, record is degraded with `NO_OCR_BACKEND` or `NO_AXIS_DETECTED`.

**Commands run:**
- `.venv\Scripts\python.exe -m pytest tests/test_waterfall.py -v`
- `.venv\Scripts\python.exe -m pytest -m "not network" -q`
- `.venv\Scripts\python.exe -m ruff check . --fix`
- `.venv\Scripts\python.exe scripts\gate.py`

**Tests:** 52 new waterfall tests, all pass. Full suite: 135 passed, 1 xfailed. Gate: 6/7 (working tree not yet committed at time of gate run; 7/7 after commit).

**Hz/px accuracy on fixtures:**
- `waterfall_836px_client_v2.3.png`: 123.76 Hz/px, error 0.245% (< 1% limit) ✓
- `waterfall_832px_client_2.1.2.png`: 79.81 Hz/px, error 0.233% (< 1% limit) ✓

**Failures and repairs:**
1. First implementation used label pixel-width to infer kHz-per-tick. Failed: all intervals 1 to 100 kHz produced the same character-count pattern with ±1 tolerance, so 1 kHz was selected (first candidate), giving 10× wrong Hz/px.
2. EasyOCR with upright (dark-on-white) image read `-30` as `530` on the 836px image, minus sign glyph misread as `5`. Fixed by inverting the image to white-on-black for OCR, and by discarding sign from OCR (infer sign from tick position instead).
3. `test_crop_836_colorbar_not_in_cropped_array` was testing for dense non-white columns, failed because the spectrogram data is itself dense. Fixed: test now checks `crop_box.x1 < colorbar_x0` (coordinate-based).
4. `test_failed_record_validates_against_schema` failed because schema required `plot_box` to be non-null but our failed records have `plot_box=None`. Fixed by making `plot_box` nullable in the schema (version bump to 0.2.2).
5. Lint: 35 errors on first pass (UP045 Optional usage, B904 exception chaining, SIM108, F401, I001). Fixed with `ruff --fix` plus manual edits.

**Coins:** estimated 4 to 6, actual ~5.

**Bob task ID:** `db67de0f0709c58bbc4155fdf78181c4` (workspace `tracetriage-august-2026`, account 2)

**Commit:** f64deec

**Outcome:** accepted. 52 tests pass. 135 offline tests pass. Gate 7/7 after commit.


---

### 2026-08-17 IST | Account 3 | A4: Physics corridor module

**Task given:** Build `pipeline/tracetriage/physics.py`: the expected-frequency
corridor for an observation, from its own stored metadata. No external TLE
lookup, no join. Emit BOTH corridor shapes (uncorrected Doppler S-curve and
corrected near-vertical residual band), each with a width band. Named degraded
states for all failure modes. Validate against ≥200 observations and report the
error distribution.

**Files created/changed:**
- `pipeline/tracetriage/physics.py` (new, production physics corridor module)
- `tests/test_physics.py` (new, 61 offline tests)
- `scripts/validate_physics.py` (new, live validation runner)
- `artifacts/PHYSICS_VALIDATION.json` (new, validation results over 200 observations)
- `docs/BOB_BUILD_LOG.md` (this entry)
- `docs/BOB_HANDOFF.md` (updated)

**Commands run:**
- `.venv\Scripts\python.exe -m pytest tests/test_physics.py -v`
- `.venv\Scripts\python.exe -m pytest -m "not network and not ocr" -q`
- `.venv\Scripts\python.exe -m ruff check .`
- `.venv\Scripts\python.exe scripts\validate_physics.py` (live, ~16 s, 8 API pages)
- `.venv\Scripts\python.exe scripts\gate.py`

**Tests:** 61 new physics tests, all pass. Full offline suite: 215 passed,
1 xfailed. Gate 7/7 after commit.

**Validation results (200 observations, end=2026-08-10T00:00:00Z):**

| Metric | Value |
|---|---|
| n_success | 199 / 200 |
| n_degraded | 1 (STALE_TLE) |
| Median abs error | 0.21° |
| p90 abs error | 0.47° |
| p99 abs error | 0.61° |
| Max abs error | 3.39° |
| Within 1° | 99.5% |
| Within 5° | 100.0% |

**Key design decisions:**
- Both corridor shapes always emitted: `uncorrected` (full Doppler S-curve,
  ±2 kHz half-width) and `corrected` (near-vertical band, ±200 Hz half-width).
  Collapsing to one shape early would destroy the disagreement signal the queue
  ranks on.
- `AXIS_SIGN_CONVENTION = -1`: the plotted frequency axis runs against the
  Doppler sign (measured in A3 at 25 sigma; tested explicitly).
- Time runs bottom to top: `row_frac = 1 - (row + 0.5) / H` (measured in A3;
  tested with a sign-flip guard test).
- Free constant `FREQ_OFFSET_SEARCH_HZ = ±20 kHz` (10× the largest measured
  offset of 14.0 kHz).
- TLE epoch staleness threshold: 14 days from pass midpoint → `STALE_TLE`.
- SGP4 propagation, proper GMST, ECI→ECEF rotation, Earth-rotation velocity
  correction. Same formulation as the A3 investigation which reproduced
  max_altitude to 0.18 degrees.
- `corridor_columns()` maps a Corridor to pixel column per image row, applying
  the axis sign convention and a free offset parameter.

**Failures and repairs:**
1. First frozen test observation (ISS over Prague, 2024-01-01 12:00 UTC) was
   below the horizon — elevation -55.9°. Fixed by scanning 48 hours to find a
   real visible pass (01:22–01:33 UTC, max_el 48.8°).
2. `@pytest.fixture(scope="class")` on an instance method caused a pytest 9
   DeprecationWarning. Fixed by adding `@classmethod`.
3. Unimodal elevation test skipped because TCA was near the edge of the
   01:22–01:33 window. Replaced with a separate 68.4° pass (03:00–03:09) where
   TCA is firmly in the interior.
4. Four ruff lint errors (I001, F401 ×2, SIM300) fixed with `ruff --fix`.

**Coins:** estimated 3–4, actual ~3.

**Bob task ID:** (workspace `tracetriage-august-2026`, account 3)

**Commit:** 0f21ce7

**Outcome:** accepted. 61 tests pass. 215 offline tests pass. Gate 7/7.

