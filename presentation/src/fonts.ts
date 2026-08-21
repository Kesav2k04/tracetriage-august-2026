/**
 * The console's own typefaces, from the same packages the console installs.
 *
 * Self-hosted for the same reason apps/web self-hosts them: nothing carrying a
 * number should wait on a third-party request. Loading is held open with
 * delayRender so no frame can be captured in a fallback face, which is how a
 * tabular column ends up misaligned in a finished mp4.
 *
 * `document.fonts.ready` is deliberately NOT awaited here. It resolves once the
 * document has finished its font loading, which needs a layout, and Remotion holds
 * the first paint back until this handle clears: the two wait on each other and the
 * render times out at a frame that has nothing wrong with it. Awaiting the explicit
 * load() calls needs no layout, and returning an empty match is the failure worth
 * catching anyway.
 */

import { cancelRender, continueRender, delayRender } from "remotion";

import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";

const FACES = [
  '400 1rem "IBM Plex Sans"',
  '600 1rem "IBM Plex Sans"',
  '400 1rem "IBM Plex Mono"',
];

/**
 * The retries are not decoration. Measured over three full renders, one group of
 * frames per run stalls here for the whole timeout and is then retried and
 * rendered correctly: frames 1780 to 1783 in one run, 1222 to 1223 and 2434 to
 * 2435 in another. The group is always the size of the concurrency, so it is a
 * page recycle where every tab refetches the bundle and the font requests queue
 * behind it. Two runs at different concurrencies produced a byte-identical file,
 * so the retry recovers rather than papering over a bad frame.
 */
const handle = delayRender("Loading IBM Plex Sans and IBM Plex Mono", {
  timeoutInMilliseconds: 60000,
  retries: 3,
});

Promise.all(FACES.map((face) => document.fonts.load(face)))
  .then((matched) => {
    const missing = FACES.filter((_, i) => matched[i].length === 0);
    if (missing.length > 0) {
      // A render that quietly falls back to the system sans is worse than one
      // that stops and says which face it could not find.
      cancelRender(new Error(`no font matched: ${missing.join(", ")}`));
      return;
    }
    continueRender(handle);
  })
  .catch((error) => cancelRender(error));
