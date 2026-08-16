# Actor and permission contract

What TraceTriage is allowed to do, stated before the code exists so that no feature can quietly widen it.

---

## The actor

**A volunteer or student reviewer of public radio observations.** They hold no special standing on the SatNOGS network, no moderation rights, and no station. They read public data and form a private opinion about which observations are worth their own attention.

TraceTriage acts **only** with that person's permissions, which are the permissions of any member of the public reading an open dataset.

## Permission boundary

| Capability | Status |
|---|---|
| Read the public SatNOGS API | **allowed**, unauthenticated |
| Download published waterfall artifacts | **allowed**, CC BY-SA 4.0 |
| Compute, rank and display locally | **allowed** |
| Store a local annotation | **allowed**, local storage only |
| Cast a SatNOGS vote | **forbidden** |
| Change any public label | **forbidden** |
| Schedule an observation | **forbidden** |
| Control or configure a ground station | **forbidden** |
| Hold any write credential | **forbidden** |
| Transmit anything | **forbidden** |

**The project holds no SatNOGS account, no API key, and no token.** `.env.example` contains no credential field and states that none may be added. This is not a configuration choice that could be flipped later; there is no code path that writes upstream, and task C3 requires a test asserting that no outbound write is even possible.

## Claim boundary

TraceTriage may say:

- this observation's image evidence, expected geometry, metadata and current network label **disagree**
- the evidence is **insufficient** to decide, here is the abstention reason
- under a fixed review budget on a frozen sample, this ordering surfaced more independently reviewable conflicts than that ordering

TraceTriage may **not** say:

- this satellite was confirmed
- this is decoded telemetry
- this label is wrong and the correct one is X
- the mission is healthy, or unsafe
- this is endorsed by SatNOGS, IBM, or anyone else
- this system moderates, corrects, or improves the public dataset

The permitted phrasing for a flagged item is **"model-label disagreement"**, unless independent adjudication supports something stronger. A visible signal can come from terrestrial interference or a different satellite; target-consistent geometry is evidence, not identification.

## Data handling

- SatNOGS observation data and waterfalls are **CC BY-SA 4.0**. Attribution, source URL, retrieval timestamp, modification notice and a licence link travel with every redistributed or derived artifact. These are captured at snapshot time because they cannot be reconstructed afterwards.
- Station operator names and observer handles appear in the public API. They are **not** used as model features and are not needed to display an evidence card. Station identifiers are used as **grouping keys for holdout splits**, which is a structural use, not a predictive one.
- Local annotations stay on the machine that made them. They are not uploaded, aggregated, or published as if they were community consensus.

## Courtesy to the network

SatNOGS is volunteer-run infrastructure. Reconnaissance on 2026-08-16 saw no rate-limit header and no throttling at 0.4 s between requests across 24 consecutive pages. **Absence of an enforced limit is not permission to hammer it.**

- keep at least 0.4 s between paged requests
- send a real `User-Agent` with a working contact address
- cache every raw response so a re-run never re-fetches
- the snapshot is bounded and immutable by design, not a continuous crawl

## Enforcement

This document is a contract, not a preference. Task C3 requires a test asserting no outbound write is possible. Task D4 requires a secret scan with zero findings and a CC BY-SA attribution audit across every redistributed artifact. If a future feature needs any capability marked forbidden above, the feature is wrong, not this file.
