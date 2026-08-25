import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { colophon, corpus, gates, provenanceLine } from "../data";
import { font, MARGIN, numeric, token } from "../theme";
import { Body, Eyebrow, Heading, Mono, Reveal, Rule } from "../ui";

/**
 * The card the film ends on.
 *
 * A thank-you is not decoration here. Somebody watched three minutes of somebody else's
 * measurements, and the last thing on screen should be an address they can go to rather
 * than a logo. So the card carries the two things a viewer can act on, the repository
 * and the console, and the one line that makes the rest checkable: every figure came
 * out of a receipt.
 *
 * The attribution rides on this card rather than on one of its own, because the film has
 * a three-minute cap and the licence obligation is satisfied by being legible and
 * present, not by having a slide to itself. The full audit for the exact waterfall the
 * film shows is on the attribution card before this one and in DATA_LICENSE.md.
 */

const Address: React.FC<{ label: string; value: string; delay: number }> = ({
  label,
  value,
  delay,
}) => (
  <Reveal delay={delay} rise={6}>
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Mono size={17} colour={token.text03}>
        {label}
      </Mono>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 30,
          color: token.text01,
          ...numeric,
        }}
      >
        {value}
      </span>
    </div>
  </Reveal>
);

/**
 * The console, drifting back in behind the sign-off. Its own component so that the card
 * carrying the words can be an expression body: `test/claims.test.ts` collapses brace
 * pairs to find a beat's copy, and a statement body would hide every word below from it.
 *
 * The film opened on this image and closes on it, because it is the thing a viewer is
 * being pointed at.
 */
const ConsoleWash: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 240], [1.02, 1.0], {
    extrapolateRight: "clamp",
  });
  const wash = interpolate(frame, [0, 40], [0, 0.34], {
    extrapolateRight: "clamp",
  });
  return (
    <>
      <Img
        src={staticFile("film/console.webp")}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${zoom})`,
          opacity: wash,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            `linear-gradient(180deg, ${token.uiBackground}e8 0%, ` +
            `${token.uiBackground}c0 50%, ${token.uiBackground}f4 100%)`,
        }}
      />
    </>
  );
};

export const Thanks: React.FC = () => (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: token.uiBackground,
        fontFamily: font.sans,
      }}
    >
      <ConsoleWash />

      <div
        style={{
          position: "absolute",
          left: MARGIN,
          right: MARGIN,
          top: 300,
          display: "flex",
          flexDirection: "column",
          gap: 26,
        }}
      >
        <Reveal delay={2}>
          <Eyebrow colour={token.interactive01}>Thank you for watching</Eyebrow>
        </Reveal>
        <Reveal delay={8}>
          <Heading size={92}>Nothing here asks to be believed.</Heading>
        </Reveal>
        <Reveal delay={16}>
          <div style={{ width: 700 }}>
            <Rule delay={16} colour={token.interactive01} thickness={2} />
          </div>
        </Reveal>
        <Reveal delay={22}>
          <div style={{ maxWidth: 1500 }}>
            <Body size={32} colour={token.text01}>
              Every figure in this film was read out of a receipt in the repository, and{" "}
              {gates.met.display} of {gates.total.display} gates are reported as met. The
              ones that are not are still on the page.
            </Body>
          </div>
        </Reveal>

        <div style={{ marginTop: 34, display: "flex", gap: 130 }}>
          <Address label="console" value="tracetriage.vercel.app" delay={32} />
          <Address
            label="repository"
            value="github.com/Kesav2k04/tracetriage-august-2026"
            delay={38}
          />
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: MARGIN,
          right: MARGIN,
          bottom: 96,
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
          bottom: 42,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 40,
        }}
      >
        <Reveal delay={50}>
          <Mono size={17} colour={token.text03}>
            {provenanceLine.attribution.display}
          </Mono>
        </Reveal>
        <Reveal delay={52}>
          <Mono size={17} colour={token.text03}>
            {corpus.licence.display} · {colophon.licenceUrl.display}
          </Mono>
        </Reveal>
      </div>
    </div>
);
