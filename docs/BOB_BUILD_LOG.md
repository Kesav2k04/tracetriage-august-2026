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
**Commit:** SHA
**Outcome:** accepted / partial / abandoned, and why

---

## Entries

### 2026-08-17 IST | Account 1 | A0: Ratify the data contracts

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

**Commit:** 8ef8d1f

**Outcome:** accepted. All four schemas now have `"status": "ratified"` and `"schema_version": "0.2.0"`. Gate contracts check passes.

---

## A0b. Contract gaps closed after external review (2026-08-16)

**Proposed by:** Claude (Anthropic), acting under the review lane in `.bob/rules.md`
section 1. No Bob coins spent. **Pending Bob integration review.** Nothing here
ships until Bob reviews the diff, runs the suite, and accepts or rejects it.

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

## Enhancement loop record

Per the plan, improvements from other AI tools are recorded as pairs: Bob's
original build task, then Bob's integration task where Bob reviewed the change,
ran its tests, and accepted or rejected it. Both halves belong here, or the loop
cannot be shown to have happened.

| Date | Subsystem | Bob build task | Change proposed by | Bob integration task | Accepted? |
|---|---|---|---|---|---|
| 2026-08-16 | Data contracts | A0 (commit 8ef8d1f) | Claude, as A0b | A0b-INT | accepted with one correction (client_version added to dataset_manifest observations entry; date strings corrected 2026-08-17 to 2026-08-16) |
