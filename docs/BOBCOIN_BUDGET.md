# Bobcoin budget and account rotation

Each IBM Bob trial account carries **40 Bobcoins**. The July 28 FAQ removed the single-account ceiling: when a trial expires or its coins are consumed, participants create another trial account with a different email and switch, following the published procedure. Use only accounts you own and preserve each account's genuine task history.

---

## Per-account allocation

The plan's split, applied to every 40-coin account:

| Purpose | Coins | Notes |
|---|---|---|
| Focused context and contracts | 4 | reading the handoff, ratifying schemas, stating the plan for a unit |
| Implementation | 27 | the actual build |
| Tests and repairs | 6 | writing tests, fixing what they catch |
| Handoff reserve | 3 | **untouchable.** Rotation costs coins too. |
| **Total** | **40** | |

**Actual consumption controls the cutoff, not this table.** Log the real cost of each unit in `docs/BOB_BUILD_LOG.md` and correct the wave estimates for the next account.

## Planned wave mapping

| Account | Wave | Units | Estimate |
|---|---|---|---|
| 1 | A | A0 to A7: contracts, snapshot, waterfall parser, Doppler question, physics, provenance, baseline, end-to-end slice | ~20 |
| 2 | B | B1 to B6: splits, fusion, calibration, abstention, OOD, ablations | ~14 |
| 3 | C | C1 to C6: ranking, duplicates, annotation, replay, console, accessibility | ~14 |
| 4 | D | D1 to D6: failure injection, claim drift, clean clone, secrets, docs, final acceptance | ~12 |

Wave A's estimate deliberately leaves headroom inside the first 40. A3 may expand: it is a research unit, and if the Doppler-correction answer splits by client family, resolving it properly is worth more than the estimate.

The mapping is a plan, not a constraint. If Wave A finishes at 24 coins, start B1 on the same account.

---

## The 3-coin rule

**Stop starting new features when 3 coins remain.** Not "finish what you are doing and then stop", stop starting.

An account that dies mid-unit with no handoff costs far more than 3 coins, because the next account cannot tell what is finished, what is half-written, and what is broken. It re-reads everything, and often rebuilds something that already worked.

## Rotation procedure

Run in order. Do not skip step 2 because the code "obviously works".

1. **Stop starting features.** Finish only what can complete inside the remaining coins.
2. **Run the full test and acceptance suite.** Record exactly what passes and what does not. A known failure written down is useful; a hidden one poisons the next account.
3. **Update `docs/BOB_HANDOFF.md`:** completed work, open failures, the *exact* next unit, changed files, test commands, dataset and model hashes, architectural decisions and why.
4. **Update `docs/BOB_BUILD_LOG.md`:** genuine task history, commit SHAs, failures, repairs, actual coins spent per unit.
5. **Export task history and screenshots to `bob_sessions/`,** secrets removed before writing.
6. **Commit** as `Kesav2k04 <kesavk659@gmail.com>`, no trailers.

## Starting a new account

1. Create the trial with a different email you own. Follow the published switch procedure.
2. Paste the master prompt from `docs/BOB_TASK_PROMPTS.md`.
3. Have the account read `.bob/rules.md` and `docs/BOB_HANDOFF.md`, rerun the tests, and inspect the current code **before** touching anything.
4. Continue at the next unfinished unit.

**It must not regenerate completed modules.** A rebuild wastes coins and, worse, breaks the continuity of the build record that proves Bob owned the judged path.

---

## Consumption log

Fill this in as accounts are used. Estimates without actuals are worthless for planning account 3.

| Account | Email | Started | Ended | Wave | Units done | Coins used | Notes |
|---|---|---|---|---|---|---|---|
| 1 | | | | A | | | not started |

## What burns coins fastest

Observed patterns worth avoiding, from the plan and from how these accounts fail:

- **Rediscovery.** Re-probing an API whose behaviour is already in `docs/SATNOGS_API_RECON.md`. This is why that file carries numbers instead of prose.
- **Rebuilding on a wrong constant.** The `samp-rate-rx` trap costs a whole physics unit plus the debugging that follows.
- **Unbounded units.** A task without acceptance criteria expands until the coins run out. Every unit in the prompt file has them.
- **Regeneration after rotation.** Prevented by an honest handoff, not by hope.
- **Concept re-litigation.** Bob does not need to re-select the concept, re-research competitors, or reconsider the rejected PassCast design. That decision is made.
