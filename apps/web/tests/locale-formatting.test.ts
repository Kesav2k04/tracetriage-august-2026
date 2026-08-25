/**
 * Every locale-sensitive formatter must name its locale.
 *
 * The rule is already written down twice in this repository, at
 * `components/LiveConsole.tsx:114`. What was
 * missing was anything that enforced it.
 *
 * `apps/web/app/evaluation/page.tsx` called `bytes.toLocaleString()` with no
 * argument, in a server component, so the builder's ICU locale decided a published
 * figure. The deployed page said `113,238,991 B`. The same commit built on a machine
 * set to en-IN said `11,32,38,991 B`, which is lakh grouping, and a de-DE builder
 * would have said `113.238.991`. Three more sites in `components/OffsetSweep.tsx`
 * had the same shape and were latent only because every value shipped there is
 * under 100,000, which is where en-IN and en-GB grouping first diverge.
 *
 * Nothing else in the suite can see this. `tsc` accepts the zero-argument overload,
 * `next build` renders it, and the arithmetic tests never touch a page. So this
 * reads the sources and requires a first argument on every call.
 *
 * The console standardises on "en-GB". Four call sites already passed it and
 * `components/PassReplay.tsx` builds a pinned `Intl.NumberFormat("en-GB")`, so
 * "en-GB" is what a new site should use rather than a fresh choice.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "..");

/**
 * The methods and constructors whose output changes with the ambient locale. Every
 * one of them takes locales as its first argument, and every one of them falls back
 * to the runtime default when that argument is absent.
 */
const LOCALE_SENSITIVE = [
  "toLocaleString",
  "toLocaleDateString",
  "toLocaleTimeString",
  "Intl.NumberFormat",
  "Intl.DateTimeFormat",
  "Intl.RelativeTimeFormat",
  "Intl.ListFormat",
  "Intl.PluralRules",
  "Intl.Collator",
] as const;

/** Directories that ship. `tests/` is excluded so this file cannot flag itself. */
const SCANNED = ["app", "components", "lib"] as const;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (entry.endsWith(".ts") || entry.endsWith(".tsx")) out.push(full);
  }
  return out;
}

type Call = { file: string; line: number; method: string; locale: string | null };

/**
 * Every locale-sensitive call in the shipped sources, with the locale it named.
 *
 * The locale is read as the text between the opening parenthesis and the first comma
 * or the matching close. A call whose first argument is a variable rather than a
 * literal is reported with that variable's name, which counts as naming a locale:
 * the defect is the empty argument list, not the spelling.
 */
function localeCalls(): Call[] {
  const out: Call[] = [];
  for (const dir of SCANNED) {
    for (const file of walk(path.join(ROOT, dir))) {
      const source = readFileSync(file, "utf8");
      for (const method of LOCALE_SENSITIVE) {
        let from = 0;
        for (;;) {
          const at = source.indexOf(`${method}(`, from);
          if (at === -1) break;
          from = at + method.length + 1;
          // Bound the read at the matching close so a nested call cannot be mistaken
          // for this one's argument, and cap it so an unbalanced file cannot hang.
          let depth = 1;
          let end = from;
          while (end < source.length && depth > 0 && end - from < 400) {
            if (source[end] === "(") depth += 1;
            else if (source[end] === ")") depth -= 1;
            end += 1;
          }
          const args = source.slice(from, end - 1);
          const first = args.split(",")[0]?.trim() ?? "";
          out.push({
            file: path.relative(ROOT, file).split(path.sep).join("/"),
            line: source.slice(0, at).split("\n").length,
            method,
            locale: first === "" ? null : first,
          });
        }
      }
    }
  }
  return out;
}

describe("locale-sensitive formatting", () => {
  it("names a locale at every call site", () => {
    const bare = localeCalls().filter((call) => call.locale === null);
    expect(
      bare.map((call) => `${call.file}:${call.line} ${call.method}() has no locale`),
    ).toEqual([]);
  });

  it("scans a non-empty set of call sites, so a broken walker cannot pass", () => {
    // Without this, a walker that returned nothing would satisfy the assertion above
    // and report the rule as held over zero measurements.
    const calls = localeCalls();
    expect(calls.length).toBeGreaterThan(0);
    expect(new Set(calls.map((call) => call.file)).size).toBeGreaterThan(1);
  });

  it("uses en-GB wherever a literal is passed", () => {
    // The console has one locale. A second literal appearing here means two pages
    // group the same number differently, which is the milder version of the same bug.
    const literals = localeCalls()
      .map((call) => call.locale)
      .filter((locale): locale is string => locale !== null && /^["']/.test(locale))
      .map((locale) => locale.replace(/^["']|["']$/g, ""));
    expect([...new Set(literals)]).toEqual(["en-GB"]);
  });
});
