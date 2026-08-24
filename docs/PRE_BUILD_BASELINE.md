# What was prepared before Bob's first task

**Written 2026-08-16, 15:10 IST, by the operator.**

This file exists so the "IBM Bob was the primary development tool" claim is auditable rather than asserted. It lists everything that existed before Bob's first task, and states the boundary that was held.

---

## The boundary

The competition requires IBM Bob to be the primary development tool. The plan (`MASTER_PLAN_TRACE_TRIAGE.md`) is stricter still: Bob must build and validate **every load-bearing subsystem** on the judged path, and a submission where Bob supplied only a scaffold has no strong evidence of primary use.

So the line drawn was:

**Prepared in advance** (removes blockers, spends no judged-path credit):
environment, dependency resolution, read-only reconnaissance of a public API, repository skeleton, licences, CI configuration, document templates, draft contracts, and pre-written task specifications.

**Left entirely to Bob** (the judged path):
ingestion, waterfall parsing, physics, the model ladder, calibration, abstention, out-of-distribution detection, queue ranking, annotation, the evidence console, the test suite, failure injection, and release acceptance.

**`pipeline/tracetriage/` contains one empty `__init__.py`. Not a single line of production logic was written.**

### What happened against this plan, which is not what this plan said

Added because a plan published before the work and never reconciled with it afterwards is
not evidence of anything, and this repository holds itself to reconciling exactly this kind
of statement. Gate 3's withdrawal from PASSED is recorded with its cause in
`docs/KILL_GATE.md`; this deviation was not recorded anywhere.

The list above assigns thirteen subsystems to Bob. Of those, the console, the calibration
and abstention blocks and the fusion ladder were not built inside a Bob account, and the
actor field of their own headings says so rather than absorbing them quietly:
`docs/BOB_BUILD_LOG.md:770` reads `### 17 Aug 2026 IST | operator | B2-B6 in one unit` and
covers calibration and the fusion ladder. `FOR_JUDGES.md` and `README.md` have always named
those four as operator work, so the accounting was published. What was missing is this
sentence, saying that the accounting differs from the plan written before it.

The cause is the one the next section names in advance: Bob's build budget is finite, and it
ran out before the list did. That is a resource outcome rather than a discovery, and it does
not move any measured number, because every measured claim resolves to an artifact and the
artifacts name the unit that produced them. It does mean this page over-promised, and the
two build logs are what correct it rather than the other way round.

### Why prepare anything at all

Bob's build budget is finite. Budget spent rediscovering that `db.satnogs.org/api/observations/` returns 404, or that `end__lte=` is silently ignored, or that the waterfall does not span `samp-rate-rx`, is budget not spent on the model, the calibration, or the queue. The reconnaissance below consumed none of it and removes roughly a day of dead ends.

That is the whole rationale. It buys Bob more room on the judged path, not less.

---

## 1. Environment

| Item | Detail |
|---|---|
| Python | 3.12.13, pinned via uv, at `.venv` |
| Why not 3.14 | The machine ships Python 3.14.2. Wheels exist for torch on cp314, but 3.12 has the widest coverage across the whole stack (opencv, scikit-image, onnxruntime) and removes a class of day-one failure. |
| Stack | polars 1.43.2, pyarrow 25.0.1, numpy 2.5.2, scipy 1.18.0, Pillow 12.3.0, opencv 5.0.0, sgp4 2.27, torch 2.13.0+cpu, torchvision 0.28.0, scikit-learn 1.9.0, scikit-image 0.26.0, httpx 0.28.1, tenacity, matplotlib 3.11.1, onnx, onnxruntime 1.28.0, pytest 9.1.1, ruff, mypy, hypothesis |
| Verified | every module imports; `pytest -m "not network"` passes |
| Caches | `D:/dev-cache/uv-cache`, `D:/dev-cache/uv-python`. Nothing on `C:\`. |

## 2. Reconnaissance (read-only, no account, no writes)

`docs/SATNOGS_API_RECON.md`, 11 sections, every number measured live on 2026-08-16 between 14:47 and 14:52 IST.

Probe scripts preserved under `scripts/recon/`, explicitly marked as recon-grade and not for import into `pipeline/`:

| Script | Answers |
|---|---|
| `probe_filters.py` | which query filters work, which return 400, which are silently ignored |
| `survey_coverage.py` | label and metadata coverage over 600 observations |
| `fetch_waterfalls.py` | artifact format, size, dimensions |
| `measure_axis.py` | plot box and Hz-per-pixel from the rendered axis |
| `physics_feasibility.py` | whether a stored TLE reproduces the pass geometry |

Findings that changed the plan's assumptions:

- `center_frequency` is null in practice; the plan assumed it usable
- `waterfall_status` is not a server-side filter
- the waterfall spans a decimated band, not `samp-rate-rx`, by a factor near 32
- geometry from the observation's own TLE agrees with the API to **0.18 degrees**

## 3. Repository skeleton

Directories per the plan: `pipeline/`, `apps/web/`, `contracts/`, `artifacts/`, `tests/`, `docs/`, `bob_sessions/`, `data/`, `scripts/`, `.bob/`, `.github/workflows/`.

Files: `pyproject.toml`, `.gitignore`, `.env.example` (contains **no credential**, and states that none may ever be added), `LICENSE` (MIT), `DATA_LICENSE.md` (CC BY-SA 4.0 handling), `README.md`.

The README's entire results table reads `[UNMEASURED]`, and `tests/test_claim_drift.py` fails if a real number appears there without a matching row in `docs/CLAIM_REGISTER.md`.

## 4. Draft contracts (Bob ratifies in task A0)

`contracts/source_observation.schema.json`, `waterfall_geometry.schema.json`, `triage_receipt.schema.json`, `split_manifest.schema.json`.

All four carry `"status": "DRAFT - not authoritative until Bob ratifies it"` and a `-draft` version suffix. They encode the verified field names and the traps found during recon. **They are a starting point to be corrected, not a specification to be obeyed.** Task A0 is Bob checking them against reality and changing what is wrong.

## 5. Test and CI scaffold

`tests/conftest.py` blocks socket access in any test not marked `network`, so an unmarked test that quietly depends on the live API fails loudly instead of making the offline-replay claim false.

`tests/test_claim_drift.py` enforces the README-to-receipt rule now, with the full implementation left as task D2.

`.github/workflows/ci.yml`: clean clone, pinned env, ruff, mypy, offline suite, claim drift, secret scan, plus a non-blocking live-API job so an upstream change surfaces in CI rather than inside a training run.

**No test of any TraceTriage behaviour was written.** Every behavioural test belongs to Bob's units.

## 6. Documents

`docs/SATNOGS_API_RECON.md` (findings), `docs/KILL_GATE.md` (status board, 3 of 6 gates pre-measured), `docs/BOB_BUILD_LOG.md` (empty), `docs/ACTOR_AND_PERMISSION_CONTRACT.md`, `docs/CLAIM_REGISTER.md` (empty).

---

## What was deliberately not done

- No ingestion, no snapshot builder, no manifest generation
- No waterfall parsing beyond a recon-grade measurement script
- No physics module (the feasibility probe is throwaway and says so in its own docstring)
- No model of any kind, no calibration, no abstention, no OOD
- No queue, no ranking, no annotation
- No web application: `apps/web/` is an empty directory
- No behavioural tests
- **No kill-gate decision.** Gates 3 to 6 are recorded as open. Unmeasured is not the same as passing, and only Bob's artifacts can close them.

---

## How the build proceeds from here

Bob builds every lettered unit: A0 through A7, then waves B, C and D. Each unit is scoped to a single acceptance-defined deliverable, its result is recorded in `docs/BOB_BUILD_LOG.md` with the commit SHA and the tests that ran, and a handoff kept outside this repository carries exact state between sessions.

Where hardening happens outside a Bob task, it is logged under "Operator-side hardening" in the build log against the unit it followed, so the history stays complete and a later unit does not overwrite it.
