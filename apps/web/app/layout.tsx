import type { Metadata } from "next";

// IBM Plex, self-hosted, latin subset only, at the three weights this console
// actually sets. Carbon's typeface served from the console's own origin: there is
// no font request to a third party, so the content security policy stays closed
// and the page has no runtime dependency on anyone else being up.
import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "./globals.css";
import Nav from "@/components/Nav";

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
        <Nav />
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <footer
          style={{
            marginTop: "var(--sp-12)",
            borderTop: "1px solid var(--border-subtle)",
            padding: "var(--sp-07) 0 var(--sp-09)",
          }}
        >
          <div
            className="shell"
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: "var(--sp-06)",
              justifyContent: "space-between",
              fontSize: "var(--type-caption)",
              color: "var(--text-03)",
            }}
          >
            <p style={{ margin: 0, maxWidth: "38rem" }}>
              Observation data and waterfall imagery from the SatNOGS Network,
              contributed by volunteer ground stations, under CC BY-SA 4.0. This
              console is static: no server, no database, no cloud inference and no
              credentials. Every number it shows was measured offline and
              validated against a contract before it reached disk.
            </p>
            <p style={{ margin: 0 }}>
              <a href="https://network.satnogs.org/">SatNOGS Network</a>
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
