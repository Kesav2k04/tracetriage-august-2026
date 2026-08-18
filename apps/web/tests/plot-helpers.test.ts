/**
 * The pure helpers that live beside the plots: the SVG path builder, the replay
 * interpolator, the axis ceiling, the cursor placement and the ground-track frame.
 *
 * The path builder is here because two components carried near-identical copies of it
 * and both chose the SVG command by index, so a series with a missing first point
 * produced a path starting with `L`. That draws nothing at all, with no error anywhere:
 * an empty overlay over a real waterfall, which reads as "the physics found nothing"
 * rather than as a bug. It is now one function, chosen by whether a point has actually
 * been emitted, and this is the test that pins it.
 */
import { describe, expect, it } from "vitest";

import { boundsForPass, type TrackGeometry } from "@/components/GroundTrack";
import { niceCeil, timeSeriesCursorX } from "@/components/PassTimeSeries";
import { sampleAt } from "@/components/PassReplay";
import { svgPolyline } from "@/lib/plot-path";

describe("svgPolyline", () => {
  it("starts with a moveto and continues with linetos", () => {
    expect(svgPolyline([1, 2, 3], [10, 20, 30])).toBe("M10 1L20 2L30 3");
  });

  it("starts with a moveto even when the first point is missing", () => {
    // The defect this replaced: the command was `i === 0 ? "M" : "L"`, so skipping
    // index 0 produced "L20 2L30 3", a path with no moveto. SVG draws nothing for
    // that, and nothing is indistinguishable from an overlay that was never asked for.
    const gappy = [Number.NaN, 2, 3];
    const out = svgPolyline(gappy, [10, 20, 30]);
    expect(out.startsWith("M")).toBe(true);
    expect(out).toBe("M20 2L30 3");
  });

  it("skips a gap rather than interpolating across it", () => {
    const out = svgPolyline([1, 2, 3], [10, Number.NaN, 30]);
    expect(out).toBe("M10 1L30 3");
  });

  it("skips a point whose column is missing from a shorter series", () => {
    const out = svgPolyline([1, 2, 3], [10, 20]);
    expect(out).toBe("M10 1L20 2");
  });

  it("returns an empty string for an empty series, which draws nothing", () => {
    expect(svgPolyline([], [])).toBe("");
    expect(svgPolyline([Number.NaN], [Number.NaN])).toBe("");
  });

  it("rounds to the requested precision and leaves raw values alone otherwise", () => {
    expect(svgPolyline([1.239], [10.006], 2)).toBe("M10.01 1.24");
    expect(svgPolyline([1.239], [10.006])).toBe("M10.006 1.239");
  });

  it("refuses an infinite coordinate, which would otherwise print as Infinity", () => {
    expect(svgPolyline([1, 2], [Number.POSITIVE_INFINITY, 20])).toBe("M20 2");
  });
});

describe("sampleAt", () => {
  it("returns the endpoints exactly", () => {
    expect(sampleAt([0, 10, 20], 0)).toBeCloseTo(0, 9);
    expect(sampleAt([0, 10, 20], 1)).toBeCloseTo(20, 9);
  });

  it("interpolates linearly between the bracketing samples", () => {
    expect(sampleAt([0, 10], 0.5)).toBeCloseTo(5, 9);
    expect(sampleAt([0, 10, 20], 0.25)).toBeCloseTo(5, 9);
  });

  it("returns NaN for an empty series rather than a plausible zero", () => {
    // A zero would be drawn: the replay would show a satellite at zero elevation
    // rather than showing nothing. NaN is what stops it being drawn.
    expect(Number.isNaN(sampleAt([], 0.5))).toBe(true);
  });

  it("returns the only sample for a one-sample series", () => {
    // A single propagated sample is a zero-length pass. x = t * 0 = 0 for every t, so
    // both ends of the interpolation are that sample and the readout holds still.
    expect(sampleAt([42], 0)).toBeCloseTo(42, 9);
    expect(sampleAt([42], 0.5)).toBeCloseTo(42, 9);
    expect(sampleAt([42], 1)).toBeCloseTo(42, 9);
  });

  it("holds at the last sample when t runs past the end", () => {
    expect(sampleAt([0, 10], 1.5)).toBeGreaterThanOrEqual(10);
  });
});

describe("niceCeil", () => {
  it("rounds an axis maximum up to a readable number", () => {
    expect(niceCeil(7_227)).toBeGreaterThanOrEqual(7_227);
    expect(niceCeil(1)).toBeGreaterThanOrEqual(1);
  });

  it("never returns zero, which would collapse the axis", () => {
    // A zero maximum divides by zero in the plot scale, and every point becomes
    // Infinity. A flat Doppler series is real, so this has to have a floor.
    expect(niceCeil(0)).toBeGreaterThan(0);
  });

  it("is monotone, so a larger series never gets a smaller axis", () => {
    let prev = 0;
    for (const v of [0.5, 1, 9, 10, 99, 100, 1_001, 12_345, 98_765]) {
      const c = niceCeil(v);
      expect(c).toBeGreaterThanOrEqual(v);
      expect(c).toBeGreaterThanOrEqual(prev);
      prev = c;
    }
  });
});

describe("timeSeriesCursorX", () => {
  it("is monotone across the pass", () => {
    expect(timeSeriesCursorX(0)).toBeLessThan(timeSeriesCursorX(0.5));
    expect(timeSeriesCursorX(0.5)).toBeLessThan(timeSeriesCursorX(1));
  });

  it("places the two ends at the plot edges", () => {
    const left = timeSeriesCursorX(0);
    const right = timeSeriesCursorX(1);
    expect(right).toBeGreaterThan(left);
    // The cursor and the series share this function so the two cannot disagree about
    // where a fraction sits, which is the reason it is exported at all.
    expect(timeSeriesCursorX(0.5)).toBeCloseTo((left + right) / 2, 9);
  });
});

describe("boundsForPass", () => {
  // The real TrackGeometry, imported rather than approximated. The first version of
  // this fixture invented alt_km, station_lat_deg and station_lon_deg, and an `as
  // never` cast let it compile: four tests then failed at run time inside the function
  // under test, reading index 1 of undefined. A cast that silences the compiler
  // silences the one check that would have caught the wrong field name.
  const geometry = (overrides: Partial<TrackGeometry> = {}): TrackGeometry => ({
    sub_lat_deg: [10, 20, 30],
    sub_lon_deg: [100, 110, 120],
    altitude_km: [500, 500, 500],
    station_lat: 15,
    station_lon: 105,
    elevation_deg: [-5, 40, -5],
    ...overrides,
  });

  it("frames a normal pass and finds closest approach at the elevation peak", () => {
    const out = boundsForPass(geometry());
    expect(out).not.toBeNull();
    expect(out?.iTca).toBe(1);
    expect(out?.halfAngleDeg).toBeGreaterThan(0);
  });

  it("returns null for a single-sample track rather than a degenerate frame", () => {
    // Fewer than two samples cannot make a line, and a frame built from one point has
    // zero span. Returning null makes the caller say so instead of drawing a dot with
    // an axis around it.
    expect(
      boundsForPass(geometry({ sub_lat_deg: [10], sub_lon_deg: [100] })),
    ).toBeNull();
  });

  it("returns null for an empty track", () => {
    expect(
      boundsForPass(geometry({ sub_lat_deg: [], sub_lon_deg: [] })),
    ).toBeNull();
  });

  it("keeps a seam-crossing pass in one frame with the station inside it", () => {
    const out = boundsForPass(
      geometry({
        sub_lon_deg: [178, 179, -179],
        station_lon: -179,
      }),
    );
    expect(out).not.toBeNull();
    const { bounds, stationLon } = out as NonNullable<typeof out>;
    expect(stationLon).toBeGreaterThanOrEqual(bounds.lonMin);
    expect(stationLon).toBeLessThanOrEqual(bounds.lonMax);
    expect(bounds.lonMax - bounds.lonMin).toBeLessThan(360);
  });

  it("keeps a polar pass inside a valid latitude range", () => {
    const out = boundsForPass(
      geometry({
        sub_lat_deg: [85, 89, 87],
        station_lat: 88,
        altitude_km: [1200, 1200, 1200],
      }),
    );
    expect(out).not.toBeNull();
    const { bounds } = out as NonNullable<typeof out>;
    expect(bounds.latMax).toBeLessThanOrEqual(90);
    expect(bounds.latMin).toBeGreaterThanOrEqual(-90);
    expect(bounds.latMax).toBeGreaterThan(bounds.latMin);
  });

  it("gives a stationary subpoint a frame with width", () => {
    const out = boundsForPass(
      geometry({
        sub_lat_deg: [10, 10, 10],
        sub_lon_deg: [100, 100, 100],
      }),
    );
    expect(out).not.toBeNull();
    const { bounds } = out as NonNullable<typeof out>;
    expect(bounds.lonMax).toBeGreaterThan(bounds.lonMin);
    expect(bounds.latMax).toBeGreaterThan(bounds.latMin);
  });
});
