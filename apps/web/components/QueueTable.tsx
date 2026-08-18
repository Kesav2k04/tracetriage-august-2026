"use client";

/**
 * The ranked queue, filterable.
 *
 * Filtering is a view over the exported rows and never changes an ordering: the
 * rank column is the rank the pipeline assigned, so a filtered view shows gaps
 * rather than renumbering. A table that renumbered its rows under a filter would
 * be showing a ranking nobody measured.
 *
 * Rows are windowed, because 407 rows of six cells each is a 2,400-node table and
 * a reader looks at the top of it. "Show all" is one click away and the filter
 * counts always describe the whole set, not the window.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import {
  NON_ACTIONABLE,
  REASON_LABELS,
  type QueueReason,
  type QueueRow,
} from "@/lib/queue-view";
import { Cell, Table, Tag } from "./ui";

const PAGE = 60;

type Filter = "all" | "budget" | "conflict" | "displaced" | QueueReason;

export default function QueueTable({
  entries,
  imaged,
  budget,
}: {
  entries: QueueRow[];
  imaged: number[];
  budget: number;
}) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);

  const imagedSet = useMemo(() => new Set(imaged), [imaged]);

  const counts = useMemo(() => {
    const out = new Map<string, number>([["all", entries.length]]);
    const bump = (key: string) => out.set(key, (out.get(key) ?? 0) + 1);
    for (const entry of entries) {
      if (entry.within_budget) bump("budget");
      if (entry.is_conflict) bump("conflict");
      if (entry.displaced_by_cap) bump("displaced");
      for (const reason of entry.reasons) bump(reason);
    }
    return out;
  }, [entries]);

  const rows = useMemo(() => {
    const needle = query.trim();
    return entries.filter((entry) => {
      if (filter === "budget" && !entry.within_budget) return false;
      if (filter === "conflict" && !entry.is_conflict) return false;
      if (filter === "displaced" && !entry.displaced_by_cap) return false;
      if (
        filter !== "all" &&
        filter !== "budget" &&
        filter !== "conflict" &&
        filter !== "displaced" &&
        !entry.reasons.includes(filter)
      ) {
        return false;
      }
      if (needle && !String(entry.obs_id).includes(needle)) return false;
      return true;
    });
  }, [entries, filter, query]);

  const shown = rows.slice(0, limit);

  const chips: Array<{ key: Filter; label: string }> = [
    { key: "all", label: "All" },
    { key: "budget", label: `Within budget (${budget})` },
    { key: "conflict", label: "Conflicts" },
    { key: "displaced", label: "Displaced by a cap" },
    ...(Object.keys(REASON_LABELS) as QueueReason[])
      .filter((reason) => (counts.get(reason) ?? 0) > 0)
      .map((reason) => ({ key: reason as Filter, label: REASON_LABELS[reason] })),
  ];

  return (
    <div>
      {/*
        Filtering is the one thing on this page that needs scripting. With it
        off the controls are hidden rather than left sitting there dead, and the
        table below still renders the top of the queue, which is the part a
        reader came for.
      */}
      <noscript>
        <style>{".queue-controls, .queue-more { display: none; }"}</style>
        <p
          style={{
            margin: "0 0 var(--sp-05)",
            padding: "var(--sp-03) var(--sp-04)",
            borderLeft: "3px solid var(--text-03)",
            background: "var(--ui-01)",
            fontSize: "var(--type-caption)",
            color: "var(--text-02)",
          }}
        >
          Filtering needs JavaScript and it is switched off, so the first rows of
          the queue are shown unfiltered. Every number in them was rendered on the
          server and is complete.
        </p>
      </noscript>

      <div
        className="queue-controls"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--sp-03)",
          alignItems: "center",
          marginBottom: "var(--sp-05)",
        }}
        role="group"
        aria-label="Filter the queue"
      >
        {chips.map((chip) => {
          const active = filter === chip.key;
          const n = counts.get(chip.key) ?? 0;
          return (
            <button
              key={chip.key}
              type="button"
              aria-pressed={active}
              onClick={() => {
                setFilter(chip.key);
                setLimit(PAGE);
              }}
              style={{
                padding: "var(--sp-02) var(--sp-04)",
                background: active ? "var(--interactive-01)" : "transparent",
                color: active ? "var(--text-04)" : "var(--text-02)",
                border: `1px solid ${
                  active ? "var(--interactive-01)" : "var(--border-strong)"
                }`,
                font: "inherit",
                fontSize: "var(--type-caption)",
                cursor: "pointer",
                transition: "background var(--dur-fast-02) var(--ease-productive-standard)",
              }}
            >
              {chip.label}
              <span className="num" style={{ marginLeft: "var(--sp-03)", opacity: 0.8 }}>
                {n}
              </span>
            </button>
          );
        })}

        <label
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
            gap: "var(--sp-03)",
            fontSize: "var(--type-caption)",
            color: "var(--text-02)",
          }}
        >
          Observation id
          <input
            type="search"
            inputMode="numeric"
            value={query}
            placeholder="14746092"
            onChange={(event) => {
              setQuery(event.target.value);
              setLimit(PAGE);
            }}
            style={{
              background: "var(--field-01)",
              border: "1px solid var(--border-strong)",
              color: "var(--text-01)",
              padding: "var(--sp-02) var(--sp-03)",
              font: "inherit",
              fontFamily: "var(--font-mono)",
              width: "9rem",
            }}
          />
        </label>
      </div>

      <p
        aria-live="polite"
        className="queue-controls"
        style={{
          margin: "0 0 var(--sp-04)",
          fontSize: "var(--type-caption)",
          color: "var(--text-03)",
        }}
      >
        Showing <span className="num">{shown.length}</span> of{" "}
        <span className="num">{rows.length}</span> matching rows, from{" "}
        <span className="num">{entries.length}</span> in the queue. Rank is the rank
        the pipeline assigned and does not change under a filter.
      </p>

      {shown.length === 0 && (
        <p
          style={{
            margin: "var(--sp-05) 0",
            padding: "var(--sp-05)",
            border: "1px solid var(--border-strong)",
            background: "var(--ui-01)",
            color: "var(--text-02)",
            lineHeight: 1.6,
          }}
        >
          No row matches{query.trim() ? ` observation ${query.trim()}` : " this filter"}.
          That is an empty result, not a failure: the queue holds{" "}
          <span className="num">{entries.length}</span> rows and none of them meet the
          condition you asked for. Clear the filter to see them.
        </p>
      )}

      <Table
        head={[
          "Rank",
          "Observation",
          "Score",
          "Why it is here",
          "Label",
          "Model p(signal)",
          "Offset ppm",
        ]}
        caption="The shipped chronological queue. A row inside the review budget is one a reviewer would actually reach."
      >
        {shown.map((entry) => {
          const inBudget = entry.within_budget === true;
          return (
            <tr
              key={entry.obs_id}
              style={{
                background: inBudget ? "rgba(69,137,255,0.05)" : undefined,
              }}
            >
              <Cell align="left" mono>
                {entry.rank}
                {inBudget && (
                  <span
                    title="Inside the review budget"
                    aria-label="inside the review budget"
                    style={{ color: "var(--interactive-04)", marginLeft: 6 }}
                  >
                    ●
                  </span>
                )}
              </Cell>
              <Cell align="left" mono>
                {imagedSet.has(entry.obs_id) ? (
                  <Link href={`/observation/${entry.obs_id}/`}>{entry.obs_id}</Link>
                ) : (
                  <span title="No waterfall shipped for this observation">
                    {entry.obs_id}
                  </span>
                )}
              </Cell>
              <Cell mono>{entry.score.toFixed(4)}</Cell>
              <Cell align="left">
                <span
                  style={{ display: "flex", gap: "var(--sp-02)", flexWrap: "wrap" }}
                >
                  {entry.reasons.length === 0 && (
                    <Tag tone="muted">no criterion met</Tag>
                  )}
                  {entry.reasons.map((reason) => (
                    <Tag
                      key={reason}
                      tone={NON_ACTIONABLE.has(reason) ? "muted" : "action"}
                      title={REASON_LABELS[reason]}
                    >
                      {REASON_LABELS[reason]}
                    </Tag>
                  ))}
                </span>
              </Cell>
              <Cell align="left">{entry.waterfall_status}</Cell>
              <Cell mono>
                {entry.model_prob === null ? "—" : entry.model_prob.toFixed(3)}
              </Cell>
              <Cell mono>
                {entry.fitted_offset_ppm === null
                  ? "—"
                  : entry.fitted_offset_ppm.toFixed(1)}
                {entry.offset_at_bound ? (
                  <span
                    title="The fit ran into the search bound, so the true offset is at least this"
                    style={{ color: "var(--support-03)" }}
                  >
                    {" "}
                    ≥
                  </span>
                ) : null}
              </Cell>
            </tr>
          );
        })}
      </Table>

      {shown.length < rows.length && (
        <button
          type="button"
          className="queue-more"
          onClick={() => setLimit(rows.length)}
          style={{
            marginTop: "var(--sp-05)",
            padding: "var(--sp-03) var(--sp-05)",
            background: "transparent",
            border: "1px solid var(--border-strong)",
            color: "var(--text-01)",
            font: "inherit",
            cursor: "pointer",
          }}
        >
          Show the remaining {rows.length - shown.length} rows
        </button>
      )}
    </div>
  );
}
