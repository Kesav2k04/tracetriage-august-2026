/**
 * Every number the film displays, checked against the receipt it came from.
 *
 * This is the same discipline tests/test_explainer_gate4_values.py applies to the
 * repository's Manim clips, with one difference: the film imports its receipts
 * rather than duplicating their values, so this file's job is not to catch a
 * mistyped constant. It is to catch the three failures that survive an import.
 *
 *   1. A key path that resolves today and stops resolving after a rename, leaving a
 *      stale figure inside an mp4 nobody can diff.
 *   2. A display string that no longer matches the value it was formatted from, or
 *      that rounds a measurement into something it is not.
 *   3. A number typed into a beat by hand instead of read, which is exactly what
 *      this film exists to argue against.
 *
 * A video is two megabytes of H.264 and a wrong figure in it passes every other
 * check this repository runs. If this file fails, the fix is to re-render.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { resolve } from "../src/claim";
import {
  ALL_CLAIMS,
  colophon,
  corpus,
  FILE,
  gate3Result,
  gates,
  HERO_OBS_ID,
  lift,
  physics,
  reviewQueue,
} from "../src/data";
import { BEATS, FILM_FRAMES } from "../src/Film";
import { FPS, HEIGHT, token, WIDTH } from "../src/theme";

const REPO = join(__dirname, "..", "..");
const OUT = join(__dirname, "..", "out", "tracetriage-film.mp4");
const POSTER = join(__dirname, "..", "out", "tracetriage-film-poster.jpg");

const receipt = (file: string): unknown =>
  JSON.parse(readFileSync(join(REPO, file), "utf-8"));

const CACHE = new Map<string, unknown>();
const cached = (file: string): unknown => {
  if (!CACHE.has(file)) CACHE.set(file, receipt(file));
  return CACHE.get(file);
};

/** A path this test can walk back to the file. Anything else is derived. */
const PLAIN_PATH = /^[A-Za-z_][A-Za-z0-9_]*(\[\d+\]|\.[A-Za-z_][A-Za-z0-9_]*)*$/;

/**
 * The claims whose path is an expression rather than a key, each recomputed by name
 * in the block below. Listed with a count so a new derivation cannot slip in
 * unchecked: an exemption with no number attached to it stops being an exemption.
 */
const DERIVED = [
  "corpus.noVerdict",
  "reviewQueue.criteria.0.firedInBudget",
  "reviewQueue.criteria.1.firedInBudget",
  "reviewQueue.criteria.2.firedInBudget",
  "physics.shiftPx",
  "gate3Result.discriminating",
  "lift.threshold",
  "gates.measured",
  "gates.measuredPassed",
];

describe("every claim names a key that still exists", () => {
  const names = Object.keys(ALL_CLAIMS);

  it("collected the claims the beats read from", () => {
    expect(names.length).toBeGreaterThan(50);
  });

  it("has exactly the derived claims it declares", () => {
    const derived = names.filter(
      (name) => !PLAIN_PATH.test(ALL_CLAIMS[name].path),
    );
    expect(derived.sort()).toEqual([...DERIVED].sort());
    expect(derived).toHaveLength(9);
  });

  it.each(
    Object.entries(ALL_CLAIMS).filter(([, claim]) => PLAIN_PATH.test(claim.path)),
  )("%s resolves to the value the film holds", (_name, claim) => {
    expect(resolve(cached(claim.file), claim.path)).toStrictEqual(claim.value);
  });

  it.each(Object.entries(ALL_CLAIMS))(
    "%s names a file that is in the repository",
    (_name, claim) => {
      expect(existsSync(join(REPO, claim.file))).toBe(true);
    },
  );
});

describe("every display string still says what its value says", () => {
  const numeric = Object.entries(ALL_CLAIMS).filter(
    ([, claim]) => typeof claim.value === "number",
  );

  it("checks a number of them", () => {
    expect(numeric.length).toBeGreaterThan(25);
  });

  /**
   * The one claim printed in a different unit from the one it was measured in.
   * A receive frequency in hertz is unreadable on a slide, so it is shown in
   * megahertz, and the divisor is written down here rather than assumed.
   */
  const SCALED: Record<string, number> = { "physics.rxMhz": 1e6 };

  it.each(numeric)("%s prints its own value", (name, claim) => {
    const printed = claim.display.replace(/,/g, "");
    expect(printed).toMatch(/^[+-]?\d+(\.\d+)?$/);
    const dot = printed.indexOf(".");
    const places = dot === -1 ? 0 : printed.length - dot - 1;
    const value = (claim.value as number) / (SCALED[name] ?? 1);
    // A signed display keeps its sign; an unsigned one may print a magnitude.
    const expected = /^[+-]/.test(claim.display) ? value : Math.abs(value);
    expect(Number(printed)).toBeCloseTo(expected, places);
  });

  it.each(
    Object.entries(ALL_CLAIMS).filter(([, claim]) => typeof claim.value === "string"),
  )("%s prints its own string", (_name, claim) => {
    expect(claim.value as string).toContain(claim.display);
  });
});

describe("the derived claims are arithmetic on the receipts", () => {
  it("observations with no verdict is stored minus decisive", () => {
    const counts = resolve(cached(FILE.manifest), "counts") as Record<string, number>;
    expect(corpus.noVerdict.value).toBe(
      counts.observations_stored - counts.waterfall_status_decisive,
    );
  });

  it("the verdict grid lights exactly the decisive observations", () => {
    const counts = resolve(cached(FILE.manifest), "counts") as Record<string, number>;
    const lit = corpus.verdictMask.filter(Boolean).length;
    expect(lit).toBe(counts.waterfall_status_decisive);
    expect(corpus.verdictMask).toHaveLength(counts.observations_stored);
  });

  it("the criteria counts are the queue rows inside the budget", () => {
    const rows = resolve(cached(FILE.queue), "queue") as {
      reasons: string[];
      within_budget: boolean;
    }[];
    for (const criterion of reviewQueue.criteria) {
      const counted = rows.filter(
        (row) => row.within_budget && row.reasons.includes(criterion.code),
      ).length;
      expect(criterion.firedInBudget.value).toBe(counted);
    }
  });

  it("the criteria inside the budget add up to the conflicts gate 6 counted", () => {
    const inBudget = reviewQueue.criteria.reduce(
      (total, criterion) => total + (criterion.firedInBudget.value as number),
      0,
    );
    expect(inBudget).toBe(lift.queueConflicts.value);
  });

  it("gate 3's discriminating count is its rate times what it scored", () => {
    const gate3 = cached(FILE.gate3);
    expect(gate3Result.discriminating.value).toBe(
      (resolve(gate3, "discriminating_rate") as number) *
        (resolve(gate3, "observations_scored") as number),
    );
    expect(Number.isInteger(gate3Result.discriminating.value)).toBe(true);
  });

  it("the threshold on screen is the one gate 6's wording names", () => {
    const wording = resolve(cached(FILE.queue), "gate6.wording") as string;
    expect(wording).toContain(String(lift.threshold.value));
  });

  it("the measured gates are the ones that were not answered up front", () => {
    const rows = resolve(cached(FILE.provenance), "gate_summary.gates") as {
      verdict: string;
    }[];
    const measured = rows.filter((row) => row.verdict !== "PRE_PASSED");
    expect(gates.measured.value).toBe(measured.length);
    expect(gates.measuredPassed.value).toBe(
      measured.filter((row) => row.verdict === "PASSED").length,
    );
  });
});

describe("the gate tally the film closes on", () => {
  const summary = () =>
    resolve(cached(FILE.provenance), "gate_summary") as {
      gates: { gate: number; title: string; verdict: string }[];
      n_gates: number;
      n_met: number;
    };

  it("shows one row per declared gate", () => {
    expect(gates.rows).toHaveLength(summary().n_gates);
    expect(gates.total.value).toBe(summary().gates.length);
  });

  it("prints the receipt's own verdict word, unsoftened", () => {
    const verdicts = summary().gates.map((row) => row.verdict);
    expect(gates.rows.map((row) => row.verdict.value)).toEqual(verdicts);
  });

  it("counts as met only what the receipt counts as met", () => {
    const met = summary().gates.filter(
      (row) => row.verdict === "PASSED" || row.verdict === "PRE_PASSED",
    ).length;
    expect(gates.met.value).toBe(summary().n_met);
    expect(gates.met.value).toBe(met);
  });
});

describe("the picture in the physics beat is the measurement", () => {
  const card = () => {
    const cards = resolve(cached(FILE.cards), "cards") as { obs_id: number }[];
    const index = cards.findIndex((c) => c.obs_id === HERO_OBS_ID);
    return resolve(cached(FILE.cards), `cards[${index}]`) as Record<string, unknown>;
  };

  it("draws the console's own corridor arrays", () => {
    const corridor = card().corridor as Record<string, number[]>;
    expect(physics.curve.rows).toStrictEqual(corridor.rows);
    expect(physics.curve.predictedPx).toStrictEqual(corridor.predicted_px);
    expect(physics.curve.fittedPx).toStrictEqual(corridor.fitted_px);
  });

  it("slides the curve by the distance the offset says", () => {
    const hzPerPx = card().hz_per_px as number;
    const corridor = card().corridor as Record<string, number>;
    const offset = corridor.fitted_offset_hz;
    // The frequency axis runs against the Doppler sign, which the receipt's own
    // note states, so the pixel shift and the offset in Hz carry opposite signs.
    expect(Math.abs(physics.shiftPx.value) * hzPerPx).toBeCloseTo(
      Math.abs(offset),
      0,
    );
    expect(Math.sign(physics.shiftPx.value)).toBe(-Math.sign(offset));
  });

  it("shows an observation gate 3 could actually be asked of", () => {
    const rows = resolve(cached(FILE.gate3), "observations") as {
      obs_id: number;
      testable: boolean;
      verdict: string;
    }[];
    const row = rows.find((o) => o.obs_id === HERO_OBS_ID);
    expect(row?.testable).toBe(true);
    expect(row?.verdict).toBe("UNCORRECTED");
  });

  it("shows the image whose bytes the colophon names", () => {
    expect(physics.image.src).toContain(String(HERO_OBS_ID));
    expect(colophon.file.value).toContain(physics.image.src);
    expect(existsSync(join(REPO, colophon.file.value as string))).toBe(true);
  });
});

describe("the colophon carries the six obligations DATA_LICENSE.md accepts", () => {
  it("reads the audit row for the file the film displays", () => {
    const rows = resolve(cached(FILE.attribution), "rows") as {
      file: string;
      satnogs_derived: boolean;
      obligations: Record<string, boolean>;
      complete: boolean;
    }[];
    const row = rows.find((r) => r.file === colophon.file.value);
    expect(row).toBeDefined();
    expect(row?.satnogs_derived).toBe(true);
    expect(row?.complete).toBe(true);
    expect(Object.values(row!.obligations).every(Boolean)).toBe(true);
  });

  it("shows all six on screen", () => {
    for (const claim of [
      colophon.recordUrl,
      colophon.artifactUrl,
      colophon.retrievedAt,
      colophon.sha256,
      colophon.licence,
      colophon.licenceUrl,
      colophon.modification,
    ]) {
      expect(claim.display.length).toBeGreaterThan(0);
    }
    expect(colophon.licence.display).toContain("CC BY-SA");
  });
});

describe("the palette is the console's", () => {
  const css = readFileSync(
    join(REPO, "apps", "web", "app", "globals.css"),
    "utf-8",
  );
  const value = (name: string): string | undefined => {
    const found = css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8});`));
    return found?.[1].toLowerCase();
  };

  const PAIRS: [keyof typeof token, string][] = [
    ["uiBackground", "ui-background"],
    ["ui01", "ui-01"],
    ["ui02", "ui-02"],
    ["ui04", "ui-04"],
    ["surfaceRaised", "surface-raised"],
    ["text01", "text-01"],
    ["text02", "text-02"],
    ["text03", "text-03"],
    ["text04", "text-04"],
    ["interactive01", "interactive-01"],
    ["support01", "support-01"],
    ["support03", "support-03"],
    ["live01", "live-01"],
    ["borderSubtle", "border-subtle"],
    ["borderStrong", "border-strong"],
    ["verdictPassed", "verdict-passed"],
    ["verdictNotEstablished", "verdict-not-established"],
    ["verdictFailed", "verdict-failed"],
    ["verdictNotMeasurable", "verdict-not-measurable"],
    ["waterfallGround", "waterfall-ground"],
  ];

  it.each(PAIRS)("%s is the --%s token", (key, name) => {
    expect(token[key]).toBe(value(name));
  });
});

describe("no measurement is typed into a beat by hand", () => {
  /**
   * Values that look like numbers to a scanner and are not measurements: CSS
   * lengths, dash patterns, flex shorthands, colours and the like.
   */
  const CSS_SHAPED =
    /^(-?\d+(\.\d+)?(px|rem|em|%|ms|s|deg|fr)?|(\d+(\.\d+)?\s+)+\d+(\.\d+)?|0 0 auto|100%|#[0-9a-fA-F]{3,8}|\d+ \d+)$/;

  /**
   * Text with a digit in it that is a name rather than a measurement. Three, and
   * each says why. A fourth needs a reason written here before it renders.
   */
  const NAMED = new Set([
    "sha256 of the bytes", // the hash algorithm, a name
    "scaled to the frame, corridor overlay drawn on top, encoded to H.264", // a codec
    "95%", // the confidence level, and it is in the receipt keys: lift_ci95
  ]);

  const sources = ["Title", "Problem", "Queue", "Physics", "Result", "Gates", "Colophon"];

  const strip = (source: string): string =>
    source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/^\s*\/\/.*$/gm, "");

  it.each(sources)("%s has no hand-typed figure in a string", (name) => {
    const source = strip(
      readFileSync(join(__dirname, "..", "src", "beats", `${name}.tsx`), "utf-8"),
    );
    const literals = source.match(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g) ?? [];
    const offenders = literals
      .map((literal) => literal.slice(1, -1))
      .filter((text) => /\d/.test(text))
      .filter((text) => !CSS_SHAPED.test(text))
      .filter((text) => !NAMED.has(text));
    expect(offenders).toEqual([]);
  });

  it.each(sources)("%s has no hand-typed figure in its copy", (name) => {
    let source = strip(
      readFileSync(join(__dirname, "..", "src", "beats", `${name}.tsx`), "utf-8"),
    );
    source = source.replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g, '""');
    source = source.replace(/`(?:[^`\\]|\\.)*`/g, "``");
    // An arrow and a comparison each carry an angle bracket that is not a tag.
    source = source.replace(/=>/g, " ARROW ").replace(/\s[<>]=?\s/g, " CMP ");
    // Everything a brace pair encloses is code, including every numeric prop.
    // The placeholder carries no braces of its own, so an outer pair can collapse
    // once its inner pairs have: leaving "{}" behind would stall the loop.
    let previous = "";
    while (previous !== source) {
      previous = source;
      source = source.replace(/\{[^{}]*\}/g, " BLOCK ");
    }
    // A generic type parameter is not a tag either, and once its braces have
    // collapsed it looks exactly like one.
    source = source.replace(/<\s*BLOCK\s*>/g, " GENERIC ");
    // What is left between a closing angle bracket and the next opening one is
    // the copy a viewer reads. Tag interiors are attributes and are not copy.
    const text: string[] = [];
    for (const match of source.matchAll(/>([^<>]*)</g)) {
      let segment = match[1].split("BLOCK").join(" ");
      for (const named of NAMED) segment = segment.split(named).join(" ");
      if (segment.trim().length > 0) text.push(segment.replace(/\s+/g, " ").trim());
    }
    expect(text.filter((segment) => /\d/.test(segment))).toEqual([]);
    // And the scan has to have seen the copy, or it proves nothing.
    expect(text.join(" ").length).toBeGreaterThan(40);
  });
});

describe("the film is the length and shape the brief asked for", () => {
  it("runs between 75 and 105 seconds", () => {
    const seconds = FILM_FRAMES / FPS;
    expect(seconds).toBeGreaterThanOrEqual(75);
    expect(seconds).toBeLessThanOrEqual(105);
  });

  it("is 1920 by 1080 at 30 frames a second", () => {
    expect([WIDTH, HEIGHT, FPS]).toEqual([1920, 1080, 30]);
  });

  it("spends the most time on the physics and the least on the title", () => {
    const byName = Object.fromEntries(
      BEATS.map((beat) => [beat.name, beat.durationInFrames]),
    );
    expect(byName.Physics).toBe(Math.max(...BEATS.map((b) => b.durationInFrames)));
    expect(byName.Title).toBe(Math.min(...BEATS.map((b) => b.durationInFrames)));
  });
});

describe("the rendered file", () => {
  it("exists, with a poster frame beside it", () => {
    if (!existsSync(OUT)) {
      // A film that has not been rendered is a state worth reporting rather than
      // a broken test, and the report says so out loud.
      console.warn(`no render at ${OUT}; run npm run render`);
      return;
    }
    expect(statSync(OUT).size).toBeGreaterThan(200_000);
    expect(existsSync(POSTER)).toBe(true);
  });

  it("has the duration, resolution and frame rate of the composition", () => {
    if (!existsSync(OUT)) return;
    let probe: string;
    try {
      probe = execFileSync(
        "ffprobe",
        [
          "-v",
          "error",
          "-select_streams",
          "v:0",
          "-show_entries",
          "stream=width,height,r_frame_rate,nb_frames",
          "-of",
          "json",
          OUT,
        ],
        { encoding: "utf-8" },
      );
    } catch {
      console.warn("ffprobe is not on PATH, so the container was not checked");
      return;
    }
    const stream = JSON.parse(probe).streams[0];
    expect(stream.width).toBe(WIDTH);
    expect(stream.height).toBe(HEIGHT);
    expect(stream.r_frame_rate).toBe(`${FPS}/1`);
    expect(Number(stream.nb_frames)).toBe(FILM_FRAMES);
  });
});
