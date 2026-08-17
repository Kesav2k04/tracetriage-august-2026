/**
 * Accessibility probe for the evidence console (unit C6).
 *
 * Paste into a browser console on any page of the console, or evaluate it
 * through a driver. It returns JSON rather than logging, so a caller can assert
 * on it.
 *
 * It measures four things and refuses to guess at any of them:
 *
 *   1. Contrast, for every text node that actually paints text. The background
 *      is resolved by walking up until an opaque colour is found, because a
 *      transparent element reports "rgba(0, 0, 0, 0)" and comparing text against
 *      that scores every page as perfect. Nodes with no rendered box, no visible
 *      text, or zero size are excluded and counted, so an empty result reads as
 *      "nothing was measured" instead of "everything passed".
 *   2. Whether every interactive element is reachable by keyboard and shows a
 *      focus ring, by focusing each one and reading the computed outline.
 *   3. Whether every image, canvas and SVG carries a text alternative.
 *   4. Whether headings descend without skipping a level, and whether the page
 *      has exactly one h1.
 *
 * A ratio of exactly 1.00 everywhere means the page had not painted when this
 * ran, not that the palette collapsed. Scroll the page first.
 */
(() => {
  const parse = (value) => {
    const m = String(value).match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const parts = m[1].split(",").map((p) => parseFloat(p.trim()));
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };

  const luminance = ({ r, g, b }) => {
    const channel = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };

  const over = (fg, bg) => {
    const a = fg.a;
    return {
      r: fg.r * a + bg.r * (1 - a),
      g: fg.g * a + bg.g * (1 - a),
      b: fg.b * a + bg.b * (1 - a),
      a: 1,
    };
  };

  const ratio = (a, b) => {
    const la = luminance(a);
    const lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };

  /** The first opaque background behind an element, compositing what is above it. */
  const backgroundOf = (element) => {
    const stack = [];
    let node = element;
    while (node && node !== document.documentElement) {
      const colour = parse(getComputedStyle(node).backgroundColor);
      if (colour && colour.a > 0) {
        stack.push(colour);
        if (colour.a === 1) break;
      }
      node = node.parentElement;
    }
    let base = parse(getComputedStyle(document.documentElement).backgroundColor);
    if (!base || base.a === 0) base = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = stack.length - 1; i >= 0; i -= 1) base = over(stack[i], base);
    return base;
  };

  const contrast = { pass: 0, fail: [], skipped: 0 };

  for (const element of document.querySelectorAll("body *")) {
    const text = [...element.childNodes]
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.textContent.trim())
      .join("")
      .trim();
    if (!text) {
      contrast.skipped += 1;
      continue;
    }
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    if (
      style.visibility === "hidden" ||
      style.display === "none" ||
      Number(style.opacity) === 0 ||
      box.width === 0 ||
      box.height === 0
    ) {
      contrast.skipped += 1;
      continue;
    }

    const fg = parse(style.color);
    if (!fg) {
      contrast.skipped += 1;
      continue;
    }
    const bg = backgroundOf(element);
    const value = ratio(over(fg, bg), bg);

    const size = parseFloat(style.fontSize);
    const weight = Number(style.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const required = large ? 3 : 4.5;

    if (value + 1e-9 < required) {
      contrast.fail.push({
        text: text.slice(0, 60),
        tag: element.tagName.toLowerCase(),
        colour: style.color,
        background: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`,
        fontSize: size,
        ratio: Number(value.toFixed(2)),
        required,
      });
    } else {
      contrast.pass += 1;
    }
  }

  // ---- keyboard reachability and focus visibility -------------------------
  const focusable = [
    ...document.querySelectorAll(
      'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"])',
    ),
  ];
  const active = document.activeElement;
  const noFocusRing = [];
  for (const element of focusable) {
    element.focus();
    if (document.activeElement !== element) {
      noFocusRing.push({ tag: element.tagName.toLowerCase(), reason: "did not take focus" });
      continue;
    }
    const style = getComputedStyle(element);
    const outline =
      style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
    const ring = outline || style.boxShadow !== "none";
    if (!ring) {
      noFocusRing.push({
        tag: element.tagName.toLowerCase(),
        label: (element.textContent || element.getAttribute("aria-label") || "").slice(0, 40),
        reason: "focused with no visible ring",
      });
    }
  }
  if (active instanceof HTMLElement) active.focus();

  // ---- text alternatives ---------------------------------------------------
  const unlabelled = [];
  for (const element of document.querySelectorAll("img, canvas, svg, video")) {
    if (element.getAttribute("aria-hidden") === "true") continue;
    const label =
      element.getAttribute("alt") ??
      element.getAttribute("aria-label") ??
      element.querySelector("title")?.textContent;
    if (!label || !label.trim()) {
      unlabelled.push(element.tagName.toLowerCase());
    }
  }

  // ---- heading order -------------------------------------------------------
  const levels = [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((h) =>
    Number(h.tagName[1]),
  );
  const skips = [];
  for (let i = 1; i < levels.length; i += 1) {
    if (levels[i] - levels[i - 1] > 1) {
      skips.push(`h${levels[i - 1]} to h${levels[i]}`);
    }
  }

  return {
    url: location.pathname,
    contrast: {
      measured: contrast.pass + contrast.fail.length,
      passed: contrast.pass,
      failed: contrast.fail.length,
      skipped_no_text_or_no_box: contrast.skipped,
      failures: contrast.fail,
    },
    keyboard: {
      focusable: focusable.length,
      problems: noFocusRing,
    },
    alternatives: { unlabelled },
    headings: { count: levels.length, h1: levels.filter((l) => l === 1).length, skips },
  };
})();
