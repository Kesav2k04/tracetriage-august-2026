/**
 * Precedent retrieval, with the condition that breaks it given as much room as the one
 * that works.
 *
 * The warm column is the flattering one: neighbours may come from the query's own station,
 * and in this corpus the outcome is partly a property of who recorded it. The cold column
 * forbids the same station and the same satellite, and it is the number that says whether
 * similarity carries an outcome across entities. Both are here, side by side, with the
 * chance level in the same table so a reader can see how much of each column is the label
 * mix rather than the retriever.
 */
import { precedent, fmt } from "@/lib/data";
import { Dumbbell } from "@/components/charts";
import { Cell, Note, Section, Stat, Table, Tag } from "@/components/ui";

export const metadata = { title: "Precedent" };

const ARM_LABELS: Record<string, string> = {
  granite_text: "Granite embedding of the card",
  numeric_knn: "Standardised numbers, Euclidean",
  same_station: "The station's own recent passes",
  random: "Uniform draw from the same pool",
};

const COMPARISON_LABELS: Record<string, string> = {
  granite_text_vs_random: "Granite against chance",
  numeric_knn_vs_random: "Numbers against chance",
  same_station_vs_random: "Station history against chance",
  granite_text_vs_numeric_knn: "Granite against the numbers",
};

const warm = precedent.conditions.warm;
const cold = precedent.conditions.cold;
const arms = Object.keys(ARM_LABELS);

function Agreement({ value }: { value: number | null }) {
  if (value === null) return <span style={{ color: "var(--text-03)" }}>not applicable</span>;
  return <span>{fmt(value, 3)}</span>;
}

export default function PrecedentPage() {
  return (
    <main className="shell" style={{ paddingBlock: "var(--sp-07)" }}>
      <h1 style={{ marginBottom: "var(--sp-03)" }}>Precedent, warm and cold</h1>
      {/* The question, and then the design behind the first figure rather than in
          front of it. Both are receipt fields and both are printed in full; what changed
          is that a reader now meets the question, then the shape of the answer, and then
          the four-arm design that produced it. Stacked ahead of the first number they
          were 60 words of method before anything had been claimed. */}
      <p style={{ maxWidth: "62ch", color: "var(--text-02)" }}>{precedent.question}</p>

      <Section
        title="Agreement at 5, per arm"
        description={`${precedent.candidate_pool.observations} decisively labelled passes from ${precedent.candidate_pool.stations} stations and ${precedent.candidate_pool.satellites} satellites. Chance is ${fmt(warm.chance_level, 3)}, which is the label mix alone.`}
      >
        {/* The finding, before the digits that support it.
            Warm and cold were two columns of a table, and the thing this page is
            actually reporting is the distance between them: three arms clear chance
            warm and every one of them falls back to it cold. That is a length, and a
            reader should not have to do four subtractions to see it. The table is
            still below, because a length is not a value and the values are the
            receipt. */}
        <Dumbbell
          rows={arms.map((arm) => ({
            label: ARM_LABELS[arm] ?? arm,
            a: warm.arms[arm]?.agreement_at_k ?? null,
            b: cold.arms[arm]?.agreement_at_k ?? null,
            missingNote: "no cold definition",
          }))}
          aName="Warm"
          bName="Cold"
          rules={[
            {
              at: warm.chance_level,
              label: `chance ${fmt(warm.chance_level, 3)}`,
            },
          ]}
          format={(v) => fmt(v, 3)}
          label={
            `Agreement at 5 for four retrieval arms, warm and cold, against a chance ` +
            `level of ${fmt(warm.chance_level, 3)}.`
          }
          caption={
            `Each line is one arm. The filled mark is the warm condition, which allows ` +
            `any neighbour; the hollow mark is cold, which forbids the query's own ` +
            `station and satellite. The dashed rule is the label mix alone. The length ` +
            `of a line is what the entity restriction costs that arm.`
          }
        />
        <p
          style={{
            maxWidth: "62ch",
            color: "var(--text-02)",
            margin: "var(--sp-06) 0 var(--sp-05)",
          }}
        >
          {precedent.design}
        </p>
        <Table
          head={["Arm", "Warm", "Cold"]}
          headAlign={["left", "right", "right"]}
        >
          {arms.map((arm) => (
            <tr key={arm}>
              <Cell align="left">{ARM_LABELS[arm]}</Cell>
              <Cell>
                <Agreement value={warm.arms[arm]?.agreement_at_k ?? null} />
              </Cell>
              <Cell>
                <Agreement value={cold.arms[arm]?.agreement_at_k ?? null} />
              </Cell>
            </tr>
          ))}
        </Table>
        {cold.arms.same_station?.not_applicable ? (
          <Note tone="limit" block>{cold.arms.same_station.not_applicable}</Note>
        ) : null}
      </Section>

      <Section
        title="What survives correction"
        description="Every margin is a paired difference over the same queries, resampled by ground station and widened by Bonferroni over the comparisons this study makes."
      >
        <Table
          head={["Comparison", "Condition", "Margin", "95% interval", "Corrected", "Survives"]}
          headAlign={["left", "left", "right", "right", "right", "left"]}
        >
          {(["warm", "cold"] as const).flatMap((condition) =>
            Object.entries(precedent.conditions[condition].comparisons).map(
              ([name, row]) => (
                <tr key={`${condition}-${name}`}>
                  <Cell align="left">{COMPARISON_LABELS[name] ?? name}</Cell>
                  <Cell align="left">{condition}</Cell>
                  <Cell>
                    {row.measurable ? fmt(row.margin ?? null, 4) : "not measurable"}
                  </Cell>
                  <Cell>
                    {row.ci95 ? `[${fmt(row.ci95[0], 4)}, ${fmt(row.ci95[1], 4)}]` : "-"}
                  </Cell>
                  <Cell>
                    {row.ci_adjusted
                      ? `[${fmt(row.ci_adjusted[0], 4)}, ${fmt(row.ci_adjusted[1], 4)}]`
                      : "-"}
                  </Cell>
                  <Cell align="left">
                    <Tag tone={row.survives_correction ? "action" : "muted"}>
                      {row.survives_correction ? "yes" : "no"}
                    </Tag>
                  </Cell>
                </tr>
              ),
            ),
          )}
        </Table>
        <Note block>
          Warm, all three retrievers beat chance and survive the correction. Cold, none of
          them does: the interval contains zero. The embedding also does not beat seven
          standardised numbers under either condition. That is the finding, and it is the
          reason the queue is not ranked by this.
        </Note>
      </Section>

      <Section
        title="The index"
        description="The measurement above is exact cosine search. This is what a real vector index returned for the same queries."
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(13rem, 100%), 1fr))",
            gap: "var(--sp-05)",
          }}
        >
          <Stat label="Backend" value={precedent.vector_index.backend} />
          {Object.entries(
            precedent.vector_index.recall_at_k_against_exact_search ?? {},
          ).map(([condition, recall]) => (
            <Stat
              key={condition}
              label={`Recall at ${precedent.top_k}, ${condition}`}
              value={fmt(recall, 4)}
              detail={`over ${precedent.vector_index.queries_compared?.[condition] ?? 0} queries`}
            />
          ))}
          <Stat
            label="Embedding"
            value={precedent.embedding_model.name}
            detail={`${precedent.embedding_model.parameter_size}, ${precedent.embedding_model.quantization}`}
          />
        </div>
        <Note>{precedent.vector_index.reading}</Note>
      </Section>

      <Section title="What this does not measure">
        <ul style={{ maxWidth: "62ch", color: "var(--text-02)" }}>
          {precedent.what_this_does_not_measure.map((line) => (
            <li key={line} style={{ marginBottom: "var(--sp-03)" }}>
              {line}
            </li>
          ))}
        </ul>
      </Section>
    </main>
  );
}
