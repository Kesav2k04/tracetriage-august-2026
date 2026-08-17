/**
 * Shared presentational pieces.
 *
 * Small on purpose. The console's job is to put measurements in front of a
 * reader without adding a layer of interpretation, so these components format
 * and label; none of them computes anything.
 */
import type { ReactNode } from "react";

import { verdictColour } from "@/lib/format";

export function Section({
  title,
  description,
  children,
  id,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section id={id} style={{ marginTop: "var(--sp-09)" }}>
      <h2
        style={{
          fontSize: "var(--type-heading-03)",
          marginBottom: description ? "var(--sp-03)" : "var(--sp-05)",
        }}
      >
        {title}
      </h2>
      {description && (
        <p
          style={{
            margin: "0 0 var(--sp-05)",
            maxWidth: "58rem",
            color: "var(--text-02)",
            lineHeight: 1.6,
          }}
        >
          {description}
        </p>
      )}
      {children}
    </section>
  );
}

export function VerdictBadge({
  verdict,
  size = "normal",
}: {
  verdict: string;
  size?: "normal" | "large";
}) {
  const colour = verdictColour(verdict);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--sp-03)",
        padding:
          size === "large" ? "var(--sp-03) var(--sp-05)" : "var(--sp-01) var(--sp-03)",
        border: `1px solid ${colour}`,
        color: colour,
        fontSize:
          size === "large" ? "var(--type-body-long)" : "var(--type-caption)",
        fontWeight: 600,
        letterSpacing: "0.04em",
        whiteSpace: "nowrap",
      }}
    >
      <span
        aria-hidden="true"
        style={{
          width: size === "large" ? 10 : 7,
          height: size === "large" ? 10 : 7,
          background: colour,
          borderRadius: "50%",
        }}
      />
      {verdict.replace(/_/g, " ")}
    </span>
  );
}

export function Tag({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "action" | "muted";
  title?: string;
}) {
  const palette = {
    neutral: { fg: "var(--text-02)", bd: "var(--border-strong)" },
    action: { fg: "#4589ff", bd: "#4589ff" },
    muted: { fg: "var(--text-03)", bd: "var(--border-subtle)" },
  }[tone];

  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        padding: "1px var(--sp-03)",
        border: `1px solid ${palette.bd}`,
        color: palette.fg,
        fontSize: "var(--type-caption)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/** A number with its label and, where there is one, the count behind it. */
export function Stat({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: string;
}) {
  return (
    <div
      style={{
        padding: "var(--sp-05)",
        background: "var(--ui-01)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      <div
        style={{
          fontSize: "var(--type-label)",
          color: "var(--text-03)",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: "var(--type-heading-04)",
          marginTop: "var(--sp-02)",
          color: tone ?? "var(--text-01)",
          lineHeight: 1.2,
        }}
      >
        {value}
      </div>
      {detail && (
        <div
          style={{
            fontSize: "var(--type-caption)",
            color: "var(--text-02)",
            marginTop: "var(--sp-02)",
            lineHeight: 1.5,
          }}
        >
          {detail}
        </div>
      )}
    </div>
  );
}

/**
 * An interval drawn against its threshold.
 *
 * The whole point of this console is that a point estimate is not a result, so
 * the interval is the figure and the point estimate is a mark inside it. A bar
 * that showed only the point estimate would make gate 6 look like a pass.
 */
export function IntervalBar({
  low,
  high,
  point,
  threshold,
  domain,
  label,
}: {
  low: number;
  high: number;
  point: number;
  threshold: number;
  domain: [number, number];
  label: string;
}) {
  const [min, max] = domain;
  const span = max - min || 1;
  const pct = (value: number) => ((value - min) / span) * 100;
  const clears = low > threshold;
  const refuted = high < threshold;
  const colour = clears
    ? "var(--verdict-passed)"
    : refuted
      ? "var(--verdict-failed)"
      : "var(--verdict-not-established)";

  return (
    <div>
      <div
        style={{
          position: "relative",
          height: "2.25rem",
          background: "var(--ui-01)",
          border: "1px solid var(--border-subtle)",
        }}
        role="img"
        aria-label={
          `${label}: 95% interval from ${low.toFixed(3)} to ${high.toFixed(3)}, ` +
          `point estimate ${point.toFixed(3)}, threshold ${threshold}. ` +
          (clears
            ? "The interval clears the threshold."
            : refuted
              ? "The interval lies below the threshold."
              : "The interval contains the threshold.")
        }
      >
        <div
          style={{
            position: "absolute",
            left: `${pct(low)}%`,
            width: `${Math.max(pct(high) - pct(low), 0.6)}%`,
            top: "0.5rem",
            bottom: "0.5rem",
            background: colour,
            opacity: 0.32,
            border: `1px solid ${colour}`,
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `${pct(point)}%`,
            top: "0.25rem",
            bottom: "0.25rem",
            width: 2,
            background: colour,
            transform: "translateX(-1px)",
          }}
        />
        <div
          style={{
            position: "absolute",
            left: `${pct(threshold)}%`,
            top: 0,
            bottom: 0,
            width: 1,
            background: "var(--text-01)",
            transform: "translateX(-0.5px)",
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "var(--type-caption)",
          color: "var(--text-03)",
          marginTop: "var(--sp-02)",
        }}
      >
        <span className="num">{min.toFixed(1)}</span>
        <span>
          threshold <span className="num">{threshold.toFixed(1)}</span>
        </span>
        <span className="num">{max.toFixed(1)}</span>
      </div>
    </div>
  );
}

export function Note({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warn" | "limit";
}) {
  const colour = {
    info: "var(--support-04)",
    warn: "var(--support-03)",
    limit: "var(--text-03)",
  }[tone];
  return (
    <p
      style={{
        margin: "var(--sp-05) 0 0",
        padding: "var(--sp-04) var(--sp-05)",
        borderLeft: `3px solid ${colour}`,
        background: "var(--ui-01)",
        color: "var(--text-02)",
        lineHeight: 1.6,
        maxWidth: "58rem",
      }}
    >
      {children}
    </p>
  );
}

export function Table({
  head,
  children,
  caption,
}: {
  head: ReactNode[];
  children: ReactNode;
  caption?: string;
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "var(--type-body)",
        }}
      >
        {caption && (
          <caption
            style={{
              captionSide: "bottom",
              textAlign: "left",
              paddingTop: "var(--sp-04)",
              fontSize: "var(--type-caption)",
              color: "var(--text-03)",
            }}
          >
            {caption}
          </caption>
        )}
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th
                key={index}
                scope="col"
                style={{
                  textAlign: index === 0 ? "left" : "right",
                  padding: "var(--sp-03) var(--sp-04)",
                  borderBottom: "1px solid var(--border-strong)",
                  color: "var(--text-03)",
                  fontSize: "var(--type-label)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  fontWeight: 400,
                  whiteSpace: "nowrap",
                }}
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Cell({
  children,
  align = "right",
  mono = false,
  header = false,
}: {
  children: ReactNode;
  align?: "left" | "right";
  mono?: boolean;
  header?: boolean;
}) {
  const Component = header ? "th" : "td";
  return (
    <Component
      scope={header ? "row" : undefined}
      className={mono ? "num" : undefined}
      style={{
        textAlign: align,
        padding: "var(--sp-03) var(--sp-04)",
        borderBottom: "1px solid var(--border-subtle)",
        fontWeight: header ? 400 : undefined,
        color: header ? "var(--text-01)" : "var(--text-02)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </Component>
  );
}
