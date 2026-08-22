# Would it keep up with the network?

The judged criteria ask about practicality and scalability, and that question has one honest
form: does the thing keep up with what SatNOGS actually produces? Every number below is
computed by `scripts/measure_throughput.py` from artifacts already in this repository and
written to `artifacts/THROUGHPUT_RECEIPT.json`, and `scripts/gate.py` re-runs it with
`--check`.

Moved out of `README.md` so the summary there stays a summary. Nothing was dropped: the four
boundaries on the measurement are the reason this page exists rather than a table.

| | Measured | Where it comes from |
|---|---|---|
| What the network produces | **6,380 observations with a waterfall per day** | the capture time each station wrote into its own object key, over 2,500 stored waterfalls spanning 9.40 hours |
| What one observation costs | **1.2576 s**, single-threaded, at the dominant stage | `artifacts/corridor_features.json`: 743 observations in 934.4 s |
| What one core therefore handles | **68,702 observations per day** | the two above, divided |
| Headroom | **10.77x on one core** | 68,702 against 6,380 |
| What ingestion costs | **1.8197 s per observation**, wall clock | `artifacts/DATASET_MANIFEST.json`: 110 API pages and 2,500 image downloads between `built_at` and `completed_at` |

**The interesting number is the last one.** Fetching an observation costs 1.45 times what
processing it does, and that cost is a 0.4-second courtesy interval between API requests
plus a 1.7 MB image download. Neither is a property of this pipeline. This is not a
project whose constraint is inference, which also names its deployment: run at the ground
station, where the waterfall is already on disk and there is no public API to be polite
to. The corridor fit is independent per observation, so the same figure holds per core.

**Four things that measurement does not cover**, stated because a scalability claim with
no boundary is not a measurement:

1. The capture span is 9.40 hours inside a single day. A day rate extrapolated from it is
   one observation of the network's rate rather than a long-run average, and SatNOGS
   volume moves with how many stations are online.
2. The 1.2576 s covers the corridor fit and the second-trace survey. SGP4 propagation,
   the fusion head's forward pass and the queue sort are all cheaper per observation and
   are not in it. Granite is not in it either, and is not per observation: it runs on
   what a reviewer opens.
3. Both stages were timed on one machine, single-threaded. The core count is a division,
   not a measured parallel speed-up.
4. Nothing here is a latency claim. The queue is a batch reading order and no part of
   this project has to answer inside a pass.
