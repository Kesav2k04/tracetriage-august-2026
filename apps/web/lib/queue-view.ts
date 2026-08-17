/**
 * The queue table's own vocabulary, and nothing else.
 *
 * This module exists because of a measured mistake. The filterable table is a
 * client component, and it imported its labels from lib/data, which imports the
 * four receipt files. Importing one constant pulled all of them: the queue page
 * shipped a 306 KB client chunk carrying every observation card, including the
 * per-row corridor coordinate arrays that only the observation pages draw. A
 * client component must not reach into a module that loads server data, so the
 * labels live here, where there is nothing to leak.
 */

export type QueueReason =
  | "MODEL_LABEL_DISAGREE"
  | "STALE_CATALOGUE_FREQ"
  | "DEAD_CAPTURE"
  | "OFFSET_AT_BOUND"
  | "NO_REASON"
  | "DISPLACED_STATION_CAP"
  | "DISPLACED_TRANSMITTER_CAP";

export const REASON_LABELS: Record<QueueReason, string> = {
  MODEL_LABEL_DISAGREE: "Model disagrees with label",
  STALE_CATALOGUE_FREQ: "Stale catalogue frequency",
  DEAD_CAPTURE: "Dead capture time",
  OFFSET_AT_BOUND: "Offset at search bound",
  NO_REASON: "No conflict criterion",
  DISPLACED_STATION_CAP: "Displaced, station cap",
  DISPLACED_TRANSMITTER_CAP: "Displaced, transmitter cap",
};

/** Reasons that are informational rather than actionable. */
export const NON_ACTIONABLE: ReadonlySet<QueueReason> = new Set([
  "OFFSET_AT_BOUND",
  "NO_REASON",
  "DISPLACED_STATION_CAP",
  "DISPLACED_TRANSMITTER_CAP",
]);

/**
 * Exactly the fields the table draws.
 *
 * The receipt's rows carry more than this. Sending the rest would put three more
 * fields per row into the page for columns nobody renders.
 */
export interface QueueRow {
  obs_id: number;
  rank: number;
  score: number;
  reasons: QueueReason[];
  is_conflict: boolean | null;
  within_budget: boolean | null;
  displaced_by_cap: string | null;
  waterfall_status: string;
  model_prob: number | null;
  fitted_offset_ppm: number | null;
  offset_at_bound: boolean | null;
}
