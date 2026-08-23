# Degraded-state recon: the twelve failure modes, measured against the code

Prepared before the failure-injection unit, for the same reason
`docs/SATNOGS_API_RECON.md` exists: a fact rediscovered inside a build task is paid for
twice. Every anchor below was read out of the file it names on 2026-08-19, at commit
`77ae14b`. Nothing here is inferred from a docstring.

The unit's rule is that every mode must produce a **named** degraded state, never a blank
frame, a zero, or a silent success, and that a test asserting "did not crash" does not
count. As first measured at `a41b87e`: five modes satisfied it, three were tested against
the wrong input, and four were not implemented at all. As of D8 and D8b, six of the twelve are
COVERED, three are PARTIAL, and three have no named reason or no test at all: mode 6 (wrong
start offset), mode 9 (missing model artifact) and mode 11 (empty queue after filtering).
An earlier version of this line said all twelve had a named reason and a test that asserts
it, which its own table nine lines below contradicted in six rows. The status column is the
answer and this sentence now counts it rather than summarising it optimistically.

**Re-read on 2026-08-24 at `202dc85`.** Modes 9 and 11 were closed after the line above was
written, in `tests/test_failure_injection.py` at `TestMissingModelArtifact:254` and
`TestEmptyQueueAfterFiltering:316`, and their rows below now name those tests. The tally is
eight COVERED, three PARTIAL and one MISSING, and the one is mode 6. The paragraph above is
left as it was written rather than edited, because it is the record of what the recon found
and the table is the record of what the code does.

---

## The twelve modes

| # | Mode | Named reason in production code | Where it is emitted | Test that asserts that exact reason | Verdict |
|---|---|---|---|---|---|
| 1 | malformed image | `MALFORMED_PNG` | `pipeline/tracetriage/waterfall.py:227`, also `:229`, `:235`, `:732` | `tests/test_waterfall.py:253`, `:260` | COVERED |
| 2 | blank image | `BLANK_IMAGE` | `pipeline/tracetriage/waterfall.py:252` | `tests/test_waterfall.py:267`, negative control at `:288` | COVERED |
| 3 | missing TLE | `MISSING_TLE` | `pipeline/tracetriage/physics.py:863` | `tests/test_physics.py:277`, `:282` | COVERED |
| 4 | stale TLE beyond the age threshold | `STALE_TLE` | `pipeline/tracetriage/physics.py:899` | `tests/test_physics.py:313` | COVERED |
| 5 | absent frequency bins | `NO_AXIS_DETECTED` at image level, `NO_HZ_PER_PX` at fit level | `pipeline/tracetriage/waterfall.py:749`, raised at `:527`, `:541`, `:545`; `pipeline/tracetriage/corridor_fit.py:916` | fit level asserted exactly at `tests/test_corridor_fit.py:340`; image level only as a disjunction, `assert degraded in ("NO_AXIS_DETECTED", "UNKNOWN_LAYOUT")`, `tests/test_waterfall.py:297` | PARTIAL |
| 6 | wrong start offset | none | see below | none | MISSING |
| 7 | multiple traces in one waterfall | `MULTIPLE_TRACES_SUSPECTED` | `pipeline/tracetriage/corridor_fit.py`, `second_trace_evidence` | `tests/test_failure_injection.py`, `TestMultipleTraces` | COVERED, measured on the corpus, not wired into the feature matrix |
| 8 | network unavailable | `HTTP_ERROR` | two producers: the transport-exception catch at `pipeline/tracetriage/snapshot.py:360` and the status path at `:379` | `tests/test_snapshot.py:323` asserts `HTTP_ERROR` from an injected 500, so it exercises `:379` and never `:360` | PARTIAL |
| 9 | missing model artifact | `MODEL_ARTIFACT_MISSING` | `scripts/run_triage_slice.py:563` | `tests/test_failure_injection.py:262` asserts the reason on an absent path and `:268` asserts the checksum on a present one | COVERED, closed after this recon |
| 10 | unsupported client image format | none for a decodable format | nearest is `TRUNCATED` on non-PNG magic, `pipeline/tracetriage/snapshot.py:391` | `tests/test_snapshot.py:305` asserts `TRUNCATED` on 8 bytes of wrong magic, not on a valid image in another format | PARTIAL |
| 11 | empty queue after filtering | `"No test observations"` with verdict `NOT_MEASURABLE` | `scripts/run_queue.py:376` to `:384`, via `pipeline/tracetriage/queue.py:1344`; sibling path at `run_queue.py:521` | `tests/test_failure_injection.py:344` asserts the string, the `NOT_MEASURABLE` verdict, the split named in the reason, and that no lift is published | COVERED, closed after this recon |
| 12 | a request that times out | `TIMEOUT` | `pipeline/tracetriage/snapshot.py:358` | `tests/test_snapshot.py:329` | COVERED |

---

## The three modes that need code before they can have a test

**Mode 6, wrong start offset.** `pipeline/tracetriage/physics.py:879` returns
`_fail("MISSING_STATION")` when the pass window cannot be parsed, and the comment beside
it says "timing is always present; fail gracefully". A shifted or reversed window is
therefore published under the name of a missing ground station, which is a different
defect with a different remedy. There is also nothing to inject against: the corridor maps
onto rows by fraction of plot height only (`corridor_fit.py:539`, `:573`), and
`waterfall.py:791` derives `seconds_per_px = pass_duration_s / plot_height_px`, so no time
origin enters the calculation. Note that `OFFSET_AT_BOUND` (`queue.py:70`,
`corridor_fit.py:416`) is a **frequency** offset saturating its ppm bound. It is not this.

**Mode 7, multiple traces in one waterfall. Implemented in D8b.**
`corridor_fit.second_trace_evidence` names it `MULTIPLE_TRACES_SUSPECTED`. Before it, no
code counted traces: one path is scored per corridor, and a second satellite in the same
image was averaged into the background the first one is measured against.

Every parameter is one the module already justified, so the detector introduces no new
tunable. `z_min = 4.0` decides that a pixel is a detection, which is the fitter's own bar.
The exclusion window is `search_window_factor` (2.0) times the corridor half-width in
pixels, so a peak the fitter is already following cannot count as a second trace.
`min_detect_frac = 0.30` is the share of rows the primary itself must appear in. The one
new quantity is the coherence bound, and it is Doppler rather than a choice:
`max_coherent_jump_px` converts `PEAK_DOPPLER_SLOPE_HZ_PER_S = 119.4`, derived in D6 for
the TLE staleness threshold, into this image's pixels using its own Hz per pixel and
seconds per row, plus half the matched-filter width.

**Measured incidence, `artifacts/SECOND_TRACE_SURVEY.json`.** 743 decisive observations,
14.5 minutes at 1.17 s each. 4 have no image, 14 fail on a stale TLE, and **543 of 743
(73.1 percent) cannot be measured at all**: fewer than 8 rows carry any pixel at
`z_min`, which is the same reason `detect_frac_curved` is 0.0 for most of this corpus.
That leaves 182 measurable, of which **10 (5.5 percent)** carry a coherent second trace.

**What the coherence bound buys, in numbers.** 61 of the 182 (33.5 percent) clear the
row-fraction bar. Only 10 of those 61 move slowly enough to be following an orbit. The
median second peak in this corpus moves 7.09 pixels per row against a median allowance of
1.82, so without the physics bound this detector would report a second satellite in a third
of the measurable corpus, and most of those would be interference. The 10 that fire move
0.0 to 1.49 pixels per row against allowances of 1.51 to 2.34.

**Two caveats that belong beside the 10.** They are not 10 independent events: station 91
contributes 4 of them, across 4 different satellites within 4.5 hours of one night, which
is the signature of a persistent interferer at one station rather than four second
satellites. The other 6 sit at 6 distinct stations, and all 10 are distinct satellites. And
one of the 10 (14733003) is labelled `without-signal`, which is not necessarily a wrong
label: the label speaks about the target, and a coherent carrier from something else can
sit in the same image. It is the exact disagreement this project's queue exists to rank.

**Not wired into the feature matrix, on purpose.** The path a measurement like this
normally takes is `extract_corridor_features.py` into `artifacts/corridor_features.json`
into `features.py`, which is how `flat_row_frac` reached the model and the queue. Taking it
there means refitting, which moves the numbers behind gates 5 and 6. That is a decision to
make deliberately and not as a side effect of closing a failure mode.

**Mode 10, unsupported client image format.** `_load_rgb`
(`pipeline/tracetriage/waterfall.py:210` to `:253`) accepts anything PIL can decode, so a
valid JPEG or GIF proceeds into layout detection and fails later under `UNKNOWN_LAYOUT`,
which names the layout rather than the format. The only format gate is the PNG magic check
at `snapshot.py:391`, and its reason is `TRUNCATED`, which is false for a complete file in
another format.

---

## Reason constants that exist and that no test asserts

Each of these is a named degraded state the code can emit today with nothing pinning it, so
a rename or a lost branch would pass the suite. Listed because the unit's acceptance is a
test per named reason, and this is the real denominator.

| Reason | Emitted at |
|---|---|
| `NO_OCR_BACKEND` | `pipeline/tracetriage/waterfall.py:765` |
| `SGP4_ERROR` | `pipeline/tracetriage/physics.py:920`. Only `SGP4_PARTIAL_ERROR` is asserted, at `tests/test_physics.py:1096` |
| `CORRIDOR_LEFT_PLOT` | `pipeline/tracetriage/corridor_fit.py:928` |
| `TRACE_NOT_MEASURABLE` | `pipeline/tracetriage/corridor_fit.py:946`. Appears in `tests/test_corridor_fit.py:823` inside a docstring only |
| `NO_VALID_MEMBERS` | `pipeline/tracetriage/fusion.py:1108` |
| `DISPLACED_STATION_CAP`, `DISPLACED_TRANSMITTER_CAP` | `pipeline/tracetriage/queue.py:78`, `:83`, emitted at `:194`. The substring `DISPLACED` does not occur anywhere in `tests/` |
| `MISCONFIGURED_CLIENT_SUSPECTED` | `pipeline/tracetriage/annotate.py:58` |
| `DEAD_CAPTURE_CONFIRMED` | `pipeline/tracetriage/annotate.py:62` |
| `MODEL_ARTIFACT_MISSING` | `scripts/run_triage_slice.py:563`. The contract declares `model_checksum_source` at `contracts/triage_receipt.schema.json:20`; `tests/test_failure_injection.py:262` now pins its value on both branches |
| `OUT_OF_DISTRIBUTION` | `pipeline/tracetriage/selective.py:43`, returned at `:250`. Reached only generically by `tests/test_selective_and_ood.py:179`, which asserts the explanation and never the reason |

---

## Two traps worth naming before the work starts

**A shared reason string hides an untested branch.** `HTTP_ERROR` has two producers. The
test injects a 500 status, which is the easy one to mock, and the branch that matters for
"network unavailable" is the `httpx.HTTPError` catch above it, which a `ConnectError` takes.
A test that asserts the string without choosing the branch reports coverage it does not
have.

**A reason can be named and still be the wrong name.** Modes 6 and 10 both emit something.
`MISSING_STATION` for a broken pass window and `TRUNCATED` for a complete JPEG are named
absences that point the reader at the wrong cause, which is worse than a null in one
respect: a null invites a check, and a confident wrong name does not.

**How to prove each test earns its place.** Mutate the input and confirm the test goes red,
the way `tests/test_gate3_bound.py`, `tests/test_kill_gate_sync.py` and
`tests/series-label.test.ts` do. A test that passes against the unfixed code is a test of
nothing.
