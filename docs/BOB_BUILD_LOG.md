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

## Enhancement loop record

Per the plan, improvements from other AI tools are recorded as pairs: Bob's
original build task, then Bob's integration task where Bob reviewed the change,
ran its tests, and accepted or rejected it. Both halves belong here, or the loop
cannot be shown to have happened.

| Date | Subsystem | Bob build task | Change proposed by | Bob integration task | Accepted? |
|---|---|---|---|---|---|
| | | | | | |
