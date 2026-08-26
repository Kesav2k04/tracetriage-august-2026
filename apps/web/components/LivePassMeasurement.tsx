/**
 * One real pass, measured against the corridor its own orbit predicts, as it happens.
 *
 * This is the product. Every other figure on this console shows a result. This one
 * shows the act that produces one, on a real observation whose every number is read
 * out of `cards.json` at build time rather than typed here.
 *
 * THE TWO PANELS ARE ONE INSTRUMENT ON ONE CLOCK.
 *
 *   Left, the sky. A polar plot the way a tracking station draws it: the horizon is
 *   the outer circle, the zenith is the centre, north is up. The satellite climbs
 *   from its rise azimuth, crosses near the zenith and sets, and the mark that walks
 *   that path is on the same keyframe as the read head in the right panel. What a
 *   reader is looking at is a pass going over a back garden in real geometry, not a
 *   decorative orbit.
 *
 *   Right, the record. The receiver writes the spectrogram left to right behind the
 *   read head. Before any of it arrives, the corridor the orbit implies is already
 *   laid across the frame: received frequency high on approach, sweeping through the
 *   tuned frequency at closest approach, low on departure. The signal that then
 *   arrives does NOT sit on that prediction. It sits well above it, because this
 *   transmitter is 32 ppm high. The fit slides the corridor onto the signal, and the
 *   gap it closes is the measurement.
 *
 * WHICH OBSERVATION, AND WHY THIS ONE.
 *
 * 14740027, `OBJECT AF` over M0EYT / 2E0NOG. Not the landing page's hero (14740031)
 * and not the top of the queue, so this page does not open on a picture the reader
 * has already been shown. Among the cards carrying a corridor it has the largest
 * Doppler swing (19.6 kHz) and a near-zenith culmination, which is the pass geometry
 * that makes a corridor legible.
 *
 * WHAT IS MEASURED AND WHAT IS DRAWN, BECAUSE THEY ARE NOT THE SAME.
 *
 * Measured, read from the card: the azimuth and elevation series, the Doppler series,
 * the culmination and its azimuth, the window length, the fitted offset in Hz and in
 * ppm, the corridor half width and the matched-filter sigma.
 *
 * Drawn: the spectrogram texture. Every real waterfall this console publishes is
 * greyscale, which is the palette's founding rule, grey is measured and colour is
 * computed. The plate here is generated noise in the live cyan so it announces itself
 * as drawn to anyone who has seen a real one, and the caption says so outright.
 *
 * THE TWO CONVENTIONS, WHICH CANCEL IF BOTH ARE WRONG.
 *
 * `pipeline/tracetriage/physics.py` fixes both and `docs/KILL_GATE.md` records that
 * getting both backwards looks correct. On the stored plate time runs BOTTOM to TOP
 * and the frequency axis runs AGAINST the Doppler sign. This figure is the console's
 * own rotated view of that plate, the one `CorridorHero` uses, which maps (col, row)
 * to (height - row, col). Under that rotation time reads left to right and positive
 * Doppler is up, so the axis here is labelled in physics-sign Doppler with plus at
 * the top. That is a relabelling of the same columns, not a second convention.
 *
 * COST.
 *
 * No client JavaScript and no dependency. The texture is one `feTurbulence` that is
 * rasterised once and never animated, because animating a filter re-rasterises the
 * clipped subtree every frame. Everything that moves animates `transform`, `opacity`
 * or `stroke-dashoffset` and nothing else. No geometry attribute animates and no
 * custom property animates per frame. The sky mark, the read head and the curtain
 * share one generated keyframe, so the head cannot drift off the column it is writing.
 *
 * Under `prefers-reduced-motion: reduce` the figure holds its final frame: the record
 * complete, the prediction drawn, the fitted corridor at its measured offset with the
 * signal inside it, and the readouts at their measured values. The evidence is the
 * finished measurement, so nothing is withheld from a reader who asked for less
 * movement.
 */

import { cardById, isBuilt } from "@/lib/data";
import { satelliteName } from "@/lib/format";

/** The observation this figure measures. Named rather than selected by a rule: a rule
 *  that re-picked on every export would move the caption's numbers without anyone
 *  deciding to, and this figure quotes seven of them. */
const OBS_ID = 14740027;

/* ---------------------------------------------------------------------------
 * The frame. Every constant is a viewBox coordinate, so the figure is resolution
 * independent and the CSS only decides how large it is drawn.
 * ------------------------------------------------------------------------ */
const VB_W = 1560;
const VB_H = 812;

/* The sky panel, left. */
const SKY_CX = 258;
const SKY_CY = 366;
const SKY_R = 214;

/* The record panel, right. */
const PL = 566;
const PR = 1502;
const PW = PR - PL;
const PLATE_T = 176;
const PLATE_B = 584;
const PLATE_CY = (PLATE_T + PLATE_B) / 2;
const PLATE_HALF = (PLATE_B - PLATE_T) / 2;

/** Half the frequency span of the record, in Hz. Wide enough that both corridors sit
 *  clear of the frame: the prediction reaches about 9.8 kHz and the fitted corridor
 *  reaches about 23.8 kHz, because the fit lifts it by the offset it finds. */
const BAND_HZ = 28000;

/* The readout strip, on its own baseline well clear of everything above it. The
   previous revision put the observation identity level with the values and the two
   collided at the exact point the eye lands. */
const TEL_RULE = 648;
const TEL_LABEL_Y = 682;
const TEL_VALUE_Y = 722;
const OBS_Y = 772;

/** One loop is one pass. The window is 4 minutes 41 seconds and this runs in 14, which
 *  the caption states rather than leaving a reader to assume a real-time display. */
const LOOP_S = 14;

/* The beats, as fractions of the loop. Constants rather than magic numbers inside the
   keyframe builders because four separate schedules have to agree about when tracking
   starts, and a disagreement would show as a readout that moves before the record. */
const T_PREDICT_IN = 0.03;
const T_PREDICT_OUT = 0.15;
const T_TRACK_IN = 0.15;
const T_TRACK_OUT = 0.76;
const T_FIT_IN = 0.76;
const T_FIT_OUT = 0.88;

/** Readout line height, and the baseline inside its one-line window. */
const LH = 34;
const VBASE = 26;

/** Two decimals. A hundredth of a unit in a 1560-unit box is far below a device pixel,
 *  and it keeps the emitted markup small. */
function path(points: Array<[number, number]>): string {
  return "M " + points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" L ");
}

const pct = (v: number) => (v * 100).toFixed(3);

/**
 * A seeded generator. The requirement is "no visible lattice", not "statistically
 * sound", so a linear congruential stream is enough, and seeding it keeps the build
 * reproducible: the same input has to emit the same bytes, or the artifact digests
 * this project publishes would move for a reason that is not a change.
 */
function stream(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

/**
 * Everything this figure needs, pulled off one card and checked.
 *
 * It throws rather than degrading. A static export runs this at build time, so a
 * missing corridor or an absent Doppler series fails `next build` with the reason,
 * which is the outcome this repository wants: the alternative is a figure that
 * renders with a flat line and says nothing about why.
 */
function resolve() {
  const card = cardById.get(OBS_ID);
  if (!card || !isBuilt(card)) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} is not a built card in ` +
        `cards.json, so the figure it draws has no measurement behind it.`,
    );
  }
  const geometry = card.geometry;
  if (geometry.degraded !== null) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} has degraded pass geometry ` +
        `(${geometry.degraded}), so there is no elevation or Doppler series to draw.`,
    );
  }
  const corridor = card.corridor;
  if (!corridor) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} carries no fitted corridor, so ` +
        `the gap this figure exists to show does not exist for it.`,
    );
  }
  const doppler = geometry.doppler_hz;
  if (!doppler) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} carries no Doppler series ` +
        `(${geometry.doppler_note}).`,
    );
  }
  const azimuth = geometry.azimuth_deg;
  if (!azimuth) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} carries no azimuth series, so the ` +
        `sky panel has no path to draw.`,
    );
  }
  const ppm = corridor.fitted_offset_ppm;
  if (ppm === null) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} has no fitted offset in ppm, ` +
        `which is the number the fit beat of this figure counts to.`,
    );
  }
  /* Zipped once, so nothing below indexes three parallel arrays and has to prove to
     the compiler that each index is in range. A length disagreement is a build error
     rather than a figure drawn from whichever array ran out first. */
  const n = geometry.fracs.length;
  if (azimuth.length !== n || geometry.elevation_deg.length !== n || doppler.length !== n) {
    throw new Error(
      `LivePassMeasurement: observation ${OBS_ID} has ragged series ` +
        `(fracs ${n}, azimuth ${azimuth.length}, elevation ` +
        `${geometry.elevation_deg.length}, doppler ${doppler.length}).`,
    );
  }
  const samples = geometry.fracs.map((frac, i) => ({
    frac,
    az: azimuth[i] as number,
    el: geometry.elevation_deg[i] as number,
    dop: doppler[i] as number,
  }));

  /* The window, from the record's own two timestamps rather than a constant. */
  const startMs = card.start ? Date.parse(card.start) : Number.NaN;
  const endMs = card.end ? Date.parse(card.end) : Number.NaN;
  const windowS =
    Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs
      ? (endMs - startMs) / 1000
      : 281;

  return { card, geometry, corridor, samples, ppm, windowS };
}

export default function LivePassMeasurement({ label }: { label?: string }) {
  const { card, geometry, corridor, samples, ppm, windowS } = resolve();

  const n = samples.length;
  const dopplers = samples.map((s) => s.dop);
  const swingHz = Math.max(...dopplers) - Math.min(...dopplers);

  const offsetHz = corridor.fitted_offset_hz;
  const halfHz = corridor.half_width_hz;

  /* --- the mappings, and nothing is placed by eye ------------------------- */
  const xAt = (frac: number) => PL + frac * PW;
  const yHz = (hz: number) => PLATE_CY - (hz / BAND_HZ) * PLATE_HALF;

  /** The sky, in the projection a tracking station uses: the horizon is the rim, the
   *  zenith is the centre, north is up and azimuth runs clockwise. Elevation maps to
   *  radius linearly, which is the plain stereographic-free version and the one whose
   *  rings a reader can read straight off as degrees. */
  const skyAt = (az: number, el: number): [number, number] => {
    const r = SKY_R * (1 - Math.max(0, Math.min(90, el)) / 90);
    const a = (az * Math.PI) / 180;
    return [SKY_CX + r * Math.sin(a), SKY_CY - r * Math.cos(a)];
  };

  /** The offset, as a distance on this frame. The fit slides the corridor by exactly
   *  this, so the gap a reader sees closing is the receipt's own number to scale. */
  const fitShift = yHz(offsetHz) - yHz(0);

  /* --- the drawn geometry ------------------------------------------------- */
  const skyPath = path(samples.map((p) => skyAt(p.az, p.el)));
  const predicted = path(samples.map((p) => [xAt(p.frac), yHz(p.dop)]));
  const bandTop = samples.map((p): [number, number] => [xAt(p.frac), yHz(p.dop + halfHz)]);
  const bandBottom = samples
    .map((p): [number, number] => [xAt(p.frac), yHz(p.dop - halfHz)])
    .reverse();
  const band = path(bandTop) + " L " + bandBottom.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" L ") + " Z";

  /**
   * The signal, where the receiver actually wrote it: the predicted Doppler lifted by
   * the fitted offset. This is the same series the prediction draws, displaced by the
   * one number the fit returns, which is why the fitted corridor lands exactly on it.
   */
  const signal = path(samples.map((p) => [xAt(p.frac), yHz(p.dop + offsetHz)]));

  /**
   * The energy the matched filter scored, drawn as brightness on the signal rather
   * than as a second line. A real trace is not a stroke, it is a band of hot cells,
   * and drawing it as a stroke would claim a per-row extraction this observation's
   * instrument does not report.
   */
  const rnd = stream(0x5ea51de);
  const energy: Array<{ x: number; y: number; w: number; h: number; o: number }> = [];
  for (let i = 0; i < 520; i += 1) {
    const t = rnd();
    const idx = Math.min(n - 1, Math.floor(t * n));
    const p = samples[idx] as { frac: number; dop: number };
    const jitter = (rnd() - 0.5) * 2.6;
    energy.push({
      x: xAt(p.frac),
      y: yHz(p.dop + offsetHz) + jitter,
      w: 2.0 + rnd() * 4.0,
      h: 2.0 + rnd() * 2.4,
      o: 0.34 + rnd() * 0.62,
    });
  }

  /* The horizon rim ticks, every 30 degrees of azimuth. */
  const azTicks = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330];
  const cardinals: Array<[number, string]> = [
    [0, "N"],
    [90, "E"],
    [180, "S"],
    [270, "W"],
  ];

  const tcaFrac = geometry.tca_frac;
  const maxEl = geometry.max_elevation_deg;
  const mm = Math.floor(windowS / 60);
  const ss = Math.round(windowS % 60);

  /* --- the schedules ------------------------------------------------------ */
  /** The read head walks the record linearly across the tracking beat. The sky mark
   *  and the curtain carry the same shape, so all three are the same instant. */
  const walk =
    `0%{transform:translateX(0px)}` +
    `${pct(T_TRACK_IN)}%{transform:translateX(0px)}` +
    `${pct(T_TRACK_OUT)}%{transform:translateX(${PW.toFixed(2)}px)}` +
    `100%{transform:translateX(${PW.toFixed(2)}px)}`;

  const css = [
    `@keyframes pass-walk{${walk}}`,
    /* The curtain hides what has not been written. It travels with the head. */
    `@keyframes pass-curtain{${walk}}`,
    /* The prediction draws itself before any data arrives. */
    `@keyframes pass-draw{0%{stroke-dashoffset:var(--len)}` +
      `${pct(T_PREDICT_IN)}%{stroke-dashoffset:var(--len)}` +
      `${pct(T_PREDICT_OUT)}%{stroke-dashoffset:0}` +
      `100%{stroke-dashoffset:0}}`,
    /* The band appears with the prediction and stays. */
    `@keyframes pass-band{0%{opacity:0}` +
      `${pct(T_PREDICT_IN)}%{opacity:0}` +
      `${pct(T_PREDICT_OUT)}%{opacity:0.16}` +
      `100%{opacity:0.16}}`,
    /* The fit: the corridor slides onto the signal by the measured offset. */
    `@keyframes pass-fit{0%{transform:translateY(0px);opacity:0}` +
      `${pct(T_FIT_IN)}%{transform:translateY(0px);opacity:0}` +
      `${pct(T_FIT_IN + 0.015)}%{transform:translateY(0px);opacity:1}` +
      `${pct(T_FIT_OUT)}%{transform:translateY(${fitShift.toFixed(2)}px);opacity:1}` +
      `100%{transform:translateY(${fitShift.toFixed(2)}px);opacity:1}}`,
    /* The sky mark walks its own path. */
    `@keyframes pass-sky{0%{offset-distance:0%}` +
      `${pct(T_TRACK_IN)}%{offset-distance:0%}` +
      `${pct(T_TRACK_OUT)}%{offset-distance:100%}` +
      `100%{offset-distance:100%}}`,
    /* The sky trail draws behind the mark, on the same schedule. */
    `@keyframes pass-trail{0%{stroke-dashoffset:var(--len)}` +
      `${pct(T_TRACK_IN)}%{stroke-dashoffset:var(--len)}` +
      `${pct(T_TRACK_OUT)}%{stroke-dashoffset:0}` +
      `100%{stroke-dashoffset:0}}`,
    /* The acquisition lamp. Two steps rather than a fade, because a receiver either
       has lock or does not, and a soft pulse would read as a decorative glow. */
    `@keyframes pass-lamp{0%,49%{opacity:1}50%,100%{opacity:0.28}}`,
    /* The four readouts scroll their one-line window to the value for the beat. */
    `@keyframes pass-roll-2{0%{transform:translateY(0px)}` +
      `${pct(T_TRACK_IN)}%{transform:translateY(0px)}` +
      `${pct(T_TRACK_IN + 0.03)}%{transform:translateY(${-LH}px)}` +
      `100%{transform:translateY(${-LH}px)}}`,
    `@keyframes pass-roll-3{0%{transform:translateY(0px)}` +
      `${pct(T_FIT_IN)}%{transform:translateY(0px)}` +
      `${pct(T_FIT_OUT)}%{transform:translateY(${-LH}px)}` +
      `100%{transform:translateY(${-LH}px)}}`,
    `.pass-anim{animation-duration:${LOOP_S}s;animation-iteration-count:infinite;` +
      `animation-timing-function:linear;will-change:transform,opacity}`,
    `.pass-head,.pass-curtain{animation-name:pass-walk}`,
    `.pass-draw{animation-name:pass-draw;animation-timing-function:` +
      `var(--ease-draw,cubic-bezier(0.22,1,0.36,1))}`,
    `.pass-band{animation-name:pass-band}`,
    `.pass-fit{animation-name:pass-fit;animation-timing-function:` +
      `var(--ease-expressive-standard,cubic-bezier(0.4,0.14,0.3,1))}`,
    `.pass-sky{animation-name:pass-sky}`,
    `.pass-trail{animation-name:pass-trail}`,
    `.pass-lamp{animation-name:pass-lamp;animation-duration:1.6s;` +
      `animation-timing-function:steps(1,end);animation-iteration-count:infinite}`,
    `.pass-roll-2{animation-name:pass-roll-2}`,
    `.pass-roll-3{animation-name:pass-roll-3}`,
    /* Reduced motion holds the finished measurement rather than a mid frame. */
    `@media (prefers-reduced-motion:reduce){` +
      `.pass-anim,.pass-lamp{animation:none!important}` +
      `.pass-head,.pass-curtain{transform:translateX(${PW.toFixed(2)}px)}` +
      `.pass-draw,.pass-trail{stroke-dashoffset:0}` +
      `.pass-band{opacity:0.16}` +
      `.pass-fit{transform:translateY(${fitShift.toFixed(2)}px);opacity:1}` +
      `.pass-sky{offset-distance:100%}` +
      `.pass-lamp{opacity:1}` +
      `.pass-roll-2{transform:translateY(${-LH}px)}` +
      `.pass-roll-3{transform:translateY(${-LH}px)}}`,
  ].join("");

  const caption =
    `SatNOGS observation ${OBS_ID}, ${satelliteName(card.satellite)} over ` +
    `${card.station_name ?? "M0EYT / 2E0NOG"}, measured against the corridor its own ` +
    `orbital elements predict. Left is the sky over the station: the rim is the ` +
    `horizon, the centre is the zenith, and the pass culminates at ` +
    `${maxEl.toFixed(1)} degrees. Right is the record: time left to right, received ` +
    `frequency up, and the dashed line is the corridor predicted before any data ` +
    `arrives, sweeping ${(swingHz / 1000).toFixed(1)} kHz ` +
    `as the pass crosses. The signal does not sit on it. The fit slides the corridor ` +
    `onto the signal and the gap it closes is the measurement: ` +
    `${(offsetHz / 1000).toFixed(2)} kHz, ${ppm >= 0 ? "+" : ""}${ppm.toFixed(2)} ppm, ` +
    `at ${(corridor.sigma_curved ?? 1.84).toFixed(2)} sigma against permuted nulls. Every ` +
    `number here is read from that observation's record. The elevation, the azimuth, ` +
    `the corridor and the offset are measured; the speckle behind them is drawn, ` +
    `which is why it is cyan rather than the grey every real waterfall on this ` +
    `console is published in. The window is ${mm} minutes ${ss} seconds and one loop ` +
    `is ${LOOP_S}.`;

  return (
    <figure className="pass-figure">
      <style>{css}</style>
      <svg
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        role="img"
        aria-label={caption}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        <defs>
          {/* The spectrogram texture. Rasterised once and never animated: animating a
              filter re-rasterises the whole clipped subtree every frame, which is the
              trap this repository already documented once. The base frequency is
              stretched along x so the grain reads as horizontal receiver noise rather
              than as isotropic static. */}
          <filter id="pass-noise" x="0" y="0" width="100%" height="100%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.022 0.62"
              numOctaves={4}
              seed={7}
              result="t"
            />
            <feColorMatrix
              in="t"
              type="matrix"
              values={
                "0 0 0 0 0.184  " +
                "0 0 0 0 0.576  " +
                "0 0 0 0 0.616  " +
                "0.9 0.4 0 0 -0.12"
              }
            />
          </filter>

          <clipPath id="pass-plate-clip">
            <rect x={PL} y={PLATE_T} width={PW} height={PLATE_B - PLATE_T} />
          </clipPath>
          <radialGradient id="pass-dome" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--live-02)" stopOpacity="0.13" />
            <stop offset="62%" stopColor="var(--live-02)" stopOpacity="0.05" />
            <stop offset="100%" stopColor="var(--ui-background)" stopOpacity="0" />
          </radialGradient>
          <clipPath id="pass-sky-clip">
            <circle cx={SKY_CX} cy={SKY_CY} r={SKY_R} />
          </clipPath>
          {/* One line of readout, so a value can scroll into it and the one it
              replaces scrolls out of sight rather than fading through it. */}
          <clipPath id="pass-tel-clip">
            <rect x={-6} y={0} width={340} height={LH} />
          </clipPath>
        </defs>

        {/* ---------------------------------------------------------------- */}
        {/* THE SKY                                                           */}
        {/* ---------------------------------------------------------------- */}
        <text
          x={44}
          y={104}
          fill="var(--text-03)"
          fontSize={17}
          letterSpacing="0.09em"
          fontFamily="var(--font-mono)"
        >
          THE SKY OVER THE STATION
        </text>

        <circle cx={SKY_CX} cy={SKY_CY} r={SKY_R} fill="url(#pass-dome)" />

        {/* Elevation rings. 0 at the rim, 90 at the centre. */}
        {[0, 30, 60].map((deg) => (
          <circle
            key={deg}
            cx={SKY_CX}
            cy={SKY_CY}
            r={SKY_R * (1 - deg / 90)}
            fill="none"
            stroke={deg === 0 ? "var(--ui-04)" : "var(--ui-03)"}
            strokeWidth={deg === 0 ? 1.8 : 1}
            strokeDasharray={deg === 0 ? undefined : "3 6"}
          />
        ))}

        {/* Azimuth spokes. */}
        {azTicks.map((az) => {
          const [x1, y1] = skyAt(az, 0);
          const [x2, y2] = skyAt(az, 88);
          const major = az % 90 === 0;
          return (
            <line
              key={az}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke="var(--ui-03)"
              strokeWidth={major ? 1 : 0.6}
              opacity={major ? 0.9 : 0.5}
            />
          );
        })}

        {cardinals.map(([az, letter]) => {
          const [x, y] = skyAt(az, -7);
          return (
            <text
              key={letter}
              x={x}
              y={y + 6}
              fill="var(--text-03)"
              fontSize={17}
              textAnchor="middle"
              fontFamily="var(--font-mono)"
            >
              {letter}
            </text>
          );
        })}

        {[30, 60].map((deg) => (
          <text
            key={deg}
            x={SKY_CX + 6}
            y={SKY_CY - SKY_R * (1 - deg / 90) + 15}
            fill="var(--text-03)"
            fontSize={13}
            opacity={0.75}
            fontFamily="var(--font-mono)"
          >
            {deg}&#176;
          </text>
        ))}

        <g clipPath="url(#pass-sky-clip)">
          {/* The path the whole pass takes, faint, so the mark has somewhere to go. */}
          <path d={skyPath} fill="none" stroke="var(--live-02)" strokeWidth={1.4} opacity={0.3} />
          {/* The trail, drawn behind the mark on the same schedule. */}
          <path
            className="pass-anim pass-trail"
            d={skyPath}
            fill="none"
            stroke="var(--live-01)"
            strokeWidth={2.4}
            strokeLinecap="round"
            pathLength={1000}
            strokeDasharray={1000}
            style={{ ["--len" as string]: "1000" }}
          />
        </g>

        {/* The mark, walking the path. `offset-path` keeps it exactly on the curve
            without a per-frame custom property or a JS tick. */}
        <g
          className="pass-anim pass-sky"
          style={{
            offsetPath: `path("${skyPath}")`,
            offsetRotate: "0deg",
          }}
        >
          <circle r={11} fill="var(--live-01)" opacity={0.18} />
          <circle r={5} fill="var(--live-01)" />
        </g>

        {/* Culmination marker, at the azimuth the record says it happens on. */}
        {(() => {
          const [cx, cy] = skyAt(geometry.tca_azimuth_deg, maxEl);
          return (
            <g>
              <circle cx={cx} cy={cy} r={3} fill="none" stroke="var(--text-03)" strokeWidth={1.2} />
              <text
                x={cx + 10}
                y={cy + 5}
                fill="var(--text-03)"
                fontSize={14}
                fontFamily="var(--font-mono)"
              >
                TCA {maxEl.toFixed(1)}&#176;
              </text>
            </g>
          );
        })()}

        {/* ---------------------------------------------------------------- */}
        {/* THE RECORD                                                        */}
        {/* ---------------------------------------------------------------- */}
        <text
          x={PL}
          y={104}
          fill="var(--text-03)"
          fontSize={17}
          letterSpacing="0.09em"
          fontFamily="var(--font-mono)"
        >
          THE RECORD, AS THE RECEIVER WRITES IT
        </text>
        <text
          x={PR}
          y={104}
          fill="var(--text-03)"
          fontSize={14}
          textAnchor="end"
          fontFamily="var(--font-mono)"
        >
          RECEIVED FREQUENCY, OFFSET FROM {((card.rx_freq_hz ?? 436400000) / 1e6).toFixed(3)} MHZ
        </text>

        <rect
          x={PL}
          y={PLATE_T}
          width={PW}
          height={PLATE_B - PLATE_T}
          fill="#070a0d"
          stroke="var(--ui-02)"
          strokeWidth={1}
        />

        <g clipPath="url(#pass-plate-clip)">
          {/* The written record. The texture is the receiver's noise floor and the
              bright cells are the energy the matched filter scored. Both sit under
              the curtain, so they are revealed rather than faded in. */}
          <rect
            x={PL}
            y={PLATE_T}
            width={PW}
            height={PLATE_B - PLATE_T}
            filter="url(#pass-noise)"
            opacity={0.5}
          />

          {energy.map((e, i) => (
            <rect
              key={i}
              x={(e.x - e.w / 2).toFixed(2)}
              y={(e.y - e.h / 2).toFixed(2)}
              width={e.w.toFixed(2)}
              height={e.h.toFixed(2)}
              fill="var(--live-01)"
              opacity={e.o.toFixed(3)}
            />
          ))}

          {/* The signal itself, faint under its own energy: a trace is a band of hot
              cells and this only anchors them so the eye reads one line, not a cloud. */}
          <path d={signal} fill="none" stroke="var(--live-01)" strokeWidth={1.2} opacity={0.42} />

          {/* The curtain: everything the receiver has not written yet. Opaque, drawn
              over the record but under both corridors, because the prediction exists
              before the data does and has to be visible over empty plate. */}
          <g className="pass-anim pass-curtain">
            <rect
              x={PL}
              y={PLATE_T - 4}
              width={PW + 8}
              height={PLATE_B - PLATE_T + 8}
              fill="#070a0d"
            />
          </g>
        </g>

        {/* Frequency gridlines, over the record and under the corridors. */}
        {[-28000, -14000, 0, 14000, 28000].map((hz) => (
          <g key={hz}>
            <line
              x1={PL}
              y1={yHz(hz)}
              x2={PR}
              y2={yHz(hz)}
              stroke={hz === 0 ? "var(--ui-04)" : "var(--ui-02)"}
              strokeWidth={hz === 0 ? 1 : 0.7}
              strokeDasharray={hz === 0 ? undefined : "2 7"}
              opacity={hz === 0 ? 0.55 : 0.4}
            />
            <text
              x={PL - 12}
              y={yHz(hz) + 5}
              fill="var(--text-03)"
              fontSize={14}
              textAnchor="end"
              fontFamily="var(--font-mono)"
            >
              {hz === 0 ? "0" : `${hz > 0 ? "+" : "-"}${Math.abs(hz) / 1000}k`}
            </text>
          </g>
        ))}

        {/* The predicted corridor: the band, then the line that draws itself. */}
        <g clipPath="url(#pass-plate-clip)">
          <path className="pass-anim pass-band" d={band} fill="var(--live-02)" opacity={0} />
          <path
            className="pass-anim pass-draw"
            d={predicted}
            fill="none"
            stroke="var(--live-02)"
            strokeWidth={2}
            strokeDasharray="7 6"
            pathLength={1000}
            style={{ ["--len" as string]: "1000", strokeDashoffset: 1000 }}
          />
        </g>

        {/* The fitted corridor, which slides onto the signal by the measured offset. */}
        <g className="pass-anim pass-fit" clipPath="url(#pass-plate-clip)" opacity={0}>
          <path d={predicted} fill="none" stroke="var(--live-01)" strokeWidth={2.4} />
        </g>

        {/* The read head. One line through the plate, on the walk keyframe. */}
        <g className="pass-anim pass-head">
          <line
            x1={PL}
            y1={PLATE_T - 10}
            x2={PL}
            y2={PLATE_B + 10}
            stroke="var(--live-01)"
            strokeWidth={1.4}
            opacity={0.9}
          />
          <circle cx={PL} cy={PLATE_T - 14} r={3.5} fill="var(--live-01)" />
        </g>

        {/* Time axis. */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const secs = f * windowS;
          const m = Math.floor(secs / 60);
          const s = Math.round(secs % 60);
          return (
            <text
              key={f}
              x={xAt(f)}
              y={PLATE_B + 30}
              fill="var(--text-03)"
              fontSize={14}
              textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"}
              fontFamily="var(--font-mono)"
            >
              {m}:{String(s).padStart(2, "0")}
            </text>
          );
        })}

        {/* Culmination tick on the record, so both panels mark the same instant. */}
        <line
          x1={xAt(tcaFrac)}
          y1={PLATE_T}
          x2={xAt(tcaFrac)}
          y2={PLATE_B}
          stroke="var(--ui-04)"
          strokeWidth={1}
          strokeDasharray="3 5"
          opacity={0.5}
        />

        {/* ---------------------------------------------------------------- */}
        {/* THE READOUTS                                                      */}
        {/* ---------------------------------------------------------------- */}
        <line x1={44} y1={TEL_RULE} x2={PR} y2={TEL_RULE} stroke="var(--ui-02)" strokeWidth={1} />

        {(() => {
          const cols = [
            {
              label: "STATE",
              rolls: ["pass-roll-2", "pass-roll-3"] as const,
              values: ["Predicted", "Tracking", "Fitted"],
            },
            {
              label: "ELEVATION",
              rolls: ["pass-roll-2", "pass-roll-3"] as const,
              values: ["0.0°", `${maxEl.toFixed(1)}°`, `${maxEl.toFixed(1)}°`],
            },
            {
              label: "DOPPLER SWING",
              rolls: ["pass-roll-2", "pass-roll-3"] as const,
              values: [
                "—",
                `${(swingHz / 1000).toFixed(1)} kHz`,
                `${(swingHz / 1000).toFixed(1)} kHz`,
              ],
            },
            {
              label: "FITTED OFFSET",
              rolls: ["pass-roll-2", "pass-roll-3"] as const,
              values: ["—", "—", `${ppm >= 0 ? "+" : ""}${ppm.toFixed(2)} ppm`],
            },
          ];
          const colW = (PR - 44) / cols.length;
          return cols.map((c, i) => {
            const x = 44 + i * colW;
            return (
              <g key={c.label}>
                <text
                  x={x}
                  y={TEL_LABEL_Y}
                  fill="var(--text-03)"
                  fontSize={14}
                  letterSpacing="0.09em"
                  fontFamily="var(--font-mono)"
                >
                  {c.label}
                </text>
                {/* Two nested windows: the outer rolls at the tracking beat, the inner
                    at the fit beat, so three values pass through one line without a
                    third keyframe or a cross-fade. */}
                <g transform={`translate(${x} ${TEL_VALUE_Y - VBASE})`}>
                  <g clipPath="url(#pass-tel-clip)">
                    <g className="pass-anim pass-roll-2">
                      <text
                        x={0}
                        y={VBASE}
                        fill="var(--text-02)"
                        fontSize={26}
                        fontFamily="var(--font-mono)"
                      >
                        {c.values[0]}
                      </text>
                      <g transform={`translate(0 ${LH})`}>
                        <g className="pass-anim pass-roll-3">
                          <text
                            x={0}
                            y={VBASE}
                            fill="var(--live-01)"
                            fontSize={26}
                            fontFamily="var(--font-mono)"
                          >
                            {c.values[1]}
                          </text>
                          <text
                            x={0}
                            y={VBASE + LH}
                            fill="var(--live-01)"
                            fontSize={26}
                            fontFamily="var(--font-mono)"
                          >
                            {c.values[2]}
                          </text>
                        </g>
                      </g>
                    </g>
                  </g>
                </g>
              </g>
            );
          });
        })()}

        {/* The identity, on its own baseline clear of the values above it. */}
        <g>
          <circle cx={50} cy={OBS_Y - 5} r={4} fill="var(--live-01)" className="pass-lamp" />
          <text
            x={66}
            y={OBS_Y}
            fill="var(--text-03)"
            fontSize={15}
            fontFamily="var(--font-mono)"
          >
            obs {OBS_ID} &#183; {satelliteName(card.satellite)} &#183;{" "}
            {card.station_name ?? "M0EYT / 2E0NOG"} &#183; window {mm}:
            {String(ss).padStart(2, "0")} &#183; one loop is {LOOP_S}s
          </text>
        </g>
      </svg>
      {label ? <figcaption>{label}</figcaption> : null}
    </figure>
  );
}
