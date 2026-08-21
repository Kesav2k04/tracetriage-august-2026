/**
 * Deep-field probe: whether the background is drawing, arriving, and receding.
 *
 * Paste into a browser console on the landing page, or evaluate it through a driver. It
 * returns JSON rather than logging, so a caller can assert on it.
 *
 * It exists because every cheap way of checking a WebGL canvas is wrong here.
 *
 * The DOM proves nothing: a failed context, a failed compile, a program that did not link
 * and a spiral placed outside clip space all leave an identical `<canvas>` behind, and
 * three of those four have happened to this component. The most recent was a link failure
 * from one uniform declared `mediump` in the fragment stage and `highp` by default in the
 * vertex stage.
 *
 * A screenshot proves little more: this canvas is full-width behind the hero, so a shot of
 * it contains the nav, the heading and the kill-gate table, and a change in any of those
 * moves the pixels.
 *
 * And a single pixel count is not a measurement. The field animates on its own: points
 * swim on a sine of their measured Doppler offset, so the number of lit pixels at any
 * instant is a sample from a distribution rather than a property of the frame. The first
 * attempt at this compared one sample at the top of the page against one sample after a
 * scroll, on a build where the recession did not exist yet, and the count fell 16% anyway.
 *
 * So the probe samples repeatedly at each scroll position and reports the range. Two
 * ranges that overlap are not a difference. It also reads the two values the component
 * writes to the canvas element as it draws, which is the only channel that says what a
 * uniform was actually set to.
 */
(async () => {
  const SAMPLES = 6;
  const GAP_MS = 130;
  const SETTLE_MS = 2600;
  /** Downsampled: this is a count of lit regions, not an image comparison. */
  const W = 320;
  const H = 200;

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const canvas = document.querySelector("canvas.deep-field");
  if (!canvas) {
    return { error: "no canvas.deep-field on this page" };
  }

  const scratch = document.createElement("canvas");
  scratch.width = W;
  scratch.height = H;
  const ctx = scratch.getContext("2d");

  /**
   * Lit pixels in one frame of the canvas.
   *
   * `drawImage` from the live canvas rather than `readPixels` on its own context: the
   * component keeps its drawing buffer, but a readback through the same context has
   * returned black on this machine before, and the compositor's copy is what a reader
   * sees.
   */
  const litNow = () => {
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(canvas, 0, 0, W, H);
    const data = ctx.getImageData(0, 0, W, H).data;
    let lit = 0;
    let alpha = 0;
    for (let i = 3; i < data.length; i += 4) {
      alpha += data[i];
      if (data[i] > 6) lit += 1;
    }
    return { lit, meanAlpha: alpha / (data.length / 4) };
  };

  const series = async () => {
    const lit = [];
    const alpha = [];
    for (let i = 0; i < SAMPLES; i += 1) {
      const sample = litNow();
      lit.push(sample.lit);
      alpha.push(sample.meanAlpha);
      await wait(GAP_MS);
    }
    const sorted = [...lit].sort((a, b) => a - b);
    return {
      samples: SAMPLES,
      lit_min: sorted[0],
      lit_median: sorted[Math.floor(SAMPLES / 2)],
      lit_max: sorted[SAMPLES - 1],
      mean_alpha: Number((alpha.reduce((a, b) => a + b, 0) / SAMPLES).toFixed(3)),
      reported_scroll: canvas.dataset.fieldScroll ?? null,
      reported_drawn: canvas.dataset.fieldDrawn ?? null,
    };
  };

  window.scrollTo(0, 0);
  await wait(SETTLE_MS);
  const top = await series();

  window.scrollTo(0, Math.round(window.innerHeight * 0.8));
  await wait(700);
  const scrolled = await series();
  window.scrollTo(0, 0);

  const overlap = top.lit_min <= scrolled.lit_max && scrolled.lit_min <= top.lit_max;
  return {
    drew: top.reported_drawn !== null,
    points_drawn: top.reported_drawn === null ? null : Number(top.reported_drawn),
    scroll_channel_present: top.reported_scroll !== null,
    scroll_channel_moved:
      top.reported_scroll !== null &&
      scrolled.reported_scroll !== null &&
      Number(scrolled.reported_scroll) > Number(top.reported_scroll),
    at_top: top,
    at_scroll: scrolled,
    recession_measured: !overlap,
    reading: overlap
      ? "The lit ranges at the two scroll positions overlap, so this run does not " +
        "establish a recession. That is the honest answer when it happens: the field " +
        "animates on its own and one sample either side proves nothing."
      : "The lit ranges at the two scroll positions do not overlap, so the field is " +
        "measurably dimmer once the hero has left, beyond its own animation.",
  };
})();
