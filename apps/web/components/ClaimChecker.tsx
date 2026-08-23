"use client";

/**
 * The grounding checker, in the reader's browser, over this observation's own packet.
 *
 * Every other claim on this site is a number in a receipt: you either trust the receipt or
 * you clone the repository. This one is different, because the checker is a rule set and a
 * rule set is only believable if you can try to beat it. So the port in `lib/grounding.ts`
 * runs here, on the same evidence packet the pipeline built, and a reader can change one
 * digit and watch the refusal appear.
 *
 * Nothing leaves the page. There is no endpoint, no key and no model: the console is a
 * static export and this component is the whole checker, which is also why the parity tests
 * exist. `tests/test_grounding_parity.py` and `apps/web/tests/grounding.test.ts` hold this
 * file and `pipeline/tracetriage/explain.py` to the same 1,275 recorded decisions, because
 * two implementations of one rule set drift and each one passes its own tests while it does.
 *
 * The presets are not written here. They come from `adversarialDrafts(packet)`, which is the
 * pipeline's own set, and each is kept only if the checker actually refuses it for the code
 * it is offered under. A demonstration button that stopped demonstrating anything would
 * otherwise sit there looking convincing.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import {
  MAX_CHARS,
  MeasurementMissing,
  adversarialDrafts,
  buildPacket,
  deterministicNote,
  verifyNote,
  type EvidencePacket,
  type GroundingCard,
  type GroundingEntry,
} from "@/lib/grounding";
import { Note, Section, Tag } from "@/components/ui";

/** A button, its draft, and the code it is there to produce. */
interface Preset {
  label: string;
  hint: string;
  text: string;
  /** null for the draft that is meant to pass. */
  expect: string | null;
}

/**
 * The time claim, built from the packet's own numbers.
 *
 * This is the preset worth having. `pass_duration_s` is in the packet, so a sentence that
 * sends the reviewer to the last second of the recording breaks no number rule: every digit
 * in it was measured. It is refused anyway, because closest approach is somewhere else and
 * the packet holds no other time to look at. A closed world of numbers is not a closed world
 * of statements, and one button is a better argument for that than a paragraph.
 */
function timePreset(packet: EvidencePacket): Preset | null {
  const duration = packet.exact.pass_duration_s;
  if (!Number.isFinite(duration) || duration <= 0) return null;
  const seconds = packet.printed.pass_duration_s;
  return {
    label: "Every number measured, pointing at the wrong second",
    hint: "MISLOCATED_TIME_CLAIM",
    text:
      `Look around the ${seconds}-second mark, where the signal should be strongest. ` +
      `The corridor is drawn from the pass geometry.`,
    expect: "MISLOCATED_TIME_CLAIM",
  };
}

/** The presets, in the order they are offered, each verified against the checker. */
function presetsFor(packet: EvidencePacket, shipped: string | null): Preset[] {
  const drafts = adversarialDrafts(packet);
  const pick = (code: string, match: RegExp): Preset | null => {
    const found = drafts.find(([text, expected]) => expected === code && match.test(text));
    return found ? { label: "", hint: code, text: found[0], expect: code } : null;
  };

  const candidates: Array<Preset | null> = [
    {
      label: "The note that shipped",
      hint: shipped ? "as published" : "the deterministic template",
      text: shipped ?? deterministicNote(packet),
      expect: null,
    },
    (() => {
      const found = pick("UNGROUNDED_NUMBER", /kHz/);
      return found
        ? { ...found, label: "The right digits in the wrong unit" }
        : null;
    })(),
    (() => {
      const found = pick("UNGROUNDED_NUMBER", /catalogue centre\. Look/);
      return found
        ? { ...found, label: "Two digits of the offset transposed" }
        : null;
    })(),
    timePreset(packet),
    (() => {
      const found = pick("OVERCLAIM", /was heard during the pass/);
      return found ? { ...found, label: "A claim this system cannot make" } : null;
    })(),
    (() => {
      const found = pick("WRONG_VOICE", /^I think/);
      return found ? { ...found, label: "A reviewer's note in the wrong voice" } : null;
    })(),
  ];

  // A preset that no longer does what its label says is worse than no preset: it reads as
  // a demonstration and demonstrates nothing. So each one is run through the checker here
  // and dropped if the verdict disagrees with the code it is offered under.
  return candidates.filter((preset): preset is Preset => {
    if (!preset) return false;
    const verdict = verifyNote(preset.text, packet);
    return preset.expect === null ? verdict.ok : verdict.codes.includes(preset.expect);
  });
}

export default function ClaimChecker({
  card,
  entry,
  shipped,
}: {
  card: GroundingCard;
  entry: GroundingEntry | undefined;
  shipped: string | null;
}) {
  const built = useMemo(() => {
    if (!entry) return { packet: null, why: "no queue entry" as const };
    try {
      return { packet: buildPacket(card, entry), why: null };
    } catch (error) {
      if (error instanceof MeasurementMissing) {
        return { packet: null, why: "no corridor fit" as const };
      }
      throw error;
    }
  }, [card, entry]);

  const packet = built.packet;
  const presets = useMemo(
    () => (packet ? presetsFor(packet, shipped) : []),
    [packet, shipped],
  );
  const [text, setText] = useState(() => presets[0]?.text ?? "");

  // The verdict is recomputed on every keystroke, and it sits in a live region. A
  // reader typing "123" into the box therefore queues three separate refusals, each
  // naming the literal that offended, before the sentence is finished. Polite does
  // not interrupt but it still queues, which is the same mistake the replay readout
  // made and fixed: the region is off while the value is moving and polite once it
  // has settled. The visible verdict is unaffected and still updates per keystroke.
  const [typing, setTyping] = useState(false);
  const settleRef = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (settleRef.current !== null) window.clearTimeout(settleRef.current);
    },
    [],
  );

  if (!packet) {
    return (
      <Section
        title="Check a claim about this observation"
        description="The checker runs in the browser, over this observation's evidence packet."
      >
        <Note tone="warn">
          This observation has {built.why}, so there is no evidence packet to check a
          sentence against. That is the same refusal the pipeline makes: a note grounded in a
          measurement nobody took is not grounded.
        </Note>
      </Section>
    );
  }

  const verdict = verifyNote(text, packet);
  const characters = Array.from(text.trim()).length;

  return (
    <Section
      title="Check a claim about this observation"
      description="The grounding checker from the pipeline, ported to TypeScript and running here. Edit the sentence, or start from one of the drafts below, and the verdict changes as you type. Nothing is sent anywhere: the whole rule set is in the page."
    >
      <div className="claim">
        <div className="claim-presets" role="group" aria-label="Drafts to start from">
          {presets.map((preset) => (
            <button
              key={preset.label}
              type="button"
              className="claim-preset"
              aria-pressed={text === preset.text}
              onClick={() => setText(preset.text)}
            >
              <span className="claim-preset-label">{preset.label}</span>
              <span className="claim-preset-hint num">{preset.hint}</span>
            </button>
          ))}
        </div>

        <label className="claim-label" htmlFor="claim-text">
          The sentence to check
        </label>
        <textarea
          id="claim-text"
          className="claim-input"
          value={text}
          spellCheck={false}
          rows={4}
          onChange={(event) => {
            setText(event.target.value);
            if (!typing) setTyping(true);
            if (settleRef.current !== null) window.clearTimeout(settleRef.current);
            // 600 ms rather than the replay's 200: a pause inside a sentence is
            // longer than a pause inside a drag, and announcing a verdict about half
            // a sentence is worse than announcing it slightly late.
            settleRef.current = window.setTimeout(() => {
              settleRef.current = null;
              setTyping(false);
            }, 600);
          }}
        />
        <p className="claim-count num">
          {characters} of {MAX_CHARS} characters
        </p>

        <div
          className={verdict.ok ? "claim-verdict is-ok" : "claim-verdict is-refused"}
          aria-live={typing ? "off" : "polite"}
          aria-atomic="true"
        >
          <p className="claim-verdict-head">
            <span className="claim-verdict-word">
              {verdict.ok ? "GROUNDED" : "REFUSED"}
            </span>
            {verdict.codes.length > 0 && (
              <span className="claim-verdict-codes">
                {verdict.codes.map((code) => (
                  <Tag key={code} tone="warn">
                    {code}
                  </Tag>
                ))}
              </span>
            )}
          </p>
          {verdict.ok ? (
            <p className="claim-verdict-body">
              Every number in this sentence is a token of the packet below, every code and
              label in it is this observation&rsquo;s, and no permission rule fired. That is all
              the checker claims: the sentence is consistent with what was measured, not
              that the measurement is right.
            </p>
          ) : (
            <ul className="claim-violations">
              {verdict.violations.map((violation, index) => (
                <li key={`${violation.code}-${index}`}>
                  <span className="claim-code num">{violation.code}</span>
                  <span className="claim-detail">{violation.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <details className="claim-packet">
          <summary>
            The evidence packet this is checked against, exactly as the model was shown it
          </summary>
          <pre className="claim-packet-text">{packet.text}</pre>
          <p className="claim-packet-note">
            The closed world. A number that is not a token of this text is not grounded,
            which is why 6490 is refused although those digits appear inside 436490000:
            containment is not membership, and a transposed offset passed the old check for
            exactly that reason.
          </p>
        </details>
      </div>
    </Section>
  );
}
