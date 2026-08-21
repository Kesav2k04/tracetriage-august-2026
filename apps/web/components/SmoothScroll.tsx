"use client";

/**
 * One frame loop for the whole console: normalised scrolling, and the choreography that rides
 * on it.
 *
 * Two jobs live here rather than in two components because they are the same clock. Lenis
 * interpolates scrolling and GSAP schedules against scroll position, and if each ran its own
 * `requestAnimationFrame` the browser would do the work twice a frame and the two would read
 * the scroll one tick apart. So GSAP's ticker drives Lenis, Lenis's scroll event drives
 * ScrollTrigger, and there is a single loop.
 *
 * ## Why scrolling is interpolated at all
 *
 * Chrome's native wheel step is 100 device pixels of instant jump, which on a page of plots
 * means the eye re-acquires the figure after every notch. Lenis turns the same scroll into a
 * short animated one, so a figure stays trackable while it moves. Nothing here is decoration
 * and nothing here changes what the page says.
 *
 * ## Why there is any JavaScript in the motion layer
 *
 * Almost all of it is CSS. Section reveals, the hero plate and the route crossfade are
 * `animation-timeline` on the compositor and cost no script at all, and they stay that way.
 * Two things a scroll timeline cannot express are worth a script:
 *
 * A counting number. CSS cannot animate the content of a text node, and the numbers on the
 * home page are the argument of the whole project, so arriving at them is worth more than
 * appearing with them. `lib/choreography.ts` holds the arithmetic and the three rules that
 * keep a counter from ever showing a value the receipt does not support.
 *
 * An ordered arrival. `view()` gives every element its own timeline against its own
 * visibility, so a row of tiles that crosses the threshold in one frame animates in one
 * frame, and at a desktop width it always does. Reading order is left to right and arrival
 * order should match it. One trigger, one sequence.
 *
 * ## The four ways it switches itself off
 *
 * `prefers-reduced-motion`. Interpolated scrolling and counting numbers are both motion the
 * reader did not ask for. A reader who has asked for less gets the browser's own scrolling
 * and the final numbers, live on the change event, not on the next load.
 *
 * Keyboard and assistive navigation. Lenis is configured off for keys, so Page Down, Home,
 * End, arrows and a focus jump from the skip link all move the document the way the platform
 * moves it. Interpolating a focus jump is how a smooth-scroll library loses a screen reader.
 *
 * Anchors. `scroll-behavior` stays with the browser for in-page links, because the console
 * links to `#queue` and `#circularity` and an interpolated 620 ms trip to an anchor is worse
 * than an instant one.
 *
 * A failed import. Everything is loaded after the first paint and the page is complete
 * without it. If the chunk never arrives the console is exactly what the server sent: every
 * number final, every tile visible. Nothing is hidden waiting for a script, which is the one
 * rule that makes a late bundle a missing animation instead of a blank page.
 *
 * It renders nothing, mounts once in the layout, and attaches after the first paint.
 */

import { useEffect } from "react";
import type Lenis from "lenis";

import { counterFrame, parseCounterTarget, staggerDelays } from "@/lib/choreography";

// Lenis owns the root's overflow while it is running, and these are the rules that make
// that work. Imported here rather than in globals.css so the stylesheet arrives with the
// module that needs it and not on a page that never scrolls smoothly.
import "lenis/dist/lenis.css";

/** How far apart tiles in one group arrive. Kept short: this is a reveal, not a queue. */
const STAGGER_STEP = 0.075;
/** One tile's entrance. */
const STAGGER_DURATION = 0.5;
/** A count is long enough to read as counting and short enough not to be waited for. */
const COUNT_DURATION = 1.1;

export default function SmoothScroll() {
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let lenis: Lenis | null = null;
    let frame = 0;
    let cancelled = false;
    /** Everything the choreography created, so teardown is total and re-entry is clean. */
    const teardown: Array<() => void> = [];

    function stopChoreography() {
      for (const undo of teardown.splice(0)) {
        try {
          undo();
        } catch {
          // A teardown that throws must not strand the ones after it.
        }
      }
    }

    function stop() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      stopChoreography();
      lenis?.destroy();
      lenis = null;
      // Lenis sets `overflow: hidden` on the root while it owns the scroll, so the class it
      // uses to do that has to go with it or the page cannot be scrolled at all.
      document.documentElement.classList.remove("lenis", "lenis-smooth");
    }

    async function start() {
      if (reduced.matches || lenis) return;
      const { default: Constructor } = await import("lenis");
      if (cancelled || reduced.matches) return;
      const instance = new Constructor({
        // Just over half a second. Long enough to be a movement rather than a jump, short
        // enough that a reader scanning a table is not waiting for the page to settle.
        duration: 0.62,
        // Standard ease-out. The tail matters more than the curve name: it is what makes a
        // plot readable while it is still moving.
        easing: (t: number) => 1 - Math.pow(1 - t, 3),
        smoothWheel: true,
        // Touch scrolling is already interpolated by the platform, and doing it twice
        // fights the reader's finger.
        syncTouch: false,
        // The browser keeps in-page links. An interpolated 620 ms trip to #queue is worse
        // than an instant one, and this is the option that decides it.
        anchors: false,
        // The ticker below drives this instance, so Lenis must not start a second loop.
        autoRaf: false,
      });
      lenis = instance;

      // The fallback loop, used until GSAP arrives and if it never does. Scrolling must not
      // depend on the choreography chunk.
      const raf = (time: number) => {
        instance.raf(time);
        frame = requestAnimationFrame(raf);
      };
      frame = requestAnimationFrame(raf);

      void attachChoreography(instance);
    }

    /**
     * Hand the loop to GSAP and register the two sequences.
     *
     * Loaded separately from Lenis so a failure here leaves normalised scrolling working.
     */
    async function attachChoreography(instance: Lenis) {
      let gsap: typeof import("gsap").gsap;
      let ScrollTrigger: typeof import("gsap/ScrollTrigger").ScrollTrigger;
      try {
        const core = await import("gsap");
        const plugin = await import("gsap/ScrollTrigger");
        gsap = core.gsap;
        ScrollTrigger = plugin.ScrollTrigger;
      } catch {
        return;
      }
      if (cancelled || reduced.matches || lenis !== instance) return;

      gsap.registerPlugin(ScrollTrigger);

      // One clock. GSAP's ticker is already running for the tweens below, so Lenis rides it
      // and the standalone loop above is retired.
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      const tick = (time: number) => instance.raf(time * 1000);
      gsap.ticker.add(tick);
      // Without this, a frame that arrives late makes GSAP assume a tab switch and skip
      // ahead, which on a scroll-linked tween reads as the page jumping.
      gsap.ticker.lagSmoothing(0);
      teardown.push(() => gsap.ticker.remove(tick));

      const onScroll = () => ScrollTrigger.update();
      instance.on("scroll", onScroll);
      teardown.push(() => instance.off("scroll", onScroll));

      const context = gsap.context(() => {
        countUp(gsap);
        stagger(gsap);
      });
      teardown.push(() => context.revert());
    }

    /**
     * The two big lift figures count to the value the receipt holds.
     *
     * The target is read out of the text the server rendered, so it cannot drift from the
     * receipt that produced the markup.
     *
     * Nothing pins the element's width, and the first attempt did. A counting number that
     * gains a digit moves whatever sits beside it, so the width was measured once and written
     * back as a `min-width`, which measured 339.54px on both figures: `.lede-number` is a
     * block filling its grid column, so its width never depended on its text and there was
     * no shift to prevent. The pin was not merely useless. It was a desktop measurement
     * frozen into an inline style, so a reader who narrowed the window after it was set kept
     * a 339px floor on a column that no longer had 339px to give. The layout is what keeps
     * the number still here, and the measured shift below is zero.
     */
    function countUp(gsap: typeof import("gsap").gsap) {
      const numbers = document.querySelectorAll<HTMLElement>(".lede-number");
      for (const element of numbers) {
        // The first text node only: the multiplication sign beside it is a separate child
        // and rewriting the whole element would delete it.
        const node = [...element.childNodes].find(
          (child): child is Text => child.nodeType === Node.TEXT_NODE && child.textContent!.trim() !== "",
        );
        if (!node) continue;
        const target = parseCounterTarget(node.textContent!);
        if (!target) continue;

        const original = node.textContent!;
        teardown.push(() => {
          node.textContent = original;
        });

        const state = { progress: 0 };
        gsap.to(state, {
          progress: 1,
          duration: COUNT_DURATION,
          ease: "power2.out",
          // A count is a value arriving, so it may not overshoot. `snap` here also means the
          // last frame writes the target's own string rather than a reformat of it.
          snap: { progress: 1 / (COUNT_DURATION * 60) },
          onUpdate: () => {
            node.textContent = counterFrame(target, state.progress);
          },
          onComplete: () => {
            node.textContent = target.text;
          },
          scrollTrigger: {
            trigger: element,
            // Late enough that the number is properly on screen, and `once` so scrolling
            // back does not re-run an argument the reader has already read.
            start: "top 88%",
            once: true,
          },
        });
      }
    }

    /**
     * Tiles in one group arrive in reading order.
     *
     * `from` rather than `fromTo`, with `immediateRender` left on, so the start state is set
     * in the same frame the tween is created and there is never a frame where a tile has been
     * hidden but not yet animated. Transform and opacity only, so it stays on the compositor.
     */
    function stagger(gsap: typeof import("gsap").gsap) {
      const groups = document.querySelectorAll<HTMLElement>("[data-stagger]");
      for (const group of groups) {
        const items = [...group.children] as HTMLElement[];
        if (items.length < 2) continue;
        const delays = staggerDelays(items.length, STAGGER_STEP);
        const belowFold = group.getBoundingClientRect().top > window.innerHeight;

        items.forEach((item, index) => {
          gsap.from(item, {
            opacity: 0,
            y: 18,
            duration: STAGGER_DURATION,
            delay: belowFold ? 0 : delays[index],
            ease: "power2.out",
            // Hand the element back when the entrance is over. GSAP writes its transform
            // inline, and an inline transform beats a stylesheet, so without this the tween
            // leaves `transform: matrix(1, 0, 0, 1, 0, 0)` sitting on the tile forever and
            // the depth layer's `:hover` lift silently never applies. It was measured doing
            // exactly that: the hover shadow arrived and the lift did not, from one rule.
            // Clearing both properties also means the finished DOM is what the server sent.
            clearProps: "transform,opacity",
            // A group already on screen at load is an entrance and runs now. A group below
            // the fold gets a trigger, so the start state is applied while it is out of
            // sight and the reader never sees the jump to it.
            ...(belowFold
              ? {
                  scrollTrigger: {
                    trigger: group,
                    start: "top 88%",
                    once: true,
                  },
                  delay: delays[index],
                }
              : {}),
          });
        });
      }
    }

    void start();
    const onReduced = () => (reduced.matches ? stop() : void start());
    reduced.addEventListener("change", onReduced);

    return () => {
      cancelled = true;
      reduced.removeEventListener("change", onReduced);
      stop();
    };
  }, []);

  return null;
}
