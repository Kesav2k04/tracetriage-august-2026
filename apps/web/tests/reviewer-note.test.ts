/**
 * The caption under a reviewer note, and the note file the console ships.
 *
 * The caption is the only place the console tells a reader whether the sentence above it
 * was written by a model or assembled from a template. Getting that wrong in either
 * direction is worse than having no note: a template presented as generated oversells, and
 * a generated sentence presented as a template hides the thing worth knowing. So every
 * branch is pinned, including the two that say nothing was generated, because those are
 * the ones a reader would otherwise mistake for a refusal.
 *
 * The file itself is checked here too. A note whose source says generated while its
 * refusal codes are populated is a contradiction no type can catch, and it is exactly what
 * a mistake in the publisher's branching would produce.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { modelLabel, noteCaption } from "../components/ReviewerNote";

interface NoteRecord {
  obs_id: number;
  note: string;
  source: "generated" | "deterministic";
  refused_codes: string[];
  why: string | null;
}

const notesFile = JSON.parse(
  readFileSync(join(__dirname, "..", "public", "data", "notes.json"), "utf8"),
) as {
  model: {
    name: string;
    digest: string;
    parameter_size: string;
    quantization: string;
    context_length: number;
  } | null;
  prompt_version: string;
  notes: NoteRecord[];
};

const record = (over: Partial<NoteRecord> = {}): NoteRecord => ({
  obs_id: 1,
  note: "text",
  source: "deterministic",
  refused_codes: [],
  why: null,
  ...over,
});

describe("modelLabel", () => {
  it("names the weights and how they were quantised", () => {
    expect(
      modelLabel({
        name: "granite3.1-dense:8b",
        digest: "a".repeat(64),
        parameter_size: "8.2B",
        quantization: "Q4_K_M",
        context_length: 131072,
      }),
    ).toBe("granite3.1-dense:8b (8.2B, Q4_K_M)");
  });

  it("says so when there is no model rather than rendering an empty bracket", () => {
    expect(modelLabel(null)).toBe("no model recorded");
  });

  it("drops empty detail fields instead of printing separators for them", () => {
    expect(
      modelLabel({
        name: "m",
        digest: "",
        parameter_size: "",
        quantization: "",
        context_length: 0,
      }),
    ).toBe("m");
  });
});

describe("noteCaption", () => {
  const model = {
    name: "granite3.1-dense:8b",
    digest: "a".repeat(64),
    parameter_size: "8.2B",
    quantization: "Q4_K_M",
    context_length: 131072,
  };

  it("names the model and the check for an accepted draft", () => {
    const caption = noteCaption(record({ source: "generated" }), model);
    expect(caption).toContain("granite3.1-dense:8b");
    expect(caption).toContain("grounding checker");
  });

  it("names every refusal code, so a two-code refusal is not reported as one", () => {
    const caption = noteCaption(
      record({ why: "GROUNDING_CHECK_REFUSED", refused_codes: ["A", "B"] }),
      model,
    );
    expect(caption).toContain("A, B");
    expect(caption).toContain("deterministic summary");
  });

  it("distinguishes nothing generated from something refused", () => {
    const absent = noteCaption(record({ why: "MODEL_RUNTIME_UNAVAILABLE" }), model);
    expect(absent).toContain("Nothing was refused");
    const refused = noteCaption(
      record({ why: "GROUNDING_CHECK_REFUSED", refused_codes: ["X"] }),
      model,
    );
    expect(refused).not.toContain("Nothing was refused");
    expect(absent).not.toEqual(refused);
  });

  it("says a stale draft was retired rather than judged", () => {
    expect(noteCaption(record({ why: "FROZEN_DRAFT_IS_STALE" }), model)).toContain(
      "retired",
    );
  });

  it("never claims a model wrote a deterministic note", () => {
    for (const why of [
      "GROUNDING_CHECK_REFUSED",
      "MODEL_RUNTIME_UNAVAILABLE",
      "NO_FROZEN_DRAFT",
      "FROZEN_DRAFT_IS_STALE",
      null,
    ]) {
      const caption = noteCaption(record({ why, refused_codes: ["X"] }), model);
      expect(caption).not.toContain("Written by");
    }
  });
});

describe("the note file the console ships", () => {
  it("carries a note per observation and none of them is empty", () => {
    expect(notesFile.notes.length).toBeGreaterThan(0);
    for (const note of notesFile.notes) {
      expect(note.note.trim().length).toBeGreaterThan(40);
      expect(Number.isInteger(note.obs_id)).toBe(true);
    }
  });

  it("never marks a note generated while also recording a refusal", () => {
    for (const note of notesFile.notes) {
      if (note.source === "generated") {
        expect(note.refused_codes).toEqual([]);
        expect(note.why).toBeNull();
      } else {
        expect(note.why).not.toBeNull();
      }
    }
  });

  it("records the model when any note is generated", () => {
    const anyGenerated = notesFile.notes.some((n) => n.source === "generated");
    if (anyGenerated) {
      expect(notesFile.model).not.toBeNull();
      expect(notesFile.model?.digest).toHaveLength(64);
    }
    expect(notesFile.prompt_version).toMatch(/^e\d+\.\d+$/);
  });

  it("has both kinds present, so neither branch of the console is dead code", () => {
    const sources = new Set(notesFile.notes.map((n) => n.source));
    expect(sources.has("deterministic")).toBe(true);
    expect(sources.has("generated")).toBe(true);
  });
});
