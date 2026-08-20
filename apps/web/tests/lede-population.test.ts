/**
 * The lede's permutation sentence must count the population, not the budget.
 *
 * Three of four blind judge seats found this independently, and two named it as the
 * single change to make before submitting. `app/page.tsx` bound the sentence to
 * `primary.n_queue_examined`, which is the review budget of 50, where the population
 * of 87 belongs. The first screen of the console read "random orderings of the same 50
 * observations" and then "a budget of 50 over 50 caps every possible ordering at
 * 1.740x". Fifty conflicts in fifty observations at a budget of fifty caps at 1.0, so
 * the sentence contradicted itself in its own next clause, in the paragraph whose code
 * comment says it exists to put the strongest evidence on the first screen.
 *
 * `tsc` cannot catch it: both fields are numbers on objects that are both in scope, so
 * the wrong one typechecks. `next build` renders it. No arithmetic test touches page
 * copy. The README had it right the whole time, because the console and the documents
 * are written by different paths, so no generator `--check` compares them.
 *
 * The deeper cause was that `build_console_data.py` did not publish the circularity
 * receipt's `reproduction` block at all, so the payload held no field carrying 87 and
 * the budget was the only population-shaped number reachable. This test pins both
 * halves: the block is published, and the sentence reads from it.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "..");

const SOURCE = readFileSync(path.join(ROOT, "app/page.tsx"), "utf8");

const EVALUATION = JSON.parse(
  readFileSync(path.join(ROOT, "public/data/evaluation.json"), "utf8"),
) as {
  circularity: {
    reproduction: {
      n_population: number;
      n_conflicts: number;
      budget: number;
    };
  };
  gate6: { per_split: Record<string, { n_queue_examined: number }> };
};

/** The paragraph the permutation result is in, from its class to its closing tag. */
function ledeWin(): string {
  const at = SOURCE.indexOf('className="lede-body lede-win"');
  expect(at, "app/page.tsx no longer has a .lede-win paragraph").toBeGreaterThan(-1);
  const closes = SOURCE.indexOf("</p>", at);
  return SOURCE.slice(at, closes === -1 ? at + 2000 : closes);
}

describe("the lede's permutation sentence", () => {
  it("reads its population from the reproduction block", () => {
    const paragraph = ledeWin();
    expect(paragraph).toContain("circularity.reproduction.n_population");
  });

  it("does not reach for the review budget as a population", () => {
    const paragraph = ledeWin();
    expect(
      paragraph.includes("n_queue_examined"),
      "the .lede-win paragraph names n_queue_examined, which is the review budget. " +
        "That produced 'a budget of 50 over 50 caps every possible ordering at 1.740x' " +
        "on the console's first screen. Use circularity.reproduction.n_population.",
    ).toBe(false);
  });

  it("reads its budget and conflict count from the same block", () => {
    const paragraph = ledeWin();
    expect(paragraph).toContain("circularity.reproduction.budget");
    expect(paragraph).toContain("circularity.reproduction.n_conflicts");
  });
});

describe("the payload the sentence reads from", () => {
  it("publishes the population, the conflicts and the budget", () => {
    const repro = EVALUATION.circularity.reproduction;
    expect(Number.isInteger(repro.n_population)).toBe(true);
    expect(Number.isInteger(repro.n_conflicts)).toBe(true);
    expect(Number.isInteger(repro.budget)).toBe(true);
  });

  it("carries a population larger than the budget spent on it", () => {
    const repro = EVALUATION.circularity.reproduction;
    // The whole defect in one assertion. A budget equal to its population caps every
    // ordering at 1.0, so a page quoting 1.740 against equal numbers is impossible.
    expect(repro.budget).toBeLessThan(repro.n_population);
  });

  it("is the same budget gate 6 was measured at", () => {
    const repro = EVALUATION.circularity.reproduction;
    const chronological = EVALUATION.gate6.per_split.chronological;
    expect(chronological, "evaluation.json lost its chronological split").toBeDefined();
    expect(repro.budget).toBe(chronological?.n_queue_examined);
  });
});
