/**
 * The pass as it appeared from the ground station: a polar azimuth and elevation
 * track.
 *
 * This is the plot that makes the corridor legible. A Doppler curve is steep when
 * the satellite is close and flat when it is far, so the shape of the trace on the
 * waterfall is a consequence of the geometry drawn here. A reader who wants to know
 * why one observation has a hard S-curve and another is nearly vertical can compare
 * the two sky tracks and see it.
 *
 * Server-rendered SVG. There is no canvas, no chart library and no client
 * JavaScript in the plot itself: the whole thing is a path string computed at build
 * time from the same propagation the pipeline scored, so it renders with scripting
 * off and costs nothing to draw. A charting library for one polar plot would have
 * been more kilobytes than the entire rest of this console.
 *
 * The projection lives in `lib/projection.ts` because the replay cursor needs the
 * same one. Two copies of it would be two chances to end up with a cursor that does
 * not sit on the line it is tracing.
 */
import { SKY, projectSky } from "@/lib/projection";

export type SkyGeometry = {
  azimuth_deg: number[];
  elevation_deg: number[];
  fracs: number[];
  max_elevation_deg: number;
  tca_frac: number;
  tca_azimuth_deg: number;
};

function polyline(az: number[], el: number[]): string {
  const parts: string[] = [];
  for (let i = 0; i < az.length; i += 1) {
    const azi = az[i];
    const eli = el[i];
    if (azi === undefined || eli === undefined) continue;
    // Below the horizon is off the plot. A sample at -2 degrees is a real
    // propagation result, not an error, so it is dropped rather than clamped:
    // clamping would draw a segment along the rim that never happened.
    if (eli < 0) {
      parts.push("BREAK");
      continue;
    }
    const [x, y] = projectSky(azi, eli);
    parts.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  const runs: string[] = [];
  let current: string[] = [];
  for (const part of parts) {
    if (part === "BREAK") {
      if (current.length > 1) runs.push(`M ${current.join(" L ")}`);
      current = [];
    } else {
      current.push(part);
    }
  }
  if (current.length > 1) runs.push(`M ${current.join(" L ")}`);
  return runs.join(" ");
}

const RINGS = [0, 30, 60];
const CARDINALS: Array<[string, number]> = [
  ["N", 0],
  ["E", 90],
  ["S", 180],
  ["W", 270],
];

export default function SkyPlot({
  geometry,
  stationName,
}: {
  geometry: SkyGeometry;
  stationName: string;
}) {
  const az = geometry.azimuth_deg;
  const el = geometry.elevation_deg;
  const path = polyline(az, el);

  const firstAz = az[0];
  const firstEl = el[0];
  const lastAz = az[az.length - 1];
  const lastEl = el[el.length - 1];

  // The highest point, found in the series rather than trusted from the summary,
  // so the marker cannot land somewhere the drawn track does not go.
  let iTca = 0;
  for (let i = 1; i < el.length; i += 1) {
    const v = el[i];
    const best = el[iTca];
    if (v !== undefined && best !== undefined && v > best) iTca = i;
  }
  const tcaAz = az[iTca];
  const tcaEl = el[iTca];

  const label = `Sky track for ${stationName}: the pass rises`
    + `${firstAz === undefined ? "" : ` at azimuth ${Math.round(firstAz)} degrees`}`
    + `, reaches ${geometry.max_elevation_deg.toFixed(1)} degrees elevation at`
    + ` azimuth ${Math.round(geometry.tca_azimuth_deg)} degrees, and sets`
    + `${lastAz === undefined ? "" : ` at azimuth ${Math.round(lastAz)} degrees`}.`;

  return (
    <svg
      viewBox={`0 0 ${SKY.size} ${SKY.size}`}
      role="img"
      aria-label={label}
      className="sky-plot"
    >
      {/* Elevation rings. The horizon is drawn with the strong stroke because it
          is a physical boundary, not a gridline. */}
      {RINGS.map((elDeg) => (
        <circle
          key={elDeg}
          cx={SKY.cx}
          cy={SKY.cy}
          r={(SKY.r * (90 - elDeg)) / 90}
          className={elDeg === 0 ? "plot-grid-strong" : "plot-grid"}
        />
      ))}
      <circle cx={SKY.cx} cy={SKY.cy} r={1.5} className="plot-grid" />

      {/* Cardinal spokes. Only four: a 30-degree rose would be eight more lines
          for information the labels already carry. */}
      {CARDINALS.map(([name, azDeg]) => {
        const [x2, y2] = projectSky(azDeg, 0);
        const [lx, ly] = projectSky(azDeg, -7.5);
        return (
          <g key={name}>
            <line x1={SKY.cx} y1={SKY.cy} x2={x2} y2={y2} className="plot-grid" />
            {/* The cardinals are the only glyphs in this plot that are not a
                measurement, so they take the label face while every tick label
                stays in the mono. That is the same split the rest of the console
                uses, drawn inside one SVG. */}
            <text
              x={lx}
              y={ly}
              className="plot-cardinal"
              textAnchor="middle"
              dominantBaseline="middle"
            >
              {name}
            </text>
          </g>
        );
      })}

      {/* Ring labels sit on the north spoke, offset so they do not sit under it.
          The zenith carries no label: the centre of a sky plot is 90 degrees by
          construction, and a label there sits under the track of exactly the
          overhead passes a reader is most likely to be looking at. */}
      {RINGS.filter((e) => e > 0).map((elDeg) => (
        <text
          key={`lbl-${elDeg}`}
          x={SKY.cx + 4}
          y={SKY.cy - (SKY.r * (90 - elDeg)) / 90 - 3}
          className="plot-label"
        >
          {elDeg}
        </text>
      ))}

      <path d={path} className="plot-track" />
      {/* The elapsed overlay. Hidden until the replay mounts, then revealed from the
          start of the path by the clock writing one stroke-dashoffset per frame. The
          full track stays visible underneath, so a reader who never presses play
          sees the whole pass and a reader who does sees how much of it has run. A
          point marker cannot carry that: it says where the satellite is now and
          nothing about where it has been.

          A second <path> repeating the same d, and not a <use> referencing the
          first, which was tried and does not work. Two things were wrong with it.
          The saving was 100 bytes, not the 6 kB it first appeared to be: that figure
          came from comparing a gzip measurement against a brotli one, and gzip
          spends almost nothing on a second copy of an identical long string. And
          the feature silently stopped painting. stroke-dasharray and
          stroke-dashoffset do inherit, and the computed values on the <use> were
          correct, but a <use> clones the referenced element WITH its class, so the
          clone still matches .plot-track, and a directly matched declaration beats
          an inherited one. The clone therefore drew in the track's own blue at the
          track's own width, dashed, directly over the solid original, and the page
          looked exactly as though nothing had been wired up. The DOM read correct
          throughout; only the pixels showed it. */}
      <path d={path} id="sky-trail" className="replay-trail" aria-hidden="true" />

      {/* Rise and set, drawn as an open ring and a square so the direction of
          travel is readable without an arrowhead, which at this scale would be
          three pixels of ambiguity. */}
      {firstAz !== undefined && firstEl !== undefined && firstEl >= 0 && (
        <circle
          cx={projectSky(firstAz, firstEl)[0]}
          cy={projectSky(firstAz, firstEl)[1]}
          r={3.5}
          className="plot-station"
        />
      )}
      {lastAz !== undefined && lastEl !== undefined && lastEl >= 0 && (
        <rect
          x={projectSky(lastAz, lastEl)[0] - 3}
          y={projectSky(lastAz, lastEl)[1] - 3}
          width={6}
          height={6}
          className="plot-station"
        />
      )}
      {tcaAz !== undefined && tcaEl !== undefined && (
        <circle
          cx={projectSky(tcaAz, tcaEl)[0]}
          cy={projectSky(tcaAz, tcaEl)[1]}
          r={4}
          className="plot-marker"
        />
      )}

      {/* The replay cursor. Rendered by the server so it is present in the HTML,
          and hidden by CSS until the replay marks itself ready, so a reader with
          scripting off never sees a cursor that cannot move. Its position is
          written as a transform on this one group and nothing else on the plot is
          touched, which is why a frame costs no layout and no restyle. */}
      <g id="sky-cursor" className="replay-cursor" aria-hidden="true">
        <circle r={6} />
        <circle r={1.75} className="replay-cursor-core" />
      </g>
    </svg>
  );
}
