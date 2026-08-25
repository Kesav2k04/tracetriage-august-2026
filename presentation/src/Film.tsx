import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile } from "remotion";
import { Bob } from "./beats/Bob";
import { Colophon } from "./beats/Colophon";
import { Established } from "./beats/Established";
import { Flow } from "./beats/Flow";
import { Gates } from "./beats/Gates";
import { Hello } from "./beats/Hello";
import { Live } from "./beats/Live";
import { Physics } from "./beats/Physics";
import { Problem } from "./beats/Problem";
import { Queue } from "./beats/Queue";
import { Result } from "./beats/Result";
import { Session } from "./beats/Session";
import { Thanks } from "./beats/Thanks";
import { Title } from "./beats/Title";
import { FPS, LEAD_IN_SECONDS, token } from "./theme";

/**
 * Eight cards, cut rather than crossfaded. A cut is what a console does when you
 * click through it, and it costs no frames to a transition nobody reads.
 *
 * The order is the argument. Physics runs early because the corridor is the one thing
 * on screen that cannot be mistaken for a chart, and the queue only means something
 * once a viewer has seen what it ranks on. The pre-registered gate is still stated in
 * full, with its interval, before the tally that reports it as not established, and
 * the three results that did come back decided are stated before it rather than used
 * to soften it. No figure moved and no verdict changed, only the order.
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
 * the estimate.
 *
 * The holds are set from the measured wav rather than chosen. An earlier cut carried
 * 31.6 seconds of silence across 142, because each card was given a round number of
 * seconds and the line inside it came up short. Every duration below is the beat's own
 * rendered speech plus the lead-in, the tail and about a second of air, rounded to the
 * next six frames, so a card holds for as long as it is being spoken over and no
 * longer. `scripts/render_narration.py --check` fails if a line ever outgrows its card.
 *
 * Three cards were added rather than the same argument being restated. "Live" is a
 * screen recording of the deployed console measuring an observation from the frozen
 * corpus, beside the figures this repository already held for it. "Session" is the
 * product being driven over MCP, refusal and all, read out of the recorded session
 * receipt. "Bob" is what IBM Bob built, read out of the same unit list the console
 * serves. None of the three is a claim the other seven cards were already making.
 */
export const BEATS = [
  { name: "Hello", component: Hello, durationInFrames: 462 },
  { name: "Title", component: Title, durationInFrames: 174 },
  { name: "Problem", component: Problem, durationInFrames: 294 },
  { name: "Physics", component: Physics, durationInFrames: 756 },
  { name: "Queue", component: Queue, durationInFrames: 336 },
  { name: "Live", component: Live, durationInFrames: 420 },
  { name: "Flow", component: Flow, durationInFrames: 498 },
  { name: "Session", component: Session, durationInFrames: 210 },
  { name: "Result", component: Result, durationInFrames: 582 },
  { name: "Gates", component: Gates, durationInFrames: 282 },
  { name: "Established", component: Established, durationInFrames: 438 },
  { name: "Bob", component: Bob, durationInFrames: 372 },
  { name: "Colophon", component: Colophon, durationInFrames: 210 },
  { name: "Thanks", component: Thanks, durationInFrames: 168 },
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
