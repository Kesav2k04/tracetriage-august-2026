/**
 * The queue: what this project produces, and the honest headline about it.
 *
 * The page leads with the verdict rather than the queue, because the verdict is
 * NOT_ESTABLISHED and a console that showed a ranked list first would be inviting
 * a reader to assume the ranking was proven to work.
 */
import Link from "next/link";

import {
  cards,
  evaluation,
  fmt,
  fmtInterval,
  queue,
  requireGate6Split,
  requireQueueSplit,
  showcaseIds,
} from "@/lib/data";
import QueueTable from "@/components/QueueTable";
import { Cell, IntervalBar, Note, Section, Stat, Table, VerdictBadge } from "@/components/ui";

export const metadata = {
  // The template only applies to child segments, so the home page states the
  // whole title itself rather than shipping a page called "Review queue".
  title: { absolute: "TraceTriage: a review queue and what it is worth" },
};

const chronological = requireQueueSplit("chronological");
const gate6 = evaluation.gate6;
const primary = requireGate6Split("chronological");

export default function QueuePage() {
  const caps = chronological.concentration?.caps ?? {};

  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "62rem" }}>
        <p
          style={{
            fontSize: "var(--type-label)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--text-03)",
            margin: 0,
          }}
        >
          SatNOGS waterfall triage
        </p>
        <h1
          style={{
            fontSize: "var(--type-heading-06)",
            lineHeight: 1.15,
            margin: "var(--sp-03) 0 var(--sp-05)",
          }}
        >
          A review queue, and the measurement that says how much it is worth.
        </h1>
        <p style={{ color: "var(--text-02)", lineHeight: 1.7, fontSize: "var(--type-body-long)" }}>
          Volunteer ground stations record far more passes than anyone reviews. This
          ranks them by how likely a human is to find something wrong, and then
          measures whether that ranking beats picking at random. The measurement is
          the point. A queue nobody tested is a preference.
        </p>
      </header>

      <div
        style={{
          marginTop: "var(--sp-07)",
          padding: "var(--sp-06)",
          border: "1px solid var(--border-strong)",
          background: "var(--ui-01)",
          display: "grid",
          gap: "var(--sp-06)",
          gridTemplateColumns: "minmax(0, 1fr) minmax(18rem, 22rem)",
          alignItems: "start",
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--sp-05)",
              flexWrap: "wrap",
            }}
          >
            <h2 style={{ fontSize: "var(--type-heading-03)" }}>
              Kill gate {gate6.gate}
            </h2>
            <VerdictBadge verdict={gate6.verdict} size="large" />
          </div>
          <p
            style={{
              margin: "var(--sp-04) 0 0",
              color: "var(--text-02)",
              fontStyle: "italic",
              lineHeight: 1.6,
            }}
          >
            “{gate6.wording}”
          </p>
          <p style={{ margin: "var(--sp-05) 0 0", lineHeight: 1.7 }}>{gate6.statement}</p>
        </div>

        <div>
          <IntervalBar
            low={primary.lift_ci95?.[0] ?? 0}
            high={primary.lift_ci95?.[1] ?? 0}
            point={primary.lift_point ?? 0}
            threshold={1.5}
            domain={[0.8, 2.2]}
            label="Queue lift over random at the review budget"
          />
          <p
            style={{
              marginTop: "var(--sp-04)",
              fontSize: "var(--type-caption)",
              color: "var(--text-02)",
              lineHeight: 1.6,
            }}
          >
            Lift <span className="num">{fmt(primary.lift_point)}</span>, 95% interval{" "}
            <span className="num">{fmtInterval(primary.lift_ci95)}</span> over{" "}
            <span className="num">{primary.n_boot_effective}</span> resamples grouped
            by pass episode and by ground station. The interval contains 1.5, so the
            gate is not met.
            {(primary.lift_ci95?.[0] ?? 0) > 1
              ? " It also sits entirely above 1.0, so the ranking is not nothing either."
              : " It also reaches below 1.0, so this measurement does not separate the ranking from random."}
          </p>
        </div>
      </div>

      <Section
        title="What the queue found"
        description="Counts, not rates. Every number here carries the denominator it was measured over."
      >
        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
          }}
        >
          <Stat
            label="Conflicts found"
            value={primary.n_queue_conflicts ?? "—"}
            detail={`in the top ${primary.n_queue_examined} the reviewer would reach`}
          />
          <Stat
            label="Random would find"
            value={fmt(primary.n_random_conflicts, 1)}
            detail="expected count at the same budget, from the population rate"
          />
          <Stat
            label="Queue length"
            value={queue.entries.length}
            detail={`from ${chronological.n_test_total ?? "—"} test observations after episode deduplication`}
          />
          <Stat
            label="Pass episodes"
            value={primary.n_groups ?? "—"}
            detail={`over ${primary.n_station_groups ?? "—"} ground stations, the two groupings the interval is built on`}
          />
        </div>

        <Note tone="warn">
          The point estimate <span className="num">{fmt(primary.lift_point)}</span> is
          above the threshold and the interval is not. Under an earlier bootstrap the
          same measurement produced an interval that did not contain its own point
          estimate; that was a defect in the resampling, not a property of ratio
          statistics, and it is documented in the claim register. The number above
          comes from the corrected bootstrap, where the point estimate does sit inside
          its interval ({String(primary.point_in_ci)}).
        </Note>
      </Section>

      <Section
        title="What counts as a conflict"
        description="Fixed before anything was measured. A criterion invented after seeing the ranking would measure the ranking against itself."
      >
        <Table
          head={["Reason", "What it means", "Threshold"]}
          caption={`Fixed before measuring: ${String(queue.conflict_definition.fixed_before_measuring)}.`}
        >
          {queue.conflict_definition.criteria.map((criterion) => (
            <tr key={criterion.reason_code}>
              <Cell align="left" header>
                {criterion.reason_code}
              </Cell>
              <Cell align="left">{criterion.description}</Cell>
              <Cell mono>
                {typeof criterion.threshold === "object"
                  ? Object.entries(criterion.threshold as Record<string, unknown>)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(", ")
                  : String(criterion.threshold)}
              </Cell>
            </tr>
          ))}
        </Table>

        {Array.isArray(queue.conflict_definition.caveats) && (
          <ul
            style={{
              marginTop: "var(--sp-05)",
              color: "var(--text-02)",
              lineHeight: 1.7,
              maxWidth: "62rem",
            }}
          >
            {queue.conflict_definition.caveats.map((caveat) => (
              <li key={caveat} style={{ marginBottom: "var(--sp-03)" }}>
                {caveat}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Concentration caps"
        description="A queue that spends its whole budget on one station has found one station's problem, not the corpus's. Caps are applied before the budget is filled, and what they displaced is recorded rather than dropped."
      >
        <Table
          head={["Cap", "Share of budget", "Entries at budget", "Displaced", "Binding"]}
          caption={
            chronological.concentration
              ? `${chronological.concentration.n_admitted_to_budget} admitted, ${chronological.concentration.n_displaced_total} displaced, budget ${chronological.concentration.budget}.`
              : "No concentration record for this split."
          }
        >
          {Object.entries(caps).map(([name, cap]) => (
            <tr key={name}>
              <Cell align="left" header>
                {name}
              </Cell>
              <Cell mono>{(cap.share_of_budget * 100).toFixed(0)}%</Cell>
              <Cell mono>{cap.entries_at_budget}</Cell>
              <Cell mono>{cap.n_displaced}</Cell>
              <Cell align="left">
                {cap.bound ? (
                  <span style={{ color: "var(--support-03)" }}>bound</span>
                ) : (
                  <span style={{ color: "var(--text-03)" }}>inert</span>
                )}
              </Cell>
            </tr>
          ))}
        </Table>

        {chronological.concentration?.note && (
          <Note tone="limit">{chronological.concentration.note}</Note>
        )}

        {primary.uncapped_reference && (
          <Note tone="info">
            Without the caps the same queue would score{" "}
            <span className="num">{fmt(primary.uncapped_reference.lift_point)}</span>{" "}
            with interval{" "}
            <span className="num">
              {fmtInterval(primary.uncapped_reference.lift_ci95_episode)}
            </span>
            , which would be {primary.uncapped_reference.verdict_if_it_were_eligible}.
            It is reported here and is not the result: the caps were fixed before
            measuring, so the capped queue is the one that counts.{" "}
            {primary.uncapped_reference.note}
          </Note>
        )}
      </Section>

      <Section
        title="The queue"
        description={
          <>
            {queue.review_budget.rationale} {cards.n_built} of these carry a waterfall
            you can open; the rest are listed with their measurements only, because
            shipping 2,500 images to prove a ranking is not evidence, it is weight.{" "}
            <Link href="/provenance/">Where the data comes from</Link>.
          </>
        }
      >
        <QueueTable
          // Projected to the columns the table draws. The receipt row also
          // carries flat_row_frac, the ensemble spread and the episode key, and
          // those belong on an observation page rather than in 407 rows of a
          // payload the browser has to parse before it can filter anything.
          entries={queue.entries.map((entry) => ({
            obs_id: entry.obs_id,
            rank: entry.rank,
            score: entry.score,
            reasons: entry.reasons,
            is_conflict: entry.is_conflict,
            within_budget: entry.within_budget,
            displaced_by_cap: entry.displaced_by_cap,
            waterfall_status: entry.waterfall_status,
            model_prob: entry.model_prob,
            fitted_offset_ppm: entry.fitted_offset_ppm,
            offset_at_bound: entry.offset_at_bound,
          }))}
          imaged={showcaseIds}
          budget={queue.review_budget.n_observations}
        />
      </Section>

      <Section title="Deduplication" description="One row per pass, not one row per capture.">
        <p style={{ color: "var(--text-02)", lineHeight: 1.7, maxWidth: "62rem" }}>
          {String(queue.deduplication.rule)}
        </p>
        <Table head={["Field", "Value"]} caption="From the queue receipt.">
          {Object.entries(queue.deduplication)
            .filter(([, value]) => typeof value !== "string")
            .map(([key, value]) => (
              <tr key={key}>
                <Cell align="left" header>
                  {key}
                </Cell>
                <Cell mono>
                  {Array.isArray(value) ? value.join(", ") : String(value)}
                </Cell>
              </tr>
            ))}
        </Table>
      </Section>
    </div>
  );
}

