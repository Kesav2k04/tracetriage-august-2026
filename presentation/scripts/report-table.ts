/**
 * Regenerate the claim table in REPORT.md, and write the film's receipt.
 *
 * The report says the table was generated rather than typed, and for two revisions of
 * this film that was true of a command nobody had written down. A claim about how a
 * document was produced is only checkable if the producer is in the tree, so this is
 * it. It rewrites the region between the two markers in place and leaves the rest of
 * the file alone.
 *
 *   npx vite-node scripts/report-table.ts            rewrite the region and the receipt
 *   npx vite-node scripts/report-table.ts --check     exit 1 if either would change
 *
 * The count sentence above the table is generated too, because it is the sentence most
 * likely to go stale: it names how many claims are read for a cross-check rather than
 * shown, and that number moves every time a beat is added.
 *
 * ## Why this also writes artifacts/FILM_RECEIPT.json
 *
 * The film was the one deliverable in this repository with no receipt. Its length, its
 * beat list, how many claims it holds and which artifacts those claims come from were
 * written by hand into REPORT.md, and the rendered file sat committed with nothing
 * comparing it to anything. That is the shape every other measurement here refuses: a
 * number nobody can re-derive, next to a binary nobody can check.
 *
 * So the same pass that regenerates the table writes a receipt naming the composition,
 * every beat with its frames, the claim counts, the artifacts the claims are read from,
 * and the digest and byte count of the rendered film and its poster. Those two digests
 * are audited by `scripts/check_receipt_digests.py`, which is a standing gate, so the
 * committed video is now a file the repository checks rather than one it stores.
 *
 * `generated_at` is excluded from the `--check` comparison. Everything else in the
 * receipt is derived, so a timestamp is the one field that would fail a check for
 * having done nothing.
 */

import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { BEATS, FILM_FRAMES } from "../src/Film";
import { NARRATION } from "../src/narration";
import { ALL_CLAIMS, FILE } from "../src/data";
import { FPS, HEIGHT, WIDTH } from "../src/theme";

const HERE = join(__dirname, "..");
const REPO = join(HERE, "..");
const REPORT = join(HERE, "REPORT.md");
const RECEIPT = join(REPO, "artifacts", "FILM_RECEIPT.json");
const OPEN = "<!-- claim-table:start -->";
const CLOSE = "<!-- claim-table:end -->";

/** Repository-relative, because a receipt naming an absolute path names one machine. */
const RENDER = "presentation/out/tracetriage-film.mp4";
const POSTER = "presentation/out/tracetriage-film-poster.jpg";

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
  const dir = join(HERE, "src", "beats");
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

/** Three decimal places, so 150 frames at 30 fps reads as 5 rather than 5.000000001. */
const round3 = (value: number): number => Math.round(value * 1000) / 1000;

type Rendered = { path: string; bytes: number; sha256: string } | null;

/**
 * The rendered file as it sits. No line-ending normalisation, because git's `text=auto`
 * detects these two as binary and stores them byte for byte, so the working copy is what
 * a clone receives. Absent is a real state of a checkout that has not rendered, and it is
 * recorded as `null` rather than as a digest of nothing.
 */
const rendered = (rel: string): Rendered => {
  const path = join(REPO, rel);
  if (!existsSync(path)) return null;
  const bytes = readFileSync(path);
  return {
    path: rel,
    bytes: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
};

/** Which artifact each claim is read from, and how many come from each. */
const claimsPerFile = (): Record<string, number> => {
  const counts: Record<string, number> = {};
  for (const claim of Object.values(ALL_CLAIMS)) {
    counts[claim.file] = (counts[claim.file] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));
};

const receipt = (): Record<string, unknown> => ({
  schema: "FILM_RECEIPT",
  schema_version: 1,
  generated_at: new Date().toISOString(),
  generated_by: "presentation/scripts/report-table.ts",
  what_this_is:
    "The presentation film, described by the sources that build it. Every field below is " +
    "derived from presentation/src at generation time rather than read from a document, " +
    "so REPORT.md and this receipt cannot disagree about the same film.",
  composition: {
    beats: BEATS.length,
    frames: FILM_FRAMES,
    fps: FPS,
    seconds: round3(FILM_FRAMES / FPS),
    width: WIDTH,
    height: HEIGHT,
    // Derived, and it was the literal `false` for one commit after the narration
    // landed. A receipt whose job is to stop REPORT.md drifting cannot itself hold a
    // typed claim about the film: the mp4 had an AAC stream and this field said it
    // did not. It is now a function of whether every beat has a line to speak.
    audio: BEATS.every((beat) => NARRATION[beat.name] !== undefined),
  },
  beats: BEATS.map((beat) => ({
    name: beat.name,
    frames: beat.durationInFrames,
    seconds: round3(beat.durationInFrames / FPS),
    narration: NARRATION[beat.name]?.text ?? null,
  })),
  claims: {
    total: Object.keys(ALL_CLAIMS).length,
    drawn: Object.keys(ALL_CLAIMS).length - notDisplayed(),
    read_but_not_drawn: notDisplayed(),
    per_file: claimsPerFile(),
    reading:
      "A claim is a value resolved from a key path in one of the files below at build " +
      "time. The ones read and never drawn are cross-checks the test suite uses, not " +
      "figures on screen.",
  },
  reads: Object.values(FILE).slice().sort(),
  render: rendered(RENDER),
  poster: rendered(POSTER),
  what_this_does_not_measure: [
    "Whether the film is any good, or whether a viewer follows it.",
    "Whether the rendered file plays. The digests say the committed bytes are the bytes " +
      "this receipt was written about; presentation/REPORT.md records the container probe.",
    "Whether the numbers are right. They are the receipts' own numbers, and each " +
      "receipt's own study is what establishes them. This receipt establishes only that " +
      "the film reads them rather than restating them.",
  ],
});

const withoutTimestamp = (payload: Record<string, unknown>): string => {
  const { generated_at: _drop, ...rest } = payload;
  return JSON.stringify(rest, null, 1);
};

const current = readFileSync(REPORT, "utf-8");
const start = current.indexOf(OPEN);
const end = current.indexOf(CLOSE);
if (start === -1 || end === -1) {
  throw new Error(
    `REPORT.md has no ${OPEN} / ${CLOSE} pair, so there is nothing to rewrite`,
  );
}

const next = current.slice(0, start) + region() + current.slice(end + CLOSE.length);
const payload = receipt();
const serialised = `${JSON.stringify(payload, null, 1)}\n`;
const claimCount = Object.keys(ALL_CLAIMS).length;

const receiptOnDisk = existsSync(RECEIPT) ? readFileSync(RECEIPT, "utf-8") : null;
const receiptChanged =
  receiptOnDisk === null ||
  withoutTimestamp(JSON.parse(receiptOnDisk)) !== withoutTimestamp(payload);

if (process.argv.includes("--check")) {
  const problems: string[] = [];
  if (next !== current) {
    problems.push("REPORT.md's claim table is not what src/data.ts produces");
  }
  if (receiptChanged) {
    problems.push(
      receiptOnDisk === null
        ? "artifacts/FILM_RECEIPT.json does not exist"
        : "artifacts/FILM_RECEIPT.json is not what presentation/src produces",
    );
  }
  if (problems.length > 0) {
    console.error(`${problems.join("; ")}. Run: npm run report`);
    process.exit(1);
  }
  console.log(
    `REPORT.md and FILM_RECEIPT.json match presentation/src ` +
      `(${claimCount} claims, ${BEATS.length} beats, ${FILM_FRAMES} frames)`,
  );
} else {
  const wrote: string[] = [];
  if (next !== current) {
    writeFileSync(REPORT, next, { encoding: "utf-8" });
    wrote.push("REPORT.md");
  }
  if (receiptChanged) {
    writeFileSync(RECEIPT, serialised, { encoding: "utf-8" });
    wrote.push("artifacts/FILM_RECEIPT.json");
  }
  console.log(
    wrote.length > 0
      ? `${wrote.join(" and ")} rewritten (${claimCount} claims, ${BEATS.length} beats)`
      : `already current (${claimCount} claims, ${BEATS.length} beats)`,
  );
}
