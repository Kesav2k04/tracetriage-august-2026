/**
 * The console's data layer.
 *
 * Everything is read from JSON produced by scripts/build_console_data.py at build
 * time. Nothing is fetched at runtime and nothing is computed here: a number
 * displayed by this console was measured by the pipeline and validated against
 * its contract before it reached disk. If a value is missing, the console says so
 * rather than filling it in, because a console that computes its own version of a
 * claim is a second implementation nobody tested.
 */
import cardsJson from "@/public/data/cards.json";
import heroNullsJson from "@/public/data/hero_nulls.json";
import evaluationJson from "@/public/data/evaluation.json";
import provenanceJson from "@/public/data/provenance.json";
import queueJson from "@/public/data/queue.json";

export {
  NON_ACTIONABLE,
  REASON_LABELS,
  type QueueReason,
  type QueueRow,
} from "./queue-view";

import type { QueueReason } from "./queue-view";

export interface QueueEntry {
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
  flat_row_frac: number | null;
  ensemble_uncertainty: number | null;
  episode_key: string;
}

export interface CorridorGeometry {
  fitted_offset_hz: number;
  fitted_offset_ppm: number | null;
  offset_at_bound: boolean | null;
  half_width_px: number;
  half_width_hz: number;
  max_elevation_deg: number;
  tca_frac: number;
  rows: number[];
  fitted_px: number[];
  predicted_px: number[];
  vertical_px: number;
  sigma_curved: number | null;
  sigma_vertical: number | null;
  note: string;
}

/**
 * The pass as geometry: where the satellite was in the sky and over the ground.
 *
 * Exported per card by `build_pass_geometry`, from the same propagation the
 * corridor was scored against. When `degraded` is a string the series are absent
 * and the reason is the string, which is why every consumer checks it first
 * instead of checking whether an array is empty.
 */
export interface PassTrack {
  station_lat: number;
  station_lon: number;
  station_alt_m: number;
  fracs: number[];
  azimuth_deg: number[];
  elevation_deg: number[];
  sub_lat_deg: number[];
  sub_lon_deg: number[];
  altitude_km: number[];
  range_km: number[];
  /** Null when the record carries no receive frequency. Not zero: zero is a claim. */
  doppler_hz: number[] | null;
  doppler_note: string;
  max_elevation_deg: number;
  tca_frac: number;
  tca_azimuth_deg: number;
  min_range_km: number;
  n_samples_propagated: number;
  n_sgp4_errors: number;
  note: string;
}

/**
 * A discriminated union rather than one interface with optional fields.
 *
 * When the propagation fails the export writes `{degraded: "..."}` and nothing
 * else, so an interface that typed the series as always present would be a lie the
 * compiler enforced. As a union, reading `max_elevation_deg` without first checking
 * `degraded` is a type error, which is the guard this console keeps getting wrong
 * by hand: two absences have already been published here as measurements.
 */
export type PassGeometry =
  | { degraded: string }
  | ({ degraded: null } & PassTrack);

export interface Card {
  obs_id: number;
  degraded: string | null;
  image?: string;
  thumb?: string;
  width?: number;
  height?: number;
  bytes?: number;
  source_sha256?: string;
  intensity?: string;
  hz_per_px?: number;
  seconds_per_px?: number;
  centre_px?: number | null;
  derivation?: string;
  derivation_confidence?: number | null;
  rx_freq_hz?: number | null;
  start?: string;
  end?: string;
  ground_station?: number;
  station_name?: string;
  norad_cat_id?: number;
  transmitter_uuid?: string;
  transmitter_mode?: string;
  waterfall_status?: string;
  corridor?: CorridorGeometry | null;
  corridor_note?: string | null;
  geometry?: PassGeometry | null;
}

export { fmt, fmtInterval, verdictColour, type Verdict } from "./format";

import type { Verdict } from "./format";

export interface SplitGate6 {
  measurable: boolean;
  not_measurable_reason: string | null;
  n_queue_examined: number | null;
  n_random_conflicts: number | null;
  n_queue_conflicts: number | null;
  lift_point: number | null;
  lift_ci95: [number, number] | null;
  lift_ci95_episode: [number, number] | null;
  lift_ci95_station: [number, number] | null;
  governing_interval: string | null;
  verdict_episode_only: Verdict | null;
  bootstrap_median: number | null;
  point_in_ci: boolean | null;
  n_boot: number | null;
  n_boot_effective: number | null;
  n_groups: number | null;
  n_station_groups: number | null;
  verdict: Verdict;
  direction: string | null;
  fifo_lift_over_random: number | null;
  image_uncertainty_lift_over_random: number | null;
  physics_only_lift_over_random: number | null;
  episode_clustering: Clustering | null;
  station_clustering: Clustering | null;
  replay_episode: Replay | null;
  replay_station: Replay | null;
  replay_conclusion: ReplayConclusion | null;
  uncapped_reference: {
    lift_point: number | null;
    lift_ci95_episode: [number, number] | null;
    verdict_if_it_were_eligible: string;
    n_queue_conflicts: number | null;
    note: string;
  } | null;
}

export interface Clustering {
  measurable: boolean;
  reason: string | null;
  icc: number | null;
  design_effect: number | null;
  n_groups: number | null;
  n_observations: number | null;
  mean_group_size: number | null;
}

export interface Replay {
  measurable: boolean;
  reason: string | null;
  budget?: number;
  n_population?: number;
  n_total_conflicts?: number;
  random_expected_conflicts?: number;
  n_groups?: number;
  n_degenerate_resamples?: number;
  orderings: Record<
    string,
    {
      n_conflicts_at_budget: number;
      lift_over_random: number;
      lift_ci95: [number, number] | null;
      measurable: boolean;
      reason: string | null;
    }
  >;
  comparisons: Record<
    string,
    {
      measurable: boolean;
      reason: string | null;
      diff_point: number | null;
      diff_ci95: [number, number] | null;
      diff_ci_adjusted: [number, number] | null;
      diff_median?: number | null;
      ratio_point: number | null;
      ratio_ci95?: [number, number] | null;
      ratio_ci_adjusted?: [number, number] | null;
      direction: string;
      survives_correction: boolean | null;
      n_comparisons: number;
      adjusted_confidence?: number;
      n_effective?: number;
      statistic?: string;
    }
  >;
  note?: string;
}

export interface ReplayConclusion {
  measurable: boolean;
  reason: string | null;
  baselines: Record<
    string,
    {
      claim: string;
      direction_episode: string | null;
      direction_station: string | null;
      survives_correction_episode: boolean | null;
      survives_correction_station: boolean | null;
      diff_point: number | null;
      diff_ci_adjusted_episode: [number, number] | null;
      diff_ci_adjusted_station: [number, number] | null;
      reason: string | null;
    }
  >;
  n_baselines?: number;
  n_beaten_under_both_groupings?: number;
  beaten?: string[];
  lost_to?: string[];
  rule?: string;
}

const queueData = queueJson as unknown as {
  generated_at: string;
  seed: number;
  review_budget: { n_observations: number; rationale: string };
  conflict_definition: {
    criteria: Array<{
      reason_code: string;
      description: string;
      threshold: string | number;
      measurable_from_snapshot: boolean;
    }>;
    fixed_before_measuring: boolean;
    caveats: string[] | string;
  };
  deduplication: Record<string, unknown>;
  per_split_summaries: Array<{
    split: string;
    n_test_total: number | null;
    n_test_decisive: number | null;
    n_queue_after_dedup: number | null;
    n_episodes_deduplicated: number | null;
    n_degraded_revolution: number | null;
    n_at_bound_obs: number | null;
    concentration: {
      caps: Record<
        string,
        {
          share_of_budget: number;
          entries_at_budget: number;
          n_displaced: number;
          bound: boolean;
          reason_code: string;
        }
      >;
      n_admitted_to_budget: number;
      n_displaced_total: number;
      budget: number;
      budget_filled: boolean;
      binding: boolean;
      note?: string;
    } | null;
  }>;
  entries: QueueEntry[];
  receipt_sha256: string;
};

const cardsData = cardsJson as unknown as {
  n_requested: number;
  n_built: number;
  n_degraded: number;
  named_observations: number[];
  intensity_note: string;
  attribution: string;
  cards: Card[];
};

export interface ArmMetrics {
  blocks: string[];
  degraded: string | null;
  n_columns: number;
  calibrator: string;
  calibrator_chosen_because: string;
  brier: number;
  log_loss: number;
  auc: number;
  ece: number;
  calibration_slope: number;
  calibration_intercept: number;
  mean_prediction: number;
}

export interface SelectivePoint {
  threshold: number;
  coverage: number;
  n_kept: number;
  n_groups_kept: number;
  risk: number;
  n_errors: number;
}

export interface FusionSplit {
  split: string;
  degraded: string | null;
  counts: Record<string, number>;
  test_positive_rate: number | null;
  arms: Record<string, ArmMetrics>;
  comparisons: Record<
    string,
    {
      margin: number | null;
      ci95: [number, number] | null;
      ci95_adjusted?: [number, number] | null;
      direction: string;
      distinguishable: boolean;
      challenger_better?: boolean;
      n_observations?: number;
      n_groups?: number;
    }
  >;
  multiplicity_adjusted: Record<string, unknown> | null;
  ensemble: Record<string, unknown> | null;
  selective: { curve: SelectivePoint[]; [k: string]: unknown } | null;
  ood: Record<string, unknown> | null;
}

export interface Gate5 {
  gate: number;
  wording: string;
  challenger: string;
  reference: string;
  decided_on: string;
  verdict: Verdict;
  statement: string;
  per_split: Record<
    string,
    {
      measurable: boolean;
      margin: number | null;
      ci95: [number, number] | null;
      ci95_adjusted?: [number, number] | null;
      direction: string;
      distinguishable: boolean;
      challenger_better: boolean;
      n_observations: number | null;
      n_groups: number | null;
      challenger_brier: number | null;
      reference_brier: number | null;
    }
  >;
}

export interface AblationConclusion {
  rules: Record<string, string>;
  deciding_rule: string;
  why_the_corrected_rule_decides: string;
  blocks?: Record<
    string,
    {
      retained: boolean;
      retained_nominal?: boolean;
      reason: string;
      [k: string]: unknown;
    }
  >;
  [k: string]: unknown;
}

const evaluationData = evaluationJson as unknown as {
  gate6: {
    gate: number;
    wording: string;
    decided_on: string;
    verdict: Verdict;
    statement: string;
    per_split: Record<string, SplitGate6>;
  };
  gate5: Gate5;
  ablation_conclusion: AblationConclusion;
  arm_ladder: Array<{ name: string; blocks: string[] }>;
  size_matched_control: Record<string, unknown>;
  fusion_splits: FusionSplit[];
  receipt_sha256: { queue: string; fusion: string };
};

const provenanceData = provenanceJson as unknown as {
  snapshot_id: string;
  split_manifest_sha256: string;
  gate_summary: {
    gates: Array<{
      gate: number;
      title: string;
      verdict: string;
      decided_in: string;
    }>;
    n_gates: number;
    n_met: number;
    note: string;
  };
  splits: Array<{ name: string; counts: Record<string, number> }>;
  receipts: Array<{ name: string; sha256: string; bytes: number }>;
  contracts: Array<{
    name: string;
    version: string;
    status: string;
    sha256: string;
  }>;
};

/**
 * The opening frame's corridors: the fitted one and the nulls it was scored against.
 *
 * Written by `scripts/export_hero_nulls.py`, which re-runs gate 3's own fit outside
 * the scoring path and refuses to write unless `n_nulls`, `true_sigma`,
 * `null_median`, `null_p95`, `null_max`, `n_at_least` and `p_value` all reproduce
 * `artifacts/GATE3_RECEIPT.json` to 1e-9. That is why the console can call these the
 * measured nulls rather than an illustration of them.
 *
 * Coordinates are the cropped plot region, 620 by 1540 on this observation, which is
 * the space the shipped waterfall and every other overlay already use.
 */
export interface HeroNullPath {
  seed: number;
  sigma: number;
  offset_px: number;
  is_best_null: boolean;
  px: number[];
}

export interface HeroNulls {
  obs_id: number;
  image: { width: number; height: number };
  rows: number[];
  true: { sigma: number; offset_px: number; px: number[] };
  distribution: {
    n_nulls: number;
    median: number;
    p95: number;
    max: number;
    n_at_least: number;
    p_value: number;
    margin_over_best_null: number;
  };
  drawn: HeroNullPath[];
  transform_residual_px: number;
}

const heroNullsData = heroNullsJson as unknown as HeroNulls;

// An absence must never be published as a measurement, and a frame that argued
// against two hundred nulls while drawing none would be exactly that.
if (heroNullsData.drawn.length === 0) {
  throw new Error(
    "hero_nulls.json contains no drawn paths. Run scripts/export_hero_nulls.py.",
  );
}

export const heroNulls = heroNullsData;

export const queue = queueData;
export const cards = cardsData;
export const evaluation = evaluationData;
export const provenance = provenanceData;

export const cardById = new Map<number, Card>(
  cardsData.cards.map((card) => [card.obs_id, card]),
);

export const entryById = new Map<number, QueueEntry>(
  queueData.entries.map((entry) => [entry.obs_id, entry]),
);

/** Observations with imagery, in queue order. These are the routable cards. */
export const showcaseIds: number[] = cardsData.cards
  .filter((card) => !card.degraded)
  .map((card) => card.obs_id)
  .sort((a, b) => {
    const ra = entryById.get(a)?.rank ?? Number.MAX_SAFE_INTEGER;
    const rb = entryById.get(b)?.rank ?? Number.MAX_SAFE_INTEGER;
    return ra - rb;
  });

/**
 * A gate 6 split, or a build failure.
 *
 * Rendering "not measured" because a split is missing from the receipt would say
 * something false about a measurement that exists, so a missing split stops the
 * build instead. Every page that needs one goes through here.
 */
export function requireGate6Split(name: string): SplitGate6 {
  const split = evaluationData.gate6.per_split[name];
  if (!split) {
    throw new Error(
      `gate 6 has no ${name} split; the receipt carries ` +
        `${Object.keys(evaluationData.gate6.per_split).join(", ")}.`,
    );
  }
  return split;
}

export function requireQueueSplit(name: string) {
  const summary = queueData.per_split_summaries.find((s) => s.split === name);
  if (!summary) {
    throw new Error(`the queue receipt has no ${name} split summary.`);
  }
  return summary;
}

