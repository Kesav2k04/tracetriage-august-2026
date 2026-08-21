import React from "react";
import { AbsoluteFill, Sequence } from "remotion";
import { Colophon } from "./beats/Colophon";
import { Established } from "./beats/Established";
import { Gates } from "./beats/Gates";
import { Physics } from "./beats/Physics";
import { Problem } from "./beats/Problem";
import { Queue } from "./beats/Queue";
import { Result } from "./beats/Result";
import { Title } from "./beats/Title";
import { token } from "./theme";

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
 */
export const BEATS = [
  { name: "Title", component: Title, durationInFrames: 150 },
  { name: "Problem", component: Problem, durationInFrames: 420 },
  { name: "Queue", component: Queue, durationInFrames: 600 },
  { name: "Physics", component: Physics, durationInFrames: 720 },
  { name: "Result", component: Result, durationInFrames: 570 },
  { name: "Gates", component: Gates, durationInFrames: 450 },
  { name: "Established", component: Established, durationInFrames: 450 },
  { name: "Colophon", component: Colophon, durationInFrames: 180 },
] as const;

export const FILM_FRAMES = BEATS.reduce(
  (total, beat) => total + beat.durationInFrames,
  0,
);

export const Film: React.FC = () => {
  let from = 0;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: token.uiBackground,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      {BEATS.map((beat) => {
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
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
