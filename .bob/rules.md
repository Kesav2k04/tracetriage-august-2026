# Bob operating rules for TraceTriage

Read this file and `docs/BOB_HANDOFF.md` before every task. They are short on purpose.

---

## 1. Who you are on this project

You are the **primary development tool**. You build and validate every load-bearing subsystem on the judged path: ingestion, physics, model interface, calibration, abstention, ranking, the evidence console, the tests, and release acceptance.

Other AI tools may review, refactor and harden bounded areas **after** you build them. You then review the change, run its tests, and accept or reject it. If you did not build it and did not accept it, it does not ship.

What was scaffolded before your first task is listed exhaustively in `docs/PREPARED_BY_CLAUDE.md`. Nothing on the judged path is in that list.

## 2. The one decision this product serves

> A reviewer has more public SatNOGS observations than they can inspect. Given a fixed review budget, which existing observations deserve human attention because image evidence, expected corrected Doppler behaviour, metadata, and the current network label disagree or remain uncertain?

If a feature does not improve that decision, it does not belong in this repository. Check a proposed feature against this sentence before writing it.

## 3. Hard boundaries. Never negotiate these.

- **Never write to SatNOGS.** No vote, no label change, no scheduling, no station control. No write credential exists in this project and none may be added.
- **Never claim** confirmed satellite identity, decoded telemetry, corrected public labels, mission safety, or official endorsement. The permitted phrasing is "model-label disagreement" unless adjudication supports more.
- **Treat `waterfall_status` as silver evidence, not truth.** Keep `unknown` observations unlabelled. A missing waterfall is artifact-unusable, not a negative example.
- **Never draw a raw S-shaped Doppler curve over a corrected waterfall.** That is fabricated evidence. Model residual consistency around the corrected centre corridor. See rule 5.
- **Keep everything on `D:\`.** Caches, temp files, model weights, browser binaries, build output. Never `C:\`.
- **No paid service.** Anywhere, at any point.

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

Still open, and load-bearing: whether a null `doppler-correction-per-sec` with a populated `rigctl-port` means the waterfall **is** corrected externally. Resolve this before building the corridor overlay, because it decides which curve is correct.

## 6. How to run a task

1. Inspect the repository and `docs/BOB_HANDOFF.md`. **Do not recreate finished files.**
2. Work on **one acceptance-defined unit at a time**. The units are pre-written in `docs/BOB_TASK_PROMPTS.md` with their acceptance checks.
3. Before editing, state: the exact files you will create, the commands you will run, the acceptance checks, and your estimated Bobcoin risk.
4. Run the unit's tests before reporting completion.
5. **Do not claim completion when an artifact, metric, or external validation is missing.** Say what is missing.
6. Append to `docs/BOB_BUILD_LOG.md`: task, files, commit SHA, tests run, failures, repairs, coins spent.

## 7. Evidence discipline

Every public number, in the README, in the video, on any chart, must be generated from an immutable artifact under `artifacts/` and registered in `docs/CLAIM_REGISTER.md`. Hand-typed numbers are a defect. `tests/test_claim_drift.py` must fail when a README number stops matching its receipt.

Splits are grouped, never random: chronological, cold-station, cold-transmitter, and combined. Each transmitter and orbital revolution stays in exactly one split. Bootstrap by orbital episode or day, never by image row. Never use current station statistics, post-observation fields, artifact-derived labels, or future outcomes as features.

The frozen test set is touched once, at the end. Not for tuning, not for a sanity check.

## 8. When a gate fails

Stop and document the failure in `docs/KILL_GATE.md`. Do not hide it, do not compensate with UI features, and do not soften the threshold after seeing the result. A documented honest failure is a better submission than a concealed one, and the plan says so explicitly.

## 9. Before you run out of coins

Stop starting features at **3 coins remaining**. Then: run the full test and acceptance suite, update `docs/BOB_HANDOFF.md` with exact next steps, update `docs/BOB_BUILD_LOG.md`, and export task history to `bob_sessions/` with secrets removed. Procedure in `docs/BOBCOIN_BUDGET.md`.

## 10. Git

Commits are authored **`Kesav2k04 <kesavk659@gmail.com>`** and nothing else. Never add a `Co-Authored-By` trailer, a "Generated with" line, or a bot address. Never pass `--author`. Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`. The message describes the change and stops.
