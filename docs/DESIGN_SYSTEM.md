# The design system, and why the palette is a measurement

IBM Carbon owns the console's structure: the Gray 100 lightness ramp, the type scale, the 8px
spacing steps and the productive motion curves, written as custom properties in
`apps/web/app/globals.css` rather than pulled in as a component library. Colour is a separate
question, and it was answered from a measurement rather than from taste. This page is the
derivation, the two accessibility defects it caught, and the checks that hold it.

Moved out of `README.md` because a judge reading the submission needs the result and not the
derivation, and a reader who wants the derivation needs all of it rather than a paragraph.

## The palette is derived from the data, and the derivation is checkable

Carbon owns the structure and nothing below moves it. Colour is a separate question, and it
was answered from a measurement rather than from taste.

Start with the input. Every waterfall this site publishes is greyscale: across the 25
committed images the largest difference between any pixel's brightest and darkest channel is
1 part in 255, and the mean is 0.01. The instrument records intensity and no hue.
`tests/test_hero_window.py::test_every_published_waterfall_is_achromatic` asserts it, so the
claim cannot quietly stop being true when the snapshot is refreshed.

That decides the palette in one rule: **grey is measured, colour is computed.** The waterfall
is shown as published, in grey. Every coloured mark on the page is something the pipeline
derived, a corridor predicted from an orbit or a conflict between two labels, so a reader can
separate the observation from the inference without reading a legend.

**The neutrals are Carbon's, re-tinted.** Each one is its Carbon Gray 100 original converted
to OKLCH, held at exactly its Carbon lightness, given a chroma that falls as lightness rises
(0.030 in the darkest steps, 0.004 in the lightest) at hue 305, and converted back. Because
OKLCH lightness is perceptually uniform and the chroma is small, the hue rotation moves the
largest ratio on the ramp by 0.026, which is rounding. One lightness did move, the page
ground, from Carbon's L 0.200 to L 0.182, and a darker ground can only raise a ratio measured
against it: `text-01` on the page ground is 16.45:1 as Carbon ships it and 17.11:1 here,
`text-03` on a rule is 3.49:1 and 3.50:1, and `ui-04` as a component boundary is 3.60:1 and
3.73:1. All 26 pairs meet their floor. The tint was done this way instead of by picking
colours that looked right so that no accessibility result measured on the built site had to
be re-argued, and the chroma falls with lightness for a reason worth stating: a tinted
mid-grey is what makes a dark theme look synthetic, while a tinted black reads as a sky, so
the void carries the colour and the ink carries almost none. Hue 305 is a deep plum, and it is the one colour on the
page that is a preference rather than a derivation. It is named as such in `globals.css`.

**The accents are stops off the colourmap the plate is rendered through.** The home page maps
its greyscale plate through `inferno` in an SVG filter, using the same 17-stop table
matplotlib generates, and every accent token is a sample off that same table with the
position it was taken from written beside it. `--link-01` is inferno at 0.80, `#fca50a`,
measuring 9.46:1 on the page ground and 7.69:1 on a tile. Inferno was chosen for three
properties rather than for its look: it is monotonic in lightness, so a value encoded by hue
is also encoded by contrast; it is safe under all three common colour-vision deficiencies,
which a blue-to-red ramp is not; and it is what matplotlib ships for spectrograms, which is
what a waterfall is.

**One verdict carries a hue, and it is red.** Two of the four substantive gates came back
neither passed nor failed, so a red and green pair would say something the measurements do
not. NASA's Appendix F display standard reserves red for a warning and amber for a caution,
and Carbon's own guidance assigns grey to unknown or pending; between them they rule out
painting a cleared gate in the brightest thing the ramp has, because that is yellow and
yellow is a statement about the subject of the measurement rather than about the measurement.
So `PASSED` is the page's strongest neutral, and the four states are told apart by the
marker's form as well as its value: a filled disc for decided, a hollow ring for measured and
inconclusive, a dash for no measurement at all. The verdict word is printed in capitals
beside every one of them, so hue is never the only channel carrying the state.

**Two checks hold it.** `scripts/check_contrast.py` recomputes all 26 rendered pairs from the
token block and `tests/test_contrast.py` fails the suite if one drops below its floor, so the
next person to reach for a nicer amber finds out immediately rather than at an accessibility
audit. `apps/web/audit/a11y-probe.js` measures the built pages instead of the tokens: over
seven page types it resolves the real background behind 2,235 text nodes and reports 0 below
requirement, 193 focusable elements with 0 missing a focus ring, one `h1` per page, no
skipped heading level and no unlabelled media element.

That probe found a defect in this repository and it is worth stating plainly. The page ground
had become a gradient set through the `background` shorthand, which resets `background-color`
to transparent, so neither `body` nor `html` carried an opaque colour anywhere. The probe's
walk for a background found none, fell back to inventing white, and reported 662 of 706 nodes
on the landing page below their contrast floor against a page that renders correctly. The
earlier run recorded in the claim register was measured before that gradient existed, and the
gradient silently invalidated it. The fix is three parts: the ground now carries an opaque
colour under the gradient, which is the gradient's own first stop so no pixel moves; the probe
reports an unresolvable background as a third outcome rather than scoring it either way; and a
background layer sized to zero on an axis is treated as painting nothing, because the hover
underline is a gradient held at `0%` until hover and treating that as an obstruction made 41
links on one page unmeasurable.

Two real contrast failures came out of the same run, both the same mistake in two places:
white text on the accent. The skip link measured 3.34:1 on the old Carbon blue, already under
its floor and unnoticed because the link is invisible until focused, and the queue's active
filter chip measured 2.00:1 on the amber. Both now carry the plate's ground as their ink,
which is the same pair inverted at 9.09:1.

## Motion costs no JavaScript

The reveal on scroll is `animation-timeline: view()`, the row stagger is an `animation-delay`
multiplied by a row index, and the digit wipe is a `clip-path` inset. All three run on the
compositor, none needs an observer or a listener, and the static export animates without
shipping a frame of script. Only opacity, transform and clip-path are animated, so nothing
costs a layout or repaints a subtree. Where `animation-timeline` is unsupported the
`@supports` block does not apply and every element renders at its final state, which is the
right fallback: the content is the information and the reveal is not.

`prefers-reduced-motion: reduce` collapses every duration, and each rule is additionally
scoped to `no-preference`, so a reader who asked for less motion never has an element start at
zero opacity and then depend on an animation to arrive. `apps/web/audit/motion-probe.js`
measures both failure modes a build cannot see: it reports the count the selector reached and
every element that did not end fully opaque after a full scroll. A matched count of zero is
reported as a failure rather than as a clean run, and it caught one. The reveal was first
written `main > section` while every section is a child of `.shell`, so it matched nothing at
all and the page had no reveal while the stylesheet looked correct.
