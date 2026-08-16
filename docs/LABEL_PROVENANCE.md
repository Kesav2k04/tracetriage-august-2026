# Label provenance

How TraceTriage assigns labels to SatNOGS observations, and why each rule
exists.

This document covers every path through [`pipeline/tracetriage/provenance.py`](../pipeline/tracetriage/provenance.py).
If a decision about a label is not in this document, it is a bug.

---

## The three-outcome model

Every observation is one of exactly three things:

| Outcome | Meaning | Eligible for training |
|---|---|---|
| `POSITIVE` | `waterfall_status == "with-signal"`, artifact present | Yes |
| `NEGATIVE` | `waterfall_status == "without-signal"`, artifact present | Yes |
| `UNLABELLED` | Everything else | No |

There is no implicit fourth state. `UNLABELLED` is not equivalent to
negative. An observation being unlabelled carries prior information (its base
rate is not 0%) and must not be discarded as background noise.

---

## The four label traps — each measured, not theoretical

### Trap 1: future observations

**Rule:** `status == "future"` → `FutureObservationError`. Never classified.

A bare API listing returns future observations with `waterfall == null` and
`waterfall_status == "unknown"`. In one A3 attempt, 200 consecutive records
were future passes. If they reach the training set they become spurious
negatives at scale: the model learns to predict "no signal" on passes that
have not happened yet, and the false-negative rate inflates accordingly.

The `label_from_obs()` function raises `FutureObservationError` on any
record with `status == "future"`. The `label_observations()` batch helper
does the same unless called with `skip_future=True`. The exception exists
so a future record that slips through fails loudly rather than silently.

Test: `TestFutureObservationNeverEntersLabelSet`

---

### Trap 2: missing waterfall → artifact-unusable, NOT negative

**Rule:** `waterfall == null` → `ArtifactStatus.MISSING`, `LabelOutcome.UNLABELLED`.
The label_origin is `MISSING`, not `SATNOGS_VET`.

A null waterfall URL means the artifact was never downloaded, or was never
created (the station may have failed to upload it, or the pass failed before
transmission). It says **nothing** about whether the satellite transmitted a
signal. Classifying a missing artifact as negative would:

- inflate the negative class with records that are genuinely unknown
- bias the calibration toward false negatives on stations that upload
  waterfalls unreliably

This rule applies even when `waterfall_status` is a seemingly decisive value.
If the API returns `waterfall_status == "without-signal"` but the waterfall
URL is null, the label is `UNLABELLED`. The stated human judgement cannot be
verified without the artifact.

`__post_init__` enforces this structurally: a `ProvenanceRecord` with
`artifact_status == MISSING` and `label_outcome == NEGATIVE` raises
`AssertionError` at construction time.

Test: `TestMissingWaterfallNeverBecomesNegative`

---

### Trap 3: `waterfall_status == "unknown"` → unlabelled, NOT negative

**Rule:** `waterfall_status == "unknown"` → `LabelOutcome.UNLABELLED`.
Label origin is `SATNOGS_UNVET`.

`unknown` means one of two things:
1. The observation has not yet been vetted.
2. A vetter found the waterfall genuinely ambiguous.

In either case the label cannot be used. Coercing it to negative would:

- suppress recall on recently-captured passes (not yet vetted by the network)
- inflate the negative class by a factor of roughly 2.4 at the measured base
  rate (71% of observations are `unknown`)

**Vetting lag** (`vetting_lag_seconds`): the module records the elapsed time
between `obs.end` and `obs._retrieved_at` (the snapshot retrieval time).
A small lag (e.g. < 24 hours) means the observation is simply unvetted rather
than permanently ambiguous. Downstream stages can use this to separate the
two cases without changing the label.

Test: `TestUnknownNeverBecomesTrainingLabel`

---

### Trap 4: `with-signal` is not `MEASURABLE` — these are distinct fields

**Rule:** `labelled_positive` and `carries_measurable_trace` are separate
boolean attributes. One can be true while the other is false. This is the
normal state at provenance time.

From A3: 24 vetted `with-signal` observations were inspected. Of those:

- 7 carried a narrowband trace strong enough to score (> 4 sigma peak)
- 17 showed something a human vetter deemed visible but no measurable
  carrier (0.7–3.5 sigma)

So `with-signal` is a human judgment that *something* is visible. It is a
training positive. It is not a guarantee that the model will find anything
to score.

If A6 trains against `MEASURABLE` instead of `POSITIVE`, it trains against
a target it cannot see (only 29% of labelled positives carry a scorable
trace). If it treats `POSITIVE` as `MEASURABLE`, it trains against a target
that is too easy (every vetted human call, including the 71% that are
sub-threshold).

The two fields are preserved separately so downstream code is forced to
choose explicitly:

| What you want | Field to use |
|---|---|
| Training target (label from the human vetter) | `labelled_positive` |
| Physics scoring target (model can see this) | `carries_measurable_trace` |
| Both must hold | Check both independently |

`carries_measurable_trace` is set by `label_from_obs()` to `False` at
provenance time (trace presence is `UNVETTED` until the model scores it).
It becomes `True` only after A7 or the model updates the record with
`TracePresence.MEASURABLE`.

`__post_init__` enforces structural consistency: setting
`carries_measurable_trace=True` with `trace_presence != MEASURABLE` raises
`AssertionError`.

Test: `TestLabelledPositiveVsMeasurableTraceAreDistinct`

---

## The `TracePresence` states

| State | When set | Meaning |
|---|---|---|
| `MEASURABLE` | After A7/model scoring | Clear narrowband trace (> 4 sigma). A3: 7/24 with-signal |
| `VISIBLE_BUT_UNMEASURABLE` | After A7/model scoring | Vetter saw something; model cannot score it. A3: 17/24 with-signal |
| `ABSENT` | At provenance time, `without-signal` | Vetted negative |
| `UNVETTED` | At provenance time | Artifact present but not yet model-scored |
| `UNKNOWN` | At provenance time | Artifact missing or future observation |

`UNVETTED` is the default state for any observation with a waterfall URL,
regardless of `waterfall_status`. The distinction between `UNVETTED` and
`MEASURABLE` / `VISIBLE_BUT_UNMEASURABLE` is resolved in A7.

---

## Label origins

| Origin | When set | Meaning |
|---|---|---|
| `SATNOGS_VET` | `waterfall_status` is `with-signal` or `without-signal` AND artifact present | A human or automated vetter on the SatNOGS network set this label |
| `SATNOGS_UNVET` | `waterfall_status == "unknown"` with artifact present | Not yet vetted, or ambiguous |
| `MISSING` | `waterfall == null` | No artifact; vetting never happened |
| `FUTURE_PASS` | Reserved (not set by `label_from_obs`) | Observation not yet run — never reaches this field because `FutureObservationError` fires first |

---

## Measured base rates

From kill gate 1 (600 observations, verified):

| Metric | Value |
|---|---|
| Decisive (`POSITIVE` or `NEGATIVE`) | **29.0%** |
| Imbalance (`POSITIVE : NEGATIVE`) | **1.85 : 1** |
| Approximate positive fraction | 18.83% |
| Approximate negative fraction | 10.17% |

These are named constants in the module (`BASE_RATE_DECISIVE_FRACTION` etc.)
and tested in `TestBaseRateConstants`. They are **not used to rebalance the
label set silently**. They are carried forward for:

- calibration: the calibration module must account for this imbalance
- reporting: the README and submission must state the imbalance, not hide it
- evaluation: a classifier that outputs 0.19 for everything beats random but
  is not useful; these numbers define the floor

---

## What `label_from_obs()` does and does not do

**Does:**
- Check `status == "future"` and raise immediately
- Check `waterfall` URL for emptiness/null and set `ArtifactStatus.MISSING`
- Map `waterfall_status` to `LabelOutcome` and `LabelOrigin`
- Compute `vetting_lag_seconds` from the two timestamps
- Set `labelled_positive` and `carries_measurable_trace` as consistent booleans
- Preserve all raw fields verbatim

**Does not:**
- Download or inspect the waterfall artifact
- Run the physics corridor
- Score the trace against any model
- Set `TracePresence.MEASURABLE` (that requires A7 or later)
- Modify any SatNOGS record

---

## Failure modes

| Failure | Symptom | Guard |
|---|---|---|
| Future records in label set | Spurious negatives on observations that have not run; inflates false-negative rate | `FutureObservationError` on `status == "future"` |
| Missing artifact treated as negative | Inflated negative class; biased against stations with unreliable upload | `AssertionError` in `__post_init__` if NEGATIVE + MISSING |
| `unknown` coerced to negative | 71% of observations become negatives; destroys recall | `UNLABELLED` for all `unknown` cases |
| `with-signal` equated to measurable trace | A6 trains against invisible target; physics score becomes meaningless | Separate `labelled_positive` and `carries_measurable_trace` fields |
| Vetting lag ignored | Recent unvetted observations indistinguishable from permanently-unknown | `vetting_lag_seconds` field on every record |

---

## Contract reference

`label_from_obs()` returns a `ProvenanceRecord` whose fields assemble into
the `provenance` sub-object of `contracts/triage_receipt.schema.json` via
`to_receipt_provenance()`. The required fields are:

- `source_url` ← `record.source_url`
- `retrieved_at` ← `record.retrieved_at_utc`
- `license` ← always `"CC BY-SA 4.0"`
- `api_label` ← `record.waterfall_status_raw`
- `label_origin` ← `record.label_origin.value`
- `artifact_sha256` ← passed separately (from snapshot manifest)
- `split` ← passed separately (null until splits are frozen in B1)
- `station_id` ← `record.ground_station`
- `transmitter_uuid` ← `record.transmitter_uuid`

## Why the invariants raise instead of asserting

`ProvenanceRecord.__post_init__` enforces its structural invariants with
explicit `raise ProvenanceInvariantError`, never with `assert`.

`python -O` strips every assert statement, and no test suite runs under `-O`, so
invariants written as asserts hold in exactly the environments that check them
and in none of the environments that run the pipeline. Measured before this was
changed: under `-O` a record constructed cleanly carrying
`label_outcome=UNLABELLED` together with `labelled_positive=True`, and
`trace_presence=ABSENT` together with `carries_measurable_trace=True`. That is
the precise conflation this module exists to make impossible, and the full suite
stayed green throughout.

`TestInvariantsSurviveOptimisedMode` runs the construction in a subprocess under
`-O` and fails if it succeeds, so a regression back to `assert` cannot pass
unnoticed.
