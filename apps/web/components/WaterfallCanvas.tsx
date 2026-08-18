"use client";

/**
 * The waterfall, rendered through a fragment shader.
 *
 * WebGL earns its place here for exactly one reason: contrast stretch and false
 * colour are per-pixel operations on a 620x1540 image driven by a slider, and
 * doing that on the CPU through canvas2D would drop frames on a laptop. Nothing
 * else on this page uses it.
 *
 * What that buys has to be paid for carefully, because an unoptimised WebGL
 * canvas is worse than no WebGL at all:
 *
 *   - One fullscreen quad and one texture, uploaded once per observation. No
 *     per-frame geometry, no per-frame upload.
 *   - Render on demand. There is no requestAnimationFrame loop: a frame is drawn
 *     when a uniform changes, when the element resizes, or when it becomes
 *     visible, and several changes inside one frame coalesce into one draw. An
 *     idle card costs nothing.
 *   - The context outlives the controls. The uniforms live in a ref and the draw
 *     callback is stable, so moving a slider does not re-run the effect that owns
 *     the context. An earlier version had the init effect depend on the draw
 *     function: every slider tick destroyed the program, the texture and the
 *     context and re-decoded the image, which is the exact cost WebGL was chosen
 *     to avoid, and it walks into the browser's live-context cap while doing it.
 *   - Device pixel ratio is capped at 2. A promoted layer rasterises its whole
 *     box, so an uncapped ratio on a 3x display quadruples the raster for no
 *     visible gain on a spectrogram.
 *   - The context is created when the canvas first becomes visible, cached on a ref
 *     for the life of the canvas, and released with WEBGL_lose_context on unmount
 *     and only on unmount. Browsers cap live contexts at around 16, and a queue of
 *     cards would exhaust that, so it cannot be left to garbage collection. It was
 *     released in the per-image cleanup instead, which meant any second run of that
 *     effect got the same still-lost context back from getContext and fell through
 *     to the shader-failure branch for good.
 *   - alpha, depth, stencil and antialias are all off, and the drawing buffer is
 *     not preserved. Each of those is a buffer the compositor would otherwise
 *     allocate and blend for a page that needs none of them.
 *   - Colour management is switched off on upload. The stored bytes are measured
 *     intensities, not a photograph; letting the browser convert them to the
 *     display profile would change the numbers this page claims to be showing.
 *   - Single-channel immutable storage. The image is intensity, so R8 through
 *     texStorage2D costs a third of an RGB upload and lets the driver skip the
 *     completeness checks a mutable texture needs on every draw.
 *   - No readPixels anywhere. It stalls the pipeline by forcing a sync.
 *
 * If WebGL is unavailable or the context is lost, the same image renders as a
 * plain <img>. The controls disappear rather than sitting there dead, because a
 * disabled control that never works is worse than an absent one.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type Palette = "grey" | "viridis" | "inferno";

export interface WaterfallCanvasProps {
  src: string;
  width: number;
  height: number;
  alt: string;
  blackPoint: number;
  whitePoint: number;
  gamma: number;
  palette: Palette;
  onFallback?: (reason: string) => void;
}

const VERTEX_SHADER = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
  // Flip V so texture row 0 lands at the top, matching the image and the
  // corridor overlay's row indices.
  v_uv = vec2(a_pos.x * 0.5 + 0.5, 0.5 - a_pos.y * 0.5);
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

/**
 * Viridis and inferno as polynomial fits rather than lookup textures. A LUT
 * would need a second texture and a second bind for six coefficients' worth of
 * arithmetic. Coefficients are the standard least-squares fits to the matplotlib
 * colormaps.
 */
const FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec2 v_uv;
out vec4 fragColor;

uniform sampler2D u_image;
uniform float u_black;
uniform float u_white;
uniform float u_gamma;
uniform int u_palette;

vec3 viridis(float t) {
  const vec3 c0 = vec3(0.2777273272234177, 0.005407344544966578, 0.3340998053353061);
  const vec3 c1 = vec3(0.1050930431085774, 1.404613529898575, 1.384590162594685);
  const vec3 c2 = vec3(-0.3308618287255563, 0.214847559468213, 0.09509516302823659);
  const vec3 c3 = vec3(-4.634230498983486, -5.799100973351585, -19.33244095627987);
  const vec3 c4 = vec3(6.228269936347081, 14.17993336680509, 56.69055260068105);
  const vec3 c5 = vec3(4.776384997670288, -13.74514537774601, -65.35303263337234);
  const vec3 c6 = vec3(-5.435455855934631, 4.645852612178535, 26.3124352495832);
  return c0 + t * (c1 + t * (c2 + t * (c3 + t * (c4 + t * (c5 + t * c6)))));
}

vec3 inferno(float t) {
  const vec3 c0 = vec3(0.0002189403691192265, 0.001651004631001012, -0.01948089843709184);
  const vec3 c1 = vec3(0.1065134194856116, 0.5639564367884091, 3.932712388889277);
  const vec3 c2 = vec3(11.60249308247187, -3.972853965665698, -15.9423941062914);
  const vec3 c3 = vec3(-41.70399613139459, 17.43639888205313, 44.35414519872813);
  const vec3 c4 = vec3(77.16287970072997, -33.40235894210092, -81.80730925738993);
  const vec3 c5 = vec3(-71.31942824499214, 32.62606426397723, 73.20951985803202);
  const vec3 c6 = vec3(25.13112622477341, -12.24266895238567, -23.07032500287172);
  return c0 + t * (c1 + t * (c2 + t * (c3 + t * (c4 + t * (c5 + t * c6)))));
}

void main() {
  float raw = texture(u_image, v_uv).r;
  // Contrast stretch between the chosen black and white points, then gamma.
  float span = max(u_white - u_black, 1e-4);
  float t = clamp((raw - u_black) / span, 0.0, 1.0);
  t = pow(t, u_gamma);

  vec3 rgb;
  if (u_palette == 1) {
    rgb = viridis(t);
  } else if (u_palette == 2) {
    rgb = inferno(t);
  } else {
    rgb = vec3(t);
  }
  fragColor = vec4(clamp(rgb, 0.0, 1.0), 1.0);
}`;

const PALETTE_INDEX: Record<Palette, number> = {
  grey: 0,
  viridis: 1,
  inferno: 2,
};

/** Cap the raster. A spectrogram gains nothing from a 3x device ratio. */
const MAX_DPR = 2;

const UNIFORM_NAMES = [
  "u_image",
  "u_black",
  "u_white",
  "u_gamma",
  "u_palette",
] as const;

type UniformName = (typeof UNIFORM_NAMES)[number];

interface Params {
  blackPoint: number;
  whitePoint: number;
  gamma: number;
  palette: Palette;
}

function compile(
  gl: WebGL2RenderingContext,
  type: number,
  source: string,
): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

export default function WaterfallCanvas({
  src,
  width,
  height,
  alt,
  blackPoint,
  whitePoint,
  gamma,
  palette,
  onFallback,
}: WaterfallCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const glRef = useRef<WebGL2RenderingContext | null>(null);
  const programRef = useRef<WebGLProgram | null>(null);
  const uniformsRef = useRef<Partial<Record<UniformName, WebGLUniformLocation | null>>>(
    {},
  );
  const textureReadyRef = useRef(false);
  const frameRef = useRef(0);
  const paramsRef = useRef<Params>({ blackPoint, whitePoint, gamma, palette });

  const [fallback, setFallback] = useState<string | null>(null);
  const [visible, setVisible] = useState(false);

  const failTo = useCallback(
    (reason: string) => {
      setFallback(reason);
      onFallback?.(reason);
    },
    [onFallback],
  );

  /**
   * Draw one frame. Stable across renders: it reads the current control values
   * from a ref rather than closing over them, which is what keeps the context
   * from being rebuilt every time a slider moves.
   */
  const render = useCallback(() => {
    const gl = glRef.current;
    const canvas = canvasRef.current;
    if (!gl || !canvas || !programRef.current || !textureReadyRef.current) return;
    if (gl.isContextLost()) return;

    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    const targetWidth = Math.max(1, Math.round(canvas.clientWidth * dpr));
    const targetHeight = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
      canvas.width = targetWidth;
      canvas.height = targetHeight;
      gl.viewport(0, 0, targetWidth, targetHeight);
    }

    const u = uniformsRef.current;
    const p = paramsRef.current;
    gl.uniform1f(u.u_black ?? null, p.blackPoint);
    gl.uniform1f(u.u_white ?? null, p.whitePoint);
    gl.uniform1f(u.u_gamma ?? null, p.gamma);
    gl.uniform1i(u.u_palette ?? null, PALETTE_INDEX[p.palette]);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }, []);

  /** Coalesce every request inside one frame into a single draw. */
  const scheduleRender = useCallback(() => {
    if (frameRef.current) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = 0;
      render();
    });
  }, [render]);

  /* Only bring the context up once the canvas is actually on screen. A queue of
     cards would otherwise create contexts the browser will start evicting. */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.disconnect();
          }
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  /* The context, the program and the texture. Depends only on which image it is
     showing and whether it is on screen: nothing a control can change. */
  useEffect(() => {
    if (!visible || fallback) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Acquired once per canvas and kept across runs of this effect. Releasing it in
    // the cleanup was the defect: a force-lost context stays lost until something
    // calls restoreContext, and getContext on the same canvas returns that same lost
    // context, so the next run compiled nothing and landed in the shader-failure
    // branch permanently. next.config.mjs sets reactStrictMode, so in the dev server
    // every effect mounts, cleans up and mounts again: the shader path was dead in
    // development and a developer reading this file would have concluded the
    // opposite. Production was unaffected, which is why the build and the deployed
    // site both looked right.
    const cached = glRef.current;
    const gl =
      cached && !cached.isContextLost()
        ? cached
        : canvas.getContext("webgl2", {
            alpha: false,
            antialias: false,
            depth: false,
            stencil: false,
            desynchronized: true,
            powerPreference: "low-power",
            preserveDrawingBuffer: false,
          });
    if (!gl) {
      failTo("This browser did not provide a WebGL2 context.");
      return;
    }

    const vertex = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
    const fragment = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
    if (!vertex || !fragment) {
      if (vertex) gl.deleteShader(vertex);
      if (fragment) gl.deleteShader(fragment);
      failTo("The waterfall shader would not compile in this browser.");
      return;
    }
    const program = gl.createProgram();
    if (!program) {
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
      failTo("This browser would not allocate a shader program.");
      return;
    }
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteProgram(program);
      failTo("The waterfall shader would not link in this browser.");
      return;
    }

    glRef.current = gl;
    programRef.current = program;
    gl.useProgram(program);

    for (const name of UNIFORM_NAMES) {
      uniformsRef.current[name] = gl.getUniformLocation(program, name);
    }

    // One quad, uploaded once. A vertex array object keeps the attribute state
    // with the geometry, so nothing has to be rebound before a draw.
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const attribute = gl.getAttribLocation(program, "a_pos");
    gl.enableVertexAttribArray(attribute);
    gl.vertexAttribPointer(attribute, 2, gl.FLOAT, false, 0, 0);

    const texture = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform1i(uniformsRef.current.u_image ?? null, 0);

    // The stored bytes are measurements. Neither premultiplication nor a colour
    // space conversion may touch them on the way to the texture.
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);

    let cancelled = false;
    const image = new Image();
    image.decoding = "async";
    image.src = src;

    image
      .decode()
      .then(() => {
        if (cancelled || glRef.current !== gl || gl.isContextLost()) return;
        // Immutable single-channel storage: the image is intensity, and a
        // three-channel upload would cost three times the memory for two
        // channels nobody reads.
        gl.texStorage2D(gl.TEXTURE_2D, 1, gl.R8, image.width, image.height);
        gl.texSubImage2D(
          gl.TEXTURE_2D,
          0,
          0,
          0,
          image.width,
          image.height,
          gl.RED,
          gl.UNSIGNED_BYTE,
          image,
        );
        textureReadyRef.current = true;
        scheduleRender();
      })
      .catch(() => {
        if (!cancelled) failTo("The waterfall image could not be decoded.");
      });

    const onContextLost = (event: Event) => {
      // No preventDefault. Calling it is a request for a webglcontextrestored event,
      // and nothing here listens for one, so it asked the browser to keep a context
      // that could never come back and left the canvas blank behind live controls.
      // Falling back to the plain image is the honest response and the one this
      // component was designed around. Supporting a real restore would mean a
      // generation counter in the deps below plus a timeout that falls back when the
      // restore never arrives, which is more machinery than a lost context on a
      // static page justifies.
      void event;
      textureReadyRef.current = false;
      failTo("The browser released the WebGL context for this page.");
    };
    canvas.addEventListener("webglcontextlost", onContextLost);

    return () => {
      cancelled = true;
      canvas.removeEventListener("webglcontextlost", onContextLost);
      cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
      textureReadyRef.current = false;
      // The resources this run created, and nothing else. The context stays: it
      // belongs to the canvas, not to this run, and losing it here is what made a
      // second run permanent fallback.
      gl.deleteTexture(texture);
      gl.deleteBuffer(buffer);
      gl.deleteVertexArray(vao);
      gl.deleteProgram(program);
      programRef.current = null;
      uniformsRef.current = {};
    };
  }, [visible, src, fallback, failTo, scheduleRender]);

  /* The context is handed back on unmount and only on unmount. Browsers cap live
     contexts at around 16 and a queue of cards would exhaust that, so this cannot
     simply be left to garbage collection. Empty deps on purpose: this runs when the
     component goes away, never when its props change. */
  useEffect(
    () => () => {
      const gl = glRef.current;
      glRef.current = null;
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    },
    [],
  );

  /* Control changes: update the values the draw reads, then ask for one frame. */
  useEffect(() => {
    paramsRef.current = { blackPoint, whitePoint, gamma, palette };
    scheduleRender();
  }, [blackPoint, whitePoint, gamma, palette, scheduleRender]);

  /* Resize redraws. Skipped while the tab is hidden, where a draw is work nobody
     can see, and repeated once it comes back so the canvas is never stale. */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const onVisibility = () => {
      if (!document.hidden) scheduleRender();
    };
    document.addEventListener("visibilitychange", onVisibility);

    if (typeof ResizeObserver === "undefined") {
      return () => document.removeEventListener("visibilitychange", onVisibility);
    }
    const observer = new ResizeObserver(() => {
      if (document.hidden) return;
      scheduleRender();
    });
    observer.observe(canvas);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      observer.disconnect();
    };
  }, [scheduleRender]);

  if (fallback) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- the export is
      // unoptimised on purpose: these are measured intensities, and next/image
      // would re-encode them.
      <img
        src={src}
        width={width}
        height={height}
        alt={alt}
        style={{ width: "100%", height: "auto", display: "block" }}
      />
    );
  }

  return (
    <canvas
      ref={canvasRef}
      role="img"
      aria-label={alt}
      style={{
        width: "100%",
        aspectRatio: `${width} / ${height}`,
        display: "block",
        background: "var(--waterfall-ground)",
      }}
    />
  );
}
