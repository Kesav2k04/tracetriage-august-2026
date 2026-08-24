/**
 * Screen two: the predicted Doppler corridor, drawn over the waterfall it was fitted to.
 *
 * This is the screen the whole client exists for. A list of scores is a list of scores; the
 * question a reviewer actually has is whether the corridor sits on the trace, and that is a
 * picture. The console has this and no other mobile client in this challenge has anything
 * like it.
 *
 * The coordinate space, because this is where a plot like this goes wrong. The waterfall is
 * 603 by 1549 pixels and the corridor is given in those same pixels: `rows` are y, `fitted_px`
 * and `predicted_px` are x, and `half_width_px` is the tolerance either side. The overlay is
 * therefore an SVG whose `viewBox` is the image's own pixel box, laid over an `Image` scaled
 * to the same rectangle. No coordinate is multiplied by anything anywhere in this file. Doing
 * the scaling by hand is how a curve ends up plausibly wrong instead of obviously wrong, and
 * a corridor displaced by a few percent still looks like a corridor.
 *
 * Three things are drawn, and each is a different kind of claim:
 *
 *   the band      what the fit was allowed, half_width_px either side of the fitted curve
 *   dashed grey   where the orbit says the signal should be, with no offset applied
 *   solid gold    where the fit put it
 *
 * The gap between the last two is the measurement. If they coincide, the station corrected
 * for Doppler; if the gold curve is an S and the grey one is a line, it did not.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Image,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import Svg, { Line, Path, Polyline } from "react-native-svg";

import { fetchCards, imageUrl, type Card } from "../api";
import { palette, space, type } from "../theme";
import { Panel, Row, Stat, Tag, fmt, int, shortSha } from "../ui";

/** The band, as one closed path: down the far edge of the corridor and back up the near one. */
function bandPath(rows: number[], centre: number[], halfWidth: number): string {
  const down = rows.map((y, i) => `${(centre[i] + halfWidth).toFixed(2)},${y.toFixed(2)}`);
  const up = rows
    .map((y, i) => `${(centre[i] - halfWidth).toFixed(2)},${y.toFixed(2)}`)
    .reverse();
  return `M${down.join(" L")} L${up.join(" L")} Z`;
}

const points = (rows: number[], xs: number[]): string =>
  rows.map((y, i) => `${xs[i].toFixed(2)},${y.toFixed(2)}`).join(" ");

export default function ObservationScreen({ obsId }: { obsId: number }) {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { width: screenWidth } = useWindowDimensions();

  useEffect(() => {
    let live = true;
    setCard(null);
    setError(null);
    fetchCards()
      .then((cards) => {
        if (!live) return;
        const found = cards.get(obsId);
        if (!found) {
          setError(
            `Observation ${obsId} is not in this snapshot. The queue holds the passes the `
            + "pipeline scored; a newer id can still be measured on the Live screen.",
          );
          return;
        }
        setCard(found);
      })
      .catch((caught) => {
        if (live) setError(caught instanceof Error ? caught.message : String(caught));
      });
    return () => {
      live = false;
    };
  }, [obsId]);

  const plot = useMemo(() => {
    if (!card || !card.width || !card.height) return null;
    const width = Math.min(screenWidth - space.page * 2, 520);
    return { width, height: (width * card.height) / card.width };
  }, [card, screenWidth]);

  if (error) {
    return (
      <ScrollView contentContainerStyle={styles.page}>
        <Panel title={`Observation ${obsId}`}>
          <Text style={styles.body}>{error}</Text>
        </Panel>
      </ScrollView>
    );
  }

  if (!card || !plot) {
    return (
      <View style={styles.centre}>
        <ActivityIndicator color={palette.accent} />
        <Text style={styles.quiet}>Reading the card index</Text>
      </View>
    );
  }

  const corridor = card.corridor ?? null;
  const url = imageUrl(card);

  return (
    <ScrollView contentContainerStyle={styles.page}>
      <Text style={styles.title}>{(card.satellite ?? "").replace(/^0 /, "") || "Unnamed"}</Text>
      <Text style={styles.quiet}>
        observation {card.obs_id}
        {card.station_name ? ` · ${card.station_name}` : ""}
        {card.start ? ` · ${card.start.slice(0, 16).replace("T", " ")} UTC` : ""}
      </Text>

      {card.degraded ? (
        <Panel title="No image was shipped for this pass">
          <Text style={styles.body}>{card.degraded}</Text>
        </Panel>
      ) : null}

      {url ? (
        <View style={[styles.plot, { width: plot.width, height: plot.height }]}>
          <Image
            source={{ uri: url }}
            style={{ width: plot.width, height: plot.height }}
            resizeMode="stretch"
            accessibilityLabel={
              `Waterfall for observation ${card.obs_id}. Time runs down, frequency across.`
            }
          />
          {corridor ? (
            <Svg
              style={StyleSheet.absoluteFill}
              width={plot.width}
              height={plot.height}
              viewBox={`0 0 ${card.width} ${card.height}`}
              preserveAspectRatio="none"
            >
              <Path
                d={bandPath(corridor.rows, corridor.fitted_px, corridor.half_width_px)}
                fill={palette.accent}
                fillOpacity={0.16}
              />
              {card.centre_px != null ? (
                <Line
                  x1={card.centre_px}
                  y1={0}
                  x2={card.centre_px}
                  y2={card.height}
                  stroke={palette.quiet}
                  strokeWidth={1.5}
                  strokeDasharray="8 8"
                />
              ) : null}
              <Polyline
                points={points(corridor.rows, corridor.predicted_px)}
                fill="none"
                stroke={palette.ink}
                strokeWidth={2}
                strokeOpacity={0.65}
                strokeDasharray="10 8"
              />
              <Polyline
                points={points(corridor.rows, corridor.fitted_px)}
                fill="none"
                stroke={palette.accent}
                strokeWidth={2.5}
              />
            </Svg>
          ) : null}
        </View>
      ) : null}

      <View style={styles.legend}>
        <Row>
          <Tag text="gold: where the fit put it" tone="accent" />
          <Tag text="dashed: where the orbit says it should be" />
          <Tag text="vertical: the commanded frequency" />
        </Row>
      </View>

      {corridor ? (
        <Panel title="The measurement" note={corridor.note}>
          <Row>
            <Stat
              label="offset"
              value={`${int(corridor.fitted_offset_hz)} Hz`}
              tone="accent"
              hint={`${fmt(corridor.fitted_offset_ppm, 2)} ppm`}
            />
            <Stat label="corridor" value={`± ${int(corridor.half_width_hz)} Hz`} />
            <Stat label="max elevation" value={`${fmt(corridor.max_elevation_deg, 1)}°`} />
            <Stat
              label="closest approach"
              value={`${fmt(corridor.tca_frac * 100, 0)}%`}
              hint="through the pass"
            />
          </Row>
          {corridor.offset_at_bound ? (
            <Tag text="AT SEARCH BOUND: the true offset may be larger" tone="alarm" />
          ) : null}
        </Panel>
      ) : (
        <Panel title="No corridor was fitted">
          <Text style={styles.body}>
            {card.corridor_note
              ?? "This pass has no fitted corridor in the snapshot, so there is nothing to "
                + "draw over the image."}
          </Text>
        </Panel>
      )}

      <Panel
        title="The image"
        note={
          "Waterfall from SatNOGS, CC BY-SA 4.0, redistributed unmodified. The digest is of "
          + "the file as downloaded, so the picture above can be checked against the source."
        }
      >
        <Row>
          <Stat label="size" value={`${card.width} × ${card.height} px`} />
          <Stat label="frequency" value={`${fmt(card.hz_per_px, 1)} Hz/px`} />
          <Stat label="time" value={`${fmt(card.seconds_per_px, 3)} s/px`} />
          <Stat label="axis from" value={card.derivation ?? "—"} />
          <Stat label="sha256" value={shortSha(card.source_sha256)} />
        </Row>
      </Panel>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.page, paddingBottom: space.page * 3 },
  title: { color: palette.ink, fontSize: type.title, fontWeight: "600" },
  quiet: { color: palette.quiet, fontSize: type.body, marginTop: 4 },
  body: { color: palette.ink, fontSize: type.body, lineHeight: 22 },
  plot: {
    marginTop: space.gap,
    backgroundColor: palette.sunken,
    borderColor: palette.edge,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 4,
    overflow: "hidden",
    alignSelf: "center",
  },
  legend: { marginTop: space.tight, marginBottom: space.gap },
  centre: { flex: 1, alignItems: "center", justifyContent: "center" },
});
