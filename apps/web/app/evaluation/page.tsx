/**
 * Every gate, including the ones that did not pass.
 *
 * The page is ordered by what a sceptical reader would check first: the headline
 * gate, then the four splits it was measured on, then the model comparison it
 * depends on, then what was kept and dropped and why. Nothing is hidden behind a
 * disclosure that a reader would have to know to open.
 */
import {
  evaluation,
  fmt,
  fmtInterval,
  type ArmMetrics,
  type SplitGate6,
} from "@/lib/data";
import RiskCoverage from "@/components/RiskCoverage";
// The gate 4 bundle's own receipt, written by scripts/pack_gate4_bundle.py at the same
// moment it verified 72 commitments and packed the archive. Imported rather than
// retyped, so the digest a reviewer checks their download against is the digest of the
// file that exists.
import gate4Bundle from "@/public/gate4/BUNDLE.json";
import {
  Cell,
  IntervalBar,
  Note,
  Section,
  Stat,
  Table,
  Tag,
  VerdictBadge,
} from "@/components/ui";

export const metadata = { title: "Evaluation" };

// Null while nobody has answered the worksheet, which is the normal state and renders
// nothing rather than a block of zeros.
const gate4Arm = evaluation.gate4_arm;
const gate6 = evaluation.gate6;
const gate5 = evaluation.gate5;
const ablation = evaluation.ablation_conclusion;
const circularity = evaluation.circularity;

/** Names for the restricted targets, so the table reads as English rather than as keys. */
const CIRCULARITY_TARGET_LABELS: Record<string, string> = {
  all_three_criteria: "The shipped definition",
  model_dependent_only: "Model-dependent criteria only",
  model_independent_only: "Model-independent criteria only",
  model_independent_and_firing: "Model-independent, and firing",
};
const chrono = evaluation.fusion_splits.find((s) => s.split === "chronological")!;
const sizeMatched = evaluation.fusion_splits.find(
  (s) => s.split === "chronological_size_matched",
);

const SPLIT_LABELS: Record<string, string> = {
  chronological: "Chronological",
  cold_station: "Cold station",
  cold_transmitter: "Cold transmitter",
  cold_combined: "Cold station and transmitter",
  chronological_size_matched: "Chronological, size matched control",
};

interface AblationRule {
  blocks: Record<
    string,
    { decision: string; better_on: string[]; worse_on: string[] }
  >;
  shipped_blocks: string[];
  shipped_arm: string | null;
}

const nominal = ablation.nominal as unknown as AblationRule;
const corrected = ablation.multiplicity_corrected as unknown as AblationRule;
const disagree = (ablation.rules_disagree_on as string[]) ?? [];
// What the ranker is built from, and what the ablation recommends, are two answers to
// two questions. They agreed until the multiplicity correction ran over the family the
// ablation rule reads; the page has to show both or it reports one as the other.
const recommendation = ablation.shipped_arm_vs_recommendation as unknown as {
  ships: string;
  corrected_recommends: string | null;
  agree: boolean;
  shipped_blocks_without_corrected_support: string[];
  note: string;
};
const shippedScores = ablation.shipped_arm_scores as unknown as {
  split: string;
  brier: number;
  auc: number;
  ece: number;
  calibration_slope: number;
};

function GateSixSplit({ name, split }: { name: string; split: SplitGate6 }) {
  if (!split.measurable) {
    return (
      <div
        style={{
          padding: "var(--sp-05)",
          border: "1px solid var(--border-subtle)",
          background: "var(--ui-01)",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "var(--sp-04)",
            alignItems: "center",
            marginBottom: "var(--sp-04)",
          }}
        >
          <h3 style={{ fontSize: "var(--type-heading-02)" }}>
            {SPLIT_LABELS[name] ?? name}
          </h3>
          <VerdictBadge verdict={split.verdict} />
        </div>
        <p style={{ margin: 0, color: "var(--text-02)", lineHeight: 1.6 }}>
          {split.not_measurable_reason}
        </p>
      </div>
    );
  }

  // lift_ci95 is whichever interval the pipeline decided governs. The two
  // component intervals are shown below it so the choice is checkable.
  const governing = split.lift_ci95;

  return (
    <div
      style={{
        padding: "var(--sp-05)",
        border: "1px solid var(--border-subtle)",
        background: "var(--ui-01)",
      }}
    >
      <div
        style={{
          display: "flex",
          gap: "var(--sp-04)",
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: "var(--sp-05)",
        }}
      >
        <h3 style={{ fontSize: "var(--type-heading-02)" }}>
          {SPLIT_LABELS[name] ?? name}
        </h3>
        <VerdictBadge verdict={split.verdict} />
        <span
          className="num"
          style={{ marginLeft: "auto", color: "var(--text-03)", fontSize: "var(--type-caption)" }}
        >
          {split.n_queue_conflicts} of {split.n_queue_examined} reviewed
        </span>
      </div>

      <IntervalBar
        low={governing?.[0] ?? 0}
        high={governing?.[1] ?? 0}
        point={split.lift_point ?? 0}
        threshold={1.5}
        domain={[0.5, 2.5]}
        label={`${SPLIT_LABELS[name] ?? name} lift`}
      />

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--sp-02) var(--sp-05)",
          margin: "var(--sp-05) 0 0",
          fontSize: "var(--type-caption)",
        }}
      >
        <dt style={{ color: "var(--text-03)" }}>Lift</dt>
        <dd className="num" style={{ margin: 0 }}>
          {fmt(split.lift_point)}
        </dd>

        <dt style={{ color: "var(--text-03)" }}>Grouped by episode</dt>
        <dd className="num" style={{ margin: 0 }}>
          {fmtInterval(split.lift_ci95_episode)}{" "}
          <span style={{ color: "var(--text-03)" }}>
            ({split.n_groups} groups)
          </span>
        </dd>

        <dt style={{ color: "var(--text-03)" }}>Grouped by station</dt>
        <dd className="num" style={{ margin: 0 }}>
          {fmtInterval(split.lift_ci95_station)}{" "}
          <span style={{ color: "var(--text-03)" }}>
            ({split.n_station_groups} groups)
          </span>
        </dd>

        <dt style={{ color: "var(--text-03)" }}>Reported</dt>
        <dd style={{ margin: 0 }}>
          {split.governing_interval === "union_of_episode_and_station"
            ? "the union of the two, which is the wider claim"
            : split.governing_interval}
        </dd>

        <dt style={{ color: "var(--text-03)" }}>Station clustering</dt>
        <dd style={{ margin: 0 }}>
          {split.station_clustering?.measurable ? (
            <>
              ICC{" "}
              <span className="num">{fmt(split.station_clustering.icc)}</span>,
              design effect{" "}
              <span className="num">
                {fmt(split.station_clustering.design_effect, 2)}
              </span>
            </>
          ) : (
            (split.station_clustering?.reason ?? "not measured")
          )}
        </dd>

        <dt style={{ color: "var(--text-03)" }}>Episode clustering</dt>
        <dd style={{ margin: 0 }}>
          {split.episode_clustering?.measurable ? (
            <>
              ICC{" "}
              <span className="num">{fmt(split.episode_clustering.icc)}</span>, mean
              group size{" "}
              <span className="num">
                {fmt(split.episode_clustering.mean_group_size, 3)}
              </span>
            </>
          ) : (
            (split.episode_clustering?.reason ?? "not measured")
          )}
        </dd>
      </dl>
    </div>
  );
}

function armRow(name: string, arm: ArmMetrics, worst: number, best: number) {
  const span = worst - best || 1;
  const width = ((worst - arm.brier) / span) * 100;
  return (
    <tr key={name}>
      <Cell align="left" header>
        {name}
      </Cell>
      <Cell align="left">
        <span style={{ display: "flex", gap: "var(--sp-02)", flexWrap: "wrap" }}>
          {arm.blocks.length === 0 ? (
            <Tag tone="muted">none</Tag>
          ) : (
            arm.blocks.map((block) => <Tag key={block}>{block}</Tag>)
          )}
        </span>
      </Cell>
      <Cell align="left">
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--sp-03)",
            justifyContent: "flex-end",
          }}
        >
          <span
            aria-hidden="true"
            style={{
              display: "block",
              height: 8,
              width: `${Math.max(width, 1)}%`,
              minWidth: 2,
              background: "var(--interactive-04)",
              opacity: 0.55,
            }}
          />
          <span className="num">{arm.brier.toFixed(5)}</span>
        </span>
      </Cell>
      <Cell mono>{arm.auc.toFixed(3)}</Cell>
      <Cell mono>{arm.ece.toFixed(4)}</Cell>
      <Cell mono>{arm.calibration_slope.toFixed(3)}</Cell>
    </tr>
  );
}

export default function EvaluationPage() {
  // arms is nullable, because a degraded split has no results and the export writes
  // null for it. Before D4 the type said otherwise and this line read straight
  // through: Object.entries(null) throws, which at least fails the export loudly
  // rather than publishing a page with an empty ladder. Held in a local const so the
  // narrowing survives into the callbacks below.
  const armsRecord = chrono.arms;
  if (chrono.degraded !== null || armsRecord === null) {
    return (
      <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
        <h1 style={{ fontSize: "var(--type-heading-05)" }}>Evaluation</h1>
        <Note tone="warn">
          Every number on this page is measured on the chronological split, and that
          split published no arm results.{" "}
          {chrono.degraded ??
            "The split is not marked degraded, so this is a build problem rather than a result: the export should have failed before writing it."}
        </Note>
      </div>
    );
  }

  const arms = Object.entries(armsRecord);
  const briers = arms.map(([, a]) => a.brier);
  const worst = Math.max(...briers);
  const best = Math.min(...briers);

  const ceiling = (chrono.selective?.ceilings as
    | Array<{
        chosen_on_calibration: { threshold: number; target_risk: number };
        achieved_on_test: {
          coverage: number;
          risk: number;
          risk_ci95: [number, number];
          threshold: number;
          held: boolean;
          held_at_point_estimate: boolean;
          n_kept: number;
          n_total: number;
          n_errors: number;
          note: string;
        };
      }>
    | undefined)?.[0];

  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "62rem" }}>
        <h1 style={{ fontSize: "var(--type-heading-05)" }}>Evaluation</h1>
        <p
          style={{
            marginTop: "var(--sp-04)",
            color: "var(--text-02)",
            lineHeight: 1.7,
            fontSize: "var(--type-body-long)",
          }}
        >
          Two gates decide whether this project earned its claims, and neither one
          passed. The sidebar says two of six gates are met: those two are the
          feasibility gates, 1 and 2, which asked whether the data and the physics
          could be obtained at all and were pre-passed before this work started. The
          four substantive gates are 3 to 6, and the two measured here are the ones a
          claim rests on. Both are reported with the intervals they were decided on,
          because a gate that only reports its wins is not a gate.
        </p>
      </header>

      <Section
        title={`Kill gate ${gate6.gate}: does the queue beat random?`}
        description={<em>“{gate6.wording}”</em>}
      >
        <div
          style={{
            display: "flex",
            gap: "var(--sp-05)",
            alignItems: "center",
            marginBottom: "var(--sp-05)",
          }}
        >
          <VerdictBadge verdict={gate6.verdict} size="large" />
          <span style={{ color: "var(--text-03)", fontSize: "var(--type-caption)" }}>
            decided on the {SPLIT_LABELS[gate6.decided_on] ?? gate6.decided_on} split
          </span>
        </div>
        <p style={{ maxWidth: "62rem", lineHeight: 1.7 }}>{gate6.statement}</p>

        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(28rem, 1fr))",
            marginTop: "var(--sp-06)",
          }}
        >
          {Object.entries(gate6.per_split).map(([name, split]) => (
            <GateSixSplit key={name} name={name} split={split} />
          ))}
        </div>

        <Note tone="info">
          Two groupings are reported because two things are correlated here and they
          are not the same thing: captures of one pass share a geometry, and captures
          from one ground station share a receiver. The reported interval is the union
          of the two, which is the wider and therefore the weaker claim. Choosing
          whichever grouping gave the narrower interval would be choosing the answer.
        </Note>
      </Section>

      <Section
        id="circularity"
        title="How much of that lift is guaranteed by the way the queue was built"
        description="The ranking score and the definition of a conflict read the same quantities, so part of the lift is true by construction. This bounds that part rather than arguing about it."
      >
        <p style={{ margin: "0 0 var(--sp-05)", lineHeight: 1.7, maxWidth: "62rem" }}>
          {circularity.shared_signals.reading}
        </p>

        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(14rem, 1fr))",
            marginBottom: "var(--sp-06)",
          }}
        >
          <Stat
            label="Ceiling at this budget"
            value={`${fmt(circularity.ceiling.lift, 3)}×`}
            detail={`An oracle finds all ${circularity.ceiling.max_findable_at_budget} and scores this.`}
          />
          <Stat
            label="Room between bar and oracle"
            value={fmt(
              circularity.ceiling.headroom_between_threshold_and_perfection,
              3,
            )}
            detail={`The gate asked for ${circularity.ceiling.threshold}×.`}
          />
          <Stat
            label="Share of the ceiling reached"
            value={fmt(circularity.ceiling.queue_share_of_the_ceiling, 3)}
            detail="Conflicts the queue found, over the most any ordering could."
          />
          <Stat
            label="Permutation p"
            value={circularity.random_ordering_control.p_value_permutation.toFixed(4)}
            detail={`${circularity.random_ordering_control.n_permutations_at_or_above_observed} of ${circularity.random_ordering_control.n_permutations} random orderings matched it.`}
          />
        </div>

        <Table
          head={["Restricted target", "Criteria", "Conflicts", "Lift", "95% interval", "Verdict"]}
          headAlign={["left", "left", "right", "right", "right", "left"]}
          caption={circularity.targets_note}
        >
          {Object.entries(circularity.targets).map(([name, target]) => (
            <tr key={name}>
              <Cell align="left" header>
                {CIRCULARITY_TARGET_LABELS[name] ?? name}
              </Cell>
              <Cell align="left">
                <span
                  style={{ display: "flex", gap: "var(--sp-02)", flexWrap: "wrap" }}
                >
                  {target.criteria.map((code) => (
                    <Tag
                      key={code}
                      tone={
                        circularity.shared_signals.inert.includes(code)
                          ? "muted"
                          : "neutral"
                      }
                    >
                      {code}
                      {circularity.shared_signals.inert.includes(code)
                        ? " (fires on nothing)"
                        : ""}
                    </Tag>
                  ))}
                </span>
              </Cell>
              <Cell mono>{target.n_conflicts}</Cell>
              <Cell mono>
                {target.lift_point === null ? "—" : fmt(target.lift_point)}
              </Cell>
              <Cell mono>
                {target.lift_ci95 === null ? "—" : fmtInterval(target.lift_ci95)}
              </Cell>
              <Cell align="left">
                <VerdictBadge verdict={target.verdict} />
              </Cell>
            </tr>
          ))}
        </Table>

        <Table
          head={["Split", "Population", "Conflicts", "Budget", "Oracle scores", "Room above the bar"]}
          headAlign={["left", "right", "right", "right", "right", "right"]}
          caption="The scale each split's verdict is read on. A split whose oracle barely clears the threshold cannot produce an informative verdict, whichever way it falls."
        >
          {Object.entries(circularity.ceilings_by_split).map(([name, block]) => (
            <tr key={name}>
              <Cell align="left" header>
                {SPLIT_LABELS[name] ?? name}
                {block.measurable && block.informative === false ? (
                  <div
                    style={{
                      fontSize: "var(--type-caption)",
                      color: "var(--support-03)",
                      fontWeight: 400,
                    }}
                  >
                    not informative at this budget
                  </div>
                ) : null}
              </Cell>
              <Cell mono>{block.n_population ?? "—"}</Cell>
              <Cell mono>{block.n_conflicts ?? "—"}</Cell>
              <Cell mono>{block.budget ?? "—"}</Cell>
              <Cell mono>
                {block.ceiling === undefined ? "—" : `${fmt(block.ceiling, 3)}×`}
              </Cell>
              <Cell mono>
                {block.headroom_between_threshold_and_perfection === undefined
                  ? "—"
                  : fmt(block.headroom_between_threshold_and_perfection, 3)}
              </Cell>
            </tr>
          ))}
        </Table>

        <Note tone="limit">{circularity.what_this_does_not_establish}</Note>
        <Note tone="info">{circularity.random_ordering_control.reading}</Note>
      </Section>

      <Section
        title={`Kill gate ${gate5.gate}: does physics conditioning help?`}
        description={<em>“{gate5.wording}”</em>}
      >
        <div
          style={{
            display: "flex",
            gap: "var(--sp-05)",
            alignItems: "center",
            marginBottom: "var(--sp-05)",
          }}
        >
          <VerdictBadge verdict={gate5.verdict} size="large" />
          <span style={{ color: "var(--text-03)", fontSize: "var(--type-caption)" }}>
            {gate5.challenger} against {gate5.reference}, decided on{" "}
            {SPLIT_LABELS[gate5.decided_on] ?? gate5.decided_on}
          </span>
        </div>
        <p style={{ maxWidth: "62rem", lineHeight: 1.7 }}>{gate5.statement}</p>

        <Table
          head={[
            "Split",
            "Brier margin",
            "95% interval",
            "Direction",
            "Observations",
            "Groups",
          ]}
          headAlign={["left", "right", "right", "left", "right", "right"]}
          caption="A positive margin means the physics-conditioned arm is better. An interval spanning zero is not a gain in either direction."
        >
          {Object.entries(gate5.per_split).map(([name, split]) => (
            <tr key={name}>
              <Cell align="left" header>
                {SPLIT_LABELS[name] ?? name}
              </Cell>
              <Cell mono>{fmt(split.margin, 5)}</Cell>
              <Cell mono>{fmtInterval(split.ci95, 5)}</Cell>
              <Cell align="left">
                <Tag tone={split.distinguishable ? "action" : "muted"}>
                  {split.direction}
                </Tag>
              </Cell>
              <Cell mono>{split.n_observations ?? "—"}</Cell>
              <Cell mono>{split.n_groups ?? "—"}</Cell>
            </tr>
          ))}
        </Table>
      </Section>

      <Section
        title="The arm ladder"
        description={`Ten arms on the ${SPLIT_LABELS[chrono.split]} split, each adding one block of features to the one before. Brier is the score being minimised; a shorter bar is a worse arm.`}
      >
        <Table
          head={["Arm", "Blocks", "Brier", "AUC", "ECE", "Calibration slope"]}
          headAlign={["left", "left", "right", "right", "right", "right"]}
          caption={`Test partition: ${chrono.counts.test} observations, positive rate ${fmt(chrono.test_positive_rate, 3)}. Calibrator: ${arms[0]?.[1].calibrator_chosen_because}`}
        >
          {arms.map(([name, arm]) => armRow(name, arm, worst, best))}
        </Table>
      </Section>

      <Section
        title="What was kept, and under which rule"
        description="Two retention rules were written down. They disagree, and the stricter one decides."
      >
        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(20rem, 1fr))",
          }}
        >
          {[
            { key: "nominal", rule: nominal, title: "Nominal rule" },
            {
              key: "multiplicity_corrected",
              rule: corrected,
              title: "Bonferroni corrected rule",
            },
          ].map(({ key, rule, title }) => (
            <div
              key={key}
              style={{
                padding: "var(--sp-05)",
                background: "var(--ui-01)",
                border: `1px solid ${
                  ablation.deciding_rule === key
                    ? "var(--interactive-04)"
                    : "var(--border-subtle)"
                }`,
              }}
            >
              <div
                style={{
                  display: "flex",
                  gap: "var(--sp-04)",
                  alignItems: "center",
                  marginBottom: "var(--sp-04)",
                }}
              >
                <h3 style={{ fontSize: "var(--type-heading-02)" }}>{title}</h3>
                {ablation.deciding_rule === key && <Tag tone="action">decides</Tag>}
              </div>
              <p
                style={{
                  margin: "0 0 var(--sp-05)",
                  color: "var(--text-02)",
                  fontSize: "var(--type-caption)",
                  lineHeight: 1.6,
                }}
              >
                {ablation.rules[key]}
              </p>
              <ul style={{ margin: 0, paddingLeft: "1.1rem", lineHeight: 1.8 }}>
                {Object.entries(rule.blocks).map(([block, decision]) => (
                  <li key={block}>
                    <span className="mono">{block}</span>{" "}
                    <Tag
                      tone={
                        decision.decision === "RETAIN"
                          ? "action"
                          : decision.decision === "DROP"
                            ? "neutral"
                            : "muted"
                      }
                    >
                      {decision.decision}
                    </Tag>
                    {disagree.includes(block) && (
                      <span
                        style={{
                          color: "var(--support-03)",
                          fontSize: "var(--type-caption)",
                          marginLeft: "var(--sp-03)",
                        }}
                      >
                        the rules disagree here
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <p
                style={{
                  marginTop: "var(--sp-05)",
                  marginBottom: 0,
                  fontSize: "var(--type-caption)",
                  color: "var(--text-03)",
                }}
              >
                recommends:{" "}
                <span className="mono">{rule.shipped_blocks.join(" + ")}</span>
                {rule.shipped_arm ? ` as ${rule.shipped_arm}` : ""}
              </p>
            </div>
          ))}
        </div>

        <Note tone="warn">{ablation.why_the_corrected_rule_decides}</Note>

        {recommendation && !recommendation.agree && (
          <Note tone="limit">{recommendation.note}</Note>
        )}

        <div
          style={{
            display: "grid",
            gap: "var(--sp-05)",
            gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
            marginTop: "var(--sp-06)",
          }}
        >
          <Stat
            label="Shipped arm"
            value={
              <span className="mono">{(ablation.shipped_arm as string) ?? "—"}</span>
            }
            detail={`measured on ${
              shippedScores
                ? (SPLIT_LABELS[shippedScores.split] ?? shippedScores.split)
                : "an unrecorded split"
            }`}
          />
          <Stat label="Brier" value={fmt(shippedScores?.brier, 5)} detail="lower is better" />
          <Stat label="AUC" value={fmt(shippedScores?.auc, 3)} detail="ranking quality" />
          <Stat
            label="ECE"
            value={fmt(shippedScores?.ece, 4)}
            detail="how far the stated probabilities are from the observed rates"
          />
        </div>

        <Note tone="limit">{ablation.caveat as string}</Note>

        <Note tone="limit">
          Splits used for the ablation verdict:{" "}
          {(ablation.splits_used as string[]).join(", ")}. Below the{" "}
          {String(ablation.min_train_for_verdict)}-row training floor and therefore
          excluded: {(ablation.splits_below_training_floor as string[]).join(", ")}.{" "}
          {String(ablation.min_train_justification)}
        </Note>
      </Section>

      {/*
        A missing curve used to remove this whole section: no heading, no note, no
        warning tone, nothing in the DOM. A reader could not tell "the model was never
        allowed to refuse" from "we did not measure it", and the export published null
        here for a block that was renamed rather than absent. The section now states
        the absence and names what it depends on.
      */}
      {!chrono.selective?.curve ? (
        <Section
          title="What it looks like when the model is allowed to refuse"
          description="Not published for this split."
        >
          <Note tone="limit">
            No selective-rejection curve was published for the{" "}
            {SPLIT_LABELS[chrono.split]} split, so there is no risk against coverage
            panel here. A degraded split is handled at the top of this page, so
            reaching here means the split ran and the curve is missing from the
            receipt rather than impossible to compute: a build problem rather than a
            result.
          </Note>
        </Section>
      ) : (
        <Section
          title="What it looks like when the model is allowed to refuse"
          description="A triage model that answers on everything is not the only option. This is what the error rate does as it is allowed to abstain."
        >
          <div
            style={{
              padding: "var(--sp-06)",
              background: "var(--ui-01)",
              border: "1px solid var(--border-subtle)",
            }}
          >
            <RiskCoverage
              curve={chrono.selective.curve}
              operating={
                ceiling
                  ? {
                      coverage: ceiling.achieved_on_test.coverage,
                      risk: ceiling.achieved_on_test.risk,
                      risk_ci95: ceiling.achieved_on_test.risk_ci95,
                      threshold: ceiling.achieved_on_test.threshold,
                      held: ceiling.achieved_on_test.held,
                    }
                  : null
              }
              label={`Risk against coverage, ${SPLIT_LABELS[chrono.split]} split`}
            />
          </div>

          {ceiling && (
            <>
              <div
                style={{
                  display: "grid",
                  gap: "var(--sp-05)",
                  gridTemplateColumns: "repeat(auto-fit, minmax(13rem, 1fr))",
                  marginTop: "var(--sp-06)",
                }}
              >
                <Stat
                  label="Target error rate"
                  value={fmt(ceiling.chosen_on_calibration.target_risk, 2)}
                  detail="the promise the threshold was chosen to keep"
                />
                <Stat
                  label="Coverage on test"
                  value={`${(ceiling.achieved_on_test.coverage * 100).toFixed(0)}%`}
                  detail={`${ceiling.achieved_on_test.n_kept} of ${ceiling.achieved_on_test.n_total} answered`}
                />
                <Stat
                  label="Error rate on test"
                  value={fmt(ceiling.achieved_on_test.risk, 3)}
                  detail={`${ceiling.achieved_on_test.n_errors} wrong, interval ${fmtInterval(ceiling.achieved_on_test.risk_ci95)}`}
                />
                <Stat
                  label="Ceiling held"
                  value={String(ceiling.achieved_on_test.held)}
                  tone={
                    ceiling.achieved_on_test.held
                      ? "var(--verdict-passed)"
                      : "var(--verdict-not-established)"
                  }
                  detail="decided on the top of the interval"
                />
              </div>
              <Note tone="limit">{ceiling.achieved_on_test.note}</Note>
            </>
          )}
        </Section>
      )}

      <Section
        title="Gate 4 needs a person, and here is what to send them"
        description="The one gate in this project that no amount of compute closes. The worksheet has been answered once and not by a person, so the gate is still OPEN: the arm below says the sample supports a decision, and it cannot say a reader would reach one."
      >
        <p style={{ color: "var(--text-02)", lineHeight: 1.8, maxWidth: "62rem" }}>
          The threshold was fixed before the build: at least 80% of a balanced sample,
          reviewed with the network&rsquo;s labels and every model output hidden, must
          support a decisive judgment. The sample is{" "}
          <strong>{gate4Bundle.n_items} items over {gate4Bundle.n_unique_observations}{" "}
          observations</strong>, {gate4Bundle.n_repeats} of them repeated under a second
          item id so intra-rater agreement can be measured without telling the reviewer
          which are repeats. Sixty rather than thirty-six because the verdict reads the
          interval: at 36 a true decisive rate of 0.90 could not clear the bar however
          the review went.
        </p>
        <p style={{ color: "var(--text-02)", lineHeight: 1.8, maxWidth: "62rem" }}>
          The sample is committed to rather than promised. A 32-byte salt and the
          item-to-observation mapping live outside the repository; what is committed is
          one sha256 per item over the salt, the item id, the observation id and the
          digest of the image file. Before the review nobody can invert that. After it,
          the scorer re-hashes every image from disk, recomputes every commitment,
          refuses outright if one fails, and publishes the salt and the mapping.{" "}
          <strong>
            All {gate4Bundle.commitments_checked} were verified against the images on
            disk when the bundle was packed.
          </strong>
        </p>
        {/* The clip goes above the arm's numbers rather than below them, because it
            ends on the sentence the numbers are most likely to be read without: the
            gate is open. `preload="none"` so a page nobody plays it on pays for a
            poster and nothing else, and it is self-hosted, so `media-src 'self'`
            holds and there is no embed from a video host.

            Labelled, not just captioned. The fallback paragraph inside a `<video>` is
            only exposed to a browser that cannot play it, so a reader using a screen
            reader on a browser that can play it hears "video" and nothing else. The
            label says what the clip shows; the figcaption carries the reasoning. */}
        <figure className="explainer">
          <video
            controls
            preload="none"
            playsInline
            aria-label={
              "Thirty-seven seconds, no narration: how gate 4's sample was committed " +
              "to before the review, what the scorer checks before it reads an " +
              "answer, the rate that came back, and why the gate is still open."
            }
            poster="/media/gate4-explainer-poster.jpg"
            width={1920}
            height={1080}
          >
            <source src="/media/gate4-explainer.mp4" type="video/mp4" />
            <p>
              Your browser cannot play this video. It shows how the gate 4 sample was
              committed to with one salted sha256 per item before any review began,
              what the scorer re-checks from disk before it reads a single answer, the
              rate that came back, and why the gate is still open.
            </p>
          </video>
          <figcaption>
            The commitment is the part of this gate a reader cannot check by running
            the code, because the claim is about the order events happened in. Every
            number in the clip is in{" "}
            <code>artifacts/GATE4_RECEIPT.json</code>, and{" "}
            <code>tests/test_explainer_gate4_values.py</code> fails if the scene and
            the receipt ever disagree.
          </figcaption>
        </figure>
        {gate4Arm && (
          <>
            <p style={{ color: "var(--text-02)", lineHeight: 1.8, maxWidth: "62rem" }}>
              <strong style={{ color: "var(--text-01)" }}>
                One arm has been measured, and its reviewer was not a person.
              </strong>{" "}
              {gate4Arm.reviewer.identity} It answered the published protocol on the
              committed plates with every label hidden, in{" "}
              {gate4Arm.reviewer.kind === "model" ? "twelve" : "several"} independent
              blocks of six so that no block could see both halves of a repeated pair.
              What that establishes is narrower than the gate and had never been
              measured: the sample as committed supports a decisive judgment at all.
              What it cannot establish is the gate as written, because the instrument
              the gate names is a reader and this was not one.
            </p>
            <div className="stat-grid">
              <Stat
                label="Decidable"
                value={`${gate4Arm.decisive}/${gate4Arm.observations_scored}`}
                detail={`rate ${fmt(gate4Arm.rate, 3)}, 95% ${fmtInterval([
                  gate4Arm.rate_lower_bound_95,
                  gate4Arm.rate_upper_bound_95,
                ])} against a 0.80 threshold`}
              />
              <Stat
                label="Same answer twice"
                value={`${gate4Arm.intra_rater.identical_on_all_three_axes}/${gate4Arm.intra_rater.repeated_pairs_scored}`}
                detail="repeated plates answered identically on all three axes, by a different block each time. A ceiling on the rate beside it"
              />
              <Stat
                label="Gate 4"
                value={gate4Arm.gate_verdict_is_not_this}
                detail="the arm's own verdict is not the gate's. This field is the gate's, and it does not move for a reviewer the gate is not about"
              />
            </div>
            <Table
              head={["Compared against the network label", "Agreed", "Of"]}
              headAlign={["left", "right", "right"]}
              caption={gate4Arm.label_agreement.neither_axis_asks_the_network_question}
            >
              {Object.values(gate4Arm.label_agreement.by_axis).map((axis) => (
                <tr key={axis.axis}>
                  <Cell align="left" header>
                    <code>{axis.axis}</code>
                  </Cell>
                  <Cell mono>{axis.agreed_with_the_network_label}</Cell>
                  <Cell mono>{axis.items_scored}</Cell>
                </tr>
              ))}
            </Table>
          </>
        )}
        <Table
          head={["What a reviewer needs", "Where it is"]}
          headAlign={["left", "left"]}
        >
          <tr>
            <Cell align="left" header>
              The protocol: three axes, four answers, what <code>unsure</code> means
            </Cell>
            <Cell align="left">
              <a href="/gate4/worksheet.md">/gate4/worksheet.md</a>
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              The review page, which exports the CSV the scorer reads
            </Cell>
            <Cell align="left">
              <a href="/gate4/review.html">/gate4/review.html</a>
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              The {gate4Bundle.images.n} plates, {(gate4Bundle.images.bytes / 1e6).toFixed(0)} MB of
              full-resolution waterfalls
            </Cell>
            <Cell align="left">
              not published: ask for{" "}
              <code>{gate4Bundle.archive.name}</code>
            </Cell>
          </tr>
          <tr>
            <Cell align="left" header>
              What to check the download against
            </Cell>
            <Cell mono align="left">
              {gate4Bundle.archive.bytes.toLocaleString()} B, sha256{" "}
              {gate4Bundle.archive.sha256.slice(0, 24)}
            </Cell>
          </tr>
        </Table>
        <Note>
          The plates are the one thing here that is not compressed, and that is why they
          are not on this page. Lossless re-encoding keeps the pixels and breaks the
          digests, which spends the commitment to save a quarter of the bytes. Lossy
          re-encoding and downscaling both smooth the faint traces the reviewer is being
          asked to judge, which answers the gate&rsquo;s question by degrading its
          stimulus. So the archive stays whole and travels as one file with a digest.
          Open <code>review.html</code> from the unpacked folder, answer{" "}
          {gate4Bundle.n_items} items, send back one CSV.{" "}
          <strong>
            Until a person does that the verdict stays OPEN, and it stays OPEN for a
            review by anything that is not a person.
          </strong>{" "}
          The scorer refuses to publish a rate without a declaration of who produced it,
          and for a reviewer that is not a person it files every number under{" "}
          <code>arm</code> and leaves the gate&rsquo;s own verdict alone.
        </Note>
      </Section>

      {sizeMatched && (
        <Section
          title="The size-matched control"
          description="A cold split has fewer training rows than the chronological one, so a difference between them could be the split or could be the sample size. This control holds the size fixed and changes only the split, which is the only way to tell those apart."
        >
          <Table head={["Partition", "Rows"]} caption={`Split: ${sizeMatched.split}.`}>
            {Object.entries(sizeMatched.counts).map(([partition, n]) => (
              <tr key={partition}>
                <Cell align="left" header>
                  {partition}
                </Cell>
                <Cell mono>{n}</Cell>
              </tr>
            ))}
          </Table>
        </Section>
      )}
    </div>
  );
}
