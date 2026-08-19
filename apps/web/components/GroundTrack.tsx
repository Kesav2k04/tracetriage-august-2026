/**
 * Where the satellite was over the ground, and how much of the ground could see it
 * at closest approach.
 *
 * There is no basemap. That is a decision, not a gap: this console ships no
 * coastline data, and drawing an approximate one would put an unmeasured object on a
 * page whose whole argument is that everything on it came from a receipt. What is
 * drawn instead is what the propagation actually produced, on a labelled graticule:
 * the subsatellite track, the station, and the satellite's horizon circle at closest
 * approach. A reader who needs to know which country is under the track has the
 * latitude and longitude printed on the axes.
 *
 * The horizon circle is the set of ground points from which the satellite sits at or
 * above zero elevation, a small circle of central half-angle arccos(Re / (Re + h)).
 * It is walked on the sphere rather than drawn as an ellipse, because away from the
 * equator an ellipse is wrong by more than the circle is wide.
 *
 * The projection and the framing both live in `lib/projection.ts`, because the
 * replay cursor has to land in the frame this plot drew. When the plot owned the
 * framing, the cursor would have had to recompute it and could have disagreed.
 */
import {
  GROUND,
  type GroundBounds,
  type GroundFrame,
  groundAxisScales,
  groundBounds,
  horizonCircle,
  niceStep,
  projectGround,
  stationLonInFrame,
  unwrapLongitudes,
  wrapLabel,
} from "@/lib/projection";

export type TrackGeometry = {
  sub_lat_deg: number[];
  sub_lon_deg: number[];
  altitude_km: number[];
  station_lat: number;
  station_lon: number;
  elevation_deg: number[];
};

/**
 * The frame for one pass, exported so the observation page can hand the identical
 * bounds to the replay cursor instead of deriving them a second time.
 */
export function boundsForPass(geometry: TrackGeometry): {
  bounds: GroundFrame;
  lons: number[];
  iTca: number;
  halfAngleDeg: number;
  circle: { lat: number[]; lon: number[]; enclosesPole: boolean };
  stationLon: number;
} | null {
  const lats = geometry.sub_lat_deg;
  const lons = unwrapLongitudes(geometry.sub_lon_deg);
  if (lats.length < 2 || lons.length < 2) return null;

  // Closest approach: the highest elevation sample, found in the series so the
  // circle, the marker and the track all agree about where it is.
  let iTca = 0;
  for (let i = 1; i < geometry.elevation_deg.length; i += 1) {
    const v = geometry.elevation_deg[i];
    const best = geometry.elevation_deg[iTca];
    if (v !== undefined && best !== undefined && v > best) iTca = i;
  }
  const tcaLat = lats[iTca] ?? lats[0] ?? 0;
  const tcaLon = lons[iTca] ?? lons[0] ?? 0;
  const tcaAlt = geometry.altitude_km[iTca] ?? geometry.altitude_km[0] ?? 0;

  const circle = horizonCircle(tcaLat, tcaLon, tcaAlt);
  const stationLon = stationLonInFrame(lons, geometry.station_lon);
  const bounds = groundBounds({
    lats,
    unwrappedLons: lons,
    stationLat: geometry.station_lat,
    stationLonUnwrapped: stationLon,
    circleLat: circle.lat,
    circleLon: circle.lon,
    circleEnclosesPole: circle.enclosesPole,
  });

  return {
    bounds,
    lons,
    iTca,
    halfAngleDeg: circle.halfAngleDeg,
    circle: {
      lat: circle.lat,
      lon: circle.lon,
      enclosesPole: circle.enclosesPole,
    },
    stationLon,
  };
}

export default function GroundTrack({
  geometry,
  stationName,
}: {
  geometry: TrackGeometry;
  stationName: string;
}) {
  const framed = boundsForPass(geometry);
  if (!framed) return null;
  const { bounds, lons, iTca, halfAngleDeg, circle, stationLon } = framed;
  const lats = geometry.sub_lat_deg;

  const tcaLat = lats[iTca] ?? 0;
  const tcaLon = lons[iTca] ?? 0;
  const tcaAlt = geometry.altitude_km[iTca] ?? 0;

  const x = (lon: number) => projectGround(bounds, lon, 0)[0];
  const y = (lat: number) => projectGround(bounds, 0, lat)[1];
  const plotW = GROUND.w - GROUND.padL - GROUND.padR;
  const plotH = GROUND.h - GROUND.padT - GROUND.padB;
  // Stable per observation rather than random, so the same page renders the same markup
  // on the server and in the browser.
  const clipId = `ground-plot-${geometry.station_lat.toFixed(3)}-${lats.length}`;

  const trackPath = lats
    .map((lat, i) => {
      const lon = lons[i];
      if (lat === undefined || lon === undefined) return null;
      return `${x(lon).toFixed(2)},${y(lat).toFixed(2)}`;
    })
    .filter((p): p is string => p !== null);

  const latStep = niceStep(bounds.latMax - bounds.latMin);
  const lonStep = niceStep(bounds.lonMax - bounds.lonMin);
  const latLines: number[] = [];
  for (
    let v = Math.ceil(bounds.latMin / latStep) * latStep;
    v <= bounds.latMax;
    v += latStep
  ) {
    latLines.push(v);
  }
  const lonLines: number[] = [];
  for (
    let v = Math.ceil(bounds.lonMin / lonStep) * lonStep;
    v <= bounds.lonMax;
    v += lonStep
  ) {
    lonLines.push(v);
  }

  const circlePoints = circle.lat
    .map((latD, i) => {
      const lonD = circle.lon[i];
      if (lonD === undefined) return null;
      return `${x(lonD).toFixed(2)},${y(latD).toFixed(2)}`;
    })
    .filter((v): v is string => v !== null);

  const scales = groundAxisScales(bounds);
  const label =
    `Ground track: the subsatellite point runs from ${lats[0]?.toFixed(1)} degrees`
    + ` latitude to ${lats[lats.length - 1]?.toFixed(1)} degrees, passing`
    + ` ${Math.abs(tcaLat - geometry.station_lat).toFixed(1)} degrees of latitude from`
    + ` ${stationName}. At closest approach the satellite was ${tcaAlt.toFixed(0)} km up,`
    + ` so its horizon circle covers ${(halfAngleDeg * 2).toFixed(1)} degrees of arc.`
    + (bounds.footprintClipped
      ? ` The footprint continues past the edge of the plot: ${bounds.footprintClipReason}`
        + `, so the frame follows the ground track instead.`
      : "")
    // The two axes are scaled independently to fill the box, so the circle is a correct
    // spherical locus drawn into a frame that does not preserve its shape. Stated, because
    // a reader cannot see it and would otherwise read the drawn eccentricity as physical.
    // The closing clause is decided by the number rather than asserted: measured across
    // the shipped cards the stretch runs 0.50 to 1.63, and one card sits at 1.01, where
    // calling the footprint an ellipse would be the misleading half of the sentence.
    + ` The axes are scaled independently to fill the plot: ${scales.lonDegPerPx.toFixed(3)}`
    + ` degrees of longitude and ${scales.latDegPerPx.toFixed(3)} degrees of latitude per`
    + ` pixel, a ${scales.verticalStretch.toFixed(2)} times vertical stretch, so the`
    + (Math.abs(scales.verticalStretch - 1) < 0.02
      ? ` footprint is drawn at close to its true shape.`
      : ` footprint is drawn as an ellipse rather than a circle.`);

  return (
    <svg viewBox={`0 0 ${GROUND.w} ${GROUND.h}`} role="img" aria-label={label}>
      <rect
        x={GROUND.padL}
        y={GROUND.padT}
        width={plotW}
        height={plotH}
        className="plot-grid-strong"
      />

      {latLines.map((v) => (
        <g key={`lat-${v}`}>
          <line
            x1={GROUND.padL}
            x2={GROUND.padL + plotW}
            y1={y(v)}
            y2={y(v)}
            className={v === 0 ? "plot-grid-strong" : "plot-grid"}
          />
          <text
            x={GROUND.padL - 4}
            y={y(v) + 3}
            className="plot-label"
            textAnchor="end"
          >
            {v}
          </text>
        </g>
      ))}

      {lonLines.map((v) => (
        <g key={`lon-${v}`}>
          <line
            y1={GROUND.padT}
            y2={GROUND.padT + plotH}
            x1={x(v)}
            x2={x(v)}
            className="plot-grid"
          />
          <text
            x={x(v)}
            y={GROUND.h - GROUND.padB + 12}
            className="plot-label"
            textAnchor="middle"
          >
            {wrapLabel(v)}
          </text>
        </g>
      ))}

      {/* Clipped to the plot, because the frame is decided by the track and the
          station. A footprint enclosing a pole spans every longitude and would
          otherwise frame the whole world; the caption says it continues off-plot. */}
      <clipPath id={clipId}>
        <rect x={GROUND.padL} y={GROUND.padT} width={plotW} height={plotH} />
      </clipPath>
      <polygon
        points={circlePoints.join(" ")}
        className="plot-footprint"
        clipPath={`url(#${clipId})`}
      />
      <polyline points={trackPath.join(" ")} className="plot-track" />
      {/* Elapsed overlay, same as the sky plot, including the reason it repeats the
          point list rather than referencing it with a <use>. */}
      <polyline
        points={trackPath.join(" ")}
        id="ground-trail"
        className="replay-trail"
        aria-hidden="true"
      />
      <circle cx={x(tcaLon)} cy={y(tcaLat)} r={3.5} className="plot-marker" />

      {/* The station: a cross rather than a dot, and drawn after the closest
          approach marker, so it stays readable on a near-zenith pass where the two
          land on the same pixel. */}
      <g className="plot-station">
        <line
          x1={x(stationLon) - 5}
          x2={x(stationLon) + 5}
          y1={y(geometry.station_lat)}
          y2={y(geometry.station_lat)}
        />
        <line
          x1={x(stationLon)}
          x2={x(stationLon)}
          y1={y(geometry.station_lat) - 5}
          y2={y(geometry.station_lat) + 5}
        />
      </g>

      {/* The replay cursor, server-rendered and CSS-hidden until the replay marks
          itself ready. See the note in SkyPlot: one transform, no restyle. */}
      <g id="ground-cursor" className="replay-cursor" aria-hidden="true">
        <circle r={5.5} />
        <circle r={1.75} className="replay-cursor-core" />
      </g>
    </svg>
  );
}
