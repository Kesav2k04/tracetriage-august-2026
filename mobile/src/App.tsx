/**
 * Three screens and a bar. No navigation library.
 *
 * `expo-router` and `react-navigation` both earn their weight on an app with a stack, deep
 * links and a back gesture that has to behave. This has three peers and one hand-off: a row
 * in the queue opens that observation. A discriminated union and a `switch` say exactly that,
 * in fewer lines than the config for either library, and with nothing to keep in step.
 *
 * The header carries the snapshot id and the gate tally, fetched from the same
 * `/data/provenance.json` the console's rail reads. It is there so that a reader who only
 * ever opens the phone still sees that three of six pre-registered gates are met, rather than
 * being shown a queue with no indication of what it is worth.
 */

import { StatusBar } from "expo-status-bar";
import React, { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
// `SafeAreaView` from react-native is deprecated and, more to the point, applies no top
// inset on Android. `app.json` sets `edgeToEdgeEnabled`, so the window really does start
// behind the status bar: the first build of this screen rendered "TraceTriage" through the
// clock and "3/6 GATES MET" through the battery icon. Running the APK is what found it; the
// bundle built clean, every test passed, and no screenshot had been taken yet.
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";

import { ORIGIN, fetchProvenance, type Provenance } from "./api";
import QueueScreen from "./screens/QueueScreen";
import ObservationScreen from "./screens/ObservationScreen";
import LiveScreen from "./screens/LiveScreen";
import { palette, space, type } from "./theme";

type Tab = "queue" | "observation" | "live";

const TABS: { id: Tab; label: string }[] = [
  { id: "queue", label: "Queue" },
  { id: "observation", label: "Pass" },
  { id: "live", label: "Live" },
];

export default function App() {
  return (
    <SafeAreaProvider>
      <Console />
    </SafeAreaProvider>
  );
}

function Console() {
  const [tab, setTab] = useState<Tab>("queue");
  const [selected, setSelected] = useState<number | null>(null);
  const [provenance, setProvenance] = useState<Provenance | null>(null);

  useEffect(() => {
    fetchProvenance()
      .then(setProvenance)
      .catch(() => {
        // The header is context, not content. A reader with no signal should still get the
        // queue's own error message rather than two of them stacked.
      });
  }, []);

  const gates = provenance?.gate_summary;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      {/* Light glyphs on the dark ground. The bar's own colour is the window's under
          edge-to-edge, which `app.json` sets, so setting it here as well would be the one
          that loses. */}
      <StatusBar style="light" />
      <View style={styles.header}>
        <View>
          <Text style={styles.brand}>TraceTriage</Text>
          <Text style={styles.subtitle}>
            {ORIGIN.replace(/^https:\/\//, "")}
            {provenance ? ` · ${provenance.snapshot_id}` : ""}
          </Text>
        </View>
        {gates ? (
          <View style={styles.gates}>
            <Text style={styles.gateValue}>
              {gates.n_met}/{gates.n_gates}
            </Text>
            <Text style={styles.gateLabel}>gates met</Text>
          </View>
        ) : null}
      </View>

      <View style={styles.body}>
        {tab === "queue" ? (
          <QueueScreen
            onOpen={(obsId) => {
              setSelected(obsId);
              setTab("observation");
            }}
          />
        ) : null}
        {tab === "observation" ? (
          selected === null ? (
            <View style={styles.empty}>
              <Text style={styles.emptyTitle}>No pass chosen</Text>
              <Text style={styles.emptyBody}>
                Open a row in the queue. This screen draws that pass's fitted corridor over
                the waterfall it was fitted to.
              </Text>
            </View>
          ) : (
            <ObservationScreen obsId={selected} />
          )
        ) : null}
        {tab === "live" ? <LiveScreen initialId={selected ?? undefined} /> : null}
      </View>

      <View style={styles.bar}>
        {TABS.map((entry) => {
          const active = entry.id === tab;
          return (
            <Pressable
              key={entry.id}
              style={styles.tab}
              onPress={() => setTab(entry.id)}
              accessibilityRole="tab"
              accessibilityState={{ selected: active }}
              accessibilityLabel={entry.label}
            >
              <View style={[styles.tabMark, active && styles.tabMarkActive]} />
              <Text style={[styles.tabLabel, active && styles.tabLabelActive]}>
                {entry.label}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.ground },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: space.page,
    paddingTop: space.gap,
    paddingBottom: space.gap,
    borderBottomColor: palette.edge,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  brand: { color: palette.ink, fontSize: type.heading, fontWeight: "600", letterSpacing: 0.3 },
  subtitle: { color: palette.quiet, fontSize: type.label, marginTop: 2 },
  gates: { alignItems: "flex-end" },
  gateValue: {
    color: palette.accent,
    fontSize: type.heading,
    fontVariant: ["tabular-nums"],
  },
  gateLabel: {
    color: palette.quiet,
    fontSize: type.label,
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  body: { flex: 1 },
  empty: { flex: 1, alignItems: "center", justifyContent: "center", padding: space.page * 2 },
  emptyTitle: { color: palette.ink, fontSize: type.heading, marginBottom: space.tight },
  emptyBody: {
    color: palette.quiet,
    fontSize: type.body,
    lineHeight: 21,
    textAlign: "center",
  },
  bar: {
    flexDirection: "row",
    borderTopColor: palette.edge,
    borderTopWidth: StyleSheet.hairlineWidth,
    backgroundColor: palette.raised,
  },
  tab: { flex: 1, alignItems: "center", paddingVertical: space.gap },
  tabMark: {
    width: 18,
    height: 2,
    backgroundColor: "transparent",
    marginBottom: space.tight,
  },
  tabMarkActive: { backgroundColor: palette.accent },
  tabLabel: { color: palette.quiet, fontSize: type.body },
  tabLabelActive: { color: palette.ink, fontWeight: "600" },
});
