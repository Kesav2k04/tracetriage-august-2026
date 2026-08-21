import { Config } from "@remotion/cli/config";

/**
 * The film's assets are the console's assets. Pointing the public directory at
 * apps/web/public means staticFile() serves the exact waterfall the console ships,
 * with no copy in this package to fall out of date.
 */
Config.setPublicDir("../apps/web/public");
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
