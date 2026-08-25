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
    <section id={id} style={{ marginTop: "var(--sp-10)" }}>
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
            margin: "0 0 var(--sp-06)",
            maxWidth: "62ch",
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
  const normalised = verdict.toUpperCase();
  const dot = size === "large" ? 10 : 7;

  // The marker's form carries the state, not just its colour. Two of the four
  // verdicts are neutral greys, so a filled circle in two similar greys would be
  // two states a reader cannot tell apart. A decided verdict is filled, a measured
  // but inconclusive one is a hollow ring, and one that could not be measured at
  // all is a dash: the shape says which kind of answer this is before the colour
  // says anything, which is the convention real status displays use.
  // NOT_INFORMATIVE joins NOT_MEASURABLE on the dash. The measurement ran and
  // returned a number; the number was a constant that no ordering could have
  // changed, so it decides nothing. A filled marker, which is what the default
  // branch gave it, would have drawn the least informative outcome in this
  // console with the shape reserved for a decided one.
  // OPEN joins the dash, and the reason moved rather than went away. It used to be
  // that gate 4 had never been run, so there was no measurement to be inconclusive
  // about. A review has now been carried out and the reviewer was not a person, so
  // there is a measurement and it is not a measurement of what this gate asks. The
  // dash is still the honest shape: a ring would say the gate's own question was
  // measured and came back inconclusive, and a filled disc would say it was decided.
  // Neither is true, and the shape a reader has already learnt from NOT_MEASURABLE is
  // the one that says so.
  const marker =
    normalised === "NOT_ESTABLISHED"
      ? "ring"
      : normalised === "NOT_MEASURABLE" ||
          normalised === "NOT_INFORMATIVE" ||
          normalised === "OPEN"
        ? "dash"
        : "filled";

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
        style={
          marker === "dash"
            ? {
                width: dot,
                height: 2,
                background: colour,
              }
            : {
                width: dot,
                height: dot,
                background: marker === "filled" ? colour : "transparent",
                border: marker === "ring" ? `2px solid ${colour}` : undefined,
                borderRadius: "50%",
              }
        }
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
  tone?: "neutral" | "action" | "muted" | "warn";
  title?: string;
}) {
  const palette = {
    neutral: { fg: "var(--text-02)", bd: "var(--border-strong)" },
    action: { fg: "var(--interactive-04)", bd: "var(--interactive-04)" },
    muted: { fg: "var(--text-03)", bd: "var(--border-subtle)" },
    // A refusal code has to read as a refusal. The same amber the gate ledger uses for a
    // gate that did not pass, so one colour means one thing across the console.
    warn: { fg: "var(--support-03)", bd: "var(--support-03)" },
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
  // A class rather than the inline styles this used to carry. Inline styles win over every
  // stylesheet rule, so while the padding, ground and border sat in a `style` attribute no
  // sheet could give a stat plate a gradient, a lit edge or a hover state: the depth layer in
  // globals.css could reach the tile's transform and shadow and not its background. The
  // computed values are unchanged, they just moved somewhere that can be overridden.
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div
        className="num stat-value"
        // `tone` stays inline. It is the one value here a caller varies per instance, and it
        // is how a stat says which verdict colour it carries.
        style={tone ? { color: tone } : undefined}
      >
        {value}
      </div>
      {detail && <div className="stat-detail">{detail}</div>}
    </div>
  );
}

/**
 * An interval drawn against its threshold.
 *
 * The whole point of this console is that a point estimate is not a result, so
 * the interval is the figure and the point estimate is a mark inside it. A bar
 * that showed only the point estimate would make gate 6 look like a pass.
 *
 * Everything drawn is clamped to the track. The cold-station interval runs to
 * 3.896 on a domain that stops at 2.5, so the band was drawn from 71% to 170%
 * of its own width and escaped the layout: 382px of overflow, a horizontal
 * scrollbar on the whole document, and at 390px wide a page 735px across. That
 * was the site's only passing result. Clamping alone would quietly redraw an
 * interval as if it ended at the axis, so a value outside the domain gets a
 * marker on the edge it left through and the real number stays in the caption
 * and in the accessible label.
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
  const raw = (value: number) => ((value - min) / span) * 100;
  const pct = (value: number) => Math.min(100, Math.max(0, raw(value)));
  const runsPast = high > max;
  const startsBefore = low < min;
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
          overflow: "hidden",
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
            borderTop: `1px solid ${colour}`,
            borderBottom: `1px solid ${colour}`,
            borderLeft: startsBefore ? "none" : `1px solid ${colour}`,
            borderRight: runsPast ? "none" : `1px solid ${colour}`,
          }}
        />
        {runsPast ? (
          <div
            aria-hidden="true"
            title={`continues to ${high.toFixed(3)}`}
            style={{
              position: "absolute",
              right: 0,
              top: "0.25rem",
              bottom: "0.25rem",
              width: "0.5rem",
              background: `repeating-linear-gradient(135deg, ${colour} 0 2px, transparent 2px 4px)`,
            }}
          />
        ) : null}
        {startsBefore ? (
          <div
            aria-hidden="true"
            title={`continues to ${low.toFixed(3)}`}
            style={{
              position: "absolute",
              left: 0,
              top: "0.25rem",
              bottom: "0.25rem",
              width: "0.5rem",
              background: `repeating-linear-gradient(135deg, ${colour} 0 2px, transparent 2px 4px)`,
            }}
          />
        ) : null}
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
      {runsPast || startsBefore ? (
        <p
          style={{
            margin: "var(--sp-02) 0 0",
            fontSize: "var(--type-caption)",
            color: "var(--text-03)",
          }}
        >
          The interval runs past this axis. Its full extent is{" "}
          <span className="num">{low.toFixed(3)}</span> to{" "}
          <span className="num">{high.toFixed(3)}</span>, and the hatched edge is where
          it leaves the scale.
        </p>
      ) : null}
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
      className="note"
      style={{
        padding: "var(--sp-04) var(--sp-05)",
        borderLeft: `3px solid ${colour}`,
        background: "var(--ui-01)",
        color: "var(--text-02)",
        maxWidth: "62ch",
      }}
    >
      {children}
    </p>
  );
}

/** Method that stays on the page without spending a screen on it.
 *
 * Every argument this wraps is still in the served HTML, still selectable, still
 * found by ctrl-F and still read by a screen reader in document order; a native
 * <details> costs nothing when closed and nothing to open. It exists so a section
 * can lead with what was measured and keep the defence of how it was measured one
 * click below, rather than making every reader walk through the second to reach
 * the first. Nothing that a verdict turns on belongs in here.
 */
export function Details({
  summary,
  children,
}: {
  summary: string;
  children: ReactNode;
}) {
  return (
    <details className="disclosure">
      <summary>{summary}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}

export function Table({
  head,
  children,
  caption,
  headAlign,
}: {
  head: ReactNode[];
  children: ReactNode;
  caption?: string;
  /**
   * Per-column header alignment. Defaults to the old behaviour, first column
   * left and the rest right, which is correct for a table of figures and wrong
   * for a table whose last column is a sentence: the header sat on one edge and
   * its cells on the other.
   */
  headAlign?: Array<"left" | "right">;
}) {
  return (
    // A scroll container that is not focusable can only be scrolled with a mouse.
    // Overflow here is the normal case rather than an edge one: every th and td
    // below sets white-space: nowrap, and two of the tables on the observation page
    // hold no link at all, so without a tab stop on the container there is no
    // keyboard route to the columns past the fold. The provenance table is the
    // clearest case, because the column a reader most wants is a 64-character
    // SHA-256. WCAG 2.1.1.
    //
    // role="region" with a name, rather than a bare tabIndex, so the extra tab stop
    // announces what it is instead of landing the reader on an unnamed div. The
    // caption is the name when there is one, which is the same string the sighted
    // reader sees under the table.
    <div
      tabIndex={0}
      role="region"
      aria-label={caption ?? "Table, scrollable"}
      style={{ overflowX: "auto" }}
    >
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
                  textAlign:
                    headAlign?.[index] ?? (index === 0 ? "left" : "right"),
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
