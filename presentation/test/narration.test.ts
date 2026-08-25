/**
 * The narration track, held to the rule the drawn numbers are held to.
 *
 * `claims.test.ts` re-reads every receipt the film draws from and checks the value and
 * the printed string. This file does the same job for the sound: every figure the
 * narration speaks is re-derived from the claim it came from, and the committed
 * receipt for the rendered audio is checked against the script that produced it.
 *
 * What this file cannot do is listen. Whether the wav says the words is measured by
 * `scripts/render_narration.py`, which transcribes the rendered audio and looks for
 * each figure in what it heard. This file checks that the receipt that reports that
 * measurement belongs to the script currently in the tree, so a passing audio check
 * cannot be inherited by a line somebody edited afterwards.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { BEATS, FILM_FRAMES } from "../src/Film";
import { physics } from "../src/data";
import {
  NARRATED,
  NARRATION,
  say,
  spellInteger,
  speechBudgetSeconds,
} from "../src/narration";
import { FPS, LEAD_IN_SECONDS, TAIL_SECONDS } from "../src/theme";

const REPO = join(__dirname, "..", "..");

type Receipt = {
  renderer: { voice: string; speed: number; licence: string; runs_offline: boolean };
  verifier: { ran: boolean };
  verdict: string;
  totals: {
    beats: number;
    figures_checked: number;
    figures_not_heard: number;
    beats_overrunning_their_card: number;
    film_seconds: number;
  };
  beats: {
    beat: string;
    text: string;
    audio: string;
    seconds: number;
    budget_seconds: number;
    fits: boolean;
    transcript: string;
    figures: { path: string; display: string; spoken: string; found: boolean }[];
  }[];
};

const receipt = (): Receipt =>
  JSON.parse(
    readFileSync(join(REPO, "artifacts", "NARRATION_RECEIPT.json"), "utf8"),
  ) as Receipt;

describe("spellInteger", () => {
  it("spells the forms the script actually produces", () => {
    expect(spellInteger(2727)).toBe("two thousand seven hundred and twenty seven");
    expect(spellInteger(17290)).toBe("seventeen thousand two hundred and ninety");
    expect(spellInteger(13985)).toBe("thirteen thousand nine hundred and eighty five");
    expect(spellInteger(1000)).toBe("one thousand");
    expect(spellInteger(1005)).toBe("one thousand and five");
    expect(spellInteger(100)).toBe("one hundred");
    expect(spellInteger(20)).toBe("twenty");
    expect(spellInteger(0)).toBe("zero");
  });

  it("refuses a value it cannot spell rather than guessing", () => {
    expect(() => spellInteger(1.5)).toThrow();
    expect(() => spellInteger(-1)).toThrow();
    expect(() => spellInteger(1_000_000)).toThrow();
  });
});

describe("the spoken form of a figure", () => {
  it("is derived from the display, so it cannot contradict the card", () => {
    // These four are the reason say() reads the display and not the value. The value
    // behind each is a float or a signed quantity the card's formatter has already
    // decided how to show, and speaking the value would disagree with the screen.
    const spoken = NARRATED.flatMap((beat) => beat.line.claims.map((c) => say(c)));
    expect(spoken).toContain("seventeen thousand two hundred and ninety");
    expect(spoken).toContain("plus thirty two point zero five");
    expect(spoken).toContain("one hundred and thirteen");
    // offsetHz is drawn on the Physics card and not spoken, so it is checked here on
    // the claim rather than in the script. Its value is -13985.xx and its display is
    // the rounded, signed +13,985 the card shows; speaking the value would disagree
    // with the screen in both the sign and the digits.
    expect(say(physics.offsetHz)).toBe(
      "plus thirteen thousand nine hundred and eighty five",
    );
  });

  it("spells every integer of three digits and leaves smaller ones as digits", () => {
    for (const beat of NARRATED) {
      for (const claim of beat.line.claims) {
        const bare = claim.display.replace(/^[+-]/, "");
        if (/^\d{3,}$/.test(bare.replace(/,/g, ""))) {
          expect(say(claim)).toMatch(/[a-z]/);
          expect(say(claim)).not.toContain(",");
        } else if (/^[A-Z][A-Z0-9]*(_[A-Z0-9]+)+$/.test(bare)) {
          expect(say(claim)).toBe(bare.toLowerCase().replace(/_/g, " "));
        } else if (/^\d+\.0\d*$/.test(bare)) {
          // A zero straight after the point is the one the reader drops, so it is
          // spelled. Everything else keeps its digits.
          expect(say(claim)).toMatch(/ point (zero|one|two|three|four|five|six|seven|eight|nine)/);
        } else {
          expect(say(claim).replace(/^(plus|minus) /, "")).toBe(
            bare.includes(".") ? bare.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "") : bare,
          );
        }
      }
    }
  });

  it("never speaks a bare comma, which is the reading that broke", () => {
    for (const beat of NARRATED) {
      const figures = beat.line.claims.map((c) => say(c));
      for (const figure of figures) {
        expect(figure).not.toMatch(/\d,\d/);
      }
    }
  });
});

describe("the script against the film", () => {
  it("has a line for every beat and no line for a beat that does not exist", () => {
    expect(Object.keys(NARRATION).sort()).toEqual(
      BEATS.map((b) => b.name).sort(),
    );
    expect(NARRATED.map((n) => n.name)).toEqual(BEATS.map((b) => b.name));
  });

  it("keeps the pre-registered result before the results that held", () => {
    // The same ordering rule claims.test.ts pins for the cards. A later edit that
    // speaks the wins first fails here rather than passing quietly.
    const order = NARRATED.map((n) => n.name);
    expect(order.indexOf("Result")).toBeLessThan(order.indexOf("Established"));
    expect(order.indexOf("Gates")).toBeLessThan(order.indexOf("Established"));
    expect(NARRATION.Result.text.toLowerCase()).toContain("not established");
  });

  it("leaves every line room inside its own card", () => {
    for (const beat of NARRATED) {
      expect(speechBudgetSeconds(beat)).toBeGreaterThan(0);
      expect(speechBudgetSeconds(beat)).toBeCloseTo(
        beat.durationInFrames / FPS - LEAD_IN_SECONDS - TAIL_SECONDS,
        6,
      );
    }
  });

  it("fits inside the brief's three minute ceiling", () => {
    expect(FILM_FRAMES / FPS).toBeLessThanOrEqual(180);
  });
});

describe("the rendered audio's receipt", () => {
  it("was produced from the script that is in the tree now", () => {
    const rows = new Map(receipt().beats.map((b) => [b.beat, b]));
    for (const beat of NARRATED) {
      const row = rows.get(beat.name);
      expect(row, `${beat.name} has no row in the receipt`).toBeDefined();
      expect(row!.text).toBe(beat.line.text);
      expect(row!.budget_seconds).toBeCloseTo(speechBudgetSeconds(beat), 3);
    }
  });

  it("reports every figure as heard, and says how many it checked", () => {
    const r = receipt();
    const figuresInScript = NARRATED.reduce(
      (n, beat) => n + beat.line.claims.length,
      0,
    );
    expect(r.totals.figures_checked).toBe(figuresInScript);
    expect(r.totals.figures_not_heard).toBe(0);
    expect(r.totals.beats_overrunning_their_card).toBe(0);
    expect(r.verdict).toBe("PASSED");
    expect(r.verifier.ran).toBe(true);
  });

  it("names a spoken figure's receipt path, not just its value", () => {
    for (const row of receipt().beats) {
      for (const figure of row.figures) {
        expect(figure.path.length).toBeGreaterThan(0);
        expect(figure.found).toBe(true);
      }
    }
  });

  it("records a voice that runs offline under a licence a reader can check", () => {
    const r = receipt();
    expect(r.renderer.runs_offline).toBe(true);
    // Both voices this film has shipped are permissive and locally runnable, which is
    // the property that matters: nobody has to take the audio's provenance on trust.
    expect(["Apache-2.0", "MIT"]).toContain(r.renderer.licence);
    expect(r.renderer.voice.length).toBeGreaterThan(0);
  });

  it("agrees with the film's own length", () => {
    expect(receipt().totals.film_seconds).toBeCloseTo(FILM_FRAMES / FPS, 3);
  });
});
