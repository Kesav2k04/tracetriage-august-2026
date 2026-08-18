Start unit C1, the review-value queue and kill gate 6. First unit of Wave C.

Read docs/BOB_HANDOFF.md and .bob/rules.md first, then the three context sections
below before you write anything. They are not background: each one changes what C1
has to produce, and most of them exist because a previous unit got the same thing
wrong.

================================================================================
CONTEXT 1: what Wave B established, and what it failed to establish
================================================================================

HEAD is `1b59b03`. Standing gates 7/7. Offline tests 563, all passing.

Wave B built the splits, the four feature blocks, the fusion ladder, calibration,
abstention and out-of-distribution scoring. Five results constrain C1.

**Finding 1. Kill gate 5 is NOT_ESTABLISHED, and you must not paper over it.** The
gate asked the physics-conditioned model to lower Brier score against a calibrated
image-only baseline. The margin is +0.02080 with a 95% interval of -0.01271 to
+0.05022 on 88 test observations across 88 episodes. A point estimate in the right
direction whose interval contains zero is not a gain. The verdict is recorded as
failed with the gate's original wording intact.

What *did* hold is narrower. With the geometry block removed, `image_corridor`
beats calibrated image-only twice on those same 88 observations: Brier +0.02026
(95% CI +0.00695 to +0.03435) and risk-coverage area +0.05736 (95% CI +0.02688 to
+0.09369). Both survive Bonferroni correction over all 7 comparisons reported for
that split. AURC drops from 0.1308 to 0.0735.

`image_corridor` is the shipped arm. Read `artifacts/FUSION_RECEIPT.json`
`ablation_conclusion` for the rule that selected it, both rules it evaluates, and
the two disclosures it carries.

**Finding 2. The physics arm's geometry block is dropped, and it is dropped on a
measurement.** Marginal AUC on the 518 decisive training observations of the
chronological split, before any head was fitted: doppler_rate_max 0.567,
tle_epoch_age_days 0.550, doppler_swing 0.547, tca_frac 0.538, max_elevation
0.521, pass_duration 0.509, rx_offset_from_catalogue 0.466. `physics_only` scores
Brier 0.2136 against the 0.2085 prior-only floor, and its calibration slope after
temperature scaling is -0.07, which is a flat line. `half_width_hz` measured
exactly 0.5000 over one distinct value, because it is a fixed model parameter
rather than a measurement, and it is excluded by name in `features.py` so nobody
re-adds it.

What that means for you: **do not rank the queue on the model's probability
alone.** A calibrated probability from arms this weak will not order the queue
usefully. The ranking signal the plan asks for is review *value*, which is a
different quantity: disagreement with the current SatNOGS label, uncertainty,
novelty, coverage gaps, and duplicate-safe diversity. Disagreement is the one with
real content here, because it does not require the model to be strong in absolute
terms, only to disagree in the right places.

**Finding 3. The corridor arm's most interesting output is not a classification.**
The fitted frequency offset is a physical measurement: observation 14740031 sits
32.0 ppm away from its recorded downlink frequency, and its commanded receive
frequency matches the SatNOGS catalogue exactly, so the discrepancy is invisible
in metadata and visible only in the image. A transmitter whose catalogue frequency
is tens of ppm stale is a database defect a volunteer can actually fix. Treat
"this observation implies a stale catalogue frequency" as a first-class queue
reason, not a side effect. Note also that `corridor_only` reaches AUC 0.785 with a
calibration slope of 8.28, so the block ranks well and is badly miscalibrated
alone: use it for ordering, not for a standalone probability.

One trap in that feature, measured, so do not rediscover it the hard way. Of the
716 observations with a fitted offset, 3 have `offset_at_bound: true`, meaning the
search hit its window limit and the reported value is a floor rather than a
measurement. Those 3 have a median absolute offset of 48.0 ppm against 12.3 ppm for
the corpus, so they are 3 of the top 20 by magnitude. Any queue that thresholds on
offset magnitude will pull them to the front, and they are the least trustworthy
rows in the cache. Exclude them, or rank them separately with the reason recorded,
and either way state the count. A value at the edge of its own search window is not
a measurement of anything.

**Finding 4. Six of the twelve split partitions contain zero Doppler-uncorrected
observations,** so the corridor's *shape* carries no information there at all. A3
found 3 uncorrected among 24 vetted. Any queue reason depending on corridor shape
must state that it applies to a minority of captures and must degrade to a named
state rather than to a zero on the rest.

**Finding 5. Abstention can only promise a low error rate on seen entities.** A 5%
risk ceiling is feasible only on the chronological split, at threshold 0.8375 and
33.1% coverage. On cold_station, cold_transmitter and cold_combined no threshold
reaches 5% risk at 5% coverage; the best available calibration risks are 0.167,
0.200 and 0.125. And novelty does not rescue this: on the one split where a
contrast exists, unseen-station risk ratio is 0.90 and unseen-transmitter 1.20, so
the novelty axes do not predict error. On a cold split every test row is novel by
construction, so `risk_by_novelty` has an empty cell and reports no ratio at all.
Ship novelty as a reviewer signal if you like. Do not ship it as an error
predictor.

================================================================================
CONTEXT 2: four rules that come from previous units getting them wrong
================================================================================

**A feature may only come from an observation-time field.**
`splits.FIELD_CLASSIFICATION` classifies all 50 fields on a raw SatNOGS record as
`observation_time`, `identifier` or `post_observation`, and
`features.admissible_source_fields` raises on anything that is not
observation-time. Route every new input through it. The list this replaced was
written by hand and had missed `status` (SatNOGS derives it from vetting, so it is
the label under another name), `demoddata` (decoded frames answer the exact
question the model is asked), `payload`, `archived`, `archive_url` and
`transmitter_updated`. `ground_station` and `transmitter_uuid` are identifiers: use
them for grouping and for novelty, never as model inputs.

**A check that examines nothing is not a passing check.** Report the count examined
next to every result. `splits.reject_vacuous_checks` refuses to freeze a manifest
where any check examined zero records, and the split manifest schema requires
`n_examined >= 1`. Gate 6 has the same failure mode available to it: a queue that
surfaces four observations and gets three right is not a 75% precision.

**An exemption needs a number attached.** Where a guarantee legitimately does not
apply, measure and record what it would have measured anyway. A leakage check was
once scoped out of the cold-combined split with a written reason and no count; the
builder later changed, the reason stopped being true, and 12 transmitters plus 4
stations crossed partitions while both checks reported clean. The scope table in
`splits.CHECK_SCOPES` is now read by both the manifest and the audit so the two
cannot disagree.

**A verdict that can only be good news is not a verdict.** Two bugs in B6 had the
same shape. A bootstrap reported `distinguishable = lo > 0`, so an interval lying
entirely *below* zero came out as "spans zero", and every place the physics blocks
were reliably worse would have read as "no difference". Separately, the
multiplicity correction was computed only where the challenger won, which made a
corrected harm unrepresentable and left the ablation rule's DROP branch as dead
code. Any verdict you emit needs at least three states, and often four: better,
worse, indistinguishable, and could-not-measure. Folding "could not measure" into
"failed" manufactures regressions; folding "worse" into "no difference" hides them.

================================================================================
CONTEXT 3: current state
================================================================================

  Splits            artifacts/SPLIT_MANIFEST.json, schema 0.3.0
                    chronological 1909/408/410 (episode-grouped time cut)
                    cold_station 2031/293/403
                    cold_transmitter 2235/139/353
                    cold_combined 945/110/183, plus 1489 excluded
  Fusion            artifacts/FUSION_RECEIPT.json, contract
                    contracts/fusion_receipt.schema.json 0.1.0
  Caches            artifacts/hog_cache/ (739 x 16740, the .npy is gitignored),
                    artifacts/corridor_features.json
  Shipped arm       image_corridor. Brier 0.1292, AUC 0.875, ECE 0.0713,
                    calibration slope 1.48 on the chronological split.
  Gates 1,2,3       PASSED. Gate 4 is an operator task.
  Gate 5            NOT_ESTABLISHED, recorded, wording unchanged.
  Gate 6            OPEN. Yours.

Snapshot: D:/tracetriage_data/snap-stage1, 2,727 observations, 739 with a decisive
with-signal or without-signal label.

Regenerate the fusion receipt with:
  .venv/Scripts/python.exe scripts/run_fusion.py --n-boot 4000

================================================================================
UNIT C1: review-value queue and kill gate 6
================================================================================

Estimated 5 to 7 credits. Do not start C2.

Gate 6, in the plan's words: "Require the top review queue to find at least 1.5
times as many manually actionable conflicts as random ordering at the same budget."

Build the queue and measure that.

**What counts as an actionable conflict** has to be defined before you rank
anything, written down, and then not changed. Propose your definition in your first
message. It must be checkable from the snapshot without a human in the loop, and it
must be something a SatNOGS volunteer would actually act on. Candidates, and you
should argue for a set rather than accept this list:

- the model confidently disagrees with the current `waterfall_status`, on an
  observation whose label was applied by a single vetter;
- the fitted frequency offset exceeds a threshold you fix in advance, implying a
  stale catalogue downlink frequency (see Finding 3);
- the capture is Doppler-uncorrected while its station's other captures are
  corrected, implying a misconfigured client;
- a substantial fraction of the waterfall is dead capture time (`flat_row_frac`).

**Ranking must beat four baselines, not one.** The plan names them: random, FIFO,
image uncertainty, and physics-only ordering. Report lift against each at a fixed
review budget, and pick the budget before you look at the results.

**The interval is grouped.** Use `fusion.grouped_paired_bootstrap` for a
per-observation mean, or `fusion.grouped_bootstrap_statistic_difference` for
anything that is a functional of the whole ranking, which lift almost certainly is.
Either way you resample pass episodes, not observations. Four captures of one pass
at one station share a receiver, a local-oscillator error and a sky geometry. Unit
A7 read three measurements that shared two ground stations as three independent
confirmations, and that is the mistake this discipline exists to prevent.

**Duplicate-safe diversity.** The queue must not spend a reviewer's budget on four
captures of the same pass. Deduplicate by (station, satellite, orbital revolution)
episode, and state what you do when two episodes share a waterfall SHA-256. The
corpus has 2,500 waterfalls with 2,500 distinct hashes, so any duplicate handling
you write is untested by the data: test it with a constructed duplicate, the way
`tests/test_split_guarantees.py` does.

Emit:

- `artifacts/QUEUE_RECEIPT.json`: the ranking, the conflict definition in full, the
  budget, lift against all four baselines with grouped intervals, and the gate 6
  verdict with its own wording quoted.
- A queue-reason field per observation, from a fixed vocabulary, in the same spirit
  as `selective.ABSTAIN_REASONS`. No free text.
- `contracts/queue_receipt.schema.json`, ratified, with the same discipline as
  `fusion_receipt.schema.json` 0.1.0: every claim carries the count it was measured
  over, every verdict is an enum with a not-measurable state, an absent measurement
  carries its reason, and the script validates its own output before writing so a
  violating receipt never reaches disk.

Acceptance checks. Run each and report the real output, not a summary of it:

1. `python scripts/gate.py` reaches 7/7.
2. `python -m pytest -m "not network" -q` passes, at least 563 plus your new tests.
3. `artifacts/QUEUE_RECEIPT.json` validates against its contract, and the emitting
   script refuses to write a receipt that does not.
4. A test proves the queue cannot surface two observations of the same pass episode,
   by constructing that case rather than relying on the corpus.
5. A test proves the lift calculation reports a null result when the queue and the
   baseline find the same number of conflicts. Assert the interval spans 1.0.
6. Re-running with the same seed produces an identical ranking.
7. Gate 6's verdict is reported for every split in the manifest, not only the
   chronological one, and a split where it cannot be measured says so with a reason
   rather than reporting a failure.
8. Plant at least four mutations in your own ranking and lift logic and show that
   your tests catch all of them. Report any that survive and what you changed.

Do not:

- Do not tune the conflict definition after seeing the lift. Fix it, then measure.
- Do not report lift without the review budget and the count of conflicts found.
- Do not let a queue that surfaces very few observations claim a high precision.
- Do not use the model probability as the only ranking signal. See Finding 2.
- Do not treat gate 6 as passed if the interval spans 1.5x. A point estimate above
  the threshold with an interval containing it is not a pass, and saying so is worth
  more to this submission than a number that will not survive a judge asking about
  it. Gate 5 went this way and was recorded as failed; that is the standard.

Before editing, state the files you will create, your conflict definition, the
review budget, the commands you will run, and your estimated build credit risk. Collect
your Bob task ID before the session closes.
