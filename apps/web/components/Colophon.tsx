/**
 * The colophon.
 *
 * Four columns rather than a row of links, because three of the four things worth
 * saying at the bottom of this site are not navigation. The licence term belongs
 * here at a size a reader can actually read: CC BY-SA 4.0 requires attribution,
 * and attribution set in 10px grey at the end of a flex row is a compliance
 * gesture rather than compliance.
 *
 * A server component. It takes the attribution string from the card export rather
 * than restating it, so the licence text on the page is the one the pipeline
 * recorded against the imagery it actually downloaded.
 */

import Link from "next/link";

/** The repository this console is built from, named once. */
const REPO = "https://github.com/Kesav2k04/tracetriage-august-2026";

export default function Colophon({
  attribution,
  snapshot,
  gatesMet,
  gatesTotal,
  gatesPrePassed,
  receiptCount,
  receiptBytes,
}: {
  attribution: string;
  snapshot: string;
  gatesMet: number;
  gatesTotal: number;
  /**
   * How many of the met gates are PRE_PASSED feasibility checks.
   *
   * This paragraph said "two of the six gates were met" and stopped, which is the
   * flattering reading: both met gates asked whether the project was feasible at all
   * and were answered before the first line of pipeline code. A judge-seat review
   * named it as the place the console rounds up while `README.md` says it plainly.
   */
  gatesPrePassed: number;
  receiptCount: number;
  receiptBytes: number;
}) {
  return (
    <footer className="colophon">
      <div className="shell">
        <div className="colophon-grid">
          <section>
            <h2>What this is</h2>
            <p>
              A review-value queue for SatNOGS waterfalls, ranking which satellite
              passes are worth a reviewer&rsquo;s time, with the measurements that say
              how much. The {gatesTotal} kill gates it set itself are a research bar and
              all {gatesTotal} are on the record: {gatesMet} met,{" "}
              {gatesPrePassed === gatesMet ? "both" : String(gatesPrePassed)} of those
              feasibility checks answered before any pipeline code existed.{" "}
              <Link href="/start/">Start here</Link>.
            </p>
          </section>

          <section>
            <h2>What it is made of</h2>
            <ul>
              <li>Static export, no server and no database</li>
              <li>{receiptCount} receipts, {(receiptBytes / 1024 / 1024).toFixed(1)} MB, committed</li>
              <li>Snapshot <span className="mono">{snapshot}</span>, frozen before fitting</li>
              <li>
                {gatesMet} of {gatesTotal} gates met, counted from the receipts, and{" "}
                {gatesPrePassed} of them pre-passed
              </li>
            </ul>
          </section>

          <section>
            <h2>What it will not do</h2>
            <ul>
              <li>Run a model in the browser</li>
              <li>Request any data from another origin</li>
              <li>Set a cookie, or store anything at all</li>
              <li>Compute a number the receipts do not contain</li>
            </ul>
          </section>

          <section>
            <h2>Data and licence</h2>
            <p>{attribution}</p>
            <p>
              <a href="https://network.satnogs.org/">SatNOGS Network</a>
              {" · "}
              <a href="https://creativecommons.org/licenses/by-sa/4.0/">
                CC BY-SA 4.0
              </a>
            </p>
          </section>
        </div>

        <div className="colophon-rule">
          {/* 191 words became 62, on every page.
              This paragraph carried the whole typography and colour argument: which
              faces, which origin, the Plex fallback, the greyscale measurement, the
              OKLCH re-expression of Carbon's ramp, the contrast delta it costs, the
              colourmap the accents come off, and the two documented departures. All of
              it is true and none of it is about satellites. It appeared eight times, at
              the foot of a page a reader had reached by wanting something else, and the
              provenance page carries the long version with the numbers.

              What stays is the claim a reader might act on, which is that a blocked font
              host costs nothing that carries a measurement, and the one fact that changes
              how the plates are read: grey means measured. */}
          <p>
            Every waterfall here is greyscale to within 1 part in 255, so grey means
            measured and every coloured mark is something the pipeline computed. The
            ground is black because the sky between passes is.{" "}
            <Link href="/provenance/">The derivation, with its numbers</Link>.
          </p>
          {/* Both forms of each document.
              The served copy is markdown source, and a browser shows 54 KB of pipe
              tables at full width, which is not a document a judge can read. The
              rendered view is on the repository, which is where a reader who wants
              the file itself is going anyway. The raw link stays because the console
              has to keep working when the repository is not reachable, and because a
              rendered page is a second copy of a file this project checks byte for
              byte. */}
          <p>
            {/* First in the row, and it points at this site rather than at GitHub now.
                A judge who arrives at the deployed URL had one signposted way into the
                page written for them and it was a link off the console into a markdown
                file. /start/ is the same map on the console, generated from the same
                receipts. The repository copy keeps its place beside it, for a reader who
                is in the repository anyway. */}
            <Link href="/start/">
              <b>Start here</b>
            </Link>
            {" · "}
            <a href={`${REPO}/blob/main/FOR_JUDGES.md`}>For judges</a>
            {" · "}
            <a href={`${REPO}/blob/main/docs/KILL_GATE.md`}>Gates</a>{" "}
            <a href="/data/KILL_GATE.md" className="colophon-raw">
              (raw)
            </a>
            {" · "}
            <a href={`${REPO}/blob/main/docs/CLAIM_REGISTER.md`}>Claims</a>{" "}
            <a href="/data/CLAIM_REGISTER.md" className="colophon-raw">
              (raw)
            </a>
            {" · "}
            <a href={`${REPO}/blob/main/docs/C2_PREREGISTRATION.md`}>
              Pre-registration
            </a>{" "}
            <a href="/data/C2_PREREGISTRATION.md" className="colophon-raw">
              (raw)
            </a>
            {" · "}
            {/* The presentation film, on the repository rather than served from here.
                It is 4.6 MB, and a second copy in the export would be 4.6 MB the
                release audit weighs twice for one artifact. A judge who arrives at the
                deployed URL had no signposted way to it at all, which is the worse of
                the two problems: a film nothing links to is a film nobody watches. */}
            <a href={`${REPO}/blob/main/presentation/out/tracetriage-film.mp4`}>
              Film
            </a>
            {" · "}
            <a href={REPO}>Repository</a>
          </p>
        </div>
      </div>
    </footer>
  );
}
