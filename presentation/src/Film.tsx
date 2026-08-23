import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { Colophon } from "./beats/Colophon";
import { Established } from "./beats/Established";
import { Gates } from "./beats/Gates";
import { Physics } from "./beats/Physics";
import { Problem } from "./beats/Problem";
import { Queue } from "./beats/Queue";
import { Result } from "./beats/Result";
import { Title } from "./beats/Title";
import { FPS, LEAD_IN_SECONDS, token } from "./theme";

/**
 * Eight cards, cut rather than crossfaded. A cut is what a console does when you
 * click through it, and it costs no frames to a transition nobody reads.
 *
 * The order is the argument, and "Established" is deliberately the last card with a
 * measurement on it. An earlier cut ran Title through Gates and stopped, so the film
 * closed on four verdicts that came back inconclusive and never said what had been
 * decided. Moving the decided results in front of the tally would have been the
 * flattering fix and the wrong one: the pre-registered gate is stated in full first,
 * with its interval, and then the three results that hold are stated after it. No
 * figure moved, no verdict softened, only the order.
 *
 * The frame counts are set by the narration rather than by reading speed.
 *
 * The first cut was silent and timed to be read, so each card held just long enough
 * for an eye to finish it. A spoken line is slower than a read one, and five of the
 * eight beats could not carry theirs. Every beat animates against `useCurrentFrame()`
 * with absolute keyframes rather than against its own duration, so lengthening a beat
 * adds hold time after its animation finishes instead of stretching it. That is the
 * cheap direction, and it is the reason the timings could move at all.
 *
 * `presentation/scripts/build-narration.ts` prints each beat's word count against its
 * budget, and `scripts/render_narration.py` fails on the measured duration rather than
 * the estimate. The film runs 142 seconds against the brief's 180 second ceiling, so
 * there is room left for a live console recording either side of it.
 */
export const BEATS = [
  { name: "Title", component: Title, durationInFrames: 150 },
  { name: "Problem", component: Problem, durationInFrames: 540 },
  { name: "Queue", component: Queue, durationInFrames: 660 },
  { name: "Physics", component: Physics, durationInFrames: 900 },
  { name: "Result", component: Result, durationInFrames: 690 },
  { name: "Gates", component: Gates, durationInFrames: 480 },
  { name: "Established", component: Established, durationInFrames: 660 },
  { name: "Colophon", component: Colophon, durationInFrames: 180 },
] as const;

export const FILM_FRAMES = BEATS.reduce(
  (total, beat) => total + beat.durationInFrames,
  0,
);

/**
 * Frames of silence before a beat's line starts, so a cut is never spoken across.
 *
 * Kept in step with `LEAD_IN_SECONDS` in `narration.ts`, which is what the caption
 * timings and the per-beat speech budget are both computed from. The audio for a beat
 * is nested inside that beat's own Sequence, so a line cannot outlive its card: if a
 * wav were ever longer than the beat holding it, Remotion would clip it and
 * `scripts/render_narration.py` would have already failed on the measurement.
 */
const LEAD_IN_FRAMES = Math.round(LEAD_IN_SECONDS * FPS);

export const Film: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: token.uiBackground,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      {BEATS.map((beat, index) => {
        const start = from;
        from += beat.durationInFrames;
        const Beat = beat.component;
        return (
          <Sequence
            key={beat.name}
            name={beat.name}
            from={start}
            durationInFrames={beat.durationInFrames}
          >
            <Beat />
            <Sequence from={LEAD_IN_FRAMES} name={`${beat.name} narration`}>
              <Audio
                src={staticFile(
                  `audio/narration-${index}-${beat.name.toLowerCase()}.wav`,
                )}
              />
            </Sequence>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
