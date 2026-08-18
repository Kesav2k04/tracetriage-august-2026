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

const LINKS: { href: string; label: string; icon: IconName }[] = [
  { href: "/", label: "Queue", icon: "queue" },
  { href: "/evaluation/", label: "Evaluation", icon: "evaluation" },
  { href: "/replay/", label: "Replay", icon: "replay" },
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
          <span>Trace</span>Triage
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
