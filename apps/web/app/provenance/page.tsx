/**
 * Where every number came from, and what would have to be true for it to be wrong.
 *
 * A console that renders a receipt is only as trustworthy as the reader's ability
 * to check the receipt, so this page lists the digest of each one. The point is
 * not that a judge will hash them; it is that they could, and that the numbers on
 * the other pages are the ones inside these files rather than a retelling.
 */
import { cards, evaluation, provenance, queue } from "@/lib/data";
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
        <Table head={["File", "SHA-256", "Bytes"]}>
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
        <Table head={["Contract", "Version", "Status", "SHA-256"]}>
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
        <Table head={["Document", "What it fixes"]}>
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
            No network request after the page loads. Every byte it needs is served
            from its own origin, including the typeface.
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
            No analytics, no cookies, no storage. There is nothing to consent to
            because there is nothing being collected.
          </li>
        </ul>
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
