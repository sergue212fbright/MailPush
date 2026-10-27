# Validation evidence

Each receipt has its own source, artifact and execution scope. These records are
not an independent security audit, a hardware-backed Keystore attestation or
proof of every phone delivery scenario. `tests.json` keeps the earlier manually
signed alpha.2 results separate from the later GitHub validation run.

## Custom F-Droid repository publication

`fdroid.json` records the separate distribution workflow: 52 feed boundary tests,
real APK/source download and unsigned catalog generation, and the GitHub runner's
keyless process-isolation/identity checks passed. A later activation run passed
production index signing and GitHub Pages deployment. Independent downloads from
the live site passed both official F-Droid index-signature/fingerprint checks,
the signed hash chain, APK signature/hash/version checks and corresponding source
checks. The earlier keyless checkpoint remains recorded separately. A physical
phone installation through an F-Droid client and live SMTP delivery were not tested.

## First GitHub-signed public release

`github-release.json` records the later protected signing and public publication
attempts for VersionCode `1000003`, including independent verification of the
downloaded APK, corresponding source and release checksums. The original signing
certificate was reused. Those results are separate from attempt 1's unsigned
validation below; they do not imply a physical-phone upgrade test or delivered
SMTP email.

## Initial GitHub validation checkpoint

Run [40423151153](https://github.com/sergue212fbright/MailPush/actions/runs/40423151153)
checked out maintenance commit
`8a09136dc638354bbdcec9a21db1850178c72c17`.

* The **checks job passed**: 47 connector tests and 46 release/device-gate parser
  tests passed. The current 40-method JVM suite, module release build/lint and
  Java-to-Python pairing interoperability check also completed successfully.
  The Python counts appear explicitly in the primary GitHub job log. The JVM
  count comes from the checked-in test methods and the successful executed Gradle
  task; fresh CI JUnit XML is not included in this checkpoint.
* The strict Android gate **passed all 11 methods with zero failures, errors or
  skips**, using synthetic data in a disposable accelerated AOSP API 35 x86_64
  emulator. The whole device gate took 2.4 seconds; the Android runner reported
  `OK (11 tests)` and its successful final result. The gate checks named methods,
  not ADB's exit status alone.
* The **full unsigned production APK build passed**: `:app:assembleProdRelease`
  completed in 24 minutes 37 seconds. The compiled-manifest audit, corresponding
  source staging and artifact upload also passed. CI's unsigned VersionCode
  `1000003` APK is `168498182` bytes; SHA-256
  `adad842c9c9f99c3d10cebd7094b6010c8e6d239b702193bece6b0368dce1a55`.
  It is a signing input, not a signed installable release.
* Signing and publication were disabled for this initial validation run. Its
  receipts do not establish a GitHub-signed release or live failure-email
  delivery; later protected-environment setup and releases need their own record.

`github-ci.json` identifies the run, maintenance and Proton source SHAs, job
links, completed unsigned validation and remaining signing/publication work. It
also records the uploaded `unsigned-build` artifact's separate ZIP digest; that
ZIP digest is not the unsigned APK's digest. `github-device-result.json` and
`github-device-instrumentation.txt` retain the actual successful device evidence.
These tests exercise the standalone module's Android fixture; they do not log
into a real Proton account or attest physical hardware-backed key storage.

The successful GitHub run is later evidence. It does not relabel the three
failed local emulator attempts below or change the manually delivered APK's
versionCode, hash or signer.

## Local manually signed alpha.2 history

The original local packaging checkpoint recorded:

* Module release build, strict dependency verification, **40 JVM tests** and
  release lint passed. JVM counts were 24 security/crypto/pairing, five host
  boundary and 11 preview-policy tests, with no failures or skips.
* Module lint reported **zero errors and five warnings**: three UI localization
  warnings and two dependency version notices.
* The 11-method Android instrumentation APK compiled. Its local execution was
  unavailable after three bounded software-emulator infrastructure failures
  before any MailPush test method ran: startup ANR, ART/system_server failure,
  and NetworkStack/system_server death with no package service. No method pass,
  failure or skip was substituted for those unavailable results. The later
  GitHub success has its separate receipts above.
* **31 local Python release/security tests** passed. SMTP was mocked; no actual
  failure email was sent.
* The complete local `:app:assembleProdRelease` build passed in 261 seconds.
  VersionCode `1000002` unsigned APK passed the compiled-manifest gate:
  `168498182` bytes; SHA-256
  `b69eb45c1f695857d85b9fca7517f343d60ba82b82260b8fae1b7fb889f3d57b`.
* The manually signed alpha.2 APK passed `apksigner` expected-certificate
  verification, 16 KB page alignment and the signed-manifest audit for
  VersionCode `1000002`: `168694857` bytes; SHA-256
  `28c9bca93f97fa796bc58b8a1c5320b5cf6981eee2c556df788bfae850312d6a`.
  Its RSA-3072 certificate reuses the alpha.1 identity:
  `bf65bf147b85f377575579d8569cfa6dda715d309ec0aabdfd7b42800f52e79e`.
  Signing happened after local build/test jobs ended; temporary signing material
  was removed afterward.

## Receipt interpretation

* `github-ci.json`: the initial GitHub run's completed unsigned validation,
  including its full production build, compiled-manifest audit, corresponding
  source and uploaded artifact metadata. Signing/release setup remains separate.
* `github-device-result.json` and `github-device-instrumentation.txt`: the later
  successful **11-method** Android run, including actual notification redaction,
  resumed-settings authorization and profile-scoped opt-out cancellation.
* `jvm/TEST-*.xml`, `module-result.json`, `lint-summary.json` and
  `lint-results-release.txt`: original local module build/test/lint evidence.
* `instrumentation-build-result.json`: original local test-APK compilation,
  distinct from device execution.
* `device-tests-result.json` and `device-tests-instrumentation.txt`: the three
  original local infrastructure failures. Their zero executed methods are not
  passes and are not overwritten by the successful GitHub records.
* `release-tests.log`: original local 31-test release/security policy run.
  `connector-tests.log` is earlier 47-test evidence; the current GitHub checks job
  separately reran all 47 connector tests and the expanded 46-test release suite.
* `full-build-result.json` and `apk-audit-unsigned.json`: original local full
  production build and its unsigned VersionCode `1000002` signing input.
* `signed-apk.json` and `apk-audit-signed.json`: the manually delivered alpha.2
  APK's verified signature, expected certificate, alignment and manifest policy.
  These are not receipts for a new GitHub-signed APK.
* `actionlint-validation.json`: historical workflow syntax evidence. The public
  setup subsequently changed the workflow's strict device gate and secret
  environments; its live execution is recorded separately in `github-ci.json`.
* `patch-reproducibility.json`: overlay/source comparison for its recorded
  inputs. Successful patch application does not establish identical APK bytes.
* `manual-delivery.json`: owner-reported working generic alerts and alpha.2
  sender/subject previews on GrapheneOS via TrueNAS Docker Apps, Proton Bridge
  and ntfy. Functional observations do not supply automated phone acknowledgements
  or replace the synthetic Android security suite.
* `tests.json`: aggregate with separate local-history and `github_validation`
  sections. Its scope must be read along with each individual receipt.

## Earlier alpha.1 evidence and remaining limits

`alpha1/` preserves the preceding VersionCode `1000001` build: 29 JVM tests,
zero-error/four-warning lint and eight successful Android device tests. Earlier
fixture foreign-key failures were fixed using UnifiedPush's public offline
registration API. Historical results are not substituted for newer tests.

Public receipts omit build-host identities and real credentials. Android
previews remain default-off; opting in shares decrypted details with Android's
notification system and its authorized listeners. Android lock-screen settings
still govern display.

Screen-off/reboot/cold-start reliability, a physical-phone upgrade to the CI APK,
a complete native Rust telemetry audit, long-term scheduled operation and live
failure-email delivery still require their own results. Successful CI signing
and publication are established separately in `github-release.json`.
