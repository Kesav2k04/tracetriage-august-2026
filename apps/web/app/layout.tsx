import type { Metadata } from "next";

// IBM Plex, self-hosted, latin subset only, at the three weights this console
// actually sets. Carbon's typeface served from the console's own origin, so every
// word of running prose and every digit of every measurement paints without a
// third-party request and without waiting on anyone else being up.
//
// The display and label faces are the one exception, and they are licensed rather
// than free, so they cannot be self-hosted: Adobe's terms of use forbid serving
// the files from another origin. They are loaded from the kit in <head> below.
// The split is deliberate and it is the whole reason the trade is worth making:
//
//   prose and every number  ->  Plex Sans, Plex Mono, same origin, no dependency
//   display headings        ->  Neue Haas Grotesk Display, third-party
//   technical labels        ->  DIN 2014 Narrow, third-party
//
// If the kit never loads, the page is still complete. Both third-party faces sit
// in front of a Plex fallback in the same token, so a reader on a blocked network
// or a cold cache gets the console in Plex rather than a page with holes in it.
// Nothing that carries a measurement depends on a request leaving this origin.
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./globals.css";
import Rail from "@/components/Rail";
import Colophon from "@/components/Colophon";
import { cards, provenance } from "@/lib/data";

export const metadata: Metadata = {
  title: {
    default: "TraceTriage",
    template: "%s — TraceTriage",
  },
  description:
    "A review-value queue for SatNOGS waterfalls, with the measurements that "
    + "decide whether it is worth a reviewer's time, including the ones that "
    + "did not establish what they set out to.",
  metadataBase: new URL("https://tracetriage.vercel.app"),
  openGraph: {
    title: "TraceTriage",
    description:
      "A review-value queue for SatNOGS waterfalls, and the gates it passed and failed.",
    type: "website",
  },
  robots: { index: true, follow: true },
};

// Read once at build time, in the server layout, and handed to the rail as plain
// numbers. The rail needs the current path so it has to be a client component, and
// a client component that imported this data would pull every receipt across the
// bundle boundary with it.
const gateSummary = provenance.gate_summary;
const chronological = provenance.splits.find((s) => s.name === "chronological");
const observationCount = chronological
  ? Object.values(chronological.counts).reduce((a, b) => a + b, 0)
  : 0;
const receiptBytes = provenance.receipts.reduce((sum, r) => sum + r.bytes, 0);

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        {/* The handshake to the font origin costs a DNS lookup and a TLS
            negotiation, and it is on the critical path for the display face.
            Starting it before the stylesheet is parsed overlaps that cost with
            the rest of the document instead of queueing behind it. */}
        <link rel="preconnect" href="https://use.typekit.net" crossOrigin="" />
        {/* Adobe Fonts kit iie4ixd. The kit itself @imports p.typekit.net for
            usage reporting, which is why the content security policy in
            vercel.json names two hosts rather than one: the second host is not in
            this markup and cannot be found by reading it. Both are declared on
            the provenance page as named third-party origins. */}
        <link
          rel="stylesheet"
          href="https://use.typekit.net/iie4ixd.css"
        />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <div className="layout">
          <Rail
            status={{
              snapshot: provenance.snapshot_id,
              gatesMet: gateSummary.n_met,
              gatesTotal: gateSummary.n_gates,
              observations: observationCount,
            }}
          />
          <main id="main" tabIndex={-1}>
            {children}
            <Colophon
              attribution={cards.attribution}
              snapshot={provenance.snapshot_id}
              gatesMet={gateSummary.n_met}
              gatesTotal={gateSummary.n_gates}
              receiptCount={provenance.receipts.length}
              receiptBytes={receiptBytes}
            />
          </main>
        </div>
      </body>
    </html>
  );
}
