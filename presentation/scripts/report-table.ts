/**
 * Regenerate the claim table in REPORT.md from src/data.ts.
 *
 * The report says the table was generated rather than typed, and for two revisions of
 * this film that was true of a command nobody had written down. A claim about how a
 * document was produced is only checkable if the producer is in the tree, so this is
 * it. It rewrites the region between the two markers in place and leaves the rest of
 * the file alone.
 *
 *   npx vite-node scripts/report-table.ts            rewrite the region
 *   npx vite-node scripts/report-table.ts --check    exit 1 if it would change
 *
 * The count sentence above the table is generated too, because it is the sentence most
 * likely to go stale: it names how many claims are read for a cross-check rather than
 * shown, and that number moves every time a beat is added.
 */

import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { ALL_CLAIMS } from "../src/data";

const REPORT = join(__dirname, "..", "REPORT.md");
const OPEN = "<!-- claim-table:start -->";
const CLOSE = "<!-- claim-table:end -->";

/** A cell that will not break the pipe table around it. */
const cell = (text: string): string => text.replace(/\|/g, "\\|").replace(/\n/g, " ");

const table = (): string => {
  const lines = ["| Shown as | Value | File | Key |", "|---|---|---|---|"];
  for (const [name, claim] of Object.entries(ALL_CLAIMS)) {
    lines.push(
      `| ${cell(name)} | \`${cell(claim.display)}\` | ${cell(claim.file)} | \`${cell(
        claim.path,
      )}\` |`,
    );
  }
  return lines.join("\n");
};

/**
 * How many claims are read for a cross-check and never drawn.
 *
 * A claim reaches the screen through its `display` string, so a beat that never names
 * `<claim>.display` never shows it. Counting rather than asserting, because the number
 * moves whenever a beat is added and a stale count in a report about staleness would be
 * the joke writing itself.
 */
const notDisplayed = (): number => {
  const dir = join(__dirname, "..", "src", "beats");
  const source = readdirSync(dir)
    .filter((name) => name.endsWith(".tsx"))
    .map((name) => readFileSync(join(dir, name), "utf-8"))
    .join("\n");
  return Object.keys(ALL_CLAIMS).filter((name) => {
    const leaf = name.split(".").pop() as string;
    return !source.includes(`${leaf}.display`) && !source.includes(`${leaf}.value`);
  }).length;
};

const lead = (): string =>
  `The film holds ${Object.keys(ALL_CLAIMS).length} claims. ${notDisplayed()} of them ` +
  "are read and never drawn: they are there because the test uses them for cross-checks, " +
  "such as the receipts' own sentences in `lift.statement` and `gate3Result.question`, " +
  "`physics.dopplerVerdict`, which proves the chosen observation is one gate 3 could be " +
  "asked of, and `reviewQueue.criteria.N.firedInCorpus`, the corpus-wide count the " +
  "in-budget count is read against.";

const region = (): string => `${OPEN}\n\n${lead()}\n\n${table()}\n\n${CLOSE}`;

const current = readFileSync(REPORT, "utf-8");
const start = current.indexOf(OPEN);
const end = current.indexOf(CLOSE);
if (start === -1 || end === -1) {
  throw new Error(
    `REPORT.md has no ${OPEN} / ${CLOSE} pair, so there is nothing to rewrite`,
  );
}

const next = current.slice(0, start) + region() + current.slice(end + CLOSE.length);

if (process.argv.includes("--check")) {
  if (next !== current) {
    console.error(
      "REPORT.md's claim table is not what src/data.ts produces. Run: npm run report",
    );
    process.exit(1);
  }
  console.log(`REPORT.md matches src/data.ts (${Object.keys(ALL_CLAIMS).length} claims)`);
} else if (next === current) {
  console.log(`REPORT.md already matches (${Object.keys(ALL_CLAIMS).length} claims)`);
} else {
  writeFileSync(REPORT, next, { encoding: "utf-8" });
  console.log(`REPORT.md rewritten (${Object.keys(ALL_CLAIMS).length} claims)`);
}
