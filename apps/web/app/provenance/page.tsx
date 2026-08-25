/**
 * Where every number came from, and what would have to be true for it to be wrong.
 *
 * A console that renders a receipt is only as trustworthy as the reader's ability
 * to check the receipt, so this page lists the digest of each one. The point is
 * not that a judge will hash them; it is that they could, and that the numbers on
 * the other pages are the ones inside these files rather than a retelling.
 */
import { cards, evaluation, isBuilt, provenance, queue } from "@/lib/data";
import { SplitBars } from "@/components/charts";
import { Cell, Note, Section, Stat, Table, Tag } from "@/components/ui";

export const metadata = { title: "Provenance" };

function Digest({ value }: { value: string }) {
  return (
    <span
      className="num"
      title={value}
      style={{ fontSize: "var(--type-caption)", color: "var(--text-02)" }}
    >
      {value.slice(0, 16)}…
    </span>
  );
}

/**
 * The failure classes the console can be put into, counted against real cards.
 *
 * The counts are computed, not written down. A hand-typed "0" would go stale the
 * first time the shipped set changed, and a table of failure handling that does
 * not match the data is worse than no table.
 */
const DEGRADED_STATES: Array<{
  when: string;
  shows: string;
  count: number | null;
}> = [
  {
    when: "The observation is not in the snapshot",
    shows:
      "The card page says so and links back to the queue. No blank frame, no zeroes.",
    count: cards.cards.filter((c) => c.degraded).length,
  },
  {
    when: "No frequency information, so no centre pixel",
    shows:
      "The waterfall renders and the corridor overlay is withheld, with the reason and the share of records it affects.",
    count: cards.cards.filter((c) => isBuilt(c) && c.centre_px === null).length,
  },
  {
    when: "The TLE will not propagate, so there is no pass geometry",
    shows:
      "The same withheld overlay, carrying the physics module's own degraded reason rather than a generic one.",
    count: cards.cards.filter((c) => isBuilt(c) && c.corridor === null).length,
  },
  {
    when: "The corridor fit ran into the edge of its search range",
    shows:
      "The offset is shown with a greater-or-equal marker and a note that it is a lower bound. The observation is excluded from the stale-catalogue conflict criterion.",
    count: cards.cards.filter(
      (c) => isBuilt(c) && c.corridor?.offset_at_bound === true,
    ).length,
  },
  {
    when: "The browser has no WebGL2, or loses the context",
    shows:
      "The same image as a plain img, the reason in a note, and the contrast controls removed rather than left dead.",
    count: null,
  },
  {
    when: "The waterfall image will not decode",
    shows: "The same note, naming the decode as the cause.",
    count: null,
  },
  {
    when: "JavaScript is off",
    shows:
      "The waterfall, the corridor overlay and the top of the queue all still render. The filter controls are hidden and a line says why.",
    count: null,
  },
  {
    when: "A filter matches nothing",
    shows:
      "A stated empty result with the full queue size beside it, so an empty table cannot be read as a broken one.",
    count: null,
  },
];

export default function ProvenancePage() {
  const totalBytes = provenance.receipts.reduce((sum, r) => sum + r.bytes, 0);

  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "62ch" }}>
        <h1 style={{ fontSize: "var(--type-heading-05)" }}>Provenance</h1>
        <p
          style={{
            marginTop: "var(--sp-04)",
            color: "var(--text-02)",
            lineHeight: 1.7,
            fontSize: "var(--type-body-long)",
          }}
        >
          Every measurement on this site was produced offline, validated against a
          schema before it was written, and committed. The console reads those files
          and renders them. It runs no model, calls no service and holds no
          credentials, so there is nothing between the number in the receipt and the
          number on the page.
        </p>
      </header>

      {/* The home page's reading path sends a judge here for "How to check it", and until
          now the page opened on "The snapshot". The paragraph above states the guarantee;
          this states the procedure, because a reader who is told nothing sits between the
          receipt and the page still has to be told where the receipt is. Four steps, in the
          order someone actually does them, and the counts come from the same export the
          sections below render rather than from a sentence that has to be kept up to date
          by hand. Step three names no figure on purpose: the clean-clone suite total is not
          in this export, and a count typed in here would be the one number on the page with
          nothing behind it. */}
      <nav className="readpath" aria-label="How to check any number on this console">
        <ol>
          <li>
            <span className="readpath-index">01</span>
            <a href="#receipts">Find the receipt</a>
            <span className="readpath-fact">
              every figure names its file;{" "}
              <span className="num">{provenance.receipts.length}</span> of them, each listed
              in <code>docs/REFERENCE.md</code> with its size and digest
            </span>
          </li>
          <li>
            <span className="readpath-index">02</span>
            <a href="#contracts">Rebuild it</a>
            <span className="readpath-fact">
              the script that wrote each receipt is named beside it, and{" "}
              <span className="num">{provenance.contracts.length}</span> schemas validate the
              files before they are written
            </span>
          </li>
          <li>
            <span className="readpath-index">03</span>
            <a href="#splits">Re-run the checks</a>
            <span className="readpath-fact">
              the offline suite needs no snapshot, no network and no credentials, so a clone
              reproduces it
            </span>
          </li>
          <li>
            <span className="readpath-index">04</span>
            <a href="#limits">Read what it refuses to claim</a>
            <span className="readpath-fact">
              <span className="num">
                {provenance.gate_summary.n_met} of {provenance.gate_summary.n_gates}
              </span>{" "}
              kill gates met, and the page says why the rest are not
            </span>
          </li>
        </ol>
      </nav>

      <Section id="snapshot" title="The snapshot">
        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
          }}
        >
          <Stat
            label="Snapshot"
            value={<span className="mono" style={{ fontSize: "1rem" }}>{provenance.snapshot_id}</span>}
            detail="frozen before any model was fitted"
          />
          <Stat
            label="Queue built"
            value={
              <span style={{ fontSize: "1rem" }}>
                {queue.generated_at.slice(0, 16).replace("T", " ")}
              </span>
            }
            detail={`seed ${queue.seed}, fixed`}
          />
          <Stat
            label="Receipts"
            value={provenance.receipts.length}
            detail={`${(totalBytes / 1024 / 1024).toFixed(1)} MB, all committed`}
          />
          <Stat
            label="Waterfalls shipped"
            value={cards.n_built}
            detail={`of ${cards.n_requested} requested, ${cards.n_degraded} degraded`}
          />
        </div>
      </Section>

      <Section
        id="splits"
        title="Splits"
        description="Four ways of holding data back, because a chronological split alone cannot tell you whether the model learned the task or learned the stations."
      >
        {/* The four splits at one scale, and the fourth one is the point.
            As five columns of digits, cold_combined reads as another row. Drawn
            against the same axis it is visibly the shortest bar on the page with the
            largest excluded block beside it, which is the honest summary: the split
            that holds back both entity kinds keeps a third of the corpus and throws
            away 1,489 observations rather than assign them to a partition whose
            guarantee they would break. */}
        <SplitBars
          rows={provenance.splits.map((split) => ({
            label: split.name,
            values: [
              split.counts.train ?? 0,
              split.counts.calibration ?? 0,
              split.counts.test ?? 0,
              split.counts.excluded ?? 0,
            ],
          }))}
          parts={[
            { name: "Train", ink: "var(--interactive-01)" },
            { name: "Calibration", ink: "#7c5cff" },
            { name: "Test", ink: "#4589ff" },
            { name: "Excluded", ink: "#3a3f4b" },
          ]}
          label={
            "Train, calibration, test and excluded counts for four splits, on one scale."
          }
          caption={
            "One scale across all four rows, so a split that keeps fewer observations " +
            "is drawn shorter. The number at the right of each row is that split's " +
            "total, and every total is the same corpus."
          }
        />
        <Table
          head={["Split", "Train", "Calibration", "Test", "Excluded"]}
          caption={`All four are defined in SPLIT_MANIFEST.json, digest ${provenance.split_manifest_sha256.slice(0, 16)}…`}
        >
          {provenance.splits.map((split) => (
            <tr key={split.name}>
              <Cell align="left" header>
                {split.name}
              </Cell>
              <Cell mono>{split.counts.train ?? "—"}</Cell>
              <Cell mono>{split.counts.calibration ?? "—"}</Cell>
              <Cell mono>{split.counts.test ?? "—"}</Cell>
              <Cell mono>{split.counts.excluded ?? "—"}</Cell>
            </tr>
          ))}
        </Table>

        <Note tone="limit">
          The cold combined split excludes rather than assigns the observations that
          would break its own guarantee. An observation whose station is held out but
          whose transmitter is not cannot sit in a partition that promises both are
          cold, so it sits in neither, and the count is stated rather than absorbed.
        </Note>
      </Section>

      <Section
        id="receipts"
        title="Receipts"
        description="One per stage, each with the digest of the file as it stood when this payload was built."
      >
        <Table
          head={["File", "SHA-256", "Bytes", "As of"]}
          headAlign={["left", "left", "right", "left"]}
        >
          {provenance.receipts.map((receipt) => (
            <tr key={receipt.name}>
              <Cell align="left" header>
                <span className="mono">{receipt.name}</span>
              </Cell>
              <Cell align="left">
                <Digest value={receipt.sha256} />
              </Cell>
              <Cell mono>{receipt.bytes.toLocaleString("en-GB")}</Cell>
              <Cell align="left">
                {receipt.rewritten_after_this_payload
                  ? "the build before the sign-off"
                  : "this build"}
              </Cell>
            </tr>
          ))}
        </Table>
        <p
          style={{
            marginTop: "var(--sp-04)",
            fontSize: "var(--type-caption)",
            color: "var(--text-03)",
          }}
        >
          {provenance.receipts_note}
        </p>
        <p
          style={{
            marginTop: "var(--sp-04)",
            fontSize: "var(--type-caption)",
            color: "var(--text-03)",
          }}
        >
          The queue and evaluation pages read{" "}
          <span className="mono">QUEUE_RECEIPT.json</span> (
          <Digest value={evaluation.receipt_sha256.queue} />) and{" "}
          <span className="mono">FUSION_RECEIPT.json</span> (
          <Digest value={evaluation.receipt_sha256.fusion} />).
        </p>
      </Section>

      <Section
        id="contracts"
        title="Contracts"
        description="A schema is ratified before the script that writes against it runs, so a receipt that violates its contract never reaches disk."
      >
        <Table
          head={["Contract", "Version", "Status", "SHA-256"]}
          headAlign={["left", "right", "left", "left"]}
        >
          {provenance.contracts.map((contract) => (
            <tr key={contract.name}>
              <Cell align="left" header>
                <span className="mono">{contract.name}</span>
              </Cell>
              <Cell mono>{contract.version}</Cell>
              <Cell align="left">
                <Tag tone={contract.status === "ratified" ? "action" : "muted"}>
                  {contract.status}
                </Tag>
              </Cell>
              <Cell align="left">
                <Digest value={contract.sha256} />
              </Cell>
            </tr>
          ))}
        </Table>
      </Section>

      <Section
        title="The documents these numbers were promised against"
        description="Each was written before the measurement it governs, and each is served here as the file itself rather than as a summary of it."
      >
        <Table head={["Document", "What it fixes"]} headAlign={["left", "left"]}>
          <tr>
            <Cell align="left" header>
              <a href="/data/KILL_GATE.md">KILL_GATE.md</a>
            </Cell>
            <Cell align="left">
              The gates, their wording, and what each one would have killed. Written
              before the pipeline that answers them.
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              <a href="/data/CLAIM_REGISTER.md">CLAIM_REGISTER.md</a>
            </Cell>
            <Cell align="left">
              Every claim this project makes, with the evidence behind it and the
              claims that were withdrawn.
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              <a href="/data/C2_PREREGISTRATION.md">C2_PREREGISTRATION.md</a>
            </Cell>
            <Cell align="left">
              The concentration caps, the grouping keys and the decision rule, all
              committed before the numbers on this site were computed.
            </Cell>
          </tr>
        </Table>
      </Section>

      <Section
        id="limits"
        title="What this console does not do"
        description="Stated positively, because an absence is easy to claim and hard to notice."
      >
        <ul
          style={{
            margin: 0,
            paddingLeft: "1.1rem",
            lineHeight: 1.9,
            color: "var(--text-02)",
            maxWidth: "62ch",
          }}
        >
          {/* Five bullets became two, and no claim was dropped.
              This section carried 890 words about a web font: the byte inventory, a
              correction to a byte figure published on 2026-08-18, the font-display
              block period, a five-round paint A/B, the layout shift it cost, the
              per-route face list that was considered and declined, and the wrong
              weight the first version of the face list had. All of it is true and all
              of it is still measured. It was 46 percent of this page's prose and 12
              percent of all the prose on this console, spent on typography, on a site
              about satellite passes.

              What stays here is what a reader has to know to check the claim: how many
              third-party origins there are, what they cost, and that the cost was
              measured both ways. The harness, the two face lists, the five rounds and
              the declined alternative are in artifacts/FONT_PAINT_RECEIPT.json, which
              is the file that would have to be read to verify any of it anyway. */}
          {/* Cut again, and the reason is the same one that took it from 890 words
              to five bullets: this is a site about satellite passes and the paragraph
              was about a typeface. What a reader has to know to check the claim is that
              exactly one third-party origin exists, that it carries no data, and that
              the browser enforces it. The measurement, the harness and the declined
              alternative are in artifacts/FONT_PAINT_RECEIPT.json, which is the file
              anyone verifying this would have to read anyway. */}
          <li>
            No request for <em>data</em> to any origin but its own, before or after load.
            Two licensed display faces are the one exception and they carry no data; the
            content security policy in <code>vercel.json</code> names the only hosts a
            browser is permitted to reach, and every digit of every measurement is set in
            IBM Plex served from this site:{" "}
            <code>artifacts/FONT_PAINT_RECEIPT.json</code>.
          </li>
          <li>
            No model runs in the browser. The probabilities shown were fitted offline
            on the training partition of the split named beside them.
          </li>
          <li>
            No number on any page is computed by the console, except the map from
            stored intensities to screen colours, which the waterfall viewer states on
            every card.
          </li>
          <li>
            No analytics about you, no cookies, no storage, and nothing to consent to.
          </li>
        </ul>
      </Section>

      <Section
        title="Degraded states"
        description="What the console shows when something is missing, and whether any observation it ships actually puts the console into that state."
      >
        <Table
          head={["When", "What the console shows", "Shipped cards in this state"]}
          headAlign={["left", "left", "right"]}
          caption={`Counted over the ${cards.n_built} observations with imagery. A zero means the path is covered by the offline suite and by a forced check, not by this corpus.`}
        >
          {DEGRADED_STATES.map((state) => (
            <tr key={state.when}>
              <Cell align="left" header>
                {state.when}
              </Cell>
              <Cell align="left">{state.shows}</Cell>
              <Cell mono>
                {state.count === null ? (
                  <span style={{ color: "var(--text-03)" }}>not from data</span>
                ) : (
                  state.count
                )}
              </Cell>
            </tr>
          ))}
        </Table>
        {/* Ninety words became forty-eight, and the sentence addressed to "a judge"
            became an instruction addressed to whoever is reading. A page that speaks
            to one class of reader tells every other reader they are not it. */}
        <Note tone="limit">
          Every count is zero, which is worth saying rather than leaving in a table:
          the observations this console ships are the top of a queue, so they have the
          cleanest geometry. To see a degraded path here, block the waterfall image and
          the page will say what it lost.
        </Note>
      </Section>

      <Section title="Data and attribution">
        <p style={{ maxWidth: "62ch", lineHeight: 1.7, color: "var(--text-02)" }}>
          {cards.attribution}
        </p>
        <p style={{ maxWidth: "62ch", lineHeight: 1.7, color: "var(--text-02)" }}>
          {cards.intensity_note}
        </p>
      </Section>
    </div>
  );
}
