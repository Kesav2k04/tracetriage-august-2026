/** The few shared pieces. Small enough that a component library would cost more than it saves. */

import React from "react";
import { StyleSheet, Text, View } from "react-native";

import { palette, space, type } from "./theme";

export const fmt = (value: number | null | undefined, digits = 2): string =>
  typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";

export const int = (value: number | null | undefined): string =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.round(value).toLocaleString("en-GB")
    : "—";

export const shortSha = (sha: string | null | undefined): string =>
  sha ? `${sha.slice(0, 12)}…` : "—";

/** A labelled value. The label is the field's own name so a reader can find it in a receipt. */
export function Stat({
  label,
  value,
  hint,
  tone = "ink",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "ink" | "accent" | "alarm";
}) {
  const colour =
    tone === "accent" ? palette.accent : tone === "alarm" ? palette.alarm : palette.ink;
  return (
    <View style={styles.stat}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.statValue, { color: colour }]}>{value}</Text>
      {hint ? <Text style={styles.hint}>{hint}</Text> : null}
    </View>
  );
}

export function Panel({
  title,
  children,
  note,
}: {
  title?: string;
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <View style={styles.panel}>
      {title ? <Text style={styles.panelTitle}>{title}</Text> : null}
      {children}
      {note ? <Text style={styles.note}>{note}</Text> : null}
    </View>
  );
}

/** A reason code, shown verbatim. Renaming these in the client would break the only link
 *  between what a phone shows and what `artifacts/QUEUE_RECEIPT.json` records. */
export function Tag({ text, tone = "quiet" }: { text: string; tone?: "quiet" | "accent" | "alarm" }) {
  const colour =
    tone === "accent" ? palette.accent : tone === "alarm" ? palette.alarm : palette.quiet;
  return (
    <View style={[styles.tag, { borderColor: colour }]}>
      <Text style={[styles.tagText, { color: colour }]}>{text}</Text>
    </View>
  );
}

export function Row({ children }: { children: React.ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

const styles = StyleSheet.create({
  panel: {
    backgroundColor: palette.raised,
    borderColor: palette.edge,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 8,
    padding: space.page,
    marginBottom: space.gap,
  },
  panelTitle: {
    color: palette.ink,
    fontSize: type.heading,
    fontWeight: "600",
    marginBottom: space.gap,
  },
  note: {
    color: palette.quiet,
    fontSize: type.label,
    lineHeight: 18,
    marginTop: space.gap,
  },
  stat: { minWidth: 108, marginRight: space.gap, marginBottom: space.gap },
  label: {
    color: palette.quiet,
    fontSize: type.label,
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  statValue: {
    fontSize: type.heading,
    fontVariant: ["tabular-nums"],
    marginTop: 2,
  },
  hint: { color: palette.quiet, fontSize: type.label, marginTop: 2 },
  tag: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 3,
    paddingHorizontal: 6,
    paddingVertical: 2,
    marginRight: space.tight,
    marginTop: space.tight,
  },
  tagText: { fontSize: type.label, letterSpacing: 0.4 },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "flex-start" },
});
