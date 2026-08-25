/**
 * The corridor clip's on-page prose must agree with the card it describes.
 *
 * The landing page states six measured figures about observation 14745984 in three
 * places: the video's `aria-label`, the fallback paragraph a browser without the codec
 * shows, and the `figcaption`. All six are typed, not read from `@/lib/data`, because the
 * sentence is prose about a specific frame rather than a table cell. Every one of them is
 * correct today and nothing would notice if it stopped being.
 *
 * `scripts/gate.py` already holds the spoken track to a higher standard: every number in
 * the narration is read out of the scene file that draws it, and a second model
 * transcribed the audio without seeing the script. That gate does not look at the page.
 * This does, and it reads `cards.json` rather than a copy of the numbers, so a rebuilt
 * snapshot that moves the fit fails here instead of shipping a caption that disagrees
 * with the card one click away.
 *
 * The offset is signed in the receipt and unsigned in the prose, which is correct: the
 * sentence says "a shift of 61 pixels" and the direction is what the video shows.
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const OBS_ID = 14745984;
const PAGE = path.join(process.cwd(), "app", "page.tsx");
const CARDS = path.join(process.cwd(), "public", "data", "cards.json");

type Card = {
  obs_id: number;
  width: number;
  hz_per_px: number;
  corridor: { fitted_offset_hz: number; fitted_offset_ppm: number };
};

function card(): Card {
  const all = JSON.parse(readFileSync(CARDS, "utf8")) as { cards: Card[] };
  const found = all.cards.find((c) => c.obs_id === OBS_ID);
  if (!found) {
    throw new Error(
      `cards.json no longer ships observation ${OBS_ID}, which the landing page names ` +
        `in three places. Either restore it or rewrite the corridor figure's prose.`,
    );
  }
  return found;
}

/** How many times a string appears in the page source. */
function occurrences(source: string, needle: string): number {
  return source.split(needle).length - 1;
}

describe("the corridor clip's caption matches its card", () => {
  const source = readFileSync(PAGE, "utf8");
  const c = card();
  const offsetHz = Math.abs(c.corridor.fitted_offset_hz);
  const offsetPpm = Math.abs(c.corridor.fitted_offset_ppm);
  const offsetPx = offsetHz / c.hz_per_px;

  it("states the observation id in all three places", () => {
    expect(occurrences(source, String(OBS_ID))).toBe(3);
  });

  it("states the pixel shift the fit implies", () => {
    // The prose rounds to a whole pixel, which is the unit the reader sees on the frame.
    // Counted rather than merely found: a partial edit that fixed two of the three
    // places would leave the page contradicting itself, which is worse than stale.
    expect(Math.round(offsetPx)).toBe(61);
    expect(occurrences(source, "61 pixels")).toBe(3);
    expect(source).toContain("61 pixel shift");
  });

  it("states the offset in hertz, grouped as the rest of the console groups", () => {
    const grouped = Math.round(offsetHz).toLocaleString("en-GB");
    expect(grouped).toBe("5,648");
    expect(occurrences(source, `${grouped} hertz`)).toBe(1);
    expect(occurrences(source, `${grouped} Hz`)).toBe(2);
  });

  it("states the offset in parts per million to one decimal", () => {
    const ppm = offsetPpm.toFixed(1);
    expect(ppm).toBe("13.0");
    expect(occurrences(source, `${ppm} parts per million`)).toBe(1);
    expect(occurrences(source, `${ppm} ppm`)).toBe(2);
  });

  it("states the hertz per pixel the two figures divide by", () => {
    const perPx = c.hz_per_px.toFixed(1);
    expect(perPx).toBe("92.6");
    expect(occurrences(source, `${perPx} hertz per pixel`)).toBe(1);
    expect(occurrences(source, `${perPx} Hz per pixel`)).toBe(1);
  });

  it("states the image width the shift is small against", () => {
    expect(c.width).toBe(620);
    expect(source).toContain(`${c.width}\n            pixel image`);
  });
});
