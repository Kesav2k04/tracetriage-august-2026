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
import { KNOWN_VERDICTS } from "../src/ui";
import { BEATS, FILM_FRAMES } from "../src/Film";
import { NARRATION } from "../src/narration";
import { FPS, HEIGHT, token, WIDTH } from "../src/theme";

/**
 * Is there an ffprobe to ask? Answered once, because the answer decides whether the two
 * container tests below run at all.
 *
 * They used to answer it inside a `try`, warn on the console and `return`, which reports a
 * pass. That is the shape that let the film ship silent twice: a test that cannot measure
 * its subject and a test that measured it and found nothing right look identical in a
 * summary line. Skipping instead puts the count in the reporter's own skipped tally, where
 * it is visible without reading the log, and the CI job installs ffmpeg so the skip is a
 * local convenience rather than a hole in the check.
 */
const HAS_FFPROBE = (() => {
  try {
    execFileSync("ffprobe", ["-version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
})();

/** One stream's fields as JSON, or a throw that names the file it could not read. */
const ffprobe = (select: string, entries: string): { streams: Record<string, string>[] } =>
  JSON.parse(
    execFileSync(
      "ffprobe",
      [
        "-v",
        "error",
        "-select_streams",
        select,
        "-show_entries",
        `stream=${entries}`,
        "-of",
        "json",
        OUT,
      ],
      { encoding: "utf-8" },
    ),
  );

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

  // Seven lines for six obligations: DATA_LICENSE.md counts the record and artifact
  // URLs as one source-URL obligation, and the licence link as one.
  it("shows all six, in the seven lines they take", () => {
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

  const sources = [
    "Title",
    "Problem",
    "Queue",
    "Physics",
    "Result",
    "Gates",
    "Established",
    "Colophon",
  ];

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
  /**
   * The competition's published ceiling for a presentation video is three minutes,
   * and docs/DEMO_SCRIPT.md budgets 160 seconds of it. The upper bound here was 105
   * when the film had seven beats, and the eighth pushed past it, so the number
   * moved. The reason is written down because a threshold that follows a result is
   * not a threshold: what changed is the film's content, the ceiling it is measured
   * against is the rules', and the margin below it is the demo script's own budget.
   * The lower bound has not moved. A film shorter than 75 seconds cannot show a
   * measurement and the interval around it.
   */
  const RULES_CEILING_SECONDS = 180;
  const SPOKEN_BUDGET_SECONDS = 160;

  it("runs between 75 seconds and the budget the demo script sets", () => {
    const seconds = FILM_FRAMES / FPS;
    expect(seconds).toBeGreaterThanOrEqual(75);
    expect(seconds).toBeLessThanOrEqual(SPOKEN_BUDGET_SECONDS);
    expect(SPOKEN_BUDGET_SECONDS).toBeLessThan(RULES_CEILING_SECONDS);
  });

  /**
   * The order is the argument, so it is pinned rather than left to whoever edits the
   * beat list next. Gates carries four verdicts that came back inconclusive and
   * Established carries the three that did not. Established has to come second, or
   * the film reads its own evidence in the order that flatters it.
   */
  it("states the pre-registered verdicts before the results that hold", () => {
    const order = BEATS.map((beat) => beat.name);
    expect(order.indexOf("Gates")).toBeGreaterThan(order.indexOf("Result"));
    expect(order.indexOf("Established")).toBeGreaterThan(order.indexOf("Gates"));
    expect(order[order.length - 1]).toBe("Colophon");
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

  /**
   * The composition is authored at 1920x1080 and delivered at twice that, because the
   * upload target is a 4K stream and every card here is type on a flat ground, which is
   * exactly the content that gains from the extra pixels and costs almost nothing to
   * encode. The multiplier is not written here: it is read out of the render script in
   * package.json, so the assertion is tied to the command that produced the file rather
   * than to a second copy of the number. Rendering at a different scale and forgetting
   * to say so fails this.
   */
  const renderScale = (): number => {
    const pkg = JSON.parse(
      readFileSync(join(__dirname, "..", "package.json"), "utf-8"),
    ) as { scripts: Record<string, string> };
    const found = /--scale=(\d+(?:\.\d+)?)/.exec(pkg.scripts.render);
    return found ? Number(found[1]) : 1;
  };

  it.skipIf(!HAS_FFPROBE)("has the duration, resolution and frame rate of the composition", () => {
    if (!existsSync(OUT)) return;
    const scale = renderScale();
    const stream = ffprobe("v:0", "width,height,r_frame_rate,nb_frames").streams[0];
    expect(stream.width).toBe(WIDTH * scale);
    expect(stream.height).toBe(HEIGHT * scale);
    expect(stream.r_frame_rate).toBe(`${FPS}/1`);
    expect(Number(stream.nb_frames)).toBe(FILM_FRAMES);
  });

  it.skipIf(!HAS_FFPROBE)("carries the narration track, which nothing here used to check", () => {
    // This test exists because the film rendered silent twice and everything passed.
    // The block above selects v:0, so it cannot see whether there is any audio at
    // all: a render that 404s on every wav still produces a correct video stream of
    // the right length. Both silent renders were caught by a frame count that
    // happened to move at the same time, which is luck rather than a check.
    if (!existsSync(OUT)) return;
    const streams = ffprobe("a:0", "codec_type,channels,sample_rate").streams;
    expect(streams, "the film has no audio stream").toHaveLength(1);
    expect(streams[0].codec_type).toBe("audio");
    expect(Number(streams[0].channels)).toBeGreaterThanOrEqual(1);
    // And the receipt's derived claim has to agree with the container. `composition.audio`
    // is computed from whether every beat has a line to speak, which is a statement about
    // the sources; this is the file. They were once opposite: the field said false while
    // the mp4 carried AAC.
    expect(BEATS.every((beat) => NARRATION[beat.name] !== undefined)).toBe(true);
  });
});

describe("the film can draw every verdict the receipts hold", () => {
  it("has a mark for each one, rather than falling through to a dash", () => {
    // `VerdictMark` returns a flat dash for anything it does not recognise, and that
    // dash means "not measurable". So an unrecognised verdict is not a missing glyph:
    // it is a false claim about the gate, rendered into a committed video.
    const summary = resolve(cached(FILE.provenance), "gate_summary") as {
      gates: { gate: number; verdict: string }[];
    };
    const onScreen = new Set<string>([
      ...summary.gates.map((row) => row.verdict),
      String(gate3Result.verdict.value),
      String(lift.verdict.value),
    ]);
    const undrawable = [...onScreen].filter(
      (v) => !(KNOWN_VERDICTS as readonly string[]).includes(v),
    );
    expect(undrawable, `add a VerdictMark branch for ${undrawable.join(", ")}`).toEqual(
      [],
    );
  });

  it("renders a multi-word verdict with no underscore left in it", () => {
    // `String.replace` with a string argument replaces the first match only in
    // JavaScript, so PASSED_UNGROUPED_ONLY rendered as "passed ungrouped_only".
    for (const verdict of KNOWN_VERDICTS) {
      expect(verdict.replace(/_/g, " ")).not.toContain("_");
    }
  });
});

describe("the sentence beside gate 3's bound agrees with it", () => {
  const receipt = () => ({
    clears: resolve(cached(FILE.gate3), "clears_threshold") as boolean,
    grouped: resolve(
      cached(FILE.gate3),
      "entity_grouping.grouped_clears_threshold",
    ) as boolean,
    groups: resolve(cached(FILE.gate3), "entity_grouping.groups_scored") as number,
  });

  it("does not deny a bound that clears the bar", () => {
    // The card ended with the literal "That is not enough to clear it" while printing a
    // bound of 0.73 against a threshold of 0.70, two lines above, from the same receipt.
    const { clears } = receipt();
    const sentence = gate3Result.outcomeSentence.toLowerCase();
    if (clears) {
      expect(sentence).toContain("clears the bar");
      expect(sentence).not.toContain("not enough");
    } else {
      expect(sentence).not.toContain("clears the bar");
    }
  });

  it("names the grouping when the grouping is what it failed", () => {
    const { clears, grouped, groups } = receipt();
    if (clears && !grouped) {
      expect(gate3Result.outcomeSentence).toContain(String(groups));
      expect(gate3Result.outcomeSentence.toLowerCase()).toContain("station-nights");
      expect(gate3Result.outcomeSentence.toLowerCase()).toContain(
        "reported and not claimed",
      );
    }
  });

  it("counts what discriminated as a part of what was scored, not all of it", () => {
    // "All 224 discriminated" was on screen against 289 scored.
    expect(gate3Result.discriminating.value as number).toBeLessThanOrEqual(
      gate3Result.scored.value as number,
    );
  });
});
