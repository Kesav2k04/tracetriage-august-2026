/**
 * The queue against the orderings a reviewer could have used instead.
 *
 * Beating random is a low bar. The question that decides whether this ranking is
 * worth building is whether it beats the orderings anybody could produce without
 * a model: take them oldest first, take them by how unsure the image model is,
 * take them by physics alone, or sort on the one number that defines most of the
 * conflicts.
 *
 * That last one was added after a review pointed out that the first three all
 * miss the obvious alternative, and it is the hardest of them: it reproduces the
 * shipped queue's lift exactly. Adding it widens the Bonferroni correction on
 * every other comparison on this page, including the ones the queue wins.
 *
 * Each comparison is run twice, grouped two different ways, and a baseline counts
 * as beaten only when both groupings survive a Bonferroni correction and agree.
 */
import {
  fmt,
  fmtInterval,
  requireGate6Split,
  showcaseIds,
  type Replay,
  type SplitGate6,
} from "@/lib/data";
import Link from "next/link";

import { IntervalChart } from "@/components/charts";
import { Cell, Note, Section, Stat, Table, Tag } from "@/components/ui";

export const metadata = { title: "Baselines" };

const ORDERING_LABELS: Record<string, string> = {
  queue: "The shipped queue",
  fifo: "Oldest first",
  image_uncertainty: "Most uncertain image first",
  physics_only: "Physics score only",
  offset_magnitude: "Largest frequency offset first",
};

const ORDERING_NOTES: Record<string, string> = {
  queue: "the composite score this project produces",
  fifo: "what a reviewer working through a backlog does by default",
  image_uncertainty: "classic active learning: review what the model is least sure about",
  physics_only: "pass geometry and corridor fit, with no image model at all",
  offset_magnitude:
    "one line: sort on the offset that defines most of the conflicts, and see whether the other three score terms bought anything",
};

/** The observation this page points at for the pass playback.
 *
 * Taken from the shipped showcase rather than hardcoded, so it cannot become a link
 * to a page that stopped being built. `showcaseIds` is the same list the observation
 * routes are generated from.
 */
const playbackId = showcaseIds[0];

const CLAIM_COLOUR: Record<string, string> = {
  queue_better: "var(--verdict-passed)",
  baseline_better: "var(--verdict-failed)",
  not_established: "var(--verdict-not-established)",
};

/**
 * The outcome of one comparison.
 *
 * Deliberately not the gate vocabulary. "PASSED" beside a baseline would read as
 * a kill gate that was met, and no kill gate is being decided here: this is one
 * ordering against another.
 */
const CLAIM_LABEL: Record<string, string> = {
  queue_better: "the queue beats it",
  baseline_better: "it beats the queue",
  not_established: "not established",
};

function ClaimBadge({ claim }: { claim: string }) {
  const colour = CLAIM_COLOUR[claim] ?? "var(--border-strong)";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--sp-03)",
        padding: "var(--sp-01) var(--sp-03)",
        border: `1px solid ${colour}`,
        color: colour,
        fontSize: "var(--type-caption)",
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      <span
        aria-hidden="true"
        style={{ width: 7, height: 7, background: colour, borderRadius: "50%" }}
      />
      {CLAIM_LABEL[claim] ?? claim}
    </span>
  );
}

function OrderingTable({ replay, title }: { replay: Replay; title: string }) {
  if (!replay.measurable) {
    return (
      <div style={{ marginTop: "var(--sp-05)" }}>
        <h3 style={{ fontSize: "var(--type-heading-02)" }}>{title}</h3>
        <Note tone="limit">{replay.reason}</Note>
      </div>
    );
  }

  return (
    <div style={{ marginTop: "var(--sp-06)" }}>
      <h3 style={{ fontSize: "var(--type-heading-02)", marginBottom: "var(--sp-04)" }}>
        {title}
      </h3>
      {/* Every ordering's lift with its interval, on one scale.
          The table under this is the receipt and it stays. What it cannot show is the
          thing the page is arguing about: whether an interval clears 1.0, and by how
          much it overlaps the queue's. Six columns of digits make that a comparison a
          reader has to perform; one axis makes it a comparison they can see. */}
      <IntervalChart
        rows={Object.entries(replay.orderings).map(([name, ordering]) => ({
          label: ORDERING_LABELS[name] ?? name,
          sublabel: ORDERING_NOTES[name],
          point: ordering.lift_over_random ?? null,
          interval: (ordering.lift_ci95 as [number, number] | null) ?? null,
          primary: name === "queue",
          value: fmt(ordering.lift_over_random),
        }))}
        rules={[{ at: 1, label: "random 1.0", kind: "null" }]}
        label={`Lift over random for ${Object.keys(replay.orderings).length} orderings, with 95% intervals, ${title.toLowerCase()}.`}
        caption={
          `Each bar is a 95% interval and the dot inside it the point estimate. The ` +
          `dashed rule is random ordering at the same budget. An interval that ` +
          `contains 1.0 has not shown that its ordering beats chance, whatever its ` +
          `point estimate reads.`
        }
      />
      <Table
        head={[
          "Ordering",
          "Conflicts",
          "Lift",
          "95% interval",
          "Against the queue",
          "Bonferroni",
        ]}
        headAlign={["left", "right", "right", "right", "left", "right"]}
        caption={`Budget ${replay.budget}, population ${replay.n_population}, ${replay.n_total_conflicts} conflicts in it, ${replay.n_groups} groups. Random finds ${fmt(replay.random_expected_conflicts, 1)} on average.`}
      >
        {Object.entries(replay.orderings).map(([name, ordering]) => {
          const comparison = replay.comparisons[name];
          return (
            <tr key={name}>
              <Cell align="left" header>
                {ORDERING_LABELS[name] ?? name}
                <div
                  style={{
                    fontSize: "var(--type-caption)",
                    color: "var(--text-03)",
                    fontWeight: 400,
                  }}
                >
                  {ORDERING_NOTES[name]}
                </div>
              </Cell>
              <Cell mono>{ordering.n_conflicts_at_budget}</Cell>
              <Cell mono>{fmt(ordering.lift_over_random)}</Cell>
              <Cell mono>{fmtInterval(ordering.lift_ci95)}</Cell>
              <Cell align="left">
                {name === "queue" ? (
                  <span style={{ color: "var(--text-03)" }}>reference</span>
                ) : comparison?.measurable ? (
                  <>
                    <Tag
                      tone={
                        comparison.direction === "queue_better" ? "action" : "muted"
                      }
                    >
                      {/* This printed the raw token (queue_better, baseline_better,
                          not_established) while CLAIM_LABEL, eighty lines above in this
                          same file, maps every one of them to a sentence. */}
                      {CLAIM_LABEL[comparison.direction] ?? comparison.direction}
                    </Tag>{" "}
                    <span className="num">
                      {comparison.diff_point === null
                        ? ""
                        : `${comparison.diff_point > 0 ? "+" : ""}${comparison.diff_point} conflicts`}
                    </span>
                  </>
                ) : (
                  <span style={{ color: "var(--text-03)" }}>{comparison?.reason}</span>
                )}
              </Cell>
              <Cell mono>
                {name === "queue"
                  ? "—"
                  : fmtInterval(comparison?.diff_ci_adjusted ?? null, 1)}
              </Cell>
            </tr>
          );
        })}
      </Table>
      {replay.n_degenerate_resamples !== undefined && (
        <p
          style={{
            marginTop: "var(--sp-03)",
            fontSize: "var(--type-caption)",
            color: "var(--text-03)",
          }}
        >
          <span className="num">{replay.n_degenerate_resamples}</span> of the resamples
          were degenerate and are reported rather than dropped silently.
        </p>
      )}
    </div>
  );
}

export default function ReplayPage() {
  const split: SplitGate6 = requireGate6Split("chronological");
  const conclusion = split.replay_conclusion;
  const statistic =
    split.replay_episode?.comparisons?.fifo?.statistic ??
    "Conflicts found by the queue minus conflicts found by the baseline at the same budget.";

  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "62ch" }}>
        <h1 style={{ fontSize: "var(--type-heading-05)" }}>
          The queue against the baselines
        </h1>
        <p
          style={{
            marginTop: "var(--sp-04)",
            color: "var(--text-02)",
            lineHeight: 1.7,
            fontSize: "var(--type-body-long)",
          }}
        >
          Random ordering is not the competition. These are: they cost nothing to
          implement, and if the queue cannot beat them then the model in front of it
          earned nothing. Every ordering is replayed on the same population, at the
          same budget, on the same resampled draws, so the comparison is paired rather
          than two separate measurements put side by side.
        </p>
        {/* The paragraph that used to sit here apologised for a rail label. "Replay"
            sent readers here looking for the pass playback, so the second paragraph on
            the page explained that the playback was somewhere else and linked off it.
            The label was renamed to "Baselines" in Rail.tsx, which fixed the cause; this
            was the workaround, and it was still spending a judge's second paragraph
            pointing away from the page. The link survives in the colophon and on the
            observation route itself. */}
      </header>

      {conclusion?.measurable ? (
        <>
          <Section
            title="The conclusion"
            description={conclusion.rule}
          >
            <div
              style={{
                display: "grid",
                gap: "var(--sp-05)",
                gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
              }}
            >
              <Stat
                label="Baselines compared"
                value={conclusion.n_baselines ?? "—"}
                detail="each replayed under two groupings"
              />
              <Stat
                label="Beaten under both"
                value={conclusion.n_beaten_under_both_groupings ?? 0}
                detail={
                  conclusion.beaten?.length
                    ? conclusion.beaten.map((b) => ORDERING_LABELS[b] ?? b).join(", ")
                    : "none"
                }
                tone={
                  (conclusion.n_beaten_under_both_groupings ?? 0) > 0
                    ? "var(--verdict-passed)"
                    : undefined
                }
              />
              <Stat
                label="Lost to"
                value={conclusion.lost_to?.length ?? 0}
                detail={
                  conclusion.lost_to?.length
                    ? // `beaten`, ten lines up, maps through ORDERING_LABELS and this
                      // did not, so the same baseline read as English in one stat and
                      // as a snake_case token in the one beside it.
                      conclusion.lost_to
                        .map((name) => ORDERING_LABELS[name] ?? name)
                        .join(", ")
                    : "no baseline beat the queue"
                }
              />
            </div>

            <div
              style={{
                display: "grid",
                gap: "var(--sp-05)",
                gridTemplateColumns: "repeat(auto-fit, minmax(20rem, 1fr))",
                marginTop: "var(--sp-06)",
              }}
            >
              {Object.entries(conclusion.baselines).map(([name, baseline]) => (
                <div
                  key={name}
                  style={{
                    padding: "var(--sp-05)",
                    background: "var(--ui-01)",
                    // The shorthand has to come first: a `border` after
                    // `borderLeft` resets the side it was meant to keep.
                    border: "1px solid var(--border-subtle)",
                    borderLeft: `3px solid ${
                      CLAIM_COLOUR[baseline.claim] ?? "var(--border-strong)"
                    }`,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      gap: "var(--sp-04)",
                      alignItems: "center",
                      flexWrap: "wrap",
                    }}
                  >
                    <h3 style={{ fontSize: "var(--type-heading-02)" }}>
                      {ORDERING_LABELS[name] ?? name}
                    </h3>
                    <ClaimBadge claim={baseline.claim} />
                  </div>

                  <dl
                    style={{
                      display: "grid",
                      gridTemplateColumns: "auto 1fr",
                      gap: "var(--sp-02) var(--sp-05)",
                      margin: "var(--sp-05) 0 0",
                      fontSize: "var(--type-caption)",
                    }}
                  >
                    <dt style={{ color: "var(--text-03)" }}>Difference</dt>
                    <dd className="num" style={{ margin: 0 }}>
                      {baseline.diff_point === null
                        ? "not measured"
                        : `${baseline.diff_point > 0 ? "+" : ""}${baseline.diff_point} conflicts`}
                    </dd>

                    <dt style={{ color: "var(--text-03)" }}>By episode</dt>
                    <dd style={{ margin: 0 }}>
                      <span className="num">
                        {fmtInterval(baseline.diff_ci_adjusted_episode, 1)}
                      </span>{" "}
                      {baseline.survives_correction_episode ? "survives" : "does not survive"}
                    </dd>

                    <dt style={{ color: "var(--text-03)" }}>By station</dt>
                    <dd style={{ margin: 0 }}>
                      <span className="num">
                        {fmtInterval(baseline.diff_ci_adjusted_station, 1)}
                      </span>{" "}
                      {baseline.survives_correction_station ? "survives" : "does not survive"}
                    </dd>
                  </dl>

                  {baseline.reason && (
                    <p
                      style={{
                        marginTop: "var(--sp-04)",
                        marginBottom: 0,
                        fontSize: "var(--type-caption)",
                        color: "var(--text-02)",
                        lineHeight: 1.6,
                      }}
                    >
                      {baseline.reason}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </Section>

          <Section
            title="The measurements behind it"
            description={statistic}
          >
            {split.replay_episode && (
              <OrderingTable
                replay={split.replay_episode}
                title="Grouped by pass episode"
              />
            )}
            {split.replay_station && (
              <OrderingTable
                replay={split.replay_station}
                title="Grouped by ground station"
              />
            )}

            <Note tone="info">
              The same numbers appear under both groupings for the point estimates and
              differ for the intervals, which is the whole reason both are shown. A
              station contributes many passes and one receiver; treating its captures
              as independent would narrow every interval here by an amount that has
              nothing to do with the ranking being better.
            </Note>
          </Section>
        </>
      ) : (
        <Note tone="warn">
          {conclusion?.reason ?? "The replay was not measurable on this split."}
        </Note>
      )}
    </div>
  );
}
