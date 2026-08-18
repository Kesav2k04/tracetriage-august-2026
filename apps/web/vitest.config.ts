import path from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Vitest covers the pure functions under lib/, which is where every coordinate bug
 * in this console has lived: the pole seam, the antimeridian unwrap, the negative
 * elevation sample. Those functions import nothing by design, so they need no DOM,
 * no React and no jsdom, which is why the environment stays node and there is no
 * setup file to keep in sync.
 *
 * Components are deliberately out of scope here. A component test would need a DOM
 * and would mostly assert markup, while `next build` already fails on a component
 * that cannot render and `tsc --noEmit` already fails on a wrong prop. The gap this
 * closes is the arithmetic, not the rendering.
 */
export default defineConfig({
  // The same "@/" alias next.config and tsconfig use, so a test imports a module
  // by the path the application imports it by. Without this a component helper
  // could only be tested by a relative path that the app itself never uses.
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname) },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // A pure-function suite that takes longer than this is doing something it should
    // not be doing.
    testTimeout: 5_000,
  },
});
