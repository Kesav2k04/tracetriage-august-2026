# Project MCP tool specifications

This project registers **two** MCP servers in `.bob/mcp.json`, and the split between them
is the point rather than an accident of packaging.

`tracetriage-evidence` answers from committed receipts. Every value it returns was
measured weeks ago and frozen, so the same checkout gives the same answer and a claim it
backs can be checked by reading a file. It imports nothing outside the standard library.

`tracetriage-live` measures. It downloads a published waterfall from the public SatNOGS
API, propagates the pass from the elements in the observation's own record, reads the
frequency axis off the tick labels, decides whether the capture was Doppler-corrected,
fits the offset and scores it against permuted nulls. Its answers carry the time they were
taken, because they are not reproducible in the way a receipt is: the same id measured
tomorrow uses newer elements.

Two rules bind every tool on both servers:

- **Read-only with respect to SatNOGS, and to this checkout.** No tool writes upstream and
  no tool writes to disk. `tests/test_mcp_server.py` walks both servers' sources for a
  network write verb and for a filesystem write, and fails on either: the evidence
  server and its transport in one test, the live server and the module it measures
  through in another. They are two tests rather than one because the offline half also
  asserts that no network library is imported at all, which is right for a server that
  reads committed files and wrong for one whose job is a GET. The one exception is
  named and bounded: `run_acceptance` runs this repository's own gate, which builds the
  console into the export directory the deploy contract names, and every generator it
  calls runs with `--check`.
- **A refusal is a result.** A call that cannot be answered returns a named reason code
  rather than an empty payload that reads like an answer, and output is bounded, because a
  tool that returns a quarter of a megabyte is a tool nobody calls twice.

---

## Auto-approved, and why the list stops where it does

`alwaysAllow` in `.bob/mcp.json` is applied at the start of each Bob task, so a listed
tool runs without an approval click. That is what makes the ten-minute demo in `docs/BOB_DEMO.md` possible, and
it is also a standing permission, so the list is drawn on cost rather than on convenience.

| Auto-approved | Cost of one call |
|---|---|
| `queue_top`, `queue_size`, `observation`, `check_claim`, `gate_status`, `receipt` | reads a committed file |
| `live_list_observations` | one API request, metadata only |
| `live_triage_observation` | two requests and one corridor fit, tens of seconds |
| `live_check_claim` | none when the id is already measured in this session |

| Not auto-approved | Why |
|---|---|
| `live_rank_observations` | up to 10 observations, two requests each |
| `live_station` | up to 6 observations, two requests each |
| `run_acceptance` | runs the full gate, minutes of CPU, and writes the console build |

The three that ask are the three that spend somebody else's bandwidth or the operator's
time. Everything a judge needs for the demo in `docs/BOB_DEMO.md` is on the first list.

---

## Implemented: `tracetriage-evidence`

`scripts/mcp_server.py`. Newline-delimited JSON-RPC 2.0 on stdin and stdout, which is what
an MCP stdio transport is. Standard library only, so it adds no dependency to the offline
install and it starts in milliseconds.

### `queue_top`

The top of the physics-conditioned review queue, in rank order.

    in:  limit (optional, capped by the server)
    out: rank, observation id, review value, reason code and label per row, the cap that
         was applied, and the three counts named apart from each other

### `queue_size`

How many observations the ranking covers, named apart from the per-call cap and the
review budget.

    in:  nothing
    out: available (407), cap (50), review_budget.n_observations (50), and a reading that
         says which is which

This tool exists because of a measured failure. In the agent study
(`artifacts/AGENT_RECEIPT.json`) the tool-using arm was asked for the total number of
ranked rows and answered 50, which is the per-call cap and also the review budget. Two of
the three numbers are 50 and the third is 407, and nothing in the old `reading` string
named them apart. A tool that returns three numbers with one label is a tool that will be
misread, and the fix is a tool whose whole job is to distinguish them.

### `observation`

Everything measured for one observation, and the note that shipped with it.

    in:  observation_id
    out: the evidence packet and its sha256, the reviewer note, whether that note was
         generated or deterministic, and the refusal codes if a generated draft was
         rejected

An observation with no corridor fit has no evidence packet, and this tool says so with a
reason rather than returning a packet of zeros. That is the same refusal
`pipeline/tracetriage/explain.py` makes: a card the pipeline could not measure cannot have
a note grounded in a measurement it never took.

### `check_claim`

Check a sentence about one observation against that observation's own fields.

    in:  observation_id, text
    out: GROUNDED or REFUSED, with a violation code and a message per problem

This is the tool worth knowing about. It is the same checker that refused 15 of 25 of this
project's own generated drafts. It answers `UNKNOWN_OBSERVATION` for an id outside the
committed corpus, which is correct and is also why `live_check_claim` exists.

### `gate_status`

The kill gates and their verdicts, read from the receipt rather than typed.

    in:  nothing
    out: one row per gate with its title, its verdict and the document it was decided in,
         plus the count met

### `receipt`

The scalar summary of one receipt under `artifacts/`.

    in:  name (a filename under artifacts/, and nothing that escapes it)
    out: the receipt's scalar fields, the size of each collection it holds, and the file
         size, never the whole file

### `run_acceptance`

Run this repository's standing gates and report the verdict per check.

    in:  nothing
    out: one row per check with its verdict, plus the tally

The one tool here that computes rather than reads, and the one that is not auto-approved.
It subprocesses `scripts/gate.py`, which is the same command the release sign-off runs.

### Resources

The evidence server also answers `resources/list` and `resources/read`:

    receipt://GATE3   receipt://GATE4   receipt://GATE5   receipt://GATE6

Each returns a bounded summary of that kill gate: its verdict, the document it was decided
in, and the scalar fields of the receipt behind it. A Bob session can `@`-mention one
rather than calling a tool. `resources/list` used to answer `-32601`, method not found,
which is the correct answer for a server that has no resources and the wrong answer for
one whose whole subject is receipts.

---

## Implemented: `tracetriage-live`

`python -m pipeline.tracetriage.mcp_live`. Needs numpy, scipy, pillow, sgp4 and httpx,
which is why `.bob/run-live.cmd` requires the project virtual environment and says so
rather than falling through to an interpreter that would answer `initialize` and then fail
every call.

### `live_triage_observation`

Measure one observation recorded at any time, including today.

    in:  observation_id, n_nulls (optional)
    out: the Doppler-correction verdict, the offset in Hz and ppm, the null distribution
         and its p value, the axis reading and its confidence, and provenance: the
         waterfall URL and sha256, both TLE lines, and the time of measurement

Three outcomes are normal and distinct. `UNCORRECTED` means the energy follows the pass's
predicted Doppler curve, so an offset and a p value are reported. `CORRECTED` means the
station corrected for Doppler and the trace is near-vertical, so an offset is reported and
no null test applies. `UNRESOLVED` means the image does not settle which, which on a real
queue is the common case and is the answer that says skip this one.

### `live_check_claim`

Check a sentence against an observation this server measured.

    in:  observation_id, text, n_nulls (optional)
    out: GROUNDED or REFUSED with a code per problem, the evidence packet it was checked
         against, and whether the measurement came from this session's cache or was taken
         now

This is the loop the live path exists for. The offline `check_claim` answers
`UNKNOWN_OBSERVATION` for an id that is not in the committed corpus, so an agent that has
just measured a pass recorded this morning had nowhere to send a sentence about it. Two
servers that cannot compose leave the grounding claim true only about last month's data.
The checker is `explain.verify_note`, unchanged and not reimplemented; what is new is the
packet it runs against.

### `live_station`

One ground station's recent captures, measured now, with the median offset split by mode.

    in:  ground_station, budget (optional), n_nulls (optional)
    out: the median ppm per Doppler-correction mode, the number of distinct satellites
         behind each median, and a refusal in place of any mixed-mode median

The one question a volunteer can act on: is this receiver off frequency, and by how much.
A single observation cannot answer it, because the offset it measures also holds that
TLE's propagation error and the pixel quantisation of the axis. Several observations of
different satellites can, because a receiver's error is the same across all of them and an
orbit's is not. Under three distinct satellites inside one mode, the tool reports the
numbers and refuses to call them a calibration.

### `live_list_observations`

Recent public observations, filtered by satellite, station or status.

    in:  norad_cat_id, ground_station, status, limit (all optional)
    out: one row per observation with its id, times, satellite, station and whether a
         waterfall was stored

Metadata only. Nothing in the result is measured, and SatNOGS's own with-signal flag is a
volunteer's judgement rather than a detection, which is the distinction the whole project
turns on. This is the tool that answers "give me something recorded in the last hour".

### `live_rank_observations`

Measure up to ten recent observations for one satellite or station and rank them.

    in:  norad_cat_id or ground_station, budget (optional), n_nulls (optional)
    out: the triage ordering over those observations, settled first, then by offset size

---

## Specified and not implemented

The four tools below were specified before the build and **do not exist**. Each was written
as a tool because the plan expected Bob to drive the pipeline through one; the work each
describes was done by a script instead, and the script is named so the gap is visible
rather than implied. Nothing in the repository claims these are callable, and no receipt
depends on them.

The fifth, `run_acceptance`, moved to the implemented list: it wraps a script that already
existed, which is the only one of the five where a tool adds something an agent cannot do
by reading a file.

### `build_review_fixture`

Build a frozen offline fixture from the snapshot. Done by `scripts/build_splits.py` for the
splits and `scripts/dump_ocr_fixture.py` for the reader fixtures; the frozen files are
committed under `tests/fixtures/`.

### `overlay_doppler_track`

Render one observation's waterfall with its expected corridor and residual. Done by
`scripts/explainer_corridor.py` and `scripts/render_evidence_card.py`, and the
two-hypothesis comparison that settled which corridor model matches reality is
`scripts/a3_doppler_investigation.py`, whose output is under `artifacts/a3_overlays`. Not
built as a tool on purpose: the live demo is numbers plus the console's own waterfall, and
a second renderer inside an agent transcript is a picture nobody can check.

### `score_triage_queue`

Rank observations by review value against baseline orderings. Done by
`scripts/run_queue.py` and `scripts/run_baseline.py`, which share one ordering code path so
the comparison is not two implementations.

### `run_selective_evaluation`

Calibrated probabilities with abstention, and grouped bootstrap intervals. Done by
`scripts/run_fusion.py`, which writes `artifacts/FUSION_RECEIPT.json`.
