/**
 * First paint and layout shift across the three font-loading conditions.
 *
 * `scripts/build_font_ab.py` writes the three directories and says which port each
 * one wants. This drives a browser at them, interleaved, with a fresh context per
 * navigation, and prints the JSON that goes into `artifacts/FONT_PAINT_RECEIPT.json`.
 *
 * Interleaved and not one condition at a time, because a machine that gets busier
 * halfway through a run would otherwise be indistinguishable from a change to the
 * page. Fresh context per navigation, because the licensed faces carry a one-year
 * cache header: the second visit measures nothing, which is the trap the note in
 * `paint-probe.js` describes.
 *
 * Two numbers, not one. First contentful paint is what the fix bought. Cumulative
 * layout shift is what it cost: the licensed face replaces Plex in one reflow, and a
 * page that paints sooner and then moves is not obviously better than one that paints
 * later and stays still. Reporting only the number that improved would be the same
 * defect as a build log that lists the tests that passed.
 *
 * Playwright is not a dependency of this project and will not become one for a probe.
 * Run it against an install you already have:
 *
 *     node apps/web/audit/font-paint-ab.mjs
 *
 * If that cannot resolve `playwright`, the body of `measure()` is plain Playwright and
 * runs unchanged in any driver that hands it a `browser`, which is how the committed
 * receipt was produced.
 */

const CONDITIONS = [
  ["after", "http://127.0.0.1:8101/"],
  ["before", "http://127.0.0.1:8102/"],
  ["nokit", "http://127.0.0.1:8103/"],
];
const ROUNDS = 5;
const VIEWPORT = { width: 1440, height: 900 };
// Long enough for the kit to arrive, the faces to load and the reflow they cause to
// be recorded. A shorter settle would report a layout shift that had not happened yet
// as an absence of one.
const SETTLE_MS = 2500;

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};

export async function measure(browser) {
  const runs = [];
  for (let round = 0; round < ROUNDS; round += 1) {
    for (const [name, url] of CONDITIONS) {
      const context = await browser.newContext({ viewport: VIEWPORT });
      const page = await context.newPage();
      // Installed before any document script, because a layout shift observer
      // registered after the shift has already been painted sees nothing. `buffered`
      // covers the gap between navigation and this callback; the init script covers
      // the gap between this file and the navigation.
      await page.addInitScript(() => {
        window.__cls = 0;
        window.__shifts = 0;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (!entry.hadRecentInput) {
              window.__cls += entry.value;
              window.__shifts += 1;
            }
          }
        }).observe({ type: "layout-shift", buffered: true });
      });
      await page.goto(url, { waitUntil: "load", timeout: 20000 });
      await page.waitForTimeout(SETTLE_MS);
      const reading = await page.evaluate(() => ({
        fcp: Math.round(
          (performance.getEntriesByName("first-contentful-paint")[0]
            || { startTime: -1 }).startTime,
        ),
        cls: Math.round((window.__cls || 0) * 10000) / 10000,
        shifts: window.__shifts || 0,
        // The condition names itself. Reading it off the page is what stops a
        // mislabelled port from being reported as a result: `nokit` cannot be ready
        // and `before` cannot be anything else.
        fonts_ready: document.documentElement.classList.contains("fonts-ready"),
        faces_waited_for: document.documentElement.getAttribute("data-fonts"),
      }));
      runs.push({ round, condition: name, ...reading });
      await context.close();
    }
  }

  const summary = {};
  for (const [name] of CONDITIONS) {
    const mine = runs.filter((r) => r.condition === name);
    summary[name] = {
      fcp_ms: mine.map((r) => r.fcp),
      fcp_ms_median: median(mine.map((r) => r.fcp)),
      cls: mine.map((r) => r.cls),
      cls_median: median(mine.map((r) => r.cls)),
      fonts_ready: mine.every((r) => r.fonts_ready),
    };
  }
  return { rounds: ROUNDS, viewport: VIEWPORT, settle_ms: SETTLE_MS, runs, summary };
}

if (import.meta.url === `file://${process.argv[1]?.replace(/\\/g, "/")}`) {
  const { chromium } = await import("playwright");
  const browser = await chromium.launch();
  try {
    console.log(JSON.stringify(await measure(browser), null, 1));
  } finally {
    await browser.close();
  }
}
