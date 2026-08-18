/**
 * One observation, with the image the measurement was taken from.
 *
 * The page exists so a claim can be checked rather than believed. Everything on it
 * is either a field from the snapshot or a number from a receipt; the only thing
 * the browser computes is how to display the pixels, and it says so.
 */
import Link from "next/link";

import {
  REASON_LABELS,
  cardById,
  entryById,
  fmt,
  showcaseIds,
} from "@/lib/data";
import WaterfallViewer from "@/components/WaterfallViewer";
import SkyPlot from "@/components/SkyPlot";
import GroundTrack, { boundsForPass } from "@/components/GroundTrack";
import PassReplay from "@/components/PassReplay";
import PassTimeSeries from "@/components/PassTimeSeries";
import { Cell, Note, Section, Stat, Table, Tag } from "@/components/ui";

export function generateStaticParams() {
  return showcaseIds.map((id) => ({ id: String(id) }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return {
    title: `Observation ${id}`,
    description: `Waterfall, Doppler corridor fit and queue position for SatNOGS observation ${id}.`,
  };
}

export default async function ObservationPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const obsId = Number(id);
  const card = cardById.get(obsId);
  const entry = entryById.get(obsId);
  const geometry = card?.geometry ?? null;

  if (!card || card.degraded) {
    return (
      <div className="shell" style={{ paddingTop: "var(--sp-09)" }}>
        <h1 style={{ fontSize: "var(--type-heading-04)" }}>Observation {id}</h1>
        <Note tone="warn">
          {card?.degraded ??
            "This observation is not in the shipped set. The console carries imagery for the top of the queue and for the observations the findings name by number."}
        </Note>
        <p style={{ marginTop: "var(--sp-06)" }}>
          <Link href="/">Back to the queue</Link>
        </p>
      </div>
    );
  }

  const position = showcaseIds.indexOf(obsId);
  const previous = position > 0 ? showcaseIds[position - 1] : null;
  const next =
    position >= 0 && position < showcaseIds.length - 1
      ? showcaseIds[position + 1]
      : null;

  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <nav
        aria-label="Observation"
        style={{
          display: "flex",
          gap: "var(--sp-05)",
          alignItems: "center",
          fontSize: "var(--type-caption)",
          color: "var(--text-03)",
        }}
      >
        <Link href="/">Queue</Link>
        <span aria-hidden="true">/</span>
        <span className="num">{obsId}</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: "var(--sp-05)" }}>
          {previous && <Link href={`/observation/${previous}/`}>← previous</Link>}
          {next && <Link href={`/observation/${next}/`}>next →</Link>}
        </span>
      </nav>

      <header style={{ marginTop: "var(--sp-05)" }}>
        <h1 style={{ fontSize: "var(--type-heading-05)" }}>
          Observation <span className="num">{obsId}</span>
        </h1>
        <p
          style={{
            margin: "var(--sp-03) 0 0",
            color: "var(--text-02)",
            display: "flex",
            gap: "var(--sp-04)",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <Tag>{card.station_name ?? `station ${card.ground_station}`}</Tag>
          <Tag>NORAD {card.norad_cat_id}</Tag>
          <Tag>{card.transmitter_mode ?? "mode unknown"}</Tag>
          <Tag tone="muted">label: {card.waterfall_status}</Tag>
          {entry && <Tag tone="action">queue rank {entry.rank}</Tag>}
        </p>
      </header>

      <div style={{ marginTop: "var(--sp-07)" }}>
        <WaterfallViewer
          src={card.image!}
          width={card.width!}
          height={card.height!}
          obsId={obsId}
          corridor={card.corridor}
          corridorNote={card.corridor_note}
          hzPerPx={card.hz_per_px}
          secondsPerPx={card.seconds_per_px}
        />
      </div>

      {/* The geometry behind the trace.
          Two plots of the same propagation the corridor was scored against, laid
          out beside each other because their job is to explain the shape on the
          image above. A steep Doppler S-curve is a high, close pass; a nearly
          vertical trace is a low one at long range. Both are server-rendered SVG
          computed at build time, so they cost no JavaScript and render with
          scripting off. */}
      {geometry && geometry.degraded === null && (
        <Section
          title="The pass"
          description="The same propagation that produced the corridor above, drawn from the station's point of view and from orbit. Elevation is measured from the WGS-84 geodetic normal, which is the reference the corridor was scored against."
        >
          <div className="instruments">
            <figure className="instrument">
              <figcaption>
                <h3 className="instrument-title">Sky track</h3>
                <p className="instrument-note">
                  Azimuth clockwise from true north, elevation from the horizon at
                  the rim to the zenith at the centre. The open circle is the rise,
                  the square is the set, and the filled mark is closest approach at{" "}
                  <span className="num">
                    {geometry.max_elevation_deg.toFixed(1)}&deg;
                  </span>
                  .
                </p>
              </figcaption>
              <SkyPlot
                geometry={geometry}
                stationName={card.station_name ?? `station ${card.ground_station}`}
              />
            </figure>

            <figure className="instrument">
              <figcaption>
                <h3 className="instrument-title">Ground track</h3>
                <p className="instrument-note">
                  The subsatellite point, the station as a cross, and the
                  satellite&rsquo;s horizon circle at closest approach from{" "}
                  <span className="num">
                    {geometry.altitude_km[
                      geometry.elevation_deg.indexOf(
                        Math.max(...geometry.elevation_deg),
                      )
                    ]?.toFixed(0) ?? "—"}
                  </span>{" "}
                  km. There is no basemap: this console ships no coastline data and
                  will not draw one it cannot cite.
                </p>
              </figcaption>
              <GroundTrack
                geometry={geometry}
                stationName={card.station_name ?? `station ${card.ground_station}`}
              />
            </figure>
          </div>

          <figure className="instrument instrument-wide">
            <figcaption>
              <h3 className="instrument-title">Elevation and Doppler against time</h3>
              <p className="instrument-note">
                The same pass on a time axis. Two stacked panels rather than one
                panel with two vertical scales, because a twin-axis chart lets the
                author choose where two curves appear to cross. Here the Doppler
                curve crosses zero at the instant elevation peaks because that is
                when it happens.
              </p>
            </figcaption>
            <PassTimeSeries
              geometry={geometry}
              durationS={
                card.start && card.end
                  ? (Date.parse(card.end) - Date.parse(card.start)) / 1000
                  : 0
              }
            />
          </figure>

          {/* One clock over all four instruments. Mounted after the plots so the
              cursors it drives already exist in the document. */}
          {(() => {
            const framed = boundsForPass(geometry);
            if (!framed || !card.height) return null;
            const seconds =
              card.start && card.end
                ? (Date.parse(card.end) - Date.parse(card.start)) / 1000
                : 0;
            if (!Number.isFinite(seconds) || seconds <= 0) return null;
            return (
              <PassReplay
                geometry={geometry}
                durationS={seconds}
                groundLons={framed.lons}
                bounds={framed.bounds}
                imageHeight={card.height}
              />
            );
          })()}

          <Table
            head={["Quantity", "Value", "Where it comes from"]}
            headAlign={["left", "right", "left"]}
            caption="Every row is a field of the exported geometry, not a figure read off the plots."
          >
            <tr>
              <Cell align="left" header>
                Maximum elevation
              </Cell>
              <Cell mono>{geometry.max_elevation_deg.toFixed(3)}&deg;</Cell>
              <Cell align="left">
                Highest sample of the propagated pass, from the geodetic normal
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Azimuth at closest approach
              </Cell>
              <Cell mono>{geometry.tca_azimuth_deg.toFixed(2)}&deg;</Cell>
              <Cell align="left">Clockwise from true north</Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Slant range at closest approach
              </Cell>
              <Cell mono>{geometry.min_range_km.toFixed(1)} km</Cell>
              <Cell align="left">
                Station to satellite, the minimum over the pass
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Closest approach, as a fraction of the pass
              </Cell>
              <Cell mono>{geometry.tca_frac.toFixed(4)}</Cell>
              <Cell align="left">
                0 is the start of the recording window, 1 the end
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Samples propagated
              </Cell>
              <Cell mono>
                {geometry.n_samples_propagated}
                {geometry.n_sgp4_errors > 0
                  ? ` (${geometry.n_sgp4_errors} SGP4 errors)`
                  : ""}
              </Cell>
              <Cell align="left">
                An error count above zero means the orbit model refused part of the
                window, and the track is drawn only where it did not
              </Cell>
            </tr>
          </Table>
        </Section>
      )}

      {geometry && geometry.degraded !== null && (
        <Section title="The pass">
          <Note tone="warn">
            The sky and ground tracks are withheld for this observation:{" "}
            {geometry.degraded}. The waterfall above is unaffected, because it is an
            image rather than a propagation.
          </Note>
        </Section>
      )}

      {card.corridor && (
        <Section title="The fit">
          <div
            style={{
              display: "grid",
              gap: "var(--sp-05)",
              gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
            }}
          >
            <Stat
              label="Frequency offset"
              value={
                <>
                  {fmt(card.corridor.fitted_offset_hz, 0)}{" "}
                  <span style={{ fontSize: "var(--type-body)" }}>Hz</span>
                </>
              }
              detail={
                card.corridor.fitted_offset_ppm === null
                  ? "no catalogue frequency to express this as a fraction"
                  : `${fmt(card.corridor.fitted_offset_ppm, 1)} ppm of the catalogue downlink`
              }
              tone={
                card.corridor.fitted_offset_ppm !== null &&
                Math.abs(card.corridor.fitted_offset_ppm) >= 20
                  ? "var(--support-03)"
                  : undefined
              }
            />
            <Stat
              label="Corridor half width"
              value={
                <>
                  {fmt(card.corridor.half_width_hz, 0)}{" "}
                  <span style={{ fontSize: "var(--type-body)" }}>Hz</span>
                </>
              }
              detail={`${fmt(card.corridor.half_width_px, 1)} pixels at this image scale`}
            />
            <Stat
              label="Max elevation"
              value={`${fmt(card.corridor.max_elevation_deg, 1)}°`}
              detail="pass geometry from the TLE that was current at capture"
            />
            <Stat
              label="Closest approach"
              value={`${(card.corridor.tca_frac * 100).toFixed(0)}%`}
              detail="through the observation window, where the Doppler curve is steepest"
            />
          </div>

          {card.corridor.offset_at_bound && (
            <Note tone="warn">
              The fit ran into the edge of the search range, so this offset is a lower
              bound on the true one. Observations in that state are flagged in the
              queue and excluded from the stale-catalogue conflict criterion, because
              a bounded fit cannot support a threshold claim.
            </Note>
          )}

          <Note tone="limit">{card.corridor.note}</Note>
        </Section>
      )}

      {entry && (
        <Section
          title="Why it is in the queue"
          description="The composite score and the criteria it met, from the queue receipt."
        >
          <Table head={["Field", "Value", "What it is"]}>
            <tr>
              <Cell align="left" header>
                Rank
              </Cell>
              <Cell mono>{entry.rank}</Cell>
              <Cell align="left">
                of {entry.within_budget ? "and inside" : "and outside"} the review
                budget
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Composite score
              </Cell>
              <Cell mono>{entry.score.toFixed(6)}</Cell>
              <Cell align="left">
                rank-normalised blend of model disagreement, uncertainty and physics
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Model p(signal)
              </Cell>
              <Cell mono>{fmt(entry.model_prob, 6)}</Cell>
              <Cell align="left">
                calibrated probability from the shipped image and corridor arm
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Ensemble spread
              </Cell>
              <Cell mono>{fmt(entry.ensemble_uncertainty, 6)}</Cell>
              <Cell align="left">
                disagreement between seeds; a proxy for how sure the arm is
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Flat rows
              </Cell>
              <Cell mono>{fmt(entry.flat_row_frac, 4)}</Cell>
              <Cell align="left">
                fraction of the waterfall with no luminance variation
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Episode
              </Cell>
              <Cell mono>{entry.episode_key}</Cell>
              <Cell align="left">
                station, satellite and orbital revolution: the unit the interval is
                grouped on
              </Cell>
            </tr>
            <tr>
              <Cell align="left" header>
                Conflict
              </Cell>
              <Cell mono>{String(entry.is_conflict)}</Cell>
              <Cell align="left">
                {entry.reasons.length
                  ? entry.reasons.map((r) => REASON_LABELS[r]).join("; ")
                  : "no criterion met"}
              </Cell>
            </tr>
          </Table>
        </Section>
      )}

      <Section title="Provenance" description="Enough to fetch the original and check it.">
        <Table head={["Field", "Value"]}>
          <tr>
            <Cell align="left" header>
              Source
            </Cell>
            <Cell align="left">
              <a href={`https://network.satnogs.org/observations/${obsId}/`}>
                network.satnogs.org/observations/{obsId}
              </a>
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              Original waterfall SHA-256
            </Cell>
            <Cell align="left" mono>
              {card.source_sha256}
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              Window
            </Cell>
            <Cell align="left" mono>
              {card.start} to {card.end}
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              Receive frequency
            </Cell>
            <Cell align="left" mono>
              {card.rx_freq_hz === null || card.rx_freq_hz === undefined
                ? "not recorded"
                : `${card.rx_freq_hz.toLocaleString("en-GB")} Hz`}
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              Axis derivation
            </Cell>
            <Cell align="left">
              {card.derivation}
              {card.derivation_confidence !== null &&
                card.derivation_confidence !== undefined && (
                  <>
                    {" "}
                    (confidence{" "}
                    <span className="num">{fmt(card.derivation_confidence, 2)}</span>)
                  </>
                )}
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              Displayed image
            </Cell>
            <Cell align="left">{card.intensity}</Cell>
          </tr>
        </Table>
      </Section>
    </div>
  );
}
