/**
 * The accessible label on the elevation and Doppler instrument.
 *
 * The defect this pins: the sentence was assembled from the first and last sample and
 * always said the Doppler curve ran "down through zero, crossing zero at the same
 * instant elevation peaks". On observation 14744250 the recording window lies entirely
 * on one side of closest approach in Doppler terms, running from -5870.4 Hz to
 * -7227.6 Hz with no sign change, so the label asserted a crossing that did not happen.
 * A sighted reader can see the curve staying below the zero line. A reader using a
 * screen reader receives only the sentence, so for that reader the console contradicted
 * its own data. Recorded as BLOCKING in docs/REVIEW_ENGINEERING.md:89.
 *
 * The fix conditions the sentence on the series. These are the three branches, plus the
 * absent-series case, because a branch with no test is how the first version passed
 * every check that existed at the time.
 */
import { describe, expect, it } from "vitest";

import {
  indexOfFirstSignChange,
  indexOfPeakElevation,
  passTimeSeriesLabel,
} from "@/components/PassTimeSeries";

// Observation 14744250, the one shipped card whose Doppler series never changes sign.
// The endpoints are the values read out of cards.json when the finding was raised.
const ONE_SIDED = {
  durationS: 284,
  fracs: [0, 0.25, 0.5, 0.75, 1],
  els: [5.2, 22.4, 37.1, 20.8, 4.6],
  dops: [-5870.4, -6200.1, -6700.9, -7000.2, -7227.6],
};

// A modelled pass: the crossing and the elevation peak fall on the same sample.
const CROSSES_AT_PEAK = {
  durationS: 300,
  fracs: [0, 0.25, 0.5, 0.75, 1],
  els: [5, 20, 40, 20, 5],
  dops: [3000, 1500, -1500, -3000, -4000],
};

// A pass where they do not: the peak is at index 1 and the sign change at index 3.
const CROSSES_AWAY_FROM_PEAK = {
  durationS: 300,
  fracs: [0, 0.2, 0.4, 0.6, 0.8, 1],
  els: [5, 40, 30, 20, 10, 5],
  dops: [2000, 1000, 500, -500, -1500, -2500],
};

describe("indexOfFirstSignChange", () => {
  it("returns -1 for a series that stays on one side of zero", () => {
    expect(indexOfFirstSignChange(ONE_SIDED.dops)).toBe(-1);
  });

  it("returns the index of the first sample past the change", () => {
    expect(indexOfFirstSignChange(CROSSES_AT_PEAK.dops)).toBe(2);
    expect(indexOfFirstSignChange(CROSSES_AWAY_FROM_PEAK.dops)).toBe(3);
  });

  it("names the absence rather than returning a plausible index", () => {
    expect(indexOfFirstSignChange(null)).toBe(-1);
  });

  it("never reports index 0, because one sample cannot show a change", () => {
    // A series whose first sample is already negative has no crossing inside the
    // window. Reporting 0 would make the label claim one at the very first instant.
    expect(indexOfFirstSignChange([-100, -200, -300])).toBe(-1);
  });
});

describe("indexOfPeakElevation", () => {
  it("finds the highest sample", () => {
    expect(indexOfPeakElevation(ONE_SIDED.els)).toBe(2);
    expect(indexOfPeakElevation(CROSSES_AWAY_FROM_PEAK.els)).toBe(1);
  });

  it("keeps the first of two equal maxima rather than drifting to the later one", () => {
    expect(indexOfPeakElevation([10, 40, 40, 10])).toBe(1);
  });
});

describe("passTimeSeriesLabel", () => {
  it("says the curve does not cross zero when the window is one-sided", () => {
    const label = passTimeSeriesLabel(ONE_SIDED);

    // The assertion that fails against the endpoint-derived version: that one said
    // "crossing zero at the same instant elevation peaks" for this exact series.
    expect(label).not.toContain("crossing zero");
    expect(label).toContain(
      "The recording window lies entirely on one side of closest approach, so the"
      + " Doppler shift does not cross zero within it.",
    );
    // The endpoints are still reported, because the reader needs the range even when
    // there is no crossing to describe.
    expect(label).toContain("runs from -5870 Hz to -7228 Hz");
    expect(label).toContain("Elevation rises to 37.1 degrees");
  });

  it("keeps the coincidence claim when the series shows it", () => {
    const label = passTimeSeriesLabel(CROSSES_AT_PEAK);

    expect(label).toContain(
      "crossing zero at the same instant elevation peaks.",
    );
  });

  it("gives the separation in seconds when the crossing is not at the peak", () => {
    const label = passTimeSeriesLabel(CROSSES_AWAY_FROM_PEAK);

    // (0.6 - 0.2) of a 300 second pass. Asserting the number rather than the shape of
    // the sentence, because a label that says "0 seconds from the peak" is the same
    // false coincidence claim in different words.
    expect(label).toContain(
      "crossing zero 120 seconds from the elevation peak rather than at it.",
    );
    expect(label).not.toContain("at the same instant");
  });

  it("names an absent Doppler series instead of describing one", () => {
    const label = passTimeSeriesLabel({ ...ONE_SIDED, dops: null });

    expect(label).toContain("The Doppler shift is not measurable for this record.");
    expect(label).not.toContain("Hz");
  });

  it("opens with the duration and the peak for every branch", () => {
    for (const series of [ONE_SIDED, CROSSES_AT_PEAK, CROSSES_AWAY_FROM_PEAK]) {
      expect(passTimeSeriesLabel(series)).toMatch(
        /^Elevation and Doppler shift against pass time over \d+ seconds\. Elevation rises to [\d.]+ degrees and falls back\./,
      );
    }
  });
});
