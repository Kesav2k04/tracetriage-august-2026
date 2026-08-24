import React from "react";
import { useCurrentFrame } from "remotion";
import { agentSession } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Eyebrow, Frame, Heading, Mono, Plate, Reveal } from "../ui";

/**
 * The card that shows the product being driven rather than described.
 *
 * Every string here is a field of `artifacts/OPERATOR_SESSION.json`, which is the
 * twelve steps of `docs/BOB_DEMO.md` run over stdio against both MCP servers and
 * recorded call by call. The two sentences below are the two the checker was actually
 * given: one carrying a downlink frequency the observation does not have, one carrying
 * only figures its own evidence packet prints. So the refusal on screen is a refusal
 * that happened, and a reader can open the receipt and find the same two verdicts.
 *
 * The typing effect is the one liberty. The characters arrive over time because a
 * sentence that appears whole gives the eye nothing to follow, and the frame it
 * finishes on is fixed rather than derived from the beat's duration, so lengthening
 * this card adds hold rather than slowing the type.
 */

const TYPE_START = 96;
const TYPE_FRAMES = 54;
const VERDICT_AT = TYPE_START + TYPE_FRAMES + 14;

const GROUNDED_START = 264;
const GROUNDED_FRAMES = 60;
const GROUNDED_VERDICT_AT = GROUNDED_START + GROUNDED_FRAMES + 14;

/** Characters revealed so far, floored at nothing and capped at the whole string. */
const typed = (text: string, frame: number, start: number, over: number): string => {
  if (frame <= start) return "";
  const share = Math.min(1, (frame - start) / over);
  return text.slice(0, Math.round(share * text.length));
};

const Caret: React.FC<{ on: boolean }> = ({ on }) =>
  on ? (
    <span
      style={{
        display: "inline-block",
        width: 12,
        height: 26,
        marginLeft: 4,
        transform: "translateY(3px)",
        background: token.live01,
      }}
    />
  ) : null;

const Exchange: React.FC<{
  tool: string;
  text: string;
  verdict: string;
  code?: string;
  start: number;
  over: number;
  verdictAt: number;
}> = ({ tool, text, verdict, code, start, over, verdictAt }) => {
  const frame = useCurrentFrame();
  const shown = typed(text, frame, start, over);
  const settled = frame >= verdictAt;
  const refused = verdict === "REFUSED";
  return (
    <Plate style={{ padding: 30 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
        <Mono size={19} colour={token.live01}>
          {tool}
        </Mono>
        <Mono size={17} colour={token.text03}>
          tools/call
        </Mono>
      </div>
      <div
        style={{
          fontFamily: font.mono,
          fontSize: 30,
          lineHeight: 1.5,
          color: token.text01,
          marginTop: 18,
          minHeight: 46,
          ...numeric,
        }}
      >
        {shown}
        <Caret on={frame > start && frame < start + over} />
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 18,
          marginTop: 22,
          opacity: settled ? 1 : 0,
        }}
      >
        <span
          style={{
            fontFamily: font.sans,
            fontWeight: 600,
            fontSize: 26,
            letterSpacing: 1.2,
            padding: "6px 16px",
            color: refused ? token.uiBackground : token.text01,
            background: refused ? token.support01 : "transparent",
            border: refused ? "none" : `1px solid ${token.borderStrong}`,
          }}
        >
          {verdict}
        </span>
        {code ? (
          <Mono size={22} colour={token.support03}>
            {code}
          </Mono>
        ) : null}
      </div>
    </Plate>
  );
};

/*
 * Expression-bodied on purpose. test/claims.test.ts scans a beat for figures typed by
 * hand, and it does that by collapsing every brace pair to a placeholder. A statement
 * body is one brace pair around the whole component, so it collapses the copy too and
 * the scan passes over an empty string. The frame this used to read is read inside
 * Exchange, which is the only thing that wanted it.
 */
export const Session: React.FC = () => (
  <Frame
    eyebrow="Driven, not described"
    sources={[agentSession.stepsMet, agentSession.refusedVerdict]}
  >
    <Heading size={62}>An agent can run this, and be refused</Heading>
    <Body width={1180} size={27}>
      {agentSession.evidenceTools.display} read-only tools over the committed
      receipts, {agentSession.liveTools.display} more that measure a pass recorded
      today. The same grounding rule that decides whether this project publishes its
      own sentence decides whether it accepts yours.
    </Body>

    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 26,
        marginTop: 34,
      }}
    >
      <Exchange
        tool="check_claim"
        text={agentSession.refusedText.display}
        verdict={agentSession.refusedVerdict.display}
        code={agentSession.refusedCode.display}
        start={TYPE_START}
        over={TYPE_FRAMES}
        verdictAt={VERDICT_AT}
      />
      <Exchange
        tool="check_claim"
        text={agentSession.groundedText.display}
        verdict={agentSession.groundedVerdict.display}
        start={GROUNDED_START}
        over={GROUNDED_FRAMES}
        verdictAt={GROUNDED_VERDICT_AT}
      />
    </div>

    <Reveal delay={GROUNDED_VERDICT_AT + 18} rise={8}>
      <div style={{ marginTop: 32 }}>
        <Eyebrow colour={token.text03}>
          the live server, which measures rather than reads
        </Eyebrow>
        <div style={{ marginTop: 12 }}>
          <Mono size={25} colour={token.live01}>
            {agentSession.liveToolNames.display}
          </Mono>
        </div>
      </div>
    </Reveal>

    <Reveal delay={GROUNDED_VERDICT_AT + 34} rise={8}>
      <div
        style={{
          marginTop: 30,
          paddingTop: 22,
          borderTop: `1px solid ${token.borderSubtle}`,
          display: "flex",
          alignItems: "baseline",
          gap: 16,
        }}
      >
        <Eyebrow colour={token.text03}>recorded session</Eyebrow>
        <span
          style={{
            fontFamily: font.sans,
            fontSize: 28,
            color: token.text01,
            ...numeric,
          }}
        >
          {agentSession.stepsMet.display} of {agentSession.stepsRun.display} steps
          came back with what the demo says they will
        </span>
      </div>
    </Reveal>
  </Frame>
);
