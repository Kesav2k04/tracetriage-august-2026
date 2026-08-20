/**
 * The grounding checker in the browser has to agree with the one in the pipeline.
 *
 * Two kinds of test here, and they close different holes.
 *
 * The parity block replays `public/data/grounding_golden.json`, which is what
 * `pipeline/tracetriage/explain.py` decided about 1275 draft/observation pairs. Every packet
 * is rebuilt from the same `cards.json` and `queue.json` the Python builder read, then every
 * row is re-checked and required to produce the same verdict, the same codes and the same
 * violations down to the detail string. That is the test that cannot be satisfied by a port
 * that "roughly" matches: a rounding mode, a word boundary or a field precision that differs
 * shows up as a row that disagrees. `tests/test_grounding_parity.py` keeps the fixture itself
 * from going stale, so neither implementation can move without the other following.
 *
 * The rule blocks below test each rule on its own, against a hand-built packet. The parity
 * fixture proves the two checkers agree; it does not prove either one is right, and a rule
 * whose regular expression matched nothing would agree perfectly. So each rule also has a
 * case here that asserts the code it is supposed to produce, and the ones with a negative
 * side ("a duration is not a position", "unknown is an ordinary word") assert that too.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  ADVERSARIAL_DRAFTS,
  CONTROL_DRAFTS,
  MAX_CHARS,
  MAX_SENTENCES,
  MeasurementMissing,
  NotAnInteger,
  TIME_TOLERANCE_FLOOR_S,
  TIME_TOLERANCE_FRACTION,
  adversarialDrafts,
  assertsAConfirmation,
  buildPacket,
  controlDrafts,
  deterministicNote,
  fixedDigits,
  groundedNumber,
  pyRound,
  renderPacketText,
  timeClaimViolations,
  transposedDigits,
  unitAfter,
  verifyNote,
  type EvidencePacket,
  type ExactFields,
  type GroundingCard,
  type GroundingEntry,
  type PrintedFields,
  type Violation,
  finalisePacket,
} from "../lib/grounding";

const DATA = join(__dirname, "..", "public", "data");

function readJson<T>(name: string): T {
  return JSON.parse(readFileSync(join(DATA, name), "utf8")) as T;
}

interface GoldenRow {
  obs_id: number;
  kind: "adversarial" | "control" | "deterministic" | "shipped" | "handwritten";
  name: string;
  expects: string | null;
  draft: string;
  ok: boolean;
  codes: string[];
  violations: Violation[];
}

interface GoldenPacket {
  obs_id: number;
  printed: Record<string, string>;
  exact: Record<string, number>;
  vocabulary: string[];
  text: string;
}

interface Golden {
  checker: string;
  checker_sha256: string;
  n_observations: number;
  n_rows: number;
  observations: number[];
  skipped: Array<{ obs_id: string; reason: string }>;
  packets: GoldenPacket[];
  rows: GoldenRow[];
}

const golden = readJson<Golden>("grounding_golden.json");
const cards = readJson<{ cards: GroundingCard[] }>("cards.json").cards;
const entries = readJson<{ entries: GroundingEntry[] }>("queue.json").entries;

const cardById = new Map(cards.map((card) => [card.obs_id, card]));
const entryById = new Map(entries.map((entry) => [entry.obs_id, entry]));

/** Every packet the fixture covers, built by the TypeScript builder from the same JSON. */
const packetById = new Map<number, EvidencePacket>(
  golden.observations.map((obsId) => {
    const card = cardById.get(obsId);
    const entry = entryById.get(obsId);
    if (!card || !entry) {
      throw new Error(
        `grounding_golden.json covers observation ${obsId}, which is not in both ` +
          `cards.json and queue.json. Regenerate the fixture.`,
      );
    }
    return [obsId, buildPacket(card, entry)];
  }),
);

function packetFor(obsId: number): EvidencePacket {
  const packet = packetById.get(obsId);
  if (!packet) throw new Error(`no packet for observation ${obsId}`);
  return packet;
}

// --------------------------------------------------------------------------------------
// Python's rounding, which is where a port of a formatter goes wrong silently.
// --------------------------------------------------------------------------------------

describe("fixedDigits", () => {
  // Each of these is what CPython prints. `toFixed` disagrees on five of the six, and the
  // asserted disagreement is the point: it is the defect this function exists to close.
  const cases: ReadonlyArray<readonly [number, number, string]> = [
    [1.25, 1, "1.2"],
    [0.5, 0, "0"],
    [2.5, 0, "2"],
    [3.5, 0, "4"],
    [0.125, 2, "0.12"],
    [0.375, 2, "0.38"],
    // 2.675 is really 2.674999999999999822..., so it rounds down in both languages. Carried
    // because a version working from the shortest decimal repr would round it up.
    [2.675, 2, "2.67"],
    [-0.5, 0, "-0"],
    [-1.25, 1, "-1.2"],
    [436.49, 1, "436.5"],
    [0.0, 2, "0.00"],
    [284, 0, "284"],
  ];

  it.each(cases)("formats %s to %s places as %s", (value, places, expected) => {
    expect(fixedDigits(value, places)).toBe(expected);
  });

  it("rounds half to even where toFixed rounds half away from zero", () => {
    const divergent = cases.filter(
      ([value, places, expected]) => value.toFixed(places) !== expected,
    );
    expect(divergent.map(([value, places]) => [value, places])).toEqual([
      [1.25, 1],
      [0.5, 0],
      [2.5, 0],
      [0.125, 2],
      [-0.5, 0],
      [-1.25, 1],
    ]);
  });

  it("keeps a magnitude toFixed switches to exponent notation for", () => {
    // Python's ".1f" never goes exponential; toFixed does above 1e21, which would put an
    // "e" in the middle of a packet field.
    expect(fixedDigits(1e21, 1)).toBe("1000000000000000000000.0");
    expect((1e21).toFixed(1)).toBe("1e+21");
  });

  it("spells a non-finite value the way Python does", () => {
    expect(fixedDigits(Number.NaN, 2)).toBe("nan");
    expect(fixedDigits(Number.POSITIVE_INFINITY, 2)).toBe("inf");
    expect(fixedDigits(Number.NEGATIVE_INFINITY, 2)).toBe("-inf");
  });
});

describe("pyRound", () => {
  it("returns the double Python's round returns", () => {
    expect(pyRound(1.25, 1)).toBe(1.2);
    expect(pyRound(0.5, 0)).toBe(0);
    expect(pyRound(2.5, 0)).toBe(2);
    expect(pyRound(0.999999 * 100, 1)).toBe(100);
    expect(pyRound(436490000 / 1e6, 2)).toBe(436.49);
  });
});

// --------------------------------------------------------------------------------------
// Parity with the pipeline.
// --------------------------------------------------------------------------------------

describe("parity with the Python checker", () => {
  it("has a fixture worth calling a check", () => {
    expect(golden.checker).toBe("pipeline/tracetriage/explain.py");
    expect(golden.rows.length).toBe(golden.n_rows);
    expect(golden.packets.length).toBe(golden.n_observations);
    // Floors, not equalities: adding a draft or an observation should not fail here, and
    // losing most of the set should. Measured on 2026-08-21 at 1275 rows over 25
    // observations, and the brief for this unit called anything under 200 pairs not a check.
    expect(golden.n_rows).toBeGreaterThanOrEqual(1000);
    expect(golden.n_observations).toBeGreaterThanOrEqual(25);
    expect(golden.checker_sha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it("covers both directions, so refusing everything cannot pass", () => {
    const refused = golden.rows.filter((row) => !row.ok).length;
    const grounded = golden.rows.filter((row) => row.ok).length;
    expect(refused).toBeGreaterThanOrEqual(500);
    expect(grounded).toBeGreaterThanOrEqual(300);
  });

  it("builds the same packet as the Python builder, field for field", () => {
    for (const record of golden.packets) {
      const packet = packetFor(record.obs_id);
      // Printed first: every refusal depends on it, so a wrong precision here is the cause
      // of a disagreement several assertions downstream.
      expect(packet.printed, `printed for ${record.obs_id}`).toEqual(record.printed);
      expect(packet.exact, `exact for ${record.obs_id}`).toEqual(record.exact);
      expect(
        Array.from(packet.vocabulary).sort(),
        `vocabulary for ${record.obs_id}`,
      ).toEqual(record.vocabulary);
      expect(packet.text, `as_text for ${record.obs_id}`).toBe(record.text);
    }
  });

  it("reaches the same verdict on every draft, with the same violations", () => {
    const disagreements: string[] = [];
    for (const row of golden.rows) {
      const verdict = verifyNote(row.draft, packetFor(row.obs_id));
      const same =
        verdict.ok === row.ok &&
        JSON.stringify(verdict.codes) === JSON.stringify(row.codes) &&
        JSON.stringify(verdict.violations) === JSON.stringify(row.violations);
      if (!same) {
        disagreements.push(
          `${row.obs_id} ${row.kind}/${row.name}: python ` +
            `${JSON.stringify({ ok: row.ok, violations: row.violations })} vs typescript ` +
            `${JSON.stringify({ ok: verdict.ok, violations: verdict.violations })}`,
        );
      }
    }
    // Reported together rather than one at a time. A rounding difference moves dozens of
    // rows at once and the shape of the list says which rule moved.
    expect(disagreements.slice(0, 5)).toEqual([]);
    expect(disagreements.length).toBe(0);
  });

  it("generates the same adversarial drafts, including the two built from the packet", () => {
    for (const obsId of golden.observations) {
      const generated = adversarialDrafts(packetFor(obsId));
      const recorded = golden.rows.filter(
        (row) => row.obs_id === obsId && row.kind === "adversarial",
      );
      expect(generated.length, `adversarial count for ${obsId}`).toBe(recorded.length);
      generated.forEach(([draft, code], index) => {
        const row = recorded[index];
        // The transposed offset and the two wrong-unit cases are formatted from the
        // packet, so this is where a divergence in `notAPacketNumber` or `transposedDigits`
        // surfaces as a different sentence rather than a different verdict.
        expect(draft, `adversarial ${index} text for ${obsId}`).toBe(row?.draft);
        expect(code, `adversarial ${index} code for ${obsId}`).toBe(row?.expects);
      });
    }
  });

  it("generates the same control drafts", () => {
    for (const obsId of golden.observations) {
      const generated = controlDrafts(packetFor(obsId));
      const recorded = golden.rows
        .filter((row) => row.obs_id === obsId && row.kind === "control")
        .map((row) => row.draft);
      expect(Array.from(generated), `controls for ${obsId}`).toEqual(recorded);
    }
  });

  it("agrees on the deterministic template for every shipped card", () => {
    for (const obsId of golden.observations) {
      const packet = packetFor(obsId);
      const row = golden.rows.find(
        (candidate) => candidate.obs_id === obsId && candidate.kind === "deterministic",
      );
      expect(deterministicNote(packet), `template text for ${obsId}`).toBe(row?.draft);
    }
  });
});

// --------------------------------------------------------------------------------------
// The rules, one at a time.
// --------------------------------------------------------------------------------------

describe("the acceptance cases from the handover", () => {
  it("refuses a false 437.2 MHz downlink on observation 14740031", () => {
    const packet = packetFor(14740031);
    // The receiver is at 436400000 Hz. 437.2 is a real amateur satellite frequency and not
    // this one, which is the failure the whole unit was built to catch.
    expect(packet.printed.receiver_frequency_hz).toBe("436400000");
    const verdict = verifyNote(
      "The downlink sits at 437.2 MHz, so the corridor is drawn there.",
      packet,
    );
    expect(verdict.ok).toBe(false);
    expect(verdict.codes).toEqual(["UNGROUNDED_NUMBER"]);
    expect(verdict.violations[0]?.literal).toBe("437.2");
    expect(verdict.violations[0]?.unit).toBe("mhz");
  });

  it("accepts the receiver's own frequency in megahertz on the same observation", () => {
    // The other half of the same rule. A checker that refused every frequency would pass
    // the assertion above.
    const verdict = verifyNote(
      "The downlink sits at 436.4 MHz, so the corridor is drawn there.",
      packetFor(14740031),
    );
    expect(verdict.codes).toEqual([]);
    expect(verdict.ok).toBe(true);
  });

  it("refuses the 284-second mark on 14744250 as a time claim, not as a number", () => {
    const packet = packetFor(14744250);
    // 284 is `pass_duration_s` and closest approach is at 0.00 of the pass, so every number
    // in the sentence is in the packet and the sentence still points at the wrong end.
    expect(packet.printed.pass_duration_s).toBe("284");
    expect(packet.printed.closest_approach_fraction).toBe("0.00");
    const verdict = verifyNote(
      "Look around the 284-second mark, where the signal should be strongest.",
      packet,
    );
    expect(verdict.ok).toBe(false);
    expect(verdict.codes).toEqual(["MISLOCATED_TIME_CLAIM"]);
    expect(verdict.codes).not.toContain("UNGROUNDED_NUMBER");
    expect(verdict.violations[0]?.detail).toBe(
      "points at 284 s of a 284 s recording, but closest approach is at 0 s (fraction " +
        "0.00), outside the 28 s tolerance. The packet holds no other time to look at.",
    );
  });

  it("still lets 14744250 say how long the pass was", () => {
    // A duration is not a position. If this failed, the rule would refuse the deterministic
    // template on the card it was written for.
    const verdict = verifyNote(
      "The recording runs 284 seconds and the corridor sits 9737 Hz from the catalogue " +
        "centre.",
      packetFor(14744250),
    );
    expect(verdict.codes).toEqual([]);
  });

  it("passes the deterministic note on every shipped card", () => {
    for (const obsId of golden.observations) {
      const packet = packetFor(obsId);
      const verdict = verifyNote(deterministicNote(packet), packet);
      expect(verdict.violations, `template for ${obsId}`).toEqual([]);
      expect(verdict.ok).toBe(true);
    }
  });

  it("refuses every adversarial draft with the code it is labelled with", () => {
    for (const obsId of golden.observations) {
      const packet = packetFor(obsId);
      for (const [draft, code] of adversarialDrafts(packet)) {
        const verdict = verifyNote(draft, packet);
        expect(verdict.ok, `${obsId}: ${draft.slice(0, 60)}`).toBe(false);
        expect(verdict.codes, `${obsId}: ${draft.slice(0, 60)}`).toContain(code);
      }
    }
  });

  it("refuses none of the control drafts", () => {
    for (const obsId of golden.observations) {
      const packet = packetFor(obsId);
      for (const draft of controlDrafts(packet)) {
        const verdict = verifyNote(draft, packet);
        expect(verdict.violations, `${obsId}: ${draft.slice(0, 60)}`).toEqual([]);
      }
    }
  });

  it("covers every module-level draft in both sets", () => {
    // The counts are the pipeline's, and a set that quietly shrank would still pass the
    // loops above.
    expect(ADVERSARIAL_DRAFTS.length).toBe(17);
    expect(CONTROL_DRAFTS.length).toBe(5);
    expect(adversarialDrafts(packetFor(14740031)).length).toBe(21);
    expect(controlDrafts(packetFor(14740031)).length).toBe(7);
  });
});

/**
 * A packet with round numbers, so a rule's own case reads without arithmetic.
 *
 * Built through `finalisePacket` rather than assembled by hand, so its text and token set
 * cannot disagree with its fields.
 */
function samplePacket(over: Partial<ExactFields> = {}): EvidencePacket {
  const exact: ExactFields = {
    queue_rank: 3,
    queue_score: 0.5,
    model_probability: 0.8,
    ensemble_uncertainty: 0.001,
    flat_row_fraction: 0.25,
    pass_duration_s: 300,
    max_elevation_deg: 40,
    closest_approach_fraction: 0.5,
    fitted_offset_hz: 6904,
    fitted_offset_ppm: 15.8,
    corridor_half_width_hz: 2000,
    sigma_curved: 3.2,
    sigma_vertical: 1.1,
    hz_per_pixel: 95.9,
    seconds_per_pixel: 0.34,
    axis_derivation_confidence: 0.94,
    receiver_frequency_hz: 436490000,
    norad_catalogue_id: 52899,
    ground_station_id: 5078,
    observation_id: 99,
    ...over,
  };
  const printed: PrintedFields = {
    observation_id: "99",
    ground_station_id: "5078",
    ground_station_name: "dm43",
    norad_catalogue_id: "52899",
    transmitter_mode: "GMSK",
    receiver_frequency_hz: String(exact.receiver_frequency_hz),
    network_label: "without-signal",
    pass_duration_s: fixedDigits(exact.pass_duration_s, 0),
    max_elevation_deg: fixedDigits(exact.max_elevation_deg, 1),
    closest_approach_fraction: fixedDigits(exact.closest_approach_fraction, 2),
    fitted_offset_hz: fixedDigits(exact.fitted_offset_hz, 0),
    fitted_offset_ppm: fixedDigits(exact.fitted_offset_ppm, 1),
    corridor_half_width_hz: fixedDigits(exact.corridor_half_width_hz, 0),
    sigma_curved: fixedDigits(exact.sigma_curved, 1),
    sigma_vertical: fixedDigits(exact.sigma_vertical, 1),
    hz_per_pixel: fixedDigits(exact.hz_per_pixel, 1),
    seconds_per_pixel: fixedDigits(exact.seconds_per_pixel, 2),
    axis_derivation: "axis_ticks_ocr",
    axis_derivation_confidence: fixedDigits(exact.axis_derivation_confidence, 2),
    model_probability: fixedDigits(exact.model_probability, 3),
    ensemble_uncertainty: fixedDigits(exact.ensemble_uncertainty, 4),
    flat_row_fraction: fixedDigits(exact.flat_row_fraction, 2),
    queue_rank: "3",
    queue_score: fixedDigits(exact.queue_score, 3),
    queue_reason_codes: "MODEL_LABEL_DISAGREE",
    offset_at_bound: "false",
  };
  return finalisePacket(99, printed, exact, [
    "dm43",
    "GMSK",
    "without-signal",
    "axis_ticks_ocr",
    "MODEL_LABEL_DISAGREE",
  ]);
}

const codesOf = (draft: string, packet = samplePacket()): string[] =>
  verifyNote(draft, packet).codes;

describe("the shape of the packet", () => {
  it("pads every field name to one column, as as_text does", () => {
    const text = renderPacketText(samplePacket().printed);
    const lines = text.split("\n");
    // "axis_derivation_confidence" is the longest name at 26 characters, so every separator
    // lands in the same column. A port that used a fixed width would move the token set,
    // and one that measured the wrong field would move it by one.
    expect(lines[0]).toBe(`observation_id${" ".repeat(12)} : 99`);
    expect(new Set(lines.map((line) => line.indexOf(" : ")))).toEqual(new Set([26]));
  });

  it("tokenises the text rather than searching it", () => {
    const packet = samplePacket();
    // The bypass this closes: 6490 appears inside 436490000 and is not a token of it, and a
    // transposition of the fitted offset was grounded by those digits.
    expect(packet.numberTokens.has("436490000")).toBe(true);
    expect(packet.numberTokens.has("6490")).toBe(false);
    expect(codesOf("The corridor sits 6490 Hz from the catalogue centre.")).toEqual([
      "UNGROUNDED_NUMBER",
    ]);
  });

  it("refuses a card with no fit rather than defaulting the measurement to zero", () => {
    const card = cardById.get(14740031);
    const entry = entryById.get(14740031);
    if (!card || !entry) throw new Error("14740031 is missing from the console data");
    for (const field of [
      "max_elevation_deg",
      "tca_frac",
      "fitted_offset_hz",
      "sigma_curved",
    ] as const) {
      const holed = { ...card, corridor: { ...card.corridor!, [field]: null } };
      expect(() => buildPacket(holed, entry)).toThrow(MeasurementMissing);
      expect(() => buildPacket(holed, entry)).toThrow(field);
    }
    expect(() => buildPacket({ ...card, corridor: null }, entry)).toThrow(
      MeasurementMissing,
    );
  });

  it("refuses a card paired with another observation's queue entry", () => {
    const card = cardById.get(14740031);
    const entry = entryById.get(14744250);
    if (!card || !entry) throw new Error("the console data is missing an observation");
    expect(() => buildPacket(card, entry)).toThrow(/grounded in neither/);
  });

  it("refuses a field Python would print with a trailing point-zero", () => {
    const card = cardById.get(14740031);
    const entry = entryById.get(14740031);
    if (!card || !entry) throw new Error("14740031 is missing from the console data");
    // str(436400000.5) is "436400000.5" in Python and "436400000.5" here, but
    // str(436400000.0) is "436400000.0" there and "436400000" here, and the difference
    // moves every token that follows it in the rendered packet.
    expect(() => buildPacket({ ...card, rx_freq_hz: 436400000.5 }, entry)).toThrow(
      NotAnInteger,
    );
  });
});

describe("the number rule", () => {
  it("accepts a value quoted at fewer digits than the packet printed", () => {
    // fitted_offset_ppm prints as 15.8; a draft writing 16 is quoting, not inventing.
    expect(codesOf("The offset is 16 ppm across the corridor.")).toEqual([]);
  });

  it("accepts a hertz field in megahertz and in kilohertz", () => {
    expect(codesOf("The pass was received at 436.49 MHz along the corridor.")).toEqual([]);
    expect(codesOf("The corridor half width is 2.0 kHz either side of centre.")).toEqual([]);
  });

  it("accepts the alphabetic spelling of each unit", () => {
    expect(codesOf("The pass was received at 436.49 megahertz.")).toEqual([]);
    expect(codesOf("The corridor half width is 2.0 kilohertz.")).toEqual([]);
    expect(codesOf("The corridor sits 6904 hertz from the catalogue centre.")).toEqual([]);
  });

  it("accepts a percentage of a field on the unit interval, with either spelling", () => {
    // The percent sign is not a word character, so a trailing word boundary made this
    // transform unreachable and 100% was refused as ungrounded.
    expect(codesOf("The model probability is 80.0% for this pass.")).toEqual([]);
    expect(codesOf("The model reads 80.0 percent for this pass.")).toEqual([]);
  });

  it("refuses a percentage of a field the transform is not scoped to", () => {
    // sigma_curved is 3.2, so 320% is arithmetic borrowed from a field the rule does not
    // cover. Dividing any number by a million would otherwise let a frequency justify a
    // sigma.
    expect(codesOf("The curved fit scores 320.0% against the vertical line.")).toEqual([
      "UNGROUNDED_NUMBER",
    ]);
  });

  it("refuses a megahertz conversion of a field that is not in hertz", () => {
    expect(codesOf("The axis reads 0.000096 MHz per pixel across the image.")).toEqual([
      "UNGROUNDED_NUMBER",
    ]);
  });

  it("requires the unit the conversion produces", () => {
    // Right digits, wrong unit by three orders of magnitude: an offset of 6904 Hz written
    // as 6.9 MHz passed with the checker satisfied, because the unit was never read.
    expect(codesOf("The corridor sits 6.9 MHz from the catalogue centre.")).toEqual([
      "UNGROUNDED_NUMBER",
    ]);
    expect(unitAfter(" MHz from")).toBe("mhz");
    expect(unitAfter(" kilohertz.")).toBe("khz");
    expect(unitAfter("% for")).toBe("%");
    expect(unitAfter(" degrees")).toBe(null);
    // The boundary is what stops a unit matching inside a word.
    expect(unitAfter(" Hzeroth")).toBe(null);
  });

  it("reads a thousands separator and an explicit sign", () => {
    // Python strips commas and every leading plus before parsing. Both spellings quote the
    // packet rather than adding to it.
    expect(codesOf("The pass was received at 436,490,000 Hz.")).toEqual([]);
    expect(codesOf("The corridor sits +6904 Hz from the catalogue centre.")).toEqual([]);
    expect(groundedNumber("436,490,000", " Hz", samplePacket())).toBe(true);
    expect(groundedNumber("+6904", " Hz", samplePacket())).toBe(true);
  });

  it("carries the literal and the unit structurally, not only in the message", () => {
    const verdict = verifyNote("The downlink sits at 437.5 MHz.", samplePacket());
    expect(verdict.violations).toEqual([
      {
        code: "UNGROUNDED_NUMBER",
        detail: "'437.5' is not in the evidence packet",
        literal: "437.5",
        unit: "mhz",
      },
    ]);
  });
});

describe("the time rule", () => {
  const early = samplePacket({ closest_approach_fraction: 0, pass_duration_s: 284 });
  const middle = samplePacket({ closest_approach_fraction: 0.5, pass_duration_s: 300 });

  it("reads all three phrasings of a position in seconds", () => {
    for (const draft of [
      "Look around the 284-second mark for the trace.",
      "The corridor crosses the centre 284 seconds into the pass.",
      "At t = 284 s the corridor is narrowest.",
      "Look near 284 seconds into the pass.",
    ]) {
      expect(verifyNote(draft, early).codes, draft).toContain("MISLOCATED_TIME_CLAIM");
    }
  });

  it("reads a fraction of the pass offered as a position", () => {
    expect(timeClaimViolations("The trace is strongest at 1.00 of the pass.", early)).toEqual(
      [
        {
          code: "MISLOCATED_TIME_CLAIM",
          detail: "places the claim at 1.00 of the pass, but closest approach is at 0.00.",
          literal: "1.00",
          unit: "fraction",
        },
      ],
    );
    expect(timeClaimViolations("The trace is strongest at 0.50 of the pass.", middle)).toEqual(
      [],
    );
  });

  it("reads the words that place a claim without a number", () => {
    expect(codesOf("The trace is strongest late in the pass.", early)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
    expect(codesOf("The best evidence sits at the end of the pass.", early)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
    expect(codesOf("Look halfway through the recording.", early)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
    // The same three sentences about a pass whose closest approach is in the middle: one
    // right, two wrong. A rule that fired on the word rather than on the geometry would
    // refuse all three.
    expect(codesOf("Look halfway through the recording.", middle)).toEqual([]);
    expect(codesOf("The trace is strongest late in the pass.", middle)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
    expect(codesOf("The trace is strongest early in the pass.", middle)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
  });

  it("holds the tolerance at a tenth of the recording, with a floor", () => {
    expect(TIME_TOLERANCE_FRACTION).toBe(0.1);
    expect(TIME_TOLERANCE_FLOOR_S).toBe(5);
    // 150 s is closest approach on the 300 s pass, so 178 s is inside a 30 s tolerance and
    // 182 s is outside it. The inside case asks the rule directly, because 178 is not a
    // token of this packet and the number rule refuses it on its own. That refusal is the
    // right one for a number nobody measured, and reading the whole verdict here would
    // report it as a time objection.
    expect(timeClaimViolations("Look at the 178-second mark.", middle)).toEqual([]);
    expect(codesOf("Look at the 182-second mark.", middle)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
    // A twenty-second pass gets the floor rather than two seconds.
    const brief = samplePacket({ pass_duration_s: 20, closest_approach_fraction: 0.5 });
    expect(timeClaimViolations("Look at the 14-second mark.", brief)).toEqual([]);
    expect(codesOf("Look at the 16-second mark.", brief)).toContain(
      "MISLOCATED_TIME_CLAIM",
    );
  });

  it("reports one violation per distinct time, however many phrasings carry it", () => {
    const verdict = timeClaimViolations(
      "At t = 284 s, that is the 284-second mark, 284 seconds into the pass.",
      early,
    );
    expect(verdict.length).toBe(1);
  });

  it("says nothing about a pass with no duration", () => {
    expect(
      timeClaimViolations("Look at the 284-second mark.", samplePacket({ pass_duration_s: 0 })),
    ).toEqual([]);
  });
});

describe("the entity rule", () => {
  it("refuses a reason code the queue did not raise", () => {
    expect(codesOf("The queue flagged this as STALE_CATALOGUE_FREQ_DRIFT.")).toEqual([
      "UNGROUNDED_ENTITY",
    ]);
  });

  it("accepts the reason code the queue did raise", () => {
    expect(codesOf("The queue flagged this as MODEL_LABEL_DISAGREE.")).toEqual([]);
  });

  it("refuses a label that is not this observation's", () => {
    // The sample packet's network label is without-signal.
    expect(codesOf("The network label is with-signal, which disagrees.")).toEqual([
      "UNGROUNDED_ENTITY",
    ]);
    expect(codesOf("The network label is without-signal, which disagrees.")).toEqual([]);
  });

  it("leaves unknown alone, because it is also an ordinary word", () => {
    // A substring test on "unknown" refused this sentence, which breaks no rule, and no
    // control draft covered the case so the receipt reported a false-refusal rate of zero
    // while the checker was refusing sentences.
    expect(codesOf("The direction of the drift is unknown here.")).toEqual([]);
  });
});

describe("the confirmation rule", () => {
  it("refuses the indicative and the participle whatever precedes them", () => {
    for (const draft of [
      "The offset is large and confirms a catalogue drift.",
      "A vertical line at this offset means confirmed mistuning.",
      "The identity of the transmitter is confirmed by the offset.",
    ]) {
      expect(codesOf(draft), draft).toContain("OVERCLAIM");
    }
  });

  it("refuses the noun and the gerund when they assert", () => {
    expect(codesOf("After confirmation of the pass the label was corrected.")).toContain(
      "OVERCLAIM",
    );
    expect(codesOf("Confirming a pass here, the label disagrees.")).toContain("OVERCLAIM");
    expect(codesOf("The drift requires confirmed identity of the transmitter.")).toContain(
      "OVERCLAIM",
    );
  });

  it("allows a purpose clause, which is what the note is asked to write", () => {
    // A single pattern on the verb stem refused "to confirm this, look for a signal" in
    // eight of twenty-five drafts.
    for (const draft of [
      "To confirm what is there, look along the predicted corridor.",
      "A pass at a higher peak elevation could confirm the drift.",
      "Settle it by confirming whether a drifting line runs through the corridor.",
      "A second capture would help confirm the reading.",
    ]) {
      expect(codesOf(draft), draft).toEqual([]);
    }
  });

  it("names the phrase it objected to", () => {
    expect(assertsAConfirmation("the offset confirms a drift")).toBe("confirms");
    expect(assertsAConfirmation("after confirmation of the pass")).toBe("after confirmation");
    expect(assertsAConfirmation("to confirm this, look here")).toBe(null);
  });
});

describe("the permission rules", () => {
  it("refuses each claim the contract puts outside this system", () => {
    const cases: ReadonlyArray<readonly [string, string]> = [
      ["The pass was decoded cleanly.", "mentions decoding"],
      ["The telemetry read cleanly.", "mentions telemetry"],
      ["The offset proves a drift.", "mentions proof"],
      ["This was a mission success for the operator.", "mentions mission outcome"],
      ["The reviewer should endorse this reading.", "mentions endorsement"],
      ["A vote on the network would settle it.", "mentions voting on the public network"],
      ["Upload the corrected label to the network.", "mentions writing to the public network"],
      ["The satellite was heard during the pass.", "mentions an asserted detection"],
    ];
    for (const [draft, detail] of cases) {
      const verdict = verifyNote(draft, samplePacket());
      expect(verdict.codes, draft).toContain("OVERCLAIM");
      expect(
        verdict.violations.map((violation) => violation.detail),
        draft,
      ).toContain(detail);
    }
  });

  it("refuses each absolute a four-sentence note cannot support", () => {
    for (const [draft, detail] of [
      ["A vertical line always means a mistuned receiver.", "says always"],
      ["A curved trace never appears at this offset.", "says never"],
      ["A second reading is impossible from this image.", "says impossible"],
      ["The corridor guarantees the trace sits inside it.", "says guarantee"],
      ["The label is definitely wrong here.", "says certainty"],
    ] as const) {
      const verdict = verifyNote(draft, samplePacket());
      expect(verdict.codes, draft).toContain("ABSOLUTE_CLAIM");
      expect(verdict.violations.map((v) => v.detail), draft).toContain(detail);
    }
  });

  it("refuses a voice that is not a reviewer's", () => {
    for (const [draft, detail] of [
      ["I think the corridor looks wrong here.", "uses first person"],
      ["My reading of the corridor is that it is offset.", "uses first person"],
      ["As an AI, the corridor reads as offset.", "uses self-reference"],
      ["See https://network.satnogs.org for the waterfall.", "uses a URL"],
      ["## Corridor\nThe label disagrees with the model.", "uses a markdown heading"],
    ] as const) {
      const verdict = verifyNote(draft, samplePacket());
      expect(verdict.codes, draft).toContain("WRONG_VOICE");
      expect(verdict.violations.map((v) => v.detail), draft).toContain(detail);
    }
  });

  it("finds a heading on a line that is not the first", () => {
    // Python anchors ^ after "\n" under re.M and the JavaScript m flag also anchors after
    // "\r", so the line split is done on "\n" alone.
    expect(codesOf("The label disagrees.\n### Corridor")).toContain("WRONG_VOICE");
    expect(codesOf("The label disagrees.\r### Corridor")).not.toContain("WRONG_VOICE");
  });

  it("keeps the lower-case pronoun out of the first-person check", () => {
    // "i" as a bare word matches nothing and "I" would match everywhere if the draft were
    // lower-cased first, so case is read on the unlowered text.
    expect(codesOf("The corridor sits inside the predicted band.")).toEqual([]);
    expect(codesOf("I see the corridor inside the band.")).toContain("WRONG_VOICE");
  });
});

describe("the shape rules", () => {
  it("refuses an empty draft and stops there", () => {
    const verdict = verifyNote("   \n  ", samplePacket());
    expect(verdict.ok).toBe(false);
    expect(verdict.violations).toEqual([{ code: "EMPTY", detail: "the draft is empty" }]);
  });

  it("counts characters as code points, the way Python does", () => {
    const long = `The corridor sits 6904 Hz from the centre. ${"x".repeat(MAX_CHARS)}`;
    const verdict = verifyNote(long, samplePacket());
    expect(verdict.codes).toContain("TOO_LONG");
    expect(verdict.violations[0]?.detail).toBe(
      `${Array.from(long.trim()).length} characters, limit ${MAX_CHARS}`,
    );
    // An astral character is one character in Python and two UTF-16 code units here.
    const astral = "a".repeat(MAX_CHARS - 1) + "\u{1F6F0}\u{1F6F0}";
    expect(Array.from(astral).length).toBe(MAX_CHARS + 1);
    expect(astral.length).toBe(MAX_CHARS + 3);
    expect(verifyNote(astral, samplePacket()).violations[0]?.detail).toBe(
      `${MAX_CHARS + 1} characters, limit ${MAX_CHARS}`,
    );
  });

  it("allows five sentences and refuses six", () => {
    expect(codesOf("One. Two. Three. Four. Five.")).toEqual([]);
    const verdict = verifyNote("One. Two. Three. Four. Five. Six.", samplePacket());
    expect(verdict.codes).toEqual(["TOO_MANY_SENTENCES"]);
    expect(verdict.violations[0]?.detail).toBe(`6 sentences, limit ${MAX_SENTENCES}`);
  });

  it("reports every reason rather than stopping at the first", () => {
    // The distribution of codes is what says whether the prompt or the model is the
    // problem, so a draft that breaks four rules has to report four.
    const verdict = verifyNote(
      "I think the pass was decoded at 437.5 MHz and this always confirms a drift.",
      samplePacket(),
    );
    expect(verdict.codes).toEqual([
      "ABSOLUTE_CLAIM",
      "OVERCLAIM",
      "UNGROUNDED_NUMBER",
      "WRONG_VOICE",
    ]);
  });
});

describe("the fixture builders", () => {
  it("swaps the last two digits, or adds one when that would change nothing", () => {
    expect(transposedDigits(6904)).toBe(6940);
    expect(transposedDigits(-6904)).toBe(6940);
    expect(transposedDigits(6900)).toBe(69007);
    expect(transposedDigits(7)).toBe(77);
  });

  it("adds precision until a wrong-unit number is genuinely ungrounded", () => {
    const packet = samplePacket();
    for (const [draft, code] of adversarialDrafts(packet)) {
      if (code !== "UNGROUNDED_NUMBER") continue;
      expect(verifyNote(draft, packet).codes, draft).toContain("UNGROUNDED_NUMBER");
    }
  });
});
