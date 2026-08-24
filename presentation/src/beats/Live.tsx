import React from "react";
import { OffthreadVideo, Sequence, staticFile, useCurrentFrame } from "remotion";
import { liveTake } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Eyebrow, Frame, Heading, Mono, Reveal, progress } from "../ui";

/**
 * The one card that is footage rather than a drawing.
 *
 * Everything else in this film is receipt data rendered by this project. This is the
 * deployed console at tracetriage.vercel.app, recorded in a single take while it measured
 * a real SatNOGS observation, and the numbers that come back are whatever the endpoint
 * returned. The id typed into it is deliberately one from the frozen corpus, so the two
 * columns on the right are answering the question a viewer should be asking by now: does
 * the path anyone can drive give the number this repository published months earlier.
 *
 * The rates the recording plays at are read from `artifacts/LIVE_TAKE.json` and printed on
 * screen, because a sped-up recording that does not say so is a claim about how long
 * something took. The wait for the endpoint is compressed, not cut: the take runs from the
 * id being typed to the result table without a jump.
 */

/**
 * When the recording starts inside the beat, and how long it is. Both are exported
 * because test/claims.test.ts holds them against `artifacts/LIVE_TAKE.json`: a video
 * that outlives its beat plays into the next card, and one the beat outlives leaves an
 * empty window on screen. Neither is visible in a passing render of the old length.
 */
export const VIDEO_AT = 24;
export const VIDEO_FRAMES = 391;
const TABLE_AT = VIDEO_AT + 96;

const WINDOW_W = 992;
const WINDOW_H = 558;
const CHROME_H = 34;

/** The recording, inside a window that reads as a browser rather than as a slide. */
const Take: React.FC = () => {
  const frame = useCurrentFrame();
  const up = progress(frame, VIDEO_AT - 14, 16);
  return (
    <div
      style={{
        width: WINDOW_W,
        border: `1px solid ${token.borderStrong}`,
        background: token.ui01,
        opacity: up,
        transform: `translateY(${((1 - up) * 10).toFixed(2)}px)`,
      }}
    >
      <div
        style={{
          height: CHROME_H,
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "0 14px",
          borderBottom: `1px solid ${token.borderSubtle}`,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 8,
            background: token.live01,
            display: "inline-block",
          }}
        />
        <Mono size={16} colour={token.text03}>
          tracetriage.vercel.app/live/
        </Mono>
      </div>
      {/* The box is reserved by this div rather than by the video, so the window does
          not collapse in the frames before the take starts. `layout="none"` keeps the
          Sequence out of the way: its default is an absolute fill over the whole frame. */}
      <div
        style={{
          position: "relative",
          width: WINDOW_W,
          height: WINDOW_H,
          background: token.uiBackground,
          overflow: "hidden",
        }}
      >
        <Sequence
          from={VIDEO_AT}
          durationInFrames={VIDEO_FRAMES}
          name="live take"
          layout="none"
        >
          <OffthreadVideo
            src={staticFile("film/live-take.mp4")}
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              display: "block",
            }}
          />
        </Sequence>
      </div>
    </div>
  );
};

const Row: React.FC<{
  label: string;
  held: string;
  now: string;
  delay: number;
}> = ({ label, held, now, delay }) => (
  <Reveal delay={delay} rise={6}>
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr auto auto",
        alignItems: "baseline",
        gap: 26,
        borderTop: `1px solid ${token.borderSubtle}`,
        paddingTop: 14,
        paddingBottom: 14,
      }}
    >
      <span style={{ fontFamily: font.sans, fontSize: 23, color: token.text02 }}>
        {label}
      </span>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 26,
          color: token.text02,
          minWidth: 150,
          textAlign: "right",
          ...numeric,
        }}
      >
        {held}
      </span>
      <span
        style={{
          fontFamily: font.mono,
          fontSize: 26,
          color: token.live01,
          minWidth: 150,
          textAlign: "right",
          ...numeric,
        }}
      >
        {now}
      </span>
    </div>
  </Reveal>
);

export const Live: React.FC = () => (
  <Frame
    eyebrow="one take, nothing staged"
    sources={[liveTake.offsetPpm, liveTake.heldOffsetPpm]}
  >
    <Heading size={58}>The deployed console, measuring while you watch</Heading>
    <Body width={1500} size={26}>
      The id typed on the left is an observation this project froze in August. The console
      downloads its waterfall, propagates the pass and refits the offset with no lookup, so
      the two columns on the right are the same quantity written twice.
    </Body>

    <div
      style={{
        display: "grid",
        gridTemplateColumns: `${WINDOW_W}px 1fr`,
        gap: 44,
        marginTop: 30,
        alignItems: "start",
      }}
    >
      <Take />

      <div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto auto",
            gap: 26,
            paddingBottom: 10,
          }}
        >
          <Eyebrow colour={token.text03}>observation</Eyebrow>
          <div style={{ minWidth: 150, textAlign: "right" }}>
            <Eyebrow colour={token.text03}>committed</Eyebrow>
          </div>
          <div style={{ minWidth: 150, textAlign: "right" }}>
            <Eyebrow colour={token.live01}>measured live</Eyebrow>
          </div>
        </div>

        <Row
          label="offset from the catalogue centre, ppm"
          held={liveTake.heldOffsetPpm.display}
          now={liveTake.offsetPpm.display}
          delay={TABLE_AT}
        />
        <Row
          label="corridor fit, sigma"
          held={liveTake.heldFitSigma.display}
          now={liveTake.fitSigma.display}
          delay={TABLE_AT + 12}
        />
        <Row
          label="rows where the trace was detected, as a fraction"
          held={liveTake.heldDetectFrac.display}
          now={liveTake.detectFrac.display}
          delay={TABLE_AT + 24}
        />

        <Reveal delay={TABLE_AT + 42} rise={6}>
          <div
            style={{
              marginTop: 26,
              paddingTop: 20,
              borderTop: `1px solid ${token.borderStrong}`,
            }}
          >
            <span style={{ fontFamily: font.sans, fontSize: 24, color: token.text01 }}>
              {liveTake.exact.display} of the quantities compared agree to the last digit.
              The {liveTake.differs.display} that do not are the mode score, which a
              different builder writes.
            </span>
            <div style={{ marginTop: 14 }}>
              <Mono size={18} colour={token.text03}>
                {liveTake.obsId.display} {liveTake.satellite.display} ·{" "}
                {liveTake.verdict.display} · {liveTake.nulls.display} permutations, p{" "}
                {liveTake.pValue.display}
              </Mono>
            </div>
            <div style={{ marginTop: 8 }}>
              <Mono size={18} colour={token.text03}>
                one take, played at {liveTake.rateFirst.display}x then{" "}
                {liveTake.rateSecond.display}x
              </Mono>
            </div>
          </div>
        </Reveal>
      </div>
    </div>
  </Frame>
);
