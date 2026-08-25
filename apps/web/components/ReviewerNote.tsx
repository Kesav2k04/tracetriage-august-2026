/**
 * The one sentence a reviewer reads before looking at the image, and its provenance.
 *
 * A generated note is only worth showing if the reader can tell it was generated and can
 * tell what stopped it being wrong. So the caption is not decoration: it names the model
 * that wrote the text, or names the codes the checker refused it for and says that what is
 * displayed instead is a template. Both captions are built from the record, so neither can
 * drift from what actually shipped.
 *
 * The refusal case is the interesting one and it is deliberately not hidden. Across the
 * twenty-five cards this console carries, the checker refused most of the drafts, and the
 * dominant reason was the model writing a downlink frequency that was not this
 * observation's. A console that quietly swapped in the template would have concealed the
 * single most useful fact about putting a language model in front of a reviewer.
 */
import type { NoteModel, ReviewerNote as NoteRecord } from "@/lib/data";
import { Note, Section, Tag } from "@/components/ui";

/** Human-readable model line, or an explicit absence. Exported for its unit test. */
export function modelLabel(model: NoteModel | null): string {
  if (!model) return "no model recorded";
  const parts = [model.parameter_size, model.quantization].filter(Boolean);
  return parts.length > 0 ? `${model.name} (${parts.join(", ")})` : model.name;
}

/**
 * The caption under a note, generated from the record.
 *
 * Every branch names its own evidence. "Checked" says what was checked; a refusal says
 * what it was refused for and what is being shown instead; and the two non-refusal
 * fallbacks say why there is no generated text rather than leaving a reader to assume the
 * model was asked and declined.
 */
export function noteCaption(record: NoteRecord, model: NoteModel | null): string {
  if (record.source === "generated") {
    return (
      `Written by ${modelLabel(model)} from this observation's evidence packet, and ` +
      `accepted by the grounding checker: every number in it appears in that packet.`
    );
  }
  if (record.why === "GROUNDING_CHECK_REFUSED") {
    const codes = record.refused_codes.join(", ");
    return (
      `A generated note was refused for ${codes}, so the deterministic summary is what ` +
      `is shown. The refusal is the measurement, not a fallback that failed quietly.`
    );
  }
  if (record.why === "MODEL_RUNTIME_UNAVAILABLE" || record.why === "NO_FROZEN_DRAFT") {
    return (
      `No generated note exists for this observation, so the deterministic summary is ` +
      `what is shown. Nothing was refused; nothing was generated.`
    );
  }
  if (record.why === "FROZEN_DRAFT_IS_STALE") {
    return (
      `A generated note existed and the observation's fields changed underneath it, so it ` +
      `was retired rather than re-checked against facts it was not written from.`
    );
  }
  return `Deterministic summary, assembled from the observation's own fields.`;
}

/**
 * What each grounding-check code means, in words.
 *
 * The codes were rendered bare with the meaning only in a `title` attribute, which is
 * invisible on a touch device, in a screenshot and on a printed page. The code stays
 * because it is the contract `pipeline/tracetriage/explain.py`, `apps/web/lib/grounding.ts`
 * and every receipt share, and a reader matching one to another needs it. The meaning sits
 * beside it rather than behind a hover.
 */
const VIOLATION_MEANING: Record<string, string> = {
  UNGROUNDED_NUMBER: "a number not in the evidence packet",
  UNGROUNDED_ENTITY: "a name or code not in the packet",
  MISLOCATED_TIME_CLAIM: "a time the packet places elsewhere",
  OVERCLAIM: "a claim this system cannot make",
  ABSOLUTE_CLAIM: "stated as certain",
  WRONG_VOICE: "not the reviewer's voice",
  TOO_LONG: "over the length the contract allows",
  TOO_MANY_SENTENCES: "more sentences than the contract allows",
};

export default function ReviewerNote({
  record,
  model,
}: {
  record: NoteRecord | undefined;
  model: NoteModel | null;
}) {
  if (!record) {
    return (
      <Section title="Reviewer note">
        <Note tone="limit">
          This observation has no note record. The card below is the whole evidence.
        </Note>
      </Section>
    );
  }

  const generated = record.source === "generated";
  return (
    <Section title="Reviewer note">
      <div style={{ display: "flex", gap: "var(--sp-03)", flexWrap: "wrap" }}>
        <Tag tone={generated ? "action" : "muted"}>
          {generated ? "generated, checked" : "deterministic"}
        </Tag>
        {record.refused_codes.map((code) => (
          <Tag key={code} tone="neutral" title="grounding check violation code">
            {code}
            {VIOLATION_MEANING[code] ? ` · ${VIOLATION_MEANING[code]}` : ""}
          </Tag>
        ))}
      </div>
      <p
        style={{
          margin: "var(--sp-05) 0 0",
          fontSize: "var(--type-body)",
          lineHeight: 1.65,
          maxWidth: "52rem",
          color: "var(--text-01)",
        }}
      >
        {record.note}
      </p>
      <Note tone={generated ? "info" : "limit"}>{noteCaption(record, model)}</Note>
    </Section>
  );
}
