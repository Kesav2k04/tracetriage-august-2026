# Project MCP tool specifications

This project registers one MCP server in `.bob/mcp.json`. It exposes the evidence
this repository measured, plus the checker that decides whether a sentence about
an observation is supported by it, so an agent can ask the questions directly
instead of learning which file holds which number.

Two rules bind every tool:

- **Read-only with respect to SatNOGS, and to this checkout.** No tool writes
  upstream, and no tool writes to disk. `tests/test_mcp_server.py` walks the
  server's source for a network write verb and for a filesystem write, and fails
  on either.
- **Deterministic.** Every value is copied from a committed receipt rather than
  recomputed, so the same checkout gives the same answer. A tool whose output
  drifts between runs cannot back a public claim.

Two further properties are asserted rather than asked for: a call that cannot be
answered returns a named reason code instead of an empty payload that reads like
an answer, and output is bounded, because a tool that returns a quarter of a
megabyte is a tool nobody calls twice.

---

## Implemented tools

The server is `scripts/mcp_server.py`. It speaks newline-delimited JSON-RPC 2.0 on
stdin and stdout, which is what an MCP stdio transport is, and it imports nothing
outside the standard library, so it adds no dependency to the offline install.

### `queue_top`

The top of the physics-conditioned review queue, in rank order.

    in:  limit (optional, capped by the server)
    out: rank, observation id, review value, reason code and label per row, and
         the cap that was applied if the request asked for more than the cap

### `observation`

Everything measured for one observation, and the note that shipped with it.

    in:  observation_id
    out: the evidence packet and its sha256, the reviewer note, whether that note
         was generated or deterministic, and the refusal codes if a generated
         draft was rejected

### `check_claim`

Check a sentence about one observation against that observation's own fields.

    in:  observation_id, text
    out: GROUNDED or REFUSED, with a violation code and a message per problem

This is the tool worth knowing about. It is the same checker that refused 14 of
25 of this project's own generated drafts, so an agent can have its prose checked
against the evidence before a human reads it.

### `gate_status`

The kill gates and their verdicts, read from the receipt rather than typed.

    in:  nothing
    out: one row per gate with its title, its verdict and the document it was
         decided in, plus the count met

### `receipt`

The scalar summary of one receipt under `artifacts/`.

    in:  name (a filename under artifacts/, and nothing that escapes it)
    out: the receipt's scalar fields, the size of each collection it holds, and
         the file size, never the whole file

---

## Specified and not implemented

The five tools below were specified before the build and **do not exist**. Each
was written as a tool because the plan expected Bob to drive the pipeline through
one; the work each describes was done by a script instead, and the script is named
so the gap is visible rather than implied. Nothing in the repository claims these
are callable, and no receipt depends on them.

### `build_review_fixture`

Build a frozen offline fixture from the snapshot. Done by `scripts/build_splits.py`
for the splits and `scripts/dump_ocr_fixture.py` for the reader fixtures; the
frozen files are committed under `tests/fixtures/`.

### `overlay_doppler_track`

Render one observation's waterfall with its expected corridor and residual. Done
by `scripts/explainer_corridor.py` and `scripts/render_evidence_card.py`, and the
two-hypothesis comparison that settled which corridor model matches reality is
`scripts/a3_doppler_investigation.py`, whose output is under
`artifacts/a3_overlays`.

### `score_triage_queue`

Rank observations by review value against baseline orderings. Done by
`scripts/run_queue.py` and `scripts/run_baseline.py`, which share one ordering
code path so the comparison is not two implementations.

### `run_selective_evaluation`

Calibrated probabilities with abstention, and grouped bootstrap intervals. Done by
`scripts/run_fusion.py`, which writes `artifacts/FUSION_RECEIPT.json`.

### `run_acceptance`

The release gate. Done by `scripts/gate.py` and `scripts/audit_release.py`, which
between them run the standing gates, the secret scan, the licence attribution
check and the repository weight check.
