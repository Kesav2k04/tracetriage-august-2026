# The TraceTriage presentation film

A 103 second silent film for the IBM AI Builders August 2026 entry, rendered with
Remotion at 1920 by 1080 and 30 frames a second. It is built to be read with the sound
off and presented live.

Every number on screen is read at build time from a receipt in this repository. Nothing
is typed from having read a document, and a test fails if that stops being true. This
report says what the film claims, where each figure came from, how to preview it, how to
re-render it, and what the verification actually printed.

## What it says, beat by beat

The film is seven cards, cut rather than crossfaded, 3090 frames in total.

| # | Card | Frames | Seconds | What it says |
|---|---|---|---|---|
| 1 | Title | 0 to 149 | 0.0 to 5.0 | TraceTriage, a ranked review queue for satellite radio captures that volunteers recorded and nobody read. The snapshot id and the data licence sit in the footer. |
| 2 | The problem, in counts | 150 to 569 | 5.0 to 19.0 | 2,727 observations in the snapshot, 2,500 with a waterfall image, 739 with a decisive human verdict, 1,988 with none. A grid of 2,727 cells in the snapshot's own fetch order, lit where a verdict exists. |
| 3 | The product | 570 to 1169 | 19.0 to 39.0 | 407 observations ranked by review value, with the first 50 as the budget. The four the per-station cap displaced are drawn in the caution token at the budget line. Then what the top 50 turned out to be carrying: 17 stale catalogue frequencies, 3 model and label disagreements, 0 dead captures, with the third criterion marked as one that never fires on this corpus. |
| 4 | The physics | 1170 to 1889 | 39.0 to 63.0 | Observation 14740031's real waterfall, from the console's own public directory. Three overlays arrive in order: the commanded receive frequency as a vertical dashed line, the pass geometry at zero offset spanning 17,290 Hz, then the same curve sliding 113 pixels onto its best match. The measurement is the gap: +13,985 Hz, +32.05 ppm. Then gate 3, which asked whether that corridor lands on a visible trace: 3 of 3 discriminated, a 95% lower bound of 0.37 against a threshold of 0.70, NOT ESTABLISHED. |
| 5 | The result | 1890 to 2459 | 63.0 to 82.0 | Gate 6's wording, quoted from its receipt. Conflicts found in the 50 examined out of 87 decisively labelled: 12.6 expected by random, 14 by first in first out, 20 by the ranked queue, against 22 in the whole population. Then the lift on one axis: a threshold at 1.50, first in first out at 1.11, a point estimate of 1.58, and a 95% interval from 1.35 to 1.74 drawn straddling the threshold. NOT ESTABLISHED, direction spans_threshold. |
| 6 | The gates | 2460 to 2909 | 82.0 to 97.0 | All six kill gates with the file each was decided in and the receipt's own verdict word. Then the tally: 2 of 6 met, the two being the feasibility checks answered before any pipeline code existed, and of the 4 that ask whether the idea works, 0 passed. |
| 7 | Attribution | 2910 to 3089 | 97.0 to 103.0 | The six obligations `DATA_LICENSE.md` accepts for the waterfall the film displayed, read from that file's own row in `artifacts/ATTRIBUTION_AUDIT.json`: record URL, artifact URL, retrieval timestamp, sha256, licence, licence URL and modification notice, plus the notice this film adds. ShareAlike is stated: the film contains a SatNOGS waterfall, so the film carries CC BY-SA 4.0 rather than the repository's code licence. |

Beat 5 is not softened. The film says the point estimate clears the threshold and the
interval does not, and beat 6 closes on 2 of 6 rather than on a win.

### Two places the film disagrees with a natural reading of the brief

The brief described beat 4 as the lift over a chronological queue. Gate 6's threshold is
lift over **random** ordering at the same budget, measured **on** the chronological
split. Those are different quantities, so the film shows both: the queue at 1.58 against
random with its interval, and first in first out at 1.11 against the same baseline. The
comparison against first in first out is reported by the receipt as `not_established`
after correction, so the film shows the two counts and the two lifts and does not claim
the difference.

The brief also described beat 3 as showing that the trace is a curve rather than a
vertical line. The receipt supports the geometry (the corridor spans 17,290 Hz across
this pass, and the fitted curve visibly tracks the trace) but the sigma scores that would
quantify curve against vertical are **not** comparable across the two implementations
that produce them: `pipeline/tracetriage/corridor_fit.py` records that its `sigma_curved`
differs from the A3 receipt's by factors from 0.87 to 12.4 on the seven decisive
observations, because the two normalise differently. So no sigma appears in the film. The
vertical line is shown and labelled for what it is, a hypothesis about how the capture was
recorded, and nothing claims a measured margin between the two shapes.

## Where every figure comes from

The table below was generated from `src/data.ts`, not typed. Each row is a claim object
holding a file, a key path, the value the path resolved to, and the string the film
prints. `src/claim.ts` resolves the path at build time, so a renamed key fails the render
instead of leaving a stale figure inside an mp4.

Twenty-two of these are read and not displayed. They are there because the test uses them
for cross-checks: `lift.statement` and `gate3Result.question` hold the receipts' own
sentences, `physics.dopplerVerdict` proves the chosen observation is one gate 3 could be
asked of, and `reviewQueue.criteria.N.firedInCorpus` is the corpus-wide count against
which the in-budget count is read.

| Shown as | Value | File | Key |
|---|---|---|---|
| corpus.snapshotId | `snap-20260817-stage1` | artifacts/DATASET_MANIFEST.json | `snapshot_id` |
| corpus.observations | `2,727` | artifacts/DATASET_MANIFEST.json | `counts.observations_stored` |
| corpus.waterfalls | `2,500` | artifacts/DATASET_MANIFEST.json | `counts.waterfalls_stored` |
| corpus.decisive | `739` | artifacts/DATASET_MANIFEST.json | `counts.waterfall_status_decisive` |
| corpus.noVerdict | `1,988` | artifacts/DATASET_MANIFEST.json | `counts.observations_stored - counts.waterfall_status_decisive` |
| corpus.queriedBackFrom | `2026-08-10T00:00:00Z` | artifacts/DATASET_MANIFEST.json | `query.end` |
| corpus.pagesFetched | `110` | artifacts/DATASET_MANIFEST.json | `counts.pages_fetched` |
| corpus.licence | `CC BY-SA 4.0` | artifacts/DATASET_MANIFEST.json | `license` |
| reviewQueue.length | `407` | artifacts/QUEUE_RECEIPT.json | `deduplication.n_observations_after` |
| reviewQueue.budget | `50` | artifacts/QUEUE_RECEIPT.json | `review_budget.n_observations` |
| reviewQueue.budgetRationale | `Fixed at 50 before any results were seen.` | artifacts/QUEUE_RECEIPT.json | `review_budget.rationale` |
| reviewQueue.episodesDeduplicated | `3` | artifacts/QUEUE_RECEIPT.json | `per_split_summaries[0].n_episodes_deduplicated` |
| reviewQueue.decisiveInTestSet | `87` | artifacts/QUEUE_RECEIPT.json | `per_split_summaries[0].n_test_decisive` |
| reviewQueue.testSetTotal | `410` | artifacts/QUEUE_RECEIPT.json | `per_split_summaries[0].n_test_total` |
| reviewQueue.stationCapDisplaced | `4` | artifacts/QUEUE_RECEIPT.json | `per_split_summaries[0].concentration.caps.ground_station.n_displaced` |
| reviewQueue.stationCapEntries | `5` | artifacts/QUEUE_RECEIPT.json | `per_split_summaries[0].concentration.caps.ground_station.entries_at_budget` |
| reviewQueue.criteria.0.firedInCorpus | `3` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.criteria_fired[0].n_flagged` |
| reviewQueue.criteria.0.firedInBudget | `3` | artifacts/QUEUE_RECEIPT.json | `queue[] where within_budget and reasons includes MODEL_LABEL_DISAGREE` |
| reviewQueue.criteria.0.inert | `false` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.criteria_fired[0].inert_on_this_corpus` |
| reviewQueue.criteria.1.firedInCorpus | `19` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.criteria_fired[1].n_flagged` |
| reviewQueue.criteria.1.firedInBudget | `17` | artifacts/QUEUE_RECEIPT.json | `queue[] where within_budget and reasons includes STALE_CATALOGUE_FREQ` |
| reviewQueue.criteria.1.inert | `false` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.criteria_fired[1].inert_on_this_corpus` |
| reviewQueue.criteria.2.firedInCorpus | `0` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.criteria_fired[2].n_flagged` |
| reviewQueue.criteria.2.firedInBudget | `0` | artifacts/QUEUE_RECEIPT.json | `queue[] where within_budget and reasons includes DEAD_CAPTURE` |
| reviewQueue.criteria.2.inert | `true` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.criteria_fired[2].inert_on_this_corpus` |
| reviewQueue.criteriaFixedBeforeMeasuring | `true` | artifacts/QUEUE_RECEIPT.json | `conflict_definition.fixed_before_measuring` |
| physics.obsId | `14740031` | apps/web/public/data/cards.json | `cards[12].obs_id` |
| physics.station | `M0EYT / 2E0NOG` | apps/web/public/data/cards.json | `cards[12].station_name` |
| physics.norad | `63214` | apps/web/public/data/cards.json | `cards[12].norad_cat_id` |
| physics.mode | `BPSK` | apps/web/public/data/cards.json | `cards[12].transmitter_mode` |
| physics.status | `with-signal` | apps/web/public/data/cards.json | `cards[12].waterfall_status` |
| physics.start | `2026-08-09T23:50:08Z` | apps/web/public/data/cards.json | `cards[12].start` |
| physics.rxMhz | `436.400` | apps/web/public/data/cards.json | `cards[12].rx_freq_hz` |
| physics.hzPerPx | `123.8` | apps/web/public/data/cards.json | `cards[12].hz_per_px` |
| physics.secondsPerPx | `0.156` | apps/web/public/data/cards.json | `cards[12].seconds_per_px` |
| physics.maxElevation | `41.2` | apps/web/public/data/cards.json | `cards[12].corridor.max_elevation_deg` |
| physics.offsetHz | `+13,985` | apps/web/public/data/cards.json | `cards[12].corridor.fitted_offset_hz` |
| physics.offsetPpm | `+32.05` | apps/web/public/data/cards.json | `cards[12].corridor.fitted_offset_ppm` |
| physics.corridorSpanHz | `17,290` | artifacts/GATE3_RECEIPT.json | `observations[4].corridor_span_hz` |
| physics.dopplerVerdict | `UNCORRECTED` | artifacts/GATE3_RECEIPT.json | `observations[4].verdict` |
| physics.shiftPx | `113` | apps/web/public/data/cards.json | `cards[12].corridor.fitted_px[0] minus cards[12].corridor.predicted_px[0]` |
| gate3Result.number | `3` | artifacts/GATE3_RECEIPT.json | `gate` |
| gate3Result.question | `Does the expected corridor intersect a visible target-like trace?` | artifacts/GATE3_RECEIPT.json | `question` |
| gate3Result.scored | `3` | artifacts/GATE3_RECEIPT.json | `observations_scored` |
| gate3Result.discriminating | `3` | artifacts/GATE3_RECEIPT.json | `discriminating_rate times observations_scored` |
| gate3Result.lowerBound | `0.37` | artifacts/GATE3_RECEIPT.json | `rate_lower_bound_95` |
| gate3Result.threshold | `0.70` | artifacts/GATE3_RECEIPT.json | `threshold` |
| gate3Result.notTestable | `4` | artifacts/GATE3_RECEIPT.json | `observations_not_testable` |
| gate3Result.verdict | `NOT_ESTABLISHED` | artifacts/GATE3_RECEIPT.json | `verdict` |
| lift.number | `6` | artifacts/QUEUE_RECEIPT.json | `gate6.gate` |
| lift.wording | `Require the top review queue to find at least 1.5 times as many manually actionable conflicts as random ordering at the same budget.` | artifacts/QUEUE_RECEIPT.json | `gate6.wording` |
| lift.decidedOn | `chronological` | artifacts/QUEUE_RECEIPT.json | `gate6.decided_on` |
| lift.examined | `50` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.n_queue_examined` |
| lift.population | `87` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.replay_episode.n_population` |
| lift.queueConflicts | `20` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.n_queue_conflicts` |
| lift.randomConflicts | `12.6` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.n_random_conflicts` |
| lift.fifoConflicts | `14` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.replay_episode.orderings.fifo.n_conflicts_at_budget` |
| lift.totalConflicts | `22` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.replay_episode.n_total_conflicts` |
| lift.point | `1.58` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.lift_point` |
| lift.ciLow | `1.35` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.lift_ci95[0]` |
| lift.ciHigh | `1.74` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.lift_ci95[1]` |
| lift.fifoLift | `1.11` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.replay_episode.orderings.fifo.lift_over_random` |
| lift.threshold | `1.50` | artifacts/QUEUE_RECEIPT.json | `gate6.wording (the 1.5 the sentence names)` |
| lift.bootstraps | `4,000` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.n_boot` |
| lift.groups | `87` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.n_groups` |
| lift.direction | `spans_threshold` | artifacts/QUEUE_RECEIPT.json | `gate6.per_split.chronological.direction` |
| lift.verdict | `NOT_ESTABLISHED` | artifacts/QUEUE_RECEIPT.json | `gate6.verdict` |
| lift.statement | `The queue's point lift is 1.58 on the chronological split (20 conflicts in 50 examined, expected 12.6 by random). The 95% interval spans the 1.5 threshold (1.35 to 1.74). A point estimate above 1.5 whose interval does not sit above 1.5 is not a pass, for the same reason gate 5 was recorded as NOT_ESTABLISHED: the evidence does not exclude noise.` | artifacts/QUEUE_RECEIPT.json | `gate6.statement` |
| gates.rows.0.number | `1` | apps/web/public/data/provenance.json | `gate_summary.gates[0].gate` |
| gates.rows.0.title | `Dataset volume and entity spread` | apps/web/public/data/provenance.json | `gate_summary.gates[0].title` |
| gates.rows.0.verdict | `PRE_PASSED` | apps/web/public/data/provenance.json | `gate_summary.gates[0].verdict` |
| gates.rows.0.decidedIn | `docs/KILL_GATE.md` | apps/web/public/data/provenance.json | `gate_summary.gates[0].decided_in` |
| gates.rows.1.number | `2` | apps/web/public/data/provenance.json | `gate_summary.gates[1].gate` |
| gates.rows.1.title | `Metadata coverage for the corridor` | apps/web/public/data/provenance.json | `gate_summary.gates[1].title` |
| gates.rows.1.verdict | `PRE_PASSED` | apps/web/public/data/provenance.json | `gate_summary.gates[1].verdict` |
| gates.rows.1.decidedIn | `docs/KILL_GATE.md` | apps/web/public/data/provenance.json | `gate_summary.gates[1].decided_in` |
| gates.rows.2.number | `3` | apps/web/public/data/provenance.json | `gate_summary.gates[2].gate` |
| gates.rows.2.title | `Corridor intersects a visible trace` | apps/web/public/data/provenance.json | `gate_summary.gates[2].title` |
| gates.rows.2.verdict | `NOT_ESTABLISHED` | apps/web/public/data/provenance.json | `gate_summary.gates[2].verdict` |
| gates.rows.2.decidedIn | `artifacts/GATE3_RECEIPT.json` | apps/web/public/data/provenance.json | `gate_summary.gates[2].decided_in` |
| gates.rows.3.number | `4` | apps/web/public/data/provenance.json | `gate_summary.gates[3].gate` |
| gates.rows.3.title | `Blinded human decidability` | apps/web/public/data/provenance.json | `gate_summary.gates[3].title` |
| gates.rows.3.verdict | `OPEN` | apps/web/public/data/provenance.json | `gate_summary.gates[3].verdict` |
| gates.rows.3.decidedIn | `artifacts/GATE4_RECEIPT.json` | apps/web/public/data/provenance.json | `gate_summary.gates[3].decided_in` |
| gates.rows.4.number | `5` | apps/web/public/data/provenance.json | `gate_summary.gates[4].gate` |
| gates.rows.4.title | `Physics beats image-only on Brier` | apps/web/public/data/provenance.json | `gate_summary.gates[4].title` |
| gates.rows.4.verdict | `NOT_ESTABLISHED` | apps/web/public/data/provenance.json | `gate_summary.gates[4].verdict` |
| gates.rows.4.decidedIn | `artifacts/FUSION_RECEIPT.json` | apps/web/public/data/provenance.json | `gate_summary.gates[4].decided_in` |
| gates.rows.5.number | `6` | apps/web/public/data/provenance.json | `gate_summary.gates[5].gate` |
| gates.rows.5.title | `Queue lift over random` | apps/web/public/data/provenance.json | `gate_summary.gates[5].title` |
| gates.rows.5.verdict | `NOT_ESTABLISHED` | apps/web/public/data/provenance.json | `gate_summary.gates[5].verdict` |
| gates.rows.5.decidedIn | `artifacts/QUEUE_RECEIPT.json` | apps/web/public/data/provenance.json | `gate_summary.gates[5].decided_in` |
| gates.total | `6` | apps/web/public/data/provenance.json | `gate_summary.n_gates` |
| gates.met | `2` | apps/web/public/data/provenance.json | `gate_summary.n_met` |
| gates.note | `Met counts a gate that was passed or pre-passed.` | apps/web/public/data/provenance.json | `gate_summary.note` |
| gates.measured | `4` | apps/web/public/data/provenance.json | `gate_summary.gates[] where verdict is not PRE_PASSED` |
| gates.measuredPassed | `0` | apps/web/public/data/provenance.json | `gate_summary.gates[] where verdict is not PRE_PASSED and verdict is PASSED` |
| provenanceLine.snapshot | `snap-20260817-stage1` | apps/web/public/data/provenance.json | `snapshot_id` |
| provenanceLine.splitSha | `bdb159ca13ec` | apps/web/public/data/provenance.json | `split_manifest_sha256` |
| provenanceLine.attribution | `Waterfall imagery from the SatNOGS Network, contributed by volunteer ground stations, under CC BY-SA 4.0. See DATA_LICENSE.md.` | apps/web/public/data/cards.json | `attribution` |
| colophon.file | `apps/web/public/waterfalls/14740031.webp` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].file` |
| colophon.recordUrl | `https://network.satnogs.org/api/observations/14740031/` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].source_url` |
| colophon.artifactUrl | `https://s3.eu-central-1.wasabisys.com/satnogs-network/data_obs/2026/8/9/23/14740031/waterfall_14740031_2026-08-09T23-50-08.png` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].waterfall_url` |
| colophon.retrievedAt | `2026-08-16T20:14:03.180818+00:00` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].retrieved_at` |
| colophon.sha256 | `e496d34e0021e6d7306ffc9602f062a56a8403feed58b0ae866be7c5825ae0cd` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].source_sha256` |
| colophon.licence | `CC BY-SA 4.0` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].license` |
| colophon.licenceUrl | `https://creativecommons.org/licenses/by-sa/4.0/` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].license_url` |
| colophon.modification | `cropped to the spectrogram interior and re-encoded from PNG to WebP; the _thumb variants are additionally downscaled` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].modification_notice` |
| colophon.station | `91` | artifacts/ATTRIBUTION_AUDIT.json | `rows[19].ground_station` |
| colophon.obligationsSource | `DATA_LICENSE.md, the six items this project commits to per artifact` | artifacts/ATTRIBUTION_AUDIT.json | `obligations_source` |

### The nine derived figures

Nine of the claims above are arithmetic on a receipt rather than a key in one. Each is
recomputed by name in `test/claims.test.ts`, and the test asserts that the set of derived
claims is exactly these nine, so a tenth cannot appear unchecked: `corpus.noVerdict`, the
three `reviewQueue.criteria.N.firedInBudget`, `physics.shiftPx`,
`gate3Result.discriminating`, `lift.threshold`, `gates.measured` and
`gates.measuredPassed`.

### The imagery

There is one photograph-like asset in the film and it is real: the waterfall for
observation 14740031, served from `apps/web/public/waterfalls/14740031.webp` through
`Config.setPublicDir("../apps/web/public")`, which is the exact file the console ships.
There is no copy of it inside `presentation/`. Everything else drawn is a chart over
receipt values: the 2,727 cell grid is `DATASET_MANIFEST.observations[].waterfall_status`,
the 407 bars are `QUEUE_RECEIPT.queue[].score` in rank order, and the three corridor
curves are `cards.json`'s own `rows`, `predicted_px` and `fitted_px` arrays, drawn with
the stroke convention `apps/web/components/WaterfallViewer.tsx` uses: white solid for the
fitted corridor with its half width shaded, amber dashed for the same geometry at zero
offset, grey dashed for the commanded receive frequency.

The test cross-checks the picture against the number rather than trusting either.
`|shiftPx| x hz_per_px` must equal `|fitted_offset_hz|`, and the two must carry opposite
signs, which is what the receipt's own note says about the frequency axis running against
the Doppler sign. 113 pixels at 123.76 Hz per pixel is 13,985.15 Hz against a recorded
offset of 13,985.15 Hz.

## Commands

Preview in the studio, which hot reloads and lets you scrub:

```
cd presentation
npm install
npx remotion studio
```

Re-render the film and the poster frame:

```
cd presentation
npm run render      # remotion render Film out/tracetriage-film.mp4 --concurrency=4 --muted --pixel-format=yuv420p
npm run poster      # remotion still Film out/tracetriage-film-poster.jpg --frame=1730 --jpeg-quality=92
```

Check every number against its receipt:

```
cd presentation
npm test            # vitest run
npx tsc --noEmit    # the key paths are resolved in TypeScript, so this is a real check
```

The film reads five files outside this package and writes nothing outside
`presentation/`. It does not need the console to be built, a network connection, a GPU or
a model runtime.

## Verification, as it printed

### The render

```
> tracetriage-presentation@1.0.0 render
> remotion render Film out/tracetriage-film.mp4 --concurrency=4 --muted --pixel-format=yuv420p

Getting composition
Composition          Film
Codec                h264
Output               out/tracetriage-film.mp4
Concurrency          4x
Rendered 3094/3090
o                    out/tracetriage-film.mp4 4 MB
```

Wall clock 158 seconds on this machine, measured around the `npm run render` call. Output
4,033,764 bytes, which is 3.85 MiB. The poster frame is 275,349 bytes.

Four frames per run stall on the font handle for the full 60 second timeout and are then
retried and rendered correctly. The group is always the size of the concurrency and the
frame numbers move between runs (1780 to 1783 in one, 1222 to 1223 and 2434 to 2435 in
another), so it looks like a page recycle where every tab refetches the bundle and the
font requests queue behind it. The retry is configured for this and recovers, and the
stall is left visible in the render log rather than hidden. It is why `src/fonts.ts` sets
`retries: 3`.

The retry recovers rather than papering over a bad frame, and that is measured rather than
assumed: rendering this tree twice, once at concurrency 4 and once at concurrency 2,
produced a byte-identical file both times.

```
$ md5sum out/probe.mp4 out/tracetriage-film.mp4
47eb374c785e7eadc6b42982611235ba *out/probe.mp4
47eb374c785e7eadc6b42982611235ba *out/tracetriage-film.mp4
```

The GL renderer is pinned to `angle` in `remotion.config.ts` for the same reason:
unpinned, the antialiasing changes and the digest with it.

### The tests

```
 + test/claims.test.ts (375 tests) 130ms

 Test Files  1 passed (1)
      Tests  375 passed (375)
   Duration  1.15s
```

`npx tsc --noEmit` prints nothing.

Two of those 375 are the scan that says no measurement was typed into a beat by hand, and
they were checked by planting one. Changing `Each one names a question` to `All 6 name a
question` in `src/beats/Gates.tsx` fails `Gates has no hand-typed figure in its copy`, and
changing the eyebrow to `The 6 gates` fails `Gates has no hand-typed figure in a string`.
Both were reverted. The scan allows three strings with a digit in them, each named in the
test with its reason: `sha256 of the bytes`, `H.264` and `95%`.

### The container

```
$ ffprobe -v error -show_entries stream=codec_name,codec_type,width,height,r_frame_rate,nb_frames,pix_fmt \
    -show_entries format=duration,size,nb_streams -of default out/tracetriage-film.mp4
[STREAM]
codec_name=h264
codec_type=video
width=1920
height=1080
pix_fmt=yuv420p
r_frame_rate=30/1
nb_frames=3090
[/STREAM]
[FORMAT]
nb_streams=1
duration=103.000000
size=4033764
[/FORMAT]
```

One stream and no audio track, 1920 by 1080, exactly 30 frames a second, 3090 frames,
103.0 seconds. `nb_streams=1` is the line that matters for the no-audio requirement:
Remotion adds a silent AAC track unless `--muted` is passed, and the first render of this
film had one.

The test asserts the same four properties when the file exists and ffprobe is on the path,
and says which one is missing rather than passing quietly when either is not.

Frames were also extracted from the encoded mp4 with ffmpeg at 3, 15, 30, 58, 75, 92 and
100 seconds and read, so the checks above are on the delivered file and not only on the
composition.

## Deliverables

| File | What it is |
|---|---|
| `presentation/out/tracetriage-film.mp4` | The film. 4,033,764 bytes, 103.0 s, 1920x1080, 30 fps, h264, no audio. |
| `presentation/out/tracetriage-film-poster.jpg` | Poster frame at frame 1730, the physics beat with both curves and the measurement on screen. 275,349 bytes. |
| `presentation/src/data.ts` | Every claim, with its file and key path. The single place a number enters the film. |
| `presentation/src/claim.ts` | The path resolver and the formatters. |
| `presentation/src/theme.ts` | The console's tokens, copied from `globals.css` and checked against it by the test. |
| `presentation/src/beats/*.tsx` | One file per card. |
| `presentation/test/claims.test.ts` | 375 checks. |
| `presentation/remotion.config.ts` | Public directory, image format, pixel format and GL renderer, each with the reason it is pinned. |

## Two things a reader should know

**The film is a derived work of a ShareAlike dataset.** It contains a SatNOGS waterfall,
so under `DATA_LICENSE.md` the mp4 is CC BY-SA 4.0, not MIT. The closing card states that
and carries the six obligations. `artifacts/ATTRIBUTION_AUDIT.json` audits tracked media
files and does not know about `presentation/out`, so if the mp4 is committed, whoever owns
`scripts/` should decide whether that directory joins the audit's scan. `DATA_LICENSE.md`
calls a missing attribution line a release blocker rather than a cleanup item, which is
why it is raised here rather than left for someone to notice.

**Nothing was estimated.** Two figures I wanted are not in the film because no receipt
carries them: how many observations exist across the SatNOGS network, which would have
made beat 1 larger than the 2,727 in this snapshot, and any measured margin between the
curved and vertical hypotheses, for the reason given above. The film says 2,727 and stops
there.
