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

/** The repository this console is built from, named once. */
const REPO = "https://github.com/Kesav2k04/tracetriage-august-2026";

export default function Colophon({
  attribution,
  snapshot,
  gatesMet,
  gatesTotal,
  receiptCount,
  receiptBytes,
}: {
  attribution: string;
  snapshot: string;
  gatesMet: number;
  gatesTotal: number;
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
              A review-value queue for SatNOGS waterfalls, and the measurements
              that decide whether it is worth a reviewer&rsquo;s time. Two of the
              six gates it set itself were met; three came back inconclusive and
              one was never run. All six are on the record.
            </p>
          </section>

          <section>
            <h2>What it is made of</h2>
            <ul>
              <li>Static export, no server and no database</li>
              <li>{receiptCount} receipts, {(receiptBytes / 1024 / 1024).toFixed(1)} MB, committed</li>
              <li>Snapshot <span className="mono">{snapshot}</span>, frozen before fitting</li>
              <li>
                {gatesMet} of {gatesTotal} gates met, counted from the receipts
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
          <p>
            Prose and every figure set in IBM Plex, self-hosted from this origin.
            Page titles in Neue Haas Grotesk Display and small labels in DIN 2014
            Narrow, both licensed and served from Adobe Fonts, which is the one
            third-party origin this site requests and the reason its content
            security policy names two hosts. Nothing that carries a measurement
            depends on that request: both licensed faces sit in front of a Plex
            fallback, so a blocked kit costs the lettering and not the reading.
            Colour from the IBM Carbon Gray 100 theme, with one documented
            departure where Carbon&rsquo;s own token failed a contrast
            requirement.
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
