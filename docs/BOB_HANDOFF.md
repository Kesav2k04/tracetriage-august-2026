# Bob handoff

**Read this and `.bob/rules.md` before every task.** Update it before every account rotation and at the end of every session.

---

## Current state

| | |
|---|---|
| **Handoff written** | 2026-08-16, 19:35 IST |
| **Units completed** | **A0** (`8ef8d1f`), **A1** (`be915b5`) |
| **Account in use** | account 1 |
| **Current wave** | Wave A, in progress |
| **Next unit** | **A2: waterfall artifact parser** |
| **Open failures** | none. 7/7 standing gates, 84 tests pass offline. |
| **Last commit** | `2e37c1d` (2026-08-16 IST) |

### A1 is closed. Read this before touching snapshot.py

A1's acceptance has been run live and **it passes**: 52 observations, 50 waterfalls, 3 pages in 56 s, and a second run resuming in 0.42 s with zero pages re-fetched.

Additional hardening was done on the operator's side in commit `931d2cd`. **Do not overwrite, revert or regenerate it.** Three defects were fixed:

1. The manifest and the resume index were written to and read from one global path regardless of `--out`. Stage 2 running in the background during Wave B would have loaded stage 1's observations as its own resume state and emitted a manifest describing files in a directory it does not name. The manifest now lives in `--out` and is mirrored to `artifacts/DATASET_MANIFEST.json` only on completion.
2. `--target-waterfalls` defaulted to 2300, so omitting it began a production-scale crawl. Now required unless `--verify` is given.
3. `--verify` ran after a full fetch rather than instead of one. It is now a mode that fetches nothing.

Two `TestResumeAfterInterrupt` cases were repointed at the snapshot directory, and `scripts/gate.py` now decodes subprocess output as UTF-8, because the Windows ANSI codepage crashed it whenever a test failed.

**Do not re-run a large snapshot casually.** Investigating those defects already put 578 observations and 870 MB of load on SatNOGS. Always pass `--target-waterfalls` explicitly.

**Start each unit in a fresh chat.** Paste the master prompt from `docs/BOB_TASK_PROMPTS.md`, then the unit prompt.

### Budget

40 Bobcoins is per trial account, not a project ceiling. The July 28 FAQ removed the single-account limit (`BOBCOIN_BUDGET.md` line 3, `MASTER_PLAN_TRACE_TRIAGE.md` line 154): when coins run out, create another trial with a different email you own and follow the published switch procedure. A rotation is a planned event, not a failure. What costs you is a bad handoff, so the stop-at-3-coins rule and the rotation checklist below are the parts that matter.

---

## What exists right now

Scaffold and verified reconnaissance only. **No production code exists.** `pipeline/tracetriage/` contains an empty `__init__.py` and nothing else.

Working and verified:

- Python **3.12.13** venv at `.venv`, with the full stack installed and every import confirmed: polars 1.43.2, pyarrow 25.0.1, numpy 2.5.2, scipy 1.18.0, Pillow 12.3.0, opencv 5.0.0, **sgp4 2.27**, **torch 2.13.0+cpu**, torchvision 0.28.0, scikit-learn 1.9.0, scikit-image 0.26.0, httpx, tenacity, matplotlib, onnxruntime 1.28.0, pytest 9.1.1.
- `pytest -m "not network"` passes. `conftest.py` blocks socket access in unmarked tests, so the offline-replay claim is enforced rather than asserted.
- CI at `.github/workflows/ci.yml`: clean clone, offline suite, claim drift, secret scan.
- Draft contracts in `contracts/`, all marked `DRAFT` and awaiting your ratification.
- Doc skeletons, MIT `LICENSE`, `DATA_LICENSE.md`, `.gitignore`, `.env.example`.

Exhaustive inventory with the boundary: **`docs/PREPARED_BY_CLAUDE.md`**.

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

In a **fresh Bob chat**: paste the master prompt from `docs/BOB_TASK_PROMPTS.md`, then unit **A1, the immutable snapshot builder**. Build stage 1 only (2,500 observations, ~2,300 waterfalls, ~4 GB, ~45 min). Stage 2 is kicked off in the background during Wave B.

Then A2 (waterfall parser), **A3 (blocking Doppler question)**, A4 (physics), A5 (provenance), A6 (baseline), A7 (end-to-end slice).

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
