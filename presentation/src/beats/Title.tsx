import React from "react";
import { corpus, provenanceLine } from "../data";
import { font, MARGIN, token } from "../theme";
import { Body, Eyebrow, Heading, Mono, Reveal, Rule } from "../ui";

export const Title: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: token.uiBackground,
      fontFamily: font.sans,
    }}
  >
    <div
      style={{
        position: "absolute",
        left: MARGIN,
        top: 330,
        right: MARGIN,
        display: "flex",
        flexDirection: "column",
        gap: 26,
      }}
    >
      <Reveal delay={0}>
        <Eyebrow>Space exploration</Eyebrow>
      </Reveal>
      <Reveal delay={6}>
        <Heading size={104}>TraceTriage</Heading>
      </Reveal>
      <Reveal delay={14}>
        <div style={{ width: 620 }}>
          <Rule delay={14} colour={token.interactive01} thickness={2} />
        </div>
      </Reveal>
      <Reveal delay={20}>
        <Body size={32} width={1060}>
          A ranked review queue for satellite radio captures that volunteers recorded
          and nobody read.
        </Body>
      </Reveal>
      <Reveal delay={34}>
        <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
          <Mono size={20} colour={token.text03}>
            every number in this film is read from a receipt in the repository
          </Mono>
        </div>
      </Reveal>
    </div>

    <div
      style={{
        position: "absolute",
        left: MARGIN,
        right: MARGIN,
        bottom: 76,
      }}
    >
      <Reveal delay={46}>
        <Rule delay={46} colour={token.ui02} />
      </Reveal>
    </div>
    <div
      style={{
        position: "absolute",
        left: MARGIN,
        right: MARGIN,
        bottom: 40,
        display: "flex",
        gap: 28,
      }}
    >
      <Reveal delay={50}>
        <Mono size={16} colour={token.text03}>
          snapshot
        </Mono>
      </Reveal>
      <Reveal delay={52}>
        <Mono size={16} colour={token.text02}>
          {provenanceLine.snapshot.display}
        </Mono>
      </Reveal>
      <Reveal delay={54}>
        <Mono size={16} colour={token.text03}>
          {corpus.licence.display}
        </Mono>
      </Reveal>
    </div>
  </div>
);
