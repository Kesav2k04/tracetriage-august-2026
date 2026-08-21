import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { gate3Result, physics } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Figure, Frame, Heading, Mono, progress, Reveal, VerdictMark } from "../ui";

const IMAGE_HEIGHT = 728;
const IMAGE_WIDTH = Math.round(
  (physics.image.width / physics.image.height) * IMAGE_HEIGHT,
);

const { rows, predictedPx, fittedPx, verticalPx, halfWidthPx } = physics.curve;
const SHIFT = fittedPx[0] - predictedPx[0];
const MID = Math.floor(rows.length / 2);

const path = (xs: number[]): string =>
  xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)} ${rows[i]}`).join(" ");

const PREDICTED_PATH = path(predictedPx);
const FITTED_PATH = path(fittedPx);
const BAND_PATH = `${path(fittedPx.map((x) => x - halfWidthPx))} ${fittedPx
  .map((x, i) => `L${(x + halfWidthPx).toFixed(2)} ${rows[i]}`)
  .reverse()
  .join(" ")} Z`;

/** The console's own overlay, drawn over the console's own image. */
const Waterfall: React.FC<{
  imageAt: number;
  verticalAt: number;
  predictedAt: number;
  fitAt: number;
  slideAt: number;
  gapAt: number;
}> = ({ imageAt, verticalAt, predictedAt, fitAt, slideAt, gapAt }) => {
  const frame = useCurrentFrame();
  const shown = progress(frame, imageAt, 16);
  const vertical = progress(frame, verticalAt);
  const predicted = progress(frame, predictedAt);
  const fit = progress(frame, fitAt);
  const slide = progress(frame, slideAt, 40);
  const gap = progress(frame, gapAt);
  const dx = interpolate(slide, [0, 1], [-SHIFT, 0]);
  return (
    <div
      style={{
        position: "relative",
        width: IMAGE_WIDTH,
        height: IMAGE_HEIGHT,
        background: token.waterfallGround,
        opacity: shown,
        border: `1px solid ${token.borderSubtle}`,
      }}
    >
      <Img
        src={staticFile(physics.image.src)}
        style={{ width: "100%", height: "100%", display: "block" }}
      />
      <svg
        width={IMAGE_WIDTH}
        height={IMAGE_HEIGHT}
        viewBox={`0 0 ${physics.image.width} ${physics.image.height}`}
        preserveAspectRatio="none"
        style={{ position: "absolute", inset: 0 }}
      >
        <line
          x1={verticalPx}
          y1={0}
          x2={verticalPx}
          y2={physics.image.height}
          stroke={token.text03}
          strokeWidth={1.5}
          strokeDasharray="6 6"
          vectorEffect="non-scaling-stroke"
          opacity={vertical}
        />
        <path
          d={PREDICTED_PATH}
          fill="none"
          stroke={token.interactive01}
          strokeWidth={2}
          strokeDasharray="4 5"
          vectorEffect="non-scaling-stroke"
          opacity={predicted}
        />
        <g transform={`translate(${dx.toFixed(2)} 0)`}>
          <path
            d={BAND_PATH}
            fill={token.text04}
            opacity={0.1 * fit * slide}
            stroke="none"
          />
          <path
            d={FITTED_PATH}
            fill="none"
            stroke={token.waterfallGround}
            strokeWidth={4.5}
            strokeOpacity={0.75 * fit}
            vectorEffect="non-scaling-stroke"
          />
          <path
            d={FITTED_PATH}
            fill="none"
            stroke={token.text04}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
            opacity={fit}
          />
        </g>
        <g opacity={gap}>
          <line
            x1={fittedPx[MID]}
            y1={rows[MID]}
            x2={predictedPx[MID]}
            y2={rows[MID]}
            stroke={token.text01}
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1={fittedPx[MID]}
            y1={rows[MID] - 26}
            x2={fittedPx[MID]}
            y2={rows[MID] + 26}
            stroke={token.text01}
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
          <line
            x1={predictedPx[MID]}
            y1={rows[MID] - 26}
            x2={predictedPx[MID]}
            y2={rows[MID] + 26}
            stroke={token.text01}
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
        </g>
      </svg>
    </div>
  );
};

const Legend: React.FC<{
  delay: number;
  colour: string;
  dash?: string;
  children: React.ReactNode;
}> = ({ delay, colour, dash, children }) => (
  <Reveal delay={delay}>
    <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
      <svg width={44} height={26} style={{ flex: "0 0 auto" }}>
        <line
          x1={0}
          y1={16}
          x2={44}
          y2={16}
          stroke={colour}
          strokeWidth={2.5}
          strokeDasharray={dash}
        />
      </svg>
      <div
        style={{
          fontFamily: font.sans,
          fontSize: 23,
          lineHeight: 1.5,
          color: token.text02,
        }}
      >
        {children}
      </div>
    </div>
  </Reveal>
);

const Meta: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
    <Mono size={15} colour={token.text03}>
      {label}
    </Mono>
    <span
      style={{
        fontFamily: font.mono,
        fontSize: 19,
        color: token.text01,
        ...numeric,
      }}
    >
      {value}
    </span>
  </div>
);

export const Physics: React.FC = () => (
  <Frame
    eyebrow="The physics"
    sources={[physics.offsetHz, gate3Result.verdict]}
  >
    <Reveal delay={2}>
      <Heading>The trace is a curve, and the pass fixes its shape.</Heading>
    </Reveal>

    <div style={{ display: "flex", gap: 56, marginTop: 24 }}>
      <Waterfall
        imageAt={8}
        verticalAt={78}
        predictedAt={150}
        fitAt={230}
        slideAt={250}
        gapAt={310}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 20 }}>
        <Reveal delay={40}>
          <div style={{ display: "flex", gap: 46, flexWrap: "wrap" }}>
            <Meta label="ground station" value={physics.station.display} />
            <Meta label="norad" value={physics.norad.display} />
            <Meta label="mode" value={physics.mode.display} />
            <Meta label="receive frequency" value={`${physics.rxMhz.display} MHz`} />
            <Meta label="start" value={physics.start.display} />
            <Meta
              label="peak elevation"
              value={`${physics.maxElevation.display} deg`}
            />
          </div>
        </Reveal>

        <Reveal delay={54}>
          <Body size={24} width={1180}>
            A pass Doppler-shifts what the receiver hears, so the carrier draws the
            whole shift as the satellite goes over. The shape comes from the orbit,
            propagated from the two-line elements in this observation's own record.
          </Body>
        </Reveal>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <Legend delay={82} colour={token.text03} dash="6 6">
            The commanded receive frequency. A capture corrected at the station would
            leave a line here.
          </Legend>
          <Legend delay={154} colour={token.interactive01} dash="4 5">
            The pass geometry at zero offset, spanning{" "}
            <strong style={{ color: token.text01, ...numeric }}>
              {physics.corridorSpanHz.display}
            </strong>{" "}
            Hz across this pass.
          </Legend>
          <Legend delay={252} colour={token.text04}>
            The same curve slid to its best match, with its half width shaded. The gap
            between the two is the measurement.
          </Legend>
        </div>

        <Reveal delay={318}>
          <div
            style={{
              display: "flex",
              gap: 64,
              alignItems: "baseline",
              borderTop: `1px solid ${token.borderSubtle}`,
              paddingTop: 22,
            }}
          >
            <Figure value={physics.offsetHz.display} unit="Hz" size={72} />
            <Figure value={physics.offsetPpm.display} unit="ppm" size={72} />
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <Mono size={19} colour={token.text02}>
                {physics.shiftPx.display} pixels
              </Mono>
              <Mono size={16} colour={token.text03}>
                at {physics.hzPerPx.display} Hz per pixel
              </Mono>
            </div>
          </div>
        </Reveal>

        <Reveal delay={402}>
          <div
            style={{
              background: token.ui01,
              border: `1px solid ${token.borderSubtle}`,
              padding: 22,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <VerdictMark verdict={gate3Result.verdict.value as string} />
              <Mono size={17} colour={token.text02}>
                gate {gate3Result.number.display}{" "}
                {gate3Result.verdict.display.replace("_", " ").toLowerCase()}
              </Mono>
            </div>
            <Body size={22} colour={token.text02}>
              Whether that corridor lands on a visible trace was tested on{" "}
              <strong style={{ color: token.text01, ...numeric }}>
                {gate3Result.scored.display}
              </strong>{" "}
              observations. All{" "}
              <strong style={{ color: token.text01, ...numeric }}>
                {gate3Result.discriminating.display}
              </strong>{" "}
              discriminated, which puts the 95% lower bound at{" "}
              <strong style={{ color: token.text01, ...numeric }}>
                {gate3Result.lowerBound.display}
              </strong>{" "}
              against a threshold of{" "}
              <strong style={{ color: token.text01, ...numeric }}>
                {gate3Result.threshold.display}
              </strong>
              . That is not enough to clear it.
            </Body>
          </div>
        </Reveal>
      </div>
    </div>
  </Frame>
);
