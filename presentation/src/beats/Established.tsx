import React from "react";
import { useCurrentFrame } from "remotion";
import { established, lift } from "../data";
import { font, numeric, token } from "../theme";
import {
  Body,
  Eyebrow,
  Frame,
  Heading,
  Mono,
  progress,
  Reveal,
  Rule,
  VerdictMark,
} from "../ui";

/**
 * The beat the film was missing.
 *
 * Every earlier cut ended on a verdict that came back inconclusive, which is the
 * honest reading of the gate that was pre-registered and is not the whole state of
 * the evidence. Three results were decided, on the same receipts and the same
 * resampling, and a film that omits them to keep a tidy arc is doing the thing this
 * project spent six gates arguing against. So this beat runs after the tally rather
 * than before it: the negatives are stated in full first, then what holds.
 *
 * Nothing here is softened and nothing is new. Each figure is a key path into
 * AGENT_RECEIPT.json, EXPLAIN_RECEIPT.json or QUEUE_RECEIPT.json, resolved at build
 * time, and the console prints all three on pages a viewer can open.
 */

const PLATE_WIDTH = 536;
const PLATE_GAP = 42;

/** A plate's own heading. Small, so the measurement under it carries the weight. */
const PlateTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontFamily: font.sans,
      fontWeight: 600,
      fontSize: 25,
      lineHeight: 1.25,
      color: token.text01,
      minHeight: 62,
    }}
  >
    {children}
  </div>
);

/** The figure line inside a plate, sized down from the film's hero figure. */
const PlateFigure: React.FC<{
  value: string;
  unit: string;
  colour?: string;
}> = ({ value, unit, colour = token.text01 }) => (
  <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
    <span
      style={{
        fontFamily: font.sans,
        fontWeight: 600,
        fontSize: 78,
        lineHeight: 1,
        letterSpacing: -1,
        color: colour,
        ...numeric,
      }}
    >
      {value}
    </span>
    <span
      style={{
        fontFamily: font.sans,
        fontWeight: 400,
        fontSize: 24,
        color: token.text03,
      }}
    >
      {unit}
    </span>
  </div>
);

/**
 * The paired arms, drawn to the same scale.
 *
 * Two bars against a shared trial count rather than two percentages, because the
 * design is paired: the same questions were put to the same model twice, and a pair
 * of proportions side by side would invite the reader to treat them as independent.
 */
const PairedArms: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const grow = progress(frame, delay, 20);
  const trials = established.trials.value as number;
  const width = PLATE_WIDTH - 56;
  const arms = [
    {
      label: "with the evidence tools",
      count: established.withTools,
      colour: token.interactive01,
    },
    {
      label: "with no tools at all",
      count: established.withoutTools,
      colour: token.ui04,
    },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {arms.map((arm, index) => (
        <div key={arm.label} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <Mono size={17} colour={token.text02}>
              {arm.label}
            </Mono>
            <Mono size={17} colour={arm.colour}>
              {arm.count.display}
            </Mono>
          </div>
          <svg width={width} height={12} style={{ display: "block" }}>
            <rect x={0} y={0} width={width} height={12} fill={token.surfaceSunken} />
            <rect
              x={0}
              y={0}
              width={
                ((arm.count.value as number) / trials) *
                width *
                progress(frame, delay + index * 8, 20)
              }
              height={12}
              fill={arm.colour}
            />
          </svg>
        </div>
      ))}
      <div style={{ opacity: grow }}>
        <Mono size={16} colour={token.text03}>
          both arms scored out of {established.trials.display}
        </Mono>
      </div>
    </div>
  );
};

/** The held-out interval, drawn against the bar the gate named. */
const HeldOutInterval: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const draw = progress(frame, delay, 18);
  const width = PLATE_WIDTH - 56;
  const min = 1;
  const max = Math.ceil(((established.coldCiHigh.value as number) + 0.15) * 10) / 10;
  const at = (v: number) => ((v - min) / (max - min)) * width;
  const low = at(established.coldCiLow.value as number);
  const high = at(established.coldCiHigh.value as number);
  const point = at(established.coldLift.value as number);
  // The bar is gate 6's threshold, read from the receipt rather than typed: the two
  // splits are the same gate asked of different data, so they are drawn to one bar.
  const bar = at(lift.threshold.value as number);
  return (
    <svg width={width} height={78} style={{ display: "block" }}>
      <line x1={0} y1={44} x2={width * draw} y2={44} stroke={token.ui02} strokeWidth={2} />
      <line
        x1={bar}
        y1={16}
        x2={bar}
        y2={62}
        stroke={token.text02}
        strokeWidth={1.5}
        strokeDasharray="4 4"
        opacity={draw}
      />
      <rect
        x={low}
        y={36}
        width={(high - low) * draw}
        height={16}
        fill={token.ui04}
        opacity={0.85}
      />
      <circle cx={point} cy={44} r={7 * draw} fill={token.interactive01} />
      <text
        x={low}
        y={74}
        fill={token.text03}
        fontFamily={font.mono}
        fontSize={17}
        textAnchor="middle"
        opacity={draw}
      >
        {established.coldCiLow.display}
      </text>
      <text
        x={Math.min(high, width - 14)}
        y={74}
        fill={token.text03}
        fontFamily={font.mono}
        fontSize={17}
        textAnchor="middle"
        opacity={draw}
      >
        {established.coldCiHigh.display}
      </text>
      <text
        x={bar}
        y={12}
        fill={token.text02}
        fontFamily={font.mono}
        fontSize={16}
        textAnchor="middle"
        opacity={draw}
      >
        the bar
      </text>
    </svg>
  );
};

export const Established: React.FC = () => (
  <Frame
    eyebrow="What holds"
    sources={[
      established.withTools,
      established.adversarialCaught,
      established.coldLift,
    ]}
  >
    <Reveal delay={2}>
      <Heading>Three results that did come back decided.</Heading>
    </Reveal>

    <Reveal delay={10}>
      <div style={{ marginTop: 16 }}>
        <Body width={1560}>
          Measured on the same receipts, at the same thresholds, with the same
          resampling as the gates. The pre-registered gate came back inconclusive.
          These did not.
        </Body>
      </div>
    </Reveal>

    <div style={{ display: "flex", gap: PLATE_GAP, marginTop: 44 }}>
      <Reveal delay={24} rise={10}>
        <div
          style={{
            width: PLATE_WIDTH,
            background: token.ui01,
            border: `1px solid ${token.borderSubtle}`,
            padding: 28,
            display: "flex",
            flexDirection: "column",
            gap: 20,
          }}
        >
          <Eyebrow>the agent study</Eyebrow>
          <PlateTitle>
            The evidence tools change what a local model gets right.
          </PlateTitle>
          <PlateFigure
            value={established.withTools.display}
            unit={`of ${established.trials.display} correct`}
            colour={token.interactive01}
          />
          <PairedArms delay={40} />
          <Rule delay={62} />
          <Body size={20} colour={token.text02}>
            {established.model.display}, run on one machine. The same questions were
            put to it twice. Paired exact test on the{" "}
            {established.discordant.display} pairs that disagreed, one sided{" "}
            {established.pairedP.display}.
          </Body>
        </div>
      </Reveal>

      <Reveal delay={38} rise={10}>
        <div
          style={{
            width: PLATE_WIDTH,
            background: token.ui01,
            border: `1px solid ${token.borderSubtle}`,
            padding: 28,
            display: "flex",
            flexDirection: "column",
            gap: 20,
          }}
        >
          <Eyebrow>the grounding checker</Eyebrow>
          <PlateTitle>
            Every planted falsehood caught, and no clean draft refused.
          </PlateTitle>
          <PlateFigure
            value={established.adversarialCaught.display}
            unit={`of ${established.adversarialChecks.display} caught`}
            colour={token.interactive01}
          />
          <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <span
              style={{
                fontFamily: font.sans,
                fontWeight: 600,
                fontSize: 44,
                lineHeight: 1,
                color: token.text01,
                ...numeric,
              }}
            >
              {established.controlRefused.display}
            </span>
            <span style={{ fontFamily: font.sans, fontSize: 21, color: token.text03 }}>
              of {established.controlChecks.display} clean drafts refused
            </span>
          </div>
          <Rule delay={76} />
          <Body size={20} colour={token.text02}>
            Both arms, because a checker that refuses everything scores perfectly on
            the first. On the notes the model actually wrote it refused{" "}
            {established.refusedOfDrafts.display} of{" "}
            {established.draftsDecided.display} and the refusals are published.
          </Body>
        </div>
      </Reveal>

      <Reveal delay={52} rise={10}>
        <div
          style={{
            width: PLATE_WIDTH,
            background: token.ui01,
            border: `1px solid ${token.borderSubtle}`,
            padding: 28,
            display: "flex",
            flexDirection: "column",
            gap: 20,
          }}
        >
          <Eyebrow>the held-out split</Eyebrow>
          <PlateTitle>
            On ground stations the queue was never fitted to, it clears the bar.
          </PlateTitle>
          <PlateFigure
            value={established.coldLift.display}
            unit="times random, at the same budget"
            colour={token.interactive01}
          />
          <HeldOutInterval delay={70} />
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <VerdictMark verdict={established.coldVerdict.value as string} />
            <span
              style={{
                fontFamily: font.sans,
                fontWeight: 600,
                fontSize: 24,
                letterSpacing: 0.6,
                color: token.text01,
              }}
            >
              {established.coldVerdict.display}
            </span>
            <Mono size={17} colour={token.text03}>
              interval above it, not spanning it
            </Mono>
          </div>
          <Body size={20} colour={token.text02}>
            {established.coldStationGroups.display} station groups, the wider of two
            resamplings:{" "}
            {(established.coldInterval.display as string).replace(/_/g, " ")}.
          </Body>
        </div>
      </Reveal>
    </div>

    <Reveal delay={300}>
      <div style={{ marginTop: 40 }}>
        <Mono size={19} colour={token.interactive01}>
          each of the three is a page on the console, with the receipt beside it
        </Mono>
      </div>
    </Reveal>
  </Frame>
);
