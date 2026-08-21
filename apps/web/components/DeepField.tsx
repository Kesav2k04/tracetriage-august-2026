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
// 0 while the hero fills the viewport, 1 once it has scrolled away. Read from scrollY
// once per frame inside the loop that was already running, so it costs no layout and no
// custom property: a per-frame CSS variable invalidates the whole subtree that reads it,
// and a transform cannot be composited from one.
// The precision is written out and it is not a leftover. The fragment stage declares
// precision mediump float and the vertex stage defaults to highp, so a uniform of the
// same name in both stages links with two different precisions and the whole program is
// rejected. It was, with "Precisions of uniform 'uScroll' differ between VERTEX and
// FRAGMENT shaders", which this component's own link-error log turned into a one-line fix
// rather than an empty canvas. No backticks in here either: this source is a template
// literal, so one would end the shader mid-comment.
uniform mediump float uScroll;
// 0 at mount, 1 when the field has finished arriving. Ranks gate on it in order, so the
// queue assembles from its own first place outward.
uniform float uIntro;
out float vValue;
out float vReason;
out float vDepth;
out float vBorn;

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

  // The camera pulls back as the hero leaves. Not a zoom on the canvas box: a CSS scale
  // on a promoted layer rasterises the whole box at the new size, and this is a
  // full-width element. Scaling the radius in clip space instead costs one multiply and
  // rasterises nothing, and the field recedes rather than growing soft.
  float recede = 1.0 - uScroll * 0.22;
  float radius = sqrt(rank) * 0.94 * recede;

  // Depth from the measured offset. A pass with no fit sits on the plane at z = 0 and
  // never moves; a large offset swims slowly toward the reader and back.
  float z = ppm * 0.5 * sin(uTime * 0.11 + rank * 6.0);
  float perspective = 1.0 / (1.0 + z * 0.22);

  // Rank order, not a random stagger. The gate opens at the centre and sweeps out, so
  // what a reader watches assemble is the queue's own ordering rather than a shuffle
  // that happens to look busy. The window is wider than the step so neighbours overlap
  // and the edge of the sweep is a gradient rather than a ring.
  vBorn = smoothstep(rank - 0.28, rank + 0.06, uIntro * 1.34);

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
  // A point that has not arrived yet is drawn at zero size rather than skipped, because
  // a skipped vertex is a branch and every point takes the same path here.
  gl_PointSize = uScale * (2.0 + value * 6.5 + aFitted * 2.2) * perspective * vBorn;
  vValue = value;
  vReason = aPoint.z;
  // Signed depth, forward positive, handed to the fragment stage so near and far differ
  // in brightness and not only in size. Size alone reads as a point changing importance;
  // brightness with it reads as a point moving through space.
  vDepth = clamp(z * 0.5, -1.0, 1.0);
}
`;

const FRAGMENT = `#version 300 es
precision mediump float;
in float vValue;
in float vReason;
in float vDepth;
in float vBorn;
uniform vec3 uColours[4];
uniform float uScroll;
out vec4 outColour;

void main() {
  // Two lobes rather than one, which is the whole difference between a dot and a light.
  // A single falloff has one width, so a point is either small and hard or large and
  // vague. A tight core inside a wide halo has both: the core carries the position and
  // the halo carries the glow, and because the canvas blends additively the halos of
  // crowded ranks sum into a brightness that is itself the density. The queue is denser
  // where it ranks harder, so that sum is information rather than decoration.
  vec2 d = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(d, d);
  if (r2 > 1.0) discard;
  float falloff = 1.0 - r2;
  float halo = pow(falloff, 1.55);
  float core = pow(falloff, 7.0);
  float disc = halo * 0.52 + core;

  int index = int(vReason + 0.5);
  vec3 colour = uColours[0];
  if (index == 1) colour = uColours[1];
  else if (index == 2) colour = uColours[2];
  else if (index == 3) colour = uColours[3];

  // Review value drives alpha rather than colour, so the criterion stays readable at
  // every brightness and the two channels do not compete for the same meaning.
  float alpha = disc * (0.22 + vValue * 0.74);

  // Aerial perspective, in one term. A point swimming forward gains a little light and
  // one swimming away loses it, so the offset channel reads as distance instead of as a
  // size wobble. Held small: this is a background, and the review value has to stay the
  // brighter of the two signals or the field starts arguing with its own caption.
  alpha *= 1.0 + vDepth * 0.30;

  // Fades as the hero leaves, on top of the geometric recession, so the field goes away
  // rather than shrinking into a bright knot at the centre of an empty screen.
  alpha *= vBorn * (1.0 - uScroll * 0.55);
  if (alpha <= 0.0) discard;
  outColour = vec4(colour * (0.6 + vValue * 0.7 + max(vDepth, 0.0) * 0.25), alpha);
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
    const uScroll = gl.getUniformLocation(program, "uScroll");
    const uIntro = gl.getUniformLocation(program, "uIntro");
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

    // Called from a ResizeObserver and from mount, never from the loop.
    //
    // It used to be the first line of `draw`, so the loop asked the layout engine for a
    // rectangle sixty times a second to learn a number that changes when the window
    // changes. On a page with nothing else invalidating layout that is cheap, which is
    // exactly why it survived: it cost nothing measurable and it was still the loop
    // taking a dependency on layout it does not need.
    function resize(w: number, h: number) {
      const pw = Math.max(1, Math.round(w * dpr));
      const ph = Math.max(1, Math.round(h * dpr));
      if (pw === width && ph === height) return;
      width = pw;
      height = ph;
      canvas!.width = pw;
      canvas!.height = ph;
      gl!.viewport(0, 0, pw, ph);
      gl!.uniform2f(uSize, pw, ph);
      gl!.uniform1f(uScale, dpr);
    }

    /**
     * How far the hero has gone, as a fraction of one viewport.
     *
     * `scrollY` and not `getBoundingClientRect`: the hero starts at the top of every page
     * this canvas is on, so the scroll position is the answer already, and reading it
     * cannot force a layout the way a rect can. Clamped rather than unbounded, so a long
     * page does not keep pushing the field back after it has left.
     */
    function scrollProgress() {
      const span = Math.max(1, window.innerHeight);
      return Math.min(1, Math.max(0, window.scrollY / span));
    }

    // Milliseconds. Long enough that 407 points arrive in a visible sweep rather than a
    // flash, short enough to be over before a reader has finished the first heading.
    const INTRO_MS = 1500;
    let born = 0;

    function draw(seconds: number, intro: number) {
      gl!.uniform1f(uTime, seconds);
      gl!.uniform1f(uScroll, scrollProgress());
      gl!.uniform1f(uIntro, intro);
      gl!.clear(gl!.COLOR_BUFFER_BIT);
      gl!.drawArrays(gl!.POINTS, 0, points.length);
      // The only claim a probe can check from outside: the field drew, and how many
      // points it drew. A canvas element proves nothing on its own, because a failed
      // context, a failed compile and a spiral outside clip space all look identical
      // from the DOM, and two of those three have already happened here.
      canvas!.dataset.fieldDrawn = String(points.length);
      // The scroll coupling, exposed for the same reason the count is. In-page readback
      // of a WebGL canvas is unreliable and a screenshot of one proves nothing about what
      // a uniform was set to, so the value the loop actually pushed is written where a
      // probe can read it. Two decimals: a probe wants to know it moved, not the float.
      canvas!.dataset.fieldScroll = scrollProgress().toFixed(2);
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let running = false;
    let visible = true;

    let started = 0;

    function tick(now: number) {
      if (!started) started = now;
      born = Math.min(1, (now - started) / INTRO_MS);
      draw(now / 1000, born);
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
    // get the distribution rather than an empty rectangle. Intro at 1, not 0: the arrival
    // sweep is the animation, and a reader who asked for less motion must get the field
    // it arrives at rather than the empty frame it starts from.
    const rect = canvas.getBoundingClientRect();
    resize(rect.width, rect.height);
    draw(0, 1);

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
    // A ResizeObserver rather than a window resize listener: the canvas is full-width
    // inside a hero whose height depends on its own content, so a box change without a
    // window change was a case the listener never saw. It also fires once on observe,
    // which is where the first correct size comes from on a slow layout.
    const sizes = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const box = entry.contentRect;
        resize(box.width, box.height);
      }
      draw(performance.now() / 1000, running ? born : 1);
    });
    sizes.observe(canvas);

    // Redraw on scroll only when the loop is stopped. While it runs, every frame already
    // reads the scroll position; adding a listener on top would draw the same frame twice.
    const onScroll = () => {
      if (!running) draw(performance.now() / 1000, born || 1);
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    start();

    return () => {
      stop();
      observer.disconnect();
      sizes.disconnect();
      window.removeEventListener("scroll", onScroll);
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
