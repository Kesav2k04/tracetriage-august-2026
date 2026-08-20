/**
 * Formatting and colour, with nothing behind them.
 *
 * Same reason lib/queue-view.ts exists. components/ui.tsx is imported by a
 * client component, so anything it imports joins the client bundle; when these
 * three helpers lived in lib/data they dragged all four receipt files across the
 * boundary with them. A module in the client graph must not touch server data.
 */

export type Verdict = "PASSED" | "NOT_ESTABLISHED" | "FAILED" | "NOT_MEASURABLE";

export function verdictColour(verdict: Verdict | string): string {
  switch (verdict) {
    case "PASSED":
      return "var(--verdict-passed)";
    // A pre-passed feasibility gate is decided and is counted as met by
    // `provenance.json`'s own gate_summary, so it takes the passed ink. Leaving it
    // on the default branch drew a met gate in the grey reserved for one that could
    // not be measured, which is the opposite of what happened to it.
    case "PRE_PASSED":
      return "var(--verdict-passed)";
    // A study that was never run is named explicitly rather than left to the
    // default, so that adding a fifth state later cannot silently absorb it.
    case "OPEN":
      return "var(--verdict-not-measurable)";
    case "NOT_ESTABLISHED":
      return "var(--verdict-not-established)";
    case "FAILED":
      return "var(--verdict-failed)";
    default:
      return "var(--verdict-not-measurable)";
  }
}

/** Fixed decimals with a phrase, not a dash, for a genuinely absent value. */
export function fmt(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "not measured";
  }
  return value.toFixed(digits);
}

export function fmtInterval(
  interval: [number, number] | null | undefined,
  digits = 3,
): string {
  if (!interval) return "not measured";
  return `[${interval[0].toFixed(digits)}, ${interval[1].toFixed(digits)}]`;
}
