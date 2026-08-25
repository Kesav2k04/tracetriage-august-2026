import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { coldOpen, colophon, physics } from "../data";
import { font, MARGIN, numeric, token } from "../theme";
import { Body, Eyebrow, Frame, Heading, Mono, Reveal, Rule } from "../ui";

/**
 * The film opens on one capture rather than on a title.
 *
 * Everything drawn here is the hero observation's own record, read from `physics`, which
 * is where the corridor card reads it too. The point of the shot is that none of it is
 * illustrative: a real volunteer station recorded a real pass, the network wrote two
 * words about it, and that is where the whole argument starts. Only one figure on this
 * card is new, and it is arithmetic on the record's own two timestamps: how long the
 * pass ran. It is read from `coldOpen`, which holds nothing else.
 *
 * The waterfall is shown raw. The corridor that explains it is four cards away, and
 * putting the overlay here would spend the reveal before the viewer knows what is odd
 * about the image.
 */

const Row: React.FC<{ label: string; value: string; delay: number }> = ({
  label,
  value,
  delay,
}) => (
  <Reveal delay={delay} rise={6}>
    <div style={{ display: "flex", gap: 20, alignItems: "baseline" }}>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 19,
          color: token.text03,
          width: 190,
          flex: "0 0 auto",
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 19,
          color: token.text02,
          ...numeric,
        }}
      >
        {value}
      </span>
    </div>
  </Reveal>
);

/**
 * The capture, drifting up across the card.
 *
 * Its own component, and not because it is reused. `test/claims.test.ts` scans each beat
 * for figures typed into the copy, and it finds the copy by collapsing every brace pair
 * as code. A component written with a statement body puts its whole return inside one
 * brace pair, so the scan sees no copy at all and passes by finding nothing. Keeping the
 * animation here and the words in an expression body below is what makes that scan able
 * to see this card.
 *
 * Time runs bottom to top in a waterfall, so drifting up is the direction the pass was
 * recorded in rather than an arbitrary choice of motion.
 */
const Capture: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, 420], [0, -46], {
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        position: "relative",
        width: 300,
        height: 700,
        overflow: "hidden",
        background: token.waterfallGround,
        border: `1px solid ${token.borderSubtle}`,
        flex: "0 0 auto",
      }}
    >
      <Img
        src={staticFile(`waterfalls/${physics.obsId.value}.webp`)}
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: "100%",
          transform: `translateY(${drift}px)`,
        }}
      />
    </div>
  );
};

export const Hello: React.FC = () => (
    <Frame eyebrow="One capture" sources={[physics.obsId, physics.status]}>
      <div style={{ display: "flex", gap: 68, marginTop: 8 }}>
        <Capture />

        <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
          <Reveal delay={4}>
            <Heading size={54}>A real pass, recorded by a volunteer.</Heading>
          </Reveal>

          <div style={{ marginTop: 30, display: "flex", flexDirection: "column", gap: 13 }}>
            <Row label="observation" value={physics.obsId.display} delay={16} />
            <Row label="ground station" value={physics.station.display} delay={22} />
            <Row label="satellite" value={`NORAD ${physics.norad.display}`} delay={28} />
            <Row label="receive frequency" value={`${physics.rxMhz.display} MHz`} delay={34} />
            <Row label="recorded" value={physics.start.display} delay={40} />
            <Row label="length of pass" value={`${coldOpen.passMinutes.display} minutes`} delay={46} />
          </div>

          <Reveal delay={186} rise={0} style={{ marginTop: 40 }}>
            <Rule delay={186} colour={token.ui02} />
            <div style={{ marginTop: 26 }}>
              <Eyebrow colour={token.text03}>
                what the network recorded about it
              </Eyebrow>
            </div>
            <div
              style={{
                marginTop: 16,
                fontFamily: font.mono,
                fontSize: 76,
                letterSpacing: -1,
                color: token.interactive01,
                ...numeric,
              }}
            >
              {physics.status.display}
            </div>
            <div style={{ marginTop: 20, maxWidth: 780 }}>
              <Body size={25} colour={token.text02}>
                That is the entire verdict. No frequency, no fit, no note. The capture
                was kept and never read again.
              </Body>
            </div>
          </Reveal>
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: MARGIN,
          right: MARGIN,
          bottom: 44,
        }}
      >
        <Reveal delay={54}>
          <Mono size={16} colour={token.text03}>
            {colophon.recordUrl.display}
          </Mono>
        </Reveal>
      </div>
    </Frame>
);
