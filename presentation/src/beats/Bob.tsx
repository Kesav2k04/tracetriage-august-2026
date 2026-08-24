import React from "react";
import { bobUnits } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Frame, Heading, Mono, Reveal } from "../ui";

/**
 * What IBM Bob built, read out of the same list the console serves.
 *
 * `apps/web/public/data/bob.json` is generated from `docs/BOB_BUILD_LOG.md` by
 * `scripts/export_bob_units.py`, so the rows here cannot drift from the log the way a
 * typed list would. The card shows the unit id and what it produced. It does not show
 * which workspace ran it, because that is a fact about the build's logistics rather
 * than about what the unit measured, and the published list no longer carries it.
 *
 * The rows arrive two frames apart rather than together: ten items appearing at once
 * read as a wall, and the stagger is what makes the count legible without a number
 * having to announce it.
 */

const Row: React.FC<{ index: number; delay: number }> = ({ index, delay }) => {
  const row = bobUnits.rows[index];
  return (
    <Reveal delay={delay} rise={5}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 20,
          borderTop: `1px solid ${token.borderSubtle}`,
          paddingTop: 11,
          paddingBottom: 11,
        }}
      >
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 21,
            color: token.interactive01,
            width: 92,
            ...numeric,
          }}
        >
          {row.unit.display}
        </span>
        <span
          style={{
            fontFamily: font.sans,
            fontSize: 26,
            color: token.text01,
            flex: 1,
          }}
        >
          {row.subject.display}
        </span>
        <Mono size={19} colour={token.text03}>
          {row.files.display} files
        </Mono>
      </div>
    </Reveal>
  );
};

export const Bob: React.FC = () => (
  <Frame eyebrow="Built with IBM Bob" sources={[bobUnits.count]}>
    <Heading size={62}>Every measurement stands on these units</Heading>
    <Body width={1240} size={27}>
      The snapshot, the parser, the physics, the splits and the queue were built inside
      IBM Bob, each with the files it changed, the commands that ran and what failed
      before it was accepted. Remove them and what is left is a console with nothing
      measured to show in it.
    </Body>
    <div style={{ marginTop: 30 }}>
      {bobUnits.rows.map((_, index) => (
        <Row key={index} index={index} delay={26 + index * 9} />
      ))}
    </div>
  </Frame>
);
