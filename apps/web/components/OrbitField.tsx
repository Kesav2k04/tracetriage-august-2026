"use client";

/*
 * A pass, propagated: the limb, the sky track over it, and the corridor that track implies.
 *
 * Why this exists. Seven of the eight pages on this console opened on a heading and a
 * paragraph, so they read as one undifferentiated document and a reader arrived at each
 * one already tired. `DeepField` gave the landing route a visual anchor and nothing else
 * had one. This is the second anchor, and it draws the thing the whole project is about:
 * a satellite crosses, the received frequency sweeps because it is moving, and the sweep
 * has a shape fixed by the geometry rather than by anything a model chose.
 *
 * The first draft of this file drew a parabola and a tanh, because both are one line and
 * both look approximately right. On a page whose entire claim is that the corridor's
 * shape is fixed by geometry, a figure of that shape which was really two convenient
 * closed forms is the worst defect it could carry. So the curves below are propagated: a
 * circular orbit under a two-body field, a rotating station on the surface beneath it,
 * elevation and slant range sampled across the visible window, and the Doppler shift
 * taken from the range rate that falls out of the same integration. Nothing is fitted and
 * nothing is placed by eye.
 *
 * What it is and is not. It is a propagation of the orbit given to it, and its caption
 * says so. It is NOT a measurement of any observation in the corpus: no receipt is read
 * here, no number on any page comes from this file, and nothing it draws is quoted
 * anywhere. That distinction is the reason the console is worth reading, so a decorative
 * element that blurred it would cost more than it gave.
 *
 * One fragment shader over one triangle. The curves are propagated once on the CPU and
 * handed down as two arrays; the per-pixel work is distance-to-polyline over 48 points.
 * No geometry is uploaded, no path is tessellated, and no buffer is rewritten between
 * frames, so a frame is one fullscreen pass. The alternative, a stroked SVG path animated
 * per frame, rasterises its whole promoted layer on every tick.
 *
 * It must not run when nobody is looking. The same three guards `DeepField` uses, for the
 * same reasons: an IntersectionObserver stops the loop when the canvas leaves the
 * viewport, `visibilitychange` stops it on a hidden tab, and `prefers-reduced-motion`
 * draws exactly one frame and never schedules another. Under reduce the evidence is the
 * frame, not the sweep, so nothing is withheld from a reader who asked for less movement.
 */

import { useEffect, useMemo, useRef } from "react";

/** Points per curve. 48 is where the polyline stops reading as a polyline at this size,
 *  and it keeps both arrays well inside the uniform budget of any WebGL2 device. */
const SAMPLES = 48;

const MU = 398600.4418; // km^3 s^-2, WGS-84 gravitational parameter
const RE = 6378.137; // km, equatorial radius
const OMEGA_E = 7.2921159e-5; // rad/s, Earth rotation
const C_KM_S = 299792.458;

type Track = {
  arc: number[];
  corridor: number[];
  peakElevationDeg: number;
  maxShiftHz: number;
  durationS: number;
};

type Vec3 = [number, number, number];

/**
 * Propagate one pass and reduce it to two polylines.
 *
 * A circular orbit is enough, and saying so is the point: the corridor's shape comes from
 * the geometry of a crossing, not from the eccentricity of any particular object, so a
 * circular orbit shows the shape without inviting a reader to think a specific satellite
 * is being modelled. Range rate is taken by central difference on the slant range rather
 * than by projecting the velocity vector, because the two agree well below a pixel here
 * and a finite difference cannot disagree with the range actually plotted.
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

  // The station turns with the Earth. Over a ten-minute pass that is about 2.5 degrees of
  // longitude: small, but leaving it out tilts the corridor, which is the one feature of
  // the curve the figure exists to show.
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
    // Classical one-way Doppler, in the sign convention the console uses: a closing range
    // raises the received frequency.
    shifts.push((-rateKmS / C_KM_S) * frequencyMHz * 1e6);
    elevations.push(elevationRad);
    peak = Math.max(peak, elevationRad);
  }

  let maxShift = 0;
  for (const s of shifts) maxShift = Math.max(maxShift, Math.abs(s));

  // Into frame coordinates. The track rides between two fixed rails so a low pass and a
  // high one both read, and the corridor is normalised to its own extreme so its shape
  // stays legible at any frequency.
  // Normalised, not framed. The first version baked frame coordinates in here, which
  // put 24 of the 48 corridor samples below the bottom of the canvas and squeezed both
  // curves into 42% of its width. Where a curve sits in the frame depends on the frame's
  // aspect ratio, which only the shader knows, so that decision belongs there.
  const arc: number[] = [];
  const corridor: number[] = [];
  for (let i = 0; i < SAMPLES; i++) {
    const x = -1 + 2 * (i / (SAMPLES - 1));
    arc.push(x, (elevations[i] ?? 0) / (peak || 1)); //  0 at the horizon, 1 at culmination
    corridor.push(x, (shifts[i] ?? 0) / (maxShift || 1)); // -1 to 1 across the sweep
  }

  return {
    arc,
    corridor,
    peakElevationDeg: (peak * 180) / Math.PI,
    maxShiftHz: maxShift,
    durationS: span,
  };
}

const VERT = `#version 300 es
/* One oversized triangle rather than a quad. Three vertices, no index buffer, and no
   diagonal seam down the middle where two triangles would have met. */
void main() {
  vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float;

#define SAMPLES 48

uniform vec2  uResolution;
uniform float uTime;
uniform float uIntro;   /* 0 to 1, once, so the mark draws itself in rather than blinking on */
uniform vec3  uInk;     /* the accent, read from the stylesheet so the palette stays single-sourced */
uniform vec3  uPaper;
uniform float uAspect;  /* width over height, so the curves can fill whatever box they get */
uniform vec2  uArc[SAMPLES];   /* x in -1..1, y 0 at the horizon and 1 at the zenith */
uniform vec2  uCorr[SAMPLES];  /* x in -1..1, y -1..1 across the sweep */

out vec4 fragColour;

/* Cheap hash. Used only for the star field, where the requirement is "no visible
   lattice", not "statistically sound". */
float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

/* Distance to a segment. Every stroke below is built from this. */
float segment(vec2 p, vec2 a, vec2 b) {
  vec2 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}

/* Framing. uv.y runs -0.5 to 0.5 whatever the box, and uv.x runs to half the aspect, so
   these two are where a normalised curve becomes a placed one. Both bands sit above the
   limb's top edge at y = -0.32, and both stay inside the canvas at every aspect.
   The points are transformed rather than the space: scaling uv would stretch every
   stroke into an ellipse. */
vec2 arcPoint(int i) {
  return vec2(uArc[i].x * uAspect * 0.36, 0.08 + uArc[i].y * 0.20);
}

vec2 corrPoint(int i) {
  return vec2(uCorr[i].x * uAspect * 0.36, -0.20 + uCorr[i].y * 0.16);
}

float arcDistUpTo(vec2 p, float frac) {
  float best = 1e9;
  float limit = frac * float(SAMPLES - 1);
  for (int i = 0; i < SAMPLES - 1; i++) {
    if (float(i) > limit) break;
    best = min(best, segment(p, arcPoint(i), arcPoint(i + 1)));
  }
  return best;
}

float corrDist(vec2 p) {
  float best = 1e9;
  for (int i = 0; i < SAMPLES - 1; i++) best = min(best, segment(p, corrPoint(i), corrPoint(i + 1)));
  return best;
}

vec2 arcAt(float f) {
  float g = clamp(f, 0.0, 1.0) * float(SAMPLES - 1);
  int i = int(floor(g));
  int j = min(i + 1, SAMPLES - 1);
  return mix(arcPoint(i), arcPoint(j), fract(g));
}

void main() {
  vec2 uv = (gl_FragCoord.xy - 0.5 * uResolution) / uResolution.y;  /* y-normalised */
  vec3 col = uPaper;

  /* --- Star field -------------------------------------------------------------
     Two octaves so the field has depth rather than one flat sprinkle. The near layer
     drifts, which gives the frame a sense of being looked out of rather than at. */
  for (int layer = 0; layer < 2; layer++) {
    float scale = layer == 0 ? 26.0 : 44.0;
    float drift = uTime * (layer == 0 ? 0.006 : 0.0022);
    vec2 gv = (uv + vec2(drift, 0.0)) * scale;
    vec2 id = floor(gv);
    float rnd = hash(id);
    if (rnd > 0.955) {
      vec2 offset = vec2(hash(id + 1.7), hash(id + 3.1)) - 0.5;
      float d = length(fract(gv) - 0.5 - offset * 0.6);
      /* Per-star phase, so the field never pulses in unison. */
      float tw = 0.75 + 0.25 * sin(uTime * 1.1 + rnd * 40.0);
      col += smoothstep(0.055, 0.0, d) * (layer == 0 ? 0.5 : 0.28) * tw * vec3(0.82, 0.86, 1.0);
    }
  }

  /* --- Earth's limb -----------------------------------------------------------
     A circle centred far below the frame, so only its top crosses: the horizon a ground
     station actually sees. The rim has a tighter falloff than the body, which is what
     reads as atmosphere rather than as a stroked circle. */
  float d = length(uv - vec2(0.0, -3.72)) - 3.30;
  col = mix(col, uPaper * 0.30 + vec3(0.012, 0.018, 0.030), smoothstep(0.004, -0.02, d) * 0.92);
  col += exp(-abs(d) * 46.0) * vec3(0.16, 0.30, 0.52) * 0.85;
  col += exp(-max(d, 0.0) * 7.5) * vec3(0.05, 0.11, 0.22) * 0.55;

  /* --- The sky track ----------------------------------------------------------- */
  float arcD = arcDistUpTo(uv, clamp(uIntro * 1.15, 0.0, 1.0));
  col += smoothstep(0.0075, 0.0, arcD) * uInk * 0.30;
  col += smoothstep(0.0500, 0.0, arcD) * uInk * 0.05;

  /* --- The satellite -----------------------------------------------------------
     One period is deliberately long. This sits near text a reader is trying to read, and
     a fast mark in the corner of the eye is a cost, not a feature. */
  float phase = fract(uTime * 0.055);
  vec2 sat = arcAt(phase);

  /* A trail, not a comet tail: the part of the track already covered, fading out. */
  float trailD = 1e9;
  for (int i = 0; i < 14; i++) {
    float t0 = max(phase - float(i)     * 0.008, 0.0);
    float t1 = max(phase - float(i + 1) * 0.008, 0.0);
    trailD = min(trailD, segment(uv, arcAt(t0), arcAt(t1)));
  }
  col += smoothstep(0.010, 0.0, trailD) * uInk * 0.34 * uIntro;

  float satD = length(uv - sat);
  col += smoothstep(0.013, 0.0, satD) * vec3(1.0) * 0.95 * uIntro;
  col += smoothstep(0.075, 0.0, satD) * uInk * 0.30 * uIntro;

  /* --- The corridor ------------------------------------------------------------
     Under the track: the shape the sweep traces on a waterfall. It brightens where the
     satellite is, which is the one piece of coupling in the frame and the only thing the
     figure is trying to say. */
  float corrD = corrDist(uv);
  float lead = smoothstep(0.42, 0.0, abs(uv.x - sat.x));
  col += smoothstep(0.0055, 0.0, corrD) * uInk * (0.16 + 0.40 * lead) * uIntro;
  col += smoothstep(0.0380, 0.0, corrD) * uInk * 0.055 * uIntro;

  /* --- Frame -------------------------------------------------------------------
     Vignette, then a fade at the lower edge so the canvas ends in the page colour and
     needs no border to sit in. A border here would have been one more box on a page that
     already had 28 of them. */
  /* Blend toward the paper rather than multiplying down to black. Multiplying darkened
     the paper itself, so a borderless canvas sat as a visibly darker rectangle on the
     page: measured rgb(7,9,11) at the sides against a page of rgb(12,14,18). Each of the
     four edges now resolves to exactly uPaper, which is what lets the figure carry no
     border on a page that already had 28 of them. */
  float vig = smoothstep(1.28, 0.30, length(uv * vec2(0.42, 1.0)));
  col = mix(uPaper, col, mix(0.55, 1.0, vig));
  col = mix(uPaper, col, smoothstep(-0.50, -0.36, uv.y));
  col = mix(uPaper, col, smoothstep(0.50, 0.36, uv.y));
  col = mix(uPaper, col, smoothstep(uAspect * 0.5, uAspect * 0.5 - 0.40, abs(uv.x)));

  fragColour = vec4(col, 1.0);
}`;

function compile(gl: WebGL2RenderingContext, kind: number, source: string) {
  const shader = gl.createShader(kind);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/** A CSS colour resolved to 0-1 RGB, so the shader reads the stylesheet rather than a
 *  second copy of the palette that would drift from it. */
function parseColour(value: string, fallback: [number, number, number]): [number, number, number] {
  const hex = value.trim().match(/^#?([0-9a-fA-F]{6})$/);
  if (hex) {
    const n = parseInt(hex[1] ?? "000000", 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  const parts = value.match(/[0-9.]+/g);
  if (parts && parts.length >= 3) {
    return [Number(parts[0]) / 255, Number(parts[1]) / 255, Number(parts[2]) / 255];
  }
  return fallback;
}

export default function OrbitField({
  altitudeKm = 550,
  inclinationDeg = 97.6,
  stationLatDeg = 52.2,
  frequencyMHz = 437,
  height = 280,
  label,
}: {
  altitudeKm?: number;
  inclinationDeg?: number;
  stationLatDeg?: number;
  frequencyMHz?: number;
  height?: number;
  /** Said out loud under the frame. A drawing that could be mistaken for a measurement on
   *  a page of measurements has to name itself. */
  label?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const track = useMemo(
    () => propagate(altitudeKm, inclinationDeg, stationLatDeg, frequencyMHz),
    [altitudeKm, inclinationDeg, stationLatDeg, frequencyMHz],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl2", {
      antialias: false,
      depth: false,
      stencil: false,
      alpha: false,
      powerPreference: "low-power",
    });
    // No WebGL2, or a driver that refuses the context. The figure is an illustration, so
    // the right behaviour is to leave the box empty and cost the reader nothing.
    if (!gl) return;

    const vs = compile(gl, gl.VERTEX_SHADER, VERT);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    if (!vs || !fs) return;

    const program = gl.createProgram();
    if (!program) return;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      return;
    }
    gl.useProgram(program);

    const uResolution = gl.getUniformLocation(program, "uResolution");
    const uTime = gl.getUniformLocation(program, "uTime");
    const uIntro = gl.getUniformLocation(program, "uIntro");
    const uAspect = gl.getUniformLocation(program, "uAspect");

    const styles = getComputedStyle(document.documentElement);
    gl.uniform3fv(
      gl.getUniformLocation(program, "uInk"),
      parseColour(styles.getPropertyValue("--interactive-01"), [0.988, 0.647, 0.039]),
    );
    gl.uniform3fv(
      gl.getUniformLocation(program, "uPaper"),
      parseColour(styles.getPropertyValue("--ui-background"), [0.047, 0.055, 0.071]),
    );
    // Uploaded once: the propagation does not change between frames, so neither does this.
    gl.uniform2fv(gl.getUniformLocation(program, "uArc"), new Float32Array(track.arc));
    gl.uniform2fv(gl.getUniformLocation(program, "uCorr"), new Float32Array(track.corridor));

    // 1.5 is where another pixel stops buying anything visible on a field of soft marks,
    // and it is the clamp DeepField already settled on.
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);

    function resize() {
      if (!canvas || !gl) return;
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width === w && canvas.height === h) return;
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
      gl.uniform2f(uResolution, w, h);
      gl.uniform1f(uAspect, w / h);
    }

    let raf = 0;
    let running = false;
    let visible = false;
    const started = performance.now();

    function draw(now: number) {
      if (!gl) return;
      resize();
      const seconds = (now - started) / 1000;
      gl.uniform1f(uTime, seconds);
      gl.uniform1f(uIntro, Math.min(1, seconds / 1.15));
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    function tick(now: number) {
      draw(now);
      raf = requestAnimationFrame(tick);
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

    function start() {
      if (running || !visible || !gl) return;
      if (reduced.matches) {
        // One frame, fully drawn in, and no loop is ever scheduled.
        resize();
        gl.uniform1f(uTime, 6);
        gl.uniform1f(uIntro, 1);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
        return;
      }
      running = true;
      raf = requestAnimationFrame(tick);
    }

    function stop() {
      running = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        visible = entries.some((entry) => entry.isIntersecting);
        if (visible) start();
        else stop();
      },
      { rootMargin: "120px" },
    );
    observer.observe(canvas);

    const onVisibility = () => {
      if (document.hidden) stop();
      else start();
    };
    const onMotionChange = () => {
      stop();
      start();
    };
    const onResize = () => {
      if (!running) {
        resize();
        draw(performance.now());
      }
    };

    document.addEventListener("visibilitychange", onVisibility);
    reduced.addEventListener("change", onMotionChange);
    window.addEventListener("resize", onResize);

    return () => {
      stop();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduced.removeEventListener("change", onMotionChange);
      window.removeEventListener("resize", onResize);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    };
  }, [track]);

  const caption =
    label ??
    `A ${altitudeKm} km circular orbit at ${inclinationDeg} degrees, propagated over one pass above a ` +
      `station at ${stationLatDeg} degrees north: ${Math.round(track.durationS / 60)} minutes above the ` +
      `horizon, peaking at ${track.peakElevationDeg.toFixed(1)} degrees. The curve beneath it is the ` +
      `Doppler shift that pass's range rate implies at ${frequencyMHz} MHz, plus or minus ` +
      `${(track.maxShiftHz / 1000).toFixed(1)} kHz. Propagated for this figure, not measured: every ` +
      `number this console publishes comes from a receipt.`;

  return (
    <figure className="orbit-field">
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        style={{ display: "block", width: "100%", height: `${height}px` }}
      />
      <figcaption>{caption}</figcaption>
    </figure>
  );
}
