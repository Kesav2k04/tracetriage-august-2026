/**
 * Every number this film puts on screen, read at build time from a receipt.
 *
 * Nothing here is typed from reading a document. Each field names its file and its
 * key path, `read()` resolves that path against the parsed JSON, and the display
 * string is a function of whatever the path returned. A renamed key breaks the
 * render. A changed measurement changes the film.
 *
 * The receipts are imported from outside this package on purpose. Copying them in
 * would create a second copy to go stale, which is the failure this whole project
 * is built against.
 */

import manifestJson from "../../artifacts/DATASET_MANIFEST.json";
import queueJson from "../../artifacts/QUEUE_RECEIPT.json";
import gate3Json from "../../artifacts/GATE3_RECEIPT.json";
import provenanceJson from "../../apps/web/public/data/provenance.json";
import cardsJson from "../../apps/web/public/data/cards.json";
import attributionJson from "../../artifacts/ATTRIBUTION_AUDIT.json";
import agentJson from "../../artifacts/AGENT_RECEIPT.json";
import explainJson from "../../artifacts/EXPLAIN_RECEIPT.json";
import circularityJson from "../../artifacts/CIRCULARITY_RECEIPT.json";
import narrationJson from "../../artifacts/NARRATION_RECEIPT.json";
import sessionJson from "../../artifacts/OPERATOR_SESSION.json";
import bobJson from "../../apps/web/public/data/bob.json";
import takeJson from "../../artifacts/LIVE_TAKE.json";
import langflowJson from "../../artifacts/LANGFLOW_RECEIPT.json";

import {
  Claim,
  firstSentence,
  fixed,
  group,
  identifier,
  identity,
  read,
  resolve,
  signedFixed,
  signedGroup,
} from "./claim";

export const FILE = {
  manifest: "artifacts/DATASET_MANIFEST.json",
  queue: "artifacts/QUEUE_RECEIPT.json",
  gate3: "artifacts/GATE3_RECEIPT.json",
  provenance: "apps/web/public/data/provenance.json",
  cards: "apps/web/public/data/cards.json",
  attribution: "artifacts/ATTRIBUTION_AUDIT.json",
  agent: "artifacts/AGENT_RECEIPT.json",
  explain: "artifacts/EXPLAIN_RECEIPT.json",
  circularity: "artifacts/CIRCULARITY_RECEIPT.json",
  narration: "artifacts/NARRATION_RECEIPT.json",
  session: "artifacts/OPERATOR_SESSION.json",
  bob: "apps/web/public/data/bob.json",
  take: "artifacts/LIVE_TAKE.json",
  langflow: "artifacts/LANGFLOW_RECEIPT.json",
} as const;

const manifest = manifestJson as unknown;
const queue = queueJson as unknown;
const gate3 = gate3Json as unknown;
const provenance = provenanceJson as unknown;
const cards = cardsJson as unknown;
const attribution = attributionJson as unknown;
const narration = narrationJson as unknown;
const session = sessionJson as unknown;
const bob = bobJson as unknown;
const take = takeJson as unknown;
const langflow = langflowJson as unknown;
const agent = agentJson as unknown;
const explain = explainJson as unknown;
const circularity = circularityJson as unknown;

const m = <T,>(path: string, format: (v: T) => string) =>
  read<T>(manifest, FILE.manifest, path, format);
const q = <T,>(path: string, format: (v: T) => string) =>
  read<T>(queue, FILE.queue, path, format);
const g3 = <T,>(path: string, format: (v: T) => string) =>
  read<T>(gate3, FILE.gate3, path, format);
const pv = <T,>(path: string, format: (v: T) => string) =>
  read<T>(provenance, FILE.provenance, path, format);
const cd = <T,>(path: string, format: (v: T) => string) =>
  read<T>(cards, FILE.cards, path, format);
const at = <T,>(path: string, format: (v: T) => string) =>
  read<T>(attribution, FILE.attribution, path, format);
const ag = <T,>(path: string, format: (v: T) => string) =>
  read<T>(agent, FILE.agent, path, format);
const ex = <T,>(path: string, format: (v: T) => string) =>
  read<T>(explain, FILE.explain, path, format);
const ci = <T,>(path: string, format: (v: T) => string) =>
  read<T>(circularity, FILE.circularity, path, format);
const na = <T,>(path: string, format: (v: T) => string) =>
  read<T>(narration, FILE.narration, path, format);
const se = <T,>(path: string, format: (v: T) => string) =>
  read<T>(session, FILE.session, path, format);
const bo = <T,>(path: string, format: (v: T) => string) =>
  read<T>(bob, FILE.bob, path, format);
const tk = <T,>(path: string, format: (v: T) => string) =>
  read<T>(take, FILE.take, path, format);
const lf = <T,>(path: string, format: (v: T) => string) =>
  read<T>(langflow, FILE.langflow, path, format);

// ---------------------------------------------------------------------------
// Beat 1. The corpus, and how much of it carries a human verdict.
// ---------------------------------------------------------------------------

const observationsStored = m<number>("counts.observations_stored", group);
const decisive = m<number>("counts.waterfall_status_decisive", group);

/**
 * One cell per stored observation, in the order the snapshot fetched them, true
 * where a human left a decisive verdict. The grid in beat 1 is this array: the
 * scatter on screen is the scatter in the corpus, not a pattern chosen to look busy.
 */
const DECISIVE_STATUS = ["with-signal", "without-signal"];
const verdictMask = (
  resolve(manifest, "observations") as { waterfall_status: string }[]
).map((o) => DECISIVE_STATUS.includes(o.waterfall_status));

export const corpus = {
  snapshotId: m<string>("snapshot_id", identity),
  observations: observationsStored,
  waterfalls: m<number>("counts.waterfalls_stored", group),
  decisive,
  /** Derived, and the arithmetic is on screen: stored minus decisive. */
  noVerdict: {
    file: FILE.manifest,
    path: "counts.observations_stored - counts.waterfall_status_decisive",
    value: observationsStored.value - decisive.value,
    display: group(observationsStored.value - decisive.value),
  } as Claim<number>,
  queriedBackFrom: m<string>("query.end", identity),
  pagesFetched: m<number>("counts.pages_fetched", group),
  licence: m<string>("license", identity),
  verdictMask,
} as const;

// ---------------------------------------------------------------------------
// Beat 2. The ranked queue and the reviewer's budget.
// ---------------------------------------------------------------------------

type QueueRow = {
  obs_id: number;
  rank: number;
  score: number;
  reasons: string[];
  within_budget: boolean;
  is_conflict: boolean;
  displaced_by_cap: string | null;
};

const rows = resolve(queue, "queue") as QueueRow[];
const budgetRows = rows.filter((r) => r.within_budget);

const countReason = (code: string) =>
  budgetRows.filter((r) => r.reasons.includes(code)).length;

export const REASON = {
  disagree: "MODEL_LABEL_DISAGREE",
  stale: "STALE_CATALOGUE_FREQ",
  dead: "DEAD_CAPTURE",
  none: "NO_REASON",
} as const;

const derivedFromQueue = (path: string, value: number): Claim<number> => ({
  file: FILE.queue,
  path,
  value,
  display: group(value),
});

export const reviewQueue = {
  length: q<number>("deduplication.n_observations_after", group),
  budget: q<number>("review_budget.n_observations", group),
  budgetRationale: q<string>("review_budget.rationale", firstSentence),
  episodesDeduplicated: q<number>(
    "per_split_summaries[0].n_episodes_deduplicated",
    group,
  ),
  decisiveInTestSet: q<number>("per_split_summaries[0].n_test_decisive", group),
  testSetTotal: q<number>("per_split_summaries[0].n_test_total", group),
  stationCapDisplaced: q<number>(
    "per_split_summaries[0].concentration.caps.ground_station.n_displaced",
    group,
  ),
  stationCapEntries: q<number>(
    "per_split_summaries[0].concentration.caps.ground_station.entries_at_budget",
    group,
  ),
  /** One bar per observation, in rank order. Real scores, not a shape. */
  bars: rows.map((r) => ({
    rank: r.rank,
    score: r.score,
    inBudget: r.within_budget,
    displaced: r.displaced_by_cap !== null,
  })),
  criteria: [
    {
      code: REASON.disagree,
      label: "model disagrees with the label",
      firedInCorpus: q<number>("conflict_definition.criteria_fired[0].n_flagged", group),
      firedInBudget: derivedFromQueue(
        `queue[] where within_budget and reasons includes ${REASON.disagree}`,
        countReason(REASON.disagree),
      ),
      inert: q<boolean>(
        "conflict_definition.criteria_fired[0].inert_on_this_corpus",
        (v) => String(v),
      ),
    },
    {
      code: REASON.stale,
      label: "catalogue frequency looks stale",
      firedInCorpus: q<number>("conflict_definition.criteria_fired[1].n_flagged", group),
      firedInBudget: derivedFromQueue(
        `queue[] where within_budget and reasons includes ${REASON.stale}`,
        countReason(REASON.stale),
      ),
      inert: q<boolean>(
        "conflict_definition.criteria_fired[1].inert_on_this_corpus",
        (v) => String(v),
      ),
    },
    {
      code: REASON.dead,
      label: "capture is substantially dead",
      firedInCorpus: q<number>("conflict_definition.criteria_fired[2].n_flagged", group),
      firedInBudget: derivedFromQueue(
        `queue[] where within_budget and reasons includes ${REASON.dead}`,
        countReason(REASON.dead),
      ),
      inert: q<boolean>(
        "conflict_definition.criteria_fired[2].inert_on_this_corpus",
        (v) => String(v),
      ),
    },
  ],
  criteriaFixedBeforeMeasuring: q<boolean>(
    "conflict_definition.fixed_before_measuring",
    (v) => String(v),
  ),
} as const;

// ---------------------------------------------------------------------------
// Beat 3. One pass, one corridor, one measured offset.
// ---------------------------------------------------------------------------

type Card = {
  obs_id: number;
  width: number;
  height: number;
  hz_per_px: number;
  centre_px: number;
  rx_freq_hz: number;
  start: string;
  end: string;
  station_name: string;
  norad_cat_id: number;
  transmitter_mode: string;
  waterfall_status: string;
  corridor: {
    rows: number[];
    fitted_px: number[];
    predicted_px: number[];
    vertical_px: number;
    fitted_offset_hz: number;
    fitted_offset_ppm: number;
    half_width_px: number;
    max_elevation_deg: number;
  };
};

/**
 * 14740031, because it is one of the three observations gate 3 could actually be
 * asked of: its capture was not Doppler-corrected at the station, so the pass
 * geometry predicts a shape that could have been wrong.
 */
export const HERO_OBS_ID = 14740031;

const cardList = resolve(cards, "cards") as Card[];
const heroIndex = cardList.findIndex((c) => c.obs_id === HERO_OBS_ID);
if (heroIndex === -1) {
  throw new Error(`cards.json carries no card for observation ${HERO_OBS_ID}`);
}
const hero = cardList[heroIndex];
const CARD = `cards[${heroIndex}]`;

const gate3Obs = resolve(gate3, "observations") as { obs_id: number }[];
const gate3HeroIndex = gate3Obs.findIndex((o) => o.obs_id === HERO_OBS_ID);
if (gate3HeroIndex === -1) {
  throw new Error(`GATE3_RECEIPT.json carries no row for observation ${HERO_OBS_ID}`);
}

/** The distance the corridor slid, in image pixels. The measurement, in the picture. */
const shiftPx = hero.corridor.fitted_px[0] - hero.corridor.predicted_px[0];

export const physics = {
  obsId: cd<number>(`${CARD}.obs_id`, identifier),
  station: cd<string>(`${CARD}.station_name`, identity),
  norad: cd<number>(`${CARD}.norad_cat_id`, identifier),
  mode: cd<string>(`${CARD}.transmitter_mode`, identity),
  status: cd<string>(`${CARD}.waterfall_status`, identity),
  start: cd<string>(`${CARD}.start`, identity),
  rxMhz: cd<number>(`${CARD}.rx_freq_hz`, (hz) => (hz / 1e6).toFixed(3)),
  hzPerPx: cd<number>(`${CARD}.hz_per_px`, fixed(1)),
  secondsPerPx: cd<number>(`${CARD}.seconds_per_px`, fixed(3)),
  maxElevation: cd<number>(`${CARD}.corridor.max_elevation_deg`, fixed(1)),
  offsetHz: cd<number>(`${CARD}.corridor.fitted_offset_hz`, signedGroup),
  offsetPpm: cd<number>(`${CARD}.corridor.fitted_offset_ppm`, signedFixed(2)),
  corridorSpanHz: g3<number>(`observations[${gate3HeroIndex}].corridor_span_hz`, group),
  dopplerVerdict: g3<string>(`observations[${gate3HeroIndex}].verdict`, identity),
  shiftPx: {
    file: FILE.cards,
    path: `${CARD}.corridor.fitted_px[0] minus ${CARD}.corridor.predicted_px[0]`,
    value: shiftPx,
    display: group(Math.abs(shiftPx)),
  } as Claim<number>,
  /** Geometry, not a claim: the arrays the console draws its overlay from. */
  image: {
    src: `waterfalls/${HERO_OBS_ID}.webp`,
    width: hero.width,
    height: hero.height,
  },
  curve: {
    rows: hero.corridor.rows,
    predictedPx: hero.corridor.predicted_px,
    fittedPx: hero.corridor.fitted_px,
    verticalPx: hero.corridor.vertical_px,
    halfWidthPx: hero.corridor.half_width_px,
  },
} as const;

const gate3Scored = resolve(gate3, "observations_scored") as number;
const gate3Rate = resolve(gate3, "discriminating_rate") as number;

/**
 * The sentence that says what the bound did, derived from the receipt that produced it.
 *
 * Grouping is what decides. A ground station's oscillator error is common to every pass
 * it records, so observations sharing a station and a night are one systematic offset
 * measured several times, and the plan collapses them before reading the rate. A bound
 * that clears over observations and not over episodes is therefore reported as exactly
 * that rather than as a pass.
 */
function gate3OutcomeSentence(): string {
  const grouping = resolve(gate3, "entity_grouping") as {
    groups_scored: number;
    grouped_rate_lower_bound_95: number | null;
    grouped_clears_threshold?: boolean;
  };
  const clears = resolve(gate3, "clears_threshold") as boolean;
  const threshold = resolve(gate3, "threshold") as number;
  const rate = resolve(gate3, "discriminating_rate") as number;
  const groups = grouping.groups_scored;
  const groupedBound = grouping.grouped_rate_lower_bound_95;

  if (clears && grouping.grouped_clears_threshold) {
    return (
      `It clears the bar, over observations and over the ${groups} independent ` +
      `station-nights they span.`
    );
  }
  if (clears) {
    const shown = groupedBound === null ? "not measurable" : groupedBound.toFixed(2);
    return (
      `That clears the bar over observations. Over the ${groups} independent ` +
      `station-nights they span the bound is ${shown}, and the plan groups before it ` +
      `decides, so this is reported and not claimed.`
    );
  }
  if (rate >= threshold) {
    return "The rate is above the bar and the interval is not, so at this sample size the rate is not established.";
  }
  return "Both the rate and the interval below it are under the bar.";
}

export const gate3Result = {
  number: g3<number>("gate", group),
  question: g3<string>("question", identity),
  scored: g3<number>("observations_scored", group),
  /** The rate, back in the units it was measured in: how many of how many. */
  discriminating: {
    file: FILE.gate3,
    path: "discriminating_rate times observations_scored",
    value: gate3Rate * gate3Scored,
    display: group(gate3Rate * gate3Scored),
  } as Claim<number>,
  lowerBound: g3<number>("rate_lower_bound_95", fixed(2)),
  threshold: g3<number>("threshold", fixed(2)),
  notTestable: g3<number>("observations_not_testable", group),
  verdict: g3<string>("verdict", identity),
  groups: g3<number>("entity_grouping.groups_scored", group),
  groupedLowerBound: g3<number>(
    "entity_grouping.grouped_rate_lower_bound_95",
    fixed(2),
  ),
  /**
   * What the bound means, in the four states it can be in.
   *
   * This card used to end with the literal "That is not enough to clear it", written
   * when the bound was 0.37 and still on screen when the bound became 0.73 against the
   * same 0.70 bar. Every number around it was read from the receipt; the sentence
   * holding them was not, which is the only reason it could go wrong.
   */
  outcomeSentence: gate3OutcomeSentence(),
} as const;

// ---------------------------------------------------------------------------
// Beat 4. The lift, and the interval around it.
// ---------------------------------------------------------------------------

const CHRONO = "gate6.per_split.chronological";

export const lift = {
  number: q<number>("gate6.gate", group),
  wording: q<string>("gate6.wording", identity),
  decidedOn: q<string>("gate6.decided_on", identity),
  examined: q<number>(`${CHRONO}.n_queue_examined`, group),
  population: q<number>(`${CHRONO}.replay_episode.n_population`, group),
  queueConflicts: q<number>(`${CHRONO}.n_queue_conflicts`, group),
  randomConflicts: q<number>(`${CHRONO}.n_random_conflicts`, fixed(1)),
  fifoConflicts: q<number>(
    `${CHRONO}.replay_episode.orderings.fifo.n_conflicts_at_budget`,
    group,
  ),
  totalConflicts: q<number>(`${CHRONO}.replay_episode.n_total_conflicts`, group),
  point: q<number>(`${CHRONO}.lift_point`, fixed(2)),
  ciLow: q<number>(`${CHRONO}.lift_ci95[0]`, fixed(2)),
  ciHigh: q<number>(`${CHRONO}.lift_ci95[1]`, fixed(2)),
  fifoLift: q<number>(
    `${CHRONO}.replay_episode.orderings.fifo.lift_over_random`,
    fixed(2),
  ),
  threshold: {
    file: FILE.queue,
    path: "gate6.wording (the 1.5 the sentence names)",
    value: 1.5,
    display: "1.50",
  } as Claim<number>,
  bootstraps: q<number>(`${CHRONO}.n_boot`, group),
  groups: q<number>(`${CHRONO}.n_groups`, group),
  direction: q<string>(`${CHRONO}.direction`, identity),
  verdict: q<string>("gate6.verdict", identity),
  statement: q<string>("gate6.statement", identity),
} as const;

// ---------------------------------------------------------------------------
// Beat 5. The gates, as they came back.
// ---------------------------------------------------------------------------

type Gate = { gate: number; title: string; verdict: string; decided_in: string };

const gateList = resolve(provenance, "gate_summary.gates") as Gate[];
const measured = gateList.filter((row) => row.verdict !== "PRE_PASSED");

export const gates = {
  rows: gateList.map((row, i) => ({
    number: pv<number>(`gate_summary.gates[${i}].gate`, group),
    title: pv<string>(`gate_summary.gates[${i}].title`, identity),
    verdict: pv<string>(`gate_summary.gates[${i}].verdict`, identity),
    decidedIn: pv<string>(`gate_summary.gates[${i}].decided_in`, identity),
  })),
  total: pv<number>("gate_summary.n_gates", group),
  met: pv<number>("gate_summary.n_met", group),
  note: pv<string>("gate_summary.note", firstSentence),
  /** Derived: the gates that were measured rather than answered up front. */
  measured: {
    file: FILE.provenance,
    path: "gate_summary.gates[] where verdict is not PRE_PASSED",
    value: measured.length,
    display: group(measured.length),
  } as Claim<number>,
  measuredPassed: {
    file: FILE.provenance,
    path: "gate_summary.gates[] where verdict is not PRE_PASSED and verdict is PASSED",
    value: measured.filter((row) => row.verdict === "PASSED").length,
    display: group(measured.filter((row) => row.verdict === "PASSED").length),
  } as Claim<number>,
} as const;

// ---------------------------------------------------------------------------
// Beat 6. What came back established.
//
// The film measured the pre-registered gate and reported it inconclusive, which is
// the honest answer and is not the whole answer. Three results were measured the
// same way, on the same receipts, and came back decided. Leaving them out of the
// film while the console prints them is the kind of omission this project exists to
// argue against, so they are read here from their own receipts.
// ---------------------------------------------------------------------------

const COLD = "gate6.per_split.cold_station";

export const established = {
  model: ag<string>("model.name", identity),
  tasks: ag<number>("tasks", group),
  withTools: ag<number>("arms.tools.correct.successes", group),
  withoutTools: ag<number>("arms.control.correct.successes", group),
  trials: ag<number>("arms.tools.correct.trials", group),
  declinedWithout: ag<number>("arms.control.declined_unknown", group),
  discordant: ag<number>("paired.discordant_pairs", group),
  /**
   * One-sided exact p, printed to six places rather than in exponent form. The
   * display has to be a number a viewer can read off the frame without knowing what
   * "e-06" means, and the test that checks a display against its value parses digits.
   */
  pairedP: ag<number>("paired.exact_p_one_sided", fixed(6)),
  adversarialChecks: ex<number>("checker_sensitivity.adversarial_checks", group),
  adversarialCaught: ex<number>(
    "checker_sensitivity.caught_for_the_expected_reason",
    group,
  ),
  controlChecks: ex<number>("checker_sensitivity.control_checks", group),
  controlRefused: ex<number>("checker_sensitivity.control_refused", group),
  refusedOfDrafts: ex<number>("counts.refused", group),
  draftsDecided: ex<number>("counts.decided_by_the_checker", group),
  coldLift: q<number>(`${COLD}.lift_point`, fixed(2)),
  coldCiLow: q<number>(`${COLD}.lift_ci95[0]`, fixed(2)),
  coldCiHigh: q<number>(`${COLD}.lift_ci95[1]`, fixed(2)),
  coldVerdict: q<string>(`${COLD}.verdict`, identity),
  coldExamined: q<number>(`${COLD}.n_queue_examined`, group),
  coldStationGroups: q<number>(`${COLD}.n_station_groups`, group),
  /**
   * The interval printed here is the wider of two: this split is resampled by pass
   * episode and again by ground station, and the receipt governs on their union, so
   * the held-out claim is made against the more conservative of the two.
   */
  coldInterval: q<string>(`${COLD}.governing_interval`, identity),
} as const;

// ---------------------------------------------------------------------------
// The ceiling, shown under the gate tally.
//
// Most of the six gates read NOT_ESTABLISHED, and a tally alone does not say what
// the measurement was up against. No count here: the tally on screen is read from the
// receipts, and a second copy in a comment can only go stale. This one said four while
// three did, from the day gate 4 was answered. This is the quantity that explains it: on the
// pre-registered split, the budget and the number of conflicts in the population
// cap every possible ordering, a perfect oracle included, only slightly above the
// bar the gate asked for.
// ---------------------------------------------------------------------------

export const ceiling = {
  maxFindable: ci<number>("ceiling.max_findable_at_budget", group),
  lift: ci<number>("ceiling.lift", fixed(2)),
  threshold: ci<number>("ceiling.threshold", fixed(2)),
  headroom: ci<number>(
    "ceiling.headroom_between_threshold_and_perfection",
    fixed(2),
  ),
} as const;

// ---------------------------------------------------------------------------
// Provenance, shown in the film's own footer.
// ---------------------------------------------------------------------------

export const provenanceLine = {
  snapshot: pv<string>("snapshot_id", identity),
  splitSha: pv<string>("split_manifest_sha256", (s) => s.slice(0, 12)),
  attribution: cd<string>("attribution", identity),
} as const;

// ---------------------------------------------------------------------------
// The colophon. Showing a SatNOGS waterfall carries six obligations under
// DATA_LICENSE.md, and the repository already audits them per file. The film
// reads its own asset's audit row rather than restating any of it.
// ---------------------------------------------------------------------------

const IMAGE_FILE = `apps/web/public/waterfalls/${HERO_OBS_ID}.webp`;
const auditRows = resolve(attribution, "rows") as { file: string }[];
const auditIndex = auditRows.findIndex((row) => row.file === IMAGE_FILE);
if (auditIndex === -1) {
  throw new Error(`ATTRIBUTION_AUDIT.json has no row for ${IMAGE_FILE}`);
}
const ROW = `rows[${auditIndex}]`;

export const colophon = {
  file: at<string>(`${ROW}.file`, identity),
  recordUrl: at<string>(`${ROW}.source_url`, identity),
  artifactUrl: at<string>(`${ROW}.waterfall_url`, identity),
  retrievedAt: at<string>(`${ROW}.retrieved_at`, identity),
  sha256: at<string>(`${ROW}.source_sha256`, identity),
  licence: at<string>(`${ROW}.license`, identity),
  licenceUrl: at<string>(`${ROW}.license_url`, identity),
  modification: at<string>(`${ROW}.modification_notice`, identity),
  station: at<number>(`${ROW}.ground_station`, identifier),
  obligationsSource: at<string>("obligations_source", identity),
  // The voice, from the narration receipt rather than typed into the card. A film with a
  // synthetic narrator that does not say so is asking a viewer to notice and wonder, and
  // this project's whole argument is that a published fact names the file it came from.
  // The three fields are the model, its licence, and what the transcription check found,
  // so the disclosure carries its own evidence instead of a reassurance.
  voiceModel: na<string>("renderer.model", identity),
  voiceLicence: na<string>("renderer.licence", identity),
  figuresHeard: na<number>("totals.figures_checked", identifier),
} as const;

// ---------------------------------------------------------------------------
// The session an agent actually ran, and what IBM Bob built.
//
// `artifacts/OPERATOR_SESSION.json` is the twelve steps of docs/BOB_DEMO.md driven
// over stdio against both servers and recorded call by call. Every string the session
// card puts on screen is a field of that receipt, including the sentence the checker
// refused and the one it accepted, so the demo in the film is the demo that ran rather
// than a screenshot of one.
// ---------------------------------------------------------------------------

/** Index of a step inside `frozen.steps` or `live.steps`, by its recorded step number. */
const stepAt = (section: "frozen" | "live", step: number): number => {
  const steps = resolve(session, `${section}.steps`) as { step: number }[];
  const at = steps.findIndex((s) => s.step === step);
  if (at < 0) throw new Error(`${section} has no step ${step}`);
  return at;
};

const REFUSED_AT = stepAt("frozen", 5);
const GROUNDED_AT = stepAt("frozen", 6);
const TOOLS_AT = stepAt("frozen", 1);
const LIVE_TOOLS_AT = stepAt("live", 2);

export const agentSession = {
  evidenceTools: se<number>(`frozen.steps[${TOOLS_AT}].reported.n_tools`, identifier),
  liveTools: se<number>(`live.steps[${LIVE_TOOLS_AT}].reported.n_tools`, identifier),
  stepsRun: se<number>("summary.n_steps", identifier),
  stepsMet: se<number>("summary.n_met", identifier),
  refusedText: se<string>(`frozen.steps[${REFUSED_AT}].reported.text`, identity),
  refusedVerdict: se<string>(`frozen.steps[${REFUSED_AT}].reported.verdict`, identity),
  refusedCode: se<string[]>(
    `frozen.steps[${REFUSED_AT}].reported.codes`,
    (codes) => codes[0],
  ),
  groundedText: se<string>(`frozen.steps[${GROUNDED_AT}].reported.text`, identity),
  groundedVerdict: se<string>(`frozen.steps[${GROUNDED_AT}].reported.verdict`, identity),
  liveToolNames: se<string[]>(
    `live.steps[${LIVE_TOOLS_AT}].reported.tools`,
    (names) => names.join("  "),
  ),
} as const;

export const bobUnits = {
  count: bo<number>("n_bob_units", identifier),
  source: bo<string>("source", identity),
  rows: (resolve(bob, "units") as { unit: string }[]).map((_, i) => ({
    unit: bo<string>(`units[${i}].unit`, identity),
    subject: bo<string>(`units[${i}].subject`, identity),
    files: bo<string[]>(`units[${i}].files`, (f) => String(f.length)),
  })),
} as const;

/**
 * The one filmed take. Left of the card is a screen recording of the deployed console
 * measuring an observation; right of it is what came back beside what this repository
 * already held for the same observation, so a viewer can see the two columns are the
 * same digits rather than take the word of a voice-over.
 *
 * The displays are bare numbers, including the two playback rates, because a claim's
 * display is the figure and the unit belongs to whatever draws it. A satellite name
 * arrives from the API with its catalogue zero in front of it, which is the record's
 * numbering rather than part of the name.
 */
const withoutCatalogueZero = (s: string): string => s.replace(/^0\s+/, "");

export const liveTake = {
  obsId: tk<number>("observation.id", identifier),
  satellite: tk<string>("observation.satellite", withoutCatalogueZero),
  recorded: tk<string>("observation.start", identity),
  verdict: tk<string>("measured_live.verdict", identity),
  offsetPpm: tk<number>("measured_live.offset_ppm", signedFixed(2)),
  fitSigma: tk<number>("measured_live.fit_sigma", fixed(2)),
  detectFrac: tk<number>("measured_live.detect_frac", fixed(3)),
  pValue: tk<number>("measured_live.p_value", fixed(3)),
  nulls: tk<number>("measured_live.nulls_n", identifier),
  heldOffsetPpm: tk<number>(
    "committed.corridor_features.fitted_offset_ppm",
    signedFixed(2),
  ),
  heldFitSigma: tk<number>("committed.corridor_features.sigma_curved", fixed(2)),
  heldDetectFrac: tk<number>(
    "committed.corridor_features.detect_frac_curved",
    fixed(3),
  ),
  compared: tk<number>("agreement.n_compared", identifier),
  exact: tk<number>("agreement.n_exact", identifier),
  differs: tk<number>("agreement.n_differs", identifier),
  takes: tk<number>("take.edit.takes", identifier),
  rateFirst: tk<number>("take.edit.rate_before_handover", identifier),
  rateSecond: tk<number>("take.edit.rate_after_handover", identifier),
  seconds: tk<number>("take.video.seconds", fixed(1)),
} as const;

// ---------------------------------------------------------------------------
// The cold open. One real pass, named, before any of the argument starts.
//
// Nothing new is measured here. Every field is the hero observation's own record,
// already resolved above for the physics card, re-read under names that say what the
// opening shot is doing with them: this is a real capture, by a real station, on a
// real night, and the network's verdict for it is two words.
// ---------------------------------------------------------------------------

const passSeconds =
  (Date.parse(resolve(cards, `${CARD}.end`) as string) -
    Date.parse(resolve(cards, `${CARD}.start`) as string)) /
  1000;

export const coldOpen = {
  /**
   * How long the pass ran, from the record's own two timestamps.
   *
   * The only claim this block adds. Everything else the opening card draws is the hero
   * observation's own record, and the card reads it from `physics` directly rather than
   * through an alias here: a second name for a claim is a second claim as far as the
   * registry is concerned, and `test/claims.test.ts` walks the registry.
   */
  passMinutes: {
    file: FILE.cards,
    path: `${CARD}.end - ${CARD}.start, in minutes`,
    value: Math.round(passSeconds / 60),
    display: String(Math.round(passSeconds / 60)),
  } as Claim<number>,
} as const;

// ---------------------------------------------------------------------------
// The flow, running, and the model getting it wrong on camera.
//
// This receipt is the one place in the repository where a generated answer is
// published beside the fact it was supposed to carry and does not. The film shows
// that rather than hiding it, because the refusal in the next shot is only worth
// anything if the failure it catches is real and on screen.
// ---------------------------------------------------------------------------

export const flow = {
  version: lf<string>("runtime.langflow", identity),
  model: lf<string>("flows.granite_agent.model", identity),
  endpoint: lf<string>("flows.granite_agent.endpoint", identity),
  outcome: lf<string>("flows.granite_agent.outcome", identity),
  question: lf<string>("flows.granite_agent.question", identity),
  answer: lf<string>("flows.granite_agent.answer", identity),
  trueObsId: lf<string>("flows.granite_agent.expected_observation_id", identity),
  /** The id the model returned, read out of the JSON it actually produced. */
  inventedObsId: {
    file: FILE.langflow,
    path: "flows.granite_agent.answer, observation_id",
    value: Number(
      JSON.parse(resolve(langflow, "flows.granite_agent.answer") as string)
        .observation_id,
    ),
    display: String(
      JSON.parse(resolve(langflow, "flows.granite_agent.answer") as string)
        .observation_id,
    ),
  } as Claim<number>,
  inventedReason: {
    file: FILE.langflow,
    path: "flows.granite_agent.answer, reason",
    value: JSON.parse(resolve(langflow, "flows.granite_agent.answer") as string)
      .reason as string,
    display: JSON.parse(resolve(langflow, "flows.granite_agent.answer") as string)
      .reason as string,
  } as Claim<string>,
  groundedVerdict: lf<string>("flows.grounding.runs[0].verdict", identity),
  groundedInput: lf<string>("flows.grounding.runs[0].input", identity),
  refusedVerdict: lf<string>("flows.grounding.runs[1].verdict", identity),
  refusedInput: lf<string>("flows.grounding.runs[1].input", identity),
  refusedCode: lf<string>("flows.grounding.runs[1].codes[0]", identity),
  agentNodes: {
    file: FILE.langflow,
    path: "flows.granite_agent.nodes, length",
    value: (resolve(langflow, "flows.granite_agent.nodes") as string[]).length,
    display: String(
      (resolve(langflow, "flows.granite_agent.nodes") as string[]).length,
    ),
  } as Claim<number>,
  notMeasured: lf<string>("what_this_does_not_measure", firstSentence),
} as const;

/** Everything above, flattened, for the test to walk. */
export const ALL_CLAIMS: Record<string, Claim<unknown>> = {};
const collect = (prefix: string, node: unknown): void => {
  if (node === null || typeof node !== "object") return;
  const record = node as Record<string, unknown>;
  if (
    typeof record.file === "string" &&
    typeof record.path === "string" &&
    typeof record.display === "string" &&
    "value" in record
  ) {
    ALL_CLAIMS[prefix] = record as unknown as Claim<unknown>;
    return;
  }
  for (const [key, child] of Object.entries(record)) {
    collect(prefix ? `${prefix}.${key}` : key, child);
  }
};
collect("corpus", corpus);
collect("reviewQueue", reviewQueue);
collect("physics", physics);
collect("gate3Result", gate3Result);
collect("lift", lift);
collect("gates", gates);
collect("established", established);
collect("ceiling", ceiling);
collect("provenanceLine", provenanceLine);
collect("colophon", colophon);
collect("agentSession", agentSession);
collect("bobUnits", bobUnits);
collect("liveTake", liveTake);
collect("coldOpen", coldOpen);
collect("flow", flow);
