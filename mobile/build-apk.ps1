<#
.SYNOPSIS
  Build and verify the signed release APK, locally, with no cloud build service.

.DESCRIPTION
  Four things this does that a bare `gradlew assembleRelease` does not.

  1. It points JAVA_HOME at Android Studio's bundled JBR. The system Java on the machine this
     was written on is 22, and Gradle with AGP wants 17 to 21: the failure is a stack trace
     about an unsupported class file version that reads like a corrupt dependency.
  2. It passes the keystore as Gradle properties, from a keystore kept outside the repository.
     `plugins/with-release-signing.js` puts a release signingConfig into the generated project
     that reads exactly these four names.
  3. It verifies which key actually signed the output, with `apksigner verify --print-certs`,
     and compares the SHA-256 against the fingerprint this project publishes. Without that
     step a missing property produces a debug-signed APK that installs, runs, looks correct
     and cannot be updated by anyone but the holder of a keystore every Android developer has.
  4. It prints the APK's own SHA-256, which is what goes on the GitHub Release beside the
     file so a download can be checked.

.PARAMETER KeystoreDir
  Where the keystore and its password live. Default D:\tracetriage_keys, outside the tree.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File mobile/build-apk.ps1
#>

param(
  [string]$KeystoreDir = "D:\tracetriage_keys",
  [string]$GradleCacheDir = "D:\dev-cache\gradle",
  [string]$Alias = "tracetriage",
  [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"

# The fingerprint of the key this project signs with. Published rather than secret: it is the
# public half, and a downloader comparing it against `apksigner verify --print-certs` on the
# file they got is the only way to tell a release from a rebuild by somebody else.
$ExpectedFingerprint = "98B530887C396BD9780B1F487154613DB3B6B5761794D7B737834A9C0BA1A80D"

$mobile = Split-Path -Parent $MyInvocation.MyCommand.Path

# On MAX_PATH, because it decides what this app is allowed to depend on. React Native's
# codegen writes object files whose names embed the full source path, so any dependency with
# C++ codegen deep enough to push one of those names past 260 characters fails with
# "ninja: error: Filename longer than 260 characters". Building through a junction does not
# fix it: CMake canonicalises the path before ninja sees it. `src/App.tsx` names the one
# dependency this ruled out and what it does instead. Nothing in this script works around it,
# because there is no working workaround.

$android = Join-Path $mobile "android"
$jbr = "D:\Android Studio\jbr"
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"

if (-not (Test-Path $jbr)) { throw "no JBR at $jbr. Point `$jbr at a JDK between 17 and 21." }
if (-not (Test-Path $android)) { throw "no android/ directory. Run: npx expo prebuild --platform android" }

$env:JAVA_HOME = $jbr
$env:ANDROID_HOME = $sdk
$env:ANDROID_SDK_ROOT = $sdk
# Expo's bundle task warns "NODE_ENV is required but was not specified" and carries on when
# Gradle is invoked directly rather than through `expo run:android`. The React Native plugin
# already passes `--dev false`, so `__DEV__` is off either way, but NODE_ENV is what selects
# the production Babel environment and which `.env` files are read. Setting it here means the
# bundle in the APK is the same one `expo export` would produce.
$env:NODE_ENV = "production"

# The Gradle wrapper downloads its own distribution on first use, with a 10-second connect
# timeout it does not expose. On this machine `services.gradle.org` answers a 307 to
# `release-assets.githubusercontent.com`, curl fetches the 137 MB zip from there in seconds,
# and the wrapper times out connecting to the redirect target every time. So: if a local copy
# of the exact distribution the wrapper asks for exists, point the wrapper at it. This is not a
# version override. The file name has to match what `gradle-wrapper.properties` already
# requests, and a mismatch leaves the properties untouched rather than silently building
# against a different Gradle.
$wrapperProps = Join-Path $android "gradle\wrapper\gradle-wrapper.properties"
if (Test-Path $wrapperProps) {
  $props = Get-Content $wrapperProps -Raw
  $wanted = [regex]::Match($props, 'distributions/(gradle-[\d.]+-bin\.zip)')
  if ($wanted.Success) {
    $local = Join-Path $GradleCacheDir $wanted.Groups[1].Value
    if ((Test-Path $local) -and ($props -notmatch 'distributionUrl=file')) {
      $asUrl = "file:///" + ($local -replace '\\', '/')
      $escaped = $asUrl -replace ':', '\:'
      $props = [regex]::Replace($props, 'distributionUrl=.*', "distributionUrl=$escaped")
      Set-Content -Path $wrapperProps -Value $props -Encoding ascii -NoNewline
      Write-Host "wrapper pointed at the local $($wanted.Groups[1].Value)"
    }
  }
}

$store = Join-Path $KeystoreDir "tracetriage-release.jks"
$passwordFile = Join-Path $KeystoreDir "keystore-password.txt"
$signed = $false
$gradleArgs = @("assembleRelease", "--no-daemon")

if ((Test-Path $store) -and (Test-Path $passwordFile)) {
  $password = (Get-Content $passwordFile -Raw).Trim()
  $gradleArgs += @(
    "-PTRACETRIAGE_STORE_FILE=$store",
    "-PTRACETRIAGE_STORE_PASSWORD=$password",
    "-PTRACETRIAGE_KEY_ALIAS=$Alias",
    "-PTRACETRIAGE_KEY_PASSWORD=$password"
  )
  $signed = $true
  Write-Host "signing with $store"
} else {
  # ${store} rather than $store, because PowerShell reads `$store:` as a drive-qualified
  # variable and refuses to parse the file at all.
  Write-Host "no keystore at ${store}: this will produce a DEBUG-SIGNED apk, not a release" -ForegroundColor Yellow
}

Push-Location $android
try {
  & (Join-Path $android "gradlew.bat") @gradleArgs
  if ($LASTEXITCODE -ne 0) { throw "gradle assembleRelease exited $LASTEXITCODE" }
} finally {
  Pop-Location
}

$apk = Join-Path $android "app\build\outputs\apk\release\app-release.apk"
if (-not (Test-Path $apk)) { throw "gradle reported success and produced no apk at $apk" }

$size = (Get-Item $apk).Length
$digest = (Get-FileHash $apk -Algorithm SHA256).Hash
Write-Host ""
Write-Host "apk    $apk"
Write-Host "bytes  $size"
Write-Host "sha256 $digest"

if ($SkipVerify) { return }

# Which key signed it. The newest build-tools directory that has apksigner, because the SDK
# on a developer machine accumulates several and the oldest one is usually the one on PATH.
$buildTools = Get-ChildItem (Join-Path $sdk "build-tools") -Directory |
  Sort-Object { [version]($_.Name -replace '[^0-9.]', '') } -Descending
$apksigner = $null
foreach ($dir in $buildTools) {
  $candidate = Join-Path $dir.FullName "apksigner.bat"
  if (Test-Path $candidate) { $apksigner = $candidate; break }
}
if (-not $apksigner) { throw "no apksigner in $sdk\build-tools, so the signer cannot be checked" }

$certs = & $apksigner verify --print-certs $apk 2>&1 | Out-String
Write-Host $certs
$match = [regex]::Match($certs, 'SHA-256 digest:\s*([0-9a-fA-F]+)')
if (-not $match.Success) { throw "apksigner printed no certificate digest" }
$actual = $match.Groups[1].Value.ToUpper()

if (-not $signed) {
  Write-Host "signer $actual (debug key: not a release)" -ForegroundColor Yellow
  return
}
if ($actual -ne $ExpectedFingerprint) {
  throw "signed by $actual, expected $ExpectedFingerprint. Do not publish this file."
}
Write-Host "signer verified against the published fingerprint" -ForegroundColor Green
