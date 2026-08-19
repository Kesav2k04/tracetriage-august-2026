/**
 * The agent payload the console ships, checked against the summary it was built from.
 *
 * The page reads a per-question join: both arms' answers on one row. That join is the
 * study's design, so if it ever drifts from the arm summaries above it, the page shows
 * a comparison nobody ran. Every number the page displays is asserted here against the
 * rows it was aggregated from, which is the only way a reader's arithmetic and the
 * console's can be the same arithmetic.
 */
import { describe, expect, it } from "vitest";

import { agent } from "@/lib/data";

describe("the agent study payload", () => {
  it("carries one row per question, with unique ids", () => {
    expect(agent.questions).toHaveLength(agent.tasks);
    const ids = new Set(agent.questions.map((row) => row.task_id));
    expect(ids.size).toBe(agent.tasks);
  });

  it("gives every question an expected answer and a question to read", () => {
    for (const row of agent.questions) {
      expect(row.expected.length).toBeGreaterThan(0);
      expect(row.question.length).toBeGreaterThan(10);
    }
  });

  it("has a paired table whose four cells account for every question", () => {
    const { paired } = agent;
    const total =
      paired.both_correct +
      paired.neither_correct +
      paired.tools_only.length +
      paired.control_only.length;
    expect(total).toBe(agent.tasks);
    expect(paired.discordant_pairs).toBe(
      paired.tools_only.length + paired.control_only.length,
    );
  });

  it("reports the same per-arm counts the rows do", () => {
    const toolsCorrect = agent.questions.filter((row) => row.tools_correct).length;
    const controlCorrect = agent.questions.filter((row) => row.control_correct).length;
    expect(agent.arms.tools.correct.successes).toBe(toolsCorrect);
    expect(agent.arms.control.correct.successes).toBe(controlCorrect);
    expect(agent.arms.tools.correct.trials).toBe(agent.tasks);
    expect(agent.arms.control.correct.trials).toBe(agent.tasks);
  });

  it("lists the discordant questions rather than only counting them", () => {
    const toolsOnly = agent.questions
      .filter((row) => row.tools_correct && !row.control_correct)
      .map((row) => row.task_id)
      .sort();
    const controlOnly = agent.questions
      .filter((row) => !row.tools_correct && row.control_correct)
      .map((row) => row.task_id)
      .sort();
    expect([...agent.paired.tools_only].sort()).toEqual(toolsOnly);
    expect([...agent.paired.control_only].sort()).toEqual(controlOnly);
  });

  it("splits the tool arm's wrong answers by whether it ever fetched the value", () => {
    const wrong = agent.questions.filter((row) => !row.tools_correct);
    const named = [
      ...agent.arms.tools.wrong_with_the_answer_in_front_of_it,
      ...agent.arms.tools.wrong_and_never_fetched_it,
    ].sort();
    expect(wrong.map((row) => row.task_id).sort()).toEqual(named);
    for (const id of agent.arms.tools.wrong_with_the_answer_in_front_of_it) {
      expect(
        agent.questions.find((row) => row.task_id === id)?.tools_fetched_the_answer,
      ).toBe(true);
    }
    for (const id of agent.arms.tools.wrong_and_never_fetched_it) {
      expect(
        agent.questions.find((row) => row.task_id === id)?.tools_fetched_the_answer,
      ).toBe(false);
    }
  });

  it("carries a p value exactly when there was something to compare", () => {
    if (agent.paired.discordant_pairs === 0) {
      expect(agent.paired.exact_p_one_sided).toBeNull();
    } else {
      expect(agent.paired.exact_p_one_sided).not.toBeNull();
      expect(agent.paired.exact_p_one_sided!).toBeGreaterThan(0);
      expect(agent.paired.exact_p_one_sided!).toBeLessThanOrEqual(1);
    }
  });

  it("says what it does not measure, in the payload rather than in the page", () => {
    expect(agent.what_this_does_not_measure.length).toBeGreaterThanOrEqual(2);
    for (const line of agent.what_this_does_not_measure) {
      expect(line.length).toBeGreaterThan(40);
    }
  });

  it("names the model and the seed, so a rerun is a comparable rerun", () => {
    expect(agent.model.name).toMatch(/granite/i);
    expect(agent.model.temperature).toBe(0);
    expect(Number.isInteger(agent.model.seed)).toBe(true);
  });

  it("keeps the counts of calls apart from the counts of refusals", () => {
    const tools = agent.arms.tools;
    expect(tools.tool_calls).toBeGreaterThanOrEqual(
      tools.repeated_calls + tools.server_refusals,
    );
    const rowCalls = agent.questions.reduce((sum, row) => sum + row.tools_calls, 0);
    expect(rowCalls).toBe(tools.tool_calls);
  });
});
