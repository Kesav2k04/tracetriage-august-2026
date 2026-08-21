import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { lift } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Frame, Heading, Mono, progress, Reveal, VerdictMark } from "../ui";

const BAR_WIDTH = 520;
const BAR_HEIGHT = 34;
const CEILING = lift.totalConflicts.value;

const RAIL_WIDTH = 720;
const AXIS_MIN = 1;
const AXIS_MAX = Math.ceil((lift.ciHigh.value + 0.08) * 10) / 10;
const atLift = (value: number) =>
  ((value - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * RAIL_WIDTH;

const ConflictBar: React.FC<{
  delay: number;
  label: string;
  count: string;
  value: number;
  colour: string;
  dashed?: boolean;
}> = ({ delay, label, count, value, colour, dashed }) => {
  const frame = useCurrentFrame();
  const grow = progress(frame, delay, 20);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <div style={{ width: 250, textAlign: "right" }}>
        <span
          style={{
            fontFamily: font.sans,
            fontSize: 22,
            color: token.text02,
          }}
        >
          {label}
        </span>
      </div>
      <svg width={BAR_WIDTH} height={BAR_HEIGHT} style={{ display: "block" }}>
        <rect
          x={0}
          y={0}
          width={(value / CEILING) * BAR_WIDTH * grow}
          height={BAR_HEIGHT}
          fill={dashed ? "none" : colour}
          stroke={dashed ? colour : "none"}
          strokeWidth={dashed ? 1.5 : 0}
          strokeDasharray={dashed ? "5 4" : undefined}
        />
      </svg>
      <span
        style={{
          fontFamily: font.sans,
          fontWeight: 600,
          fontSize: 30,
          color: dashed ? token.text02 : token.text01,
          opacity: grow,
          ...numeric,
        }}
      >
        {count}
      </span>
    </div>
  );
};

const LiftRail: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const rail = progress(frame, delay, 16);
  const band = progress(frame, delay + 22, 20);
  const dot = progress(frame, delay + 48, 12);
  const x0 = atLift(lift.ciLow.value);
  const x1 = atLift(lift.ciHigh.value);
  const xPoint = atLift(lift.point.value);
  const xThreshold = atLift(lift.threshold.value);
  const xFifo = atLift(lift.fifoLift.value);
  const fifo = progress(frame, delay + 70, 12);
  return (
    <svg width={RAIL_WIDTH + 40} height={252} style={{ display: "block" }}>
      <line
        x1={0}
        y1={150}
        x2={RAIL_WIDTH * rail}
        y2={150}
        stroke={token.ui02}
        strokeWidth={2}
      />
      <line
        x1={xThreshold}
        y1={30}
        x2={xThreshold}
        y2={178}
        stroke={token.text02}
        strokeWidth={1.5}
        strokeDasharray="4 4"
        opacity={rail}
      />
      <text
        x={xThreshold + 12}
        y={44}
        fill={token.text02}
        fontFamily={font.mono}
        fontSize={19}
        opacity={rail}
      >
        threshold {lift.threshold.display}
      </text>
      <rect
        x={x0}
        y={138}
        width={(x1 - x0) * band}
        height={24}
        fill={token.ui04}
        opacity={0.85}
      />
      <line
        x1={x0}
        y1={128}
        x2={x0}
        y2={172}
        stroke={token.text02}
        strokeWidth={2}
        opacity={band}
      />
      <line
        x1={x1}
        y1={128}
        x2={x1}
        y2={172}
        stroke={token.text02}
        strokeWidth={2}
        opacity={band * band}
      />
      <text
        x={x0}
        y={200}
        fill={token.text03}
        fontFamily={font.mono}
        fontSize={19}
        textAnchor="middle"
        opacity={band}
      >
        {lift.ciLow.display}
      </text>
      <text
        x={x1}
        y={200}
        fill={token.text03}
        fontFamily={font.mono}
        fontSize={19}
        textAnchor="middle"
        opacity={band * band}
      >
        {lift.ciHigh.display}
      </text>
      <text
        x={0}
        y={132}
        fill={token.text03}
        fontFamily={font.mono}
        fontSize={18}
        opacity={rail}
      >
        no better than random
      </text>
      <line
        x1={xFifo}
        y1={138}
        x2={xFifo}
        y2={162}
        stroke={token.text03}
        strokeWidth={2}
        opacity={fifo}
      />
      <text
        x={Math.max(0, xFifo - 40)}
        y={232}
        fill={token.text03}
        fontFamily={font.mono}
        fontSize={18}
        opacity={fifo}
      >
        first in, first out {lift.fifoLift.display}
      </text>
      <circle
        cx={xPoint}
        cy={150}
        r={interpolate(dot, [0, 1], [0, 9])}
        fill={token.text01}
      />
      <text
        x={xPoint}
        y={112}
        fill={token.text01}
        fontFamily={font.sans}
        fontWeight={600}
        fontSize={40}
        textAnchor="middle"
        opacity={dot}
      >
        {lift.point.display}
      </text>
    </svg>
  );
};

export const Result: React.FC = () => (
  <Frame eyebrow="The result" sources={[lift.point, lift.verdict]}>
    <Reveal delay={2}>
      <Heading>Both halves of the result.</Heading>
    </Reveal>

    <Reveal delay={10}>
      <div
        style={{
          marginTop: 20,
          borderLeft: `2px solid ${token.ui04}`,
          paddingLeft: 20,
          maxWidth: 1420,
        }}
      >
        <Body size={23} colour={token.text02}>
          {lift.wording.display}
        </Body>
        <div style={{ marginTop: 6 }}>
          <Mono size={17} colour={token.text03}>
            gate {lift.number.display}, fixed before the queue was built
          </Mono>
        </div>
      </div>
    </Reveal>

    <div style={{ display: "flex", gap: 70, marginTop: 62 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        <Reveal delay={22}>
          <Mono size={18} colour={token.text03}>
            conflicts found in the {lift.examined.display} examined, out of{" "}
            {lift.population.display} decisively labelled
          </Mono>
        </Reveal>
        <ConflictBar
          delay={30}
          label="random ordering, expected"
          count={lift.randomConflicts.display}
          value={lift.randomConflicts.value}
          colour={token.text03}
          dashed
        />
        <ConflictBar
          delay={44}
          label="first in, first out"
          count={lift.fifoConflicts.display}
          value={lift.fifoConflicts.value}
          colour={token.ui04}
        />
        <ConflictBar
          delay={58}
          label="the ranked queue"
          count={lift.queueConflicts.display}
          value={lift.queueConflicts.value}
          colour={token.interactive01}
        />
        <Reveal delay={80}>
          <div style={{ paddingLeft: 268 }}>
            <Mono size={17} colour={token.text03}>
              {lift.totalConflicts.display} exist in the whole population
            </Mono>
          </div>
        </Reveal>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Reveal delay={96}>
          <Mono size={18} colour={token.text03}>
            lift over random at the same budget, with its 95% interval
          </Mono>
        </Reveal>
        <LiftRail delay={104} />
      </div>
    </div>

    <Reveal delay={190}>
      <div
        style={{
          marginTop: 54,
          background: token.ui01,
          border: `1px solid ${token.borderSubtle}`,
          padding: 24,
          display: "flex",
          gap: 26,
          alignItems: "flex-start",
          maxWidth: 1520,
        }}
      >
        <div style={{ paddingTop: 8 }}>
          <VerdictMark verdict={lift.verdict.value as string} size={18} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", gap: 20, alignItems: "baseline" }}>
            <span
              style={{
                fontFamily: font.sans,
                fontWeight: 600,
                fontSize: 30,
                color: token.text01,
              }}
            >
              {lift.verdict.display.replace("_", " ")}
            </span>
            <Mono size={18} colour={token.text03}>
              {lift.direction.display.replace(/_/g, " ")}
            </Mono>
          </div>
          <Body size={23} colour={token.text02}>
            The point estimate clears the threshold. The interval does not, so this is
            recorded as a measurement that came back inconclusive rather than as a win.
            Grouped by orbital pass episode over {lift.bootstraps.display} resamples of{" "}
            {lift.groups.display} groups.
          </Body>
        </div>
      </div>
    </Reveal>
  </Frame>
);
