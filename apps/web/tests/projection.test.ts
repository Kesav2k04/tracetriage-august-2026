/**
 * The pure functions behind every plot on this console, and the degenerate inputs
 * that produce a wrong picture rather than an error.
 *
 * Until 2026-08-19 nothing exercised any of them. They are pure and import nothing,
 * so the only reason they were untested is that there was no runner. The cases here
 * are the ones an independent review named: a single-sample series, an all-equal
 * series, a pass crossing the antimeridian, a station at a pole, a zero-length pass,
 * a horizon circle that encloses a pole, and a negative-elevation sample carried
 * through every consumer.
 */
import { describe, expect, it } from "vitest";

import {
  EARTH_R_KM,
  GROUND,
  SKY,
  groundBounds,
  horizonCircle,
  niceStep,
  projectGround,
  projectSky,
  skyChromePoint,
  skyRadius,
  stationLonInFrame,
  unwrapLongitudes,
  wrapLabel,
} from "../lib/projection";

describe("projectSky", () => {
  it("puts the zenith at the centre", () => {
    expect(projectSky(0, 90)).toEqual([SKY.cx, SKY.cy]);
    expect(projectSky(137, 90)).toEqual([SKY.cx, SKY.cy]);
  });

  it("puts the horizon on the ring, north up and east right", () => {
    const north = projectSky(0, 0) as [number, number];
    expect(north[0]).toBeCloseTo(SKY.cx, 6);
    expect(north[1]).toBeCloseTo(SKY.cy - SKY.r, 6);

    const east = projectSky(90, 0) as [number, number];
    expect(east[0]).toBeCloseTo(SKY.cx + SKY.r, 6);
    expect(east[1]).toBeCloseTo(SKY.cy, 6);
  });

  it("returns null below the horizon, so every consumer has to say so", () => {
    // This used to clamp. A negative elevation is a real value in the propagated
    // series (the satellite is below the local horizon at both ends of a pass), and
    // clamping gave it a position on the rim where the satellite was not. Three
    // consumers then disagreed: the sky plot broke its polyline, the elevation panel
    // drew a flat segment along zero, and the replay cursor sat on the ring while
    // the track under it had a gap. Null is what makes the disagreement impossible.
    expect(projectSky(45, -30)).toBeNull();
    expect(projectSky(45, -0.017)).toBeNull(); // the smallest one in the corpus
    expect(projectSky(45, Number.NaN)).toBeNull();
  });

  it("clamps above the zenith, which an elevation over 90 would otherwise invert", () => {
    expect(projectSky(45, 91)).toEqual(projectSky(45, 90));
  });

  it("keeps zero itself, which is on the horizon rather than below it", () => {
    expect(projectSky(45, 0)).not.toBeNull();
  });
});

describe("skyRadius and skyChromePoint", () => {
  it("maps the horizon to the ring and the zenith to the centre", () => {
    expect(skyRadius(0)).toBeCloseTo(SKY.r, 9);
    expect(skyRadius(90)).toBeCloseTo(0, 9);
  });

  it("places a cardinal label outside the ring, which the clamp used to prevent", () => {
    // The cardinal labels ask for -7.5 degrees, meaning just outside the horizon
    // ring. While projectSky clamped, that returned exactly the point at 0 degrees,
    // so N, E, S and W sat on the ring on top of their own spokes: the intent was in
    // the number and never on the screen.
    const label = skyChromePoint(0, -7.5);
    const onRing = skyChromePoint(0, 0);
    expect(Math.hypot(label[0] - SKY.cx, label[1] - SKY.cy)).toBeGreaterThan(
      Math.hypot(onRing[0] - SKY.cx, onRing[1] - SKY.cy),
    );
    expect(skyRadius(-7.5)).toBeGreaterThan(SKY.r);
  });

  it("agrees with projectSky wherever a sample is legal", () => {
    for (const el of [0, 12.5, 45, 90]) {
      expect(projectSky(30, el)).toEqual(skyChromePoint(30, el));
    }
  });
});

describe("unwrapLongitudes", () => {
  it("returns an empty series for an empty input rather than throwing", () => {
    expect(unwrapLongitudes([])).toEqual([]);
  });

  it("passes a single sample through untouched", () => {
    expect(unwrapLongitudes([137.5])).toEqual([137.5]);
  });

  it("leaves a series that never crosses the seam alone", () => {
    expect(unwrapLongitudes([10, 20, 30])).toEqual([10, 20, 30]);
  });

  it("removes the 360 degree jump at the antimeridian going east", () => {
    // 178, 179, -179, -178 is a pass crossing the seam. Drawn raw it jumps the whole
    // width of the plot and back.
    const out = unwrapLongitudes([178, 179, -179, -178]);
    expect(out).toEqual([178, 179, 181, 182]);
    for (let i = 1; i < out.length; i += 1) {
      expect(Math.abs((out[i] as number) - (out[i - 1] as number))).toBeLessThan(180);
    }
  });

  it("removes the jump going west as well", () => {
    const out = unwrapLongitudes([-178, -179, 179, 178]);
    expect(out).toEqual([-178, -179, -181, -182]);
  });

  it("takes the shorter step at every sample, not the eastward one", () => {
    // 170, -170, 170, -170 is not a satellite going east twice. Each step is 20
    // degrees the short way and 340 the long way, and a propagated pass cannot move
    // 340 degrees between samples, so the short reading is the physical one. The
    // series therefore oscillates rather than accumulating: the invariant to hold is
    // that no drawn segment jumps more than half the world, not that the values only
    // increase.
    const out = unwrapLongitudes([170, -170, 170, -170]);
    expect(out).toEqual([170, 190, 170, 190]);
    for (let i = 1; i < out.length; i += 1) {
      expect(Math.abs((out[i] as number) - (out[i - 1] as number))).toBeLessThan(180);
    }
  });

  it("accumulates when the motion really is one-way", () => {
    // Eastward at 30 degrees a step, twice around the seam. Here the values do grow
    // without bound, which is what the plot frame is built from.
    const out = unwrapLongitudes([150, 180, -150, -120, -90]);
    expect(out).toEqual([150, 180, 210, 240, 270]);
  });
});

describe("wrapLabel", () => {
  it("brings a longitude back into the labelled range", () => {
    expect(wrapLabel(181)).toBeCloseTo(-179, 9);
    expect(wrapLabel(-181)).toBeCloseTo(179, 9);
    // 540 wraps to the antimeridian, which this returns as -180. Both spellings name
    // the same meridian, and the function is only used for a tick label, so the sign
    // is a presentation choice rather than a correctness one. Asserted as it behaves
    // so a future change to the wrap arithmetic has to be deliberate.
    expect(wrapLabel(540)).toBeCloseTo(-180, 9);
  });

  it("never returns negative zero, which renders as -0", () => {
    expect(Object.is(wrapLabel(360), -0)).toBe(false);
    expect(wrapLabel(360)).toBe(0);
  });
});

describe("horizonCircle", () => {
  it("closes the ring", () => {
    const c = horizonCircle(12, 34, 500);
    expect(c.lat.length).toBe(c.lon.length);
    expect(c.lat[0]).toBeCloseTo(c.lat[c.lat.length - 1] as number, 9);
  });

  it("grows the half angle with altitude", () => {
    const low = horizonCircle(0, 0, 300).halfAngleDeg;
    const high = horizonCircle(0, 0, 1200).halfAngleDeg;
    expect(high).toBeGreaterThan(low);
    // acos(R / (R + h)) at 300 km is about 17.7 degrees for R = 6371.0088 km.
    const expected =
      (Math.acos(EARTH_R_KM / (EARTH_R_KM + 300)) * 180) / Math.PI;
    expect(low).toBeCloseTo(expected, 9);
  });

  it("treats a zero or negative altitude as a floor rather than a zero circle", () => {
    // altKm is clamped to at least 1, so a record with a missing or absurd altitude
    // still yields a ring with a positive radius instead of a degenerate point.
    expect(horizonCircle(0, 0, 0).halfAngleDeg).toBeGreaterThan(0);
    expect(horizonCircle(0, 0, -50).halfAngleDeg).toBeGreaterThan(0);
  });

  it("stays inside the latitude range when the circle encloses the pole", () => {
    // A satellite over 88 N with a 20 degree half angle has a horizon circle that
    // contains the pole. Every latitude must still be a latitude.
    const c = horizonCircle(88, 0, 1200);
    for (const lat of c.lat) {
      expect(lat).toBeGreaterThanOrEqual(-90);
      expect(lat).toBeLessThanOrEqual(90);
      expect(Number.isFinite(lat)).toBe(true);
    }
    for (const lon of c.lon) {
      expect(Number.isFinite(lon)).toBe(true);
    }
  });

  it("spans the full longitude range when the circle encloses the pole", () => {
    // This is the property the plot depends on: a pole-enclosing circle wraps all the
    // way round, so its longitudes cover a wide span rather than a narrow arc. A frame
    // computed as lon +/- halfAngle would clip it at both edges.
    const c = horizonCircle(89, 0, 1200);
    const span = Math.max(...c.lon) - Math.min(...c.lon);
    expect(span).toBeGreaterThan(180);
  });
});

describe("projectGround", () => {
  const bounds = { lonMin: -10, lonMax: 10, latMin: -5, latMax: 5 };

  it("maps the frame corners to the plot corners", () => {
    const [x0, y0] = projectGround(bounds, -10, 5);
    expect(x0).toBeCloseTo(GROUND.padL, 9);
    expect(y0).toBeCloseTo(GROUND.padT, 9);

    const [x1, y1] = projectGround(bounds, 10, -5);
    expect(x1).toBeCloseTo(GROUND.w - GROUND.padR, 9);
    expect(y1).toBeCloseTo(GROUND.h - GROUND.padB, 9);
  });

  it("increases y downward, because latitude increases upward", () => {
    const [, yNorth] = projectGround(bounds, 0, 4);
    const [, ySouth] = projectGround(bounds, 0, -4);
    expect(yNorth).toBeLessThan(ySouth);
  });
});

describe("niceStep", () => {
  it("keeps a graticule to at most seven lines over any span a pass can produce", () => {
    // 630 is the largest span the ladder covers, and it is far beyond anything one
    // pass draws: a frame is a single pass plus its horizon circle, so a few tens of
    // degrees, and the widest case in the corpus is under 180.
    for (const span of [0.5, 3, 8, 25, 100, 175, 360, 630]) {
      const step = niceStep(span);
      expect(span / step).toBeLessThanOrEqual(7.0000001);
      expect(step).toBeGreaterThan(0);
    }
  });

  it("falls back to 90 above that, and the fallback is what caps the line count", () => {
    // Above 630 degrees the ladder runs out and 90 is returned, which draws more than
    // seven lines. That is a multi-revolution frame, which this console never draws.
    // Asserted rather than left implicit, so the limit is visible to whoever first
    // needs a wider frame.
    expect(niceStep(1e6)).toBe(90);
    expect(1000 / niceStep(1000)).toBeGreaterThan(7);
  });
});

describe("groundBounds", () => {
  const base = {
    lats: [10, 20, 30],
    unwrappedLons: [100, 110, 120],
    stationLat: 15,
    stationLonUnwrapped: 105,
    circleLat: [5, 35],
    circleLon: [90, 130],
  };

  it("contains the track, the station and the whole horizon circle", () => {
    const b = groundBounds(base);
    expect(b.latMin).toBeLessThanOrEqual(5);
    expect(b.latMax).toBeGreaterThanOrEqual(35);
    expect(b.lonMin).toBeLessThanOrEqual(90);
    expect(b.lonMax).toBeGreaterThanOrEqual(130);
  });

  it("never returns a latitude outside the sphere", () => {
    const b = groundBounds({
      ...base,
      lats: [89.9, 90],
      circleLat: [-90, 90],
      stationLat: 89,
    });
    expect(b.latMin).toBeGreaterThanOrEqual(-90);
    expect(b.latMax).toBeLessThanOrEqual(90);
  });

  it("gives an all-equal series a frame with width, not a zero-size one", () => {
    // A zero-span frame divides by zero in projectGround and every point becomes
    // Infinity or NaN, which draws nothing. The padding floor of 1 degree is what
    // stops that, so it is asserted here rather than assumed.
    const b = groundBounds({
      lats: [12, 12, 12],
      unwrappedLons: [34, 34, 34],
      stationLat: 12,
      stationLonUnwrapped: 34,
      circleLat: [12],
      circleLon: [34],
    });
    expect(b.latMax - b.latMin).toBeGreaterThan(0);
    expect(b.lonMax - b.lonMin).toBeGreaterThan(0);
    const [x, y] = projectGround(b, 34, 12);
    expect(Number.isFinite(x)).toBe(true);
    expect(Number.isFinite(y)).toBe(true);
  });

  it("gives a single sample a frame with width", () => {
    const b = groundBounds({
      lats: [45],
      unwrappedLons: [7],
      stationLat: 45,
      stationLonUnwrapped: 7,
      circleLat: [45],
      circleLon: [7],
    });
    expect(b.latMax).toBeGreaterThan(b.latMin);
    expect(b.lonMax).toBeGreaterThan(b.lonMin);
  });
});

describe("stationLonInFrame", () => {
  it("leaves a station already inside the frame alone", () => {
    expect(stationLonInFrame([100, 110, 120], 105)).toBeCloseTo(105, 9);
  });

  it("brings a station into an unwrapped frame that has crossed the seam", () => {
    // The pass runs 178 -> 182 in unwrapped coordinates. A station at -179 is at the
    // same place as 181, and without this it would be plotted 360 degrees away.
    const frame = unwrapLongitudes([178, 179, -179, -178]);
    expect(stationLonInFrame(frame, -179)).toBeCloseTo(181, 9);
  });

  it("works for a single-sample frame", () => {
    expect(stationLonInFrame([181], -179)).toBeCloseTo(181, 9);
  });

  it("puts a polar station in the frame the pass is drawn in", () => {
    // Longitude is meaningless at a pole but the marker still has to land inside the
    // frame rather than off the edge, so the same shift applies.
    const frame = unwrapLongitudes([170, -170, -160]);
    const shifted = stationLonInFrame(frame, 0);
    expect(shifted).toBeGreaterThanOrEqual(Math.min(...frame) - 360);
    expect(shifted).toBeLessThanOrEqual(Math.max(...frame) + 360);
  });
});

describe("footprint framing", () => {
  // Observation 14744250 as shipped: NORAD 46487 seen from station 329CZ144, at closest
  // approach 62.28 degrees north and 1518 km up, which puts the horizon circle over the
  // pole. Framing to that circle drew 360 degrees of longitude and left the 15.5 degree
  // ground track occupying 4.1 percent of the 378 px plot width.
  const polarTrack = {
    lats: [55.0, 62.28, 68.0],
    unwrappedLons: [10.0, 17.0, 25.5],
    stationLat: 60.0,
    stationLonUnwrapped: 14.0,
  };

  it("reports pole enclosure from the exact geometric condition", () => {
    const over = horizonCircle(62.28, 17, 1518);
    expect(over.halfAngleDeg).toBeCloseTo(36.14, 1);
    expect(Math.abs(62.28) + over.halfAngleDeg).toBeGreaterThan(90);
    expect(over.enclosesPole).toBe(true);

    // A degree or two lower and the same altitude no longer reaches the pole, which is
    // the boundary the condition has to sit on rather than near.
    const under = horizonCircle(53.0, 17, 1518);
    expect(Math.abs(53.0) + under.halfAngleDeg).toBeLessThan(90);
    expect(under.enclosesPole).toBe(false);
  });

  it("unwraps a circle that straddles the antimeridian into one arc", () => {
    const c = horizonCircle(0, 179.5, 500);
    expect(c.enclosesPole).toBe(false);
    const span = Math.max(...c.lon) - Math.min(...c.lon);
    expect(span).toBeLessThan(90);
    // Every step is small: a wrapped ring shows a 360 degree jump between neighbours.
    for (let i = 1; i < c.lon.length; i += 1) {
      expect(Math.abs((c.lon[i] as number) - (c.lon[i - 1] as number))).toBeLessThan(30);
    }
  });

  it("frames the ground track rather than a pole-enclosing footprint", () => {
    const circle = horizonCircle(62.28, 17, 1518);
    const framed = groundBounds({
      ...polarTrack,
      circleLat: circle.lat,
      circleLon: circle.lon,
      circleEnclosesPole: circle.enclosesPole,
    });
    expect(framed.footprintClipped).toBe(true);
    expect(framed.footprintClipReason).toContain("encloses a pole");

    const span = framed.lonMax - framed.lonMin;
    expect(span).toBeLessThan(30);
    const trackShare = (25.5 - 10.0) / span;
    expect(trackShare).toBeGreaterThan(0.5);
  });

  it("keeps an ordinary footprint inside the frame", () => {
    // The other 24 shipped cards. A footprint several times wider than a short track is
    // normal and useful context, so a ratio test between the two is the wrong rule: over
    // the 25 cards that ratio runs to 17.2 and a cap of 3 would clip 23 of them.
    const circle = horizonCircle(20, 110, 500);
    expect(circle.enclosesPole).toBe(false);
    const framed = groundBounds({
      lats: [10, 20, 30],
      unwrappedLons: [100, 110, 120],
      stationLat: 15,
      stationLonUnwrapped: 105,
      circleLat: circle.lat,
      circleLon: circle.lon,
      circleEnclosesPole: circle.enclosesPole,
    });
    expect(framed.footprintClipped).toBe(false);
    expect(framed.footprintClipReason).toBe(null);
    expect(framed.lonMin).toBeLessThanOrEqual(Math.min(...circle.lon));
    expect(framed.lonMax).toBeGreaterThanOrEqual(Math.max(...circle.lon));
  });

  it("clips a footprint that would squeeze the track under the stated share", () => {
    // The backstop, exercised deliberately: no pole involved, a wide footprint and a
    // track a fraction of a degree long. Inert on everything that ships, where the
    // smallest non-polar track share is 6.7 percent against the 6 percent floor.
    const circle = horizonCircle(0, 0, 20_000);
    expect(circle.enclosesPole).toBe(false);
    const framed = groundBounds({
      lats: [0.0, 0.05, 0.1],
      unwrappedLons: [0.0, 0.05, 0.1],
      stationLat: 0.0,
      stationLonUnwrapped: 0.05,
      circleLat: circle.lat,
      circleLon: circle.lon,
      circleEnclosesPole: circle.enclosesPole,
    });
    expect(framed.footprintClipped).toBe(true);
    expect(framed.footprintClipReason).toContain("percent of the plot width");
    expect(framed.lonMax - framed.lonMin).toBeLessThan(10);
  });

  it("never reports a clipped footprint without saying why", () => {
    const cases = [
      { lat: 62.28, alt: 1518 },
      { lat: 20, alt: 500 },
      { lat: 0, alt: 20_000 },
      { lat: -75, alt: 800 },
    ];
    for (const c of cases) {
      const circle = horizonCircle(c.lat, 17, c.alt);
      const framed = groundBounds({
        ...polarTrack,
        lats: [c.lat - 2, c.lat, c.lat + 2],
        stationLat: c.lat,
        circleLat: circle.lat,
        circleLon: circle.lon,
        circleEnclosesPole: circle.enclosesPole,
      });
      expect(framed.footprintClipped).toBe(framed.footprintClipReason !== null);
      expect(framed.lonMax).toBeGreaterThan(framed.lonMin);
      expect(framed.latMax).toBeGreaterThan(framed.latMin);
      expect(framed.latMin).toBeGreaterThanOrEqual(-90);
      expect(framed.latMax).toBeLessThanOrEqual(90);
    }
  });
});
