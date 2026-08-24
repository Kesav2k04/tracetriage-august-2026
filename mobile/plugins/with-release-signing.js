/**
 * Sign the release build with a real key, without committing one.
 *
 * `expo prebuild` generates `android/` from `app.json`, and the template it generates points
 * the release build type at the debug keystore with a comment telling you to fix it. Fixing
 * it by hand works exactly once: the directory is generated, it is gitignored for that
 * reason, and the next prebuild silently restores the debug key. An APK signed with the
 * public debug key is not a release, it is a build that anybody can forge an update to.
 *
 * So the fix belongs in the generator. This is a config plugin: prebuild runs it over the
 * generated `app/build.gradle`, so the signing config exists in every regeneration and there
 * is nothing to remember.
 *
 * The key itself is never here and never in the repository. Four Gradle properties name it,
 * passed on the command line by `mobile/build-apk.ps1` from a keystore kept outside the tree:
 *
 *   TRACETRIAGE_STORE_FILE      absolute path to the .jks
 *   TRACETRIAGE_STORE_PASSWORD
 *   TRACETRIAGE_KEY_ALIAS
 *   TRACETRIAGE_KEY_PASSWORD
 *
 * When they are absent the release build falls back to the debug key, which is what a fork
 * cloning this repository needs: `gradlew assembleRelease` still produces a working APK for
 * them, it is simply not signed as this project. A hard failure would have meant nobody else
 * could build the thing at all, and a silent debug-signed release with no way to tell is the
 * defect this whole file exists to remove. The APK's signer is therefore checked after the
 * build rather than assumed: `build-apk.ps1` runs `apksigner verify --print-certs` and
 * compares the SHA-256 against the fingerprint recorded in `mobile/README.md`.
 */

const { withAppBuildGradle } = require("expo/config-plugins");

/** Unique to the release block in the generated file, which is why it is the anchor. */
const RELEASE_ANCHOR = "            // Caution! In production, you need to generate your own keystore file.";

const SIGNING_CONFIG = `        release {
            // Set by mobile/plugins/with-release-signing.js. Absent properties mean an
            // unsigned-by-this-project build, which is the fallback the release buildType
            // below selects explicitly rather than by accident.
            if (project.hasProperty('TRACETRIAGE_STORE_FILE')) {
                storeFile file(project.property('TRACETRIAGE_STORE_FILE'))
                storePassword project.property('TRACETRIAGE_STORE_PASSWORD')
                keyAlias project.property('TRACETRIAGE_KEY_ALIAS')
                keyPassword project.property('TRACETRIAGE_KEY_PASSWORD')
            }
        }
`;

const RELEASE_SELECTOR = `            // Signed with this project's key when it is available, and with the debug key
            // when it is not, so a fork can still build. mobile/build-apk.ps1 verifies which
            // one actually signed the output.
            signingConfig project.hasProperty('TRACETRIAGE_STORE_FILE') ? signingConfigs.release : signingConfigs.debug
`;

function patch(contents) {
  if (contents.includes("TRACETRIAGE_STORE_FILE")) {
    return contents;
  }

  // 1. Add the release signing config beside the debug one. Anchored on the closing brace of
  //    the debug block inside signingConfigs, found by locating that block rather than by
  //    matching whitespace, because the template's indentation has changed between SDKs.
  const marker = "    signingConfigs {\n";
  const at = contents.indexOf(marker);
  if (at === -1) {
    throw new Error(
      "with-release-signing: no signingConfigs block in app/build.gradle. The Expo template "
        + "changed shape, so this plugin needs reading before the next release is trusted.",
    );
  }
  const debugEnd = contents.indexOf("        }\n", at + marker.length);
  if (debugEnd === -1) {
    throw new Error("with-release-signing: could not find the end of the debug signingConfig");
  }
  const insertAt = debugEnd + "        }\n".length;
  let out = contents.slice(0, insertAt) + SIGNING_CONFIG + contents.slice(insertAt);

  // 2. Point the release build type at it. `signingConfig signingConfigs.debug` appears
  //    twice, once for each build type, so the replacement is anchored on the caution comment
  //    that only the release block carries. Replacing the wrong one would leave a release
  //    signed by debug and a debug build that fails on a machine with no keystore.
  const anchorAt = out.indexOf(RELEASE_ANCHOR);
  if (anchorAt === -1) {
    throw new Error(
      "with-release-signing: the release block's caution comment is gone, so the anchor this "
        + "plugin replaces on is unreliable. Read app/build.gradle before shipping an APK.",
    );
  }
  const lineEnd = out.indexOf("signingConfig signingConfigs.debug\n", anchorAt);
  if (lineEnd === -1) {
    throw new Error("with-release-signing: release buildType no longer selects the debug key");
  }
  const lineStart = out.lastIndexOf("\n", lineEnd) + 1;
  out =
    out.slice(0, lineStart)
    + RELEASE_SELECTOR
    + out.slice(lineEnd + "signingConfig signingConfigs.debug\n".length);

  return out;
}

module.exports = function withReleaseSigning(config) {
  return withAppBuildGradle(config, (inner) => {
    if (inner.modResults.language !== "groovy") {
      throw new Error(
        `with-release-signing: expected a Groovy build.gradle, got ${inner.modResults.language}`,
      );
    }
    inner.modResults.contents = patch(inner.modResults.contents);
    return inner;
  });
};

// Exported for `mobile/plugins/with-release-signing.test.js`, which runs the patch over the
// generated file and over a copy with the anchor removed, so the throw is exercised too.
module.exports.patch = patch;
