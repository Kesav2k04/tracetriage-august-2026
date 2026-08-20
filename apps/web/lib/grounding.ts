/**
 * The grounding checker, in the browser.
 *
 * `pipeline/tracetriage/explain.py` decides whether a generated reviewer note may ship.
 * It runs offline, at pipeline time, over the drafts a local model wrote. A judge reading
 * the console cannot run it: the export is static, there is no server, and the interesting
 * question ("what happens if I change one digit?") needs the checker where the reader is.
 * So it is ported here, and the port is only worth having if it agrees with the original.
 *
 * `public/data/grounding_golden.json` is what makes that agreement checkable rather than
 * asserted. It carries every draft/observation pair the Python checker was run over, with
 * the violations it produced. `tests/grounding.test.ts` replays those rows through this
 * module and `tests/test_grounding_parity.py` regenerates the file from the current Python
 * source, so a change to either implementation that the other does not follow fails a test
 * instead of shipping two checkers that disagree about the same sentence.
 *
 * Python and JavaScript do not agree about numbers or about regular expressions, and the
 * places where they disagree are all load-bearing here. Each one is handled at its call
 * site and named there. The three that would have silently changed a verdict:
 *
 *   - `round(x, n)` and `f"{x:.nf}"` in Python round half to even on the exact binary
 *     value of the double. `Number.prototype.toFixed` rounds half away from zero. So
 *     Python prints 0.125 to two places as "0.12" and JavaScript prints "0.13", which
 *     changes what the packet says and therefore what the checker grounds. `fixedDigits`
 *     below reimplements Python's rounding exactly, in BigInt.
 *   - `re.M` anchors `^` after "\n" only; the JavaScript `m` flag also anchors after
 *     "\r" and two Unicode separators.
 *   - `len(s)` counts code points and `s.length` counts UTF-16 code units.
 *
 * Nothing here reaches the DOM, the network or any dependency. It is the same closed world
 * the Python module describes: a packet of printed facts, and a draft that has to trace
 * back to it.
 */

/** Version of the prompt contract, carried so a note's receipt can name it. */
export const PROMPT_VERSION = "e1.2";

/** The label vocabulary SatNOGS uses. A draft may name one only if the packet does. */
export const LABEL_VALUES = ["with-signal", "without-signal", "unknown"] as const;

/**
 * The derived forms a draft may write that the packet does not print, each bound to the
 * fields it applies to. Named here so they are rules rather than exceptions buried in a
 * branch, and scoped by field so the arithmetic cannot be borrowed by an unrelated value:
 * dividing any number by a million would let a frequency justify a sigma.
 */
export const ALLOWED_TRANSFORMS = [
  "a frequency in hertz written as megahertz, for fields ending in _hz",
  "a frequency in hertz written as kilohertz, for fields ending in _hz",
  "a value on the unit interval written as a percentage, for the listed fields only",
] as const;

/** Fields whose value is a probability or a fraction, so a percentage is the same number. */
const UNIT_INTERVAL_FIELDS: ReadonlySet<string> = new Set([
  "model_probability",
  "ensemble_uncertainty",
  "flat_row_fraction",
  "closest_approach_fraction",
  "queue_score",
  "axis_derivation_confidence",
]);

/**
 * Claims outside what this system is permitted to state. The wording comes from the
 * permission contract: no confirmed identity, no decoded telemetry, no mission outcome,
 * no endorsement, and no instruction to act on the public network.
 */
const OVERCLAIM_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bdecod(?:e|ed|es|ing)\b/, "decoding"],
  [/\btelemetry\b/, "telemetry"],
  [/\bprove[sn]?\b|\bproof\b/, "proof"],
  [/\bmission (?:success|failure)\b/, "mission outcome"],
  [/\bendorse[sd]?\b|\bendorsement\b/, "endorsement"],
  [/\bvote\b|\bvoting\b/, "voting on the public network"],
  [/\bupload\b|\bsubmit to\b|\breport to satnogs\b/, "writing to the public network"],
  [/\bwas heard\b|\bwas detected\b|\bis a detection\b/, "an asserted detection"],
];

/** Absolutes a four-sentence note about one observation cannot support. */
const ABSOLUTE_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\balways\b/, "always"],
  [/\bnever\b/, "never"],
  [/\bimpossible\b/, "impossible"],
  [/\bguarantee[sd]?\b/, "guarantee"],
  [/\bcertainly\b|\bdefinitely\b|\bundoubtedly\b/, "certainty"],
];

/**
 * A note is for a reviewer, not a chat partner. Case matters for the first-person pronoun
 * and nowhere else, so it is checked against the unlowered draft.
 */
const FIRST_PERSON_RE = /\bI\b|\bI'm\b|\bI've\b/;

/**
 * Python anchors `^` after "\n" alone under `re.M`. The JavaScript `m` flag also anchors
 * after "\r", U+2028 and U+2029, so a draft whose heading followed a bare carriage return
 * would be refused here and passed by the pipeline. Splitting on "\n" and testing each
 * piece from its own index 0 puts both checkers on the same line boundaries.
 */
function usesMarkdownHeading(lowered: string): boolean {
  return lowered.split("\n").some((line) => /^#{1,6}\s/.test(line));
}

const VOICE_PATTERNS: ReadonlyArray<{
  readonly matches: (lowered: string) => boolean;
  readonly name: string;
}> = [
  { matches: (s) => /\bmy\b|\bmine\b|\bwe think\b/.test(s), name: "first person" },
  { matches: (s) => /\bas an ai\b|\blanguage model\b/.test(s), name: "self-reference" },
  { matches: (s) => /https?:\/\//.test(s), name: "a URL" },
  { matches: usesMarkdownHeading, name: "a markdown heading" },
];

/**
 * Upper bounds. Four sentences was the instruction; five is the tolerance before the note
 * stops being a note.
 */
export const MAX_CHARS = 700;
export const MAX_SENTENCES = 5;

/**
 * Words that turn the bare verb, the gerund or the noun into a proposed action rather than
 * an assertion. The contract forbids claiming a confirmed detection or identity. It does
 * not forbid telling a reviewer what would settle the question, which is the third thing
 * the prompt asks the note to cover, so a single pattern on the verb stem was broader than
 * the rule it implements: it refused "to confirm this, look for a signal" in eight of
 * twenty-five drafts.
 */
const CONFIRM_ALLOWED_BEFORE: ReadonlySet<string> = new Set([
  // modals and the infinitive marker: a proposed action
  "to",
  "would",
  "could",
  "might",
  "should",
  "cannot",
  "not",
  // the two verbs and one preposition that were observed introducing a nominalised action
  // in real drafts, and nothing beyond them.
  "by",
  "help",
  "helps",
  "involve",
  "involves",
]);

/**
 * The indicative and the participle assert on their own, whatever precedes them, so the
 * preceding word is only consulted for the bare verb, the gerund and the noun.
 */
const CONFIRM_ALWAYS_RE = /\bconfirms\b|\bconfirmed\b/;
const CONFIRM_RE = /\bconfirm\b|\bconfirming\b|\bconfirmation\b/g;
const PRECEDING_WORD_RE = /(\w+)\W*$/;

/**
 * Python's `\w` and `\b` are Unicode-aware on a `str`; JavaScript's are ASCII plus the
 * underscore. Every draft this checker has ever seen is ASCII, so the two agree on the
 * corpus, and the golden fixture is what would catch it if a draft stopped being ASCII.
 * The one place the difference was worth closing rather than noting is the label lookaround
 * below, where a Unicode property escape costs nothing.
 */
const NUMBER_RE = /[-+]?\d[\d,]*(?:\.\d+)?/g;
const CODE_RE = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g;
const SENTENCE_RE = /[.!?](?:\s|$)/g;

/**
 * The corridor fields a note is allowed to talk about, and therefore the fields whose
 * absence makes a note impossible rather than shorter.
 *
 * The console export refused a missing fit already and the packet builder did not: it read
 * the same block with a default of 0.0, so an observation with no fit produced a packet
 * claiming a fitted offset of 0 Hz, a half width of 0 Hz and closest approach at the first
 * sample. Every one of those is a measurement the pipeline never took, and because they
 * were in the packet the grounding checker would have accepted a note quoting them.
 */
const REQUIRED_CORRIDOR_FIELDS = [
  "max_elevation_deg",
  "tca_frac",
  "fitted_offset_hz",
  "fitted_offset_ppm",
  "half_width_hz",
  "sigma_curved",
  "sigma_vertical",
] as const;

/**
 * Raised when a card carries no fit, so no packet can be built from it.
 *
 * A named error rather than a bare `Error` because every caller has to make the same
 * decision and the decision is not "crash": degraded cards are shipped on purpose, and a
 * card that cannot become a packet is a different receipt line from a draft the checker
 * refused. `MeasurementMissing` in the Python module, and the name is checked rather than
 * the class so it survives a bundler that duplicates the module.
 */
export class MeasurementMissing extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MeasurementMissing";
  }
}

/**
 * Raised when a field the packet prints with Python's `str()` is not an integer.
 *
 * Python prints a float as "436490000.0" and switches to exponent notation at a different
 * magnitude than JavaScript does, so a float arriving in one of these fields would make the
 * two packets differ by a trailing ".0" and quietly move every number token that follows.
 * Refusing is the honest answer: guessing which of the two spellings the pipeline meant is
 * how a formatting difference becomes a grounding difference.
 */
export class NotAnInteger extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotAnInteger";
  }
}

/** The console card fields a packet is built from. A subset of `Card & CardMeasurements`. */
export interface GroundingCard {
  obs_id: number;
  start: string | null;
  end: string | null;
  hz_per_px: number;
  seconds_per_px: number;
  derivation: string | null;
  derivation_confidence: number | null;
  rx_freq_hz: number | null;
  ground_station: number | null;
  station_name: string | null;
  norad_cat_id: number | null;
  transmitter_mode: string | null;
  waterfall_status: string | null;
  corridor: GroundingCorridor | null;
}

export interface GroundingCorridor {
  max_elevation_deg: number | null;
  tca_frac: number | null;
  fitted_offset_hz: number | null;
  fitted_offset_ppm: number | null;
  half_width_hz: number | null;
  sigma_curved: number | null;
  sigma_vertical: number | null;
  offset_at_bound?: boolean | null;
}

/** The queue row fields a packet is built from. A subset of `QueueEntry`. */
export interface GroundingEntry {
  obs_id: number;
  rank: number;
  score: number;
  model_prob: number | null;
  ensemble_uncertainty: number | null;
  flat_row_frac: number | null;
  reasons?: readonly string[] | null;
}

/**
 * What the model is shown: field name to formatted value, in the order the packet prints
 * them. Named keys rather than an index signature so a typo in a consumer is a compile
 * error and the packet's shape is readable without running it.
 */
export interface PrintedFields {
  observation_id: string;
  ground_station_id: string;
  ground_station_name: string;
  norad_catalogue_id: string;
  transmitter_mode: string;
  receiver_frequency_hz: string;
  network_label: string;
  pass_duration_s: string;
  max_elevation_deg: string;
  closest_approach_fraction: string;
  fitted_offset_hz: string;
  fitted_offset_ppm: string;
  corridor_half_width_hz: string;
  sigma_curved: string;
  sigma_vertical: string;
  hz_per_pixel: string;
  seconds_per_pixel: string;
  axis_derivation: string;
  axis_derivation_confidence: string;
  model_probability: string;
  ensemble_uncertainty: string;
  flat_row_fraction: string;
  queue_rank: string;
  queue_score: string;
  queue_reason_codes: string;
  offset_at_bound: string;
}

/** The unrounded values, so the checker can accept a draft that printed one to fewer digits. */
export interface ExactFields {
  queue_rank: number;
  queue_score: number;
  model_probability: number;
  ensemble_uncertainty: number;
  flat_row_fraction: number;
  pass_duration_s: number;
  max_elevation_deg: number;
  closest_approach_fraction: number;
  fitted_offset_hz: number;
  fitted_offset_ppm: number;
  corridor_half_width_hz: number;
  sigma_curved: number;
  sigma_vertical: number;
  hz_per_pixel: number;
  seconds_per_pixel: number;
  axis_derivation_confidence: number;
  receiver_frequency_hz: number;
  norad_catalogue_id: number;
  ground_station_id: number;
  observation_id: number;
}

/**
 * Every fact a note may use, and nothing else.
 *
 * `text` and `numberTokens` are derived from `printed` and carried rather than recomputed
 * so a packet cannot be handed around in a state where its rendered text disagrees with
 * its field map. Build one with `buildPacket` or, for a hand-made packet, `finalisePacket`.
 */
export interface EvidencePacket {
  readonly obsId: number;
  readonly printed: Readonly<PrintedFields>;
  readonly exact: Readonly<ExactFields>;
  readonly vocabulary: ReadonlySet<string>;
  /** What `EvidencePacket.as_text()` renders in Python, byte for byte. */
  readonly text: string;
  /** Every numeric token in `text`, as a token and not as a substring. */
  readonly numberTokens: ReadonlySet<string>;
}

/** One reason a draft may not ship. */
export interface Violation {
  code: string;
  detail: string;
  literal?: string;
  unit?: string;
}

/** The checker's decision about one draft, with every reason it reached it. */
export interface Verification {
  ok: boolean;
  violations: Violation[];
  /** The distinct codes, sorted. Both implementations sort ASCII, so the order agrees. */
  codes: string[];
}

// --------------------------------------------------------------------------------------
// Python's number formatting, exactly.
// --------------------------------------------------------------------------------------

/**
 * A finite double as `mantissa * 2 ** exponent`, both integers.
 *
 * The decomposition is exact, which is the point: the decimal a double rounds to depends on
 * the double's full binary value, and 2.675 is really 2.67499999999999982... A routine that
 * works from the shortest decimal repr instead would round it up and disagree with Python.
 */
function decompose(x: number): { negative: boolean; mantissa: bigint; exponent: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const negative = (hi & 0x80000000) !== 0;
  const biased = (hi >>> 20) & 0x7ff;
  const fraction = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  // A subnormal has no implicit leading bit and a fixed exponent.
  if (biased === 0) return { negative, mantissa: fraction, exponent: -1074 };
  return { negative, mantissa: fraction | (1n << 52n), exponent: biased - 1075 };
}

/**
 * `f"{x:.{places}f}"`, including the rounding rule.
 *
 * CPython formats a float by asking David Gay's `dtoa` for the correctly rounded decimal,
 * which breaks a tie by rounding to even. `toFixed` breaks a tie away from zero. The cases
 * that differ are the ones a packet is full of: 0.125 to two places, 2.5 to none, 1.25 to
 * one. Getting this wrong changes `printed`, which changes the token set, which changes
 * which drafts are grounded, so it is done in BigInt on the exact value rather than in
 * floating point.
 *
 * Non-finite input returns Python's spelling of it. JSON cannot carry either, so this is a
 * guard against a computed field rather than a case the fixture exercises.
 */
export function fixedDigits(x: number, places: number): string {
  if (Number.isNaN(x)) return "nan";
  if (!Number.isFinite(x)) return x > 0 ? "inf" : "-inf";

  const { negative, mantissa, exponent } = decompose(x);
  const scale = 10n ** BigInt(places);
  let scaled: bigint;
  if (exponent >= 0) {
    // An integral double. Nothing to round.
    scaled = mantissa * (1n << BigInt(exponent)) * scale;
  } else {
    const denominator = 1n << BigInt(-exponent);
    const numerator = mantissa * scale;
    const quotient = numerator / denominator;
    const remainder = numerator % denominator;
    const doubled = remainder * 2n;
    // Half to even, on the exact value. This is the whole difference from toFixed.
    scaled =
      doubled > denominator || (doubled === denominator && (quotient & 1n) === 1n)
        ? quotient + 1n
        : quotient;
  }

  let digits = scaled.toString();
  if (places > 0) {
    if (digits.length <= places) digits = digits.padStart(places + 1, "0");
    const split = digits.length - places;
    digits = `${digits.slice(0, split)}.${digits.slice(split)}`;
  }
  // Python keeps the sign of a negative that rounds to zero: format(-0.5, ".0f") is "-0".
  return negative ? `-${digits}` : digits;
}

/**
 * `round(x, places)`.
 *
 * CPython rounds a float by formatting it to `places` decimals and reading the result back,
 * so the returned double is the nearest one to that decimal. Doing the same here means the
 * comparison in `groundedNumber` is between the same two doubles on both sides.
 */
export function pyRound(x: number, places: number): number {
  if (!Number.isFinite(x)) return x;
  return Number(fixedDigits(x, places));
}

/** `int(round(x))`: half to even at the tie, and the result is already integral. */
function pyRoundToInt(x: number): number {
  return Math.trunc(pyRound(x, 0));
}

/**
 * `str(value)` for a field the packet prints without formatting.
 *
 * `null` prints as "None" because that is what Python's `str()` does, and a packet that
 * silently printed "null" instead would be a different closed world. A non-integer number
 * is refused rather than guessed; `NotAnInteger` says why.
 */
function pyStr(value: string | number | null | undefined, field: string): string {
  if (value === undefined) {
    throw new NotAnInteger(
      `card field ${field} is absent. Python would raise KeyError here rather than print ` +
        `a placeholder into the packet.`,
    );
  }
  if (value === null) return "None";
  if (typeof value === "number") {
    if (!Number.isInteger(value)) {
      throw new NotAnInteger(
        `card field ${field} is ${value}, which Python would print with a trailing ".0". ` +
          `The packet has to be byte-identical in both checkers, so this is refused ` +
          `rather than spelled one of the two ways.`,
      );
    }
    return String(value);
  }
  return value;
}

/**
 * `float(value)`, with the field named so a null reads as a missing measurement.
 *
 * Python raises `TypeError` on `float(None)` for the queue fields and `MeasurementMissing`
 * for the corridor fields. The type differs, the outcome does not: neither produces a
 * packet. One named error covers both here so a caller has one thing to catch, and the
 * message says which field was absent, which the `TypeError` did not.
 */
function pyFloat(value: number | null | undefined, field: string): number {
  if (value === null || value === undefined) {
    throw new MeasurementMissing(
      `${field} is absent, so there is no measurement to print. The packet is a closed ` +
        `world: a default here would be published as a number nobody measured.`,
    );
  }
  return value;
}

// --------------------------------------------------------------------------------------
// The packet.
// --------------------------------------------------------------------------------------

/** `EvidencePacket.as_text()`: the field map padded to a column, one field per line. */
export function renderPacketText(printed: Readonly<PrintedFields>): string {
  const entries = Object.entries(printed) as Array<[string, string]>;
  const width = Math.max(...entries.map(([key]) => key.length));
  return entries.map(([key, value]) => `${key.padEnd(width)} : ${value}`).join("\n");
}

function numberTokensOf(text: string): ReadonlySet<string> {
  return new Set(Array.from(text.matchAll(NUMBER_RE), (m) => m[0]));
}

/**
 * Finish a packet: render its text and tokenise it.
 *
 * Exported for a hand-built packet in a test or a fixture. Every packet goes through here,
 * so `text` and `numberTokens` can never be stale with respect to `printed`.
 */
export function finalisePacket(
  obsId: number,
  printed: Readonly<PrintedFields>,
  exact: Readonly<ExactFields>,
  vocabulary: Iterable<string>,
): EvidencePacket {
  const text = renderPacketText(printed);
  return {
    obsId,
    printed,
    exact,
    vocabulary: new Set(Array.from(vocabulary).filter((v) => v)),
    text,
    numberTokens: numberTokensOf(text),
  };
}

/**
 * Assemble the closed world for one observation.
 *
 * `card` is an entry from the console's `cards.json` and `entry` is the matching row of
 * `queue.json`, which is the same pair the Python builder takes. Both ship in the export,
 * so a packet is reproducible in the browser from committed data.
 */
export function buildPacket(card: GroundingCard, entry: GroundingEntry): EvidencePacket {
  if (card.obs_id !== entry.obs_id) {
    throw new Error(
      `card ${card.obs_id} paired with queue entry ${entry.obs_id}. A note assembled from ` +
        `two observations would be grounded in neither.`,
    );
  }

  const corridor: Partial<GroundingCorridor> = card.corridor ?? {};
  const missing = REQUIRED_CORRIDOR_FIELDS.filter(
    (name) => corridor[name] === null || corridor[name] === undefined,
  );
  if (missing.length > 0) {
    throw new MeasurementMissing(
      `observation ${card.obs_id} has no ${missing.join(", ")} in its corridor block, so ` +
        `there is no fit to write a note about. The packet is a closed world: a default of ` +
        `0.0 here would print 'the corridor sits 0 Hz from the catalogue centre' as a ` +
        `measurement, and the checker would ground it.`,
    );
  }

  const durationS = passDurationSeconds(card);

  const exact: ExactFields = {
    queue_rank: entry.rank,
    queue_score: entry.score,
    model_probability: pyFloat(entry.model_prob, "model_prob"),
    ensemble_uncertainty: pyFloat(entry.ensemble_uncertainty, "ensemble_uncertainty"),
    flat_row_fraction: pyFloat(entry.flat_row_frac, "flat_row_frac"),
    pass_duration_s: durationS,
    // Indexed, not defaulted. The guard above has already refused a card missing any of
    // these, so a hole here would be a bug in the guard rather than a missing measurement.
    max_elevation_deg: pyFloat(corridor.max_elevation_deg, "max_elevation_deg"),
    closest_approach_fraction: pyFloat(corridor.tca_frac, "tca_frac"),
    fitted_offset_hz: pyFloat(corridor.fitted_offset_hz, "fitted_offset_hz"),
    fitted_offset_ppm: pyFloat(corridor.fitted_offset_ppm, "fitted_offset_ppm"),
    corridor_half_width_hz: pyFloat(corridor.half_width_hz, "half_width_hz"),
    sigma_curved: pyFloat(corridor.sigma_curved, "sigma_curved"),
    sigma_vertical: pyFloat(corridor.sigma_vertical, "sigma_vertical"),
    hz_per_pixel: pyFloat(card.hz_per_px, "hz_per_px"),
    seconds_per_pixel: pyFloat(card.seconds_per_px, "seconds_per_px"),
    axis_derivation_confidence: pyFloat(card.derivation_confidence, "derivation_confidence"),
    receiver_frequency_hz: pyFloat(card.rx_freq_hz, "rx_freq_hz"),
    norad_catalogue_id: pyFloat(card.norad_cat_id, "norad_cat_id"),
    ground_station_id: pyFloat(card.ground_station, "ground_station"),
    observation_id: card.obs_id,
  };

  // Declaration order is the print order, and `Object.entries` preserves it for string
  // keys, so this renders in the same sequence as the Python dict.
  const printed: PrintedFields = {
    observation_id: pyStr(card.obs_id, "obs_id"),
    ground_station_id: pyStr(card.ground_station, "ground_station"),
    ground_station_name: pyStr(card.station_name, "station_name"),
    norad_catalogue_id: pyStr(card.norad_cat_id, "norad_cat_id"),
    transmitter_mode: pyStr(card.transmitter_mode, "transmitter_mode"),
    receiver_frequency_hz: pyStr(card.rx_freq_hz, "rx_freq_hz"),
    network_label: pyStr(card.waterfall_status, "waterfall_status"),
    pass_duration_s: fixedDigits(durationS, 0),
    max_elevation_deg: fixedDigits(exact.max_elevation_deg, 1),
    closest_approach_fraction: fixedDigits(exact.closest_approach_fraction, 2),
    fitted_offset_hz: fixedDigits(exact.fitted_offset_hz, 0),
    fitted_offset_ppm: fixedDigits(exact.fitted_offset_ppm, 1),
    corridor_half_width_hz: fixedDigits(exact.corridor_half_width_hz, 0),
    sigma_curved: fixedDigits(exact.sigma_curved, 1),
    sigma_vertical: fixedDigits(exact.sigma_vertical, 1),
    hz_per_pixel: fixedDigits(exact.hz_per_pixel, 1),
    seconds_per_pixel: fixedDigits(exact.seconds_per_pixel, 2),
    axis_derivation: pyStr(card.derivation, "derivation"),
    axis_derivation_confidence: fixedDigits(exact.axis_derivation_confidence, 2),
    model_probability: fixedDigits(exact.model_probability, 3),
    ensemble_uncertainty: fixedDigits(exact.ensemble_uncertainty, 4),
    flat_row_fraction: fixedDigits(exact.flat_row_fraction, 2),
    queue_rank: pyStr(entry.rank, "rank"),
    queue_score: fixedDigits(exact.queue_score, 3),
    queue_reason_codes: (entry.reasons && entry.reasons.length > 0
      ? entry.reasons
      : ["none"]
    ).join(", "),
    // Python writes `str(bool(...)).lower()`, so "true" or "false". `String(Boolean(x))` is
    // already lower case, which is the one place JavaScript's spelling is the wanted one.
    offset_at_bound: String(Boolean(corridor.offset_at_bound ?? false)),
  };

  const vocabulary = [
    pyStr(card.station_name, "station_name"),
    pyStr(card.transmitter_mode, "transmitter_mode"),
    pyStr(card.waterfall_status, "waterfall_status"),
    pyStr(card.derivation, "derivation"),
    ...(entry.reasons ?? []),
  ];

  return finalisePacket(card.obs_id, printed, exact, vocabulary);
}

/**
 * The recorded pass length in seconds.
 *
 * The console writes whole-second UTC timestamps, so `Date` is exact here. It would not be
 * if a timestamp ever carried microseconds: `datetime` keeps them and `Date` truncates to
 * milliseconds, which would move `pass_duration_s` and every check that reads it. A
 * sub-millisecond component is therefore refused rather than rounded away.
 */
function passDurationSeconds(card: GroundingCard): number {
  const start = parseIsoUtc(card.start, "start", card.obs_id);
  const end = parseIsoUtc(card.end, "end", card.obs_id);
  return (end - start) / 1000;
}

function parseIsoUtc(value: string | null, field: string, obsId: number): number {
  if (value === null) {
    throw new MeasurementMissing(
      `observation ${obsId} has no ${field} time, so the pass has no length and a note ` +
        `cannot say where in it to look.`,
    );
  }
  const microseconds = /\.\d{4,}/.exec(value);
  if (microseconds) {
    throw new MeasurementMissing(
      `observation ${obsId} has ${field} ${value}, whose sub-millisecond part JavaScript ` +
        `Date truncates and Python datetime keeps. That would move pass_duration_s between ` +
        `the two checkers, so it is refused rather than rounded.`,
    );
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    throw new MeasurementMissing(
      `observation ${obsId} has an unparseable ${field} time ${JSON.stringify(value)}.`,
    );
  }
  return parsed;
}

/**
 * The note that ships when generation is refused or unavailable.
 *
 * Assembled by format string from the same packet, so the card is never empty and the
 * generated note is an improvement on something rather than the only option.
 */
export function deterministicNote(packet: EvidencePacket): string {
  const p = packet.printed;
  return (
    `Ranked ${p.queue_rank} with score ${p.queue_score}, flagged ${p.queue_reason_codes}. ` +
    `The network label is ${p.network_label} and the model probability is ` +
    `${p.model_probability}. The corridor sits ${p.fitted_offset_hz} Hz from the ` +
    `catalogue centre, ${p.fitted_offset_ppm} ppm, with a half width of ` +
    `${p.corridor_half_width_hz} Hz; the curved fit scores ${p.sigma_curved} ` +
    `against ${p.sigma_vertical} for a vertical line. Peak elevation was ` +
    `${p.max_elevation_deg} degrees at ${p.closest_approach_fraction} of the pass.`
  );
}

// --------------------------------------------------------------------------------------
// The checks.
// --------------------------------------------------------------------------------------

/**
 * Return the offending phrase if a draft claims something is confirmed.
 *
 * A purpose clause ("to confirm this, look for ...") proposes work for the reviewer. An
 * indicative ("this confirms a pass") states the thing the permission contract forbids
 * stating. Two rules, because one was not enough.
 */
export function assertsAConfirmation(lowered: string): string | null {
  const always = CONFIRM_ALWAYS_RE.exec(lowered);
  if (always) return always[0];
  for (const match of lowered.matchAll(CONFIRM_RE)) {
    const before = PRECEDING_WORD_RE.exec(lowered.slice(0, match.index));
    const previous = before ? (before[1] ?? "") : "";
    if (CONFIRM_ALLOWED_BEFORE.has(previous)) continue;
    return `${previous} ${match[0]}`.trim();
  }
  return null;
}

/**
 * The unit written immediately after a number, if it is one this checker knows.
 *
 * The alternation is split because a percent sign is not a word character, so a trailing
 * word boundary never matched after it and the percentage transform was unreachable: a
 * probability of 0.999999 written as "100%" was refused as ungrounded. Only the alphabetic
 * units carry the boundary, which is where it is needed to stop "Hz" matching inside a word.
 */
export function unitAfter(suffix: string): string | null {
  // `re.match` anchors at the start of the string, which is what the leading ^ is for.
  const match = /^\s*(?:(MHz|megahertz|kHz|kilohertz|Hz|hertz)\b|(%)|(percent)\b)/i.exec(
    suffix,
  );
  if (!match) return null;
  const unit = (match[1] || match[2] || match[3] || "").toLowerCase();
  const canonical: Record<string, string> = {
    megahertz: "mhz",
    kilohertz: "khz",
    hertz: "hz",
    percent: "%",
  };
  return canonical[unit] ?? unit;
}

/**
 * Is this numeric token traceable to the packet, in the unit the draft wrote it in?
 *
 * Three ways for a number to be grounded, in order of strength. First, it is one of the
 * packet's own printed tokens: token equality, not containment, because an earlier version
 * accepted a literal appearing anywhere in the rendered packet and a transposition of the
 * fitted offset passed on the digits inside the receiver frequency. Second, it equals a
 * packet value at the precision the draft printed it to. Third, it is one of the
 * conversions in `ALLOWED_TRANSFORMS` and the draft wrote the unit that conversion
 * produces; without the unit, dividing a frequency by a thousand grounded "6.9 MHz" for an
 * offset of 6904 Hz.
 */
export function groundedNumber(
  literal: string,
  suffix: string,
  packet: EvidencePacket,
): boolean {
  if (packet.numberTokens.has(literal)) return true;

  // Python's `lstrip("+")` removes every leading plus, not just one.
  const bare = literal.replace(/,/g, "").replace(/^\++/, "");
  const value = Number(bare);
  // `NUMBER_RE` always captures a digit, so `bare` is never the empty string that
  // `Number` would read as 0 and `float` would reject. The guard is here anyway because
  // this function is exported and a caller could hand it anything.
  if (bare === "" || !Number.isFinite(value)) return false;

  const dot = bare.indexOf(".");
  const places = dot === -1 ? 0 : bare.length - dot - 1;
  const target = pyRound(value, places);
  const unit = unitAfter(suffix);

  for (const [name, exact] of Object.entries(packet.exact) as Array<[string, number]>) {
    if (pyRound(exact, places) === target) return true;
    if (name.endsWith("_hz")) {
      if (unit === "mhz" && pyRound(exact / 1e6, places) === target) return true;
      if (unit === "khz" && pyRound(exact / 1e3, places) === target) return true;
    }
    if (
      UNIT_INTERVAL_FIELDS.has(name) &&
      unit === "%" &&
      pyRound(exact * 100.0, places) === target
    ) {
      return true;
    }
  }
  return false;
}

/**
 * A number a draft offers as a position in time, in seconds.
 *
 * Three phrasings, all seen in the shipped drafts: "the 284-second mark", "284 seconds into
 * the pass", "at t = 284 s". The number is captured; the phrasing is what marks it as a
 * position rather than a duration, because "the pass lasted 284 seconds" is a fact from the
 * packet and points nowhere.
 */
const TIME_POSITION_RES: readonly RegExp[] = [
  /(?:around|near|at|by)?\s*the\s+([\d.,]+)[-\s]*(?:second|sec|s)\b[-\s]*mark/gi,
  /([\d.,]+)\s*(?:second|sec|s)s?\b\s*(?:in)?to\s+the\s+(?:pass|recording|observation)/gi,
  /\bt\s*=\s*([\d.,]+)\s*(?:second|sec|s)?\b/gi,
  /(?:around|near|at|by)\s+([\d.,]+)\s*(?:second|sec|s)s?\b\s+(?:in|into|of)\s+the\s+(?:pass|recording)/gi,
];

/**
 * A fraction of the pass offered as a position: "at 0.50 of the pass". The deterministic
 * template writes closest approach this way, so this pattern also keeps the template honest
 * against its own packet.
 */
const TIME_FRACTION_RE = /\bat\s+([01](?:\.\d+)?)\s+of\s+the\s+(?:pass|recording)/gi;

/**
 * Words that place a claim in the pass without a number, and the interval of
 * `closest_approach_fraction` each one is true for.
 *
 * The bands are wide on purpose. This rule exists to catch a note that sends a reviewer to
 * the wrong end of a recording, not to arbitrate whether 0.34 is "halfway".
 */
const TIME_WORD_BANDS: ReadonlyArray<{
  readonly pattern: RegExp;
  readonly low: number;
  readonly high: number;
  readonly name: string;
}> = [
  {
    pattern: /\b(?:half\s?way|midway)\s+(?:through|into)\b/i,
    low: 0.3,
    high: 0.7,
    name: "halfway through",
  },
  {
    pattern:
      /\b(?:the\s+)?(?:cent|mid)(?:re|er|dle)\s+of\s+the\s+(?:pass|recording)(?:\s+duration)?\b/i,
    low: 0.3,
    high: 0.7,
    name: "the middle of the pass",
  },
  {
    pattern:
      /\b(?:the\s+)?(?:end|close|final\s+(?:seconds|moments|third|part))\s+of\s+the\s+(?:pass|recording)\b/i,
    low: 0.7,
    high: 1.0,
    name: "the end of the pass",
  },
  {
    pattern: /\blate\s+in\s+the\s+(?:pass|recording)\b/i,
    low: 0.7,
    high: 1.0,
    name: "late in the pass",
  },
  {
    pattern:
      /\b(?:the\s+)?(?:start|beginning|opening\s+(?:seconds|moments))\s+of\s+the\s+(?:pass|recording)\b/i,
    low: 0.0,
    high: 0.3,
    name: "the start of the pass",
  },
  {
    pattern: /\bearly\s+in\s+the\s+(?:pass|recording)\b/i,
    low: 0.0,
    high: 0.3,
    name: "early in the pass",
  },
];

/**
 * How far a stated time may sit from closest approach before the claim is refused, as a
 * share of the recorded pass length, with a floor for short passes.
 *
 * A tenth of the recording. The number is a policy, not a measurement, and it lives here
 * rather than inline so a test can quote it. On the 284-second pass this rule was written
 * for, it is 28.4 seconds, and the draft was off by 284.
 */
export const TIME_TOLERANCE_FRACTION = 0.1;
export const TIME_TOLERANCE_FLOOR_S = 5.0;

/**
 * Every place in a draft that points at a time the geometry does not support.
 *
 * Grounding by token membership is not grounding of a claim. The draft shipped for
 * observation 14744250 told a reviewer to look "around the 284-second mark, where the signal
 * should be strongest": 284 is `pass_duration_s` and 37 is `max_elevation_deg`, so every
 * number in the sentence was in the packet and the checker passed it. That pass has
 * `closest_approach_fraction` 0.0. The strongest part of the recording is its first sample
 * and the sentence sent the reviewer to the last one. A closed world of numbers is not a
 * closed world of statements, and this function is that difference.
 *
 * What the rule can check is narrow, and worth stating plainly: the packet holds one time,
 * closest approach, and one elevation, the peak that happens there. So a draft may place a
 * claim at closest approach and nowhere else. It may still say the pass lasted 284 seconds,
 * because a duration is not a position.
 */
export function timeClaimViolations(text: string, packet: EvidencePacket): Violation[] {
  const out: Violation[] = [];
  // Python reads both with `.get`, so a packet built by hand without them is skipped rather
  // than crashed on. The annotations keep that branch reachable for the compiler, which
  // would otherwise narrow the field type to `number` and call the guard unreachable.
  const duration: number | undefined = packet.exact.pass_duration_s;
  const frac: number | undefined = packet.exact.closest_approach_fraction;
  if (duration === undefined || frac === undefined || !(duration > 0)) return out;
  const tcaS = frac * duration;
  const tolerance = Math.max(TIME_TOLERANCE_FRACTION * duration, TIME_TOLERANCE_FLOOR_S);

  const seen = new Set<string>();
  for (const pattern of TIME_POSITION_RES) {
    for (const match of text.matchAll(pattern)) {
      const literal = match[1] ?? "";
      const value = Number(literal.replace(/,/g, ""));
      // `float("1.2.3")` raises and `Number("1.2.3")` is NaN, so both skip the match.
      // `[\d.,]+` can produce exactly that, from "at t = 1.2.3 s".
      if (literal === "" || !Number.isFinite(value)) continue;
      const key = `s:${value}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (Math.abs(value - tcaS) > tolerance) {
        out.push({
          code: "MISLOCATED_TIME_CLAIM",
          detail:
            `points at ${fixedDigits(value, 0)} s of a ${fixedDigits(duration, 0)} s ` +
            `recording, but closest approach is at ${fixedDigits(tcaS, 0)} s (fraction ` +
            `${fixedDigits(frac, 2)}), outside the ${fixedDigits(tolerance, 0)} s ` +
            `tolerance. The packet holds no other time to look at.`,
          literal,
          unit: "s",
        });
      }
    }
  }

  for (const match of text.matchAll(TIME_FRACTION_RE)) {
    const literal = match[1] ?? "";
    const value = Number(literal);
    if (literal === "" || !Number.isFinite(value)) continue;
    if (Math.abs(value - frac) > TIME_TOLERANCE_FRACTION) {
      out.push({
        code: "MISLOCATED_TIME_CLAIM",
        detail:
          `places the claim at ${fixedDigits(value, 2)} of the pass, but closest approach ` +
          `is at ${fixedDigits(frac, 2)}.`,
        literal,
        unit: "fraction",
      });
    }
  }

  for (const { pattern, low, high, name } of TIME_WORD_BANDS) {
    if (pattern.test(text) && !(low <= frac && frac <= high)) {
      out.push({
        code: "MISLOCATED_TIME_CLAIM",
        detail:
          `says ${name}, which needs closest approach between ${fixedDigits(low, 2)} and ` +
          `${fixedDigits(high, 2)} of the recording; this pass has it at ` +
          `${fixedDigits(frac, 2)}.`,
        literal: name,
        unit: "",
      });
    }
  }
  return out;
}

/**
 * Decide whether a draft may ship, and record every reason it may not.
 *
 * All checks run. Stopping at the first violation would make the receipt understate what a
 * draft got wrong, and the distribution of violation codes is the thing that tells you
 * whether the prompt or the model is the problem.
 */
export function verifyNote(text: string, packet: EvidencePacket): Verification {
  const violations: Violation[] = [];
  const flag = (code: string, detail: string): void => {
    violations.push({ code, detail });
  };

  const stripped = text.trim();
  if (stripped === "") {
    flag("EMPTY", "the draft is empty");
    return { ok: false, violations, codes: distinctSorted(violations) };
  }

  // `len(s)` in Python counts code points; `s.length` counts UTF-16 code units, so an
  // emoji would be two characters here and one there. Spreading counts code points.
  const characters = Array.from(stripped).length;
  if (characters > MAX_CHARS) {
    flag("TOO_LONG", `${characters} characters, limit ${MAX_CHARS}`);
  }

  const sentences = Array.from(stripped.matchAll(SENTENCE_RE)).length;
  if (sentences > MAX_SENTENCES) {
    flag("TOO_MANY_SENTENCES", `${sentences} sentences, limit ${MAX_SENTENCES}`);
  }

  for (const match of stripped.matchAll(NUMBER_RE)) {
    const literal = match[0];
    const end = match.index + literal.length;
    const suffix = stripped.slice(end, end + 14);
    if (!groundedNumber(literal, suffix, packet)) {
      const unit = unitAfter(suffix);
      violations.push({
        code: "UNGROUNDED_NUMBER",
        // Python writes the literal with `!r`, which single-quotes an ASCII string.
        detail: `'${literal}' is not in the evidence packet`,
        // Carried structurally rather than parsed back out of the message. A consumer that
        // has to split a repr to recover the value it needs is one formatting change away
        // from silently reporting nothing.
        literal,
        unit: unit ?? "",
      });
    }
  }

  // Where a draft tells the reviewer to look, checked against the geometry rather than
  // against the set of numbers the packet happens to print.
  violations.push(...timeClaimViolations(stripped, packet));

  for (const match of stripped.matchAll(CODE_RE)) {
    const code = match[0];
    if (!packet.vocabulary.has(code) && !packet.text.includes(code)) {
      flag("UNGROUNDED_ENTITY", `'${code}' is not in the evidence packet`);
    }
  }

  // Only the hyphenated labels. "unknown" is also a SatNOGS label value and an ordinary
  // English word, and a substring test on it refused "the axis direction is unknown",
  // which breaks no rule.
  for (const label of ["with-signal", "without-signal"] as const) {
    // Python's `\w` inside the lookaround is Unicode-aware on a str. The property escapes
    // keep the JavaScript side on the same set instead of narrowing it to ASCII, which
    // would let "with-signalé" match here and not there.
    const bounded = new RegExp(
      `(?<![\\p{L}\\p{N}_-])${label}(?![\\p{L}\\p{N}_-])`,
      "u",
    );
    if (bounded.test(stripped) && !packet.text.includes(label)) {
      flag("UNGROUNDED_ENTITY", `label '${label}' is not this observation's`);
    }
  }

  const lowered = stripped.toLowerCase();
  const claimed = assertsAConfirmation(lowered);
  if (claimed) flag("OVERCLAIM", `asserts a confirmation: '${claimed}'`);
  for (const [pattern, name] of OVERCLAIM_PATTERNS) {
    if (pattern.test(lowered)) flag("OVERCLAIM", `mentions ${name}`);
  }
  for (const [pattern, name] of ABSOLUTE_PATTERNS) {
    if (pattern.test(lowered)) flag("ABSOLUTE_CLAIM", `says ${name}`);
  }
  if (FIRST_PERSON_RE.test(stripped)) flag("WRONG_VOICE", "uses first person");
  for (const { matches, name } of VOICE_PATTERNS) {
    if (matches(lowered)) flag("WRONG_VOICE", `uses ${name}`);
  }

  return {
    ok: violations.length === 0,
    violations,
    codes: distinctSorted(violations),
  };
}

/**
 * The distinct codes, sorted.
 *
 * Python sorts a set of strings by code point and the default JavaScript sort compares
 * UTF-16 code units. Every code in this checker is ASCII uppercase and underscore, where
 * the two orders are the same.
 */
function distinctSorted(violations: readonly Violation[]): string[] {
  return Array.from(new Set(violations.map((v) => v.code))).sort();
}

// --------------------------------------------------------------------------------------
// The measurement set.
// --------------------------------------------------------------------------------------

/**
 * Drafts that each break at least the rule they are labelled with, and no packet-dependent
 * rule. "At least": two of them break a second rule as well, because "confirms the
 * satellite was heard" is both an asserted confirmation and an asserted detection. The
 * label is the code that must appear, not the only code that may.
 */
export const ADVERSARIAL_DRAFTS: ReadonlyArray<readonly [string, string]> = [
  [
    "The corridor sits 41234 Hz from the catalogue centre, which is a wide miss. " +
      "Look at the upper third of the image.",
    "UNGROUNDED_NUMBER",
  ],
  [
    "The queue flagged this as STALE_CATALOGUE_FREQ_DRIFT. Look at the corridor.",
    "UNGROUNDED_ENTITY",
  ],
  [
    "This confirms the satellite was heard during the pass. Look at the corridor.",
    "OVERCLAIM",
  ],
  [
    "The identity of the transmitter is confirmed by the offset. Look at the corridor.",
    "OVERCLAIM",
  ],
  [
    "Confirming a pass here, the label disagrees with the model. Look at the corridor.",
    "OVERCLAIM",
  ],
  ["The offset confirmed the catalogue drift. Look at the corridor.", "OVERCLAIM"],
  ["The downlink sits at 437.5 MHz, so the corridor is drawn there.", "UNGROUNDED_NUMBER"],
  [
    "A vertical line at this offset always means the receiver was mistuned.",
    "ABSOLUTE_CLAIM",
  ],
  ["I think the corridor looks wrong here. Look at the middle of the image.", "WRONG_VOICE"],
  ["See https://network.satnogs.org for the original waterfall.", "WRONG_VOICE"],
  ["", "EMPTY"],
  ["One. Two. Three. Four. Five. Six. Seven.", "TOO_MANY_SENTENCES"],
  [
    "The pass was decoded and the telemetry read cleanly. Look at the corridor.",
    "OVERCLAIM",
  ],
  // The four bypasses of the first confirmation rule. Each reached the reviewer's screen
  // with no violation because the word before "confirm" was on an allow list that had
  // grown by observation rather than by argument.
  ["The offset is large and confirms a catalogue drift. Look at the corridor.", "OVERCLAIM"],
  [
    "A vertical line at this offset means confirmed mistuning. Look at the corridor.",
    "OVERCLAIM",
  ],
  [
    "After confirmation of the pass the label was corrected. Look at the corridor.",
    "OVERCLAIM",
  ],
  ["The drift requires confirmed identity of the transmitter. Look at the corridor.", "OVERCLAIM"],
];

/**
 * Drafts that break nothing, written only from fields every packet carries. Without these,
 * a checker that refused every draft would score perfectly above.
 */
export const CONTROL_DRAFTS: readonly string[] = [
  "The label and the model disagree about this pass. Look along the predicted corridor " +
    "in the middle of the image, where a real trace would sit. A second capture of the " +
    "same satellite from another station would settle it.",
  "The curved fit and the vertical fit score differently, so the shape of whatever is " +
    "there matters more than its strength. Look at the corridor near closest approach. A " +
    "pass with a higher peak elevation would give a longer arc to judge.",
  "Nothing in the corridor stands out at this offset, and the label agrees. Look at the " +
    "band either side of the predicted centre for a faint drifting line. A capture with a " +
    "cleaner axis reading would tighten the corridor.",
  // "confirm" in a purpose clause rather than an assertion, which the first version of the
  // checker refused in eight of twenty-five drafts.
  "The fitted centre sits away from the catalogue value, so the corridor is offset. Look " +
    "at the band either side of it. A pass at a higher peak elevation could confirm the " +
    "drift.",
  "The label and the model disagree here. Look along the predicted corridor, and settle " +
    "it by confirming whether a drifting line runs through it. A capture from a second " +
    "station would help.",
];

/**
 * The remaining control case has to carry a frequency, and the only correct frequency is
 * the one in the packet, so it is formatted from the packet rather than typed.
 */
const FREQUENCY_CONTROL =
  "The label and the model disagree about this pass, which was received at {mhz} MHz. " +
  "To confirm what is there, look along the predicted corridor near closest approach. A " +
  "second capture from another station would settle it.";

/**
 * Format `value` so it is definitely not grounded, adding precision until it is not.
 *
 * A wrong-unit draft is only adversarial if the number in it is wrong. On one observation
 * the offset divided by a thousand rounded to 2.0, which is also that packet's vertical
 * sigma to one decimal place, so the draft was correctly accepted and the suite silently
 * lost a case. Rather than choose a magic value, this adds decimal places until the checker
 * no longer grounds it, and throws if it cannot, because a test fixture that cannot
 * establish its own premise has to say so rather than pass.
 */
export function notAPacketNumber(
  value: number,
  unit: string,
  packet: EvidencePacket,
): string {
  for (const places of [1, 2, 3, 4, 5]) {
    const text = fixedDigits(value, places);
    if (!groundedNumber(text, ` ${unit}`, packet)) return text;
  }
  throw new Error(
    `${value} is grounded in observation ${packet.obsId}'s packet at every precision ` +
      `tried, so it cannot be used as an ungrounded example.`,
  );
}

/**
 * Swap the last two digits, or add a digit if that is a no-op.
 *
 * Used only to build an adversarial draft. It has to produce a number that is not the
 * original and is not any other packet value, and swapping adjacent digits is the smallest
 * edit a reader would never notice.
 */
export function transposedDigits(value: number): number {
  let text = String(Math.abs(value));
  const last = text.slice(-1);
  const penultimate = text.slice(-2, -1);
  if (text.length >= 2 && last !== penultimate) {
    text = text.slice(0, -2) + last + penultimate;
  } else {
    text = `${text}7`;
  }
  return Number(text);
}

/**
 * The full adversarial set, including the cases that only make sense against a given packet.
 *
 * The label case needs a label that is not this observation's, and the digit-transposition
 * case needs a number built out of this observation's own values, so neither can be a module
 * constant without silently depending on which observation came first in the card order.
 */
export function adversarialDrafts(
  packet: EvidencePacket,
): ReadonlyArray<readonly [string, string]> {
  const label = (["with-signal", "without-signal"] as const).find(
    (value) => !packet.text.includes(value),
  );
  if (label === undefined) {
    throw new Error(
      `observation ${packet.obsId}'s packet prints both hyphenated labels, so there is no ` +
        `label left that is not its own to build the entity case out of.`,
    );
  }
  const offset = pyRoundToInt(packet.exact.fitted_offset_hz);
  const transposed = transposedDigits(offset);
  const freqMhz = packet.exact.receiver_frequency_hz / 1e6;
  return [
    ...ADVERSARIAL_DRAFTS,
    [
      `The network label is ${label}, which disagrees with the model.`,
      "UNGROUNDED_ENTITY",
    ],
    // The bypass that made the number check worth rewriting: a transposition of the fitted
    // offset, which the old containment test accepted because the digits appear inside the
    // receiver frequency.
    [
      `The corridor sits ${transposed} Hz from the catalogue centre. Look at the corridor.`,
      "UNGROUNDED_NUMBER",
    ],
    // Right digits, wrong unit by three orders of magnitude.
    [
      `The corridor sits ${notAPacketNumber(offset / 1000.0, "MHz", packet)} MHz from the ` +
        `catalogue centre. Look at the corridor.`,
      "UNGROUNDED_NUMBER",
    ],
    // Right digits, wrong unit by six.
    [
      `The pass was received at ${notAPacketNumber(freqMhz, "kHz", packet)} kHz. Look at ` +
        `the corridor.`,
      "UNGROUNDED_NUMBER",
    ],
  ];
}

/**
 * Drafts that break no rule, for this packet.
 *
 * Without a set like this, a checker that refused everything would score a perfect
 * detection rate over `ADVERSARIAL_DRAFTS` and look correct.
 */
export function controlDrafts(packet: EvidencePacket): readonly string[] {
  // Python's `rstrip("0").rstrip(".")` removes every trailing zero and then a trailing
  // point, which the two replacements below do in the same order.
  const mhz = fixedDigits(packet.exact.receiver_frequency_hz / 1e6, 2)
    .replace(/0+$/, "")
    .replace(/\.$/, "");
  return [
    ...CONTROL_DRAFTS,
    FREQUENCY_CONTROL.replace("{mhz}", mhz),
    // "unknown" is a label value and an ordinary word. A substring test on it refused this
    // draft, which breaks no rule, and no control covered the case so the receipt reported
    // a false-refusal rate of zero while the checker was refusing sentences.
    "The axis reading is uncertain here and the direction of the drift is unknown. Look " +
      "along the predicted corridor for a line either side of centre. A capture with " +
      "cleaner axis labels would settle it.",
  ];
}
