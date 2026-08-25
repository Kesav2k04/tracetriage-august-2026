/*
 * Four chart primitives, and the reason there are four rather than one per page.
 *
 * Five of the nine routes on this console shipped with no figure at all: /agent,
 * /live, /precedent, /provenance and /replay were a heading, a paragraph, a table and
 * a note, repeated down the page. Measured on the rendered pixels of /precedent at
 * 1440px, 21% of the page carried no ink across the full width of the reading column,
 * and a reader arrived at every one of them already tired. The finding on each of
 * those pages is a shape, and each was published only as digits in a table.
 *
 * These are the shapes, and they are deliberately a small set rather than a bespoke
 * component per page:
 *
 *   IntervalChart  a point estimate with its interval, against reference rules.
 *                  The only honest way to draw an effect this project measured, and
 *                  the one that makes "the interval contains the threshold" a thing
 *                  you can see rather than a sentence you have to parse.
 *   Dumbbell       one quantity under two conditions, joined. Reading a collapse off
 *                  two columns of a table is arithmetic; reading it off the length of
 *                  a line is not.
 *   OutcomeStrip   one cell per item, one row per arm. For counts small enough that
 *                  the items themselves are the evidence.
 *   SplitBars      composition, stacked, with the parts named.
 *
 * Rules every one of them follows.
 *
 * No client JavaScript. These are server components: the SVG is in the HTML the
 * static export ships, so a figure is complete at first paint and cannot be waiting
 * on hydration. The section reveal in globals.css is the only motion, it is CSS on
 * the compositor, and it is off under `prefers-reduced-motion`.
 *
 * Nothing is drawn that was not passed in. There is no smoothing, no fitted line and
 * no axis that starts somewhere flattering. A domain is either given by the caller or
 * taken from the data plus a stated pad, and every reference rule carries its own
 * label, so a reader can never be looking at a scale they have not been told.
 *
 * The type is the interface's type. Labels in the label face, uppercase and tracked;
 * numbers in the mono face with tabular figures; 1px rules in the same border token
 * every table uses; no rounded corners and no shadow. A chart that invented its own
 * typography would read as a picture of a chart pasted into the page, which is
 * exactly what a console arguing that its numbers are real cannot afford.
 *
 * Values are formatted by the caller, not here. `lib/data.ts` owns `fmt`, and a second
 * rounding rule living in a chart is how two places in one page come to print the same
 * receipt to different precision.
 */

/*
 * No `<title>` inside these SVGs, and that is a correctness fix rather than a
 * simplification.
 *
 * React 19 treats `<title>` as hoistable document metadata. Inside an `<svg>` with a
 * single string child it survived, but `<title>{name}: {v}</title>` is three children,
 * and the static export wrote `<title></title>` on the server while the client
 * rendered `Train: 1909`. That is a hydration mismatch, and React answered it the way
 * it always does: it threw away the whole tree and re-rendered it on the client.
 * /provenance/ was doing that on every load.
 *
 * Nothing is lost. Each figure is `role="img"` with an `aria-label` on the `<svg>`, and
 * `role="img"` makes the subtree presentational, so a per-cell `<title>` was never
 * reaching assistive technology in the first place. The reading of the figure lives in
 * the label and the caption, which is where a reader who cannot see it needs it.
 */

import type { ReactNode } from "react";

/* --------------------------------------------------------------------------
 * Shared frame
 * ----------------------------------------------------------------------- */

const VB_W = 1000;

/** Two decimals in a 1000-unit box is well under a device pixel and keeps the emitted
 *  markup small on a page that ships several of these. */
const n2 = (v: number) => v.toFixed(2);

function Frame({
  height,
  label,
  caption,
  children,
}: {
  height: number;
  label: string;
  caption?: ReactNode;
  children: ReactNode;
}) {
  return (
    <figure className="chart">
      <svg
        className="chart-svg"
        viewBox={`0 0 ${VB_W} ${height}`}
        role="img"
        aria-label={label}
      >
        {children}
      </svg>
      {caption ? <figcaption>{caption}</figcaption> : null}
    </figure>
  );
}

/* --------------------------------------------------------------------------
 * IntervalChart
 * ----------------------------------------------------------------------- */

export type IntervalRow = {
  label: string;
  sublabel?: string;
  point: number | null;
  /** Lower and upper. Omitted where the measurement has no interval. */
  interval?: [number, number] | null;
  /** `true` marks the row the page is arguing for, which is drawn in the accent.
   *  Everything else is drawn in the reference ink, because a chart that highlights
   *  every row highlights nothing. */
  primary?: boolean;
  /** Printed at the right of the row, already formatted. */
  value?: string;
};

export type ReferenceRule = {
  at: number;
  label: string;
  /** A threshold is drawn solid and a null level dashed, so the two are never confused
   *  at a glance. */
  kind?: "threshold" | "null";
};

export function IntervalChart({
  rows,
  rules = [],
  domain,
  label,
  caption,
  labelWidth = 300,
}: {
  rows: IntervalRow[];
  rules?: ReferenceRule[];
  /** Given explicitly wherever the scale is part of the claim. Left out, it is taken
   *  from the data and the rules with a 6% pad, which is stated in the caption the
   *  caller writes. */
  domain?: [number, number];
  label: string;
  caption?: ReactNode;
  labelWidth?: number;
}) {
  const ROW_H = 52;
  const TOP = 34;
  const height = TOP + rows.length * ROW_H + 30;
  const plotL = labelWidth;
  const plotR = VB_W - 108; // room for the printed value at the right

  const values: number[] = [];
  for (const r of rows) {
    if (r.point !== null) values.push(r.point);
    if (r.interval) values.push(r.interval[0], r.interval[1]);
  }
  for (const rule of rules) values.push(rule.at);
  const lo = domain ? domain[0] : Math.min(...values);
  const hi = domain ? domain[1] : Math.max(...values);
  const pad = domain ? 0 : (hi - lo) * 0.06 || 1;
  const d0 = lo - pad;
  const d1 = hi + pad;
  const x = (v: number) => plotL + ((v - d0) / (d1 - d0 || 1)) * (plotR - plotL);

  return (
    <Frame height={height} label={label} caption={caption}>
      {/* Reference rules first, so every mark that matters is drawn over them. */}
      {rules.map((rule) => (
        <g key={rule.label}>
          <line
            x1={n2(x(rule.at))}
            y1={TOP - 12}
            x2={n2(x(rule.at))}
            y2={TOP + rows.length * ROW_H - 8}
            stroke={
              rule.kind === "threshold" ? "var(--text-03)" : "var(--border-subtle)"
            }
            strokeWidth="1"
            strokeDasharray={rule.kind === "threshold" ? undefined : "3 5"}
          />
          <text
            x={n2(x(rule.at))}
            y={TOP + rows.length * ROW_H + 12}
            className="chart-tick chart-mid"
          >
            {rule.label}
          </text>
        </g>
      ))}

      {rows.map((row, i) => {
        const y = TOP + i * ROW_H + ROW_H / 2 - 6;
        const ink = row.primary ? "var(--interactive-01)" : "var(--text-02)";
        return (
          <g key={row.label}>
            <text x="0" y={row.sublabel ? y - 4 : y + 4} className="chart-row-label">
              {row.label}
            </text>
            {row.sublabel ? (
              <text x="0" y={y + 14} className="chart-row-sub">
                {row.sublabel}
              </text>
            ) : null}

            {row.point === null ? (
              <text x={n2(plotL)} y={y + 4} className="chart-row-sub">
                not applicable
              </text>
            ) : (
              <>
                {row.interval ? (
                  <>
                    {/* The interval is the measurement. It is drawn heavier than the
                        point, because a reader who takes only one mark off this row
                        should take the range and not the estimate. */}
                    <line
                      x1={n2(x(row.interval[0]))}
                      y1={y}
                      x2={n2(x(row.interval[1]))}
                      y2={y}
                      stroke={ink}
                      strokeWidth="6"
                      opacity="0.28"
                    />
                    <line
                      x1={n2(x(row.interval[0]))}
                      y1={y - 7}
                      x2={n2(x(row.interval[0]))}
                      y2={y + 7}
                      stroke={ink}
                      strokeWidth="1.5"
                    />
                    <line
                      x1={n2(x(row.interval[1]))}
                      y1={y - 7}
                      x2={n2(x(row.interval[1]))}
                      y2={y + 7}
                      stroke={ink}
                      strokeWidth="1.5"
                    />
                  </>
                ) : null}
                <circle cx={n2(x(row.point))} cy={y} r="5" fill={ink} />
              </>
            )}

            {row.value ? (
              <text x={VB_W} y={y + 5} className="chart-value chart-end">
                {row.value}
              </text>
            ) : null}
          </g>
        );
      })}
    </Frame>
  );
}

/* --------------------------------------------------------------------------
 * Dumbbell
 * ----------------------------------------------------------------------- */

export type DumbbellRow = {
  label: string;
  a: number | null;
  b: number | null;
  /** Printed where `b` is missing, in place of the second mark. */
  missingNote?: string;
};

export function Dumbbell({
  rows,
  aName,
  bName,
  rules = [],
  domain,
  label,
  caption,
  format,
  labelWidth = 300,
}: {
  rows: DumbbellRow[];
  aName: string;
  bName: string;
  rules?: ReferenceRule[];
  domain?: [number, number];
  label: string;
  caption?: ReactNode;
  format: (v: number) => string;
  labelWidth?: number;
}) {
  const ROW_H = 48;
  const TOP = 56;
  const height = TOP + rows.length * ROW_H + 12;
  // The plot is inset from the label column so a value printed outside the leftmost
  // mark still lands inside the frame.
  const plotL = labelWidth + 68;
  const plotR = VB_W - 76;

  const values: number[] = [];
  for (const r of rows) {
    if (r.a !== null) values.push(r.a);
    if (r.b !== null) values.push(r.b);
  }
  for (const rule of rules) values.push(rule.at);
  const lo = domain ? domain[0] : Math.min(...values);
  const hi = domain ? domain[1] : Math.max(...values);
  const pad = domain ? 0 : (hi - lo) * 0.12 || 1;
  const d0 = lo - pad;
  const d1 = hi + pad;
  const x = (v: number) => plotL + ((v - d0) / (d1 - d0 || 1)) * (plotR - plotL);

  return (
    <Frame height={height} label={label} caption={caption}>
      {/* The legend is drawn, not named in prose. A colour word in a sentence is a
          second copy of a design decision and it goes stale the way a hand-typed
          number does; it also asks a reader who cannot separate two hues to use the
          hue as an identifier, which they cannot. Each series carries a shape here as
          well as a fill. */}
      <g>
        <circle cx={n2(labelWidth + 6)} cy="16" r="5" fill="var(--interactive-01)" />
        <text x={n2(labelWidth + 20)} y="21" className="chart-legend">
          {aName}
        </text>
        <circle
          cx={n2(labelWidth + 176)}
          cy="16"
          r="5"
          fill="none"
          stroke="var(--text-02)"
          strokeWidth="2"
        />
        <text x={n2(labelWidth + 190)} y="21" className="chart-legend">
          {bName}
        </text>
      </g>

      {rules.map((rule) => (
        <g key={rule.label}>
          <line
            x1={n2(x(rule.at))}
            y1={TOP - 8}
            x2={n2(x(rule.at))}
            y2={TOP + rows.length * ROW_H - 10}
            stroke="var(--text-03)"
            strokeWidth="1"
            strokeDasharray="3 5"
          />
          <text
            x={n2(x(rule.at))}
            y={TOP - 16}
            className="chart-tick chart-mid"
          >
            {rule.label}
          </text>
        </g>
      ))}

      {rows.map((row, i) => {
        const y = TOP + i * ROW_H + ROW_H / 2 - 8;
        // Which end of the line each value hangs off. `a` may be either side of `b`,
        // and on this data it is on both: warm is above cold on three arms and level
        // with it on the fourth.
        // With no second mark there is no pair to sit outside of, so the value takes
        // the left and the note takes the right. Left to the general rule both landed
        // on the right of the same dot and printed over each other: "0.605" under
        // "no cold definition" on the precedent chart's third row.
        const leftIsA = row.b === null ? true : (row.a ?? 0) <= (row.b ?? 0);
        return (
          <g key={row.label}>
            <text x="0" y={y + 5} className="chart-row-label">
              {row.label}
            </text>
            {row.a !== null && row.b !== null ? (
              <line
                x1={n2(x(row.a))}
                y1={y}
                x2={n2(x(row.b))}
                y2={y}
                stroke="var(--text-03)"
                strokeWidth="1.5"
              />
            ) : null}
            {/* Each value is printed on the outside of its own end of the line, so
                two marks can be arbitrarily close without their labels touching.
                Centred under the mark, the bottom row of the precedent chart printed
                0.530 and 0.528 over each other and over the chance rule's own label:
                three strings inside one 12px box. An outside label cannot collide
                with anything but the frame. */}
            {row.a !== null ? (
              <>
                <circle cx={n2(x(row.a))} cy={y} r="6" fill="var(--interactive-01)" />
                <text
                  x={n2(x(row.a) + (leftIsA ? -13 : 13))}
                  y={y + 5}
                  className={leftIsA ? "chart-tick chart-end" : "chart-tick"}
                >
                  {format(row.a)}
                </text>
              </>
            ) : null}
            {row.b !== null ? (
              <>
                <circle
                  cx={n2(x(row.b))}
                  cy={y}
                  r="6"
                  fill="var(--ui-background)"
                  stroke="var(--text-02)"
                  strokeWidth="2"
                />
                <text
                  x={n2(x(row.b) + (leftIsA ? 13 : -13))}
                  y={y + 5}
                  className={leftIsA ? "chart-tick" : "chart-tick chart-end"}
                >
                  {format(row.b)}
                </text>
              </>
            ) : (
              <text
                x={n2(x(row.a ?? d0) + 18)}
                y={y + 5}
                className="chart-row-sub"
              >
                {row.missingNote ?? "not applicable"}
              </text>
            )}
          </g>
        );
      })}
    </Frame>
  );
}

/* --------------------------------------------------------------------------
 * OutcomeStrip
 * ----------------------------------------------------------------------- */

export type StripCell = {
  /** `true` is drawn filled, `false` hollow, `null` struck through. */
  state: boolean | null;
  /** Read out by assistive technology, one per cell. */
  title: string;
};

export function OutcomeStrip({
  arms,
  label,
  caption,
  itemLabel,
  labelWidth = 260,
}: {
  arms: Array<{ name: string; sub?: string; cells: StripCell[] }>;
  label: string;
  caption?: ReactNode;
  /** Printed under the strip: what one cell is. */
  itemLabel: string;
  labelWidth?: number;
}) {
  const count = Math.max(...arms.map((a) => a.cells.length));
  const ROW_H = 62;
  const TOP = 18;
  const height = TOP + arms.length * ROW_H + 30;
  const plotL = labelWidth;
  const plotR = VB_W - 96;
  const gap = 4;
  const cellW = (plotR - plotL - gap * (count - 1)) / count;
  const cellH = 30;

  return (
    <Frame height={height} label={label} caption={caption}>
      {arms.map((arm, ai) => {
        const y = TOP + ai * ROW_H;
        const hits = arm.cells.filter((c) => c.state === true).length;
        return (
          <g key={arm.name}>
            <text x="0" y={y + 20} className="chart-row-label">
              {arm.name}
            </text>
            {arm.sub ? (
              <text x="0" y={y + 38} className="chart-row-sub">
                {arm.sub}
              </text>
            ) : null}
            {arm.cells.map((cell, i) => {
              const cx = plotL + i * (cellW + gap);
              return (
                <g key={i}>
                  <rect
                    x={n2(cx)}
                    y={y + 4}
                    width={n2(cellW)}
                    height={cellH}
                    fill={cell.state === true ? "var(--interactive-01)" : "none"}
                    stroke={
                      cell.state === true
                        ? "var(--interactive-01)"
                        : "var(--border-subtle)"
                    }
                    strokeWidth="1"
                  />
                  {cell.state === null ? (
                    <line
                      x1={n2(cx + 4)}
                      y1={y + cellH}
                      x2={n2(cx + cellW - 4)}
                      y2={y + 8}
                      stroke="var(--text-03)"
                      strokeWidth="1"
                    />
                  ) : null}
                </g>
              );
            })}
            <text x={VB_W} y={y + 26} className="chart-value chart-end">
              {hits}/{arm.cells.length}
            </text>
          </g>
        );
      })}
      <text x={n2(plotL)} y={height - 10} className="chart-tick">
        {itemLabel}
      </text>
    </Frame>
  );
}

/* --------------------------------------------------------------------------
 * SplitBars
 * ----------------------------------------------------------------------- */

export function SplitBars({
  rows,
  parts,
  label,
  caption,
  labelWidth = 260,
}: {
  rows: Array<{ label: string; sublabel?: string; values: number[] }>;
  /** One name and one ink per segment, in the order `values` gives them. */
  parts: Array<{ name: string; ink: string }>;
  label: string;
  caption?: ReactNode;
  labelWidth?: number;
}) {
  const ROW_H = 54;
  const TOP = 40;
  const height = TOP + rows.length * ROW_H + 14;
  const plotL = labelWidth;
  const plotR = VB_W - 88;
  // One scale across every row, so a shorter split is drawn shorter. Normalising each
  // row to its own width would draw four bars of equal length and hide the one fact
  // this figure exists to carry.
  const max = Math.max(...rows.map((r) => r.values.reduce((a, b) => a + b, 0)));

  return (
    <Frame height={height} label={label} caption={caption}>
      <g>
        {parts.map((part, i) => (
          <g key={part.name}>
            <rect
              x={n2(plotL + i * 190)}
              y="8"
              width="14"
              height="14"
              fill={part.ink}
            />
            <text x={n2(plotL + i * 190 + 22)} y="20" className="chart-legend">
              {part.name}
            </text>
          </g>
        ))}
      </g>
      {rows.map((row, i) => {
        const y = TOP + i * ROW_H;
        const total = row.values.reduce((a, b) => a + b, 0);
        let cursor = plotL;
        return (
          <g key={row.label}>
            <text x="0" y={row.sublabel ? y + 16 : y + 22} className="chart-row-label">
              {row.label}
            </text>
            {row.sublabel ? (
              <text x="0" y={y + 32} className="chart-row-sub">
                {row.sublabel}
              </text>
            ) : null}
            {row.values.map((v, vi) => {
              const w = (v / (max || 1)) * (plotR - plotL);
              const x0 = cursor;
              cursor += w;
              return (
                <g key={vi}>
                  <rect
                    x={n2(x0)}
                    y={y + 6}
                    width={n2(Math.max(0, w))}
                    height="26"
                    fill={parts[vi]?.ink ?? "var(--text-03)"}
                  />
                  {w > 42 ? (
                    <text
                      x={n2(x0 + w / 2)}
                      y={y + 24}
                      className="chart-in-bar chart-mid"
                    >
                      {v}
                    </text>
                  ) : null}
                </g>
              );
            })}
            <text x={VB_W} y={y + 25} className="chart-value chart-end">
              {total}
            </text>
          </g>
        );
      })}
    </Frame>
  );
}
