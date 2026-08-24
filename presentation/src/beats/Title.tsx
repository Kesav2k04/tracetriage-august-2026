import React from "react";
import { Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { corpus, provenanceLine } from "../data";
import { font, MARGIN, token } from "../theme";
import { Body, Eyebrow, Heading, Mono, Reveal, Rule } from "../ui";

/**
 * The opening shot is the deployed console, photographed rather than drawn.
 *
 * `apps/web/public/film/console.webp` is a 3840x2160 capture of
 * https://tracetriage.vercel.app taken with the site answering a real request, so the
 * first thing a viewer sees is the thing that exists. It is held under a scrim heavy
 * enough for the title to carry the frame and light enough that the queue, the
 * intervals and the corridor behind it are all legible, and it drifts about one and a
 * half percent over the card, which reads as depth rather than as motion.
 *
 * The image is a derived work of a ShareAlike capture and is declared as one:
 * `scripts/audit_release.py` names it, resolves it to observation 14740031, and
 * publishes its licence row like every other redistributed file here.
 */

const ConsoleBackdrop: React.FC = () => {
  const frame = useCurrentFrame();
  const zoom = interpolate(frame, [0, 200], [1.0, 1.015], {
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
          opacity: 0.5,
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            `linear-gradient(90deg, ${token.uiBackground} 0%, ` +
            `${token.uiBackground}f0 34%, ${token.uiBackground}40 100%)`,
        }}
      />
    </>
  );
};

export const Title: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      background: token.uiBackground,
      fontFamily: font.sans,
    }}
  >
    <ConsoleBackdrop />
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
