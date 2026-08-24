/**
 * Screen one: the ranked passes.
 *
 * The same 407 entries the console's landing page ranks, in the same order, from the same
 * file. What a reviewer needs off a list is which pass to open next and why, so each row
 * carries the score, the reason codes verbatim, and whether the pass is inside the review
 * budget. The reason codes are not translated into friendlier words: `MODEL_LABEL_DISAGREE`
 * is what `artifacts/QUEUE_RECEIPT.json` records, and a reviewer who sees a different
 * vocabulary on a phone than in the receipt cannot check one against the other.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { fetchQueue, type QueueEntry } from "../api";
import { palette, space, type } from "../theme";
import { Row, Tag, fmt } from "../ui";

export default function QueueScreen({ onOpen }: { onOpen: (obsId: number) => void }) {
  const [entries, setEntries] = useState<QueueEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const queue = await fetchQueue();
      setEntries(queue.entries);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <View style={styles.centre}>
        <Text style={styles.errorTitle}>The queue did not load</Text>
        <Text style={styles.errorBody}>{error}</Text>
        <Pressable style={styles.retry} onPress={() => void load()}>
          <Text style={styles.retryText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  if (!entries) {
    return (
      <View style={styles.centre}>
        <ActivityIndicator color={palette.accent} />
        <Text style={styles.errorBody}>Reading the queue</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={entries}
      keyExtractor={(entry) => String(entry.obs_id)}
      contentContainerStyle={styles.list}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          tintColor={palette.accent}
          onRefresh={() => {
            setRefreshing(true);
            void load().finally(() => setRefreshing(false));
          }}
        />
      }
      ListHeaderComponent={
        <Text style={styles.lead}>
          {entries.length.toLocaleString("en-GB")} passes, highest review value first. The
          score is the queue's, not a model's confidence: it is what a reviewer's next ten
          minutes are worth on this pass.
        </Text>
      }
      renderItem={({ item }) => (
        <Pressable
          style={({ pressed }) => [styles.card, pressed && styles.cardPressed]}
          onPress={() => onOpen(item.obs_id)}
          accessibilityRole="button"
          accessibilityLabel={
            `Rank ${item.rank}, observation ${item.obs_id}, ${item.satellite}, `
            + `score ${fmt(item.score, 3)}`
          }
        >
          <View style={styles.cardHead}>
            <Text style={styles.rank}>{item.rank}</Text>
            <View style={styles.cardTitle}>
              <Text style={styles.satellite} numberOfLines={1}>
                {item.satellite.replace(/^0 /, "")}
              </Text>
              <Text style={styles.obsId}>observation {item.obs_id}</Text>
            </View>
            <Text style={styles.score}>{fmt(item.score, 3)}</Text>
          </View>
          <Row>
            {item.reasons.map((reason) => (
              <Tag key={reason} text={reason} tone="accent" />
            ))}
            {item.is_conflict ? <Tag text="CONFLICT" tone="alarm" /> : null}
            {item.within_budget === false ? <Tag text="OUTSIDE BUDGET" /> : null}
            {item.waterfall_status ? <Tag text={item.waterfall_status} /> : null}
          </Row>
        </Pressable>
      )}
    />
  );
}

const styles = StyleSheet.create({
  list: { padding: space.page, paddingBottom: space.page * 3 },
  lead: {
    color: palette.quiet,
    fontSize: type.body,
    lineHeight: 21,
    marginBottom: space.gap,
  },
  card: {
    backgroundColor: palette.raised,
    borderColor: palette.edge,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 8,
    padding: space.gap,
    marginBottom: space.gap,
  },
  cardPressed: { backgroundColor: palette.corridor },
  cardHead: { flexDirection: "row", alignItems: "center" },
  rank: {
    color: palette.quiet,
    fontSize: type.body,
    fontVariant: ["tabular-nums"],
    width: 34,
  },
  cardTitle: { flex: 1, paddingRight: space.tight },
  satellite: { color: palette.ink, fontSize: type.heading, fontWeight: "600" },
  obsId: { color: palette.quiet, fontSize: type.label, marginTop: 2 },
  score: {
    color: palette.accent,
    fontSize: type.heading,
    fontVariant: ["tabular-nums"],
  },
  centre: { flex: 1, alignItems: "center", justifyContent: "center", padding: space.page },
  errorTitle: { color: palette.ink, fontSize: type.heading, marginBottom: space.tight },
  errorBody: {
    color: palette.quiet,
    fontSize: type.body,
    textAlign: "center",
    marginTop: space.tight,
  },
  retry: {
    marginTop: space.gap,
    borderColor: palette.accent,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: 4,
    paddingHorizontal: space.gap,
    paddingVertical: space.tight,
  },
  retryText: { color: palette.accent, fontSize: type.body },
});
