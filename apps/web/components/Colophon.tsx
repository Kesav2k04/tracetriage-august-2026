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
              how much. <Link href="/start/">Start here</Link>.
            </p>
            {/* The challenge theme, and it was on one page of nine.
                A judge scoring Challenge Fit was relying on reaching /start to find the
                theme named at all. It is one line and it belongs in the chrome. */}
            <p className="colophon-theme">
              Built for Advance Space Exploration with AI.
            </p>
          </section>

          <section>
            <h2>What it is made of</h2>
            <ul>
              {/* IBM Bob and Granite were named on one page of nine, and "effective
                  use of IBM Bob and additional technologies" is the first clause of the
                  most heavily weighted criterion. Both are named here, in chrome every
                  page carries, with the build log a click away. */}
              <li>
                Built with IBM Bob, with a dated build log:{" "}
                <Link href="/start/">what it built and what failed first</Link>
              </li>
              <li>
                IBM Granite over Ollama on one machine, with{" "}
                <Link href="/agent/">a no-tools control</Link>
              </li>
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
            {/* The author, last so the two lines above keep saying whose data this
                is before this one says who built the thing that reads it. The name
                was in the repository URL and nowhere a reader could see it, which
                is a byline only for someone who hovers a link. No class: the
                surrounding `.colophon p` rule is the style it should have. */}
            <p>Built by Kesav Kumar Jayakumar.</p>
          </section>
        </div>

        <div className="colophon-rule">
          {/* 62 words became 0, on every page.
              The cut before this one took the typography argument down to the two facts
              a reader might act on, and one of those was still in the wrong place: how
              a waterfall is encoded is a fact about the plate, not about the console,
              and it was being restated at the foot of nine pages a reader had reached by
              wanting something else. It now sits beside the first waterfall on the
              landing page, once, where a reader is actually looking at one.
              The link stays. It is the route to the long version and to every number in
              it. */}
          <p>
            <Link href="/provenance/">
              How every number here was generated, and what this console will not do
            </Link>
            .
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
            <a href={REPO}>Repository</a>
          </p>
        </div>
      </div>
    </footer>
  );
}
