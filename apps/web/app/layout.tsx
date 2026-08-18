import type { Metadata } from "next";

// IBM Plex, self-hosted, latin subset only, at the three weights this console
// actually sets. Carbon's typeface served from the console's own origin: there is
// no font request to a third party, so the content security policy stays closed
// and the page has no runtime dependency on anyone else being up.
//
// The display face is a token, not an import. --font-display currently falls back
// to Plex Sans; pointing it at an Adobe Fonts kit is a one-line change in
// globals.css plus a <link> here, and it would be the only third-party request on
// the site, which is a trade this console has so far declined to make.
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
