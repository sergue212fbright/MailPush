# Validation evidence — 0.3.0-alpha.2

These receipts have only their recorded scope. They are not an independent
security audit, a hardware-backed Keystore attestation or proof of every phone
delivery scenario. `VALIDATION.md` describes the current checkpoint and remaining
limitations.

## Current alpha.2 checkpoint

* Module release build, strict dependency verification, **40 JVM tests** and
  release lint passed. JVM counts are 24 security/crypto/pairing tests, five host
  boundary tests and 11 preview-policy tests, with no failures or skips.
* Module lint has **zero errors and five warnings**: three UI localization
  warnings and two dependency version notices.
* The Android instrumentation APK compiled with **11** device-test methods.
  Current execution is **unavailable; all 11 remain unverified**. Three bounded
  software-emulator attempts failed in infrastructure before any completed
  MailPush result: startup ANR, ART/system_server suspend-thread timeout with
  SIGABRT, then NetworkStack/system_server death and a missing package service
  before APK installation. These are not method failures, passes or substituted
  skips. A stable emulator or physical test device must complete all 11 methods,
  including the notification-permission-dependent opt-out cancellation test.
* **31 Python release/security tests** passed. SMTP behavior is mocked; no
  actual failure email was sent.
* The complete `:app:assembleProdRelease` build passed in 261 seconds. Its
  VersionCode `1000002` unsigned APK passed the compiled-manifest gate:
  size `168498182` bytes; SHA-256
  `b69eb45c1f695857d85b9fca7517f343d60ba82b82260b8fae1b7fb889f3d57b`.
* The signed alpha.2 APK passed `apksigner` signature/expected-certificate
  verification, 16 KB page-alignment verification and the signed-manifest audit
  for VersionCode `1000002`. Size: `168694857` bytes; SHA-256:
  `28c9bca93f97fa796bc58b8a1c5320b5cf6981eee2c556df788bfae850312d6a`.
  Its verified RSA-3072 certificate is the existing alpha.1 identity:
  `bf65bf147b85f377575579d8569cfa6dda715d309ec0aabdfd7b42800f52e79e`.
  Signing reused that key only after all build/test jobs ended; temporary local
  signing material was removed again after verification.

The newly added device cases inspect the actual Android notification's private
and independently generic public fields, verify that a paused settings screen
cannot change preview consent, and exercise clearing existing notifications only
for the profile whose previews were disabled. Previews remain default-off, and
test alerts stay generic. Android's own lock-screen/privacy policy still applies
to notifications containing opted-in decrypted details.

## Receipt interpretation

* `jvm/TEST-*.xml`, `module-result.json`, `lint-summary.json` and
  `lint-results-release.txt`: module test/build/lint results. Confirm the current
  40-test and five-warning counts when assessing alpha.2.
* `instrumentation-build-result.json`: successful test-APK compilation, not
  proof of device execution.
* `device-tests-result.json` and `device-tests-instrumentation.txt`: current
  device-attempt evidence. Alpha.2 execution is **unavailable** after three
  infrastructure failures, and all **11** methods remain unverified. A receipt
  reporting eight successful tests describes the earlier alpha.1 suite. Preserve
  the distinction between infrastructure unavailability and actual method
  outcomes; zero completed methods is not a passing result.
* `release-tests.log`: release/security policy tests. `connector-tests.log` holds
  the previous 47-test connector result unless a new run is explicitly recorded;
  the connector protocol/runtime are unchanged in this Android preview update.
* `full-build-result.json` and `apk-audit-unsigned.json`: full production build
  and unsigned signing input. Check VersionCode `1000002` and the unsigned hash
  above when identifying alpha.2.
* `signed-apk.json` and `apk-audit-signed.json`: final installable alpha.2
  artifact's verified signature, expected certificate, 16 KB page alignment and
  compiled-manifest policy. Confirm VersionCode `1000002` and the signed hash
  above; alpha.1's signed hash is not evidence for the changed application.
* `actionlint-validation.json`: workflow syntax result for its recorded source.
  Syntax validation does not activate or execute the owner's GitHub workflow.
* `patch-reproducibility.json`: overlay/source comparison for its recorded
  inputs. Successful application alone does not prove source equivalence or
  bit-for-bit APK reproducibility.
* `manual-delivery.json`: owner-reported real alpha.1 generic alerts and working
  alpha.2 sender/subject previews on GrapheneOS via TrueNAS Docker Apps, Proton
  Bridge and ntfy. These functional reports do not supply automated phone
  acknowledgements or replace the Android security suite.
* `tests.json`: aggregate summary; its artifact version and counts must agree
  with the individual current receipts before release staging is complete.

## Historical evidence

`alpha1/` preserves the previous signed VersionCode `1000001` build's receipts,
29 JVM tests, zero-error/four-warning lint result and **eight** successful Android
device tests. Earlier completed device runs found two registration-fixture
foreign-key failures, which were fixed by using UnifiedPush's real public offline
registration API. Earlier emulator attempts also crashed or timed out. Those
results remain historical and are not substituted for alpha.2's changed suite.

The earlier overlay receipt retains its original difference lists and
`reconciliation` notes. It does not establish reproducible APK bytes. Finalized
receipts shorten machine-specific workspace paths and omit the JVM build
hostname while retaining outcomes and timestamps; signing keys and real account
credentials are never public validation artifacts.

The owner's manual delivery observation is separate from workspace execution.
These checks do not establish current execution of the 11 Android device
methods, screen-off/reboot/cold-start reliability, owner GitHub workflow
activation or a
complete native Rust telemetry audit. Keep those claims unverified until their
own results are recorded. Device execution being unavailable means the full
release-validation gates have not all passed.
