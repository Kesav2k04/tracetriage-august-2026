/**
 * The page written for someone scoring this in twelve minutes.
 *
 * `FOR_JUDGES.md` exists, is generated from the receipts, and lives on GitHub. The lived
 * evidence from the June 2026 entry is that the judges did not clone the repository: they
 * opened the deployed console, watched the video and read the submission page. So the
 * console needs its own way in, and this is it.
 *
 * What that way in should be changed. This page used to answer the question by putting
 * every answer on it: the pre-registered gates at full size, the judged criteria mapped
 * row by row, the Bob waves, the notes. All of it true, all of it read from the receipts,
 * and all of it asking a reader to decide whether the page is worth reading by reading it.
 * A visitor who has not committed yet does not audit a page of tables to find out whether
 * to audit it.
 *
 * So the argument is made once, in order, by a clip that takes forty four seconds, and the
 * tables moved to `FOR_JUDGES.md`, which now opens with a summary of its own that runs
 * about a minute. Two surfaces, each doing one job, instead of one surface doing both
 * badly. The figure above the clip stays because it is measured rather than drawn, and it
 * is the one thing on this console a reader understands without being told anything.
 *
 * The clip's spoken figures are read from the same constants its animation draws, and
 * `scripts/build_explainers.py --check` fails if the clip, its captions and this page ever
 * disagree about what it says or how long it runs.
 */
import type { Metadata } from "next";

import { queue } from "@/lib/data";
import OrbitField from "@/components/OrbitField";

export const metadata: Metadata = {
  title: "Start here",
  description:
    "TraceTriage in one page: a forty four second map of the console, and the one "
    + "measurement that shows why the queue exists.",
};

export default function StartPage() {
  return (
    <div className="shell" style={{ paddingTop: "var(--sp-08)" }}>
      <header style={{ maxWidth: "62ch" }}>
        <p className="lede-kicker">
          AI Builders Challenge with IBM Bob · August theme, Advance Space Exploration
          with AI
        </p>
        <h1 className="lede-headline" style={{ marginTop: "var(--sp-04)" }}>
          Which satellite passes are worth a reviewer&rsquo;s time.
        </h1>
        <p
          style={{
            marginTop: "var(--sp-05)",
            maxWidth: "62ch",
            color: "var(--text-02)",
            fontSize: "var(--type-body-long)",
            lineHeight: 1.7,
          }}
        >
          SatNOGS is a network of volunteer ground stations that record satellites passing
          overhead and publish every recording as a waterfall image. It produces far more
          than anyone can look at. TraceTriage reads the image and the orbital physics
          together, works out which unreviewed observations would teach a reviewer the
          most, and puts {queue.entries.length} of them in order, with the top{" "}
          {queue.review_budget.n_observations} as the budget a volunteer actually has. It
          writes nothing back to the network. A human still decides.
        </p>
        <p
          style={{
            marginTop: "var(--sp-05)",
            maxWidth: "62ch",
            color: "var(--text-02)",
            lineHeight: 1.7,
          }}
        >
          Ground-station networks are how university and cubesat missions are actually
          operated, and an unreviewed pass is telemetry nobody read. The decision this
          serves is the one every mission-operations queue has: of everything that came
          down, what does a person open first.
        </p>
      </header>

      {/* The geometry the clip argues from, drawn rather than measured, which its own
          label says. The measured version of this idea is the two waterfall figure, and
          that lives in the README: printing it here as well put the same picture and the
          same four numbers on two surfaces a judge reads back to back. */}
      <OrbitField
        label="One pass, propagated from a 550 km circular orbit at 97.6 degrees over a station at 52.2 degrees north. The track is elevation above the horizon; the curve beneath it is the Doppler shift that pass's range rate implies at 437 MHz. Drawn for this figure and not measured: every number this console publishes comes from a receipt."
      />


      {/* What this page argued in sections it now argues once, in order, in the clip.
          A visitor who has not decided to read yet will not read a page of tables to find
          out whether the page is worth reading, so the map goes first and the detail moves
          to FOR_JUDGES.md, which opens with a one minute summary of its own. The drawn
          orbit figure that used to sit here went with the sections: it illustrated the
          geometry rather than measuring anything, and the figure above it is measured. */}
      <figure className="explainer">
        <video
          controls
          preload="none"
          playsInline
          aria-label={
            "44 seconds, narrated and captioned: what each of the nine pages of this " +
            "console is for, and how one recording moves through them."
          }
          poster="/media/console-explainer-poster.jpg"
          width={1920}
          height={1080}
        >
          <source src="/media/console-explainer.mp4" type="video/mp4" />
          <track
            kind="captions"
            src="/media/console-explainer.vtt"
            srcLang="en"
            label="English"
            default
          />
          <p>
            Your browser cannot play this video. It maps the nine pages of this console:
            one recording, the two pages that measure it, the queue that ranks four
            hundred and seven of them, and the pages holding the evidence for every
            number, including the gates that did not pass.
          </p>
        </video>
        <figcaption>
          44 seconds, narrated and captioned. Every figure it speaks is read from the same
          constants the animation draws, and{" "}
          <code>scripts/build_explainers.py --check</code> fails if the clip, its captions
          and this page ever disagree. The evidence behind each page is in{" "}
          <code>FOR_JUDGES.md</code>, one section per judged criterion.
        </figcaption>
      </figure>
    </div>
  );
}
