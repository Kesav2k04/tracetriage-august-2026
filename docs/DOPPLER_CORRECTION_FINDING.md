# Doppler correction status of SatNOGS waterfalls

**Unit A3. Resolves the blocking unknown that gated A4.**

## Finding: BOTH. Correction status varies per observation, and no metadata field reveals it.

SatNOGS waterfalls are not uniformly Doppler-corrected and not uniformly
uncorrected. Both appear in the public network, measured here with wide
margins, and **nothing in the observation record distinguishes them.**

Of 24 vetted `with-signal` observations, 7 carried a signal strong enough to
decide. Four show a Doppler-corrected capture: the carrier is a vertical line
within about a kilohertz of the tuned frequency while the predicted Doppler
swing across the pass was 5.8 to 19.3 kHz. Three show an uncorrected capture:
the energy follows the predicted Doppler curve across roughly 17 kHz.

| | Corrected | Uncorrected |
|---|---|---|
| Observations | 4 | 3 |
| Ground stations | 4 distinct | 2 distinct |
| Satellites (NORAD) | 4 distinct | 3 distinct |
| Frequency bands | 137, 400, 437 MHz | 436 MHz |
| Winning hypothesis | vertical line, 32.4 to 54.2 sigma | Doppler curve, 15.1 to 25.1 sigma |
| Losing hypothesis | 1.7 to 21.0 sigma | 2.2 to 2.8 sigma |

Evidence: 24 overlays in `artifacts/a3_overlays/`, one per observation, each
showing the untouched waterfall beside the same image annotated. Every number
here is in `artifacts/a3_overlays/summary.json`.

## What this means for A4

1. **The corridor cannot assume one hypothesis.** Both shapes occur in the data
   the queue will rank. A single fixed model is wrong on part of the corpus.
2. **Correction status must be inferred from the image, not read from
   metadata.** `doppler-correction-per-sec` is null on all 24 records and
   `rigctl-port` is `4532` on all 24, in both groups. The earlier reading of
   those two fields, that a populated `rigctl-port` implies external correction,
   is not supported: the same pair of values appears on captures that are
   plainly corrected and on captures that are plainly not.
3. **This is a feature, not only an obstacle.** TraceTriage ranks observations
   where image evidence, expected physics and the network label disagree.
   Correction status is exactly such a disagreement, it is measurable from the
   image, and it is invisible in metadata.

## Two calibration facts that A4 must not re-derive

Both were wrong in the first implementation, and wrong together, which is why
they are called out rather than buried.

**Time runs bottom to top.** The top row of a SatNOGS waterfall is the END of
the pass. Read directly off the axis of observation 14740031: the tick labelled
`200` s sits at y=258 and the tick labelled `50` s at y=1228, evenly spaced at
323 px per 50 s across a 241 s pass.

**The plotted frequency axis runs against the Doppler sign.** With a Doppler
shift defined as positive when the satellite approaches, the trace moves in the
opposite direction on the rendered axis. Measured, not assumed: the sign is
scanned per observation and all three uncorrected observations chose the same
one, at 25.1 against 2.0 sigma, 15.1 against 1.2, and 15.9 against 1.4.

These two errors cancel. A Doppler curve is near odd-symmetric about closest
approach, so reversing time and flipping the frequency sign produce almost the
same curve. The first implementation had both wrong and scored 25 sigma, and
its overlay looked correct to the eye. **A visual check cannot catch this.**
The measurement that did catch it: the trace on 14740031 runs -22.5 kHz at
t=5.5 s to -5.4 kHz at t=237.7 s, an apparent rise of +85 Hz/s against real
time, which no Doppler shift can produce.

## Method

For each observation, from its own stored record and nothing else:

1. Propagate the stored TLE across the pass and compute the Doppler shift from
   the range rate and `client_metadata.radio.parameters.rx-freq`. The geometry
   chain was already verified to 0.18 degrees and is built on, not re-tested.
2. Derive `hz_per_px`, `crop_box` and `centre_px` from the rendered axis with
   the A2 parser.
3. Normalise each image row to a median-based z-score. Nothing is normalised along
   the time axis, because that would delete a stationary carrier, which is the
   exact shape one hypothesis predicts.
4. Score two families of paths over the same set of horizontal offsets: a
   vertical line, and the predicted Doppler curve at both possible axis signs.
   Each score is the mean normalised intensity along the path.
5. Report both in units of the spread of all vertical paths across the image,
   so the null is measured from the image itself rather than assumed.

### Why whole paths and not a per-row peak

The first working version found the brightest column in each block of 8 to 32
rows and fitted the resulting track. **That method is biased toward finding
"corrected."** Near closest approach a real Doppler trace crosses about a dozen
columns inside one 16-row block, so block averaging smears it into the noise,
while a stationary carrier survives untouched. On the same 10 observations it
detected nothing at all in 8 of them, including an 86 degree pass. A method
that can only see one of two hypotheses cannot be used to choose between them.

### When the answer is refused

A verdict requires all three of:

- the better path clears 8 sigma
- one hypothesis leads the other by at least 3 sigma
- all three matched-filter widths agree

and the predicted swing must exceed 3 kHz, below which the two shapes are not
distinguishable. 17 of 24 observations failed the first condition: their best
path scored 0.7 to 3.5 sigma. They are recorded as UNRESOLVED with their
numbers, not pushed into whichever answer was more convenient.

## What remains uncertain

1. **17 of 24 vetted `with-signal` observations carry no narrowband trace this
   method can find.** `with-signal` is a human judgement that something is
   visible, not that a narrow carrier is present. Wideband, drifting and
   intermittent signals are outside what a single-path matched filter measures.
   The 29.0% decisive-label rate already known for this corpus is not the same
   thing as a 29% measurable rate, and A6's baseline should not assume it is.
2. **The correlate is suggestive but under-powered.** All 4 corrected
   observations report `samp-rate-rx` of 2.048e6 and 77 to 80 Hz/px; all 3
   uncorrected report 2.5e6 and 124 to 128 Hz/px. With 7 decisive points that
   separation could arise by chance roughly 3 times in 100. It is recorded as
   an observation to test at snapshot scale, **not** as a rule to key on.
   `client_version` does **not** separate them: version 2.1.2 appears in both
   groups.
3. **The uncorrected group is narrow.** All 3 sit at 436.400 MHz on NORAD
   63214, 63217 and 63218, from 2 ground stations. Corrected behaviour is the
   better-spread observation, across 4 stations, 4 satellites and 3 bands.
   That uncorrected captures exist is established; how common they are is not.
4. **A vertical carrier could in principle be a fixed local interferer rather
   than a corrected satellite.** Against that: all 4 sit within 1.2 kHz of the
   tuned frequency, which an unrelated interferer has no reason to do, and
   their intensity rises and falls with elevation across the pass, visible in
   `overlay_14745602.png`. This is argued from evidence, not settled by it.
5. **The constant frequency offset is unexplained.** The uncorrected traces sit
   14.0, 7.1 and 7.1 kHz off the predicted curve: `curved_offset_hz` is
   -13,985.1 Hz on 14740031 and +7,148.9 Hz on both 14745664 and 14745929, which
   is -32.1, +16.4 and +16.4 ppm of the 436.400 MHz downlink. A transmitter
   sitting a few kHz from nominal is the ordinary explanation, but it is not
   verified here. The matched filter absorbs it by design, so the verdict does
   not depend on it, but A4 must not assume the corridor is centred on `rx-freq`.

   The two 7.1 kHz figures are **identical to the decimal**, and that is not a
   coincidence: 14745664 and 14745929 were recorded by the same ground station
   (1696) three minutes apart, so they share a receiver and therefore one
   local-oscillator error and one stale catalogue frequency. That is the
   measurement behind the dependence argument in `docs/KILL_GATE.md`, and it only
   works with these numbers.

   This item read "14.0, 2.4 and 1.8 kHz" until 2026-08-23. Those two smaller
   values are `vertical_column_offset_hz` on the same two records, which is the
   offset of the vertical hypothesis these three observations reject, not the
   offset of the curve being fitted. Reading them made the two station-1696
   offsets look different when they are the same, which is the wrong way round
   for the argument above. `docs/KILL_GATE.md` carried the correct pair
   throughout, sign-flipped by `AXIS_SIGN_CONVENTION` as it documents.

## Reproducing

```
.venv\Scripts\python.exe scripts\a3_doppler_investigation.py
```

API pages and waterfall PNGs are cached under `.a3_cache/`, so a rerun costs no
requests and reproduces `summary.json` and every overlay from the same bytes.
`A3_TARGET_OBS` sets the sample size; this finding used 24.

Overlays are written as 256-colour PNGs. Measured against the source on
observation 14745929 that costs a mean absolute error of 0.06 of 255 per
channel with the 99th percentile at 1, and takes the set from 38.9 MB to
16.4 MB.
