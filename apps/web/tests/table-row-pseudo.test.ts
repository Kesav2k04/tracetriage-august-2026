/**
 * A generated box may not hang off a table row.
 *
 * The hover rule down the left edge of a queue row was drawn by `main tbody tr::before`
 * with `content: ""` and `position: absolute`. That looks safe and is not. CSS runs table
 * fix-up before it resolves positioning, so a generated box inside a `display: table-row`
 * element is wrapped in an anonymous table-cell first and only then taken out of flow. The
 * anonymous cell still counted, so every `tbody` on the site sat one column to the right of
 * its own `thead`: the queue's "Why it is here" text ran under the "Reason" header and the
 * last column of every table had no header at all.
 *
 * Nothing in the suite could see it. The CSS is valid, `next build` renders it, and
 * `table-alignment.test.ts` compares the `headAlign` prop against the `<Cell>` props in the
 * source, where the two did agree. The defect only exists in the rendered box tree.
 *
 * The fix was to move the pseudo-element onto the row's first cell, where a generated box is
 * already inside a cell and needs no anonymous one. This test pins that: no rule in the
 * stylesheet may attach `::before` or `::after` directly to a `tr`.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const CSS = path.join(process.cwd(), "app", "globals.css");

/** `tr::before`, `tr:hover::after`, and the legacy single-colon spellings of both. */
const ROW_PSEUDO = /(^|[\s>+~,])tr(:(?!:)[a-z-]+(\([^)]*\))?)*\s*::?(before|after)\b/i;

/** Strip `/* ... *\/` so a selector quoted inside a comment cannot fail the test. */
function withoutComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Selector list and declaration body of every rule, flattened across at-rule nesting. */
function rules(css: string): Array<{ selector: string; body: string }> {
  const out: Array<{ selector: string; body: string }> = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css)) !== null) {
    const selector = (m[1] ?? "").trim().replace(/\s+/g, " ");
    if (selector.startsWith("@")) continue;
    out.push({ selector, body: m[2] ?? "" });
  }
  return out;
}

describe("table rows carry no generated box", () => {
  const css = withoutComments(readFileSync(CSS, "utf8"));
  const all = rules(css);

  it("finds rules to check", () => {
    expect(all.length).toBeGreaterThan(50);
  });

  it("declares no content on a tr pseudo-element", () => {
    const offenders = all
      .filter(({ body }) => /(^|[;{\s])content\s*:/.test(body))
      .flatMap(({ selector }) => selector.split(","))
      .map((s) => s.trim())
      .filter((s) => ROW_PSEUDO.test(s));
    expect(offenders).toEqual([]);
  });

  it("recognises the shape it is guarding against", () => {
    expect(ROW_PSEUDO.test("main tbody tr::before")).toBe(true);
    expect(ROW_PSEUDO.test("main tbody tr:hover::after")).toBe(true);
    expect(ROW_PSEUDO.test("tr:before")).toBe(true);
    // The shipped fix, and anything else that puts the box inside a cell, is fine.
    expect(ROW_PSEUDO.test("main tbody tr > *:first-child::before")).toBe(false);
    expect(ROW_PSEUDO.test("main tbody tr:hover > *:first-child::before")).toBe(false);
    expect(ROW_PSEUDO.test("main tbody td::before")).toBe(false);
  });
});
