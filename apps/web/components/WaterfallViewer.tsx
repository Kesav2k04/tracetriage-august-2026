"use client";

/**
 * The waterfall with its Doppler corridor drawn on top.
 *
 * The three curves are the whole argument of this project rendered in one frame:
 *
 *   - the vertical line is where a Doppler-corrected capture would put the trace,
 *     and where the commanded receive frequency sits;
 *   - the predicted curve is the pass geometry from the TLE, at zero frequency
 *     offset, which is where the trace should be if the catalogue is right;
 *   - the fitted curve is the same geometry shifted by the offset the matched
 *     filter actually found.
 *
 * The gap between the last two is the measurement. On observation 14740031 it is
 * 113 pixels, which is 13,985 Hz, which is 32 ppm, and it is invisible in the
 * metadata because the commanded receive frequency matches the catalogue exactly.
 *
 * The paths are not drawn by this component. They come from
 * physics.corridor_columns via the export script, so what is on screen is the
 * path the matched filter scored rather than a picture of roughly that idea.
 *
 * The overlay is SVG in the image's own pixel space, sharing a viewBox with the
 * canvas beneath it. That keeps the two aligned under any scale without either
 * one knowing the other's size.
 */

import { useId, useState } from "react";

import type { CorridorGeometry } from "@/lib/data";
import { svgPolyline } from "@/lib/plot-path";
import WaterfallCanvas, { type Palette } from "./WaterfallCanvas";

export interface WaterfallViewerProps {
  src: string;
  width: number;
  height: number;
  obsId: number;
  corridor: CorridorGeometry | null | undefined;
  corridorNote: string | null | undefined;
  hzPerPx: number | undefined;
  secondsPerPx: number | undefined;
}

type OverlayMode = "all" | "fitted" | "none";

// Two decimal places on a curve drawn over a raster: the overlay is placed in
// image pixels, so a hundredth of a pixel is far below anything visible and
// keeps the markup small.
function pathFrom(rows: number[], columns: number[]): string {
  return svgPolyline(rows, columns, 2);
}

export default function WaterfallViewer({
  src,
  width,
  height,
  obsId,
  corridor,
  corridorNote,
  hzPerPx,
  secondsPerPx,
}: WaterfallViewerProps) {
  const [black, setBlack] = useState(0.05);
  const [white, setWhite] = useState(0.85);
  const [gamma, setGamma] = useState(1);
  const [palette, setPalette] = useState<Palette>("viridis");
  const [overlay, setOverlay] = useState<OverlayMode>("all");
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);
  const controlId = useId();

  const showFitted = overlay !== "none";
  const showRest = overlay === "all";

  return (
    <figure className="viewer" style={{ margin: 0 }}>
      <div
        style={{
          position: "relative",
          background: "var(--waterfall-ground)",
          border: "1px solid var(--border-subtle)",
          // Never wider than the measurement. One screen pixel is one measured
          // pixel on any display wide enough to hold it.
          maxWidth: width,
          width: "100%",
        }}
      >
        <WaterfallCanvas
          src={src}
          width={width}
          height={height}
          alt={
            `Waterfall for observation ${obsId}. Frequency runs left to right, ` +
            `time runs bottom to top. ` +
            (corridor
              ? `The fitted Doppler corridor sits ${Math.abs(
                  corridor.fitted_offset_hz,
                ).toFixed(0)} hertz from the commanded receive frequency.`
              : "No corridor geometry is available for this observation.")
          }
          blackPoint={black}
          whitePoint={white}
          gamma={gamma}
          palette={palette}
          onFallback={setFallbackReason}
        />

        {/*
          Without JavaScript the canvas is an empty black box, so the same image
          is served as a plain <img> and the canvas is hidden. The corridor
          overlay is server-rendered SVG and needs nothing, so a reader with
          scripting off still gets the measurement drawn on the waterfall.
        */}
        <noscript>
          <style>{".viewer canvas { display: none; }"}</style>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={src}
            width={width}
            height={height}
            alt={`Waterfall for observation ${obsId}.`}
            style={{ width: "100%", height: "auto", display: "block" }}
          />
        </noscript>

        {/* The replay cursor's row marker.
            Inside its own SVG rather than a positioned div, and for a specific
            reason: this overlay carries preserveAspectRatio="none" and a viewBox of
            the image's own pixels, so one user unit is one image row at any display
            size. A div translated by a pixel count would be correct only while the
            frame happens to be displayed at exactly 1:1, and would drift off the row
            it names on every narrower viewport.

            It is a separate overlay from the corridor's because the corridor is
            withheld on records with no frequency axis, and the pass clock still runs
            on those. */}
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          aria-hidden="true"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
          }}
        >
          <g id="waterfall-row-cursor" className="replay-cursor-row">
            <line x1={0} x2={width} y1={0} y2={0} />
          </g>
        </svg>

        {corridor && showFitted && (
          <svg
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            aria-hidden="true"
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              pointerEvents: "none",
            }}
          >
            {showRest && (
              <>
                {/* Where a corrected capture would place the trace. */}
                <line
                  x1={corridor.vertical_px}
                  y1={0}
                  x2={corridor.vertical_px}
                  y2={height}
                  stroke="var(--text-03)"
                  strokeWidth={1.5}
                  strokeDasharray="6 6"
                  vectorEffect="non-scaling-stroke"
                />
                {/* The TLE geometry at zero offset. */}
                <path
                  d={pathFrom(corridor.rows, corridor.predicted_px)}
                  fill="none"
                  stroke="var(--support-03)"
                  strokeWidth={1.5}
                  strokeDasharray="4 5"
                  vectorEffect="non-scaling-stroke"
                />
              </>
            )}

            {/* The corridor the matched filter scored, with its half width. */}
            <path
              d={
                pathFrom(
                  corridor.rows,
                  corridor.fitted_px.map((x) => x - corridor.half_width_px),
                ) +
                pathFrom(
                  [...corridor.rows].reverse(),
                  [...corridor.fitted_px]
                    .reverse()
                    .map((x) => x + corridor.half_width_px),
                ).replace("M", "L") +
                "Z"
              }
              fill="rgba(69, 137, 255, 0.16)"
              stroke="none"
            />
            <path
              d={pathFrom(corridor.rows, corridor.fitted_px)}
              fill="none"
              stroke="var(--interactive-04)"
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}
      </div>

      <div className="viewer-controls">
      <figcaption
        style={{
          margin: 0,
          fontSize: "var(--type-caption)",
          color: "var(--text-02)",
          lineHeight: 1.6,
        }}
      >
        {corridor ? (
          <>
            <span style={{ color: "var(--interactive-04)" }}>Solid blue</span> is the fitted
            corridor, the path the matched filter scored.{" "}
            <span style={{ color: "var(--support-03)" }}>Dashed yellow</span> is the same
            pass geometry at zero frequency offset.{" "}
            <span style={{ color: "var(--text-03)" }}>Dashed grey</span> is the commanded
            receive frequency, where a Doppler-corrected capture would sit. The
            gap between yellow and blue is the measurement.
          </>
        ) : (
          <>
            No corridor overlay for this observation.{" "}
            {corridorNote ?? "No reason was recorded, which is itself a defect."}
          </>
        )}
        {hzPerPx && secondsPerPx ? (
          <>
            {" "}
            Scale: <span className="num">{hzPerPx.toFixed(1)}</span> Hz per pixel
            across, <span className="num">{secondsPerPx.toFixed(3)}</span> seconds
            per pixel down, drawn one screen pixel to one measured pixel.
          </>
        ) : null}
      </figcaption>

      {fallbackReason && (
        <p
          style={{
            marginTop: "var(--sp-04)",
            padding: "var(--sp-03) var(--sp-04)",
            borderLeft: "3px solid var(--support-03)",
            background: "var(--ui-01)",
            fontSize: "var(--type-caption)",
            color: "var(--text-02)",
          }}
        >
          Showing the plain image: {fallbackReason} The measurement is unaffected,
          because the contrast controls only change how the same pixels are
          displayed.
        </p>
      )}

      {!fallbackReason && (
        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(9rem, 1fr))",
            marginTop: "var(--sp-05)",
            padding: "var(--sp-05)",
            background: "var(--ui-01)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          <label htmlFor={`${controlId}-black`} style={labelStyle}>
            Black point <span className="num">{black.toFixed(2)}</span>
            <input
              id={`${controlId}-black`}
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={black}
              onChange={(event) =>
                setBlack(Math.min(Number(event.target.value), white - 0.02))
              }
              style={rangeStyle}
            />
          </label>

          <label htmlFor={`${controlId}-white`} style={labelStyle}>
            White point <span className="num">{white.toFixed(2)}</span>
            <input
              id={`${controlId}-white`}
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={white}
              onChange={(event) =>
                setWhite(Math.max(Number(event.target.value), black + 0.02))
              }
              style={rangeStyle}
            />
          </label>

          <label htmlFor={`${controlId}-gamma`} style={labelStyle}>
            Gamma <span className="num">{gamma.toFixed(2)}</span>
            <input
              id={`${controlId}-gamma`}
              type="range"
              min={0.3}
              max={3}
              step={0.05}
              value={gamma}
              onChange={(event) => setGamma(Number(event.target.value))}
              style={rangeStyle}
            />
          </label>

          <label htmlFor={`${controlId}-palette`} style={labelStyle}>
            Palette
            <select
              id={`${controlId}-palette`}
              value={palette}
              onChange={(event) => setPalette(event.target.value as Palette)}
              style={selectStyle}
            >
              <option value="viridis">Viridis</option>
              <option value="inferno">Inferno</option>
              <option value="grey">Greyscale</option>
            </select>
          </label>

          <label htmlFor={`${controlId}-overlay`} style={labelStyle}>
            Overlay
            <select
              id={`${controlId}-overlay`}
              value={overlay}
              onChange={(event) => setOverlay(event.target.value as OverlayMode)}
              style={selectStyle}
            >
              <option value="all">Fitted, predicted and centre</option>
              <option value="fitted">Fitted corridor only</option>
              <option value="none">No overlay</option>
            </select>
          </label>
        </div>
      )}
      </div>
    </figure>
  );
}

const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "var(--sp-02)",
  fontSize: "var(--type-label)",
  color: "var(--text-02)",
};

const rangeStyle: React.CSSProperties = {
  width: "100%",
  accentColor: "var(--interactive-04)",
};

const selectStyle: React.CSSProperties = {
  background: "var(--field-01)",
  color: "var(--text-01)",
  border: "1px solid var(--border-strong)",
  padding: "var(--sp-02) var(--sp-03)",
  fontSize: "var(--type-body)",
  fontFamily: "inherit",
};
