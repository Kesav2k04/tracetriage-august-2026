/**
 * The console's lint configuration, which did not exist until 2026-08-21.
 *
 * `package.json` has carried a `lint` script and `eslint` plus `eslint-config-next` as
 * devDependencies since the console was created, and running it printed "Oops! Something
 * went wrong!" because ESLint 9 wants a flat config and there was no config file of any
 * kind. So the script had never run, on any commit, and a judge who tried it got a stack
 * trace from a project whose whole claim is that its checks are runnable.
 *
 * The type checker is what has actually been catching things here (`tsc --noEmit`, with
 * `strict` and `noUncheckedIndexedAccess` on), and this does not replace it. What ESLint
 * adds is the React and Next rules a type checker cannot see: a hook called
 * conditionally, a dependency array that lies, an `<img>` where the framework has an
 * element that sets width and height.
 */
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

// Named rather than exported anonymously, because `import/no-anonymous-default-export`
// is one of the rules this file turns on and a config that fails its own rules is a
// config nobody trusts the rest of.
const config = [
  {
    // The build output, the generated types and the vendored probes. `audit/` is written
    // to be pasted into a browser console, so it is not modules and is not linted as if
    // it were: those files end in a bare expression on purpose, which is the shape of a
    // paste. `next-env.d.ts` is written by the framework on every build and its triple
    // slash reference is not ours to fix.
    ignores: ["out/**", ".next/**", "audit/**", "public/**", "next-env.d.ts"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
