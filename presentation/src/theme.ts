/**
 * The console's tokens, copied from apps/web/app/globals.css.
 *
 * Copied rather than imported because a Remotion bundle cannot read CSS custom
 * properties out of a Next.js stylesheet at build time, and because the film has to
 * keep rendering from a checkout where the console was never built. The cost of the
 * copy is a test: test/claims.test.ts reads globals.css and fails if any value here
 * has drifted from the token it names.
 */

export const token = {
  // Ground and plates
  uiBackground: "#050d21", // --ui-background
  ui01: "#1b2434", // --ui-01
  ui02: "#313845", // --ui-02
  ui04: "#6c7077", // --ui-04
  surfaceRaised: "#121c2e", // --surface-raised
  surfaceSunken: "#02081c", // --surface-sunken
  edgeHighlight: "#444d5e", // --edge-highlight

  // Ink
  text01: "#f1f2f3", // --text-01
  text02: "#c3c4c7", // --text-02
  text03: "#888b90", // --text-03
  text04: "#ffffff", // --text-04

  // Accent and status, sampled off the inferno table
  interactive01: "#fca50a", // --interactive-01
  support01: "#eb5e61", // --support-01
  support03: "#f37819", // --support-03

  // Live
  live01: "#56d9e7", // --live-01
  live02: "#2f939d", // --live-02

  // Borders
  borderSubtle: "#313845", // --border-subtle
  borderStrong: "#6c7077", // --border-strong

  // Verdict ink
  verdictPassed: "#f1f2f3", // --verdict-passed
  verdictNotEstablished: "#c3c4c7", // --verdict-not-established
  verdictFailed: "#eb5e61", // --verdict-failed
  verdictNotMeasurable: "#888b90", // --verdict-not-measurable

  waterfallGround: "#000000", // --waterfall-ground
} as const;

export const font = {
  sans: '"IBM Plex Sans", system-ui, sans-serif',
  mono: '"IBM Plex Mono", ui-monospace, Consolas, monospace',
} as const;

/** Carbon's productive easing, from the --ease-* tokens in globals.css. */
export const ease = {
  standard: [0.2, 0, 0.38, 0.9] as const,
  entrance: [0, 0, 0.38, 0.9] as const,
  exit: [0.2, 0, 1, 0.9] as const,
};

/** Every number on screen is a measurement, so every number gets tabular figures. */
export const numeric = {
  fontVariantNumeric: "tabular-nums lining-nums",
} as const;

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** The margin the console uses on a full-bleed page, scaled to 1080p. */
export const MARGIN = 96;
