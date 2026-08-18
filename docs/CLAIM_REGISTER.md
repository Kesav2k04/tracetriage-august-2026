# Claim register

Every number that appears in the README, in the video, on a chart, or in the
submission text maps to a row here, and every row points at a generated artifact.

A number with no row is a defect. `tests/test_claim_drift.py` enforces this, and
task D2 extends it to compare each quoted value against its artifact so that
updating the README without regenerating the receipt fails CI.

## Rules

1. **Numbers are generated, never typed.** If it was typed, it is wrong until proven.
2. Every row cites an artifact path and the commit that produced it.
3. A claim whose artifact changed but whose text did not is a **drift failure**, not a rounding difference.
4. Video numbers are registered too. The video is public and unversioned; drift there is not recoverable after submission.
5. Claims about what the system *cannot* do belong here as well, and are checked the same way.

## Register

| Claim | Value | Where it appears | Artifact | Commit | Verified |
|---|---|---|---|---|---|
| Corrected and uncorrected captures both occur | 4 corrected, 3 uncorrected of 24 | A3 finding, README, video | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Metadata cannot reveal correction status | `doppler-correction-per-sec` null and `rigctl-port` 4532 on 24/24 | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Strongest uncorrected match | 25.1 sigma curved against 2.8 sigma vertical, obs 14740031 | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Strongest corrected match | 54.2 sigma vertical against 7.3 sigma curved, obs 14746118 | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Observations with no measurable narrowband trace | 17 of 24 vetted with-signal | A3 finding | `artifacts/a3_overlays/summary.json` | `c7ca696` | 2026-08-16 |
| Pass geometry against reported max_altitude | median 0.21 deg, p99 0.61 deg, 99.5% within 1 deg, 199 of 200 | A4 finding, README, video | `artifacts/PHYSICS_VALIDATION.json` | `0f21ce7` | 2026-08-17 |
| Gate 6 point lift (chronological, shipped capped queue) | 1.582x over random at budget 50 | KILL_GATE.md, gate 6 section | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Gate 6 governing 95% CI (chronological) | [1.353, 1.755], union of episode and station, contains 1.5 | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Gate 6 bootstrap median (chronological) | 1.589 over 4000 of 4000 surviving resamples | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Gate 6 cold_station point lift | 2.253x, union [1.920, 3.896] (PASSED), 217 decisive | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| n_queue_conflicts at budget 50 (chronological) | 20 of 50, against 12.644 expected by random | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Every ordering's lift over random (chronological) | queue 1.582, image uncertainty 1.186, FIFO 1.107, physics-only 1.028 | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` | C2 | 2026-08-18 |
| Pass episodes hold 1.004 observations | 8 of 2716 episodes hold more than one; 87 episodes over 87 decisive chronological test rows, mean size 1.000 | KILL_GATE.md, C2_PREREGISTRATION.md | `artifacts/QUEUE_RECEIPT.json` episode_clustering | C2 | 2026-08-18 |
| Conflicts cluster by ground station | ICC 0.0887 / 0.0784 / 0.1347 / 0.0909, design effects 1.132 to 1.552 | KILL_GATE.md, C2_PREREGISTRATION.md | `artifacts/QUEUE_RECEIPT.json` station_clustering | C2 | 2026-08-18 |
| Cost of entity-concentration control | cold_station: 40 displaced, 36 conflicts to 27, lift 3.005 to 2.253, still PASSED | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` uncapped_reference | C2 | 2026-08-18 |
| Transmitter cap is inert on this corpus | 0 displaced on all four splits, under non-exclusive attribution | KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` concentration | C2 | 2026-08-18 |
| Baselines beaten under both groupings | chronological: physics-only. cold_station: FIFO. cold_transmitter: FIFO and physics-only. cold_combined: physics-only | KILL_GATE.md C4 section | `artifacts/QUEUE_RECEIPT.json` replay_conclusion | C4 | 2026-08-18 |
| Queue never beats image-uncertainty ordering under the both-groupings standard | leads by +5 to +11 conflicts on every split, not established on any | KILL_GATE.md C4 section | `artifacts/QUEUE_RECEIPT.json` replay_conclusion | C4 | 2026-08-18 |
| Queue never loses to any baseline | 0 of 12 comparisons reach baseline_better under either grouping | KILL_GATE.md C4 section | `artifacts/QUEUE_RECEIPT.json` replay_conclusion | C4 | 2026-08-18 |
| Conflicts found at budget 50 (chronological) | queue 20, image uncertainty 15, FIFO 14, physics-only 13 | KILL_GATE.md C4 section | `artifacts/QUEUE_RECEIPT.json` replay_episode | C4 | 2026-08-18 |
| Superseded: gate 6 CI published in C1 | [1.00, 1.20] was a resample artefact, not a measurement | KILL_GATE.md failure log | reproduced at [1.0000, 1.2200] from the old loop | C2 | 2026-08-18 |
| Fitted corridor offset, obs 14740031 | 113.0 px, 13,985 Hz, 32 ppm, read off the rendered overlay at 1:1 | console observation page | `apps/web/public/data/cards.json` corridor | C5 | 2026-08-18 |
| Console contrast, five page types | 1,475 text nodes measured, 0 below requirement | C6 build log entry | `apps/web/audit/a11y-probe.js` output | C6 | 2026-08-18 |
| Console keyboard reachability | 99 focusable elements, 0 unreachable, 0 without a focus ring | C6 build log entry | `apps/web/audit/a11y-probe.js` output | C6 | 2026-08-18 |
| Carbon text-03 fails contrast as a text colour | 3.60:1 on the page background, 3.01:1 on a tile, against a 4.5:1 requirement | C5 build log entry, globals.css | computed from the Gray 100 palette | C5 | 2026-08-18 |
| Console client bundle, queue route | 306 kB to 7.5 kB after the data layer stopped crossing the client boundary | C5 build log entry | `next build` route table | C5 | 2026-08-18 |
| Console page weight over the wire | 8 to 18 kB brotli per page, 3.9 kB CSS for the whole site | C5 build log entry | measured against the deployed site | C5 | 2026-08-18 |
| Degraded states exercised by shipped cards | 0 of 25, stated on the page rather than implied | console provenance page | `apps/web/public/data/cards.json` | C6 | 2026-08-18 |
| Superseded: console reported four splits with no partition counts | `{}` on all four, and two null arm sections, from `.get()` against wrong key names | C5 build log entry | fixed by `_require` in `scripts/build_console_data.py` | C5 | 2026-08-18 |
| Superseded: queue receipt named an hour bucket as its episode key | `start[:13]` in the prose while the code grouped by orbital revolution | C5 build log entry | key now pinned by `const` in `contracts/queue_receipt.schema.json` | C5 | 2026-08-18 |
| Superseded: console claimed no network request after load | the router prefetches same-origin RSC payloads on link visibility | console provenance page | measured request list on the built site | C6 | 2026-08-18 |

## Pre-registered limits

These are stated before results exist, so they cannot be quietly relaxed once
numbers arrive:

- No generalisation claim survives a failed cold-entity result.
- Queue lift is only claimed when the grouped 95% interval sits above random.
- "Target-consistent trace" is never restated as confirmed identity, decoded
  telemetry, mission success, or a corrected community label.
- Physics is claimed to help only if it lowers Brier score against a **calibrated**
  image-only baseline, not an uncalibrated one.
- Any metric measured on a single window is reported as such, never as a
  population constant.
| Elevation was measured from the geocentric vertical, not the geodetic normal | up to 0.1924 degrees of systematic error on every elevation the pipeline ever computed | C7 build log entry, `pipeline/tracetriage/physics.py` | `geodetic_normal`, plus the before/after comparison against SatNOGS `max_altitude` | C7 | 2026-08-18 |
| The A4 elevation validation could not have detected that error | median absolute difference against SatNOGS `max_altitude` 0.2082 before, 0.2249 after; the error is smaller than the reference's own scatter | C7 build log entry | `artifacts/PHYSICS_VALIDATION.json`, re-run both ways | C7 | 2026-08-18 |
| The geodetic fix moved no gate verdict | gate 5 margin +0.02080 to +0.02079, gate 6 lift 1.582 to 1.582, both intervals unchanged to three decimals | C7 build log entry, `docs/KILL_GATE.md` | both receipts re-run at seed 42 and the published bootstrap count | C7 | 2026-08-18 |
| The fix moved only the arms that consume elevation | four arms changed in the fifth decimal, six arms bit-identical including every corridor arm | C7 build log entry | `artifacts/FUSION_RECEIPT.json`, before and after | C7 | 2026-08-18 |
| A physics-only ranking equals the full queue on the cold-station split once the horizon is correct | 19 conflicts at budget before, 27 after, against the queue's unchanged 27 | C7 build log entry | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.cold_station | C7 | 2026-08-18 |
| Superseded: KILL_GATE.md published two different 95% intervals for gate 6 | summary said [1.00, 1.20] and 3.00x, the table and the receipt said [1.353, 1.755] and 2.253x | C7 build log entry | now generated by `scripts/sync_kill_gate.py` | C7 | 2026-08-18 |
| Superseded: gate 6's sample size was published as 88 observations | it is 87; gate 5's 88 had been copied across, and the queue deduplicates 410 rows to 407 | C7 build log entry | `n_test_decisive` and `n_groups` in the queue receipt | C7 | 2026-08-18 |
| Superseded: the pre-registration stated 88 observations in 87 episodes at mean size 1.000 | arithmetically impossible; the receipt says 87 in 87 at 1.000 | C7 build log entry | `gate6.per_split.chronological.episode_clustering` | C7 | 2026-08-18 |
| Exported pass geometry agrees with the scored propagation exactly | elevation and derived Doppler are asserted equal, not close, to `propagate_pass` output | `tests/test_physics.py::TestPassGeometry` | two equality tests over the full sample series | C7 | 2026-08-18 |
| The four instruments share one clock and the physics is consistent across them | at closest approach: 62.40 deg elevation, 758 km range, -197 Hz; +9,693 Hz at 2,054 km rising, -9,682 Hz at 2,032 km setting | console observation page | measured from the built site through the rendered DOM | C7 | 2026-08-18 |
| The replay costs no dropped frames | 662 consecutive frames, median interval 6.1 ms, maximum 6.3 ms, none over 32 ms, in an uncapped headless run | C7 build log entry | frame-interval probe on the built site | C7 | 2026-08-18 |
| The replay and the fourth instrument cost 1.73 kB of client JavaScript | observation route 5.22 kB to 6.95 kB, because the plots stayed server-rendered | C7 build log entry | `next build` route table | C7 | 2026-08-18 |
| The horizon circle is contained by its own plot frame on all four sides | asserted from `getBBox` on the rendered SVG, on the 62 degree and the 88 degree pass | C7 build log entry | browser bounding-box probe | C7 | 2026-08-18 |
| Amber was the wrong colour for an inconclusive verdict | Carbon assigns grey to unknown states; NASA Appendix F reserves yellow for caution | C7 build log entry, `apps/web/app/globals.css` | Carbon data-visualisation colour guidance and the Appendix F display standard | C7 | 2026-08-18 |
| NOT_ESTABLISHED matches SatNOGS' own review vocabulary | SatNOGS manual vetting has three states and one is Unknown; its automated rating adds a separate four-state axis | C7 build log entry | SatNOGS wiki, vetting documentation | C7 | 2026-08-18 |
| The gate tally on every page is computed from the receipts | 3 of 6 met; gates 5 and 6 read from their receipts, an unknown verdict raises | console side rail, `provenance.json` | `build_gate_summary` in `scripts/build_console_data.py` | C7 | 2026-08-18 |
| Every colour in the console is a token | 11 inlined hex values removed, 0 remaining in `app/` and `components/` | C7 build log entry | repository grep for hex literals in TSX | C7 | 2026-08-18 |
| The corridor explainer uses only values from the card it names | 61 px, 5,648 Hz, 13.0 ppm at 92.6 Hz per pixel, observation 14745984 | `media/explainer` video, `scripts/explainer_corridor.py` | the exported card for that observation | C7 | 2026-08-18 |
