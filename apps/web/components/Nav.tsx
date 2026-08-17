"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Queue" },
  { href: "/evaluation/", label: "Evaluation" },
  { href: "/replay/", label: "Replay" },
  { href: "/provenance/", label: "Provenance" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header
      style={{
        borderBottom: "1px solid var(--border-subtle)",
        background: "var(--ui-background)",
        position: "sticky",
        top: 0,
        zIndex: 10,
      }}
    >
      <div
        className="shell"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "var(--sp-07)",
          minHeight: "3rem",
        }}
      >
        <Link
          href="/"
          style={{
            color: "var(--text-01)",
            fontWeight: 600,
            letterSpacing: "0.02em",
          }}
        >
          TraceTriage
        </Link>

        <nav aria-label="Sections">
          <ul
            style={{
              display: "flex",
              gap: "var(--sp-06)",
              listStyle: "none",
              margin: 0,
              padding: 0,
            }}
          >
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
                    aria-current={active ? "page" : undefined}
                    style={{
                      color: active ? "var(--text-01)" : "var(--text-02)",
                      fontSize: "var(--type-body)",
                      paddingBottom: "var(--sp-02)",
                      borderBottom: active
                        ? "2px solid var(--interactive-04)"
                        : "2px solid transparent",
                    }}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
