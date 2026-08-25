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

/**
 * A line sample drawn in the legend, in place of the name of a colour.
 *
 * The legend used to read "Solid blue is the fitted corridor" with the words tinted by
 * a token. When the palette moved, the tokens moved and the words did not, so the page
 * shipped the sentence "Solid blue" set in amber over a corridor drawn in amber. A
 * colour word in prose is a second copy of a design decision and it goes stale exactly
 * the way a hand-typed number does.
 *
 * Drawing the sample fixes more than the drift. A reader who cannot separate two hues
 * could never use "yellow" and "blue" as identifiers at all, and the dash pattern is
 * carried here too, so each series is identified by two channels rather than one.
 */
function Swatch({ stroke, dash }: { stroke: string; dash?: string }) {
  return (
    <svg
      width="22"
      height="8"
      viewBox="0 0 22 8"
      aria-hidden="true"
      style={{ verticalAlign: "middle", marginRight: "0.25rem" }}
    >
      <line
        x1="1"
        y1="4"
        x2="21"
        y2="4"
        stroke={stroke}
        strokeWidth="2"
        strokeDasharray={dash}
      />
    </svg>
  );
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
  // The display window, and it is a starting point rather than a derivation. These
  // two are absolute values handed to the shader, and one pair cannot be right for
  // this corpus: measured across the 25 committed waterfalls, the noise floor runs
  // from 0.2000 to 0.3843 and the 99.9th percentile from 0.3882 to 0.8980. Nineteen of
  // the 25 have a floor above 0.05, so the default spends most of the ramp below the
  // first real sample on most observations, which is why a weak pass opens looking
  // flat until the black point is moved.
  //
  // The honest fix is per-observation and it belongs in generated data, not here:
  // `scripts/build_console_data.py` already opens every image and could publish a
  // window per card the way the hero plate carries one. It is not done, so the
  // limitation is stated on the control rather than left for a reader to discover by
  // wondering why the plate looks empty.
  const [black, setBlack] = useState(0.05);
  const [white, setWhite] = useState(0.85);
  const [gamma, setGamma] = useState(1);
  // Inferno, matching the hero plate and the accent ramp, so a reader who arrives
  // from the landing page is not handed a second colour map for the same instrument.
  // Grey and viridis stay in the select: the point of offering them is that a reader
  // who wants the data as SatNOGS published it, or the map they are used to, has it.
  const [palette, setPalette] = useState<Palette>("inferno");
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
                  stroke="var(--interactive-01)"
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
              fill="rgba(255, 255, 255, 0.14)"
              stroke="none"
            />
            {/* White, not an accent, and for the same reason the hero plate draws its
                corridor in white: this is the answer the page is about, and it has to
                separate from both of the other two curves and from every value the
                colour map can produce underneath it. On the old palette the fitted
                corridor was Carbon blue and the zero-offset geometry was amber, which
                are opposites; drawn in interactive-04 and support-03 off the inferno
                ramp they became amber and orange, one ramp step apart, and the two
                curves the whole measurement is a comparison between stopped being
                distinguishable. */}
            {/* A near-black casing under the corridor, on the same path so it cannot
                displace it. The hero plate has carried one since it was built and this
                view did not, which was survivable while the default map was viridis
                and its top end was yellow-green. Inferno's top end is near-white, and
                a white corridor crossing a bright band on a strong signal would have
                disappeared into exactly the observations a reviewer most needs to
                read. The casing costs one path and makes the overlay legible on all
                three maps, including grey. */}
            <path
              d={pathFrom(corridor.rows, corridor.fitted_px)}
              fill="none"
              stroke="var(--waterfall-ground)"
              strokeWidth={4.5}
              strokeOpacity={0.75}
              vectorEffect="non-scaling-stroke"
            />
            <path
              d={pathFrom(corridor.rows, corridor.fitted_px)}
              fill="none"
              stroke="var(--text-04)"
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
            <Swatch stroke="var(--text-04)" /> the fitted corridor, the path the
            matched filter scored, with its half width shaded.{" "}
            <Swatch stroke="var(--interactive-01)" dash="4 5" /> the same pass geometry
            at zero frequency offset.{" "}
            <Swatch stroke="var(--text-03)" dash="6 6" /> the commanded receive
            frequency, where a Doppler-corrected capture would sit. The gap between the
            first two is the measurement.
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
            // 9rem truncated the overlay control to "Fitted, predicted and ce"
            // at 1440 and to "Fitted, predicted a" at 390, on the one control
            // that explains what the three lines over the flagship image are.
            // 13.5rem fits the longest option at the body size, and auto-fit
            // still collapses to one column on a narrow screen.
            gridTemplateColumns: "repeat(auto-fit, minmax(min(13.5rem, 100%), 1fr))",
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

          <p
            style={{
              margin: "0 0 var(--sp-04)",
              fontSize: "var(--type-caption)",
              color: "var(--text-03)",
              lineHeight: 1.55,
            }}
          >
            The black and white points open at a fixed pair, not one fitted to this
            image. Across the 25 committed waterfalls the noise floor runs from 0.20 to
            0.38, so on most observations the ramp starts well below the first real
            sample and a weak pass reads flat until the black point is raised toward
            the floor.
          </p>
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
  // A select in a grid column is sized by the column, not by its content, so
  // without this it inherits whatever the track gives it and clips its own
  // selected option. minWidth 0 keeps it from forcing the track wider than the
  // figure on a narrow screen.
  width: "100%",
  minWidth: 0,
};
