# Validation record — 0.3.0-alpha.2

## Current release checkpoint

The complete production Proton fork with optional sender/subject previews built
successfully from official Proton commit
`17fe04fd0f8b9b7dc45c188d4d5e2d55033128c0`. The
`:app:assembleProdRelease` process completed with exit code zero in 261 seconds,
including the production Java/Kotlin, Hilt and R8 build. The resulting unsigned
APK passed the compiled-manifest audit.

The unsigned alpha.2 signing input has:

* Application ID: `ch.protonmail.android.mailpush`.
* VersionCode: `1000002`.
* Size: `168498182` bytes.
* SHA-256: `b69eb45c1f695857d85b9fca7517f343d60ba82b82260b8fae1b7fb889f3d57b`.

The final installable `MailPush-ProtonMail-0.3.0-alpha.2.apk` has:

* VersionCode: `1000002`.
* Size: `168694857` bytes.
* SHA-256: `28c9bca93f97fa796bc58b8a1c5320b5cf6981eee2c556df788bfae850312d6a`.
* Verified RSA-3072 certificate SHA-256:
  `bf65bf147b85f377575579d8569cfa6dda715d309ec0aabdfd7b42800f52e79e`.

The signed APK passed `apksigner` signature/expected-certificate verification,
`zipalign -c -P 16 4`, and an independent compiled-manifest audit for VersionCode
`1000002`. It reuses the alpha.1 signing identity for in-place updates. The
unsigned input above has a different hash and size and is not the installable
artifact.

Signing material was removed from the workspace before Gradle ran. The existing
private key was restored only after all build/test jobs ended, used for signing,
and removed again after verification. The owner's private backup remains
separate from public source and must be retained for future in-place updates.

**Current Android device execution is unavailable.** All three bounded
software-emulator attempts failed in infrastructure before producing any
completed MailPush test result. All 11 device methods remain unverified; passing
build and signed-artifact checks do not mean every release-validation gate
passed.

Earlier alpha.1 receipts are preserved under `docs/validation/alpha1/`. Their
VersionCode `1000001`, signed hash and eight-test device result describe alpha.1,
not this changed application. Read the version, hash and test count inside each
receipt rather than inferring its scope from the filename alone.

## Preview behavior under test

Previews require both connector-side `preview = true` and the phone profile's
explicit **Show sender and subject** choice. Existing and new phone profiles
default to generic alerts. The connector already supports encrypted preview
fields; this update changes their Android presentation without adding Proton
entry points, receiver dependencies or plaintext work storage.

The private Android notification may contain a sanitized sender, subject and
bounded local account label. Its independently built public version remains
generic and contains no sender, subject, account label or expanded preview.
System-generated contextual actions are disabled. Test alerts remain generic.
Disabling previews and clearing that profile's active alerts is serialized with
the receiver's final profile read and notification post.

Opting in shares decrypted details with Android's notification service and
authorized notification listeners, including while Proton Mail's own app lock
is enabled. Android's lock-screen privacy settings govern display. A generic
public version is not a guarantee that a user-selected Android policy will hide
all sensitive notification content. Preview fields remain end-to-end encrypted
over the push relay; sender and subject are not written in plaintext to
WorkManager input, local profile records or navigation intents.

## Completed automated checks for alpha.2

* Receiver module: release Java/resources compiled into an Android library.
  **40 JVM tests passed**, with zero failures, errors or skipped tests: 24
  crypto/payload/pairing tests, five host/account boundary tests and 11 preview
  consent/sanitization tests. Coverage includes strict Boolean opt-in, generic
  test alerts, safe fallbacks, line/bidi-control removal, literal markup,
  supplementary Unicode bounds and local account-label limits.
* The module build passed with strict dependency verification, release
  compilation, JVM tests, release lint and compilation/packaging of the
  **11-test Android instrumentation APK**. Module lint reported **zero errors
  and five warnings**: three UI localization warnings and two dependency version
  notices. Compiling the instrumentation APK does not establish that those tests
  executed successfully.
* Release/security boundaries: **31 Python tests passed**. These include the
  compiled-manifest policy, release input/checksum validation and verified TLS
  SMTP ordering/failure checks. SMTP remains mocked; no actual email was sent.
* The complete `:app:assembleProdRelease` build and the unsigned production APK's
  compiled-manifest gate passed. Firebase/Sentry auto-initialization removals,
  disabled backup/cleartext/profiling and the Sentry build-plugin source guard
  remain part of the existing release policy.
* The signed APK passed expected-certificate/signature verification, 16 KB page
  alignment verification and the signed compiled-manifest gate. Its public
  receipts identify the new VersionCode `1000002` artifact and signed hash above.

The connector runtime and encryption protocol are unchanged by this Android
preview update. The prior **47-test Python connector result** is retained as
carried-forward evidence, covering synthetic local IMAP IDLE, encrypted HTTP
delivery, durable retry/expiry, certificate pinning before login, pairing,
revocation and secret permissions. It must not be described as a new alpha.2
run unless the corresponding receipt is refreshed.

## Android device execution — unavailable

The current suite has 11 `DeviceSecurityTest` methods. It retains the previous
Keystore, encrypted-work, replay, account-removal and stale-authorization checks,
and adds actual framework notification construction/redaction, preview-setting
authorization after pause, and per-profile opt-out cancellation of posted
notifications. The live cancellation test requires notification permission in
the disposable test application; a skipped test is not a passing gate.

All three bounded alpha.2 attempts failed in a disposable AOSP API 35 x86_64
software emulator before producing any completed MailPush test result:

* The first attempt encountered an application/startup ANR before the methods
  could complete.
* The second attempt failed in ART/system_server with a suspend-thread timeout
  and SIGABRT.
* The third, reduced to one virtual CPU, lost NetworkStack/system_server and the
  package service before the instrumentation APK could be installed.

Current execution is therefore **unavailable: all 11 device methods remain
unverified**. These infrastructure failures are not MailPush method failures,
passed methods or substituted skips. Successful test-APK compilation and the
historical alpha.1 eight-test run do not replace current framework execution.
No claim of `OK (11 tests)`, complete release-gate success or hardware-backed
Keystore behavior is made. Run the current suite on a stable emulator or
physical test device before relying on its Android-specific assertions.

## Owner-reported deployment evidence

On 2026-10-26, the owner confirmed a real generic new-mail notification in
alpha.1, then reported that alpha.2 sender/subject previews work beautifully after
the APK/configuration update. The deployment uses GrapheneOS, TrueNAS Docker Apps,
Proton Mail Bridge and ntfy UnifiedPush. See
`docs/validation/manual-delivery.json`.

These are owner-reported functional observations, not automated acknowledgements,
an independent lab test or a substitute for the eleven Android security tests.
They do not separately establish screen-off/reboot behavior, app-lock/redaction,
launcher badges or hardware-backed key storage.
The setup session also exposed Bridge account-loading/startup timing: an IMAP
listener can accept connections before its users are loaded. A successful check
against a warmed Bridge is not proof of unattended cold-start behavior.

## Not yet established

* Current execution of all 11 alpha.2 Android device tests; infrastructure
  attempts were unavailable, not passed.
* Independent Docker execution in this build workspace; Docker is unavailable
  here. The owner's deployment observation has the separate scope stated above.
* Scheduled upstream builds, release publication and failure email in an owner's
  GitHub repository. The workflow is prepared, but no MailPush destination
  repository or SMTP/signing-secret setup has been verified.
* A complete telemetry/traffic audit of Proton's native Rust SDK.
* Bit-for-bit APK reproducibility. Source overlay checks and successful builds
  alone do not establish identical APK bytes.

## Before relying on a release

Complete the unavailable device checks. Verify the downloaded artifact against
the signed hash and expected certificate above, then test the in-place upgrade,
opt-in/default-off behavior, real sender/subject
delivery, Android lock-screen settings, app lock, screen-off delivery, reboot,
cold start, account switching, logout/revocation and endpoint changes on the
owner's phone. Confirm that turning previews off clears existing alerts only for
the selected profile. Check network traffic for unexpected Firebase, analytics
and native SDK activity.

Keep distribution labeled alpha until those results are recorded. Preserve the
existing signing identity and pairing data; installing a differently signed APK
is not an in-place update.
