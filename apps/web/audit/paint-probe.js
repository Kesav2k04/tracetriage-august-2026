/**
 * First-paint probe for the evidence console.
 *
 * Same shape as `a11y-probe.js` and `motion-probe.js`: paste into a browser console
 * on any page, or evaluate it through a driver, and it returns JSON rather than
 * logging so a caller can assert on it.
 *
 * It exists because of one measurement. The landing page's first contentful paint
 * was 956 ms from a local static server with no network in the way, against 152 ms
 * with the licensed font host blocked. Nothing else in this repository could see
 * that: the build succeeds, the type check passes, every test passes, both other
 * probes report clean, and the page is blank for most of a second.
 *
 * The cause is `font-display`, which is a property of a stylesheet this project does
 * not write. The Adobe Fonts kit declares 72 of its 90 faces at `font-display: auto`,
 * and auto means Chrome will hold text unpainted for up to three seconds while the
 * face loads. The two self-hosted faces are `font-display: swap` and hold nothing. So
 * the one number that predicts a blank first screen is not a byte count or a request
 * count: it is whether a face used in the first viewport is set to block.
 *
 * As of 2026-08-21 that number is zero on every page and this probe will say so,
 * because the licensed families are no longer named in `--font-display` or
 * `--font-label` until a head script has loaded them. `blocking_faces` reports what
 * the reader was held by, and after the fix nobody is held: 596 ms to 236 ms against a
 * 200 ms floor, in `artifacts/FONT_PAINT_RECEIPT.json`. Two consequences for anyone
 * reading this probe's output. An empty `blocking_faces` no longer means the kit's
 * descriptors are safe, only that no face the first viewport uses is waiting on one,
 * which is why `families` lists every face with its `display` descriptor rather than
 * only the ones that block. And the question this file cannot answer is now the one
 * that matters: whether the head script waited for every face the page renders.
 * `font-swap-probe.js` answers that one.
 *
 * That is what this reports. `document.fonts` exposes every FontFace with its
 * `display` descriptor and its load status, and the first viewport's computed
 * families say which of them the reader is actually waiting on. A face at auto or
 * block that is loaded and used above the fold is the finding.
 *
 * Three things it does not do. It does not decide what an acceptable first paint is,
 * because that depends on the connection and this returns one draw from it. It cannot
 * read the rules of a cross-origin stylesheet, so `blocking_faces` is built from
 * `document.fonts` rather than from `cssRules`, which throws on the kit. And it has no
 * way to tell a cold load from a warm one: run against three pages in one browser and
 * the first reports 1628 ms while the next two report about 200 ms, because they took
 * the faces out of the HTTP cache. The first visit is the one that matters and it is
 * the only one a fresh browser measures, so `first_contentful_paint` is a single draw
 * whose cache state the caller has to know. `blocking_faces` does not have that
 * problem: a face set to block is set to block whether it was cached or not, which is
 * why the font list is the finding and the millisecond count is the symptom.
 */
(() => {
  const paints = Object.fromEntries(
    performance.getEntriesByType("paint").map((p) => [p.name, Math.round(p.startTime)]),
  );
  const nav = performance.getEntriesByType("navigation")[0];

  // Families the reader is looking at before scrolling. The first entry of the
  // computed stack is the one that decides whether text is held, because a later
  // fallback is only reached once the browser gives up on the one in front of it.
  //
  // Every element with text of its own, not a list of tags. This asked
  // `h1, h2, h3, h4, p, a, span, li, td, th` until a review pointed out what that
  // misses: `dt`, `dd`, `button`, `label`, `figcaption`, `caption`. The home page's
  // hero readout is a `<dl>` whose `<dt>` sets the Adobe-hosted label face, above the
  // fold, in the same component this file's docstring is about. It did not change the
  // answer, because two nearby `<p>` elements happen to use the same family, and that
  // is exactly the problem: the probe was right by coincidence. A longer tag list would
  // be the same defect with a longer list, so the test is now the thing actually being
  // asked, which is whether the element paints text.
  //
  // `el.textContent` is not that test: a `<div>` wrapping the whole page has the text
  // of everything under it and would report the wrapper's inherited family for content
  // it does not paint. A direct child text node is what an element renders itself.
  const paintsText = (el) => {
    for (const node of el.childNodes) {
      if (node.nodeType === 3 && node.nodeValue && node.nodeValue.trim()) return true;
    }
    return false;
  };
  const SKIP = new Set(["SCRIPT", "STYLE", "TITLE", "NOSCRIPT", "TEMPLATE", "OPTION"]);

  const firstScreen = new Set();
  for (const el of document.querySelectorAll("body *")) {
    if (SKIP.has(el.tagName) || !paintsText(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.top > window.innerHeight || r.bottom < 0 || r.width === 0 || r.height === 0) {
      continue;
    }
    const style = getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") continue;
    const family = style.fontFamily.split(",")[0].replace(/["']/g, "").trim();
    if (family) firstScreen.add(family);
  }

  const faces = [];
  document.fonts.forEach((f) =>
    faces.push({
      family: f.family,
      weight: f.weight,
      style: f.style,
      display: f.display,
      status: f.status,
    }),
  );

  // One row per family, because a kit declares dozens of faces per family and the
  // reader waits on families.
  const byFamily = new Map();
  for (const f of faces) {
    const row = byFamily.get(f.family) || {
      family: f.family,
      faces: 0,
      loaded: 0,
      displays: new Set(),
    };
    row.faces += 1;
    if (f.status === "loaded") row.loaded += 1;
    row.displays.add(f.display);
    byFamily.set(f.family, row);
  }

  const BLOCKS = new Set(["auto", "block"]);
  const families = [...byFamily.values()].map((r) => ({
    family: r.family,
    faces: r.faces,
    loaded: r.loaded,
    display: [...r.displays].sort().join("|"),
    in_first_viewport: firstScreen.has(r.family),
    blocks_paint: r.loaded > 0 && firstScreen.has(r.family) && [...r.displays].some((d) => BLOCKS.has(d)),
  }));

  const resources = performance
    .getEntriesByType("resource")
    .filter((r) => r.initiatorType === "css" || r.name.endsWith(".woff2") || r.name.includes("typekit"))
    .map((r) => ({
      url: r.name.length > 90 ? r.name.slice(0, 90) + "..." : r.name,
      kind: r.initiatorType,
      start: Math.round(r.startTime),
      end: Math.round(r.responseEnd),
      transfer_bytes: r.transferSize || null,
    }));

  const blocking = families.filter((f) => f.blocks_paint);

  return {
    url: location.pathname,
    paint: {
      first_paint: paints["first-paint"] ?? null,
      first_contentful_paint: paints["first-contentful-paint"] ?? null,
      dom_content_loaded: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
      load: nav ? Math.round(nav.loadEventEnd) : null,
      html_response_end: nav ? Math.round(nav.responseEnd) : null,
      reading:
        paints["first-contentful-paint"] == null
          ? "no contentful paint recorded; this ran before the page painted"
          : "the gap between html_response_end and first_contentful_paint is what a " +
            "reader waits with nothing on screen",
    },
    fonts: {
      families: families.sort((a, b) => Number(b.blocks_paint) - Number(a.blocks_paint)),
      blocking_faces: blocking.map((f) => f.family),
      reading: blocking.length
        ? `${blocking.length} font family(ies) used in the first viewport are set to ` +
          `block: ${blocking.map((f) => f.family).join(", ")}. Text stays unpainted ` +
          `until each one arrives or the browser's block period expires.`
        : "no font family used in the first viewport is set to block, so no face " +
          "holds the first paint",
    },
    resources,
  };
})();
