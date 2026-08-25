import type { Metadata, Viewport } from "next";

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
import SmoothScroll from "@/components/SmoothScroll";
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
    // Drawn by scripts/build_og_image.py from the queue receipt, so the two
    // verdicts on the card are the two the console holds and cannot drift from
    // them. Without it a pasted link rendered as a bare text card, which is the
    // first thing a reader sees when a submission is shared before it is opened.
    images: [
      {
        url: "/og.png",
        width: 1200,
        height: 630,
        alt:
          "TraceTriage. A review queue, and the measurement that says how much it "
          + "is worth. Pre-registered split 1.58 times random, not established. "
          + "Held-out stations 2.25 times random, passed.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "TraceTriage",
    description:
      "A review-value queue for SatNOGS waterfalls, and the gates it passed and failed.",
    images: ["/og.png"],
  },
  robots: { index: true, follow: true },
  // Installable, with no store account on either platform. `public/manifest.webmanifest`
  // carries the name, the ground colour and three shortcuts; the icons are rasterised
  // from `app/icon.svg` by scripts/build_pwa_icons.py, so the home-screen icon is the
  // same mark as the favicon and cannot drift from the palette.
  //
  // iOS reads `apple-touch-icon` at 180 and ignores the manifest's `purpose: maskable`
  // variant, which is why there are four files rather than two. `appleWebApp.capable`
  // is what makes an Add to Home Screen launch open without Safari's chrome.
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "TraceTriage",
    statusBarStyle: "black-translucent",
  },
  icons: {
    // Naming `apple` here suppresses Next's `app/icon.svg` file convention, so the export
    // shipped no `rel="icon"` at all and every cold load fell back to a `/favicon.ico`
    // this site does not serve: one 404 in the console on a first visit. Both are named.
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = {
  // The same value as the manifest's `theme_color` and `--ui-background`. It colours the
  // address bar on Android and the status bar area of an installed launch, so a mismatch
  // shows up as a band of the wrong grey above the page.
  themeColor: "#0c0e12",
};

// Read once at build time, in the server layout, and handed to the rail as plain
// numbers. The rail needs the current path so it has to be a client component, and
// a client component that imported this data would pull every receipt across the
// bundle boundary with it.
const gateSummary = provenance.gate_summary;
// How many met gates were pre-passed, so the colophon can say which kind they are
// rather than printing a tally that reads better than the result.
const gatesPrePassed = gateSummary.gates.filter(
  (gate) => gate.verdict === "PRE_PASSED",
).length;
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
            the rest of the document instead of queueing behind it.

            It is not what holds the first paint, and the measurement is written
            down here so nobody spends another hour on this line. Five interleaved
            rounds, fresh browser each, against the built export on a local server:
            956 ms to first contentful paint as served, 152 ms with this host
            blocked, 944 ms with the self-hosted faces blocked instead. A second
            preconnect changed nothing, because there was already one. The cost is
            `font-display`, which belongs to a stylesheet this project does not
            write: the kit declares 72 of its 90 faces `auto`, so Chrome holds
            text unpainted while `neue-haas-grotesk-display` and `din-2014-narrow`
            load, and no query parameter on the kit URL overrides it. The two
            self-hosted faces are `swap` and hold nothing, which is the whole
            difference. `apps/web/audit/paint-probe.js` reports which families are
            set to block, so this cannot regress unnoticed. */}
        <link rel="preconnect" href="https://use.typekit.net" crossOrigin="" />
        {/* Adobe Fonts kit iie4ixd, loaded so that it cannot hold the first paint.

            The note above used to end by saying the fix was one setting in the
            Adobe Fonts web project and that there was no substitute for it. The
            setting was applied and it is not enough: the kit now serves 18 faces
            at `swap` and 72 at `auto`, and the 18 are `acumin-pro`, a family this
            console does not use. Both faces it does use are still `auto`. So the
            sentence was right about CSS and wrong about the browser, because
            `font-display` is not the only lever on the sequence it controls.

            What happens here instead. The stylesheet is appended by script at
            `media="print"`, which fetches it without blocking the render, and the
            media flips to `all` once it has arrived. That on its own would be
            worse than the problem: the moment the kit's rules apply, every heading
            resolves to a family that has not downloaded, `auto` starts its block
            period, and text that had already painted goes invisible mid-read. So
            the licensed families are not in `--font-display` or `--font-label` at
            all. They arrive with the `fonts-ready` class in `globals.css`, added
            only once `document.fonts.load` has resolved for every face this
            console renders, which is the sequence `swap` would have produced: Plex
            paints at once, the licensed face replaces it in one reflow, and no
            text is ever invisible.

            The faces are named rather than discovered, because a weight that is
            not loaded before the class lands is a weight that blocks. Three is the
            whole set and it is measured rather than assumed: across all eight
            pages, `apps/web/audit/font-swap-probe.js` finds exactly
            `neue-haas-grotesk-display 500`, `din-2014-narrow 600` and
            `din-2014-narrow 400` rendered anywhere. The first version of this list
            had the display face at 400 instead of the label face at 400, which is
            how the probe earns its place: both lists are three names long, both
            leave every page looking correct, and one of them lets a caption go
            invisible after the reader has started reading. `data-fonts` on the
            root element is the list this script actually loaded, so the probe
            compares what a page renders against what was waited for rather than
            against a copy of this array that could drift from it.

            Without JavaScript the class never lands and the console stays in Plex.
            That is the state a blocked kit already produced, it is what the
            fallback in each token was written for, and nothing carrying a
            measurement uses either licensed face.

            The kit @imports p.typekit.net for usage reporting, which is why the
            content security policy in vercel.json names two hosts rather than one:
            the second host is not in this markup and cannot be found by reading
            it. Both are declared on the provenance page as named third-party
            origins. */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){var F=["
              + "'500 1em \"neue-haas-grotesk-display\"',"
              + "'600 1em \"din-2014-narrow\"',"
              + "'400 1em \"din-2014-narrow\"'"
              + "];var h=document.documentElement;"
              + "var l=document.createElement('link');"
              + "l.rel='stylesheet';l.href='https://use.typekit.net/iie4ixd.css';"
              + "l.media='print';l.onload=function(){l.media='all';"
              + "var f=document.fonts;if(!f||!f.load){return}"
              + "Promise.all(F.map(function(s){"
              + "return f.load(s).catch(function(){})})).then(function(){"
              + "h.setAttribute('data-fonts',F.join('|'));"
              + "h.classList.add('fonts-ready')})};"
              + "document.head.appendChild(l)})();",
          }}
        />
      </head>
      <body>
        {/* Renders nothing. It normalises the wheel step so a plot stays trackable while
            the page moves, and it removes itself for a reader who has asked for reduced
            motion, for every key the platform owns, and for in-page links. */}
        <SmoothScroll />
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
              gatesPrePassed={gatesPrePassed}
              receiptCount={provenance.receipts.length}
              receiptBytes={receiptBytes}
            />
          </main>
        </div>
        {/* Register the service worker, and only in a built export.

            `process.env.NODE_ENV` is inlined at build time, so `next dev` emits no script
            at all. That is deliberate rather than tidy: the worker answers `/_next/static/`
            from cache first, which is correct for a production build where those names
            carry a content hash and are served `immutable`, and wrong under the dev server
            where the same paths are rebuilt in place.

            On `load` rather than inline, so it competes with nothing on the critical path.
            A first visit is never faster for this; the second one is the point. There is
            no update prompt and no reload nag, because documents are network-first: a
            reader online is reading what the deployment currently serves, worker or not.

            CSP: `worker-src` is not set in vercel.json, so this falls back to `script-src
            'self'`, which a same-origin worker satisfies. */}
        {process.env.NODE_ENV === "production" && (
          <script
            dangerouslySetInnerHTML={{
              __html:
                "if('serviceWorker' in navigator){addEventListener('load',function(){"
                + "navigator.serviceWorker.register('/sw.js').catch(function(){})})}",
            }}
          />
        )}
      </body>
    </html>
  );
}
