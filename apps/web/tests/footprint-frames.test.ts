/**
 * The footprint framing rule, applied to every card the console ships.
 *
 * The rule has to change the one card that was broken and leave the other 24 alone. A
 * ratio between the footprint and the track cannot do that: measured over these cards
 * the footprint-to-track longitude span ratio has a median of 5.2 and a maximum of 17.2,
 * so a cap of 3 clips 23 of 25. Pole enclosure is the exact trigger, and this test is
 * what keeps the rule honest against the data rather than against an argument.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { boundsForPass } from "../components/GroundTrack";
import {
  MIN_TRACK_WIDTH_FRACTION,
  groundAxisScales,
  horizonCircle,
} from "../lib/projection";

type Geometry = {
  sub_lat_deg: number[];
  sub_lon_deg: number[];
  altitude_km: number[];
  elevation_deg: number[];
  station_lat: number;
  station_lon: number;
};

const cards = JSON.parse(
  readFileSync(join(__dirname, "..", "public", "data", "cards.json"), "utf-8"),
) as { cards: { obs_id: number; geometry?: Geometry }[] };

const framed = cards.cards
  .filter((c) => c.geometry !== undefined)
  .map((c) => {
    const geometry = c.geometry as Geometry;
    const result = boundsForPass(geometry);
    return { obs_id: c.obs_id, geometry, result };
  });

describe("every shipped card's ground-track frame", () => {
  it("has a frame at all", () => {
    expect(framed.length).toBeGreaterThan(20);
    for (const row of framed) {
      expect(row.result).not.toBeNull();
    }
  });

  it("clips the footprint only where the circle encloses a pole", () => {
    const clipped = framed.filter((r) => r.result?.bounds.footprintClipped);
    expect(clipped.map((r) => r.obs_id)).toEqual([14744250]);
    for (const row of clipped) {
      const { geometry, result } = row;
      let iTca = 0;
      for (let i = 1; i < geometry.elevation_deg.length; i += 1) {
        if ((geometry.elevation_deg[i] as number) > (geometry.elevation_deg[iTca] as number)) {
          iTca = i;
        }
      }
      const circle = horizonCircle(
        geometry.sub_lat_deg[iTca] as number,
        geometry.sub_lon_deg[iTca] as number,
        geometry.altitude_km[iTca] as number,
      );
      expect(circle.enclosesPole).toBe(true);
      expect(result?.bounds.footprintClipReason).toContain("encloses a pole");
    }
  });

  it("leaves every pass legible in its own frame", () => {
    // The quantity the review measured: on observation 14744250 the track occupied 4.1
    // percent of the plot width. Nothing may sit below the stated floor now.
    for (const { obs_id, result } of framed) {
      const bounds = result?.bounds;
      const lons = result?.lons ?? [];
      if (bounds === undefined || lons.length === 0) continue;
      const span = bounds.lonMax - bounds.lonMin;
      const share = (Math.max(...lons) - Math.min(...lons)) / span;
      expect(
        share,
        `observation ${obs_id} draws its track across ${(share * 100).toFixed(1)} percent of the plot width`,
      ).toBeGreaterThanOrEqual(MIN_TRACK_WIDTH_FRACTION);
    }
  });

  it("reports the per-axis scale every card is actually drawn at", () => {
    // The two axes are scaled independently to fill the box, so a footprint computed as a
    // spherical locus is usually drawn as an ellipse. That is a framing choice, not a
    // defect; the defect would be not saying so. Measured over these cards the vertical
    // stretch runs 0.5046 (14744250) to 1.6342 (14735743), and 14733024 sits at 1.0081,
    // where calling the footprint an ellipse would be the wrong half of the sentence. So
    // the caption reports the number and the number decides the clause, and this test
    // holds the range that makes both worth stating.
    const stretches: number[] = [];
    for (const { obs_id, result } of framed) {
      const bounds = result?.bounds;
      if (bounds === undefined) continue;
      const scales = groundAxisScales(bounds);
      expect(scales.lonDegPerPx).toBeGreaterThan(0);
      expect(scales.latDegPerPx).toBeGreaterThan(0);
      expect(
        scales.verticalStretch,
        `observation ${obs_id} reports a stretch that is not the ratio of its two scales`,
      ).toBeCloseTo(scales.lonDegPerPx / scales.latDegPerPx, 10);
      stretches.push(scales.verticalStretch);
    }
    expect(stretches.length).toBeGreaterThan(20);
    expect(Math.min(...stretches)).toBeLessThan(0.7);
    expect(Math.max(...stretches)).toBeGreaterThan(1.4);
    expect(
      stretches.filter((v) => Math.abs(v - 1) < 0.02).length,
      "at least one card is drawn at near-equal scale, which is why the caption reports "
        + "the ratio instead of asserting a distortion",
    ).toBeGreaterThan(0);
  });

  it("frames no card wider than a hemisphere", () => {
    for (const { obs_id, result } of framed) {
      const bounds = result?.bounds;
      if (bounds === undefined) continue;
      expect(
        bounds.lonMax - bounds.lonMin,
        `observation ${obs_id} frames ${(bounds.lonMax - bounds.lonMin).toFixed(1)} degrees of longitude`,
      ).toBeLessThan(180);
    }
  });
});
