import React from "react";
import { useCurrentFrame } from "remotion";
import { reviewQueue } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Frame, Heading, Mono, progress, Reveal } from "../ui";

const BAR = 3;
const BAR_GAP = 1;
const CHART_HEIGHT = 210;

const bars = reviewQueue.bars;
const topScore = Math.max(...bars.map((b) => b.score));

/**
 * One bar per ranked observation, height by review value, in rank order. The dip at
 * the budget line is real: four observations that scored their way in were displaced
 * by the cap on how much of one budget a single ground station may take.
 */
const RankedBars: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const budgetX = bars.filter((b) => b.inBudget).length * (BAR + BAR_GAP);
  const width = bars.length * (BAR + BAR_GAP);
  const cut = progress(frame, delay + 40, 20);
  return (
    <svg width={width} height={CHART_HEIGHT + 34} style={{ display: "block" }}>
      {bars.map((bar, i) => {
        const grow = progress(frame, delay + i * 0.14, 10);
        const height = (bar.score / topScore) * CHART_HEIGHT * grow;
        const dim = bar.inBudget ? 1 : 1 - 0.45 * cut;
        const fill = bar.displaced
          ? token.support03
          : bar.inBudget
            ? token.interactive01
            : token.ui04;
        return (
          <rect
            key={bar.rank}
            x={i * (BAR + BAR_GAP)}
            y={CHART_HEIGHT - height}
            width={BAR}
            height={height}
            fill={fill}
            opacity={dim}
          />
        );
      })}
      <rect
        x={budgetX}
        y={0}
        width={1}
        height={CHART_HEIGHT + 12}
        fill={token.text02}
        opacity={cut}
      />
    </svg>
  );
};

const Criterion: React.FC<{
  index: number;
  delay: number;
}> = ({ index, delay }) => {
  const criterion = reviewQueue.criteria[index];
  const inert = criterion.inert.value === true;
  return (
    <Reveal delay={delay}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 16,
          borderTop: `1px solid ${token.borderSubtle}`,
          paddingTop: 12,
          paddingBottom: 12,
        }}
      >
        <span
          style={{
            fontFamily: font.sans,
            fontWeight: 600,
            fontSize: 34,
            width: 64,
            textAlign: "right",
            color: inert ? token.text03 : token.text01,
            ...numeric,
          }}
        >
          {criterion.firedInBudget.display}
        </span>
        <span
          style={{
            fontFamily: font.sans,
            fontSize: 22,
            color: token.text02,
            flex: 1,
          }}
        >
          {criterion.label}
        </span>
        <Mono size={17} colour={inert ? token.support03 : token.text03}>
          {inert ? "never fires on this corpus" : criterion.code.toLowerCase()}
        </Mono>
      </div>
    </Reveal>
  );
};

export const Queue: React.FC = () => (
  <Frame
    eyebrow="The product"
    sources={[reviewQueue.length, reviewQueue.budget]}
  >
    <Reveal delay={2}>
      <Heading>A queue ordered by what a reviewer would learn.</Heading>
    </Reveal>

    <div style={{ display: "flex", gap: 64, marginTop: 26 }}>
      <Reveal delay={10}>
        <Body width={880}>
          Every observation in the held-out set is scored on how much opening it would
          teach, then ranked. A volunteer does not have an evening for all of them, so
          the queue also carries the budget it was measured against.
        </Body>
      </Reveal>
      <Reveal delay={16}>
        <div style={{ display: "flex", gap: 56 }}>
          <div>
            <div
              style={{
                fontFamily: font.sans,
                fontWeight: 600,
                fontSize: 64,
                color: token.text01,
                ...numeric,
              }}
            >
              {reviewQueue.length.display}
            </div>
            <Mono size={18} colour={token.text02}>
              ranked
            </Mono>
          </div>
          <div>
            <div
              style={{
                fontFamily: font.sans,
                fontWeight: 600,
                fontSize: 64,
                color: token.interactive01,
                ...numeric,
              }}
            >
              {reviewQueue.budget.display}
            </div>
            <Mono size={18} colour={token.text02}>
              the budget
            </Mono>
          </div>
        </div>
      </Reveal>
    </div>

    <div style={{ marginTop: 38 }}>
      <RankedBars delay={26} />
    </div>

    <Reveal delay={92}>
      <div style={{ display: "flex", gap: 34, marginTop: 2 }}>
        <Mono size={18} colour={token.text02}>
          {reviewQueue.budgetRationale.display}
        </Mono>
        <Mono size={18} colour={token.support03}>
          {reviewQueue.stationCapDisplaced.display} displaced by the per station cap
        </Mono>
      </div>
    </Reveal>

    <div style={{ marginTop: 40 }}>
      <Reveal delay={110}>
        <Mono size={18} colour={token.text03}>
          bar height is review value from zero. what the top of the queue turned out
          to be carrying:
        </Mono>
      </Reveal>
      <div style={{ marginTop: 10 }}>
        <Criterion index={1} delay={120} />
        <Criterion index={0} delay={132} />
        <Criterion index={2} delay={144} />
      </div>
    </div>
  </Frame>
);
