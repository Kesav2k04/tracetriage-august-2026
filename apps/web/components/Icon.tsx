/**
 * The console's icons, drawn here rather than installed.
 *
 * No icon package. A set this small (five glyphs) is a few hundred bytes of inline
 * SVG against tens of kilobytes for a library, and every mark can then say something
 * about this project rather than being a generic chart or clock borrowed from a
 * dashboard kit. The rule the set follows: each glyph is a small diagram of the
 * thing its section shows, not a metaphor for it.
 *
 *   queue       four rows, the top two marked, the rest plain. A ranked list where
 *               the budget takes the top of it, which is exactly what the queue is.
 *   evaluation  a reliability diagram: the diagonal a perfectly calibrated model
 *               would sit on, and a curve departing from it. The evaluation page's
 *               own subject.
 *   replay      a play mark on a time axis with a tick, because the replay is a
 *               pass playing against a clock rather than a video.
 *   provenance  a receipt with a torn edge and a hash rule, which is what that page
 *               is: the sha256 of every artifact behind every number.
 *   corridor    the S curve of a Doppler pass crossing its centre line, the shape
 *               the whole project is testing for.
 *
 * All are 16 by 16 on a 2px stroke grid, `currentColor`, no fill, so they take the
 * colour of the text they sit beside and need no per-state variants. They are marked
 * `aria-hidden` because in every current use the adjacent text already names the
 * destination, and a second announcement of the same word is noise for a screen
 * reader.
 */

export type IconName =
  | "queue"
  | "evaluation"
  | "replay"
  | "provenance"
  | "corridor";

const PATHS: Record<IconName, React.ReactNode> = {
  queue: (
    <>
      <path d="M2.5 3.5h11" className="icon-mark" />
      <path d="M2.5 6.5h11" className="icon-mark" />
      <path d="M2.5 9.5h7.5" />
      <path d="M2.5 12.5h7.5" />
    </>
  ),
  evaluation: (
    <>
      <path d="M2.5 13.5v-11" />
      <path d="M2.5 13.5h11" />
      <path d="M2.5 13.5 13.5 2.5" className="icon-faint" />
      <path d="M2.5 13.5c3 0 3.6-8 11-8" className="icon-mark" />
    </>
  ),
  replay: (
    <>
      <path d="M2.5 13.5h11" />
      <path d="M5.5 12v3" />
      <path d="M10.5 12v3" />
      <path d="m5.5 2.5 6 3.75-6 3.75z" className="icon-mark" />
    </>
  ),
  provenance: (
    <>
      <path d="M3.5 1.5h9v13l-1.5-1.2-1.5 1.2-1.5-1.2-1.5 1.2L5 13.3l-1.5 1.2z" />
      <path d="M6 5h4" className="icon-mark" />
      <path d="M6 8h4" className="icon-mark" />
    </>
  ),
  corridor: (
    <>
      <path d="M8 1.5v13" className="icon-faint" />
      <path d="M4.5 1.5c0 3.2 7 6.3 7 9.5v3.5" className="icon-mark" />
    </>
  ),
};

export default function Icon({
  name,
  size = 16,
  className,
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      className={className ? `icon ${className}` : "icon"}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
