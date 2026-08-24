/**
 * Everything this client reads, and the one thing it writes.
 *
 * There is no separate mobile backend and no mobile copy of the data. The three screens read
 * the same four files the console reads and post to the same function the console posts to,
 * all from one origin declared in `app.json` under `expo.extra.origin`. That is the property
 * worth having: a number on a phone and the same number on the console cannot disagree,
 * because there is only one of it.
 *
 *   /data/queue.json       the ranked passes, 407 entries, with the score and the reasons
 *   /data/cards.json       per-observation geometry: the image, its scale, the corridor
 *   /data/provenance.json  the snapshot id and the six gate verdicts
 *   /api/live              POST an observation id, get a Doppler measurement taken now
 *
 * `cards.json` is 739 KB and is fetched once per launch, held in memory, and never written
 * to disk. A local copy would be a second dataset that could go stale against the console,
 * which is the whole failure this arrangement avoids.
 */

import Constants from "expo-constants";

/** The deployment this build talks to. One place, so a fork can point it somewhere else. */
export const ORIGIN: string =
  (Constants.expoConfig?.extra?.origin as string | undefined)
  ?? "https://tracetriage.vercel.app";

export interface QueueEntry {
  obs_id: number;
  satellite: string;
  rank: number;
  score: number;
  reasons: string[];
  is_conflict: boolean | null;
  within_budget: boolean | null;
  waterfall_status: string;
  model_prob: number | null;
  fitted_offset_ppm: number | null;
  offset_at_bound: boolean | null;
}

export interface Queue {
  generated_at: string;
  review_budget: { n: number; note?: string } | Record<string, unknown>;
  entries: QueueEntry[];
  receipt_sha256: string;
}

/** The corridor, in the pixel coordinates of the waterfall image it belongs to. */
export interface Corridor {
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
  note: string;
}

export interface Card {
  obs_id: number;
  degraded: string | null;
  image?: string;
  width?: number;
  height?: number;
  hz_per_px?: number;
  seconds_per_px?: number;
  centre_px?: number | null;
  /** How the frequency axis was established for this image, not assumed. */
  derivation?: string;
  derivation_confidence?: number | null;
  rx_freq_hz?: number | null;
  satellite?: string;
  station_name?: string | null;
  ground_station?: number | null;
  start?: string | null;
  waterfall_status?: string | null;
  transmitter_mode?: string | null;
  corridor?: Corridor | null;
  corridor_note?: string | null;
  source_sha256?: string;
}

export interface Provenance {
  snapshot_id: string;
  gate_summary: {
    n_gates: number;
    n_met: number;
    gates: { gate: number; title: string; verdict: string; decided_in: string }[];
  };
}

/**
 * What `/api/live/` returns when it measured something.
 *
 * The envelope is nested, and the nesting is the point: `mode` is whether the station
 * Doppler-corrected the capture, `measurement` is how far the trace sits from where the
 * orbit says it should be, and `nulls` is what that margin is worth. A client that flattened
 * these into one bag of numbers would be able to show an offset without the verdict that
 * says whether the offset means anything. The field names are `pipeline/tracetriage/live.py`
 * `LiveMeasurement.to_dict`, which is also what the CLI prints and what the console renders,
 * so all three agree by construction.
 */
export interface Measurement {
  observation?: {
    id?: number;
    norad_cat_id?: number;
    satellite?: string;
    station?: number;
    station_name?: string;
    start?: string;
    waterfall_status?: string;
  };
  pass?: {
    rx_freq_hz?: number;
    max_elevation_deg?: number;
    duration_s?: number;
    doppler_swing_hz?: number;
  };
  axis?: { hz_per_px?: number; derivation?: string; confidence?: number };
  mode?: {
    verdict?: string;
    why?: string;
    sigma_curved?: number | null;
    sigma_vertical?: number | null;
    corridor_scored?: string | null;
  };
  measurement?: {
    offset_hz?: number | null;
    offset_ppm?: number | null;
    at_search_bound?: boolean | null;
    sigma?: number | null;
  };
  nulls?: {
    n?: number | null;
    p_value?: number | null;
    not_tested?: string | null;
    median?: number | null;
  };
  provenance?: {
    measured_at_utc?: string;
    waterfall_sha256?: string;
    waterfall_bytes?: number;
    tle_source?: string;
  };
}

async function readJson<T>(path: string, timeoutMs = 20000): Promise<T> {
  // An explicit timeout, because the default on Android is over a minute and a screen that
  // says nothing for a minute is indistinguishable from one that is broken.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${ORIGIN}${path}`, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`${path} answered ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const fetchQueue = () => readJson<Queue>("/data/queue.json");
export const fetchProvenance = () => readJson<Provenance>("/data/provenance.json");

/** The card index, fetched once and shared. 739 KB, so not once per screen. */
let cardCache: Promise<Map<number, Card>> | null = null;

export function fetchCards(): Promise<Map<number, Card>> {
  if (!cardCache) {
    cardCache = readJson<{ cards: Card[] }>("/data/cards.json", 40000)
      .then((body) => new Map(body.cards.map((card) => [card.obs_id, card])))
      .catch((error) => {
        // Do not cache a failure. A reader who lost signal for one request should get a
        // retry on the next screen rather than a permanent empty index.
        cardCache = null;
        throw error;
      });
  }
  return cardCache;
}

export function imageUrl(card: Card): string | null {
  return card.image ? `${ORIGIN}${card.image}` : null;
}

export type LiveResult =
  | { kind: "measured"; measurement: Measurement; source: string }
  | { kind: "refused"; code: string; detail: string };

/**
 * The one write. POST an observation id, and the function downloads that waterfall from
 * SatNOGS and fits a corridor to it, which takes tens of seconds on a cold start.
 *
 * A refusal is a result, not an exception. The endpoint answers with a code for every way it
 * can decline, and the screen shows the code, because "something went wrong" is the message
 * that makes a reader distrust the number they got last time.
 */
export async function measure(obsId: number, timeoutMs = 75000): Promise<LiveResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    // The trailing slash is not cosmetic. `vercel.json` sets `trailingSlash: true`, so the
    // deployment answers `/api/live` with a 308 and the rewrite sends it back to the
    // function. A fetch follows the redirect and keeps the method, so the unslashed form
    // works and costs an extra round trip on a request that already takes tens of seconds.
    // Measured from the console: POST /api/live is 308, POST /api/live/ is 200 in 16.1 s.
    const response = await fetch(`${ORIGIN}/api/live/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ obs_id: obsId }),
      signal: controller.signal,
    });
    const body = (await response.json()) as {
      ok?: boolean;
      // Every refusal nests under `error`. Read from the deployment on 2026-08-24:
      // 429 -> {"ok":false,"error":{"kind":"rate_limit","code":"RATE_LIMITED",
      //         "detail":"at most 6 measurements per 60 s from one caller","retry_after_s":18}}
      // 422 -> {"ok":false,"error":{"kind":"refusal","code":"NOT_FOUND",
      //         "detail":"observation 999999999","observation_id":999999999}}
      // The first version of this function read `code` and `detail` at the top level, where
      // they are undefined, so every server refusal printed HTTP_429 or HTTP_422 over "the
      // endpoint answered without a measurement and without a reason" while the endpoint had
      // in fact given one. A wrong nesting level returns undefined instead of raising, so
      // nothing failed anywhere: not tsc, not a test, not the screen. Only posting an id to
      // the live deployment showed it. The top-level names are kept as a fallback so an older
      // deployment still reads.
      error?: { kind?: string; code?: string; detail?: string; retry_after_s?: number };
      code?: string;
      detail?: string;
      message?: string;
      source?: string;
      measurement?: Measurement;
    };
    if (response.ok && body.ok && body.measurement) {
      return {
        kind: "measured",
        measurement: body.measurement,
        source: body.source ?? "live",
      };
    }
    const error = body.error ?? {};
    const wait = error.retry_after_s;
    const detail = error.detail ?? body.detail ?? body.message;
    return {
      kind: "refused",
      code: error.code ?? body.code ?? `HTTP_${response.status}`,
      detail:
        (detail ?? "The endpoint answered without a measurement and without a reason.")
        + (typeof wait === "number" ? `. Try again in ${wait} s.` : ""),
    };
  } catch {
    return {
      kind: "refused",
      code: "ENDPOINT_UNREACHABLE",
      detail:
        "The measurement endpoint did not answer. One waterfall download plus a corridor "
        + "fit takes tens of seconds, so a cold start can exceed the platform's function "
        + "limit. Try the same id again: the second call is served from cache.",
    };
  } finally {
    clearTimeout(timer);
  }
}
