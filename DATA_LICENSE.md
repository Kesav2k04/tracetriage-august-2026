# Data licence and attribution

The MIT licence in `LICENSE` covers **source code only**. It does not cover the data.

## SatNOGS data: CC BY-SA 4.0

Observation metadata and waterfall artifacts come from the SatNOGS Network,
operated by the Libre Space Foundation and its volunteer station operators, and
are licensed **Creative Commons Attribution-ShareAlike 4.0 International**.

https://creativecommons.org/licenses/by-sa/4.0/

### Obligations this project accepts

Every redistributed or derived artifact carries, captured at snapshot time
because it cannot be reconstructed later:

- attribution to the SatNOGS Network
- the exact source URL of the record and of the waterfall artifact
- the retrieval timestamp in UTC
- a sha256 of the retrieved bytes
- a notice of any modification made (crop, resize, colour conversion, overlay)
- a link to the licence

**ShareAlike applies.** Anything derived from these artifacts and redistributed
is released under CC BY-SA 4.0, not under MIT. That includes cropped waterfalls,
rendered evidence cards containing a waterfall, and any published dataset of
derived annotations.

### Attribution string

    Contains data from the SatNOGS Network (https://network.satnogs.org),
    (c) SatNOGS contributors, licensed CC BY-SA 4.0
    (https://creativecommons.org/licenses/by-sa/4.0/).
    Retrieved <UTC timestamp>. Modified: <modification notice>.

## Local annotations

Annotations produced inside TraceTriage are the reviewer's own work. They are
stored locally and are never written back to SatNOGS. If a set of annotations is
ever published, it is published under CC BY-SA 4.0 alongside the observations it
describes, and clearly marked as one reviewer's opinion rather than network
consensus.

## Model weights

Any model trained on these artifacts is a derived work of a ShareAlike dataset.
Published weights ship with the same attribution and the dataset manifest that
identifies exactly which observations produced them.

## Audit

Task D4 audits attribution across every redistributed artifact. A missing source
URL, retrieval timestamp or licence line is a release blocker, not a cleanup item.
