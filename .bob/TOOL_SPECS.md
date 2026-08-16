# Project MCP tool specifications

Five tools, named in the master plan, exposed to Bob through `.bob/mcp.json`.
**None of them exist yet.** Bob implements the server at
`pipeline/tracetriage/mcp_server.py`.

Two rules bind all five:

- **Read-only with respect to SatNOGS.** No tool may write upstream, ever.
- **Deterministic.** Same snapshot plus same seed gives the same output, byte for
  byte. A tool whose output drifts between runs cannot back a public claim.

---

## `build_review_fixture`

Build a small, frozen, offline fixture from the snapshot so tests and the demo
never touch the network.

    in:  snapshot_id, n_observations, seed, include (list of reason codes to guarantee present)
    out: fixture path, sha256, the observation ids chosen, and the label distribution

Must guarantee at least one of each: decisive positive, decisive negative,
unknown, missing waterfall, unreadable axis. A fixture without the degraded cases
tests only the happy path. Implement after A1.

## `overlay_doppler_track`

Render one observation's waterfall with its expected corridor, detected trace and
residual.

    in:  observation_id, hypothesis ("corrected" | "uncorrected"), show_residual
    out: image path, hz_per_px used, plot box used, corridor width, degraded reason if any

The `hypothesis` argument is deliberate: task A3 uses this tool to overlay both
hypotheses on the same image and decide which one matches reality. Once A3
settles it, the wrong hypothesis stays available so the finding stays
reproducible. **Must state the Hz/px it used**, so a wrong constant is visible in
the output rather than hidden in the picture. Implement after A2, before A3.

## `score_triage_queue`

Rank a set of observations by review value and return the ordering with its
reasons.

    in:  snapshot_id, split, budget, ordering ("tracetriage" | "random" | "fifo" | "entropy" | "image_confidence" | "physics_only")
    out: ordered observation ids, per-item review value, reason codes, diversity stats

The baseline orderings are part of the tool, not a separate script, because gate
6 is a comparison and a comparison run through two different code paths is not
one. Implement in C1/C4.

## `run_selective_evaluation`

Evaluate calibrated probabilities with abstention.

    in:  model_checksum, split, coverage_levels
    out: Brier, log loss, calibration slope and intercept, risk-coverage curve,
         precision at budget, cold-entity slices, grouped bootstrap intervals

Bootstrap groups by orbital episode or day, never by image row. Must refuse to
run against the frozen test set unless explicitly passed `final=true`, so the
test set cannot be touched by habit. Implement in B3/B4.

## `run_acceptance`

The release gate. Run every acceptance check and emit a signed-off receipt.

    in:  commit_sha, strict
    out: per-check pass/fail, artifact hashes, model checksum, and a receipt path

Checks: clean-clone reproduction, offline replay, claim drift, secret scan,
licence attribution, failure injection coverage, accessibility, and every kill
gate's recorded status.

**This tool produces the artifact that proves Bob owned the release.** Bob's final
task runs it against the release commit, repairs what fails, and signs off.
Implement in D6.
