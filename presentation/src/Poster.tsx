import React from "react";
import { Img, staticFile } from "remotion";
import { corpus, gates, physics } from "./data";
import { font, numeric, token } from "./theme";

/**
 * The thumbnail, designed as a thumbnail rather than taken as a frame of the film.
 *
 * A still lifted out of the film is a card built to be read at full size over twenty
 * seconds of narration. A thumbnail is read at about 160 pixels wide, in a grid, in
 * under a second, by somebody who has not decided to watch anything yet. Those are
 * different jobs, and the poster this replaces was doing the first one in the second
 * one's slot: eleven figures, four paragraphs and a footnote, none of it legible small.
 *
 * So this holds one idea and two numbers: the record's verdict for a real pass, and the
 * measurement the same pass contains. Neither was written for the thumbnail.
 * `with-signal` is the network's own status field and +32.05 is the fitted offset, both
 * resolved out of the same receipts the physics card draws, so the hook is the finding
 * rather than copy about the finding.
 *
 * Laid out at 1920x1080 and rendered at scale 2, which is the composition size the film
 * uses. Sizes are set against the small render: nothing on the card is under 22px here,
 * which survives the downscale to a grid thumbnail, and the two figures are set at 75
 * and 150 so the contradiction still reads when the words have stopped resolving.
 */

const PANEL_W = 648;
const PANEL_H = 1080;
// The capture is 620x1540. Filling the panel by width crops it vertically rather than
// letterboxing it, which keeps the trace at a size that reads as a signal.
const IMAGE_W = PANEL_W;
const IMAGE_H = Math.round((physics.image.height / physics.image.width) * PANEL_W);
const IMAGE_TOP = Math.round((PANEL_H - IMAGE_H) / 2);

const { rows, predictedPx, fittedPx, halfWidthPx } = physics.curve;

const path = (xs: number[]): string =>
  xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${rows[i]}`).join(" ");

const BAND = `${path(fittedPx.map((x) => x - halfWidthPx))} ${fittedPx
  .map((x, i) => `L${(x + halfWidthPx).toFixed(2)} ${rows[i]}`)
  .reverse()
  .join(" ")} Z`;

const LEFT = 742;

const Eyebrow: React.FC<{ colour: string; top: number; children: React.ReactNode }> = ({
  colour,
  top,
  children,
}) => (
  <div
    style={{
      position: "absolute",
      left: LEFT,
      top,
      fontFamily: font.mono,
      fontSize: 23,
      letterSpacing: 3,
      textTransform: "uppercase",
      color: colour,
    }}
  >
    {children}
  </div>
);

export const Poster: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: token.uiBackground,
      fontFamily: font.sans,
      overflow: "hidden",
    }}
  >
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: PANEL_W,
        height: PANEL_H,
        overflow: "hidden",
        background: token.waterfallGround,
      }}
    >
      <div
        style={{ position: "absolute", left: 0, top: IMAGE_TOP, width: IMAGE_W, height: IMAGE_H }}
      >
        <Img
          src={staticFile(physics.image.src)}
          style={{ width: "100%", height: "100%", display: "block" }}
        />
        <svg
          width={IMAGE_W}
          height={IMAGE_H}
          viewBox={`0 0 ${physics.image.width} ${physics.image.height}`}
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0 }}
        >
          <path d={BAND} fill={token.interactive01} opacity={0.15} />
          <path
            d={path(predictedPx)}
            fill="none"
            stroke={token.interactive01}
            strokeWidth={2.5}
            strokeDasharray="9 8"
            vectorEffect="non-scaling-stroke"
          />
          <path
            d={path(fittedPx)}
            fill="none"
            stroke={token.text04}
            strokeWidth={4}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
      {/* Feathered so the capture joins the ground instead of ending at a hard seam. */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            `linear-gradient(90deg, transparent 0%, transparent 55%, ` +
            `${token.uiBackground} 100%)`,
        }}
      />
    </div>

    <Eyebrow colour={token.text03} top={196}>
      The record for this pass said
    </Eyebrow>
    <div
      style={{
        position: "absolute",
        left: LEFT,
        top: 232,
        fontFamily: font.mono,
        fontSize: 78,
        lineHeight: 1,
        color: token.text02,
        ...numeric,
      }}
    >
      {physics.status.display}
    </div>

    <div
      style={{
        position: "absolute",
        left: LEFT,
        top: 366,
        width: 300,
        height: 3,
        background: token.interactive01,
      }}
    />

    <Eyebrow colour={token.interactive01} top={416}>
      The physics said
    </Eyebrow>
    <div
      style={{
        position: "absolute",
        left: LEFT,
        top: 446,
        display: "flex",
        alignItems: "baseline",
        gap: 16,
      }}
    >
      <span
        style={{
          fontFamily: font.sans,
          fontWeight: 600,
          fontSize: 190,
          lineHeight: 1,
          letterSpacing: -7,
          color: token.text04,
          ...numeric,
        }}
      >
        {physics.offsetPpm.display}
      </span>
      <span
        style={{
          fontFamily: font.sans,
          fontWeight: 400,
          fontSize: 54,
          color: token.text02,
        }}
      >
        ppm
      </span>
    </div>

    <div
      style={{
        position: "absolute",
        left: LEFT,
        top: 690,
        right: 80,
        fontFamily: font.sans,
        fontWeight: 600,
        fontSize: 66,
        lineHeight: 1.1,
        letterSpacing: -1,
        color: token.text01,
      }}
    >
      Nobody wrote that down.
    </div>

    <div
      style={{
        position: "absolute",
        left: LEFT,
        right: 80,
        bottom: 84,
      }}
    >
      <div
        style={{
          fontFamily: font.sans,
          fontWeight: 600,
          fontSize: 48,
          letterSpacing: -0.5,
          color: token.text01,
        }}
      >
        TraceTriage
      </div>
      <div
        style={{
          marginTop: 8,
          fontFamily: font.mono,
          fontSize: 24,
          color: token.text03,
          ...numeric,
        }}
      >
        {corpus.observations.display} captures &middot; {gates.total.display} gates
        written before measuring
      </div>
    </div>
  </div>
);
