"use client";

/**
 * The whole ranked queue, drawn on the GPU, behind the first screen.
 *
 * This is a background and it is also a chart, which is the only reason it is allowed to
 * exist on this site. Nothing here is invented: every point is one of the observations the
 * queue ranks, placed by its rank, lit by its review value and coloured by the criterion
 * that raised it. A reader who never reads the caption still sees a real distribution, and
 * a reader who does can name any pixel.
 *
 *   angle and radius  rank, spiralled from the centre out. Rank 1 is the middle of the
 *                     screen, rank 407 is the rim, and the radius goes as the square root
 *                     of the rank so the area density is even rather than crowding the
 *                     middle.
 *   brightness        review value, the score the queue orders by.
 *   colour            the reason code that put it in the queue.
 *   drift             the fitted Doppler offset in ppm. Only 87 of the 407 have a fit, so
 *                     most of the field is still. Two of those 87 fits landed on exactly
 *                     zero ppm, and they are still too, which is why a measured offset and
 *                     an absent one are carried as separate channels: a zero that means "on
 *                     frequency" must not look like a zero that means "nobody measured".
 *
 * Three things it must not do, all of them measured rather than assumed:
 *
 * It must not hold the first paint. The canvas mounts in an effect, after the document is
 * painted, and the hero reads correctly with no canvas at all: this element is `aria-hidden`
 * and carries no information the page does not also state in text.
 *
 * It must not cost contrast. The field is masked to the outer edges of the hero and held
 * under the text at low alpha. `tests/test_contrast.py` measures the rendered pixels rather
 * than the CSS, which is the only measurement that means anything with a canvas underneath.
 *
 * It must not run when nobody is looking. An IntersectionObserver stops the loop when the
 * hero leaves the viewport, `visibilitychange` stops it on a hidden tab, and
 * `prefers-reduced-motion` draws exactly one frame and never schedules another.
 */

import { useEffect, useRef } from "react";

import { FIELD_REASON_TOKENS, type FieldPoint } from "@/lib/field";

const VERTEX = `#version 300 es
in vec4 aPoint;   // rank01, value01, reason, ppm
in float aFitted; // 1 when a corridor was fitted, whatever the offset came out at
uniform float uTime;
uniform vec2 uSize;
uniform float uScale;
uniform float uCount;
out float vValue;
out float vReason;

void main() {
  float rank = aPoint.x;
  float value = aPoint.y;
  float ppm = aPoint.w;

  // Phyllotaxis. Consecutive ranks are separated by the golden angle, 2.39996 radians,
  // which is the arrangement a sunflower head uses and the only one that fills a disc
  // evenly with no visible arms. Two and a bit turns, which is what a small multiplier
  // gives, reads as a single thin arc: a line through empty space rather than a field.
  // The radius still goes as the square root of the rank, so rank 1 is the centre and
  // the area density is even.
  float theta = rank * (uCount - 1.0) * 2.39996 + uTime * 0.035;
  float radius = sqrt(rank) * 0.94;

  // Depth from the measured offset. A pass with no fit sits on the plane at z = 0 and
  // never moves; a large offset swims slowly toward the reader and back.
  float z = ppm * 0.5 * sin(uTime * 0.11 + rank * 6.0);
  float perspective = 1.0 / (1.0 + z * 0.22);

  // No aspect correction, on purpose. Clip space is the box, so the spiral fills whatever
  // shape the hero is: nearly round on a narrow viewport, a wide ellipse on a broad one.
  // An aspect factor here was worse than useless. Written as uSize.y / uSize.x it scaled
  // the vertical axis by 2.17 on a hero taller than it is wide, which put most of the
  // field outside clip space, and the canvas read as empty rather than as wrong.
  vec2 clip = vec2(cos(theta), sin(theta)) * radius * perspective;

  gl_Position = vec4(clip, 0.0, 1.0);
  // A measured point is drawn larger than an unmeasured one at the same review value, so
  // the 87 that carry a corridor fit are legible as a group even where two of them sit
  // still because their offset is zero.
  gl_PointSize = uScale * (2.0 + value * 6.5 + aFitted * 2.2) * perspective;
  vValue = value;
  vReason = aPoint.z;
}
`;

const FRAGMENT = `#version 300 es
precision mediump float;
in float vValue;
in float vReason;
uniform vec3 uColours[4];
out vec4 outColour;

void main() {
  // A soft disc. The square falloff is what stops 407 hard squares reading as noise.
  vec2 d = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(d, d);
  if (r2 > 1.0) discard;
  float disc = pow(1.0 - r2, 1.8);

  int index = int(vReason + 0.5);
  vec3 colour = uColours[0];
  if (index == 1) colour = uColours[1];
  else if (index == 2) colour = uColours[2];
  else if (index == 3) colour = uColours[3];

  // Review value drives alpha rather than colour, so the criterion stays readable at
  // every brightness and the two channels do not compete for the same meaning.
  float alpha = disc * (0.22 + vValue * 0.74);
  outColour = vec4(colour * (0.6 + vValue * 0.7), alpha);
}
`;

/**
 * Compile one stage, and say so on the console when it fails.
 *
 * A silent return here is how this component spent a build looking like a browser without
 * WebGL2 rather than like a shader with a typo in it. The log is the difference between
 * "nothing drew" and "nothing drew, and here is the line".
 */
function compile(gl: WebGL2RenderingContext, kind: number, source: string) {
  const shader = gl.createShader(kind);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error("[deep-field] shader did not compile", gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

/** `#rrggbb` or `rgb(r g b)` to linear-ish 0..1, whichever the token resolves to. */
function parseColour(value: string): [number, number, number] {
  const text = value.trim();
  const hex = /^#([0-9a-f]{6})$/i.exec(text)?.[1];
  if (hex) {
    const n = parseInt(hex, 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  const [r, g, b] = text.match(/[\d.]+/g) ?? [];
  if (r !== undefined && g !== undefined && b !== undefined) {
    return [Number(r) / 255, Number(g) / 255, Number(b) / 255];
  }
  // A token that resolves to something this cannot read is mid grey rather than black:
  // an unreadable colour should look wrong, not look like nothing was drawn.
  return [0.5, 0.5, 0.5];
}

export default function DeepField({ points }: { points: readonly FieldPoint[] }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;

    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      // On, and it is not an optimisation left switched the wrong way. With this off the
      // drawing buffer is cleared after each composite, which is free while a loop is
      // running and wrong in the three states this component deliberately stops in:
      // reduced motion, scrolled out of view, hidden tab. Each draws one frame and stops,
      // and each would then blank on the next composite. Keeping the buffer costs one
      // more surface for a canvas this size and is what makes a paused field a field
      // rather than a hole.
      preserveDrawingBuffer: true,
      powerPreference: "low-power",
    });
    if (!gl) return;

    const vs = compile(gl, gl.VERTEX_SHADER, VERTEX);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT);
    const program = vs && fs ? gl.createProgram() : null;
    if (!vs || !fs || !program) return;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error("[deep-field] program did not link", gl.getProgramInfoLog(program));
      return;
    }
    gl.useProgram(program);

    // One interleaved buffer, five floats a point, so the whole field is a single
    // upload and a single draw call.
    const STRIDE = 5;
    const data = new Float32Array(points.length * STRIDE);
    points.forEach((p, i) => {
      data[i * STRIDE] = p.rank01;
      data[i * STRIDE + 1] = p.value01;
      data[i * STRIDE + 2] = p.reason;
      data[i * STRIDE + 3] = p.ppm;
      data[i * STRIDE + 4] = p.fitted ? 1 : 0;
    });
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    const bytes = STRIDE * 4;
    const aPoint = gl.getAttribLocation(program, "aPoint");
    gl.enableVertexAttribArray(aPoint);
    gl.vertexAttribPointer(aPoint, 4, gl.FLOAT, false, bytes, 0);
    const aFitted = gl.getAttribLocation(program, "aFitted");
    gl.enableVertexAttribArray(aFitted);
    gl.vertexAttribPointer(aFitted, 1, gl.FLOAT, false, bytes, 16);

    const style = getComputedStyle(document.documentElement);
    const colours = new Float32Array(
      FIELD_REASON_TOKENS.flatMap((token) => parseColour(style.getPropertyValue(token))),
    );
    gl.uniform3fv(gl.getUniformLocation(program, "uColours"), colours);

    const uTime = gl.getUniformLocation(program, "uTime");
    const uSize = gl.getUniformLocation(program, "uSize");
    const uScale = gl.getUniformLocation(program, "uScale");
    // The count, so the golden-angle step is computed from the queue's real length rather
    // than from a constant that would silently stop being the queue's length.
    gl.uniform1f(gl.getUniformLocation(program, "uCount"), points.length);

    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    // Additive over a transparent canvas: overlapping points brighten, which is the one
    // place on this page where an overlap should read as more rather than as occlusion.
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.clearColor(0, 0, 0, 0);

    // A promoted layer rasterises its whole box, so the device pixel ratio is capped: a
    // full-width canvas at 3x on a wide screen is tens of megabytes of raster for a
    // decorative field, and the difference is invisible on a soft disc.
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let width = 0;
    let height = 0;

    function resize() {
      const rect = canvas!.getBoundingClientRect();
      const w = Math.max(1, Math.round(rect.width * dpr));
      const h = Math.max(1, Math.round(rect.height * dpr));
      if (w === width && h === height) return;
      width = w;
      height = h;
      canvas!.width = w;
      canvas!.height = h;
      gl!.viewport(0, 0, w, h);
      gl!.uniform2f(uSize, w, h);
      gl!.uniform1f(uScale, dpr);
    }

    function draw(seconds: number) {
      resize();
      gl!.uniform1f(uTime, seconds);
      gl!.clear(gl!.COLOR_BUFFER_BIT);
      gl!.drawArrays(gl!.POINTS, 0, points.length);
      // The only claim a probe can check from outside: the field drew, and how many
      // points it drew. A canvas element proves nothing on its own, because a failed
      // context, a failed compile and a spiral outside clip space all look identical
      // from the DOM, and two of those three have already happened here.
      canvas!.dataset.fieldDrawn = String(points.length);
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let running = false;
    let visible = true;

    function tick(now: number) {
      draw(now / 1000);
      frame = requestAnimationFrame(tick);
    }

    function start() {
      if (running || reduced.matches || !visible || document.hidden) return;
      running = true;
      frame = requestAnimationFrame(tick);
    }

    function stop() {
      running = false;
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    }

    // One frame either way, so a reduced-motion reader and a scrolled-past reader both
    // get the distribution rather than an empty rectangle.
    draw(0);

    const observer = new IntersectionObserver(
      (entries) => {
        visible = entries.some((entry) => entry.isIntersecting);
        if (visible) start();
        else stop();
      },
      { rootMargin: "120px" },
    );
    observer.observe(canvas);

    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);
    const onReduced = () => (reduced.matches ? stop() : start());
    reduced.addEventListener("change", onReduced);
    window.addEventListener("resize", () => draw(performance.now() / 1000), {
      passive: true,
    });

    start();

    return () => {
      stop();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduced.removeEventListener("change", onReduced);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
    };
  }, [points]);

  return (
    <canvas
      ref={canvasRef}
      className="deep-field"
      aria-hidden="true"
      role="presentation"
    />
  );
}
