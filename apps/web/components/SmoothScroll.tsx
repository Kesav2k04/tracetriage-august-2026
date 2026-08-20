"use client";

/**
 * Normalised scrolling, and the three ways it is allowed to switch itself off.
 *
 * A console like this is read by scrolling. Chrome's native wheel step is 100 device pixels
 * of instant jump, which on a page of plots means the eye re-acquires the figure after every
 * notch. Lenis interpolates the same scroll into a short animated one, so a figure stays
 * trackable while it moves. That is the whole argument for it: nothing here is decoration and
 * nothing here changes what the page says.
 *
 * The three switches, because a smooth-scroll library that cannot be turned off is a
 * usability defect wearing a nice coat:
 *
 * `prefers-reduced-motion`. Interpolated scrolling is motion the reader did not ask for, so a
 * reader who has asked for less gets the browser's own scrolling, live, not on the next load.
 *
 * Keyboard and assistive navigation. Lenis is configured off for keys, so Page Down, Home,
 * End, arrow keys and a focus jump from the skip link all move the document the way the
 * platform moves it. Interpolating a focus jump is how a smooth-scroll library loses a
 * screen reader.
 *
 * Anchors. `scroll-behavior` stays with the browser for in-page links, because the console
 * links to `#queue` and `#circularity` and an interpolated 900 ms trip to an anchor is worse
 * than an instant one.
 *
 * It renders nothing. Mounted once in the layout, it attaches on the client after the first
 * paint and cannot affect it.
 */

import { useEffect } from "react";
import type Lenis from "lenis";

// Lenis owns the root's overflow while it is running, and these are the rules that make
// that work. Imported here rather than in globals.css so the stylesheet arrives with the
// module that needs it and not on a page that never scrolls smoothly.
import "lenis/dist/lenis.css";

export default function SmoothScroll() {
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    let lenis: Lenis | null = null;
    let frame = 0;
    let cancelled = false;

    function stop() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
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
        // This component drives the loop below, so Lenis must not start a second one.
        autoRaf: false,
      });
      lenis = instance;
      const raf = (time: number) => {
        instance.raf(time);
        frame = requestAnimationFrame(raf);
      };
      frame = requestAnimationFrame(raf);
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
