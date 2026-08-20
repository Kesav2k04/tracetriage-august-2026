/**
 * Motion probe for the evidence console.
 *
 * Written in the same shape as `a11y-probe.js`: paste into a browser console on any
 * page, or evaluate it through a driver. It returns JSON rather than logging, so a
 * caller can assert on it.
 *
 * It exists because of one failure mode. The console's reveal on scroll is
 * `animation-timeline: view()`, which is CSS-only and therefore invisible to the
 * build, the type check and the test suite. Two things can go wrong with it and both
 * are silent:
 *
 *   1. The selector stops matching. This already happened once: the rule was
 *      written `main > section` while every section is a child of `.shell`, so it
 *      matched nothing at all and the page had no reveal while the stylesheet looked
 *      correct. A rule that matches zero elements is not a rule.
 *   2. An element never finishes arriving. If a reveal starts at opacity 0 and the
 *      timeline does not advance, the content is on the page, in the accessibility
 *      tree, and unreadable. Nothing else in this repository can catch that.
 *
 * So the probe scrolls the whole document, then reports the count the selector
 * reached and every element that did not end fully opaque. It also reports the
 * counts under `prefers-reduced-motion`, because the honest reduced state here is
 * the final frame and an element left at zero opacity for a reader who asked for
 * less motion is worse than the animation.
 *
 * A count of zero matched elements is reported as `matched: 0` and is a failure, not
 * a pass. That distinction is the whole point: an empty result means nothing was
 * measured, not that everything was fine.
 */
(async () => {
  const REVEAL = "main .shell > section, main .shell > figure, .instrument";
  const STAGGER = ".ledger-row";
  const WRITE = ".lede-number";

  const settle = () =>
    new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  const opacityOf = (el) => parseFloat(getComputedStyle(el).opacity);

  const describe = (el) => {
    const cls = typeof el.className === "string" ? el.className : "";
    return `${el.tagName.toLowerCase()}${cls ? "." + cls.trim().split(/\s+/).join(".") : ""}`;
  };

  const supported = {
    view_timeline: CSS.supports("animation-timeline", "view()"),
    clip_path: CSS.supports("clip-path", "inset(0 0 100% 0)"),
  };

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Load state, before any scrolling. An element already inside the viewport must
  // already be visible: a reveal that waits for a scroll the reader will never make
  // is the same defect as one that never finishes.
  await wait(700);
  const inViewAtLoad = [...document.querySelectorAll(REVEAL)].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.top < window.innerHeight * 0.6 && r.bottom > 0;
  });
  const hiddenInViewAtLoad = inViewAtLoad
    .filter((el) => opacityOf(el) < 0.999)
    .map((el) => ({ el: describe(el), opacity: opacityOf(el) }));

  // Walk the document. A single jump to the bottom advances a view() timeline to its
  // end state for elements above, but stepping is what a reader does and it catches
  // a range that overshoots.
  const height = document.documentElement.scrollHeight;
  for (let y = 0; y <= height; y += Math.round(window.innerHeight * 0.4)) {
    window.scrollTo(0, y);
    await settle();
  }
  window.scrollTo(0, height);
  await wait(600);

  const targets = [...document.querySelectorAll(REVEAL)];
  const unfinished = targets
    .filter((el) => opacityOf(el) < 0.999)
    .map((el) => ({ el: describe(el), opacity: opacityOf(el) }));

  const stagger = [...document.querySelectorAll(STAGGER)];
  const staggerUnfinished = stagger
    .filter((el) => opacityOf(el) < 0.999)
    .map((el) => ({ el: describe(el), opacity: opacityOf(el) }));

  const write = [...document.querySelectorAll(WRITE)];
  const writeUnfinished = write
    .filter((el) => {
      const cs = getComputedStyle(el);
      // A finished wipe is inset with a negative or zero bottom. An unfinished one
      // still carries a positive bottom inset, which is how a clipped number reads
      // as a shorter number rather than as a missing one.
      return /inset\(/.test(cs.clipPath) && /\b(\d+(\.\d+)?)%/.test(cs.clipPath)
        ? parseFloat(cs.clipPath.match(/(\d+(?:\.\d+)?)%/)[1]) > 1
        : opacityOf(el) < 0.999;
    })
    .map((el) => ({
      el: describe(el),
      clipPath: getComputedStyle(el).clipPath,
      opacity: opacityOf(el),
    }));

  window.scrollTo(0, 0);

  return {
    url: location.pathname,
    supported,
    prefers_reduced_motion: reduced,
    document_height: height,
    reveal: {
      selector: REVEAL,
      matched: targets.length,
      in_view_at_load: inViewAtLoad.length,
      hidden_in_view_at_load: hiddenInViewAtLoad,
      unfinished_after_full_scroll: unfinished,
    },
    stagger: {
      selector: STAGGER,
      matched: stagger.length,
      unfinished: staggerUnfinished,
    },
    digit_wipe: {
      selector: WRITE,
      matched: write.length,
      unfinished: writeUnfinished,
    },
  };
})();
