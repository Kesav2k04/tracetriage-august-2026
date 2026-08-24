/**
 * Does the console actually work with the network switched off.
 *
 * The claim this measures, in the words the README uses: the console installs to a home
 * screen on Android and iOS, and after one visit every page reachable from the rail opens
 * with no network. That sentence has three failure modes a build cannot see.
 *
 *   1. The worker registers, precaches nothing, and the pages 404 offline. A registration
 *      that resolves is not a cache that holds anything.
 *   2. The pages open and render in Times New Roman, because `public/sw.js` stored the
 *      documents and the chunks but not the font files, which are named only inside the
 *      stylesheets. This is the one the two-level discovery in that file exists for, and
 *      it is invisible in a screenshot taken on a warm HTTP cache.
 *   3. A page that was never precached opens as a browser error page rather than the
 *      offline fallback, so the reader sees Chrome's dinosaur instead of a list of the
 *      pages that do work.
 *
 * So the probe asserts on all three: what the caches hold, whether each document renders
 * its own heading offline, and whether the two self-hosted faces report as loaded.
 *
 * Playwright is not a dependency of this project and will not become one for a probe, the
 * same arrangement as `font-paint-ab.mjs`. Point it at an install you already have:
 *
 *     python -m http.server --directory apps/web/out 4173
 *     node apps/web/audit/offline-probe.mjs [http://127.0.0.1:4173] [--receipt]
 *
 * It prints JSON and exits non-zero if any document fails offline. With `--receipt` it also
 * writes `artifacts/OFFLINE_RECEIPT.json`, which `tests/test_pwa_install.py` reads: the
 * routes the receipt covers have to still be the routes the site has, so adding a page
 * without re-measuring it offline fails rather than passing quietly. Nothing in that
 * receipt is retyped by hand, which is the only way a number in it stays true.
 */

import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

/** Where a Playwright install might be, in the order worth trying. */
const CANDIDATES = [
  "playwright",
  "D:/dev-cache/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright",
];

function loadPlaywright() {
  for (const id of CANDIDATES) {
    try {
      return require(id);
    } catch {
      // Next candidate. The last failure is reported below with all of them named, so a
      // reader knows what to install rather than seeing one path they do not have.
    }
  }
  throw new Error(
    `cannot resolve playwright. Tried: ${CANDIDATES.join(", ")}. `
      + "Install it anywhere and re-run, or set the path in CANDIDATES.",
  );
}

const args = process.argv.slice(2);
const WRITE_RECEIPT = args.includes("--receipt");
const BASE = args.find((a) => !a.startsWith("--")) || "http://127.0.0.1:4173";

/** Every page in the rail. */
const PAGES = ["/", "/start/", "/live/", "/evaluation/", "/agent/", "/precedent/",
  "/replay/", "/provenance/"];

/** The built export, which is what a deployment serves and what the worker precached. */
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "out");

/**
 * The heading the built file carries for a route, read off disk rather than typed here.
 *
 * The first version of this probe compared each page against a word a reader would expect
 * to see on it, and reported `/replay/` as broken offline. The page was fine. It renders
 * "The queue against the baselines" and never says "Replay" anywhere in its body text, so
 * the probe was asserting on my expectation of the site rather than on the site. Reading
 * the heading out of `out/` removes the whole class: the comparison is now between what
 * the deployment serves and what the worker serves with the network gone, and neither side
 * is a string somebody remembered to update.
 */
function builtHeading(path) {
  const file = join(OUT, path === "/" ? "index.html" : join(path, "index.html"));
  const html = readFileSync(file, "utf8");
  const match = /<h1[^>]*>([\s\S]*?)<\/h1>/.exec(html);
  if (!match) throw new Error(`no h1 in ${file}`);
  return match[1].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}

/** The three faces `app/layout.tsx` waits on are licensed and third-party, so an offline
 *  page is expected to render in Plex. These two are self-hosted and must be held. */
const FACES = ['400 1em "IBM Plex Sans"', '400 1em "IBM Plex Mono"'];

async function cacheReport(page) {
  return page.evaluate(async () => {
    const names = await caches.keys();
    const out = {};
    for (const name of names) {
      const cache = await caches.open(name);
      const keys = await cache.keys();
      out[name] = keys.map((r) => new URL(r.url).pathname);
    }
    return out;
  });
}

async function main() {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const browserVersion = browser.version();
  const context = await browser.newContext();
  const page = await context.newPage();

  // First visit, online. The worker installs and precaches here.
  await page.goto(`${BASE}/`, { waitUntil: "load" });
  const registered = await page.evaluate(async () => {
    if (!("serviceWorker" in navigator)) return "unsupported";
    const reg = await navigator.serviceWorker.ready;
    return reg.active ? reg.active.state : "no active worker";
  });

  // Precaching continues after the worker activates: `install` waits on it, but the page
  // resolves `ready` as soon as there is an active worker. Poll the shell cache for the
  // document count rather than sleeping a guessed number of milliseconds.
  let caches_ = {};
  for (let attempt = 0; attempt < 60; attempt += 1) {
    caches_ = await cacheReport(page);
    const shell = caches_["tracetriage-shell"] || [];
    const assets = caches_["tracetriage-assets"] || [];
    if (shell.length >= PAGES.length + 1 && assets.length > 0) break;
    await page.waitForTimeout(250);
  }

  const shell = caches_["tracetriage-shell"] || [];
  const assets = caches_["tracetriage-assets"] || [];
  const fonts = assets.filter((p) => /\.woff2?$/.test(p));

  // Now cut the network. Everything below is served by the worker or not at all.
  await context.setOffline(true);

  const documents = [];
  for (const path of PAGES) {
    const expected = builtHeading(path);
    const fresh = await context.newPage();
    let ok = false;
    let heading = null;
    let facesHeld = null;
    let error = null;
    try {
      const response = await fresh.goto(`${BASE}${path}`, { waitUntil: "load" });
      heading = (await fresh.locator("h1").first().textContent().catch(() => null)) || null;
      const body = await fresh.locator("body").innerText();
      ok = Boolean(response)
        && heading !== null
        && heading.replace(/\s+/g, " ").trim() === expected
        && !body.includes("not held offline");
      facesHeld = await fresh.evaluate(
        (list) => list.map((f) => document.fonts.check(f)),
        FACES,
      );
    } catch (e) {
      error = String(e).split("\n")[0];
    }
    await fresh.close();
    documents.push({ path, offline_ok: ok, heading, expected, faces_held: facesHeld, error });
  }

  // A page that was never precached: an observation nobody opened while online. The
  // expected answer is the fallback, not a browser error page.
  const fallback = await context.newPage();
  let fallbackServed = false;
  try {
    await fallback.goto(`${BASE}/observation/14746092/`, { waitUntil: "load" });
    fallbackServed = (await fallback.locator("body").innerText()).includes("not held offline");
  } catch (e) {
    fallbackServed = false;
    console.error(`fallback navigation threw: ${String(e).split("\n")[0]}`);
  }
  await fallback.close();

  await browser.close();

  const failed = documents.filter((d) => !d.offline_ok);
  const withoutFonts = documents.filter(
    (d) => !d.faces_held || d.faces_held.some((held) => held !== true),
  );
  const report = {
    base: BASE,
    worker_state: registered,
    cached: {
      shell_documents: shell.length,
      static_assets: assets.length,
      font_files: fonts.length,
      runtime: (caches_["tracetriage-runtime"] || []).length,
    },
    documents,
    uncached_page_gets_fallback: fallbackServed,
    verdict: {
      documents_offline: `${documents.length - failed.length}/${documents.length}`,
      documents_with_self_hosted_fonts:
        `${documents.length - withoutFonts.length}/${documents.length}`,
      failed: failed.map((d) => d.path),
    },
  };
  console.log(JSON.stringify(report, null, 2));

  const clean = failed.length === 0 && withoutFonts.length === 0 && fallbackServed;

  if (WRITE_RECEIPT) {
    writeReceipt(report, browserVersion, clean);
  }
  process.exit(clean ? 0 : 1);
}

/**
 * Write the receipt.
 *
 * Every value here comes from the run that just happened or from git. The `reading` lines
 * interpolate the measured counts rather than describing them, so a receipt cannot end up
 * with prose that says eight while its own table says seven.
 */
function writeReceipt(report, browserVersion, clean) {
  const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
  const commit = execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" })
    .trim();
  const receipt = {
    schema: "tracetriage/offline-install",
    schema_version: "0.1.0",
    unit: "counts of pages and cache entries; no timings",
    measured_at_utc: new Date().toISOString().slice(0, 10),
    commit,
    browser: `${browserVersion}, headless`,
    server: "python -m http.server --directory apps/web/out, loopback only",
    harness: {
      worker: "apps/web/public/sw.js",
      manifest: "apps/web/public/manifest.webmanifest",
      measured_by: "apps/web/audit/offline-probe.mjs",
      method:
        "one online visit to /, then the browser context is switched offline and every "
        + "page in the rail is opened in a fresh tab",
    },
    worker_state_after_first_visit: report.worker_state,
    cached: report.cached,
    documents: report.documents.map((d) => ({
      path: d.path,
      offline_ok: d.offline_ok,
      heading_offline: d.heading,
      heading_in_built_export: d.expected,
      self_hosted_faces_held: d.faces_held,
    })),
    uncached_page_gets_fallback: report.uncached_page_gets_fallback,
    verdict: { ...report.verdict, clean },
    reading: [
      `${report.verdict.documents_offline} pages in the rail render their own heading with `
        + "the browser context offline, after a single online visit to the landing page.",
      `${report.cached.static_assets} hashed assets are held, ${report.cached.font_files} of `
        + "them font files. The font count is the one worth watching: those files are named "
        + "only inside the stylesheets, so a worker that precached the documents and the "
        + "chunks would report every page working and render all of them in a system font.",
      report.uncached_page_gets_fallback
        ? "A page that was never visited online falls back to /offline.html, which lists "
          + "the pages that are held, rather than to the browser's own error page."
        : "A page that was never visited online did NOT get the fallback.",
    ],
  };
  const out = join(repo, "artifacts", "OFFLINE_RECEIPT.json");
  writeFileSync(out, `${JSON.stringify(receipt, null, 2)}
`, "utf8");
  console.error(`wrote ${out}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
