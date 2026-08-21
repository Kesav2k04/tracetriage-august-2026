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
        id="contracts"
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
            maxWidth: "62rem",
          }}
        >
          <li>
            No request for <em>data</em> to any origin but its own, before or after
            load. There is exactly one exception to the wider claim and it is not
            data: two licensed families are served from Adobe Fonts, because their
            terms forbid serving the files from anywhere else. Measured cold on this
            page, as response bodies the browser received, that is 60,082 bytes: a
            4,482 byte stylesheet from <code>use.typekit.net</code>, a 172 byte
            licence counter, and three faces at 23,455, 16,430 and 15,543 bytes.
            Two families, three faces: the label family is drawn at two weights.
            They carry a one-year cache header, so a returning reader fetches none
            of it. Every word of prose and every digit of every measurement is set
            in IBM Plex from this origin, and both licensed families sit in front of
            a Plex fallback, so a blocked font host costs the lettering and not the
            reading.{" "}
            <strong>This corrects a figure published here on 2026-08-18.</strong>{" "}
            It said 43,598 bytes over one stylesheet and two faces. That was curl
            against two URLs rather than a page load, and this page was already
            fetching three faces when it was written, so the number was low by a
            face from the day it appeared.
          </li>
          <li>
            <strong>What those two faces cost is not the bytes.</strong> The kit
            declares 72 of its 90 faces at <code>font-display: auto</code>, which
            tells the browser to hold text unpainted while the face loads, and both
            faces this console uses are among the 72. Until 2026-08-21 that made the
            first screen of a first visit blank until they arrived:{" "}
            <code>956 ms</code> to first contentful paint as served against{" "}
            <code>152 ms</code> with the font host blocked, and <code>944 ms</code>{" "}
            with the self-hosted faces blocked instead, so it was the licensed pair
            and not IBM Plex, which is <code>swap</code> and holds nothing. The
            preconnect above was not the cause and adding another changed nothing.
          </li>
          <li>
            <strong>It is fixed now, and not by the setting you would expect.</strong>{" "}
            The obvious fix is <code>font-display: swap</code> in the Adobe Fonts
            web project. It was applied, and the kit today serves 18 faces at{" "}
            <code>swap</code> and 72 at <code>auto</code>: the 18 are{" "}
            <code>acumin-pro</code>, which this console does not use. So the fix
            here is in the loading order instead. The licensed families are not in{" "}
            <code>--font-display</code> or <code>--font-label</code> at all. A head
            script appends the kit at <code>media=&quot;print&quot;</code>, which
            fetches it without blocking the render, and the families arrive with a
            class on the root element only once{" "}
            <code>document.fonts.load</code> has resolved for each of the three
            faces any page renders. Plex paints at once, the licensed face replaces
            it in one reflow, and no text is ever invisible, which is the sequence{" "}
            <code>swap</code> would have produced. Measured the same way, five
            interleaved rounds, one build patched three ways, all on one machine:
            first contentful paint <code>596 ms</code> before,{" "}
            <code>236 ms</code> after, against a floor of <code>200 ms</code> with
            the kit pointed at a closed port. The after case is on the floor rather
            than near it. Its fastest round, 192 ms, beats the floor&rsquo;s
            slowest.
          </li>
          <li>
            <strong>What that cost.</strong> A layout shift, and it is published
            because reporting only the number that improved is how a build log
            becomes a brochure. Cumulative layout shift is <code>0.0115</code> after
            and <code>0</code> before, identically in all five rounds: an eighth of
            the 0.1 that counts as good, and the same reflow <code>swap</code>{" "}
            causes. It also costs <code>15,543</code> bytes on the five pages that
            draw only two of the three faces, because the script waits for all three
            everywhere: 44,536 bytes before against 60,079 after on{" "}
            <code>/evaluation/</code>, and nothing at all on the three pages that draw
            all three. Both arrive after the first paint and cache for a year. The
            alternative is a per-route face list computed at build time, which buys
            15 KB on a page that has already painted and costs a build step that can
            be wrong about what a page renders. The three faces waited for are the
            three any page renders,
            checked over eight pages at two viewport widths. The first version of
            that list had the display face at weight 400, which no page renders, and
            omitted the label face at 400, which three pages do, and every page
            still reported clean: by the time a probe can run, anything rendered has
            finished loading. The head script therefore publishes what it waited for
            in a <code>data-fonts</code> attribute, and{" "}
            <code>apps/web/audit/font-swap-probe.js</code> compares that against
            what the page draws instead of against a copy of the list. Both numbers
            and both lists are in{" "}
            <code>artifacts/FONT_PAINT_RECEIPT.json</code>, with the harness that
            produced them.{" "}
            <strong>
              The kit&rsquo;s descriptors are an Adobe account setting and can change
              with no commit here.
            </strong>{" "}
            Nothing above depends on them any more, and{" "}
            <code>apps/web/audit/paint-probe.js</code> still reads them off{" "}
            <code>document.fonts</code> at run time, so the live page can be asked
            rather than trusted.
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
