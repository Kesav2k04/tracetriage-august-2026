import { describe, expect, it } from "vitest";

import {
  counterFrame,
  parseCounterTarget,
  staggerDelays,
  staggerSpan,
} from "@/lib/choreography";

/**
 * The counter is the only animation on this console that writes a number, so it is the only
 * one that can make the page disagree with its own receipts. These tests are about that, not
 * about whether the motion looks right.
 */
describe("parseCounterTarget", () => {
  it("keeps the digit count the page printed", () => {
    expect(parseCounterTarget("1.58")).toEqual({ value: 1.58, decimals: 2, text: "1.58" });
    expect(parseCounterTarget("2.250")).toEqual({ value: 2.25, decimals: 3, text: "2.250" });
    expect(parseCounterTarget("407")).toEqual({ value: 407, decimals: 0, text: "407" });
  });

  it("tolerates the whitespace a JSX text node carries", () => {
    expect(parseCounterTarget("\n        1.58\n      ")?.text).toBe("1.58");
  });

  it("declines anything that is not a plain decimal, rather than guessing", () => {
    // An interval, a ratio, an em dash placeholder and a thousands separator all appear on
    // this console, and counting to any of them is meaningless.
    for (const raw of ["[0.88, 2.41]", "1.58x", "—", "2,727", "1.2e3", "", "  "]) {
      expect(parseCounterTarget(raw)).toBeNull();
    }
  });
});

describe("counterFrame", () => {
  const target = parseCounterTarget("1.58")!;

  it("starts at zero with the target's precision", () => {
    expect(counterFrame(target, 0)).toBe("0.00");
    expect(counterFrame(target, -1)).toBe("0.00");
  });

  it("lands on the exact string the page rendered", () => {
    expect(counterFrame(target, 1)).toBe("1.58");
    expect(counterFrame(target, 1.4)).toBe("1.58");
  });

  it("never displays a value above the target, at any progress", () => {
    // The rule that matters. A single frame above 1.58 is a lift the measurement does not
    // support, so this walks the whole range rather than sampling a few points.
    for (let i = 0; i <= 2000; i++) {
      const progress = i / 2000;
      const shown = Number(counterFrame(target, progress));
      expect(shown).toBeLessThanOrEqual(target.value);
    }
  });

  it("never shows more precision than the receipt", () => {
    for (let i = 0; i <= 500; i++) {
      const frame = counterFrame(target, i / 500);
      expect(frame.split(".")[1]?.length ?? 0).toBe(2);
    }
  });

  it("is monotonic, so a count never appears to go backwards", () => {
    let previous = -Infinity;
    for (let i = 0; i <= 1000; i++) {
      const shown = Number(counterFrame(target, i / 1000));
      expect(shown).toBeGreaterThanOrEqual(previous);
      previous = shown;
    }
  });

  it("counts an integer without inventing a decimal point", () => {
    const whole = parseCounterTarget("407")!;
    expect(counterFrame(whole, 0)).toBe("0");
    expect(counterFrame(whole, 0.5)).toBe("203");
    expect(counterFrame(whole, 1)).toBe("407");
  });

  it("handles a negative target without crossing zero the wrong way", () => {
    const negative = parseCounterTarget("-0.42")!;
    expect(counterFrame(negative, 0)).toBe("0.00");
    expect(counterFrame(negative, 1)).toBe("-0.42");
    for (let i = 0; i <= 200; i++) {
      const shown = Number(counterFrame(negative, i / 200));
      expect(shown).toBeGreaterThanOrEqual(negative.value);
      expect(shown).toBeLessThanOrEqual(0);
    }
  });
});

describe("staggerDelays", () => {
  it("is in reading order and starts immediately", () => {
    expect(staggerDelays(4, 0.075)).toEqual([0, 0.075, 0.15, 0.225]);
  });

  it("handles the degenerate counts a data-driven group can produce", () => {
    expect(staggerDelays(0, 0.075)).toEqual([]);
    expect(staggerDelays(1, 0.075)).toEqual([0]);
    expect(staggerDelays(-3, 0.075)).toEqual([]);
  });

  it("refuses a step that would run the sequence backwards", () => {
    expect(() => staggerDelays(3, -0.1)).toThrow(RangeError);
  });

  it("keeps a group's whole arrival inside a second", () => {
    // Past about a second the reader has stopped reading the group as one thing and started
    // waiting for it. These are the values the component uses.
    expect(staggerSpan(4, 0.075, 0.5)).toBeLessThan(1);
    expect(staggerSpan(6, 0.075, 0.5)).toBeLessThan(1);
    expect(staggerSpan(0, 0.075, 0.5)).toBe(0);
  });
});
