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
| Brier score, chronological holdout | 0.1292 shipped arm, 0.1495 image-only, 0.2085 prior-only floor | README, evaluation page | `artifacts/FUSION_RECEIPT.json` splits.chronological.arms | C7 | 2026-08-18 |
| AUC, chronological holdout | 0.875 shipped arm, 0.842 image-only | README, evaluation page | `artifacts/FUSION_RECEIPT.json` splits.chronological.arms | C7 | 2026-08-18 |
| Calibration slope and intercept | slope 1.483, intercept -0.246, ECE 0.0713 | README, evaluation page | `artifacts/FUSION_RECEIPT.json` splits.chronological.arms.image_corridor | C7 | 2026-08-18 |
| Selective risk near 80% coverage | risk 0.0857 at 79.5% coverage | README, evaluation page | `artifacts/FUSION_RECEIPT.json` splits.chronological.selective.curve | C7 | 2026-08-18 |
| Queue lift over random, chronological | 1.582x, 95% CI [1.353, 1.755], NOT_ESTABLISHED | README, queue page, KILL_GATE.md | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.chronological | C7 | 2026-08-18 |
| Queue lift over image-only uncertainty | 1.582x against 1.186x at the same budget | README, replay page | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.chronological | C7 | 2026-08-18 |
| Queue lift over first-in-first-out | 1.582x against 1.107x | README, replay page | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.chronological | C7 | 2026-08-18 |
| Cold-station holdout | PASSED, 2.253x, 95% CI [1.920, 3.896] | README, queue page | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.cold_station | C7 | 2026-08-18 |
| Cold-transmitter holdout | 1.656x, 95% CI [1.340, 1.913], NOT_ESTABLISHED | README, queue page | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.cold_transmitter | C7 | 2026-08-18 |
| Cold station and transmitter together | 1.292x, 95% CI [1.073, 1.520], NOT_ESTABLISHED | README, queue page | `artifacts/QUEUE_RECEIPT.json` gate6.per_split.cold_combined | C7 | 2026-08-18 |
| Physics beats image-only on Brier | NOT ESTABLISHED. Margin +0.02079, 95% CI [-0.01268, 0.05029], spans zero | README, evaluation page, KILL_GATE.md | `artifacts/FUSION_RECEIPT.json` gate5 | C7 | 2026-08-18 |
| Console page weight over the wire, C7 | 8.4 kB replay to 26.9 kB observation, compressed, measured on the deployed site | C7 build log entry | curl with Accept-Encoding against https://tracetriage.vercel.app | C7 | 2026-08-18 |
| Superseded: console page weight 8 to 18 kB | the observation page grew to 26.9 kB when the pass geometry was exported to it | C7 build log entry | superseded by the C7 measurement above | C7 | 2026-08-18 |
| Offline test suite size and result | 745 collected, 744 passed, 1 declared expected failure | C7 build log entry, Wave D prompt | `pytest -q --tb=no -p no:warnings` progress census, 744 `.` and 1 `x` | C7 | 2026-08-18 |
| Retracted: "745 offline tests pass" | the passing count is 744; the `xfail` in tests/test_claim_drift.py has been collected since the scaffold commit, so 745, 732 and 721 were all collected counts | earlier build log entries | superseded by the row above | C7 | 2026-08-18 |
| Explainer video plays from the deployed origin | 1920x1080, 24.0 s, 1,646,670 B, poster 24,761 B, both HTTP 200 | home page | https://tracetriage.vercel.app/media/corridor-explainer.mp4 and its poster, checked in-browser and with curl | C7 | 2026-08-18 |
| Third-party bytes for the licensed typefaces, cold | 43,598 B: 4,166 stylesheet + 23,224 display face + 16,208 label face | provenance page, colophon, C7d build log entry | curl against use.typekit.net, each URL fetched cold outside the browser | C7d | 2026-08-18 |
| Licensed font files cache for one year | Cache-Control public, max-age=31536000 on both woff2 faces; the kit stylesheet is private, max-age=600 | C7d build log entry, provenance page | response headers from use.typekit.net | C7d | 2026-08-18 |
| The licence counter sets no cookie and returns five bytes | HTTP 200, Content-Length 5, no Set-Cookie header | provenance page | response headers from p.typekit.net/p.css | C7d | 2026-08-18 |
| Retracted: the console requests nothing from another origin | false from C7d. Two licensed faces and one licence counter are requested; the narrowed claim is that no DATA is requested from another origin | provenance page, colophon, video caption | superseded by the two rows above | C7d | 2026-08-18 |
| Instrument label sizes now render as one set | 11.3, 11.7 and 12.9 px against 14 px body prose, from viewBox scales of 1.03, 1.30 and 1.18 | C7d build log entry | getBoundingClientRect against viewBox.baseVal on the built page at 1440px | C7d | 2026-08-18 |
| The wide instrument was rendering its labels at 24.7 px | 420 user units displayed at 1151 px, a scale of 2.74 applied to a 9 px declared size | C7d build log entry | same measurement, before the rescale | C7d | 2026-08-18 |
| Hero figure treatments compared before choosing | ink widths 259, 235, 222 and 173 px at 112 px for Plex Mono -0.022em, Plex Mono -0.075em, Plex Sans 600, Neue Haas Display 500 | C7d build log entry, globals.css comment | Range.getBoundingClientRect on four rendered variants | C7d | 2026-08-18 |
| The first third-party byte count was contaminated | 138,112 B across 6 files, every entry transferSize 0 and deliveryType cache, warmed by this session's own canvas probes | C7d build log entry | performance.getEntriesByType('resource') deliveryType field | C7d | 2026-08-18 |
| Hero top padding above the fold at 375px | 88 px before the change, 64 px after, headline still fully above the fold | C7d build log entry | getBoundingClientRect at a 360 px client width | C7d | 2026-08-18 |
| Display face family name | neue-haas-grotesk-display, not "Neue Haas Grotesk Display Pro", which is the desktop retail name and never resolved | globals.css comment, C7d build log entry | Adobe Fonts kit iie4ixd font-family declarations | C7d | 2026-08-18 |
| Elapsed-overlay cost per frame | 0.009 ms for both writes including a forced style flush | C7e build log entry, PassReplay.tsx comment | 400-iteration timing loop in the browser on the built page | C7e | 2026-08-18 |
| Sub-pixel guard drops three quarters of the rasters | 180 of 721 frames write over a 12 s pass at 60 fps, 75 per cent skipped | C7e build log entry, PassReplay.tsx comment | enumeration of the guard condition over the frame sequence | C7e | 2026-08-18 |
| Adding the overlays did not change the bundle | route JavaScript 7.12 kB and shared 102 kB, both unchanged | C7e build log entry | next build route table, before and after | C7e | 2026-08-18 |
| Lottie rejected, with the cost that decided it | about 60 to 70 kB gzipped runtime against a 1.73 kB clock; rejected on provenance, not weight | C7e build log entry, globals.css comment | published lottie-web bundle size against the measured client bundle | C7e | 2026-08-18 |
| The duplicate path costs 100 bytes, not 6 kB | 34,138 B against 34,038 B, both gzip; the 6 kB figure compared gzip against brotli | C7e build log entry, SkyPlot.tsx comment | gzip -c on the built observation page for both variants | C7e | 2026-08-18 |
| Retracted: removing the duplicate path saves about 6 kB | it saves 100 bytes; the original figure compared two different compressors | SkyPlot.tsx comment, C7e build log entry | superseded by the row above | C7e | 2026-08-18 |
| The overlay paints, proven by hit test | at 60 per cent progress a point 10 per cent along hits sky-trail and a point 92 per cent along hits path.plot-track | C7e build log entry | document.elementFromPoint on both probe points, screen coordinates from getScreenCTM | C7e | 2026-08-18 |
| The overlay reveals from the rise, not the set | at value 0 the cursor is at translate(169.40 44.46) and the path start is (169.4, 44.5) | C7e build log entry | getPointAtLength(0) against the cursor transform at value 0 | C7e | 2026-08-18 |
| Playback frame intervals during the overlay animation | median 6.1 ms, max 6.5 ms, 0 of 660 frames over 20 ms, on an unthrottled headless browser at about 164 Hz | C7e build log entry | requestAnimationFrame interval sampling over a 4 s playback window | C7e | 2026-08-18 |
