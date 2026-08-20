"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import Icon, { type IconName } from "./Icon";

/**
 * The side rail.
 *
 * A client component, because marking the active section needs the current path.
 * It therefore takes its status values as plain props rather than importing the
 * data layer: importing one label from `lib/data` is what previously pulled all
 * four receipt files across the client boundary and put the queue route at 306 kB.
 * Everything here is a string or a number the server already had.
 */

/**
 * Every route this console has, in reading order.
 *
 * Two were missing for the whole build. `/agent/` and `/precedent/` existed, returned
 * 200, were described in the README as two of six pages, and could not be reached from
 * anywhere on the site: `components/Nav.tsx` listed all six and was imported by nothing,
 * while this list, the one that renders, had four. A route a reader cannot navigate to is
 * a route that does not exist for them.
 *
 * `tests/test_console_routes.py` fails if a page under `apps/web/app` is not listed here.
 */
const LINKS: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Queue", icon: "queue" },
  // Second, not last. This is the only page on the console that measures rather than
  // reports, and it was the answer to the fair criticism of everything else here: a
  // queue over a frozen corpus is an exhibit. A reader who never scrolls the rail
  // would never find it, and a route nobody can reach does not exist for them.
  { href: "/live/", label: "Live", icon: "live" },
  { href: "/evaluation/", label: "Evaluation", icon: "evaluation" },
  { href: "/agent/", label: "Agent", icon: "agent" },
  { href: "/precedent/", label: "Precedent", icon: "precedent" },
  // "Replay" named this page after the statistical replay of one ordering against
  // another, and pointed a reader at the wrong thing: the pass playback, the one
  // control on the site that moves four instruments at once, is on an observation
  // page and not here. This page is the baseline comparison, so it says so.
  { href: "/replay/", label: "Baselines", icon: "replay" },
  { href: "/provenance/", label: "Provenance", icon: "provenance" },
];

export type RailStatus = {
  snapshot: string;
  gatesMet: number;
  gatesTotal: number;
  observations: number;
};

export default function Rail({ status }: { status: RailStatus }) {
  const pathname = usePathname();

  return (
    <div className="rail">
      <div className="rail-inner">
        <Link href="/" className="rail-mark">
          {/* The mark, inline rather than an asset: 500 bytes in the document costs no
              request and cannot arrive after the wordmark it belongs to. It is the same
              figure as app/icon.svg and the same figure the whole project is about, which
              is the reason it is a diagram and not a monogram. Time runs down, frequency
              runs across; the dashed line is the frequency the station was commanded to
              receive on, the curve is where an uncorrected capture actually lands, and the
              gap between them is what every number on this site measures.

              currentColor for the commanded line, so the mark inherits the rail's ink and
              the two never disagree. The trace keeps the accent, because it is the thing
              being measured rather than part of the interface. */}
          <svg
            className="rail-glyph"
            viewBox="0 0 32 32"
            width="24"
            height="24"
            aria-hidden="true"
            focusable="false"
          >
            <rect
              x="0.6"
              y="0.6"
              width="30.8"
              height="30.8"
              rx="5"
              fill="var(--surface-raised)"
              stroke="var(--border-subtle)"
            />
            <path
              d="M19.8 6 C 19 12.6, 9.8 19.4, 9 26 L 14.2 26 C 15 19.4, 24.2 12.6, 25 6 Z"
              fill="var(--ui-02)"
            />
            <line
              x1="16"
              y1="5"
              x2="16"
              y2="27"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeDasharray="2.6 2.4"
              opacity="0.62"
            />
            <path
              d="M22.4 6 C 21.6 12.6, 12.4 19.4, 11.6 26"
              fill="none"
              stroke="var(--interactive-04)"
              strokeWidth="3.1"
              strokeLinecap="round"
            />
          </svg>
          <span className="rail-wordmark">
            <span>Trace</span>Triage
          </span>
        </Link>

        <nav className="rail-nav" aria-label="Sections">
          <ul>
            {LINKS.map((link) => {
              // An observation page belongs to the queue section.
              const active =
                link.href === "/"
                  ? pathname === "/" || pathname.startsWith("/observation")
                  : pathname.startsWith(link.href);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="rail-link"
                    aria-current={active ? "page" : undefined}
                  >
                    <Icon name={link.icon} />
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* The three things a reader checks a claim against, on every page. The
            gate tally counts gates met out of gates asked, and four of them were
            not met, so the number is deliberately not a score. */}
        <dl className="rail-status">
          <div>
            <dt>Snapshot</dt>
            <dd>{status.snapshot}</dd>
          </div>
          <div>
            <dt>Observations</dt>
            <dd>{status.observations.toLocaleString("en-GB")}</dd>
          </div>
          <div>
            <dt>Gates met</dt>
            <dd>
              {status.gatesMet} of {status.gatesTotal}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
