/**
 * Matched-filter sigma against corridor offset, for one observation.
 *
 * The page above this draws the predicted corridor and the fitted corridor and says the
 * gap between them is the measurement. That asks a reader to accept that the fitted
 * position is where the evidence peaks rather than one plausible place among many. This
 * is the evidence: the same matched filter, scored at every whole-pixel offset it was
 * allowed, rising to a peak and falling away either side.
 *
 * A corridor that were merely near the trace would give a flat sweep with no peak to
 * find, so the shape is the claim and not decoration.
 *
 * The peak marked here is the fitted offset. Not checked to be: `corridor_fit.py`
 * computes the fit as the argmax of this exact array, so a disagreement is not possible
 * rather than not observed. Publishing a curve beside a separately computed number would
 * have been two implementations of one quantity, which is the failure mode the rest of
 * this project spends its tests on.
 *
 * Server-rendered SVG. It is a fixed set of measured points, so there is nothing for the
 * browser to compute and no reason to ship JavaScript to draw it.
 */
import type { OffsetSweepData } from "@/lib/data";

const W = 640;
const H = 240;
const PAD = { top: 16, right: 20, bottom: 46, left: 52 };

export default function OffsetSweep({ sweep }: { sweep: OffsetSweepData }) {
  const xs = sweep.offset_hz;
  const ys = sweep.sigma;
  if (xs.length < 3) return null;

  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(0, ...ys);
  const yMax = Math.max(...ys);
  const ySpan = yMax - yMin || 1;

  const x = (hz: number) =>
    PAD.left + ((hz - xMin) / (xMax - xMin || 1)) * (W - PAD.left - PAD.right);
  const y = (sigma: number) =>
    H - PAD.bottom - ((sigma - yMin) / ySpan) * (H - PAD.top - PAD.bottom);

  // Zipped rather than indexed, because the two arrays are published as a pair and
  // `noUncheckedIndexedAccess` is right to ask what happens if they are not.
  if (ys.length !== xs.length) return null;
  const path = xs
    .map((hz, i) => `${i === 0 ? "M" : "L"}${x(hz).toFixed(1)} ${y(ys[i] as number).toFixed(1)}`)
    .join("");

  // The exporter's own conversion, not a lookup by sigma value: two offsets can score
  // identically and the peak is the one the receipt names.
  const peakHz = sweep.peak_offset_hz;

  // Five ticks across the bound, rounded to whole kilohertz so the axis reads.
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => xMin + f * (xMax - xMin));
  const yTicks = [yMin, yMin + ySpan / 2, yMax];

  const kHz = (hz: number) => (hz / 1000).toFixed(hz === 0 ? 0 : 1);

  return (
    <figure style={{ margin: "var(--sp-05) 0 0" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label={
          `Matched-filter sigma against corridor frequency offset, over ` +
          `${sweep.n_scored} whole-pixel offsets from ${kHz(xMin)} to ${kHz(xMax)} ` +
          `kilohertz. The curve peaks at ${sweep.peak_sigma.toFixed(2)} sigma at an ` +
          `offset of ${Math.round(peakHz)} hertz, which is the fitted offset, and falls ` +
          `to ${Math.min(...ys).toFixed(2)} sigma away from it.`
        }
      >
        <title>Detection strength against corridor offset</title>

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
              {tick.toFixed(1)}
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
            {kHz(tick)}
          </text>
        ))}

        <text
          x={(PAD.left + W - PAD.right) / 2}
          y={H - 6}
          textAnchor="middle"
          fill="var(--text-02)"
          fontSize={12}
        >
          corridor offset, kHz
        </text>
        <text
          x={12}
          y={(H - PAD.bottom + PAD.top) / 2}
          textAnchor="middle"
          fill="var(--text-02)"
          fontSize={12}
          transform={`rotate(-90 12 ${(H - PAD.bottom + PAD.top) / 2})`}
        >
          sigma
        </text>

        {/* Zero offset: where the corridor sits before anything is fitted. The distance
            from here to the peak is the measurement the page above is about. */}
        {xMin < 0 && xMax > 0 && (
          <line
            x1={x(0)}
            x2={x(0)}
            y1={PAD.top}
            y2={H - PAD.bottom}
            stroke="var(--text-03)"
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.7}
          />
        )}

        <path d={path} fill="none" stroke="var(--interactive-04)" strokeWidth={2} />

        <line
          x1={x(peakHz)}
          x2={x(peakHz)}
          y1={y(sweep.peak_sigma)}
          y2={H - PAD.bottom}
          stroke="var(--support-03)"
          strokeWidth={1}
        />
        <circle
          cx={x(peakHz)}
          cy={y(sweep.peak_sigma)}
          r={4}
          fill="var(--support-03)"
        />
        <text
          x={x(peakHz)}
          y={y(sweep.peak_sigma) - 10}
          textAnchor={x(peakHz) > W / 2 ? "end" : "start"}
          fill="var(--text-01)"
          fontSize={12}
          fontFamily="var(--font-mono)"
        >
          {sweep.peak_sigma.toFixed(2)}σ at {Math.round(peakHz).toLocaleString("en-GB")} Hz
        </text>
      </svg>
      <figcaption
        style={{
          color: "var(--text-03)",
          fontSize: "var(--type-caption)",
          marginTop: "var(--sp-03)",
        }}
      >
        {sweep.note} Scored at {sweep.n_scored.toLocaleString("en-GB")} offsets,{" "}
        {sweep.n_published.toLocaleString("en-GB")} plotted.
      </figcaption>
    </figure>
  );
}
