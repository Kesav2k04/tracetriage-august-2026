# Degraded-state recon: the twelve failure modes, measured against the code

Prepared before the failure-injection unit, for the same reason
`docs/SATNOGS_API_RECON.md` exists: a fact rediscovered inside a build task is paid for
twice. Every anchor below was read out of the file it names on 2026-08-19, at commit
`77ae14b`. Nothing here is inferred from a docstring.

The unit's rule is that every mode must produce a **named** degraded state, never a blank
frame, a zero, or a silent success, and that a test asserting "did not crash" does not
count. Read that against the table: five modes already satisfy it, three are tested
against the wrong input, and four are not implemented at all.

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
| 7 | multiple traces in one waterfall | none | nothing in `pipeline/`, `scripts/` or `contracts/` counts traces | none | MISSING |
| 8 | network unavailable | `HTTP_ERROR` | two producers: the transport-exception catch at `pipeline/tracetriage/snapshot.py:360` and the status path at `:379` | `tests/test_snapshot.py:323` asserts `HTTP_ERROR` from an injected 500, so it exercises `:379` and never `:360` | PARTIAL |
| 9 | missing model artifact | `MODEL_ARTIFACT_MISSING` | `scripts/run_triage_slice.py:563` | none | MISSING |
| 10 | unsupported client image format | none for a decodable format | nearest is `TRUNCATED` on non-PNG magic, `pipeline/tracetriage/snapshot.py:391` | `tests/test_snapshot.py:305` asserts `TRUNCATED` on 8 bytes of wrong magic, not on a valid image in another format | PARTIAL |
| 11 | empty queue after filtering | `"No test observations"` with verdict `NOT_MEASURABLE` | `scripts/run_queue.py:376` to `:384`, via `pipeline/tracetriage/queue.py:1344`; sibling path at `run_queue.py:521` | none. No test references that string | MISSING |
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

**Mode 7, multiple traces in one waterfall.** No code counts traces. `corridor_fit.py`
scores one path per corridor and reports `TRACE_NOT_MEASURABLE` when too few rows carry a
usable maximum. A second satellite in the same image is scored as though it were noise
around the first, silently.

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
| `MODEL_ARTIFACT_MISSING` | `scripts/run_triage_slice.py:563`. The contract declares `model_checksum_source` at `contracts/triage_receipt.schema.json:20` and no test pins its value |
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
