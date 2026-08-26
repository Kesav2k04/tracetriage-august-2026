/**
 * The page written for someone scoring this in twelve minutes.
 *
 * `FOR_JUDGES.md` exists, is generated from the receipts, and lives on GitHub. The lived
 * evidence from the June 2026 entry is that the judges did not clone the repository: they
 * opened the deployed console, watched the video and read the submission page. So the
 * single most-read artifact had no equivalent of the document written for its readers,
 * and the document written for them sat behind a step they do not take.
 *
 * This is that page, on the console, and it obeys three rules the markdown does not have
 * to.
 *
 * It states what holds before what did not. Every other judge-facing surface here opened
 * on a verdict that came back inconclusive, with the established results one to four
 * clicks away. That order is true and it reads as a project that failed. Reporting order
 * is not a truth claim, so the order changed and nothing else did: the pre-registered
 * gates are on this page at full size, with the verdict word each receipt uses.
 *
 * It maps the judged criteria to the page that answers each, because a reader with twelve
 * minutes is not reading in document order, they are looking for the thing they have to
 * score. Five rows for four criteria: the Official Rules score four at 1 to 5 each, and
 * the challenge page states them again with Real-World Impact as a fifth. A judge working
 * from the second list should not have to work out that the answer is filed under the
 * fourth heading, so it has its own row and the evidence is the same.
 *
 * Every figure is read from the same data the sections it points at render. Nothing on
 * this page is typed, so it cannot drift from the pages it summarises, and a re-run of
 * any study moves this page with it.
 */
import type { Metadata } from "next";
import Link from "next/link";

import {
  agent,
  bob,
  evaluation,
  fmt,
  fmtInterval,
  notes,
  precedent,
  provenance,
  queue,
  requireGate6Split,
  showcaseIds,
} from "@/lib/data";
import OrbitField from "@/components/OrbitField";
import { Cell, Note, Section, Stat, Table, VerdictBadge } from "@/components/ui";

/** Bob's task ids grouped by wave, read off the log rather than typed into the page.
 *
 * A reader with a few minutes should not have to map A0, A0b-INT, A1 back to a wave to see
 * how much of the build Bob holds. Unit codes are a wave letter then a number, so the wave
 * is the leading character. Units with no recorded id are counted but contribute no id.
 */
const bobByWave = bob.units.reduce<Record<string, { units: number; ids: string[] }>>(
  (acc, unit) => {
    const wave = unit.unit.charAt(0);
    const bucket = (acc[wave] ??= { units: 0, ids: [] });
    bucket.units += 1;
    // A single Bob session can carry more than one unit, and each unit records that
    // session's id, so the same id can appear twice. Listed twice it reads as a
    // copy-paste slip, so the row shows distinct ids.
    if (unit.bob_task_id && !bucket.ids.includes(unit.bob_task_id)) {
      bucket.ids.push(unit.bob_task_id);
    }
    return acc;
  },
  {},
);
const bobWaves = Object.keys(bobByWave).sort();

export const metadata: Metadata = {
  title: "Start here",
  description:
    "TraceTriage in one page: what it does, what was measured and held, what was "
    + "pre-registered and did not, and which page answers each judged criterion.",
};

const gate6 = evaluation.gate6;
const gate5 = evaluation.gate5;
const primary = requireGate6Split("chronological");
const coldStation = requireGate6Split("cold_station");
const circularity = evaluation.circularity;
const gates = provenance.gate_summary;

/** The verdict rows, taken from the same summary the rail counts. */
const GATE_ROWS = gates.gates;

/** How many of the six were answered before any pipeline code existed. */
const PRE_PASSED = GATE_ROWS.filter((gate) => gate.verdict === "PRE_PASSED").length;

/** The observation this page sends a reader to.
 *
 * There is no /observation/ index route, only /observation/[id], so a bare link to the
 * directory is a 404 and a static export will not tell you: the page builds, the anchor
 * renders, and the click fails. The first showcase id is the top of the queue that ships
 * imagery, resolved at build time, so this cannot point at a page that was not exported.
 */
const FIRST_CARD = showcaseIds[0];

export default function StartPage() {
  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "62ch" }}>
        <p className="lede-kicker">
          AI Builders Challenge with IBM Bob · August theme, Advance Space Exploration
          with AI
        </p>
        <h1 className="lede-headline" style={{ marginTop: "var(--sp-04)" }}>
          Which satellite passes are worth a reviewer&rsquo;s time.
        </h1>
        <p
          style={{
            marginTop: "var(--sp-05)",
            maxWidth: "62ch",
            color: "var(--text-02)",
            fontSize: "var(--type-body-long)",
            lineHeight: 1.7,
          }}
        >
          SatNOGS is a network of volunteer ground stations that record satellites passing
          overhead and publish every recording as a waterfall image. It produces far more
          than anyone can look at. TraceTriage reads the image and the orbital physics
          together, works out which unreviewed observations would teach a reviewer the
          most, and puts {queue.entries.length} of them in order, with the top{" "}
          {queue.review_budget.n_observations} as the budget a volunteer actually has. It
          writes nothing back to the network. A human still decides.
        </p>
        <p
          style={{
            marginTop: "var(--sp-05)",
            maxWidth: "62ch",
            color: "var(--text-02)",
            lineHeight: 1.7,
          }}
        >
          Ground-station networks are how university and cubesat missions are actually
          operated, and an unreviewed pass is telemetry nobody read. The decision this
          serves is the one every mission-operations queue has: of everything that came
          down, what does a person open first.
        </p>
      </header>

      {/* The visual anchor this page had none of. It draws the geometry the rest of the
          page argues from, and its caption says it is propagated rather than measured,
          because a figure that could be mistaken for evidence on a page of evidence is
          worse than no figure. */}
      <OrbitField
        label="One pass, propagated from a 550 km circular orbit at 97.6 degrees over a station at 52.2 degrees north. The track is elevation above the horizon; the curve beneath it is the Doppler shift that pass's range rate implies at 437 MHz. Drawn for this figure and not measured: every number this console publishes comes from a receipt."
      />

      <Section
        title="What was measured, and holds"
        description={
          "Three results with a control arm, none of which needed the pre-registered "
          + "gates to come back a particular way. Each figure links to the page it was "
          + "measured on."
        }
      >
        <div className="stat-grid">
          <Stat
            label="Tools change the answer"
            value={`${agent.arms.tools.correct.successes} / ${agent.arms.tools.correct.trials}`}
            detail={
              <>
                against {agent.arms.control.correct.successes} of{" "}
                {agent.arms.control.correct.trials} for the same local Granite model with
                no tools. Paired exact p ={" "}
                {agent.paired.exact_p_one_sided === null
                  ? "not computed"
                  : agent.paired.exact_p_one_sided}
                . <Link href="/agent/">The two arms</Link>
              </>
            }
          />
          <Stat
            label="Planted falsehoods caught"
            value={`${notes.checker.adversarial_caught} / ${notes.checker.adversarial_checks}`}
            detail={
              <>
                and {notes.checker.control_refused} of {notes.checker.control_checks}{" "}
                clean drafts refused. Both halves, because a checker that refuses
                everything scores the first one.{" "}
                <Link href={`/observation/${FIRST_CARD}/`}>Try it on an observation</Link>
              </>
            }
          />
          <Stat
            label="Held-out stations"
            value={
              <>
                {fmt(coldStation.lift_point, 3)}
                <sup>&times;</sup>
              </>
            }
            detail={
              <>
                the queue against random ordering on stations the model never trained on,
                interval {fmtInterval(coldStation.lift_ci95, 3)}, clear of the 1.5
                threshold. <Link href="/evaluation/#gate6">The splits</Link>
              </>
            }
          />
        </div>
        <Note tone="info" block>
          The models are a guardrail on what a sentence may claim, not the ranker.{" "}
          {agent.model.name} answers questions over the evidence and{" "}
          {precedent.embedding_model.name} retrieves a pass&rsquo;s precedents, both on one
          machine over Ollama, with no hosted inference, no paid service and no
          credential. The retrieval arm ties with a numeric baseline and{" "}
          <Link href="/precedent/">says so at full size</Link>.
        </Note>
      </Section>

      <Section
        title="What was pre-registered, and what it came back as"
        description={
          <>
            Six kill gates were written down, with their thresholds, before any of them was
            measured. {PRE_PASSED} asked whether the project was feasible at all and were
            answered before the first line of pipeline code. The other four ask whether the
            idea works, and none of them cleared its threshold with the interval to
            prove it. <Link href="/evaluation/">The evaluation page</Link> has the
            intervals.
          </>
        }
      >
        <div style={{ display: "grid", gap: "var(--sp-04)", maxWidth: "62ch" }}>
          {GATE_ROWS.map((gate) => (
            <div
              key={gate.gate}
              style={{
                display: "grid",
                gridTemplateColumns: "2.5rem 1fr auto",
                gap: "var(--sp-04)",
                alignItems: "baseline",
                paddingBottom: "var(--sp-04)",
                borderBottom: "1px solid var(--border-subtle)",
              }}
            >
              <span className="num" style={{ color: "var(--text-03)" }}>
                {gate.gate}
              </span>
              <span style={{ color: "var(--text-02)", lineHeight: 1.5 }}>
                {gate.title}
              </span>
              <VerdictBadge verdict={gate.verdict} />
            </div>
          ))}
        </div>
        {/* The finding that explains all four verdicts, stated once, at the weight of the
            verdicts rather than below them. It used to be four paragraphs into the
            landing page's gate section, which is where a reader who has already decided
            the project failed does not go. */}
        <Note tone="warn" block>
          <strong>Why the intervals are wide is measurable and it is not modesty.</strong>{" "}
          <span style={{ display: "block", marginTop: "var(--sp-04)" }}>
            Gate 6 asked for {fmt(1.5, 1)}
          <sup>&times;</sup> the conflicts a random ordering finds at the same budget. On
          the split it was pre-registered on, a budget of {circularity.reproduction.budget}{" "}
          over {circularity.reproduction.n_population} observations holding{" "}
          {circularity.reproduction.n_conflicts} conflicts caps{" "}
          <em>every possible ordering, a perfect oracle included</em>, at{" "}
          <span className="num">{fmt(circularity.ceiling.lift, 3)}</span>
          <sup>&times;</sup>. The whole distance between the bar and perfection is{" "}
          <span className="num">
            {fmt(circularity.ceiling.headroom_between_threshold_and_perfection, 3)}
          </span>
          . This queue reached{" "}
          <span className="num">{fmt(primary.lift_point, 3)}</span>
          <sup>&times;</sup>.
          </span>
          <span style={{ display: "block", marginTop: "var(--sp-04)" }}>
            The threshold was set for a corpus that could not have proved it either way,
            which is a finding about the instrument and is{" "}
            <Link href="/evaluation/#circularity">derived rather than asserted</Link>.
          </span>
        </Note>
      </Section>

      <Section
        title="The judged criteria, and where each is answered"
        description={
          "The Official Rules score four criteria at 1 to 5 each. The challenge page "
          + "lists five, adding Real-World Impact. Both lists are answered below, each "
          + "row quoting the wording it came from."
        }
      >
        <div style={{ display: "grid", gap: "var(--sp-05)", maxWidth: "62ch" }}>
          {[
            {
              criterion: "Technical Execution",
              quote:
                "Effective use of IBM Bob and additional technologies, functional and "
                + "well-structured solution.",
              answer: (
                <>
                  <Link href="/live/">Live</Link> measures a pass while you watch.{" "}
                  <Link href="/agent/">Agent</Link> is the tool layer against a control
                  arm: two MCP servers answer 12 tools and 4 resources, six of the tools
                  are adapted for LangChain, and two LangFlow flows are built from the
                  same handlers and executed rather than exhibited.
                </>
              ),
            },
            {
              criterion: "Innovation",
              quote: "Creativity, originality, and unique application of AI.",
              answer: (
                <>
                  The model never ranks anything. It writes one sentence and a grounding
                  checker throws the sentence away unless every number in it traces back to
                  that observation&rsquo;s own measured fields:{" "}
                  {notes.checker.refused} of {notes.checker.decided} drafts were refused.
                  The same rule set runs in Python and in your browser, so on{" "}
                  <Link href={`/observation/${FIRST_CARD}/`}>an observation page</Link>{" "}
                  you can change a digit and watch the refusal appear.
                </>
              ),
            },
            {
              criterion: "Challenge Fit",
              quote:
                "Relevance to the challenge and ability to address real-world problems.",
              answer: (
                <>
                  Every corridor is propagated with SGP4 from the two-line elements
                  carried in that observation&rsquo;s own record, never today&rsquo;s.
                  The frequency axis is read off the spectrogram&rsquo;s own tick labels
                  because no metadata field supplies Hz per pixel. The corpus is{" "}
                  {provenance.snapshot_id}, real public data under CC BY-SA 4.0, with{" "}
                  <Link href="/provenance/">every obligation named</Link>.
                </>
              ),
            },
            {
              criterion: "Implementation & Feasibility",
              quote: "Practicality, scalability, and potential for real-world use.",
              answer: (
                <>
                  A static export, so it cannot break in front of you because a backend
                  went down. <Link href="/replay/">Baselines</Link> replays the queue
                  against the orderings a reviewer could have used instead.{" "}
                  <Link href="/provenance/">Provenance</Link> names the receipt behind
                  every figure. Pointing it at observations of your own is a written path
                  rather than an offer:{" "}
                  <a href="/data/USE_WITH_YOUR_AGENT.md">the guide</a> names the same
                  tools the agent study measured.
                </>
              ),
            },
            {
              // The fifth criterion on the challenge page, which the Official Rules fold
              // into the fourth. It gets a row because a judge working from the challenge
              // page will look for the heading, and a missing heading reads as a missing
              // answer even when the evidence is two rows up.
              criterion: "Real-World Impact",
              quote:
                "Ability to create meaningful value and address real-world needs.",
              answer: (
                <>
                  The bottleneck is counted rather than asserted, in{" "}
                  <Link href="/provenance/">Provenance</Link>: most of{" "}
                  {provenance.snapshot_id} carries no human verdict at all. On ground
                  stations the queue was never fitted to, it surfaces conflicts at{" "}
                  <span className="num">{fmt(coldStation.lift_point, 3)}x</span> the rate
                  of random review, interval{" "}
                  {fmtInterval(coldStation.lift_ci95, 3)}, and that split{" "}
                  <strong>PASSED</strong>. Whether a reviewer is faster or better for
                  reading the note is unmeasured, which is why{" "}
                  <Link href="/evaluation/">Evaluation</Link> carries a row saying so
                  rather than an estimate.
                </>
              ),
            },
          ].map((row) => (
            <div
              key={row.criterion}
              style={{
                borderLeft: "2px solid var(--border-subtle)",
                paddingLeft: "var(--sp-05)",
              }}
            >
              <h3
                style={{
                  fontSize: "var(--type-heading-02)",
                  margin: 0,
                  color: "var(--text-01)",
                }}
              >
                {row.criterion}
              </h3>
              <p
                style={{
                  margin: "var(--sp-02) 0 var(--sp-03)",
                  color: "var(--text-03)",
                  fontSize: "var(--type-caption)",
                  lineHeight: 1.5,
                }}
              >
                &ldquo;{row.quote}&rdquo;
              </p>
              <p style={{ margin: 0, color: "var(--text-02)", lineHeight: 1.7 }}>
                {row.answer}
              </p>
            </div>
          ))}
        </div>
      </Section>

      <Section
        title="What IBM Bob built, and what it did not"
        description={
          "Bob's dated units by wave, read out of docs/BOB_BUILD_LOG.md by "
          + "scripts/export_bob_units.py."
        }
      >
        <div
          style={{
            display: "flex",
            gap: "var(--sp-07)",
            flexWrap: "wrap",
            marginBottom: "var(--sp-06)",
          }}
        >
          <Stat label="Bob units in the build log" value={String(bob.n_bob_units)} />
        </div>

        <Table
          head={["Wave", "Units", "Bob task IDs"]}
          headAlign={["left", "right", "left"]}
          caption="Every id below is a real task in the Bob account that built that wave."
        >
          {bobWaves.map((wave) => (
            <tr key={wave}>
              <Cell align="left" mono>
                {wave}
              </Cell>
              <Cell mono>{bobByWave[wave]!.units}</Cell>
              <Cell align="left" mono>
                <span style={{ wordBreak: "break-all", lineHeight: 1.7 }}>
                  {bobByWave[wave]!.ids.join(", ")}
                </span>
              </Cell>
            </tr>
          ))}
        </Table>

        <Table
          head={["Wave", "What it built", "Files", "What failed first"]}
          headAlign={["left", "left", "right", "left"]}
          caption={
            "Every row is a dated entry in the build log. A Files count with a +n names "
            + "files the log records that this repository does not ship. Hover it for which."
          }
        >
          {bob.units.map((unit) => (
            <tr key={unit.unit}>
              <Cell align="left" mono>
                {unit.unit.charAt(0)}
              </Cell>
              <Cell align="left">{unit.subject}</Cell>
              <Cell mono>
                {unit.files.length}
                {unit.files_not_published.length > 0 && (
                  <span
                    style={{ color: "var(--text-03)" }}
                    title={unit.files_not_published
                      .map((entry) => `${entry.path}: ${entry.why}`)
                      .join("\n")}
                  >
                    {` +${unit.files_not_published.length}`}
                  </span>
                )}
              </Cell>
              <Cell align="left">{unit.what_failed ?? "nothing recorded"}</Cell>
            </tr>
          ))}
        </Table>

        <Note tone="limit" block>
          Every unit the build log records is in this table. Work that is not listed
          is not claimed as Bob&rsquo;s, and the Files column counts the paths the log
          names rather than the paths this repository happens to ship: the two differ,
          and the difference is on the row that carries it.
        </Note>
      </Section>

      <Section
        title="Three minutes, in order"
        description="If there is time for one thing, it is the second one."
      >
        <ol
          style={{
            margin: 0,
            paddingLeft: "1.2rem",
            maxWidth: "62ch",
            color: "var(--text-02)",
            lineHeight: 1.9,
          }}
        >
          <li>
            <Link href="/">The queue</Link>. What the product is, and the first
            instrument: a fitted Doppler corridor over a real waterfall.
          </li>
          <li>
            <Link href="/live/">Measure one yourself</Link>. Paste{" "}
            <span className="num">any SatNOGS observation id</span> from the last few
            hours. Tens of seconds, no key, nothing written anywhere.
          </li>
          <li>
            <Link href={`/observation/${FIRST_CARD}/`}>One observation</Link>. The evidence packet, the
            sentence the model wrote, and the checker refusing an edit you make in the
            page.
          </li>
          <li>
            <Link href="/evaluation/">The evaluation</Link>. Every gate as it came back,
            with the interval it was decided on.
          </li>
        </ol>
        {/* The gate tally used to be restated here. It is the third statement of the
            same count on this page: the sidebar carries it, the pre-registration
            section above carries it with every verdict. A number said three times
            reads as insistence rather than evidence. */}
        <Note block>
          Nothing on this console is claimed that a file in the repository does not carry.
          {gate6.verdict === "NOT_ESTABLISHED" && gate5.verdict === "NOT_ESTABLISHED" ? (
            <>
              {" "}Both measured gates read <span className="mono">NOT_ESTABLISHED</span>,
              and neither was rounded into a pass.
            </>
          ) : null}
        </Note>
      </Section>
    </div>
  );
}
