/**
 * Screen three: measure a pass recorded today.
 *
 * Everything else in this client reads a frozen snapshot. This posts an observation id to
 * `/api/live/`, which downloads that waterfall from SatNOGS and fits a corridor to it while
 * you wait. It is the answer to the fair criticism of the rest: a queue over a fixed corpus
 * is an exhibit, and this is the same code measuring something nobody chose in advance.
 *
 * Two things this screen refuses to do.
 *
 * It does not hide a refusal. The endpoint has a code for every way it declines, the code is
 * shown, and the copy for an unreachable endpoint says a cold start can exceed the platform's
 * function limit rather than blaming the network. A client that reported every failure as
 * "something went wrong" would make a reader distrust the measurement they got last time.
 *
 * It does not show an offset without the verdict beside it. `mode.verdict` is whether the
 * station Doppler-corrected the capture at all, and an offset measured against the wrong
 * hypothesis is a number with no meaning. UNRESOLVED is the common case on a real queue and
 * is the honest answer: this image does not settle it, skip this one.
 */

import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Keyboard,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { measure, type LiveResult } from "../api";
import { palette, space, type } from "../theme";
import { Panel, Row, Stat, Tag, fmt, int, shortSha } from "../ui";

/** Ids worth trying: three passes the snapshot already holds, so the answer can be compared. */
const SUGGESTED = [14746092, 14735140, 14732518];

type State =
  | { kind: "idle" }
  | { kind: "measuring"; obsId: number }
  | { kind: "done"; obsId: number; result: LiveResult };

export default function LiveScreen({ initialId }: { initialId?: number }) {
  const [text, setText] = useState(initialId ? String(initialId) : "");
  const [state, setState] = useState<State>({ kind: "idle" });
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (state.kind === "measuring") {
      setElapsed(0);
      timer.current = setInterval(() => setElapsed((seconds) => seconds + 1), 1000);
    } else if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [state.kind]);

  const run = async (raw: string) => {
    const obsId = Number.parseInt(raw.trim(), 10);
    if (!Number.isFinite(obsId) || obsId <= 0) {
      setState({
        kind: "done",
        obsId: 0,
        result: {
          kind: "refused",
          code: "BAD_OBS_ID",
          detail: "An observation id is a positive integer, as it appears in a SatNOGS URL.",
        },
      });
      return;
    }
    Keyboard.dismiss();
    setState({ kind: "measuring", obsId });
    const result = await measure(obsId);
    setState({ kind: "done", obsId, result });
  };

  return (
    <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>Measure a pass recorded today</Text>
      <Text style={styles.quiet}>
        An observation id from satnogs.org. The endpoint downloads that waterfall and fits a
        corridor to it, which takes tens of seconds. Nothing is cached on this phone.
      </Text>
      <Text style={styles.quiet}>
        On the passes this queue flags, the verdict usually comes back UNRESOLVED. The mode
        needs one shape to lead by 8 sigma and a weak pass does not settle it, so the offset
        is withheld rather than guessed. That is the answer that says skip this one.
      </Text>

      <View style={styles.controls}>
        <TextInput
          value={text}
          onChangeText={setText}
          keyboardType="number-pad"
          placeholder="14746092"
          placeholderTextColor={palette.quiet}
          style={styles.input}
          accessibilityLabel="SatNOGS observation id"
          editable={state.kind !== "measuring"}
          onSubmitEditing={() => void run(text)}
        />
        <Pressable
          style={({ pressed }) => [
            styles.button,
            pressed && styles.buttonPressed,
            state.kind === "measuring" && styles.buttonDisabled,
          ]}
          disabled={state.kind === "measuring"}
          onPress={() => void run(text)}
          accessibilityRole="button"
        >
          <Text style={styles.buttonText}>
            {state.kind === "measuring" ? "Measuring" : "Measure"}
          </Text>
        </Pressable>
      </View>

      <Row>
        {SUGGESTED.map((id) => (
          <Pressable key={id} onPress={() => setText(String(id))}>
            <Tag text={String(id)} tone="accent" />
          </Pressable>
        ))}
      </Row>

      {state.kind === "measuring" ? (
        <Panel title={`Measuring observation ${state.obsId}`}>
          <View style={styles.measuring}>
            <ActivityIndicator color={palette.accent} />
            <Text style={styles.elapsed}>{elapsed}s</Text>
          </View>
          <Text style={styles.body}>
            One waterfall download, then a bounded offset search against the pass's own
            predicted corridor and a set of nulls built from the same physics.
          </Text>
        </Panel>
      ) : null}

      {state.kind === "done" && state.result.kind === "refused" ? (
        <Panel title="Refused">
          <Tag text={state.result.code} tone="alarm" />
          <Text style={[styles.body, styles.spaced]}>{state.result.detail}</Text>
        </Panel>
      ) : null}

      {state.kind === "done" && state.result.kind === "measured" ? (
        <Result result={state.result} />
      ) : null}
    </ScrollView>
  );
}

function Result({ result }: { result: Extract<LiveResult, { kind: "measured" }> }) {
  const m = result.measurement;
  const mode = m.mode ?? {};
  const measurement = m.measurement ?? {};
  const nulls = m.nulls ?? {};
  const observation = m.observation ?? {};
  const provenance = m.provenance ?? {};
  const unresolved = (mode.verdict ?? "").toUpperCase() === "UNRESOLVED";

  return (
    <>
      <Panel title={(observation.satellite ?? "").replace(/^0 /, "") || "Measured"}>
        <Text style={styles.quiet}>
          observation {observation.id ?? "—"}
          {observation.station_name ? ` · ${observation.station_name}` : ""}
          {result.source === "shelf" ? " · from the shelf, not measured now" : ""}
        </Text>
        <Row>
          <Stat
            label="offset"
            value={`${int(measurement.offset_hz)} Hz`}
            tone={unresolved ? "ink" : "accent"}
            hint={`${fmt(measurement.offset_ppm, 2)} ppm`}
          />
          <Stat label="sigma" value={fmt(measurement.sigma, 2)} />
          <Stat
            label="nulls"
            value={nulls.not_tested ? "not tested" : int(nulls.n)}
            hint={nulls.not_tested ?? `p = ${fmt(nulls.p_value, 3)}`}
          />
        </Row>
        {measurement.at_search_bound ? (
          <Tag text="AT SEARCH BOUND: the true offset may be larger" tone="alarm" />
        ) : null}
      </Panel>

      <Panel title="Was the capture Doppler-corrected" note={mode.why}>
        <Tag text={mode.verdict ?? "—"} tone={unresolved ? "quiet" : "accent"} />
        <Row>
          <Stat label="sigma, curved" value={fmt(mode.sigma_curved, 2)} />
          <Stat label="sigma, vertical" value={fmt(mode.sigma_vertical, 2)} />
          <Stat label="corridor scored" value={mode.corridor_scored ?? "—"} />
        </Row>
      </Panel>

      <Panel
        title="Where this came from"
        note={
          "The digest is of the waterfall as downloaded for this measurement. Two runs on "
          + "the same observation should agree on it"
          + (unresolved
            ? ". There is no offset to compare, because the verdict withheld it."
            : ", and on the offset.")
        }
      >
        <Row>
          <Stat label="measured at" value={(provenance.measured_at_utc ?? "—").slice(0, 19)} />
          <Stat label="waterfall" value={shortSha(provenance.waterfall_sha256)} />
          <Stat label="bytes" value={int(provenance.waterfall_bytes)} />
          <Stat label="elements" value={provenance.tle_source ?? "—"} />
          <Stat label="Hz per pixel" value={fmt(m.axis?.hz_per_px, 1)} />
        </Row>
      </Panel>
    </>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.page, paddingBottom: space.page * 3 },
  title: { color: palette.ink, fontSize: type.title, fontWeight: "600" },
  quiet: { color: palette.quiet, fontSize: type.body, lineHeight: 21, marginTop: 4 },
  body: { color: palette.ink, fontSize: type.body, lineHeight: 22 },
  spaced: { marginTop: space.gap },
  controls: { flexDirection: "row", alignItems: "center", marginTop: space.gap },
  input: {
    flex: 1,
    backgroundColor: palette.corridor,
    borderColor: palette.edge,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 4,
    color: palette.ink,
    fontSize: type.heading,
    fontVariant: ["tabular-nums"],
    paddingHorizontal: space.gap,
    paddingVertical: 10,
    marginRight: space.tight,
  },
  button: {
    backgroundColor: palette.accent,
    borderRadius: 4,
    paddingHorizontal: space.page,
    paddingVertical: 12,
  },
  buttonPressed: { opacity: 0.8 },
  buttonDisabled: { backgroundColor: palette.edge },
  buttonText: { color: palette.ground, fontSize: type.body, fontWeight: "600" },
  measuring: { flexDirection: "row", alignItems: "center", marginBottom: space.gap },
  elapsed: {
    color: palette.accent,
    fontSize: type.heading,
    fontVariant: ["tabular-nums"],
    marginLeft: space.gap,
  },
});
