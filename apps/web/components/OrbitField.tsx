/*
 * A pass, propagated: elevation above the horizon and the Doppler shift that same
 * pass implies, drawn against each other on one time axis.
 *
 * Why it exists. Seven of the eight pages on this console opened on a heading and a
 * paragraph, so they read as one undifferentiated document and a reader arrived at
 * each one already tired. This is the anchor for the pages that argue from geometry,
 * and it draws the thing the whole project is about: a satellite crosses, the
 * received frequency sweeps because it is moving, and the sweep has a shape fixed by
 * the geometry rather than by anything a model chose.
 *
 * What changed, and why the first version was wrong. It was one fragment shader over
 * one triangle: two amber curves, a dot, a star field and a faint limb. Rendered, it
 * was two similar squiggles floating in a black rectangle with no axis, no unit and
 * no label on either one, so a reader could not tell which curve was which without
 * reading four lines of caption, and could not read a value off either at all. A
 * figure on a page whose entire claim is that numbers come from somewhere cannot be a
 * decoration that resembles a chart. It is an instrument now: two panels on a shared
 * time axis, both scaled, both labelled, with the horizon drawn as a horizon and the
 * ground under it.
 *
 * The propagation is unchanged and is still the point. A circular orbit under a
 * two-body field, a rotating station on the surface beneath it, elevation and slant
 * range sampled across the visible window, and the Doppler shift taken from the range
 * rate that falls out of the same integration. Nothing is fitted and nothing is placed
 * by eye. An earlier draft drew a parabola and a tanh, because both are one line and
 * both look approximately right; on a page arguing that the corridor's shape is fixed
 * by geometry, a figure of that shape which was really two convenient closed forms is
 * the worst defect it could carry.
 *
 * What it is and is not. It is a propagation of the orbit given to it, and its caption
 * says so. It is NOT a measurement of any observation in the corpus: no receipt is read
 * here, no number on any page comes from this file, and nothing it draws is quoted
 * anywhere. That distinction is the reason the console is worth reading, so a
 * decorative element that blurred it would cost more than it gave. The corridor is
 * drawn in the same white the hero plate uses for its fitted corridor, because it is
 * the same quantity, and the reader who noticed that on the landing page should be
 * right about it here.
 *
 * No client JavaScript, and no WebGL. The old version needed a context, a compile, a
 * link, an IntersectionObserver, a `visibilitychange` listener and a reduced-motion
 * listener, and returned nothing at all on a driver that refused the context. This is
 * a server component: the curves are propagated once at build time and emitted as SVG,
 * and the only motion is three CSS animations whose keyframes are generated from the
 * same samples. Every one of them animates `transform` alone, so a frame costs a
 * composite and no layout, no paint and no path re-raster.
 *
 * The three moving marks share one keyframe schedule rather than an `offset-path`
 * each. `offset-distance` advances along arc length, and the elevation hump and the
 * Doppler sweep have different arc lengths per unit of time, so two marks driven that
 * way drift apart visibly by the middle of the pass. Explicit stops at the same
 * sample indices cannot drift: mark and read-head are on sample i at the same instant
 * by construction.
 *
 * Under `prefers-reduced-motion: reduce` the marks are placed at culmination and
 * nothing animates. The evidence is the frame, not the sweep, so nothing is withheld
 * from a reader who asked for less movement.
 */

import type { CSSProperties } from "react";

const SAMPLES = 48;

const MU = 398600.4418; // km^3 s^-2, WGS-84 gravitational parameter
const RE = 6378.137; // km, equatorial radius
const OMEGA_E = 7.2921159e-5; // rad/s, Earth rotation
const C_KM_S = 299792.458;

type Track = {
  /** Elevation in radians, one per sample, across the visible window. */
  elevations: number[];
  /** Doppler shift in Hz, one per sample, same instants. */
  shifts: number[];
  peakElevationDeg: number;
  maxShiftHz: number;
  durationS: number;
};

type Vec3 = [number, number, number];

/**
 * Propagate one pass and reduce it to two sampled series.
 *
 * A circular orbit is enough, and saying so is the point: the corridor's shape comes
 * from the geometry of a crossing, not from the eccentricity of any particular object,
 * so a circular orbit shows the shape without inviting a reader to think a specific
 * satellite is being modelled. Range rate is taken by central difference on the slant
 * range rather than by projecting the velocity vector, because the two agree well
 * below a pixel here and a finite difference cannot disagree with the range actually
 * plotted.
 */
function propagate(
  altitudeKm: number,
  inclinationDeg: number,
  stationLatDeg: number,
  frequencyMHz: number,
): Track {
  const a = RE + altitudeKm;
  const n = Math.sqrt(MU / (a * a * a)); // mean motion, rad/s
  const inc = (inclinationDeg * Math.PI) / 180;
  const lat = (stationLatDeg * Math.PI) / 180;

  // Orbit-plane basis, node placed so the ground track runs near the station. That is
  // what makes this a pass rather than a miss.
  const P: Vec3 = [1, 0, 0];
  const Q: Vec3 = [0, Math.cos(inc), Math.sin(inc)];

  const satAt = (t: number): Vec3 => {
    const c = Math.cos(n * t);
    const s = Math.sin(n * t);
    return [
      a * (c * P[0] + s * Q[0]),
      a * (c * P[1] + s * Q[1]),
      a * (c * P[2] + s * Q[2]),
    ];
  };

  // The station turns with the Earth. Over a ten-minute pass that is about 2.5 degrees
  // of longitude: small, but leaving it out tilts the corridor, which is the one
  // feature of the curve the figure exists to show.
  const stationAt = (t: number): Vec3 => {
    const lon = OMEGA_E * t;
    return [
      RE * Math.cos(lat) * Math.cos(lon),
      RE * Math.cos(lat) * Math.sin(lon),
      RE * Math.sin(lat),
    ];
  };

  const geometry = (t: number) => {
    const sat = satAt(t);
    const sta = stationAt(t);
    const rx = sat[0] - sta[0];
    const ry = sat[1] - sta[1];
    const rz = sat[2] - sta[2];
    const range = Math.hypot(rx, ry, rz);
    const staMag = Math.hypot(sta[0], sta[1], sta[2]);
    // Elevation is the complement of the angle between the slant vector and the local
    // vertical, which on a spherical Earth is the station vector itself.
    const sinEl = (rx * sta[0] + ry * sta[1] + rz * sta[2]) / (range * staMag);
    return { range, elevationRad: Math.asin(Math.max(-1, Math.min(1, sinEl))) };
  };

  // Scan one revolution coarsely for the culmination, then bisect out to both horizon
  // crossings. Steadier and cheaper than stepping finely across the whole orbit.
  const period = (2 * Math.PI) / n;
  let best = { t: 0, el: -Math.PI };
  for (let t = 0; t < period; t += 5) {
    const el = geometry(t).elevationRad;
    if (el > best.el) best = { t, el };
  }
  const horizon = (dir: number) => {
    let inside = best.t;
    let outside = best.t + dir * period * 0.25;
    for (let i = 0; i < 40; i++) {
      const mid = (inside + outside) / 2;
      if (geometry(mid).elevationRad > 0) inside = mid;
      else outside = mid;
    }
    return inside;
  };
  const tStart = horizon(-1);
  const span = Math.max(1, horizon(1) - tStart);

  const elevations: number[] = [];
  const shifts: number[] = [];
  let peak = 0;

  for (let i = 0; i < SAMPLES; i++) {
    const t = tStart + (i / (SAMPLES - 1)) * span;
    const { elevationRad } = geometry(t);
    const dt = 0.5;
    const rateKmS = (geometry(t + dt).range - geometry(t - dt).range) / (2 * dt);
    // Classical one-way Doppler, in the sign convention the console uses: a closing
    // range raises the received frequency.
    shifts.push((-rateKmS / C_KM_S) * frequencyMHz * 1e6);
    elevations.push(elevationRad);
    peak = Math.max(peak, elevationRad);
  }

  let maxShift = 0;
  for (const s of shifts) maxShift = Math.max(maxShift, Math.abs(s));

  return {
    elevations,
    shifts,
    peakElevationDeg: (peak * 180) / Math.PI,
    maxShiftHz: maxShift,
    durationS: span,
  };
}

/* ---------------------------------------------------------------------------
 * The frame.
 *
 * One viewBox, two panels, one time axis. Every constant below is a coordinate in
 * that box rather than a pixel, so the figure is resolution independent and the
 * caller's `height` only decides how large it is drawn.
 * ------------------------------------------------------------------------ */
const VB_W = 1000;
const VB_H = 356;

const PLOT_L = 62; // room for the elevation and frequency labels, inside the frame
const PLOT_R = 986;

const SKY_TOP = 22; // the zenith end of the elevation panel
const HORIZON = 196; // elevation 0, and the line the ground starts at
const GROUND_H = 13;

const DOP_TOP = 232; // the most positive shift
const DOP_ZERO = 279;
const DOP_BOT = 326; // the most negative shift

/** Two decimals: this is drawn in a 1000-unit box, so a hundredth of a unit is far
 *  below a device pixel and it keeps the emitted markup small. */
function path(points: Array<[number, number]>): string {
  return "M " + points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" L ");
}

/** A deterministic star field. Static, so it costs one paint and never a frame.
 *  The requirement is "no visible lattice", not "statistically sound", so a hash is
 *  enough and a seeded generator keeps the build reproducible: the same input has to
 *  emit the same bytes or the artifact digests this project publishes would move for
 *  a reason that is not a change. */
function stars(count: number) {
  const out: Array<{ x: number; y: number; r: number; o: number }> = [];
  let seed = 0x2f6e2b1;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
  for (let i = 0; i < count; i++) {
    const x = 6 + rnd() * (VB_W - 12);
    const y = 6 + rnd() * (HORIZON - 20);
    // Thin them out near the horizon, where the atmosphere plate is brightest and a
    // star would read as a stuck pixel rather than as a star.
    if (rnd() < (y / HORIZON) * 0.75) continue;
    out.push({ x, y, r: 0.5 + rnd() * 0.9, o: 0.12 + rnd() * 0.3 });
  }
  return out;
}

/**
 * The keyframe schedule the three marks share.
 *
 * `transform` only. A keyframe that moved `cx` or `x` would invalidate the path and
 * repaint the layer every frame; a translate is a composite and costs the same at any
 * size. Both marks and the read line are emitted at the origin and translated into
 * place, which is why every stop below is an absolute position rather than a delta.
 */
function keyframes(name: string, points: Array<[number, number]>): string {
  const last = points.length - 1;
  const stops = points.map(([x, y], i) => {
    const pct = ((i / last) * 100).toFixed(3);
    return `${pct}%{transform:translate(${x.toFixed(2)}px,${y.toFixed(2)}px)}`;
  });
  return `@keyframes ${name}{${stops.join("")}}`;
}

export default function OrbitField({
  altitudeKm = 550,
  inclinationDeg = 97.6,
  stationLatDeg = 52.2,
  frequencyMHz = 437,
  label,
}: {
  altitudeKm?: number;
  inclinationDeg?: number;
  stationLatDeg?: number;
  frequencyMHz?: number;
  /** Said out loud under the frame. A drawing that could be mistaken for a measurement
   *  on a page of measurements has to name itself. */
  label?: string;
}) {
  const track = propagate(altitudeKm, inclinationDeg, stationLatDeg, frequencyMHz);
  const peakRad = (track.peakElevationDeg * Math.PI) / 180;

  const xAt = (i: number) => PLOT_L + (i / (SAMPLES - 1)) * (PLOT_R - PLOT_L);
  // The elevation axis is linear in degrees and topped at the pass's own culmination,
  // which is why a low pass and a high one both fill the panel. The number is printed
  // on the axis, so the scale can never be mistaken for a fixed one.
  const yEl = (rad: number) => HORIZON - (rad / (peakRad || 1)) * (HORIZON - SKY_TOP);
  // Symmetric about zero on purpose. A Doppler sweep is very nearly antisymmetric and
  // an axis that was not would put the crossing off centre and imply a bias the
  // geometry does not have.
  //
  // The 1.12 is headroom, and it is not cosmetic. Scaled to the extreme exactly, the
  // sweep's first and last samples land on the panel's own top and bottom edge, where a
  // 2px stroke is half outside the box and the read-head is a half-disc. A twelfth of
  // the range keeps every sample and both marks inside the frame they are drawn in.
  const DOP_HEADROOM = 1.12;
  const yDop = (hz: number) =>
    DOP_ZERO -
    (hz / ((track.maxShiftHz || 1) * DOP_HEADROOM)) * (DOP_ZERO - DOP_TOP);

  const elPoints: Array<[number, number]> = track.elevations.map((e, i) => [
    xAt(i),
    yEl(e),
  ]);
  const dopPoints: Array<[number, number]> = track.shifts.map((s, i) => [
    xAt(i),
    yDop(s),
  ]);
  const readPoints: Array<[number, number]> = track.shifts.map((_, i) => [xAt(i), 0]);

  const elPath = path(elPoints);
  const dopPath = path(dopPoints);
  // Closed down to the horizon: the area under an elevation curve is the part of the
  // pass the station can actually hear, and shading it says that in one mark.
  const elArea = `${elPath} L ${PLOT_R.toFixed(2)},${HORIZON} L ${PLOT_L.toFixed(2)},${HORIZON} Z`;

  // Culmination, for the reduced-motion resting position and for the peak label.
  let peakIndex = 0;
  track.elevations.forEach((e, i) => {
    if (e > (track.elevations[peakIndex] ?? 0)) peakIndex = i;
  });

  const minutes = track.durationS / 60;
  const kHz = track.maxShiftHz / 1000;
  // Gridlines for the pass this figure was given, not for a pass it was not. The
  // elevation axis is topped at the culmination, so a fixed 30/60 set draws nothing at
  // all below 36 degrees: at the default 550 km orbit the peak is 26.2, and the panel
  // shipped with no gridline and no readable elevation anywhere between 0 and the top.
  const gridDegs = [5, 10, 15, 20, 30, 45, 60, 75]
    .filter((d) => d < track.peakElevationDeg - 4)
    .reverse()
    .filter((_, i, all) => all.length <= 3 || i % Math.ceil(all.length / 3) === 0)
    .slice(0, 3);

  const css = [
    keyframes("orbit-sat", elPoints),
    keyframes("orbit-read", dopPoints),
    keyframes("orbit-scrub", readPoints),
    // One duration, one timing function, one iteration count, declared once and shared,
    // because three marks that are meant to be the same instant must not be able to
    // drift apart in a stylesheet edit.
    `.orbit-mark{animation-duration:26s;animation-timing-function:linear;` +
      `animation-iteration-count:infinite;animation-fill-mode:both}`,
    `.orbit-sat{animation-name:orbit-sat}`,
    `.orbit-read{animation-name:orbit-read}`,
    `.orbit-scrub{animation-name:orbit-scrub}`,
    // The resting frame. `reduce` is not "the same thing, faster": it is the pass at
    // its culmination with every mark where a reader would put a ruler.
    `@media (prefers-reduced-motion: reduce){.orbit-mark{animation:none;` +
      `transform:translate(var(--rest-x),var(--rest-y))}}`,
  ].join("");

  const caption =
    label ??
    `A ${altitudeKm} km circular orbit at ${inclinationDeg} degrees, propagated over one ` +
      `pass above a station at ${stationLatDeg} degrees north: ${Math.round(minutes)} minutes ` +
      `above the horizon, peaking at ${track.peakElevationDeg.toFixed(1)} degrees. The lower ` +
      `curve is the Doppler shift that pass's range rate implies at ${frequencyMHz} MHz, ` +
      `plus or minus ${kHz.toFixed(1)} kHz. Propagated for this figure, not measured: every ` +
      `number this console publishes comes from a receipt.`;

  return (
    <figure className="orbit-field">
      <style dangerouslySetInnerHTML={{ __html: css }} />
      {/* Sized by its own aspect, and there is no height prop to override it.
          There was one, and with a width of 100% and a fixed height both set, the
          default `xMidYMid meet` fitted a 2.81 to 1 viewBox into a 3.95 to 1 box by
          height: the drawing came out 843px wide inside a 1184px frame with 170px of
          empty black down each side. A viewBox has an aspect ratio and a caller who
          also names a height is telling it two different things. */}
      {/* A 1000-unit frame squeezed into a 358px phone renders its 13px axis labels at
          4.7px, which is a picture of an axis rather than an axis. Below 48rem the frame
          keeps a floor and this scrolls, the same treatment and the same reason as every
          table on this console: a scroll container nobody can reach with a keyboard is a
          column nobody can read. WCAG 2.1.1. */}
      <div
        className="orbit-scroll"
        tabIndex={0}
        role="region"
        aria-label="Pass geometry and Doppler, scrollable"
      >
      <svg
        className="orbit-svg"
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        role="img"
        aria-label={caption}
      >
        <defs>
          <linearGradient id="orbit-air" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3d6ea8" stopOpacity="0" />
            <stop offset="70%" stopColor="#3d6ea8" stopOpacity="0.16" />
            <stop offset="100%" stopColor="#7fb2e6" stopOpacity="0.42" />
          </linearGradient>
          <linearGradient id="orbit-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--interactive-01)" stopOpacity="0.30" />
            <stop offset="100%" stopColor="var(--interactive-01)" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* --- the sky ------------------------------------------------------- */}
        <rect x="0" y="0" width={VB_W} height={HORIZON} fill="#06080e" />
        {stars(150).map((s, i) => (
          <circle key={i} cx={s.x} cy={s.y} r={s.r} fill="#cfe0ff" opacity={s.o} />
        ))}
        {/* Airglow. It is the one purely pictorial mark in the frame and it earns its
            place: without it the horizon is a rule across a black box and the panel
            does not read as looking up at anything. */}
        <rect x="0" y={HORIZON - 58} width={VB_W} height={58} fill="url(#orbit-air)" />

        {/* --- elevation gridlines ------------------------------------------- */}
        {gridDegs.map((d) => {
          const y = yEl((d * Math.PI) / 180);
          return (
            <g key={d}>
              <line
                x1={PLOT_L}
                y1={y}
                x2={PLOT_R}
                y2={y}
                stroke="var(--border-subtle)"
                strokeWidth="1"
                strokeDasharray="2 6"
                opacity="0.7"
              />
              <text x="8" y={y + 4} className="orbit-tick">
                {d}
                {"°"}
              </text>
            </g>
          );
        })}

        {/* --- the pass ------------------------------------------------------- */}
        <path d={elArea} fill="url(#orbit-fill)" />
        <path
          d={elPath}
          fill="none"
          stroke="var(--interactive-01)"
          strokeWidth="2"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />

        {/* --- the horizon, and the ground under it ---------------------------- */}
        <rect x="0" y={HORIZON} width={VB_W} height={GROUND_H} fill="#0a0c11" />
        <line
          x1="0"
          y1={HORIZON}
          x2={VB_W}
          y2={HORIZON}
          stroke="#4a5a72"
          strokeWidth="1"
        />
        <text x="8" y={HORIZON - 7} className="orbit-tick">
          0{"°"}
        </text>

        {/* --- the Doppler panel ----------------------------------------------- */}
        <line
          x1={PLOT_L}
          y1={DOP_ZERO}
          x2={PLOT_R}
          y2={DOP_ZERO}
          stroke="var(--border-subtle)"
          strokeWidth="1"
          strokeDasharray="2 6"
        />
        <text x="8" y={yDop(track.maxShiftHz) + 4} className="orbit-tick">
          +{kHz.toFixed(1)}k
        </text>
        <text x="8" y={DOP_ZERO + 4} className="orbit-tick">
          0
        </text>
        <text x="8" y={yDop(-track.maxShiftHz) + 4} className="orbit-tick">
          {"−"}
          {kHz.toFixed(1)}k
        </text>
        {/* Cased, then drawn. The same treatment the hero plate gives its fitted
            corridor, and for the same reason: this is that quantity. */}
        <path
          d={dopPath}
          fill="none"
          stroke="#05070c"
          strokeWidth="5"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={dopPath}
          fill="none"
          stroke="#f4f4f4"
          strokeWidth="2"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />

        {/* --- the marks, all three on one schedule ---------------------------- */}
        <g
          className="orbit-mark orbit-scrub"
          style={
            {
              "--rest-x": `${xAt(peakIndex).toFixed(2)}px`,
              "--rest-y": "0px",
            } as CSSProperties
          }
        >
          <line
            x1="0"
            y1={SKY_TOP}
            x2="0"
            y2={DOP_BOT}
            stroke="var(--interactive-01)"
            strokeWidth="1"
            opacity="0.34"
          />
        </g>
        <g
          className="orbit-mark orbit-sat"
          style={
            {
              "--rest-x": `${xAt(peakIndex).toFixed(2)}px`,
              "--rest-y": `${yEl(track.elevations[peakIndex] ?? 0).toFixed(2)}px`,
            } as CSSProperties
          }
        >
          <circle r="11" fill="var(--interactive-01)" opacity="0.18" />
          <circle r="4.5" fill="#ffffff" />
        </g>
        <g
          className="orbit-mark orbit-read"
          style={
            {
              "--rest-x": `${xAt(peakIndex).toFixed(2)}px`,
              "--rest-y": `${yDop(track.shifts[peakIndex] ?? 0).toFixed(2)}px`,
            } as CSSProperties
          }
        >
          <circle r="3.4" fill="#ffffff" stroke="#05070c" strokeWidth="1.4" />
        </g>

        {/* --- what each panel is ---------------------------------------------- */}
        <text x={PLOT_L} y={SKY_TOP - 6} className="orbit-axis">
          Elevation, peak {track.peakElevationDeg.toFixed(1)}
          {"°"}
        </text>
        <text x={PLOT_L} y={DOP_TOP - 8} className="orbit-axis">
          Doppler shift at {frequencyMHz} MHz
        </text>
        <text x={PLOT_R} y={VB_H - 6} className="orbit-axis orbit-axis-end">
          One pass, {minutes.toFixed(0)} min, time {String.fromCharCode(0x2192)}
        </text>
      </svg>
      </div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}
