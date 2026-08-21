import React from "react";
import { ceiling, gates } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Frame, Heading, Mono, Reveal, VerdictMark } from "../ui";

const inkFor = (verdict: string): string => {
  if (verdict === "PASSED" || verdict === "PRE_PASSED") return token.text01;
  if (verdict === "NOT_ESTABLISHED") return token.text02;
  if (verdict === "FAILED") return token.verdictFailed;
  return token.text03;
};

const GateRow: React.FC<{ index: number; delay: number }> = ({ index, delay }) => {
  const row = gates.rows[index];
  const verdict = row.verdict.value as string;
  return (
    <Reveal delay={delay} rise={6}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 22,
          borderTop: `1px solid ${token.borderSubtle}`,
          paddingTop: 18,
          paddingBottom: 18,
        }}
      >
        <span
          style={{
            fontFamily: font.mono,
            fontSize: 22,
            color: token.text03,
            width: 40,
            ...numeric,
          }}
        >
          {row.number.display}
        </span>
        <span
          style={{
            fontFamily: font.sans,
            fontSize: 26,
            color: token.text01,
            flex: 1,
          }}
        >
          {row.title.display}
        </span>
        <Mono size={17} colour={token.text03}>
          {row.decidedIn.display}
        </Mono>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            width: 290,
            justifyContent: "flex-end",
          }}
        >
          <VerdictMark verdict={verdict} />
          <span
            style={{
              fontFamily: font.sans,
              fontWeight: 600,
              fontSize: 22,
              letterSpacing: 0.6,
              color: inkFor(verdict),
            }}
          >
            {row.verdict.display.replace(/_/g, " ")}
          </span>
        </div>
      </div>
    </Reveal>
  );
};

export const Gates: React.FC = () => (
  <Frame eyebrow="The gates" sources={[gates.met, gates.total, ceiling.lift]}>
    <Reveal delay={2}>
      <Heading>The kill gates, written down before measuring.</Heading>
    </Reveal>

    <Reveal delay={10}>
      <div style={{ marginTop: 16 }}>
        <Body width={1500}>
          Each one names a question that could have ended the project, and each is
          reported as it came back.
        </Body>
      </div>
    </Reveal>

    <div style={{ marginTop: 38 }}>
      {gates.rows.map((row, index) => (
        <GateRow key={row.number.display} index={index} delay={22 + index * 11} />
      ))}
      <div style={{ borderTop: `1px solid ${token.borderSubtle}` }} />
    </div>

    <div style={{ display: "flex", gap: 64, marginTop: 48, alignItems: "flex-start" }}>
      <Reveal delay={118}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
          <span
            style={{
              fontFamily: font.sans,
              fontWeight: 600,
              fontSize: 96,
              lineHeight: 1,
              color: token.text01,
              ...numeric,
            }}
          >
            {gates.met.display}
          </span>
          <span
            style={{
              fontFamily: font.sans,
              fontSize: 30,
              color: token.text02,
            }}
          >
            of {gates.total.display} met
          </span>
        </div>
      </Reveal>
      <Reveal delay={132}>
        <div style={{ maxWidth: 1080, display: "flex", flexDirection: "column", gap: 12 }}>
          <Body size={24}>{gates.note.display}</Body>
          <Body size={24} colour={token.text01}>
            The {gates.met.display} that were met are the feasibility checks
            answered before any pipeline code existed. Of the{" "}
            {gates.measured.display} that ask whether the idea works,{" "}
            {gates.measuredPassed.display} passed.
          </Body>
          {/* A tally with a zero in it and no scale beside it invites one reading,
              which is that the idea did not work. This is the quantity that decides
              how much room there was to work in, and it is a finding rather than an
              excuse: it was computed from the population and the budget, not from
              the result, and the console derives it on the evaluation page. */}
          <Body size={24} colour={token.text02}>
            What the measured gates were up against: the{" "}
            {ceiling.maxFindable.display} conflicts that exist at this budget cap
            every possible ordering, a perfect oracle included, at{" "}
            {ceiling.lift.display} against a bar of {ceiling.threshold.display}. The
            entire distance between the bar and perfection is{" "}
            {ceiling.headroom.display}.
          </Body>
        </div>
      </Reveal>
    </div>

    <Reveal delay={210}>
      <div style={{ marginTop: 40 }}>
        <Mono size={19} colour={token.interactive01}>
          the console prints this tally on its own front page
        </Mono>
      </div>
    </Reveal>
  </Frame>
);
