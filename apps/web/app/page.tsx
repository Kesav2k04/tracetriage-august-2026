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
import CorridorHero from "@/components/CorridorHero";
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
      {/* Stat-led opening.
          The figure is the queue's measured lift, and the interval is set at the
          same weight as the figure rather than under it. A hero that showed 1.58
          alone would be making the claim the gate declined to make, and this page
          would be the first place a reader met that claim. */}
      <header className="lede">
        <p className="lede-kicker">
          SatNOGS waterfall triage · chronological split ·{" "}
          {primary.n_queue_examined} observations examined
        </p>
        <div className="lede-figure">
          <p style={{ margin: 0 }}>
            <span className="lede-number">
              {fmt(primary.lift_point, 2)}
              <sup>&times;</sup>
            </span>
            <span
              style={{
                display: "block",
                marginTop: "var(--sp-05)",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--type-body)",
                color: "var(--text-02)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              95% CI {fmtInterval(primary.lift_ci95, 3)}
            </span>
            <span
              style={{
                display: "block",
                marginTop: "var(--sp-02)",
                fontSize: "var(--type-caption)",
                color: "var(--text-03)",
              }}
            >
              against a 1.5&times; threshold, so the gate is not met
            </span>
          </p>
          <div>
            <h1 className="lede-headline">
              A review queue, and the measurement that says how much it is worth.
            </h1>
            <p className="lede-body" style={{ marginTop: "var(--sp-05)" }}>
              Volunteer ground stations record far more passes than anyone reviews.
              This ranks them by how likely a human is to find something wrong, then
              measures whether that ranking beats picking at random. The measurement
              is the point. A queue nobody tested is a preference.
            </p>
          </div>
        </div>
      </header>

      {/* The instrument, immediately after the verdict.
          A reader who leaves after one screen should have seen the measurement
          rather than a description of it, and the measurement is a fitted corridor
          standing among the corridors that could not fit. It sits below the lede
          rather than above it because the lede carries the honest headline, and a
          console that opened on the strongest single frame would be arranging the
          evidence to flatter itself. */}
      <CorridorHero />

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
        title="What the measurement actually is"
        description="Twenty-four seconds, rendered offline from one observation's own exported corridor. Served from this origin: there is no embed, no player script, and nothing about it is requested from anyone else."
      >
        <figure className="explainer">
          {/* preload="none" so the 1.6 MB costs nothing until a reader asks for it,
              and a poster frame drawn from the video itself rather than a title card,
              so the still already shows the measurement. No autoplay: a page that
              starts moving on load takes the decision away from the reader, and this
              one is 24 seconds of someone else talking. */}
          <video
            controls
            preload="none"
            playsInline
            poster="/media/corridor-explainer-poster.jpg"
            width={1920}
            height={1080}
          >
            <source src="/media/corridor-explainer.mp4" type="video/mp4" />
            <p>
              Your browser cannot play this video. It shows the predicted Doppler
              corridor for observation 14745984 being slid across the waterfall to its
              best match, a shift of 61 pixels, which at 92.6 Hz per pixel is 5,648 Hz,
              which is 13.0 ppm of the receive frequency.
            </p>
          </video>
          <figcaption>
            A detector that assumes the trace is vertical looks in one column. The
            satellite is moving, so the received frequency sweeps, and the corridor is
            curved with its shape fixed by the pass geometry. Sliding that curve to its
            best match gives one number: how far off the capture was. For observation
            14745984 that is 61 pixels, 5,648 Hz, 13.0 ppm. The frequency axis is
            cropped and exaggerated against the time axis so a 61 pixel shift on a 620
            pixel image is visible at all, and the video says so on screen.
          </figcaption>
        </figure>
      </Section>

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
                {/* The object branch is the one that runs for all three criteria.
                    It needed a cast while `threshold` was typed `string | number`,
                    because that made `typeof x === "object"` narrow to never and a
                    cast on never is allowed: the executing branch was the one the
                    compiler believed was dead, and deleting it on that advice would
                    have rendered every threshold as [object Object]. The type now
                    includes the object, so the guard narrows for real. */}
                {typeof criterion.threshold === "object"
                  ? Object.entries(criterion.threshold)
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

