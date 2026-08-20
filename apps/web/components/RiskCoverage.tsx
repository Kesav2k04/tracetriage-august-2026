/**
 * The risk-coverage curve.
 *
 * Server-rendered SVG: it is a fixed set of measured points, so there is nothing
 * for the browser to compute and no reason to ship JavaScript to draw it. The
 * curve answers the operational question the Brier score does not: if the model
 * only answers when it is confident, how often is it wrong, and how much does it
 * refuse?
 *
 * The marked point is the threshold chosen on the calibration partition, plotted
 * where it landed on test. Choosing it on test and reporting the same point would
 * be reporting the best of 41 thresholds as if it had been picked in advance.
 */
import type { SelectivePoint } from "@/lib/data";

const W = 640;
const H = 300;
const PAD = { top: 16, right: 20, bottom: 44, left: 56 };

export default function RiskCoverage({
  curve,
  operating,
  label,
}: {
  curve: SelectivePoint[];
  operating?: {
    coverage: number;
    risk: number;
    risk_ci95?: [number, number] | null;
    threshold: number;
    held: boolean;
  } | null;
  label: string;
}) {
  const points = [...curve].sort((a, b) => a.coverage - b.coverage);
  const maxRisk = Math.max(0.05, ...points.map((p) => p.risk));

  const x = (coverage: number) =>
    PAD.left + coverage * (W - PAD.left - PAD.right);
  const y = (risk: number) =>
    H - PAD.bottom - (risk / maxRisk) * (H - PAD.top - PAD.bottom);

  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.coverage).toFixed(1)} ${y(p.risk).toFixed(1)}`)
    .join("");

  const yTicks = [0, maxRisk / 2, maxRisk];
  const xTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label={
          `${label}. Risk against coverage over ${points.length} thresholds. ` +
          `At full coverage the error rate is ${(points[points.length - 1]?.risk ?? 0).toFixed(3)}; ` +
          (operating
            ? `at the threshold chosen on calibration the model answers ${(operating.coverage * 100).toFixed(0)}% of the time with an error rate of ${operating.risk.toFixed(3)}.`
            : "no operating point was selected.")
        }
      >
        <title>{label}</title>

        {yTicks.map((tick) => (
          <g key={`y${tick}`}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
              stroke="var(--border-subtle)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(tick) + 4}
              textAnchor="end"
              fill="var(--text-03)"
              fontSize={11}
              fontFamily="var(--font-mono)"
            >
              {tick.toFixed(2)}
            </text>
          </g>
        ))}

        {xTicks.map((tick) => (
          <text
            key={`x${tick}`}
            x={x(tick)}
            y={H - PAD.bottom + 18}
            textAnchor="middle"
            fill="var(--text-03)"
            fontSize={11}
            fontFamily="var(--font-mono)"
          >
            {(tick * 100).toFixed(0)}%
          </text>
        ))}

        <text
          x={(PAD.left + W - PAD.right) / 2}
          y={H - 6}
          textAnchor="middle"
          fill="var(--text-02)"
          fontSize={12}
        >
          coverage: share of observations the model answers on
        </text>
        <text
          x={14}
          y={(H - PAD.bottom + PAD.top) / 2}
          textAnchor="middle"
          fill="var(--text-02)"
          fontSize={12}
          transform={`rotate(-90 14 ${(H - PAD.bottom + PAD.top) / 2})`}
        >
          risk: error rate among those
        </text>

        <path d={path} fill="none" stroke="var(--interactive-04)" strokeWidth={2} />

        {points.map((p) => (
          <circle
            key={p.threshold}
            cx={x(p.coverage)}
            cy={y(p.risk)}
            r={2}
            fill="var(--interactive-04)"
            opacity={0.55}
          />
        ))}

        {operating && (
          <g>
            {operating.risk_ci95 && (
              <line
                x1={x(operating.coverage)}
                x2={x(operating.coverage)}
                y1={y(Math.min(operating.risk_ci95[1], maxRisk))}
                y2={y(operating.risk_ci95[0])}
                stroke="var(--support-03)"
                strokeWidth={2}
                opacity={0.8}
              />
            )}
            <circle
              cx={x(operating.coverage)}
              cy={y(operating.risk)}
              r={5}
              fill="var(--ui-background)"
              stroke="var(--support-03)"
              strokeWidth={2}
            />
            <text
              x={x(operating.coverage) + 10}
              y={y(operating.risk) - 8}
              fill="var(--support-03)"
              fontSize={11}
              fontFamily="var(--font-mono)"
            >
              chosen on calibration
            </text>
          </g>
        )}
      </svg>

      <figcaption
        style={{
          fontSize: "var(--type-caption)",
          color: "var(--text-02)",
          lineHeight: 1.6,
          marginTop: "var(--sp-03)",
        }}
      >
        {/* The caption used to say "the yellow bar", and the bar is drawn from
            --support-03, which the palette change moved from #f1c21b to inferno's
            0.70 stop. A colour word in prose is a second copy of a token: it went
            stale the moment the token moved, and the page shipped a sentence naming a
            colour it no longer drew. The mark is named by what it is instead, and the
            label already on the chart carries the pointer. */}
        The vertical bar through the marked point is the 95% interval on the error rate
        at that operating point.
        Whether the ceiling held is decided on the top of that interval, not on the
        point estimate, because the promise to a reviewer is about the worst plausible
        error rate rather than the luckiest one.
      </figcaption>
    </figure>
  );
}
