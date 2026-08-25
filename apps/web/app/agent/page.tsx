/**
 * The agent study, with the control arm given the same room as the tool arm.
 *
 * A page that showed only the tool arm's score would be a demonstration. The number
 * that makes it a measurement is the other arm's, so the two sit side by side, the
 * paired table below them is the four cells of the comparison rather than a summary
 * of it, and the per-question table carries both answers so a reader can disagree
 * with any single grade.
 */
import { agent, fmt, fmtInterval, mcp } from "@/lib/data";
import { OutcomeStrip } from "@/components/charts";
import { Cell, Note, Section, Stat, Table, Tag } from "@/components/ui";

export const metadata = { title: "Agent" };

const tools = agent.arms.tools;
const control = agent.arms.control;
const paired = agent.paired;

const toolCount = mcp.servers.reduce((total, server) => total + server.tools.length, 0);

const controlInvented = agent.questions.filter((row) => !row.control_grounded).length;

function Verdict({ correct, children }: { correct: boolean; children: string }) {
  return (
    <Tag tone={correct ? "action" : "muted"} wrap>
      {children}
    </Tag>
  );
}

export default function AgentPage() {
  return (
    <main className="shell" style={{ paddingBlock: "var(--sp-07)" }}>
      <h1 style={{ marginBottom: "var(--sp-03)" }}>Agent, against a control</h1>
      <p style={{ maxWidth: "62ch", color: "var(--text-02)" }}>{agent.design}</p>

      <Section
        title="The two arms"
        description={`${agent.tasks} questions, at most ${agent.max_steps} steps each, ${agent.model.name} at temperature ${agent.model.temperature} with seed ${agent.model.seed}.`}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(15rem, 100%), 1fr))",
            gap: "var(--sp-05)",
          }}
        >
          <Stat
            label="Correct, with the tools"
            value={`${tools.correct.successes} / ${tools.correct.trials}`}
            detail={`95% ${fmtInterval([tools.correct.lower_95, tools.correct.upper_95])}`}
          />
          <Stat
            label="Correct, with no tools"
            value={`${control.correct.successes} / ${control.correct.trials}`}
            detail={`95% ${fmtInterval([control.correct.lower_95, control.correct.upper_95])}`}
          />
          <Stat
            label="Numbers that were read, tools"
            value={`${tools.grounded.successes} / ${tools.grounded.trials}`}
            detail="every number in the answer appeared in something the agent fetched"
          />
          <Stat
            label="Declined as unknown, control"
            value={`${control.declined_unknown} / ${control.correct.trials}`}
            detail={`${controlInvented} answers carried a number nothing supported`}
          />
        </div>
      </Section>

      <Section title="The paired comparison" description={paired.method}>
        {/* The pairing, drawn as the pairing.
            A two-by-two of counts is the correct summary and it is right below this,
            but it throws away the thing that makes this result readable: the two arms
            answered the SAME 24 questions, and a reader can see all 24 at once. Twenty
            cells filled on one row and hollow on the other is the discordance the
            exact test is computed from, and it is the same twenty either way. */}
        <OutcomeStrip
          arms={[
            {
              name: "With the tools",
              sub: "may read this project's own files",
              cells: agent.questions.map((q) => ({
                state: q.tools_correct,
                title: `${q.task_id}: ${q.tools_correct ? "correct" : "wrong"} with tools`,
              })),
            },
            {
              name: "With no tools",
              sub: "the same model, answering from what it knows",
              cells: agent.questions.map((q) => ({
                state: q.control_correct,
                title: `${q.task_id}: ${q.control_correct ? "correct" : "wrong"} with no tools`,
              })),
            },
          ]}
          itemLabel={`One cell is one of the ${agent.tasks} questions, in the same order on both rows.`}
          label={
            `Twenty-four questions, answered by the same model with and without this ` +
            `project's tools. Filled is correct.`
          }
          caption={
            `Both rows are the same questions in the same order, so a column is one ` +
            `question under both conditions. ${paired.discordant_pairs} columns differ ` +
            `between the rows, and the tool arm holds ${paired.tools_only.length} of them.`
          }
        />
        <Table head={["", "Control right", "Control wrong"]}>
          <tr>
            <Cell align="left">Tools right</Cell>
            <Cell>{paired.both_correct}</Cell>
            <Cell>{paired.tools_only.length}</Cell>
          </tr>
          <tr>
            <Cell align="left">Tools wrong</Cell>
            <Cell>{paired.control_only.length}</Cell>
            <Cell>{paired.neither_correct}</Cell>
          </tr>
        </Table>
        <p style={{ marginTop: "var(--sp-04)", color: "var(--text-02)" }}>
          {paired.discordant_pairs} questions separated the arms, and the tool arm was
          right on {paired.tools_only.length} of them: an exact one-sided p of{" "}
          {paired.exact_p_one_sided === null ? "not computed" : paired.exact_p_one_sided}.
        </p>
        <Note>{paired.reading}</Note>
      </Section>

      <Section
        title="How the tool arm spent its calls"
        description="A repeated call is a planning failure and a rejected argument is not, so they are counted apart."
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(11rem, 100%), 1fr))",
            gap: "var(--sp-05)",
          }}
        >
          <Stat label="Tool calls" value={String(tools.tool_calls)} />
          <Stat label="Refused as repeats" value={String(tools.repeated_calls)} />
          <Stat label="Refused for arguments" value={String(tools.server_refusals)} />
          <Stat label="Hit the step cap" value={String(tools.hit_the_step_cap)} />
          <Stat
            label="Fetched the answer"
            value={`${tools.fetched_the_answer.successes} / ${tools.fetched_the_answer.trials}`}
            detail={fmt(tools.fetched_the_answer.rate, 3)}
          />
        </div>
        <Note>{tools.reading}</Note>
      </Section>

      <Section
        title="Every question, both answers"
        description="The expected answer is derived from the files this console ships, by a different code path than the tools use."
      >
        <Table
          head={["Question", "Expected", "With tools", "No tools", "Calls"]}
          headAlign={["left", "left", "left", "left", "right"]}
        >
          {agent.questions.map((row) => (
            <tr key={row.task_id}>
              <Cell align="left">{row.question}</Cell>
              <Cell align="left" mono>
                {row.expected}
              </Cell>
              <Cell align="left">
                <Verdict correct={row.tools_correct}>
                  {row.tools_answer ?? "no answer"}
                </Verdict>
                {!row.tools_correct ? (
                  <span style={{ color: "var(--text-03)" }}>
                    {row.tools_fetched_the_answer
                      ? " had it and chose another field"
                      : " never fetched it"}
                  </span>
                ) : null}
              </Cell>
              <Cell align="left">
                <Verdict correct={row.control_correct}>
                  {row.control_answer ?? "no answer"}
                </Verdict>
                {!row.control_grounded ? (
                  <span style={{ color: "var(--text-03)" }}> invented a number</span>
                ) : null}
              </Cell>
              <Cell>{row.tools_calls}</Cell>
            </tr>
          ))}
        </Table>
      </Section>

      {/* The tool layer was one clause on /start: "two MCP servers answer 12 tools". A
          reader could not see what the twelve are, and the tool arm above is scored on
          five of them. Read out of each server's own TOOLS dict by
          scripts/build_console_data.py, so this is the catalogue a client receives from
          `tools/list` rather than a description of it that could go stale alone. */}
      <Section
        id="tools"
        title="The tool layer"
        description={`${toolCount} tools across ${mcp.servers.length} MCP servers. One reads the receipts this console ships; the other measures a pass from the network while you wait.`}
      >
        {mcp.servers.map((server) => (
          <div key={server.server} style={{ marginBottom: "var(--sp-06)" }}>
            <div
              style={{
                display: "flex",
                gap: "var(--sp-04)",
                alignItems: "baseline",
                flexWrap: "wrap",
                marginBottom: "var(--sp-04)",
              }}
            >
              <span className="num" style={{ color: "var(--text-01)" }}>
                {server.server}
              </span>
              <span
                style={{ fontSize: "var(--type-caption)", color: "var(--text-03)" }}
              >
                {server.module}
              </span>
            </div>
            <div className="tool-grid">
              {server.tools.map((tool) => (
                <div key={tool.name} className="tool-card">
                  <p className="tool-card-name">{tool.name}</p>
                  <p className="tool-card-body">{tool.description}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </Section>

      <Section title="What this does not measure">
        <ul style={{ maxWidth: "62ch", color: "var(--text-02)" }}>
          {agent.what_this_does_not_measure.map((line) => (
            <li key={line} style={{ marginBottom: "var(--sp-03)" }}>
              {line}
            </li>
          ))}
        </ul>
      </Section>
    </main>
  );
}
