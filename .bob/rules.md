# Bob operating rules for TraceTriage

Read this file before every task. It is short on purpose. The rotation handoff and the pre-written unit prompts are kept outside this repository: they are build logistics rather than evidence about the product.

---

## 0. If you are here to see the product, run this first

Both MCP servers are registered in `.bob/mcp.json` and the tools below are pre-approved,
so this needs no configuration edit and no approval clicks. The full prompt, with what each
step demonstrates and what to do when one fails, is `docs/BOB_DEMO.md`.

```
Use MCP tools only. Do not invent numbers. Quote fields verbatim.

1. queue_top limit=5. Report rank 1's obs_id and the reason code that fired.
2. check_claim observation_id=14740031 text="The downlink is 437.2 MHz."
   Expect REFUSED, UNGROUNDED_NUMBER.
3. live_list_observations limit=5. Pick an id with has_waterfall true.
4. live_triage_observation on it, n_nulls=99. Report mode.verdict,
   measurement.offset_ppm, nulls.p_value, provenance.waterfall_sha256 and
   provenance.measured_at_utc.
5. live_check_claim on that same id, text="The downlink is 437.2 MHz."
   Expect REFUSED, UNGROUNDED_NUMBER.
6. gate_status. Report n_met and the verdict of gates 3, 5 and 6.
```

Steps 2 and 5 are the same refusal on two different kinds of data: a frozen observation,
then a pass recorded while the session was running. The second is the claim that matters,
because it means the guardrail is a property of the system rather than of the corpus.

Step 6 has to come back with three of six met: gates 3, 5 and 6 `NOT_ESTABLISHED`, and
gate 4 `PASSED`. A session that reports six of six met has been told something false.

The live server needs the project virtual environment (`pip install -e .`, 166 MB on
disk). Without it `.bob/run-live.cmd` prints the install line rather than starting a
server that would answer `initialize` and then fail every call. The `[ocr]` extra is not
part of that: the axis reader defaults to the template matcher in `glyph_axis.py`, and
easyocr, which brings 4.5 GB of torch with it, is only the fallback when too few tick
labels are matched to fit an axis through.

---

## 1. Who you are on this project

You are the **primary development tool**. You build and validate every load-bearing subsystem on the judged path: ingestion, physics, model interface, calibration, abstention, ranking, the evidence console, the tests, and release acceptance.

Other AI tools may review, refactor and harden bounded areas **after** you build them. You then review the change, run its tests, and accept or reject it. If you did not build it and did not accept it, it does not ship.

What was scaffolded before your first task is listed exhaustively in `docs/PRE_BUILD_BASELINE.md`. Nothing on the judged path is in that list.

## 2. The one decision this product serves

> A reviewer has more public SatNOGS observations than they can inspect. Given a fixed review budget, which existing observations deserve human attention because image evidence, expected corrected Doppler behaviour, metadata, and the current network label disagree or remain uncertain?

If a feature does not improve that decision, it does not belong in this repository. Check a proposed feature against this sentence before writing it.

## 3. Hard boundaries. Never negotiate these.

- **Never write to SatNOGS.** No vote, no label change, no scheduling, no station control. No write credential exists in this project and none may be added.
- **Never claim** confirmed satellite identity, decoded telemetry, corrected public labels, mission safety, or official endorsement. The permitted phrasing is "model-label disagreement" unless adjudication supports more.
- **Treat `waterfall_status` as silver evidence, not truth.** Keep `unknown` observations unlabelled. A missing waterfall is artifact-unusable, not a negative example.
- **Never draw a raw S-shaped Doppler curve over a corrected waterfall.** That is fabricated evidence. Model residual consistency around the corrected centre corridor. See rule 5.
- **Keep everything on `D:\`.** Caches, temp files, model weights, browser binaries, build output. Never `C:\`.
- **No paid service on the required path.** Nothing a judge runs, and nothing CI runs,
  may bill anyone. The measurement path, the console, the checker and both MCP servers are
  local or read public APIs. One optional integration may touch a paid account when an
  operator supplies credentials: watsonx text generation. It is off by default, it falls
  back to the local model or to the deterministic template, and it is not on the path any
  check runs. If credentials are absent the receipt records the skip and no claim is made.
  This line named watsonx Orchestrate as a second such integration until 2026-08-22. No
  Orchestrate code, toolkit or receipt has ever existed here, so the claim is deleted
  rather than qualified.

## 4. The kill list

Do not build: contact scheduling, future-pass ranking, OR-Tools, station availability, mission planning, a 3D globe, generic RAG, voice, audio or IQ decoding, orbit fitting, automatic SatNOGS voting, continuous online training, user accounts, PostgreSQL, cloud inference, a vector database, or a generic chatbot.

Remove on ablation failure: Granite if exact filter parsing fails or the typed form is clearer. The CNN if HOG plus logistic regression ties it. The physics if it does not improve calibration or queue yield. **Any component whose ablation does not change a judge-facing result.**

Component count is not technical depth. Measured improvement is.

## 5. Physics facts already verified. Do not re-derive these.

Full detail with method and numbers is in `docs/SATNOGS_API_RECON.md`. The four that will cost you the most if forgotten:

1. **Observations live on `network.satnogs.org`.** `db.satnogs.org/api/observations/` returns 404.
2. **`end__lte=` is silently ignored** and returns HTTP 200 with unfiltered data. Use bare `end=`. **`waterfall_status=` is not a filter at all** and returns HTTP 400. Filter it client-side.
3. **The waterfall does not span `samp-rate-rx`.** Measured Hz/px was 123.46 on one client and 80.00 on another, against a 2.5 MHz sample rate. Assuming the sample rate squeezes the Doppler corridor from ~118 px down to ~5 px and makes the physics look worthless. Derive Hz/px from the rendered axis, per observation.
4. **The plot box is not the image box.** Measured x=66..686 on one client, x=74..677 on another, and one client renders a colorbar at x=724..755. Crop to the plot box before a model sees the image.

Already proven, so build on it rather than re-testing it: the observation's own stored TLE plus station coordinates reproduced pass geometry to **0.18 degrees** against the API's own `max_altitude`.

**Resolved at A3, and the answer is not the one the metadata suggested.** Both corrected and uncorrected captures exist in the public network, and **no metadata field tells them apart**: `doppler-correction-per-sec` was null and `rigctl-port` was `4532` on all 24 observations measured, in both groups. Correction status has to be inferred from the image. Four corrected observations across 4 stations, 4 satellites and 3 bands; three uncorrected across 3 satellites and 2 stations. Full method, margins and open questions: `docs/DOPPLER_CORRECTION_FINDING.md`.

Two calibration facts from A3 that cost a rebuild if forgotten. **Time runs bottom to top**: the top row of a waterfall is the END of the pass, read off the axis of observation 14740031 (the 200 s tick at y=258, the 50 s tick at y=1228). **The plotted frequency axis runs against the Doppler sign.** These two errors cancel, because a Doppler curve is near odd-symmetric about closest approach, so getting both wrong scores 25 sigma and looks right in an overlay. Never accept an orientation from a visual check; scan the sign and report which one won.

## 6. How to run a task

1. Inspect the repository. **Do not recreate finished files.**
2. Work on **one acceptance-defined unit at a time**. Every unit is written down with its acceptance checks before it starts, and `docs/BOB_BUILD_LOG.md` records what each one actually did.
3. Before editing, state: the exact files you will create, the commands you will run, the acceptance checks, and your estimated build credit risk.
4. Run the unit's tests before reporting completion.
5. **Do not claim completion when an artifact, metric, or external validation is missing.** Say what is missing.
6. Append to `docs/BOB_BUILD_LOG.md`: task, files, commit SHA, tests run, failures, repairs, credits spent.

## 7. Evidence discipline

Every public number, in the README, in the video, on any chart, must be generated from an immutable artifact under `artifacts/` and registered in `docs/CLAIM_REGISTER.md`. Hand-typed numbers are a defect. `tests/test_claim_drift.py` must fail when a README number stops matching its receipt.

Splits are grouped, never random: chronological, cold-station, cold-transmitter, and combined. Each transmitter and orbital revolution stays in exactly one split. Bootstrap by orbital episode or day, never by image row. Never use current station statistics, post-observation fields, artifact-derived labels, or future outcomes as features.

The frozen test set is touched once, at the end. Not for tuning, not for a sanity check.

## 8. When a gate fails

Stop and document the failure in `docs/KILL_GATE.md`. Do not hide it, do not compensate with UI features, and do not soften the threshold after seeing the result. A documented honest failure is a better submission than a concealed one, and the plan says so explicitly.

## 9. Before you run out of credits

Stop starting features at **3 credits remaining**. Then: run the full test and acceptance suite, write the exact next steps into the handoff kept outside this repository, update `docs/BOB_BUILD_LOG.md`, Task history is not exported into this repository: `bob_sessions/` was deleted in E0 because it held one `.gitkeep`, git does not publish an empty directory, and the README named it as evidence. `docs/BOB_BUILD_LOG.md` is the record. The credit budget and the account-rotation procedure are kept outside this repository: they are build logistics, not evidence about the product, and a reader of the tracked tree gains nothing from them.

## 10. Git

Commits are authored **`Kesav2k04 <kesavk659@gmail.com>`** and nothing else. Never add a `Co-Authored-By` trailer, a "Generated with" line, or a bot address. Never pass `--author`. Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`. The message describes the change and stops.
