/**
 * The queue, encoded for the field behind the first screen.
 *
 * `components/DeepField.tsx` draws 407 points and claims each one is an observation. That
 * claim is only worth making if the encoding is derived rather than decorative, so it is
 * built here, on the server, from the same `queue.json` the table reads, and checked by
 * `tests/field-encoding.test.ts`.
 *
 * The one rule that matters: a reason code with no colour is an error, not a default. A
 * fifth criterion folded silently into the grey of `NO_REASON` would let the field show a
 * category it never named, and nobody would see it happen.
 */

import type { QueueEntry } from "@/lib/data";

/**
 * One point in the field: rank position, review value, criterion and measured drift.
 *
 * Declared here rather than beside the canvas that draws it, because everything a server
 * component needs has to live outside the `"use client"` boundary. An export read across
 * that boundary is replaced with a client reference, so `FIELD_REASONS.indexOf` came back
 * as "not a function" at build time: the value the server saw was a proxy for a module it
 * was never going to run.
 */
export interface FieldPoint {
  /** 0 at the top of the queue, 1 at the tail. */
  rank01: number;
  /** Review value, rescaled across the queue's own range of scores. */
  value01: number;
  /** Index into `FIELD_REASONS`. */
  reason: number;
  /** |fitted offset| as a fraction of the ceiling. 0 for no fit and for a zero fit. */
  ppm: number;
  /** Whether a corridor was fitted at all. A fit of zero ppm is still a fit. */
  fitted: boolean;
}

/**
 * The criteria the field has colours for, in the order the shader indexes them.
 *
 * These four are the ones the queue actually raised over the 407 ranked observations.
 * `reasonIndex` throws on a fifth rather than folding it into the grey of `NO_REASON`.
 */
export const FIELD_REASONS = [
  "NO_REASON",
  "STALE_CATALOGUE_FREQ",
  "MODEL_LABEL_DISAGREE",
  "DISPLACED_STATION_CAP",
] as const;

/**
 * The custom property each criterion reads its colour from, in the same order.
 *
 * Tokens rather than hex, resolved off the document at runtime, so the field is painted in
 * whatever `scripts/derive_palette.py` last generated and the legend beside it cannot
 * disagree with the canvas.
 */
export const FIELD_REASON_TOKENS = [
  "--text-03",
  "--support-03",
  "--live-01",
  "--support-05",
] as const;

/** The largest offset the drift is scaled to. Beyond this a point stops swimming faster. */
export const FIELD_PPM_CEILING = 40;

/**
 * One point per entry, in rank order.
 *
 * `value01` is the score rescaled across the queue's own range rather than across 0..1,
 * because the scores run from 0.23 to 0.88 and a field normalised to the wrong span would
 * be uniformly bright and say nothing.
 */
export function fieldPoints(entries: readonly QueueEntry[]): FieldPoint[] {
  if (entries.length === 0) return [];
  const scores = entries.map((entry) => entry.score);
  const low = Math.min(...scores);
  const high = Math.max(...scores);
  const span = high - low || 1;
  const last = Math.max(1, entries.length - 1);

  return entries.map((entry, index) => {
    const reason = reasonIndex(entry.reasons);
    const ppm = entry.fitted_offset_ppm;
    return {
      rank01: index / last,
      value01: (entry.score - low) / span,
      reason,
      ppm:
        ppm === null
          ? 0
          : Math.min(Math.abs(ppm), FIELD_PPM_CEILING) / FIELD_PPM_CEILING,
      // Two of the 87 fits came out at exactly zero ppm, which is a measurement and not
      // a missing one. Carried apart from the drift so the field can show the difference
      // between a receiver that is on frequency and a pass nobody measured.
      fitted: ppm !== null,
    };
  });
}

/**
 * The criterion a point is coloured by: the most specific one the entry carries.
 *
 * An entry can raise more than one. `NO_REASON` is the absence of a criterion, so anything
 * else wins over it; beyond that the first one in the entry's own order is used, which is
 * the order `run_queue.py` wrote them in.
 */
export function reasonIndex(reasons: readonly string[]): number {
  const specific = reasons.find((reason) => reason !== "NO_REASON") ?? reasons[0];
  if (specific === undefined) return 0;
  const index = FIELD_REASONS.indexOf(specific as (typeof FIELD_REASONS)[number]);
  if (index < 0) {
    throw new Error(
      `the queue raised ${specific} and the field has no colour for it. Add it to ` +
        `FIELD_REASONS and REASON_TOKENS in components/DeepField.tsx, or the field will ` +
        `show a category it never named.`,
    );
  }
  return index;
}
