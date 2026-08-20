/**
 * The field behind the first screen is a chart, so its encoding is checked like one.
 *
 * A decorative background that goes wrong is a background that looks slightly different. A
 * chart that goes wrong tells a reader something false, and this one is a chart: every point
 * is one of the 407 observations the queue ranks. So the four things it claims are asserted
 * here against the real queue rather than against a fixture, because the failure worth
 * catching is a change in the data the encoding was written for.
 */

import { describe, expect, it } from "vitest";

import {
  FIELD_PPM_CEILING,
  FIELD_REASONS,
  FIELD_REASON_TOKENS,
  fieldPoints,
  reasonIndex,
} from "@/lib/field";
import { queue } from "@/lib/data";

const points = fieldPoints(queue.entries);

describe("the field encoding", () => {
  it("draws one point per ranked observation", () => {
    expect(points.length).toBe(queue.entries.length);
    expect(points.length).toBeGreaterThan(300);
  });

  it("puts rank 1 at the centre and the tail at the rim", () => {
    const ranks = points.map((point) => point.rank01);
    expect(ranks.at(0)).toBe(0);
    expect(ranks.at(-1)).toBe(1);
    // Strictly increasing, so the spiral reads outward in rank order rather than in file
    // order. Asserted as a sort and a cardinality rather than a loop over indices, which
    // is the same claim without reaching past the end of the array to make it.
    expect(ranks).toEqual([...ranks].sort((a, b) => a - b));
    expect(new Set(ranks).size).toBe(ranks.length);
  });

  it("spreads brightness across the queue's own range of scores", () => {
    const values = points.map((point) => point.value01);
    expect(Math.min(...values)).toBe(0);
    expect(Math.max(...values)).toBe(1);
    // A field normalised to 0..1 instead of to the observed 0.23..0.88 would be
    // uniformly bright, so the spread is asserted rather than only the bounds.
    const mean = values.reduce((a, b) => a + b, 0) / values.length;
    expect(mean).toBeGreaterThan(0.05);
    expect(mean).toBeLessThan(0.95);
  });

  it("moves only the observations that have a fitted offset", () => {
    const withFit = queue.entries.filter((e) => e.fitted_offset_ppm !== null).length;
    expect(points.filter((point) => point.fitted).length).toBe(withFit);
    expect(withFit).toBeLessThan(points.length);
    expect(withFit).toBeGreaterThan(10);
    for (const point of points) {
      expect(point.ppm).toBeGreaterThanOrEqual(0);
      expect(point.ppm).toBeLessThanOrEqual(1);
    }
  });

  it("keeps a measured zero apart from an absent measurement", () => {
    // Two observations were fitted at exactly -0.0 ppm. Both are still, like the 320 with
    // no fit at all, and the field has to be able to say which kind of still each one is:
    // a receiver on frequency and a pass nobody measured are not the same result.
    const zeroFits = points.filter((point) => point.fitted && point.ppm === 0);
    const noFit = points.filter((point) => !point.fitted);
    expect(zeroFits.length).toBe(
      queue.entries.filter((e) => e.fitted_offset_ppm === 0).length,
    );
    expect(zeroFits.length).toBeGreaterThan(0);
    expect(noFit.every((point) => point.ppm === 0)).toBe(true);
  });

  it("has a colour for every criterion the queue actually raised", () => {
    // One token per criterion, or the shader and the legend index different lists.
    expect(FIELD_REASON_TOKENS.length).toBe(FIELD_REASONS.length);
    const raised = new Set(queue.entries.flatMap((entry) => entry.reasons));
    for (const reason of raised) {
      expect(FIELD_REASONS as readonly string[], reason).toContain(reason);
    }
    for (const point of points) {
      expect(point.reason).toBeGreaterThanOrEqual(0);
      expect(point.reason).toBeLessThan(FIELD_REASONS.length);
    }
  });

  it("refuses a criterion it has no colour for, rather than defaulting to grey", () => {
    expect(() => reasonIndex(["DEAD_CAPTURE"])).toThrow(/no colour for it/);
    // The absence of a criterion is not a criterion, so anything else outranks it.
    expect(reasonIndex(["NO_REASON", "STALE_CATALOGUE_FREQ"])).toBe(
      FIELD_REASONS.indexOf("STALE_CATALOGUE_FREQ"),
    );
    expect(reasonIndex(["NO_REASON"])).toBe(0);
    expect(reasonIndex([])).toBe(0);
  });

  it("clamps the drift rather than letting one outlier set the scale", () => {
    const template = queue.entries.at(0);
    if (!template) throw new Error("the queue is empty");
    const extreme = fieldPoints([
      { ...template, fitted_offset_ppm: FIELD_PPM_CEILING * 10 },
    ]);
    expect(extreme.at(0)?.ppm).toBe(1);
    expect(extreme.at(0)?.fitted).toBe(true);
  });
});
