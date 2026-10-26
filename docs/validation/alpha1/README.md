# Validation evidence

These receipts record the local checks summarized in `tests.json`. They are evidence for their stated scope, not an independent security audit or proof of end-to-end mail delivery.

- `connector-tests.log`: 47 Python connector tests passed.
- `release-tests.log`: 31 Python release/security policy tests passed.
- `jvm/TEST-*.xml`: 29 Android module JVM tests, no failures, errors or skipped tests.
- `module-result.json`: module Gradle process completed successfully.
- `instrumentation-build-result.json`: instrumentation APK rebuilt after the
  offline registration fixture fix; production application code was unchanged.
- `device-tests-result.json` and `device-tests-instrumentation.txt`: all eight
  `DeviceSecurityTest` tests passed in an actual Android framework running in a
  disposable AOSP API 35 x86_64 software emulator. This used synthetic data, no
  real Proton account or distributor, and makes no hardware-backed Keystore claim.
- `lint-summary.json` and `lint-results-release.txt`: release module lint, zero errors and four warnings. Two warnings concern UI localization; two are newer dependency version notices.
- `actionlint-validation.json`: workflow syntax check completed with zero findings.
- `patch-reproducibility.json`: overlay application and source comparison receipt. Inspect its difference lists when assessing source equivalence; successful application alone does not prove all files match.
- `full-build-result.json`: corrected complete `:app:assembleProdRelease` build
  succeeded; no source changes or command-level task skips were used for its retry.
- `apk-audit-unsigned.json`: the resulting unsigned production APK passed the
  compiled-manifest gate. Its hash identifies the unsigned signing input.
- `signed-apk.json`: final APK hash/size, RSA-3072 certificate fingerprint, verified
  signature and verified 16 KB page alignment. The private signing identity was
  generated after all build/test jobs stopped and is not included in source.
- `apk-audit-signed.json`: the signed APK independently passed the same compiled
  manifest policy. This hash identifies the installable release artifact.

The device suite exercises the stale app-lock authorization callback regression,
Keystore-backed vault round trips, tamper rejection, profile-bound encrypted work,
atomic backup restoration, persistent replay isolation, public UnifiedPush
registration/key persistence/deletion, and local sign-out cleanup. An earlier
completed run passed six tests and exposed two fixture failures: generating keys
directly omitted the registration parent required by the library's SQLite foreign
key. The fixture now uses the real public offline registration API; it does not
replace the key manager or weaken the checks. Earlier emulator attempts also
crashed or timed out. The retained final transcript reports `OK (8 tests)`.

The overlay comparison preserves its original difference lists and adds a `reconciliation` field: the prepared metadata hash was refreshed, the Detekt difference is one build-added timestamp comment, and `.kotlin` compiler session markers are excluded from the corresponding-source bundle. This does not establish reproducible APK bytes.

Machine-specific absolute paths have been shortened. The JVM XML build-container hostname was omitted. Test names, outcomes and recorded timestamps remain intact.

These receipts do not establish real Proton Bridge/ntfy delivery on GrapheneOS,
Docker deployment execution, activation of the owner's GitHub
workflow, or a complete native Rust telemetry audit. Those require their own results.
