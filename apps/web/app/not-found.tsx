/**
 * The 404, in this console's own shell.
 *
 * Next ships a stock page whose injected style is `body{color:#000;background:#fff}`
 * with a `prefers-color-scheme: dark` branch. This app sets no `color-scheme`, so on
 * a machine in light mode the stock page painted a white content area inside the dark
 * chrome, with no link back to anything. A judge who mistypes a route, or follows a
 * link to an observation that is not one of the twenty-five the console ships, landed
 * on a page that looked broken rather than one that said what happened.
 *
 * This is a server component with no data of its own beyond the showcase list, which
 * is what makes it useful: the most likely way to reach it is an observation id that
 * exists in the corpus and was not built, so the page offers the ones that were.
 */
import Link from "next/link";

import { showcaseIds } from "@/lib/data";

export const metadata = { title: "Not found" };

export default function NotFound() {
  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "52rem" }}>
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--type-label)",
            letterSpacing: "var(--tracking-label)",
            textTransform: "uppercase",
            color: "var(--text-03)",
          }}
        >
          404
        </p>
        <h1 style={{ fontSize: "var(--type-heading-05)", marginTop: "var(--sp-03)" }}>
          There is no page at this address.
        </h1>
        <p
          style={{
            marginTop: "var(--sp-05)",
            color: "var(--text-02)",
            lineHeight: 1.7,
            fontSize: "var(--type-body-long)",
          }}
        >
          This console is a static export of a fixed set of pages. If you followed a
          link to an observation, the console ships {showcaseIds.length} of them with
          imagery rather than the whole corpus, so an id outside that set has no page
          even when the observation is in the dataset.
        </p>
      </header>

      <nav style={{ marginTop: "var(--sp-07)" }} aria-label="Where to go instead">
        <h2 style={{ fontSize: "var(--type-heading-03)" }}>Where to go instead</h2>
        <ul
          style={{
            marginTop: "var(--sp-05)",
            paddingLeft: "1.1rem",
            lineHeight: 2,
            color: "var(--text-02)",
          }}
        >
          <li>
            <Link href="/">The review queue</Link>, which is what this project produces
          </li>
          <li>
            <Link href="/evaluation/">Evaluation</Link>, every gate including the ones
            that did not pass
          </li>
          <li>
            <Link href="/agent/">Agent</Link> and <Link href="/precedent/">Precedent</Link>
            , the two Granite results
          </li>
          <li>
            <Link href="/replay/">Baselines</Link>, the queue against the orderings a
            reviewer could have used instead
          </li>
          <li>
            <Link href="/provenance/">Provenance</Link>, every receipt with its digest
          </li>
          <li>
            <Link href={`/observation/${showcaseIds[0]}/`}>
              Observation {showcaseIds[0]}
            </Link>
            , one pass with its waterfall, its corridor and its playback
          </li>
        </ul>
      </nav>
    </div>
  );
}
