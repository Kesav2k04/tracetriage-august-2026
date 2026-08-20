/**
 * Column headers must sit on the same side as the cells beneath them.
 *
 * `Table` defaults to first column left and the rest right, which is correct for a
 * table of figures and wrong for a table whose last column is a sentence. Fifteen
 * headers across four pages had drifted onto the wrong edge: "What it means" on the
 * home page sat 1257px from its own content, "What the console shows" on the
 * provenance page 1008px, "Why it is here" in the queue 386px. The `headAlign` prop
 * existed and its doc comment described exactly this bug, and sixteen of twenty-one
 * call sites did not pass it.
 *
 * Nothing already in the suite could catch it. `tsc` is happy with a missing optional
 * prop, `next build` renders it fine, and the arithmetic tests never touch a page.
 * This reads the sources, pairs each `head={[...]}` with the `<Cell>` alignments in
 * the first row of its body, and requires them to agree.
 *
 * A `<Cell align="left">` whose contents are laid out flush right, which the Brier
 * bar does, is declared in `KNOWN_VISUALLY_RIGHT` with its reason rather than left to
 * make this test look wrong.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "..");

/**
 * Cells that declare `align="left"` and paint their contents against the right edge.
 * Each entry is a file, the 0-based column, and why. The list is short on purpose: a
 * growing one means the component's alignment prop is being worked around.
 */
const KNOWN_VISUALLY_RIGHT: Array<{ file: string; column: number; why: string }> = [
  {
    file: "app/evaluation/page.tsx",
    column: 2,
    why:
      "The Brier column is a bar and a number in a flex row with justifyContent " +
      "flex-end, so the cell is declared left and reads right.",
  },
];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (entry.endsWith(".tsx")) out.push(full);
  }
  return out;
}

type TableCall = {
  file: string;
  line: number;
  columns: string[];
  headAlign: string[] | null;
  cells: string[];
};

/**
 * Every `<Table>` in the app, with its declared headers and the alignment of the
 * cells in the first row of its body.
 *
 * A row built by a helper function rather than inline has no cells here, so it is
 * reported with an empty cell list and skipped rather than passing silently: the
 * assertion below states which tables it actually checked.
 */
function tableCalls(): TableCall[] {
  const out: TableCall[] = [];
  for (const file of walk(ROOT)) {
    if (file.includes(`${path.sep}tests${path.sep}`)) continue;
    const source = readFileSync(file, "utf8");
    let from = 0;
    for (;;) {
      const at = source.indexOf("<Table", from);
      if (at === -1) break;
      from = at + 6;
      // Bound the window at this table's own closing tag. A fixed-width slice runs
      // into the next <Table> and reads its headAlign, which made two correct call
      // sites look like they declared the wrong number of columns.
      const closes = source.indexOf("</Table>", at);
      const segment = source.slice(at, closes === -1 ? at + 4000 : closes);
      const head = /head=\{\[(.*?)\]\}/s.exec(segment);
      if (!head) continue;
      const columns = [...(head[1] ?? "").matchAll(/"([^"]*)"/g)].map((m) => m[1] ?? "");
      const alignMatch = /headAlign=\{\[(.*?)\]\}/s.exec(segment);
      const headAlign = alignMatch
        ? [...(alignMatch[1] ?? "").matchAll(/"([^"]*)"/g)].map((m) => m[1] ?? "")
        : null;
      const rowAt = segment.indexOf("<tr");
      const cells: string[] = [];
      if (rowAt !== -1) {
        const rest = segment.slice(rowAt);
        const end = rest.indexOf("</tr>");
        const body = rest.slice(0, end === -1 ? rest.length : end);
        for (const cell of body.matchAll(/<Cell\b([^>]*)>/g)) {
          const attrs = cell[1] ?? "";
          if (attrs.includes('align="left"')) cells.push("left");
          else if (attrs.includes('align="right"')) cells.push("right");
          else cells.push("right"); // the component's default, mono included
        }
      }
      out.push({
        file: path.relative(ROOT, file).split(path.sep).join("/"),
        line: source.slice(0, at).split("\n").length,
        columns,
        headAlign,
        cells,
      });
    }
  }
  return out;
}

describe("table column alignment", () => {
  const calls = tableCalls();

  it("finds every Table in the app", () => {
    expect(calls.length).toBeGreaterThanOrEqual(20);
  });

  it("puts each header on the same edge as its own cells", () => {
    const mismatches: string[] = [];
    let checked = 0;
    for (const call of calls) {
      if (call.cells.length === 0) continue;
      for (let column = 0; column < call.columns.length; column += 1) {
        const cell = call.cells[column];
        if (cell === undefined) continue;
        const declared = call.headAlign?.[column] ?? (column === 0 ? "left" : "right");
        const exempt = KNOWN_VISUALLY_RIGHT.some(
          (row) => row.file === call.file && row.column === column,
        );
        checked += 1;
        if (exempt || declared === cell) continue;
        mismatches.push(
          `${call.file}:${call.line} column ${column} "${call.columns[column]}" ` +
            `header is ${declared} and its cells are ${cell}`,
        );
      }
    }
    expect(checked).toBeGreaterThan(60);
    expect(mismatches).toEqual([]);
  });

  it("declares an alignment for every column it declares a header for", () => {
    const short = calls
      .filter((call) => call.headAlign && call.headAlign.length !== call.columns.length)
      .map(
        (call) =>
          `${call.file}:${call.line} has ${call.columns.length} headers and ` +
          `${call.headAlign?.length} alignments`,
      );
    expect(short).toEqual([]);
  });

  it("keeps every alignment exemption attached to a reason", () => {
    for (const row of KNOWN_VISUALLY_RIGHT) {
      expect(row.why.length).toBeGreaterThan(30);
      expect(calls.some((call) => call.file === row.file)).toBe(true);
    }
  });
});
