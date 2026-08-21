import React from "react";
import { colophon, physics } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Frame, Heading, Mono, Reveal } from "../ui";

const Line: React.FC<{ label: string; value: string; delay: number }> = ({
  label,
  value,
  delay,
}) => (
  <Reveal delay={delay} rise={5}>
    <div style={{ display: "flex", gap: 24, alignItems: "baseline" }}>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 17,
          color: token.text03,
          width: 230,
          flex: "0 0 auto",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 17,
          color: token.text02,
          wordBreak: "break-all",
          ...numeric,
        }}
      >
        {value}
      </span>
    </div>
  </Reveal>
);

/**
 * Showing one SatNOGS waterfall carries six obligations under DATA_LICENSE.md.
 * Every line here is the repository's own audit row for the exact file the physics
 * beat displayed, so this card cannot say something the audit does not.
 */
export const Colophon: React.FC = () => (
  <Frame eyebrow="Attribution" sources={[colophon.recordUrl]}>
    <Reveal delay={2}>
      <Heading size={44}>The waterfall in this film, and where it came from.</Heading>
    </Reveal>

    <div style={{ marginTop: 34, display: "flex", flexDirection: "column", gap: 14 }}>
      <Line label="observation" value={physics.obsId.display} delay={8} />
      <Line label="ground station" value={colophon.station.display} delay={12} />
      <Line label="record" value={colophon.recordUrl.display} delay={16} />
      <Line label="waterfall artifact" value={colophon.artifactUrl.display} delay={20} />
      <Line label="retrieved" value={colophon.retrievedAt.display} delay={24} />
      <Line label="sha256 of the bytes" value={colophon.sha256.display} delay={28} />
      <Line label="licence" value={colophon.licence.display} delay={32} />
      <Line label="licence url" value={colophon.licenceUrl.display} delay={36} />
      <Line label="modified" value={colophon.modification.display} delay={40} />
      <Line
        label="modified again here"
        value="scaled to the frame, corridor overlay drawn on top, encoded to H.264"
        delay={44}
      />
    </div>

    <Reveal delay={56}>
      <div
        style={{
          marginTop: 34,
          borderTop: `1px solid ${token.borderSubtle}`,
          paddingTop: 22,
          maxWidth: 1400,
        }}
      >
        <Body size={24} colour={token.text01}>
          Data from the SatNOGS Network, contributed by volunteer ground stations. This
          film contains one of their waterfalls, so the film is released under the same
          ShareAlike licence rather than under the repository's code licence.
        </Body>
        <div style={{ marginTop: 14 }}>
          <Mono size={17} colour={token.text03}>
            {colophon.obligationsSource.display}
          </Mono>
        </div>
      </div>
    </Reveal>
  </Frame>
);
