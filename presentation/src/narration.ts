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
  bobUnits,
  coldOpen,
  corpus,
  established,
  flow,
  gates,
  lift,
  liveTake,
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
 * Spell a decimal whose fraction starts with a zero, digit by digit after the point.
 *
 * `32.05` was transcribed as `32.5`. The zero after the point carries no stress and a
 * reader drops it, which turns a figure into a different figure ten times its size in
 * the fraction. Reading the fraction as separate digits puts a word on the zero, and
 * "thirty two point zero five" came back as `32.05`. Only decimals with that leading
 * zero are spelled: `2.25` and `12.6` have a stressed first fraction digit and read
 * correctly as they are, and spelling them would sound like a phone number.
 */
export const spellLeadingZeroDecimal = (whole: number, fraction: string): string =>
  `${spellInteger(whole)} point ${[...fraction].map((d) => ONES[Number(d)]).join(" ")}`;

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
 * Integers of three digits or more are spelled into words. A grouped display is read
 * inconsistently: `2,727` came back as "two, seven twenty seven", which is a different
 * number rather than an odd reading. Three digits fail a second way, because that is
 * where a reader starts choosing between "one hundred and thirteen" and "one thirteen":
 * `113` was transcribed as `1130`. Spelling removes the choice. Two digits and below
 * have no such fork and are left alone, as are decimals, because "one point five eight"
 * spelled out reads worse than it sounds.
 */
export const say = (claim: Claim<unknown>): string => {
  // A verdict or violation code is stored the way the receipt stores it, in screaming
  // snake case, and read aloud that way it comes back as something else entirely: the
  // transcription check caught "UNGROUNDED_NUMBER" being spoken as "Who grew Undead
  // Number". Speaking the words the code is made of is a function of the code rather
  // than a second spelling kept beside it, and `canonical()` reduces the code and the
  // spoken form to the same string, so the check still compares against the receipt.
  if (/^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/.test(claim.display)) {
    return claim.display.toLowerCase().replace(/_/g, " ");
  }
  const display = trimPaddedDecimal(claim.display);
  const sign = display.startsWith("+") ? "plus " : display.startsWith("-") ? "minus " : "";
  const bare = display.replace(/^[+-]/, "");
  if (/^\d{3,}$/.test(bare.replace(/,/g, ""))) {
    return `${sign}${spellInteger(Number(bare.replace(/,/g, "")))}`;
  }
  const zeroLed = /^(\d+)\.(0\d*)$/.exec(bare);
  if (zeroLed) {
    return `${sign}${spellLeadingZeroDecimal(Number(zeroLed[1]), zeroLed[2])}`;
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
  Hello: line([
    "Hello everyone. This one is real. On a Sunday night in August, a volunteer pointed ",
    "a radio at the sky and caught ",
    coldOpen.passMinutes,
    " minutes of a satellite. The record for it says two words. ",
    physics.status,
    ".",
  ]),

  Title: line([
    "Nobody went back to it. It is one of ",
    corpus.observations,
    ".",
  ]),

  Problem: line([
    "Only ",
    corpus.decisive,
    " carry a human verdict. The rest were kept and never read, because there is no ",
    "order to work through them in.",
  ]),

  Physics: line([
    "A pass shifts the frequency you hear. The orbit predicts that curve, spanning ",
    physics.corridorSpanHz,
    " hertz. Slide it ",
    physics.shiftPx,
    " pixels and it lands on the trace. The gap, as a fraction of the frequency, is ",
    physics.offsetPpm,
    " parts per million. This station had already corrected for Doppler, and nothing in ",
    "the record says so.",
  ]),

  Queue: line([
    "That is what the queue ranks on. ",
    reviewQueue.length,
    " observations against a budget of ",
    reviewQueue.budget,
    ". Not the loudest. The ones where the evidence disagrees with itself.",
  ]),

  Live: line([
    "All of that was frozen in August. Here is the live console measuring one again. Of ",
    liveTake.compared,
    " quantities, ",
    liveTake.exact,
    " match the archived digits exactly.",
  ]),

  Flow: line([
    "You can drive the same evidence from a LangFlow canvas. Watch. A sentence goes in ",
    "with a frequency this observation does not have. One take, no cut. The checker ",
    "refuses it and names why.",
  ]),

  Session: line([
    flow.refusedCode,
    ". That is the same checker that decides whether our own generated notes ship.",
  ]),

  Result: line([
    "Now the part demos skip. Six gates, with thresholds, written before anything was ",
    "measured. The headline one wanted half again as many conflicts as random. This ",
    "queue found ",
    lift.queueConflicts,
    " of them. Random ordering, at the same budget, expects ",
    lift.randomConflicts,
    ". We publish that as not established.",
  ]),

  Gates: line([
    "The point estimate is ",
    lift.point,
    ", and the interval straddles the bar, so it fails here. ",
    gates.met,
    " of ",
    gates.total,
    " gates met, and nothing was moved.",
  ]),

  Established: line([
    "Three did come back decided. Evidence tools take a local Granite model from ",
    established.withoutTools,
    " of ",
    established.trials,
    " right to ",
    established.withTools,
    ". The checker caught every one of ",
    established.adversarialChecks,
    " planted falsehoods. And on stations the queue never saw, lift clears at ",
    established.coldLift,
    ".",
  ]),

  Bob: line([
    "IBM Bob built the load-bearing pipeline: contracts, snapshot, parser, corridor, ",
    "baselines, queue. ",
    bobUnits.count,
    " dated units, each naming what it changed and what failed first.",
  ]),

  Colophon: line([
    "Every figure you heard came out of a receipt. The waterfall is public, cited and ",
    "licensed.",
  ]),

  Thanks: line([
    "That is TraceTriage. Thank you for watching. Go and check a number.",
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
