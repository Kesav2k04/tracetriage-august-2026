/*
 * The console's service worker.
 *
 * What it is for: a reviewer on a train, on conference wifi, or on a phone that has
 * dropped to one bar can still open every page of this console and read every number on
 * it. Nothing here changes what the console says. It changes whether the console is
 * there to say it.
 *
 * Three rules, and the reason each one is the way round it is.
 *
 * 1. Documents are network-first. The cached copy is a fallback, never a source. That is
 *    what makes this worker safe to ship without a version stamp in its filename: an
 *    online reader always gets the page the deployment currently serves, and the cache
 *    only ever answers when the network did not. A cache-first shell would have needed a
 *    version bumped by hand on every deploy, and the failure mode of forgetting is a
 *    judge reading last week's numbers with no way to tell.
 *
 * 2. Hashed assets are cache-first. Everything under `/_next/static/` carries a content
 *    hash in its name and is served `immutable` (see `vercel.json`), so a hit is correct
 *    by construction. A new build produces new names, which miss and are fetched.
 *
 * 3. Anything that is not a same-origin GET is not touched at all. The live measurement
 *    is a POST to `/api/live`, and it must reach the function or fail honestly. A worker
 *    that answered it from a cache would be reporting a measurement nobody took.
 *
 * The precache list is the eight fixed pages, not all thirty-four: the per-observation
 * pages and their waterfall images are cached as they are visited. So a fresh install
 * gives the whole console offline except individual passes, and a pass you have opened
 * stays available afterwards.
 *
 * Assets are discovered rather than listed. Next hashes its chunk names at build time,
 * so no list written here could survive a build. Instead the precached documents are
 * read back out of the cache and their `/_next/static/` references collected, and the
 * stylesheets among those are read for the `url(...)` fonts they pull in. That is one
 * level deeper than it looks like it needs to be, and it is the level that matters: the
 * self-hosted Plex faces are referenced by the CSS and by nothing in the HTML, so
 * without this step an offline page rendered in a system font.
 */

const SHELL = "tracetriage-shell";
const ASSETS = "tracetriage-assets";
const RUNTIME = "tracetriage-runtime";

/** Every page reachable from the rail, plus the fallback shown when a page is not held. */
const DOCUMENTS = [
  "/",
  "/start/",
  "/live/",
  "/evaluation/",
  "/agent/",
  "/precedent/",
  "/replay/",
  "/provenance/",
  "/offline.html",
];

/** Small, stable, and referenced from metadata rather than from the page body. */
const FIXED = [
  "/manifest.webmanifest",
  "/og.png",
  "/icons/apple-touch-icon.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-512-maskable.png",
];

/**
 * Cap on the visited-as-you-go cache. A waterfall PNG is the largest thing this console
 * serves, so the bound is on entries and is deliberately modest: enough for a session of
 * review, not enough to fill a phone. Oldest out first, which for this cache is the
 * least recently added rather than the least recently used, and the difference does not
 * matter for a cache whose contents are immutable.
 */
const RUNTIME_MAX_ENTRIES = 150;

/** Paths served with a content hash or otherwise safe to answer from cache first. */
const IMMUTABLE_PREFIXES = ["/_next/static/", "/waterfalls/"];

/** Same-origin paths worth keeping once seen, but not worth precaching. */
const RUNTIME_PREFIXES = ["/media/", "/audio/", "/data/", "/gate4/", "/icons/"];

function startsWithAny(path, prefixes) {
  return prefixes.some((prefix) => path.startsWith(prefix));
}

/**
 * Pull every `/_next/static/` URL out of a text body.
 *
 * A regex over markup, which is the wrong tool for arbitrary HTML and the right one
 * here: the input is Next's own static export, the pattern is anchored on a path prefix
 * this project controls, and a false positive costs one 404 that is caught below.
 */
function staticRefs(text) {
  const found = new Set();
  const pattern = /\/_next\/static\/[A-Za-z0-9._\-/]+/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    found.add(match[0]);
  }
  return found;
}

/** The `url(...)` targets inside a stylesheet, which is where the fonts live. */
function cssRefs(text) {
  const found = new Set();
  const pattern = /url\(\s*["']?(\/[^)"']+)["']?\s*\)/g;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    found.add(match[1]);
  }
  return found;
}

/** Cache a list of URLs one at a time, so one missing file cannot fail the install. */
async function cacheEach(cache, urls) {
  await Promise.all(
    [...urls].map(async (url) => {
      try {
        const response = await fetch(url, { cache: "reload" });
        if (response.ok) {
          await cache.put(url, response.clone());
        }
      } catch {
        // Offline mid-install, or a path that no longer exists. Either way the page it
        // belongs to falls back to the network, which is the behaviour without a worker.
      }
    }),
  );
}

async function precache() {
  const shell = await caches.open(SHELL);
  await cacheEach(shell, [...DOCUMENTS, ...FIXED]);

  // Read the documents back out of the cache rather than re-fetching them, so the assets
  // collected are the ones the stored pages actually reference.
  const refs = new Set();
  for (const url of DOCUMENTS) {
    const held = await shell.match(url);
    if (!held) continue;
    for (const ref of staticRefs(await held.text())) refs.add(ref);
  }

  const assets = await caches.open(ASSETS);
  await cacheEach(assets, refs);

  // Second level: the fonts and any other `url(...)` target inside the stylesheets that
  // were just stored. Without this the offline console renders in a system font.
  const nested = new Set();
  for (const ref of refs) {
    if (!ref.endsWith(".css")) continue;
    const held = await assets.match(ref);
    if (!held) continue;
    for (const nestedRef of cssRefs(await held.text())) nested.add(nestedRef);
  }
  await cacheEach(assets, nested);
}

self.addEventListener("install", (event) => {
  event.waitUntil(precache().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, ASSETS, RUNTIME]);
      const names = await caches.keys();
      await Promise.all(names.filter((n) => !keep.has(n)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

/** Keep the runtime cache bounded. Insertion order is the eviction order. */
async function trim(cache) {
  const keys = await cache.keys();
  const excess = keys.length - RUNTIME_MAX_ENTRIES;
  for (let i = 0; i < excess; i += 1) {
    await cache.delete(keys[i]);
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const held = await cache.match(request);
  if (held) return held;
  const response = await fetch(request);
  if (response.ok) {
    // Storing is best effort, and deliberately cannot fail the request it was storing.
    // `cache.put` rejects for a response the Cache API declines to hold, and an
    // unhandled rejection here is not a missing cache entry: it is the promise handed
    // to `respondWith`, so the browser reports a network error for a response that was
    // already fetched and was fine. The reader gets the response either way.
    try {
      await cache.put(request, response.clone());
      if (cacheName === RUNTIME) await trim(cache);
    } catch {
      // Not cacheable. Nothing else follows from that.
    }
  }
  return response;
}

/**
 * A document: the network decides, the cache covers for it.
 *
 * The trailing-slash retry exists because this site is exported with `trailingSlash:
 * true`. Online, `/live` is a 308 to `/live/` and the browser follows it. Offline there
 * is nobody to issue the redirect, so a link or a typed URL without the slash would land
 * on the offline page while the page itself sat in the cache one character away.
 */
async function serveDocument(request) {
  const shell = await caches.open(SHELL);
  try {
    const response = await fetch(request);
    if (response.ok) {
      await shell.put(request, response.clone());
    }
    return response;
  } catch {
    const held = await shell.match(request, { ignoreSearch: true });
    if (held) return held;
    const url = new URL(request.url);
    if (!url.pathname.endsWith("/")) {
      const withSlash = await shell.match(`${url.pathname}/`);
      if (withSlash) return withSlash;
    }
    return (await shell.match("/offline.html")) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // The measurement endpoint answers or it does not. A cached answer would be a
  // measurement attributed to a run that never happened.
  if (url.pathname.startsWith("/api/")) return;

  // Media is left to the browser, and this is the rule the explainer clips needed.
  //
  // A `<video>` does not ask for a file, it asks for bytes: Chrome opens every clip
  // with `Range: bytes=0-` and keeps asking for ranges as the reader scrubs. The
  // network answers 206, and the Cache API refuses to store a 206 by specification, so
  // `cacheFirst` threw inside the handler and the browser saw a network error. Both
  // clips under `/media/` showed their poster and would not play. Answering a range
  // request out of a stored 200 fails for the same reason pointing the other way, so
  // the cache was never the right answer here in either direction.
  //
  // Serving media offline would mean implementing partial content against a stored
  // body. Two clips do not earn that, and the honest fallback for a clip on a dead
  // connection is the poster and the captions, both of which are small, cached by the
  // rules below, and carry what the clip says. So the worker stands aside and the
  // request behaves exactly as it would with no worker installed.
  if (request.headers.has("range")) return;
  if (request.destination === "video" || request.destination === "audio") return;

  if (request.mode === "navigate") {
    event.respondWith(serveDocument(request));
    return;
  }
  if (startsWithAny(url.pathname, IMMUTABLE_PREFIXES)) {
    event.respondWith(cacheFirst(request, ASSETS));
    return;
  }
  if (startsWithAny(url.pathname, RUNTIME_PREFIXES)) {
    event.respondWith(cacheFirst(request, RUNTIME));
  }
});
