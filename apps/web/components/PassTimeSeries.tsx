/**
 * Elevation and Doppler shift against pass time.
 *
 * The polar sky plot shows where the satellite was but throws time away: two passes
 * with the same track can take different lengths of time to fly it. Satellite
 * tracking software has carried both views side by side for decades (Gpredict shows a
 * polar plot and an azimuth/elevation-against-time chart together) and this is the
 * second one, with the Doppler curve added underneath because the Doppler curve is
 * what the corridor actually is.
 *
 * Two stacked panels on one shared time axis rather than one panel with two y axes.
 * A twin-axis chart lets the author decide where two unrelated curves appear to
 * cross, and the crossing is then an artefact of the scaling rather than a fact. Here
 * the zero crossing of the Doppler curve and the peak of the elevation curve line up
 * because they happen at the same instant, not because the axes were arranged to make
 * them.
 *
 * Server-rendered. The only client-side part is the cursor, which the replay moves.
 */
import type { ReactNode } from "react";
import { svgPolyline } from "@/lib/plot-path";

export type SeriesGeometry = {
  fracs: number[];
  elevation_deg: number[];
  doppler_hz: number[] | null;
};

// The viewBox is sized so one user unit is about one CSS pixel at the width this
// instrument is actually displayed at, and that is not cosmetic. An SVG laid out
// with width:100% scales its whole coordinate system, text included, so a label
// declared at 9px renders at 9px times the scale factor. Measured on the built
// page at a 1440px viewport: the sky plot scales 1.18, the ground track 1.30, and
// this instrument, 420 units wide inside a 1151px column, scaled 2.74. Its axis
// labels were rendering at 24.7px next to 14px body prose, so the chrome of the
// chart was the largest text in the section.
//
// The fix is the coordinate system rather than the font size, because the scale
// factor depends on the viewport and any font-size chosen to cancel it would only
// be right at one width. At 1120 units wide the scale is about 1.03 and the labels
// land near their declared size at every width the column takes.
//
// Two consequences worth naming. Stroke widths come from CSS and were being
// multiplied by 2.74 here, so the curves drop from about 4.8px to 1.75px and now
// match the weight of the other two instruments instead of overpowering them. And
// the small offsets below are NOT the old numbers scaled by 8/3: they position
// text that did not scale with the geometry, so each one is re-derived for a label
// of about 11px rather than one of 25px.
const W = 1120;
const PANEL_H = 250;
const GAP = 30;
const PAD_L = 44;
const PAD_R = 16;
const PAD_T = 18;
const PAD_B = 44;
const H = PAD_T + PANEL_H * 2 + GAP + PAD_B;
const PLOT_W = W - PAD_L - PAD_R;

/** Right-aligned tick label to its axis. */
const AXIS_GAP = 8;
/** Panel title baseline above the panel's top edge. */
const TITLE_LIFT = 5;
/** Time tick baseline below the plot's bottom edge. */
const TICK_DROP = 16;
/** Axis title baseline above the bottom of the frame. */
const AXIS_TITLE_LIFT = 6;

const TOP_Y = PAD_T;
const BOTTOM_Y = PAD_T + PANEL_H + GAP;

export function niceCeil(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (value <= step * magnitude) return step * magnitude;
  }
  return 10 * magnitude;
}

/**
 * Index of the highest elevation sample, which is closest approach as this instrument
 * knows it. Exported because the drawn marker and the accessible label have to agree
 * about which sample that is.
 */
export function indexOfPeakElevation(els: readonly number[]): number {
  let iTca = 0;
  for (let i = 1; i < els.length; i += 1) {
    const v = els[i];
    const best = els[iTca];
    if (v !== undefined && best !== undefined && v > best) iTca = i;
  }
  return iTca;
}

/**
 * Index of the first sign change in the Doppler series, or -1 when the window lies
 * entirely on one side of closest approach. Sign changes rather than an exact zero,
 * because the samples are discrete and the crossing lands between two of them.
 */
export function indexOfFirstSignChange(dops: readonly number[] | null): number {
  if (!dops) return -1;
  return dops.findIndex((v, i) => i > 0 && (v >= 0) !== ((dops[i - 1] ?? v) >= 0));
}

/**
 * The accessible label, derived from the series rather than from its endpoints.
 *
 * This is a pure function and not inline markup because of what it used to say. The
 * sentence was built from the first and last sample and asserted that the curve ran
 * "down through zero", which is false on any window that sits entirely on one side of
 * closest approach. One of the 25 shipped observations, 14744250, is exactly that: the
 * Doppler curve runs from -5870.4 Hz to -7227.6 Hz and never changes sign. A sighted
 * reader sees a curve that stays below the zero line and can discount the sentence. A
 * reader using a screen reader gets the sentence and nothing else, so the console was
 * asserting as measured fact something its own data contradicts. Exported so the three
 * branches can be tested, which is the only way that class of defect stays closed.
 */
export function passTimeSeriesLabel({
  durationS,
  fracs,
  els,
  dops,
}: {
  durationS: number;
  fracs: readonly number[];
  els: readonly number[];
  dops: readonly number[] | null;
}): string {
  const iTca = indexOfPeakElevation(els);
  const iCross = indexOfFirstSignChange(dops);
  const crossesZero = iCross > 0;
  // Whether the crossing lands on the sample where elevation peaks. The physics
  // says both happen at closest approach, and on a modelled series they do, but
  // the label must not assert the coincidence on a series that does not show it.
  // One sample of tolerance, because the crossing falls between iCross - 1 and
  // iCross while iTca is a sample index.
  const crossingIsAtPeak = crossesZero && Math.abs(iCross - iTca) <= 1;

  return (
    `Elevation and Doppler shift against pass time over ${durationS.toFixed(0)} seconds.`
    + ` Elevation rises to ${(els[iTca] ?? 0).toFixed(1)} degrees and falls back.`
    + (dops
      ? crossesZero
        ? crossingIsAtPeak
          ? ` The Doppler shift runs from ${(dops[0] ?? 0).toFixed(0)} Hz to`
            + ` ${(dops[dops.length - 1] ?? 0).toFixed(0)} Hz, crossing zero at the`
            + ` same instant elevation peaks.`
          : ` The Doppler shift runs from ${(dops[0] ?? 0).toFixed(0)} Hz to`
            + ` ${(dops[dops.length - 1] ?? 0).toFixed(0)} Hz, crossing zero`
            + ` ${Math.abs(((fracs[iCross] ?? 0) - (fracs[iTca] ?? 0)) * durationS).toFixed(0)}`
            + ` seconds from the elevation peak rather than at it.`
        : ` The Doppler shift runs from ${(dops[0] ?? 0).toFixed(0)} Hz to`
          + ` ${(dops[dops.length - 1] ?? 0).toFixed(0)} Hz. The recording window`
          + ` lies entirely on one side of closest approach, so the Doppler shift`
          + ` does not cross zero within it.`
      : " The Doppler shift is not measurable for this record.")
  );
}

export default function PassTimeSeries({
  geometry,
  durationS,
}: {
  geometry: SeriesGeometry;
  durationS: number;
}) {
  const fracs = geometry.fracs;
  const els = geometry.elevation_deg;
  const dops = geometry.doppler_hz;
  if (fracs.length < 2) return null;

  const x = (frac: number) => PAD_L + frac * PLOT_W;

  // Elevation: always 0 to 90, not scaled to the data. A pass that only reached 15
  // degrees should look like a low pass, and auto-scaling it to fill the panel would
  // make every pass look the same height.
  // No clamp. A sample below the horizon is not drawn at zero: it is not drawn.
  // This panel used to clamp with Math.max(0, deg), which put a flat segment along
  // the zero line for exactly the samples where the sky plot beside it breaks its
  // track, so the two instruments disagreed about the same series. Three of the
  // shipped observations have below-horizon samples.
  const elY = (deg: number) => TOP_Y + PANEL_H - (deg / 90) * PANEL_H;

  // Doppler: symmetric about zero and rounded outward, so the zero line sits exactly
  // in the middle of the panel and a reader can see the sign change rather than infer
  // it. Asymmetric scaling would put zero somewhere arbitrary.
  const dopMax = dops ? niceCeil(Math.max(...dops.map(Math.abs))) : 1;
  const dopY = (hz: number) => BOTTOM_Y + PANEL_H / 2 - (hz / dopMax) * (PANEL_H / 2);

  // NaN for a below-horizon sample, so svgPolyline breaks the subpath there rather
  // than joining across it. The projection makes the same statement for the sky
  // plot and the replay cursor; this is the third consumer of that policy.
  const elPath = svgPolyline(
    els.map((v) => (v === undefined || v < 0 ? Number.NaN : elY(v))),
    fracs.map((f) => (f === undefined ? Number.NaN : x(f))),
    2,
    true,
  );

  const dopPath = dops
    ? fracs
        .map((f, i) => {
          const v = dops[i];
          if (f === undefined || v === undefined) return null;
          return `${x(f).toFixed(2)},${dopY(v).toFixed(2)}`;
        })
        .filter((p): p is string => p !== null)
    : [];

  // Closest approach, from the elevation series, drawn on both panels so the
  // alignment is explicit rather than left for the reader to eyeball.
  const iTca = indexOfPeakElevation(els);
  const tcaX = x(fracs[iTca] ?? 0);

  const timeTicks = [0, 0.25, 0.5, 0.75, 1];

  const label = passTimeSeriesLabel({ durationS, fracs, els, dops });

  const axis = (
    text: string,
    yPos: number,
  ): ReactNode => (
    <text
      x={PAD_L - AXIS_GAP}
      y={yPos}
      className="plot-label"
      textAnchor="end"
      dominantBaseline="middle"
    >
      {text}
    </text>
  );

  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      {/* Elevation panel */}
      <rect
        x={PAD_L}
        y={TOP_Y}
        width={PLOT_W}
        height={PANEL_H}
        className="plot-grid-strong"
      />
      {[0, 30, 60, 90].map((deg) => (
        <g key={`el-${deg}`}>
          <line
            x1={PAD_L}
            x2={PAD_L + PLOT_W}
            y1={elY(deg)}
            y2={elY(deg)}
            className="plot-grid"
          />
          {axis(String(deg), elY(deg))}
        </g>
      ))}
      <path d={elPath} className="plot-track" />
      <text x={PAD_L} y={TOP_Y - TITLE_LIFT} className="plot-label">
        ELEVATION, DEG
      </text>

      {/* Doppler panel */}
      <rect
        x={PAD_L}
        y={BOTTOM_Y}
        width={PLOT_W}
        height={PANEL_H}
        className="plot-grid-strong"
      />
      {dops ? (
        <>
          {[dopMax, 0, -dopMax].map((hz) => (
            <g key={`dop-${hz}`}>
              <line
                x1={PAD_L}
                x2={PAD_L + PLOT_W}
                y1={dopY(hz)}
                y2={dopY(hz)}
                className={hz === 0 ? "plot-grid-strong" : "plot-grid"}
              />
              {axis(
                hz === 0 ? "0" : `${hz > 0 ? "+" : "−"}${Math.abs(hz) / 1000}k`,
                dopY(hz),
              )}
            </g>
          ))}
          <polyline points={dopPath.join(" ")} className="plot-track" />
        </>
      ) : (
        <text
          x={PAD_L + PLOT_W / 2}
          y={BOTTOM_Y + PANEL_H / 2}
          className="plot-label"
          textAnchor="middle"
          dominantBaseline="middle"
        >
          no receive frequency on this record, so no Doppler curve
        </text>
      )}
      <text x={PAD_L} y={BOTTOM_Y - TITLE_LIFT} className="plot-label">
        DOPPLER, HZ
      </text>

      {/* Closest approach, marked on both panels. */}
      <line
        x1={tcaX}
        x2={tcaX}
        y1={TOP_Y}
        y2={BOTTOM_Y + PANEL_H}
        className="plot-track-faint"
      />

      {/* Shared time axis. */}
      {timeTicks.map((frac) => (
        <text
          key={`t-${frac}`}
          x={x(frac)}
          y={H - PAD_B + TICK_DROP}
          className="plot-label"
          textAnchor={frac === 0 ? "start" : frac === 1 ? "end" : "middle"}
        >
          {(frac * durationS).toFixed(0)}
        </text>
      ))}
      <text
        x={PAD_L + PLOT_W / 2}
        y={H - AXIS_TITLE_LIFT}
        className="plot-label"
        textAnchor="middle"
      >
        SECONDS FROM THE START OF THE RECORDING
      </text>

      {/* The replay cursor: one vertical line across both panels. */}
      <g id="timeseries-cursor" className="replay-cursor-time" aria-hidden="true">
        <line x1={0} x2={0} y1={TOP_Y} y2={BOTTOM_Y + PANEL_H} />
      </g>
    </svg>
  );
}

/** The x coordinate the replay cursor should sit at, for a given pass fraction. */
export function timeSeriesCursorX(frac: number): number {
  return PAD_L + frac * PLOT_W;
}
