/**
 * The two projections the pass plots use, in one place.
 *
 * Both the server-rendered plots and the client-side replay cursor need to turn a
 * propagated sample into a coordinate. Writing that twice would be the same trap
 * the physics module hit when `station_ecef` and `ecef_to_geodetic` each computed
 * their own WGS-84 eccentricity: two copies of a formula are two chances to end up
 * with a cursor that does not sit on the line it is supposed to be tracing.
 *
 * The module is client-safe on purpose. It holds no receipt data and imports
 * nothing, so a client component can use it without pulling the data layer across
 * the bundle boundary, which is the mistake that once put the queue route at
 * 306 kB.
 */

// ---------------------------------------------------------------------------
// Sky plot: polar azimuth and elevation
// ---------------------------------------------------------------------------

export const SKY = {
  size: 320,
  cx: 160,
  cy: 160,
  /** Radius of the horizon ring, in viewBox units. */
  r: 132,
} as const;

/**
 * Azimuth and elevation to sky-plot coordinates. North is up, east is right, and
 * elevation maps to radius linearly with the zenith at the centre.
 */
export function projectSky(azDeg: number, elDeg: number): [number, number] {
  const clamped = Math.max(0, Math.min(90, elDeg));
  const radius = (SKY.r * (90 - clamped)) / 90;
  const angle = ((azDeg - 90) * Math.PI) / 180; // 0 degrees azimuth points up
  return [SKY.cx + radius * Math.cos(angle), SKY.cy + radius * Math.sin(angle)];
}

// ---------------------------------------------------------------------------
// Ground track: equirectangular, framed to the pass
// ---------------------------------------------------------------------------

export const GROUND = {
  w: 420,
  h: 260,
  padL: 34,
  padR: 8,
  padT: 8,
  padB: 20,
} as const;

/** Mean Earth radius. The right one for a horizon half-angle. */
export const EARTH_R_KM = 6371.0088;

export type GroundBounds = {
  lonMin: number;
  lonMax: number;
  latMin: number;
  latMax: number;
};

/**
 * Remove 360-degree seams from a longitude series.
 *
 * A pass that crosses the antimeridian has a 360-degree jump in its longitudes.
 * Projected directly that jump draws a line straight across the plot: an artefact
 * that reads as a data error and is really a coordinate seam.
 */
export function unwrapLongitudes(lons: number[]): number[] {
  const out: number[] = [];
  let offset = 0;
  let prev: number | undefined;
  for (const raw of lons) {
    if (raw === undefined) continue;
    if (prev !== undefined) {
      const delta = raw + offset - prev;
      if (delta > 180) offset -= 360;
      else if (delta < -180) offset += 360;
    }
    const value = raw + offset;
    out.push(value);
    prev = value;
  }
  return out;
}

/** Wrap a longitude back into -180..180 for a label. */
export function wrapLabel(lon: number): number {
  const v = (((lon + 180) % 360) + 360) % 360 - 180;
  return Object.is(v, -0) ? 0 : v;
}

/**
 * The satellite's horizon circle at a given subpoint and altitude, walked on the
 * sphere.
 *
 * Returned as degrees rather than as a path, because the plot needs the points
 * twice: once to work out how much of the world to show, and once to draw them. An
 * earlier version approximated the extent as `lon +/- halfAngle` and clipped the
 * circle at both the east and the west edge, because a small circle of half-angle
 * t centred at latitude phi reaches roughly t / cos(phi) in longitude.
 */
export function horizonCircle(
  latDeg: number,
  lonDeg: number,
  altKm: number,
  stepDeg = 3,
): { lat: number[]; lon: number[]; halfAngleDeg: number } {
  const halfAngleDeg =
    (Math.acos(Math.min(1, EARTH_R_KM / (EARTH_R_KM + Math.max(altKm, 1)))) * 180) /
    Math.PI;
  const phi = (latDeg * Math.PI) / 180;
  const lam = (lonDeg * Math.PI) / 180;
  const theta = (halfAngleDeg * Math.PI) / 180;
  const lat: number[] = [];
  const lon: number[] = [];
  for (let deg = 0; deg <= 360; deg += stepDeg) {
    const b = (deg * Math.PI) / 180;
    const latR = Math.asin(
      Math.sin(phi) * Math.cos(theta) + Math.cos(phi) * Math.sin(theta) * Math.cos(b),
    );
    const lonR =
      lam +
      Math.atan2(
        Math.sin(b) * Math.sin(theta) * Math.cos(phi),
        Math.cos(theta) - Math.sin(phi) * Math.sin(latR),
      );
    lat.push((latR * 180) / Math.PI);
    lon.push((lonR * 180) / Math.PI);
  }
  return { lat, lon, halfAngleDeg };
}

/** Longitude and latitude to ground-track coordinates, for a given frame. */
export function projectGround(
  bounds: GroundBounds,
  lonDeg: number,
  latDeg: number,
): [number, number] {
  const plotW = GROUND.w - GROUND.padL - GROUND.padR;
  const plotH = GROUND.h - GROUND.padT - GROUND.padB;
  return [
    GROUND.padL + ((lonDeg - bounds.lonMin) / (bounds.lonMax - bounds.lonMin)) * plotW,
    GROUND.padT + ((bounds.latMax - latDeg) / (bounds.latMax - bounds.latMin)) * plotH,
  ];
}

/** A graticule step that yields roughly four to seven lines over the span. */
export function niceStep(span: number): number {
  for (const step of [1, 2, 5, 10, 15, 20, 30, 45, 60]) {
    if (span / step <= 7) return step;
  }
  return 90;
}

/**
 * The frame for one pass: the track, the station, and the whole horizon circle.
 *
 * Computed here rather than inside the plot so the replay cursor is placed by the
 * same bounds the track was drawn with. When the plot owned this, the cursor would
 * have had to recompute it and could have disagreed.
 */
export function groundBounds(input: {
  lats: number[];
  unwrappedLons: number[];
  stationLat: number;
  stationLonUnwrapped: number;
  circleLat: number[];
  circleLon: number[];
}): GroundBounds {
  const latValues = [...input.lats, input.stationLat, ...input.circleLat];
  const lonValues = [...input.unwrappedLons, input.stationLonUnwrapped, ...input.circleLon];
  let latMin = Math.min(...latValues);
  let latMax = Math.max(...latValues);
  let lonMin = Math.min(...lonValues);
  let lonMax = Math.max(...lonValues);

  const latPad = Math.max(1, (latMax - latMin) * 0.03);
  const lonPad = Math.max(1, (lonMax - lonMin) * 0.03);
  latMin = Math.max(-90, latMin - latPad);
  latMax = Math.min(90, latMax + latPad);
  lonMin -= lonPad;
  lonMax += lonPad;

  return { lonMin, lonMax, latMin, latMax };
}

/**
 * Bring a station longitude into the same unwrapped frame as a pass.
 *
 * Without this, a pass that crossed the seam would put the station marker off the
 * plot while every other mark landed correctly.
 */
export function stationLonInFrame(unwrappedLons: number[], stationLon: number): number {
  const mid = (Math.min(...unwrappedLons) + Math.max(...unwrappedLons)) / 2;
  return stationLon + 360 * Math.round((mid - stationLon) / 360);
}
