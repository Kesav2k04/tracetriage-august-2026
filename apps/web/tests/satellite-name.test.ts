/**
 * The satellite name, from the payload to the cell.
 *
 * The payloads carry `tle0` verbatim, so the name arrives with the line-number marker
 * a three-line element set prescribes: "0 OBJECT E". `satelliteName` drops that marker
 * and nothing else, and three surfaces call it (the queue table, the observation page
 * header and the live console) so a satellite is spelled the same way on all of them.
 *
 * The last block checks the committed payload rather than the helper, because the
 * helper cannot fail on data it never receives: a queue row with no `satellite` field
 * would render "not recorded" in every row and pass every unit test above it.
 */
import { describe, expect, it } from "vitest";

import cards from "../public/data/cards.json";
import queue from "../public/data/queue.json";
import { satelliteName } from "@/lib/format";

describe("satelliteName", () => {
  it("drops the leading TLE line marker", () => {
    expect(satelliteName("0 OBJECT E")).toBe("OBJECT E");
    expect(satelliteName("0 SHINSEI (MS-F2)")).toBe("SHINSEI (MS-F2)");
    expect(satelliteName("0 CUTE-1.7+APD 2")).toBe("CUTE-1.7+APD 2");
  });

  it("leaves a name that carries no marker alone", () => {
    expect(satelliteName("FRONTIERSAT")).toBe("FRONTIERSAT");
    // A name that merely begins with a zero is not a marker: only "0 " is.
    expect(satelliteName("0MEGA")).toBe("0MEGA");
  });

  it("says so rather than rendering an empty cell", () => {
    expect(satelliteName("")).toBe("not recorded");
    expect(satelliteName("   ")).toBe("not recorded");
    expect(satelliteName(null)).toBe("not recorded");
    expect(satelliteName(undefined)).toBe("not recorded");
  });

  it("never returns an empty string for a name that had content", () => {
    // "0" alone would slice to nothing under a naive implementation.
    expect(satelliteName("0")).toBe("0");
  });
});

describe("the committed payloads", () => {
  it("names a satellite on every queue row", () => {
    expect(queue.entries.length).toBeGreaterThan(0);
    const unnamed = queue.entries.filter(
      (entry) => !(entry.satellite ?? "").trim(),
    );
    expect(unnamed.map((entry) => entry.obs_id)).toEqual([]);
  });

  it("names a satellite on every built card", () => {
    const built = cards.cards.filter((card) => !card.degraded);
    expect(built.length).toBeGreaterThan(0);
    const unnamed = built.filter((card) => !(card.satellite ?? "").trim());
    expect(unnamed.map((card) => card.obs_id)).toEqual([]);
  });

  it("renders every published name as something a reader can read", () => {
    for (const entry of queue.entries) {
      const shown = satelliteName(entry.satellite);
      expect(shown).not.toBe("");
      expect(shown).not.toBe("not recorded");
      expect(shown.startsWith("0 ")).toBe(false);
    }
  });
});
