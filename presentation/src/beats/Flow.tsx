import React from "react";
import { OffthreadVideo, staticFile } from "remotion";
import { flow } from "../data";
import { font, numeric, token } from "../theme";
import { Body, Eyebrow, Frame, Heading, Mono, Reveal } from "../ui";

/**
 * The one shot in this film that is a recording rather than a drawing.
 *
 * `film/flow-take.mp4` is an unbroken 16-second capture of LangFlow 1.11.4 running the
 * flow this repository commits at `flows/tracetriage_grounding.json`: the graph, the
 * playground, a sentence typed into it, and what came back. Nothing is cut inside the
 * take, because a cut is where a viewer would reasonably suspect the interesting part
 * went missing.
 *
 * The sentence is the one the receipt records, and it is a lie: this observation has no
 * 437.2 MHz downlink. The checker refuses it in a tenth of a second and names the
 * violation. That is the whole argument of the project happening to a real tool rather
 * than being described.
 *
 * Two honest notes, both drawn on the card rather than left for a reader to discover.
 * The committed flow is a file LangFlow wrote with `Graph.dump()`, which records no node
 * positions, so the copy that was filmed has positions added and nothing else: the
 * graph, the component code and the result are the committed file's. And nothing this
 * project publishes runs through LangFlow. It is a second client for the same read-only
 * surface, offered because a visual graph is how some teams would wire it.
 *
 * Written as an expression body on purpose. `test/claims.test.ts` finds a beat's copy by
 * collapsing every brace pair as code, so a statement body hides the whole card from the
 * scan that checks no figure was typed into it by hand. The verdict panel's entrance is
 * `Reveal`, which is the film's own easing and needs no state here.
 */
export const Flow: React.FC = () => (
    <Frame
      eyebrow="Running, not described"
      sources={[flow.refusedCode, flow.version]}
    >
      <Reveal delay={2}>
        <Heading size={46}>
          The same evidence, driven from a LangFlow canvas.
        </Heading>
      </Reveal>

      <Reveal delay={8}>
        <div style={{ marginTop: 16, maxWidth: 1560 }}>
          <Body size={25} colour={token.text02}>
            One unbroken take. A sentence goes in with a downlink frequency this
            observation does not carry, and the checker that decides whether this
            project&rsquo;s own notes ship decides this one too.
          </Body>
        </div>
      </Reveal>

      <Reveal delay={14}>
        <div
          style={{
            marginTop: 26,
            // The frame's own content box, so the take cannot run past the margin the
            // rest of the film keeps. At the capture's 1684 by 640 this leaves the
            // footer its line. It was 2020 and overflowed both.
            width: "100%",
            border: `1px solid ${token.borderSubtle}`,
            background: token.surfaceSunken,
            overflow: "hidden",
          }}
        >
          <OffthreadVideo
            src={staticFile("film/flow-take.mp4")}
            style={{ width: "100%", display: "block" }}
            muted
          />
        </div>
      </Reveal>

      {/* Arrives once the take has reached the answer, so the card never asserts a
          refusal the footage has not shown yet. */}
      <Reveal
        delay={300}
        rise={0}
        style={{ position: "absolute", right: 96, top: 300, width: 1040 }}
      >
        <div
          style={{
            border: `1px solid ${token.borderStrong}`,
            background: token.ui01,
            padding: 30,
          }}
        >
          <Eyebrow colour={token.text03}>what came back</Eyebrow>
          <div
            style={{
              marginTop: 16,
              fontFamily: font.sans,
              fontWeight: 600,
              fontSize: 68,
              lineHeight: 1,
              letterSpacing: -1,
              color: token.support01,
              ...numeric,
            }}
          >
            {flow.refusedVerdict.display}
          </div>
          <div style={{ marginTop: 18 }}>
            <Mono size={26} colour={token.interactive01}>
              {flow.refusedCode.display}
            </Mono>
          </div>
          <div style={{ marginTop: 18, maxWidth: 940 }}>
            <Body size={22} colour={token.text02}>
              LangFlow {flow.version.display}, the committed flow, laid out for viewing
              and otherwise unchanged. Nothing this project publishes runs through it.
            </Body>
          </div>
        </div>
      </Reveal>
    </Frame>
);
