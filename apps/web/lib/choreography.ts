/**
 * The arithmetic behind the scroll choreography, kept out of the browser so it can be tested.
 *
 * Every animated number on this console is a number a receipt already fixed. That makes the
 * counting animation a place where a display can quietly disagree with its own evidence: a
 * tween that overshoots shows a lift the measurement does not support, and one that rounds
 * on the way past shows a precision the measurement does not have. Both are wrong in the
 * direction that flatters the project, which is the direction that matters.
 *
 * So the rules here are stricter than an easing curve needs to be:
 *
 * A counter never displays a value above its target. Not for one frame.
 * A counter displays exactly the digits its target was printed with, at every step.
 * A counter lands on the target string itself, not on a rounding of it.
 *
 * The functions are pure and the component in components/SmoothScroll.tsx is the only caller.
 */

export type CounterTarget = {
  /** The numeric value the receipt holds. */
  value: number;
  /** How many digits after the point the page printed, which the counter must not exceed. */
  decimals: number;
  /** The exact string the page rendered, which the counter must finish on. */
  text: string;
};

/**
 * Read a counter's target out of the text a server render already produced.
 *
 * The page is the source of truth, not a second copy of the data: the markup was generated
 * from the receipt, so parsing it back cannot drift from the receipt. Anything that is not a
 * plain decimal number returns null and is left alone, which covers intervals, ratios written
 * with a solidus, and any value where counting would be meaningless.
 */
export function parseCounterTarget(raw: string): CounterTarget | null {
  const text = raw.trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) return null;
  const value = Number(text);
  if (!Number.isFinite(value)) return null;
  const point = text.indexOf(".");
  const decimals = point === -1 ? 0 : text.length - point - 1;
  return { value, decimals, text };
}

/**
 * The string to show at a given progress through the count.
 *
 * Clamped at both ends, and the last frame returns the target's own text rather than a
 * reformat of it, so the value the reader is left looking at is the value the page rendered.
 */
export function counterFrame(target: CounterTarget, progress: number): string {
  if (!(progress > 0)) return (0).toFixed(target.decimals);
  if (progress >= 1) return target.text;
  const shown = target.value * progress;
  // Truncate rather than round. Rounding can carry a frame above the target near the end,
  // and above the target is the one place a number on this page may never be.
  const scale = 10 ** target.decimals;
  const truncated = Math.trunc(Math.abs(shown) * scale) / scale;
  const signed = target.value < 0 ? -truncated : truncated;
  return signed.toFixed(target.decimals);
}

/**
 * Entrance delays for a group that must arrive in a stated order.
 *
 * This is the one thing a CSS `view()` timeline cannot express here. `view()` gives each
 * element its own timeline against its own visibility, so a row of four tiles that all cross
 * the threshold in the same frame all animate in the same frame, and at a desktop width they
 * always do. The reading order is left to right and the arrival order should match it.
 */
export function staggerDelays(count: number, step: number): number[] {
  if (!Number.isFinite(step) || step < 0) throw new RangeError("step must be >= 0");
  return Array.from({ length: Math.max(0, count) }, (_, i) => Number((i * step).toFixed(4)));
}

/**
 * Total time a stagger occupies, which is what decides whether it is still a reveal.
 *
 * Past about a second the reader has stopped reading the group as one thing and started
 * waiting for it, so the caller asserts against this rather than guessing a step.
 */
export function staggerSpan(count: number, step: number, duration: number): number {
  if (count <= 0) return 0;
  return Number(((count - 1) * step + duration).toFixed(4));
}
