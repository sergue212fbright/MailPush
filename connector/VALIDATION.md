# Validation — MailPush 0.2.0-alpha.1

Executed in a Linux workspace using Python3.12.14, JDK17.0.21, Gradle8.13, Android Gradle Plugin8.13.2, SDK36 and Build Tools36.0.0. This is an unaudited alpha, with no live-account or phone-runtime claim.

## Passed

- **47 Python tests:** real IMAP wire protocol/IDLE fixtures; first-start baseline; restart catch-up; bounded batches; read-only PEEK; seen/old filtering; UIDVALIDITY resets; stable installation/mailbox identity; durable encrypted outbox/checkpoint atomicity; capacity rollback; locking; retries/expiry/redirect rejection; real local HTTP encryption delivery; process lifecycle/shutdown and redacted logs.
- Real self-signed local IMAP TLS: a matching SHA256 certificate pin allows login; wrong pin or absent CA trust rejects the connection before LOGIN. No credentials are sent by the certificate-inspection implementation.
- AES-GCM pairing import and encrypted return receipt, binding/source/mailbox approvals, wrong key/expired request/reflection rejection, overwrite guards/rollback and private Unix file modes. Persistent receiver revocation blocks queued jobs.
- **24 Android JVM tests:** bound-event policy, malformed/unencrypted/unpaired input rejection, mailbox/source/binding/type/time/size checks, control/bidi stripping, Python RFC8291 ciphertext decrypted by the actual Tink implementation, tamper rejection, Python receipt verification and matching cross-language fingerprints. A Java-generated AES-GCM pairing request was separately decrypted and checked by Python.
- Android `assembleRelease`, `testReleaseUnitTest` and `lintRelease`: release compiled, R8/resource shrinking completed; lint reports **0 errors and3 English-localization warnings**. These are JVM/build checks, not Android instrumentation tests.
- Signed release APK verifies using APK Signature Schemes v2/v3, RSA3072. Zip alignment passes. Packaged manifest contains only notification, boot and wake-lock permissions, no Internet permission; backups/cleartext disabled, release not debuggable. No FCM library in the resolved runtime graph.
- Python wheel/source distribution built; installed wheel's version/help/status run outside the source tree. Installed CLI completed synthetic encrypted pairing/receipt and private VAPID generation. `pip check` reports no broken dependencies.
- Shell syntax checked for signing/entrypoint scripts. Signing tools were exercised with the actual release key. Bridge installer URL/digest match the official release asset. Container runtime has not been executed.

The source kit includes JVM test XML, lint output, compiled manifest and a synthetic public-ntfy result under `validation`. RELEASE.json records exact APK size/hash and signing-certificate fingerprint. Test fixture keys are synthetic, deliberately public test data, never production credentials.

## Incomplete runtime verification

- **GrapheneOS/Android device:** no emulator or phone was available. Keystore operations, registration broadcasts, Storage Access Framework, screen-off/reboot delivery, UI layout/accessibility, channel privacy and endpoint replacement/removal need device validation.
- **Live Proton Bridge:** no account/credentials were supplied. IMAP fixtures cover the protocol path, not real Bridge synchronization/account behaviour.
- **Public/self-hosted ntfy phone delivery:** a synthetic public ntfy experiment opened an HTTP subscriber but publishing returned507; no successful receive/decrypt occurred through that public server. ntfy documents507 when subscriber-based rate limiting has no registered rate visitor. The exact cause in this environment was not established. Local HTTP transport and Python/Tink crypto interoperability passed; they do not prove public distributor/device delivery.
- **Docker:** unavailable here. Compose/Dockerfiles are supplied, including a pinned official Bridge installer wrapper, but build/runtime/login/volume/keyring compatibility need host validation. CI jobs are provided but have not been run remotely.
- **Other host platforms:** Python3.11/3.13 and macOS/Windows CI matrix is provided, not executed. No validated launchd or Windows-service installer is supplied.

HTTP acceptance does not prove phone receipt. Delivery is not exactly-once, and the phone has a narrow claim/post crash window. No independent security audit, formal cryptographic review, reproducible-byte-for-byte build claim or production-readiness claim is made. Follow START-HERE.md and test with generic synthetic alerts before relying on it for mail.
