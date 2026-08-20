/**
 * Measure a pass that was recorded after this project was built.
 *
 * Every other page on this console reports a number that was measured weeks ago and
 * frozen. That is what makes them checkable, and it is also the fair criticism of the
 * whole thing: a queue over a corpus is an exhibit, and a volunteer network records
 * another nine thousand observations while you read it.
 *
 * This page closes that gap in the only honest way a static export can. It has two
 * halves and they are labelled, because they are not the same claim.
 *
 * The form measures now. It posts one observation id to `api/live.py`, a read-only
 * endpoint that calls the same `live.triage` the CLI calls, which downloads the
 * published waterfall, propagates the pass from the TLE in the observation's own record,
 * reads the frequency axis off the tick labels, decides whether the capture was
 * Doppler-corrected, fits the offset and scores it against permuted nulls. Tens of
 * seconds, no GPU, no credential, nothing written anywhere.
 *
 * The shelf is frozen. Six observations recorded after the snapshot, measured the same
 * way at the time each entry records, baked into this build. It exists because a cold
 * serverless start plus a volunteer-run API is two things that have to be fast at once,
 * and a demo that needs both is a demo that fails in front of somebody. The shelf is the
 * floor. It is not the product, and the copy says so rather than letting a reader think
 * the buttons are live.
 */
import type { Metadata } from "next";

import LiveConsole from "@/components/LiveConsole";
import shelfJson from "@/public/data/live_shelf.json";

export const metadata: Metadata = {
  title: "Measure a pass recorded today",
  description:
    "Paste a SatNOGS observation id and measure its Doppler corridor, offset in ppm " +
    "and null-distribution p value, with provenance, from the same function the CLI " +
    "runs.",
};

type ShelfFile = {
  built_at_utc: string;
  snapshot_cutoff_utc: string;
  n_observations: number;
  n_decisive: number;
  engine: { function: string; n_nulls: number };
  observations: unknown[];
};

const shelf = shelfJson as unknown as ShelfFile;

export default function LivePage() {
  return (
    <div className="shell live-shell">
      <header className="live-head">
        <p className="eyebrow">
          <span className="live-dot" aria-hidden="true" /> Live measurement
        </p>
        <h1 className="live-title">
          Measure a pass <em>recorded today</em>
        </h1>
        <p className="live-lede">
          Everything else on this console was measured in August and frozen so it could be
          checked. This one runs now. Paste any public SatNOGS observation id, including
          one recorded in the last hour, and the same function the command line calls will
          download its waterfall, propagate the pass from the elements in its own record,
          read the frequency axis off the tick labels, decide whether the station
          corrected for Doppler, fit the offset and score it against permuted nulls.
        </p>
        <p className="live-lede live-lede-quiet">
          Read-only, no credential, no GPU, and nothing is written to SatNOGS or anywhere
          else. Three outcomes are normal and distinct: an uncorrected capture gets an
          offset and a p value, a corrected one gets an offset with no null test, and an
          image that does not settle which gets <span className="mono">UNRESOLVED</span>,
          which on a real queue is the common case and is the answer that says skip this
          one.
        </p>
      </header>

      <LiveConsole
        shelf={shelf.observations}
        builtAt={shelf.built_at_utc}
        snapshotCutoff={shelf.snapshot_cutoff_utc}
        nNulls={shelf.engine.n_nulls}
        nDecisive={shelf.n_decisive}
      />
    </div>
  );
}
