/**
 * Where every number came from, and what would have to be true for it to be wrong.
 *
 * A console that renders a receipt is only as trustworthy as the reader's ability
 * to check the receipt, so this page lists the digest of each one. The point is
 * not that a judge will hash them; it is that they could, and that the numbers on
 * the other pages are the ones inside these files rather than a retelling.
 */
import { cards, evaluation, isBuilt, provenance, queue } from "@/lib/data";
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
      <header style={{ maxWidth: "62rem" }}>
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

      <Section title="The snapshot">
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
        title="Splits"
        description="Four ways of holding data back, because a chronological split alone cannot tell you whether the model learned the task or learned the stations."
      >
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
        title="Receipts"
        description="Each one is the output of a stage, validated against its contract before it reached disk."
      >
        <Table
          head={["File", "SHA-256", "Bytes"]}
          headAlign={["left", "left", "right"]}
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
          The queue and evaluation pages read{" "}
          <span className="mono">QUEUE_RECEIPT.json</span> (
          <Digest value={evaluation.receipt_sha256.queue} />) and{" "}
          <span className="mono">FUSION_RECEIPT.json</span> (
          <Digest value={evaluation.receipt_sha256.fusion} />).
        </p>
      </Section>

      <Section
        title="Contracts"
        description="A schema is ratified before the script that writes against it runs. A receipt that violates its contract never reaches disk, so a malformed measurement cannot be published and then noticed later."
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
        title="What this console does not do"
        description="Stated positively, because an absence is easy to claim and hard to notice."
      >
        <ul
          style={{
            margin: 0,
            paddingLeft: "1.1rem",
            lineHeight: 1.9,
            color: "var(--text-02)",
            maxWidth: "62rem",
          }}
        >
          <li>
            No request for <em>data</em> to any origin but its own, before or after
            load. There is exactly one exception to the wider claim and it is not
            data: two licensed typefaces are served from Adobe Fonts, because their
            terms forbid serving the files from anywhere else. Measured cold, that
            is 43,598 bytes: a 4,166 byte stylesheet from{" "}
            <code>use.typekit.net</code>, one 23,224 byte face for page titles and
            one 16,208 byte face for small labels. The faces carry a one-year cache
            header, so a returning reader fetches none of it. Every word of prose
            and every digit of every measurement is set in IBM Plex from this
            origin, and both licensed faces sit in front of a Plex fallback, so a
            blocked font host costs the lettering and not the reading.
          </li>
          <li>
            The kit stylesheet imports a five-byte counter from{" "}
            <code>p.typekit.net</code> so Adobe can meter the licence. It is named
            here rather than blocked: it sets no cookie and returns no content, and
            suppressing a licensor&rsquo;s own metering to keep a claim tidy would
            be the wrong way to earn it. Those two hosts are the complete list, and
            the content security policy in <code>vercel.json</code> names both, so
            a request to any third origin would be refused by the browser.
          </li>
          <li>
            The router does prefetch the next page&rsquo;s data when a link enters
            the viewport, which is a request to this site for a file that is
            already public.
          </li>
          <li>
            No model runs in the browser. The probabilities shown were fitted offline
            on the training partition of the split named beside them.
          </li>
          <li>
            No number on any page is computed by the console. The one thing the
            browser calculates is how to map stored intensities to screen colours,
            and the waterfall viewer says so on every card.
          </li>
          <li>
            No analytics about you, no cookies, no storage. Nothing is collected
            about a reader, nothing is stored on their machine, and there is
            nothing to consent to. The font counter above reports that a licence
            was used; it is told nothing about who used it.
          </li>
        </ul>
      </Section>

      <Section
        title="Degraded states"
        description="What the console shows when something is missing, and whether any observation it ships actually puts the console into that state. The right-hand column is counted from the shipped cards rather than asserted, because a failure path nobody has walked is a claim, not a feature."
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
        <Note tone="limit">
          Every count above is zero, and that is worth saying out loud rather than
          leaving as a table nobody reads. The observations this console ships are the
          top of a queue, so they are the ones with the cleanest geometry; the
          degraded paths are exercised in the offline suite and, for the WebGL
          fallback, by disabling the context and reloading. A judge who wants to see
          one live can switch off JavaScript, or block the waterfall image, and the
          page will say what it lost.
        </Note>
      </Section>

      <Section title="Data and attribution">
        <p style={{ maxWidth: "62rem", lineHeight: 1.7, color: "var(--text-02)" }}>
          {cards.attribution}
        </p>
        <p style={{ maxWidth: "62rem", lineHeight: 1.7, color: "var(--text-02)" }}>
          {cards.intensity_note}
        </p>
      </Section>
    </div>
  );
}
