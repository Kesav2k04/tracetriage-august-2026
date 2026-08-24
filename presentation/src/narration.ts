/**
 * What the film says out loud, and the receipt key every spoken figure came from.
 *
 * The film was built to be read with the sound off, because it was built to be
 * presented live with a person talking over it. The submission is watched by a judge
 * with nobody in the room, so it needs a track. That changes one thing and it is the
 * thing this file exists to protect: a spoken number is a published number, and it
 * has to be held to the same rule as a drawn one.
 *
 * So narration is not typed. Each line is a template over the same `Claim` objects
 * `data.ts` already resolved out of the receipts, and the spoken form of a figure is
 * a function of the claim's value rather than a second string somebody kept in sync.
 * `say()` is that function. A renamed receipt key breaks the render, the caption and
 * the audio together, which is the same failure mode `claim.ts` was written for.
 *
 * `test/narration.test.ts` re-reads every claim named here, re-derives every spoken
 * figure, and fails if a word in the track is a number no receipt holds. It also
 * checks each beat's rendered audio against the beat's own frame count, because a
 * line that overruns its card is a line the viewer hears over the next card.
 */

import { Claim } from "./claim";
import {
  agentSession,
  bobUnits,
  corpus,
  established,
  gates,
  lift,
  physics,
  reviewQueue,
} from "./data";
import { BEATS } from "./Film";
import { FPS, LEAD_IN_SECONDS, TAIL_SECONDS } from "./theme";

// ---------------------------------------------------------------------------
// Turning a published figure into something a speech model reads correctly.
//
// Three of these were found by rendering the audio and transcribing it back, not by
// reading the model's documentation:
//
//   "2,727"    read as "two, seven twenty seven"   a different number
//   "436.400"  read as two numbers                  the padding causes it
//   "+13,985"  read with the sign dropped           silent plus
//
// So a grouped integer is spelled into words, a padded decimal is trimmed, and a
// sign is spoken. All three are done here as functions of the figure rather than in
// the script, so no line carries a hand-typed spelling of a number a receipt owns.
// "1.58" and every integer under a thousand read correctly and pass through.
// ---------------------------------------------------------------------------

/** Strip zeros that only exist to pad a decimal: `436.400` becomes `436.4`. */
const trimPaddedDecimal = (text: string): string =>
  text.includes(".") ? text.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") : text;

/** Speak a leading sign, which the model otherwise drops. */
const speakSign = (text: string): string =>
  text.replace(/^\+/, "plus ").replace(/^-/, "minus ");

const ONES = [
  "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
  "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
  "seventeen", "eighteen", "nineteen",
];
const TENS = [
  "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
];

/** Spell a non-negative integer below one million. */
const spellBelowThousand = (n: number): string => {
  if (n < 20) return ONES[n];
  if (n < 100) {
    const rest = n % 10;
    return rest === 0 ? TENS[Math.floor(n / 10)] : `${TENS[Math.floor(n / 10)]} ${ONES[rest]}`;
  }
  const rest = n % 100;
  const head = `${ONES[Math.floor(n / 100)]} hundred`;
  return rest === 0 ? head : `${head} and ${spellBelowThousand(rest)}`;
};

export const spellInteger = (n: number): string => {
  if (!Number.isInteger(n) || n < 0 || n >= 1_000_000) {
    throw new Error(`spellInteger cannot spell ${n}`);
  }
  if (n < 1000) return spellBelowThousand(n);
  const thousands = Math.floor(n / 1000);
  const rest = n % 1000;
  const head = `${spellBelowThousand(thousands)} thousand`;
  if (rest === 0) return head;
  return rest < 100 ? `${head} and ${spellBelowThousand(rest)}` : `${head} ${spellBelowThousand(rest)}`;
};

/**
 * The spoken form of a claim, derived from the claim rather than written beside it.
 *
 * Derived from `display` and not from `value`, which is deliberate and was a bug
 * first. Most numeric claims here hold a float that the formatter rounds for the
 * screen: `corridorSpanHz` is 17289.651679120747 and the card says 17,290, and
 * `shiftPx` is -113 while the card says 113 because its formatter takes the size of
 * the shift and the direction is drawn rather than printed. Speaking the raw value
 * would have the track disagree with the card in both cases. The display is already
 * a pure function of the value, so speaking the display keeps one chain from the
 * receipt to the screen to the sound instead of forking it in two.
 *
 * Integers of four digits or more are spelled into words. Kokoro reads a grouped
 * display inconsistently: `2,727` came back as "two, seven twenty seven", which is a
 * different number rather than an odd reading, and the transcription check caught it.
 * Smaller integers and decimals read correctly as digits and are left alone, because
 * "one point five eight" spelled out reads worse than it sounds.
 */
export const say = (claim: Claim<unknown>): string => {
  const display = trimPaddedDecimal(claim.display);
  const sign = display.startsWith("+") ? "plus " : display.startsWith("-") ? "minus " : "";
  const bare = display.replace(/^[+-]/, "");
  if (/^\d{1,3}(,\d{3})+$/.test(bare)) {
    return `${sign}${spellInteger(Number(bare.replace(/,/g, "")))}`;
  }
  return `${sign}${bare}`;
};

/** A line of narration, and the claims it is allowed to be checked against. */
export type Line = {
  readonly text: string;
  readonly claims: readonly Claim<unknown>[];
};

/** Build a line, recording which claims produced the figures inside it. */
const line = (
  parts: readonly (string | Claim<unknown>)[],
): Line => {
  const claims: Claim<unknown>[] = [];
  const text = parts
    .map((part) => {
      if (typeof part === "string") return part;
      claims.push(part);
      return say(part);
    })
    .join("");
  return { text: text.replace(/\s+/g, " ").trim(), claims };
};

// ---------------------------------------------------------------------------
// The script, one entry per beat, in the order the beats run.
//
// The narration says what the card cannot: why the number is the number. It does
// not read the screen out, because a viewer who can see "1.58" does not need to be
// told the digits, they need to be told that the interval is what decides it.
//
// Beat order carries the same argument the cards do. The pre-registered gate is
// spoken in full, with its interval, before the three results that came back
// decided. Saying the wins first would be the flattering edit and the wrong one.
// ---------------------------------------------------------------------------

export const NARRATION: Readonly<Record<string, Line>> = {
  Title: line([
    "Of everything a ground station recorded last night, what should a person open ",
    "first?",
  ]),

  Problem: line([
    "Volunteers point radios at satellites and judge what came back by eye. This ",
    "frozen snapshot holds ",
    corpus.observations,
    " captures. Only ",
    corpus.decisive,
    " carry a decisive verdict. The rest were recorded, and nobody read them.",
  ]),

  Physics: line([
    "From this pass's own orbital elements, propagated with ",
    "S G P 4, the expected Doppler curve spans ",
    physics.corridorSpanHz,
    " hertz. Slide that curve ",
    physics.shiftPx,
    " pixels and it lands on the trace. The gap is the measurement. ",
    physics.offsetHz,
    " hertz, ",
    physics.offsetPpm,
    " parts per million. This station had already taken the Doppler out, and ",
    "nothing in the observation record says so.",
  ]),

  Queue: line([
    "So the queue ranks ",
    reviewQueue.length,
    " observations by what a reviewer would learn, and spends a fixed budget of ",
    reviewQueue.budget,
    " on the top of it. Not the loudest signals. The ones where the evidence ",
    "disagrees with itself: ",
    reviewQueue.criteria[1].firedInBudget,
    " stale catalogue frequencies, and ",
    reviewQueue.criteria[0].firedInBudget,
    " where the model and the network label do not match.",
  ]),

  Session: line([
    "Any agent can drive this over the Model Context Protocol. ",
    agentSession.evidenceTools,
    " read-only tools over the committed receipts, ",
    agentSession.liveTools,
    " more that measure a pass recorded today. Write a downlink frequency this ",
    "observation does not have and the checker refuses it, naming the reason. Write ",
    "only what its own packet prints and it passes. The recorded session ran ",
    agentSession.stepsRun,
    " steps and ",
    agentSession.stepsMet,
    " came back as documented.",
  ]),

  Established: line([
    "Three results came back decided. Read-only evidence tools take a local Granite ",
    "model from ",
    established.withoutTools,
    " of ",
    established.trials,
    " right to ",
    established.withTools,
    " of ",
    established.trials,
    ". The grounding checker caught ",
    established.adversarialCaught,
    " of ",
    established.adversarialChecks,
    " planted falsehoods, and refused ",
    established.controlRefused,
    " of ",
    established.controlChecks,
    " clean drafts. On stations the queue never saw, lift is ",
    established.coldLift,
    ", and that one clears.",
  ]),

  Result: line([
    "The gate written down in advance asked the queue to find one and a half times ",
    "as many conflicts as random ordering at the same budget. It found ",
    lift.queueConflicts,
    " where random expects ",
    lift.randomConflicts,
    ". That is a lift of ",
    lift.point,
    ". The interval runs ",
    lift.ciLow,
    " to ",
    lift.ciHigh,
    ", so it straddles the bar, and this is published as not established.",
  ]),

  Gates: line([
    "Six gates, with their thresholds, written down before anything was measured. ",
    gates.met,
    " of ",
    gates.total,
    " were met. A point estimate above the bar whose interval crosses it counts as ",
    "a failure here, which is stricter than the brief asked for. Nothing was moved ",
    "to make a verdict look better.",
  ]),

  Bob: line([
    "IBM Bob built the load-bearing pipeline. The data contracts, the immutable ",
    "snapshot, the waterfall parser, the physics corridor, the label provenance, the ",
    "baselines, the grouped splits and the queue: ",
    bobUnits.count,
    " dated units, each with the files it changed and what failed first. Every ",
    "measurement here is computed on what those units produced.",
  ]),

  Colophon: line([
    "Every figure you heard was read out of a receipt. The waterfall is a public ",
    "SatNOGS capture, cited and licensed.",
  ]),
};

/** Beat name, its frame budget, and the line spoken over it. */
export type NarratedBeat = {
  readonly name: string;
  readonly durationInFrames: number;
  readonly seconds: number;
  readonly line: Line;
};

/**
 * The script in beat order, with each beat's own frame count attached.
 *
 * Derived from `BEATS` rather than listed again, so a beat added to the film with no
 * line written for it fails here instead of rendering as silence.
 */
export const NARRATED: readonly NarratedBeat[] = BEATS.map((beat) => {
  const spoken = NARRATION[beat.name];
  if (spoken === undefined) {
    throw new Error(`beat "${beat.name}" has no narration line`);
  }
  return {
    name: beat.name,
    durationInFrames: beat.durationInFrames,
    seconds: beat.durationInFrames / FPS,
    line: spoken,
  };
});

/**
 * Room left for speech inside a beat, in seconds.
 *
 * A card cuts on its last frame, so audio is held off the cut at both ends: a beat
 * of a given length cannot carry a line that runs its full duration without the tail
 * landing over the next card. The two constants live in `theme.ts` beside FPS, and
 * are re-exported here because the caption writer reads them from the script.
 */
export { LEAD_IN_SECONDS, TAIL_SECONDS };

export const speechBudgetSeconds = (beat: NarratedBeat): number =>
  beat.seconds - LEAD_IN_SECONDS - TAIL_SECONDS;
