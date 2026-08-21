import React from "react";
import { useCurrentFrame } from "remotion";
import { corpus } from "../data";
import { token } from "../theme";
import { Body, Frame, Heading, Mono, progress, Reveal, Stat } from "../ui";

const COLUMNS = 124;
const CELL = 10;
const GAP = 3;
const STEP = CELL + GAP;

/**
 * One cell per stored observation, lit where a human left a decisive verdict.
 * The order is the snapshot's own fetch order, so the scatter is the corpus's.
 */
const VerdictGrid: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const mask = corpus.verdictMask;
  const rows = Math.ceil(mask.length / COLUMNS);
  return (
    <svg
      width={COLUMNS * STEP - GAP}
      height={rows * STEP - GAP}
      style={{ display: "block" }}
    >
      {mask.map((decisive, i) => {
        const column = i % COLUMNS;
        const row = Math.floor(i / COLUMNS);
        const appear = progress(frame, delay + row * 1.1, 10);
        const lit = progress(frame, delay + 46 + column * 0.32, 12);
        return (
          <rect
            key={i}
            x={column * STEP}
            y={row * STEP}
            width={CELL}
            height={CELL}
            fill={decisive ? token.text01 : token.ui02}
            opacity={decisive ? appear * (0.22 + 0.78 * lit) : appear * 0.9}
          />
        );
      })}
    </svg>
  );
};

export const Problem: React.FC = () => (
  <Frame
    eyebrow="The problem, in counts"
    sources={[corpus.observations, corpus.decisive]}
  >
    <Reveal delay={2}>
      <Heading>More captures than verdicts.</Heading>
    </Reveal>

    <Reveal delay={10}>
      <div style={{ marginTop: 20 }}>
        <Body width={1500}>
          Volunteer ground stations on the SatNOGS network record every pass they can
          see. Reviewing one means opening it and looking. This snapshot was taken
          backwards from a fixed date and stops there.
        </Body>
      </div>
    </Reveal>

    <div style={{ display: "flex", gap: 96, marginTop: 44 }}>
      <Reveal delay={26}>
        <Stat
          size={76}
          figure={corpus.observations.display}
          caption="observations stored in the snapshot"
        />
      </Reveal>
      <Reveal delay={34}>
        <Stat
          size={76}
          figure={corpus.waterfalls.display}
          caption="of them arrived with a waterfall image"
        />
      </Reveal>
      <Reveal delay={42}>
        <Stat
          size={76}
          figure={corpus.decisive.display}
          caption="carry a decisive human verdict"
          colour={token.text01}
        />
      </Reveal>
      <Reveal delay={50}>
        <Stat
          size={76}
          figure={corpus.noVerdict.display}
          caption="carry none at all"
          colour={token.interactive01}
        />
      </Reveal>
    </div>

    <div style={{ marginTop: 52 }}>
      <VerdictGrid delay={64} />
    </div>

    <Reveal delay={150}>
      <div style={{ marginTop: 26, display: "flex", gap: 18, alignItems: "baseline" }}>
        <Mono size={18} colour={token.text02}>
          one cell per observation, in the order the snapshot fetched them
        </Mono>
        <Mono size={18} colour={token.text03}>
          lit where a verdict exists
        </Mono>
      </div>
    </Reveal>
  </Frame>
);
