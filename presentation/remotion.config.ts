import { Config } from "@remotion/cli/config";

/**
 * The film renders out of a workspace that is a sibling of the repository, not a
 * directory inside it. Its narration is a voice recording and its output is a fifteen
 * mp4 tens of megabytes long, and neither belongs in a clone; the film is published as a
 * link instead.
 *
 * The console's own assets are copied into that workspace from the tracked files by
 * scripts/film_workspace.py before every render, so staticFile() still serves the exact
 * waterfall the site ships and there is no second copy here to fall out of date.
 * TRACETRIAGE_FILM_LOCAL moves the whole workspace; everything that reads or writes any
 * part of it resolves the same way.
 */
Config.setPublicDir(
  process.env.TRACETRIAGE_FILM_LOCAL
    ? `${process.env.TRACETRIAGE_FILM_LOCAL}/public`
    : "../../film-local/public",
);
// PNG intermediates rather than JPEG: this film is almost entirely small type on
// a dark ground, which is exactly where JPEG ringing shows. It also keeps the
// output in limited-range yuv420p instead of the full-range yuvj420p a JPEG
// pipeline produces, which some players level-shift.
Config.setVideoImageFormat("png");
Config.setPixelFormat("yuv420p");
Config.setCodec("h264");
Config.setOverwriteOutput(true);

// Fixed rather than left to the machine: the GL renderer changes antialiasing, and
// two runs of this file at different concurrencies produce a byte-identical mp4
// only when it is pinned. Measured: md5 7b5fa3ff at concurrency 4 and at 2 with
// this line, a different digest without it.
Config.setChromiumOpenGlRenderer("angle");
