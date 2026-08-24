/**
 * The console's palette, the subset this client uses.
 *
 * Copied deliberately rather than imported. `apps/web/app/globals.css` derives these from
 * `scripts/derive_palette.py` with checked contrast ratios, and a React Native app cannot
 * read a CSS custom property, so there is no import that would keep them in step. What keeps
 * them in step is `tests/test_mobile_client.py`, which parses both files and fails when a
 * hex here is not the value the stylesheet sets for the same token. Nine values, checked,
 * beats a build-time asset pipeline for nine values.
 *
 * The token name is kept beside each one because the check needs it and because a reader
 * comparing the two files should not have to guess which grey is which.
 */
export const palette = {
  /** --ui-background: the ground the whole console sits on. */
  ground: "#0c0e12",
  /** --surface-raised: a panel above the ground. */
  raised: "#161c26",
  /** --surface-sunken: a well a plot or an image is sunk into. */
  sunken: "#07090e",
  /** --ui-01: the corridor fill, and a table's alternating row. */
  corridor: "#1e242f",
  /** --hover-ui: the edge of a raised panel. */
  edge: "#2d333d",
  /** --text-01: running prose. */
  ink: "#f1f2f3",
  /** --text-03: a caption or a label. 5.65:1 on the ground. */
  quiet: "#888b90",
  /** --interactive-04: the fitted trace, and every number a reader can act on. */
  accent: "#fbbe23",
  /** --support-01: a refusal, a conflict, a failed verdict. */
  alarm: "#eb5e61",
} as const;

export const space = {
  page: 16,
  gap: 12,
  tight: 6,
} as const;

export const type = {
  /** No custom face is bundled. The system font is what a phone renders best, and the
   *  licensed display face on the console is licensed for the web only. */
  title: 22,
  heading: 17,
  body: 15,
  label: 12,
  mono: 13,
} as const;
