/**
 * A number on screen, and the receipt key it was read from.
 *
 * The path is not a comment. `read()` resolves it against the parsed receipt, so a
 * renamed key fails the render instead of quietly leaving a stale figure in an mp4.
 * test/claims.test.ts re-reads every file named here from disk, walks every path
 * again, and checks both the value and the string the film prints.
 */

export type Claim<T> = {
  readonly file: string;
  readonly path: string;
  readonly value: T;
  readonly display: string;
};

/** Resolve a dotted path with optional array indices: `a.b[0].c`. */
export function resolve(root: unknown, path: string): unknown {
  let node: unknown = root;
  const steps = path
    .replace(/\[(\d+)\]/g, ".$1")
    .split(".")
    .filter((s) => s.length > 0);
  for (const step of steps) {
    if (node === null || typeof node !== "object") {
      throw new Error(`path "${path}" ran out of object at "${step}"`);
    }
    node = (node as Record<string, unknown>)[step];
    if (node === undefined) {
      throw new Error(`path "${path}" has no key "${step}"`);
    }
  }
  return node;
}

/**
 * Read one value out of a receipt and pin the string the film will print beside it.
 *
 * `format` receives the value the path resolved to, so the display can never be
 * typed independently of the measurement.
 */
export function read<T>(
  receipt: unknown,
  file: string,
  path: string,
  format: (value: T) => string,
): Claim<T> {
  const value = resolve(receipt, path) as T;
  return { file, path, value, display: format(value) };
}

// ---------------------------------------------------------------------------
// Formatters. Deterministic on purpose: toLocaleString depends on the ICU data
// the runtime shipped with, and a film and its test have to agree.
// ---------------------------------------------------------------------------

/** Thousands-grouped integer: 2727 becomes "2,727". */
export const group = (n: number): string => {
  const negative = n < 0;
  const digits = Math.round(Math.abs(n)).toString();
  let out = "";
  for (let i = 0; i < digits.length; i += 1) {
    if (i > 0 && (digits.length - i) % 3 === 0) out += ",";
    out += digits[i];
  }
  return (negative ? "-" : "") + out;
};

/** Grouped integer with an explicit sign: 13985 becomes "+13,985". */
export const signedGroup = (n: number): string =>
  (n < 0 ? "-" : "+") + group(Math.abs(n));

export const fixed =
  (places: number) =>
  (n: number): string =>
    n.toFixed(places);

export const signedFixed =
  (places: number) =>
  (n: number): string =>
    (n < 0 ? "-" : "+") + Math.abs(n).toFixed(places);

export const identity = (s: string): string => s;

/**
 * A catalogue number, printed without thousands separators. NORAD 63214 is a name,
 * not a count, and grouping it into "63,214" says it is a quantity.
 */
export const identifier = (n: number): string => String(n);

/** The first sentence of a receipt note, for the ones written to be quoted. */
export const firstSentence = (s: string): string => {
  const stop = s.indexOf(". ");
  return stop === -1 ? s : s.slice(0, stop + 1);
};
