/**
 * Which licensed faces a page renders, and whether any of them was still loading.
 *
 * Same shape as the other probes in this directory: paste it into a browser console
 * on any console page, or evaluate it through a driver, and it returns JSON rather
 * than logging, so a caller can assert on it.
 *
 * It exists because of the fix in `app/layout.tsx`. The Adobe kit declares the two
 * faces this console uses at `font-display: auto`, which holds text unpainted for up
 * to three seconds, so the licensed families are kept out of `--font-display` and
 * `--font-label` until a head script has loaded them and added `html.fonts-ready`.
 * That trades one failure for another if the loaded set is wrong: a weight the head
 * script does not name is a weight that starts its block period at the moment the
 * class lands, which is after the reader has begun reading. A blank first screen is
 * at least obvious. Text vanishing under the cursor is not.
 *
 * So the finding is `rendered_unwaited`: a licensed face this page renders that the
 * head script did not wait for. The script publishes what it waited for in
 * `data-fonts` on the root element, which is why this probe compares against that
 * attribute rather than against its own copy of the list. A copy would agree with a
 * wrong list as happily as with a right one.
 *
 * `rendered_unloaded` is the same question asked at the wrong moment, and it is here
 * to show why the attribute is needed. Anything rendered has finished loading by the
 * time a reader could run this, so that list is empty either way: the first version
 * of the head script waited for `neue-haas-grotesk-display 400`, which no page
 * renders, and never waited for `din-2014-narrow 400`, which three pages do. Every
 * page reported clean. `rendered_unwaited` named it immediately.
 *
 * Two things it deliberately does not do. It does not judge the first paint, which
 * `paint-probe.js` reports and which depends on the connection. And it does not read
 * the kit's stylesheet: `cssRules` throws on a cross-origin sheet, so every fact
 * about a face comes from `document.fonts`, which is same-origin by definition.
 *
 * Run it after the fonts have settled. Called during the load it will report the
 * class as absent and every face as unwaited, which is the truth at that instant and
 * not the question being asked.
 */
(() => {
  const LICENSED = ["neue-haas-grotesk-display", "din-2014-narrow"];

  // The faces the browser knows about, keyed the way a computed style names them.
  // `document.fonts` holds one FontFace per @font-face rule the kit declared, which
  // is 22 for these two families across every weight and both slopes, so a key has
  // to carry the weight or six of them collapse into one.
  const known = new Map();
  document.fonts.forEach((face) => {
    const family = face.family.replace(/^["']|["']$/g, "");
    if (!LICENSED.includes(family)) return;
    known.set(`${family} ${face.weight} ${face.style}`, face.status);
  });

  // Every element that paints text of its own. Same test as `paint-probe.js` and for
  // the same reason: a wrapper holds the text of everything under it and would report
  // a family for content it does not draw, so what counts is a direct child text node.
  const paints = [...document.querySelectorAll("body *")].filter((el) =>
    [...el.childNodes].some(
      (n) => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0,
    ),
  );

  const rendered = new Map();
  for (const el of paints) {
    const style = getComputedStyle(el);
    const first = style.fontFamily.split(",")[0].trim().replace(/^["']|["']$/g, "");
    if (!LICENSED.includes(first)) continue;
    // The computed weight is a number here even when the author wrote a keyword, and
    // it is the weight the face lookup uses, so it is the half of the key that the
    // family name does not carry.
    const key = `${first} ${style.fontWeight} ${style.fontStyle}`;
    const seen = rendered.get(key) || { n: 0, example: null };
    seen.n += 1;
    if (!seen.example) {
      seen.example = el.tagName.toLowerCase()
        + (el.className && typeof el.className === "string"
          ? `.${el.className.split(/\s+/)[0]}`
          : "");
    }
    rendered.set(key, seen);
  }

  // What the head script actually waited for, in the same `family weight style` key
  // the rendered set uses. The shorthand it publishes is a CSS font value, so the
  // family is at the end and the weight at the front, and only the normal slope is
  // ever requested: an italic licensed face would show up as unwaited, which is the
  // correct answer, because none is loaded.
  const waited = new Set(
    (document.documentElement.getAttribute("data-fonts") || "")
      .split("|")
      .filter(Boolean)
      .map((shorthand) => {
        const weight = shorthand.trim().split(/\s+/)[0];
        const family = shorthand.slice(shorthand.indexOf('"') + 1, shorthand.lastIndexOf('"'));
        return `${family} ${weight} normal`;
      }),
  );

  const rows = [...rendered.entries()].map(([key, seen]) => ({
    face: key,
    elements: seen.n,
    first_example: seen.example,
    // `undefined` means the kit declared no such face, so the browser synthesises
    // from a neighbour and nothing blocks. Reporting it apart from "loaded" matters,
    // because the two look identical on the page and only one of them is a request.
    status: known.has(key) ? known.get(key) : "not-in-the-kit",
    waited_for: waited.has(key),
  }));
  rows.sort((a, b) => b.elements - a.elements);

  return {
    url: location.pathname,
    fonts_ready: document.documentElement.classList.contains("fonts-ready"),
    n_licensed_faces_declared: known.size,
    n_licensed_faces_loaded: [...known.values()].filter((s) => s === "loaded").length,
    rendered_licensed_faces: rows,
    faces_waited_for: [...waited],
    // The finding. Empty is the passing state.
    rendered_unwaited: rows
      .filter((r) => !r.waited_for && r.status !== "not-in-the-kit")
      .map((r) => r.face),
    // The same question asked too late to answer it. Kept because a reader who does
    // not know that will ask it, and an empty list next to a full one is the clearest
    // way to say why the attribute above is the instrument.
    rendered_unloaded: rows
      .filter((r) => r.status !== "loaded" && r.status !== "not-in-the-kit")
      .map((r) => r.face),
    // Present so a caller can tell "the class never landed" apart from "the class
    // landed and a weight was missing". The first is a blocked host or JavaScript
    // off, and the console is complete in Plex either way. The second is the defect
    // this file was written to catch.
    reading: document.documentElement.classList.contains("fonts-ready")
      ? "the licensed faces are in use"
      : "the console is in Plex: either the kit did not load or the fonts have not settled yet",
    first_contentful_paint_ms: Math.round(
      (performance.getEntriesByName("first-contentful-paint")[0] || { startTime: -1 })
        .startTime,
    ),
  };
})();
