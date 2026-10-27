# Security and privacy model

This is security-sensitive **alpha software with no independent audit**. Passing
tests substantiate specific properties; they cannot establish maximum privacy or
prove that the whole Proton application has no vulnerabilities or telemetry.

## Trust and encryption boundaries

The trusted endpoints are your Bridge/connector host and your Android mail fork.
Bridge decrypts mail locally. A compromised host can access mail and send valid
alerts. A compromised phone/app process can access its mail and notification
keys. The isolated module is a maintenance boundary, **not an Android sandbox
inside the Proton process**.

The connector uses maintained `pywebpush`/`http_ece` implementations of RFC 8291
`aes128gcm` to encrypt alerts to the phone's P-256 recipient key and authentication
secret. UnifiedPush's maintained connector uses Tink to decrypt. There is no
home-grown message cipher. Fresh encryption and fixed 2048-byte plaintext padding
reduce content/length disclosure; encrypted packets still have observable length.

An authenticated encrypted payload contains the random receiver binding, stable
connector source UUID, approved mailbox ID, event ID, timestamps and generic
event type. The receiver rejects plaintext, wrong bindings/sources/scopes,
unsupported types, invalid times, oversized data and replayed events. The
connector's optional preview setting is false by default. Android profiles also
default to generic alerts, including profiles created before preview support.
Sender/subject display requires a separate, explicitly enabled phone setting;
receiving preview fields cannot turn that setting on.

With both preview settings enabled, sender/subject remain inside the encrypted,
padded payload. Only From/Subject headers are requested from Bridge. No mail body
or attachment is fetched. Display strings are bounded plain text, with control,
format, line-separator and paragraph-separator characters removed. The account
label comes from the encrypted local profile, not an alert-supplied account name.

Opting in deliberately exposes those decrypted fields to Android's notification
system and authorized notification listeners, including when Proton's app lock is
enabled. The setup toggle is itself protected by the native setup authorization
gate. Notifications use `VISIBILITY_PRIVATE` and an independently built generic
`publicVersion`; the public copy has no sender, subject, account label or expanded
preview style. Android/user/channel settings have ultimate control of lock-screen
display, so this is not an unconditional promise to hide previews while locked.
System-generated contextual actions are disabled. Turning previews off updates
the encrypted setting and cancels that profile's displayed alerts under the same
lock used to reread the setting and post notifications. Preview text is never
added to the vault, replay ledger, intents, logs or WorkManager job data. Android
can retain displayed notification content according to its own settings.

A public relay does not receive the recipient private key or plaintext message.
It can observe IPs, endpoint identifiers, timing, volume and sizes, and can
reorder, delay, replay or drop traffic. Encryption alone does not restrict who
can publish to a public endpoint. Use provider authentication/VAPID where needed;
keep the subscription bundle and its authentication secret private.

No phone acknowledgement exists. HTTP acceptance is not receipt, and a persistent
replay ledger claims an event before posting it: a crash in that narrow interval
can lose an alert. This is an alert path, not a reliable replacement for checking
mail availability.

The UnifiedPush callback schedules an expedited WorkManager job instead of doing
native account I/O on Android's UI thread. Input payloads are wrapped in a separate
Keystore AES-GCM envelope, bound to the profile, before WorkManager persists them.
Only ciphertext and a random profile ID enter its job database. Duplicate queued
payloads coalesce; the replay ledger still controls actual posting. Android can
delay jobs when quota/battery policy prevents immediate execution. API 29/30 may
briefly show a generic processing notification for expedited work. Profile removal
cancels queued jobs; any running job rechecks pairing before posting. Encrypted
completed/cancelled job records follow WorkManager's own pruning policy.

## Pairing and key storage

Pairing is an offline, bidirectional, AES-GCM protected request/receipt exchange.
A fresh 256-bit one-time key must be transferred separately from the encrypted
request; fingerprints must match. Whoever has both can impersonate the exchange.
Requests/receipts expire after a day. Delete transfer files after setup and
revoke an old device on the connector before retiring it.

Pairing profiles and temporary pairing material use an Android Keystore-backed
AES-GCM vault, an atomic file and app-private no-backup storage. UnifiedPush's
`DefaultKeyManager` uses its API-23+ implementation on all supported devices here
(minimum API 29): it encrypts the P-256 private key with an Android Keystore
AES-GCM key before database storage. Its public key and Web Push authentication
secret also exist in its app-private database; the library does not encrypt
every database field. Our vault separately encrypts the subscription copy.
This was checked in the pinned library bytecode. Persistence and deletion were
also exercised through public UnifiedPush registration on a disposable AOSP
emulator; physical-device hardware behavior remains untested. Hardware-backed
wrapping depends on the device, and no hardware-backed claim is made for every
secret byte.

The module adds no network client and delegates push transport to its selected
distributor. The full Proton app retains its normal Internet access for mail.
The distributor is trusted to register subscriptions and deliver IPC correctly.
Only private Android components handle our setup, open-mail and push callbacks.
Notification intents are explicit and immutable. No alert-provided intent or
external URL is executed. Setup uses `FLAG_SECURE`, hides on pause and asks
Proton's existing app-lock policy for authorization before showing account labels
or keys. No key is placed on the clipboard automatically.

Pairing is bound to a local signed-in Proton account. Each alert performs a fresh,
bounded account-readiness check. Removed/disabled accounts lose profiles and keys
locally before distributor unregistering; already-posted module notifications are
cancelled. Cleanup requires a successful native account snapshot: Proton's seeded
empty observer value or a failed account query cannot delete pairings. Transient
NotReady states retain keys and suppress alerts. Removing a phone profile cannot
stop a remote connector; revoke the device there too.

Connector config/secrets require private filesystem permissions on Unix. IMAP
authentication follows verified TLS/CA trust or a deliberately pinned Bridge
certificate; credentials are never sent before pin validation. Loopback plaintext
is a deliberate opt-in only. HTTPS push forbids redirects and ignores ambient
proxy/.netrc settings. Its durable outbox stores ciphertext, not preview text.
Protect/encrypt host disks, state and backups. Windows ACLs need owner setup;
POSIX permission checks are not Windows ACL enforcement.

## Changes to Proton's application

The patch disables Proton's FCM token lifecycle registration and FCM service,
removes Firebase automatic provider/receiver/base-service entry points, removes
advertising permissions, empties Sentry DSNs, and replaces the small optional
upselling telemetry adapter with no-ops. Automatic Firebase entries and Sentry's
performance provider are removed in the top-level app manifest so that direct
library dependencies cannot restore them during manifest merging. The compiled
manifest gate rejects those entries and Sentry's initialization provider.

The Sentry Gradle plugin and its buildscript classpath are removed entirely,
including its instrumentation and upload configuration. Disabling symbol uploads
alone did not prevent that plugin's build telemetry. Source preparation now
rejects recognized Sentry Gradle plugin declarations or classpath references in
the root/app build scripts before invoking Gradle. The application still includes
the Sentry runtime APIs needed to compile upstream code, with empty runtime DSNs;
this is not a claim that every Sentry or native SDK reference has been removed.

Release rules strip Android/Timber logging calls where R8 can identify them.
Backup/extraction rules exclude app data, cleartext traffic is disabled, and
shell profiling is explicitly disabled. A compiled-manifest audit gates signing.

**This is not a complete audit/removal of Proton's native Rust SDK telemetry or
logging.** The native SDK remains an upstream dependency. Runtime traffic and
native behaviour still require inspection on a real device. The privacy patch
does not promise zero network metadata or zero telemetry across every upstream
SDK. Proton login, synchronization, anti-abuse checks and other normal account
functions continue to contact Proton services.

## Update supply chain

The source repository, branch and full commit SHA are checked. Patches use strict
`git apply --check`, never fuzzy/automatic AI repair. Wrapper JAR and distribution
checksums come from Gradle's official service. Workflow actions use full commit
SHAs. A change in the integration, build policy or workflow changes its release
identity. Upstream source publication can lag app-store releases.

The upstream build runs without signing or SMTP secrets and without repository
write permission. A separate runner checks out only this maintained repo, audits
the unsigned compiled manifest, signs with a temporary private key file, checks
the certificate fingerprint/alignment, and stages checksums. A separate publisher
receives write permission, and a separate failure-email job receives SMTP secrets.
The signing and SMTP jobs use separate GitHub environments, configured to
allow only the main branch. Keep their secrets in those environments rather than
as repository-wide secrets. Pull requests cannot sign/publish or receive SMTP
secrets through this workflow.
Do not add `pull_request_target`, shared untrusted build caches or self-hosted
runners that retain release secrets without a fresh security review.

### Custom F-Droid distribution

The GitHub-hosted feed is a binary repository maintained by this project; it is
not a review or endorsement by the F-Droid project. The APK retains its existing
signing certificate. A different key signs the repository index, and its public
certificate/fingerprint is pinned in `fdroid/config.json` and the add-repository
link. Keep both private signing backups, with their distinct purposes.

Repository preparation verifies release provenance, checksums, package,
versionCode and the expected APK certificate before indexing. Only public APKs,
corresponding source, icons and bounded index files enter its artifact; caches
and tool configuration stay outside the deployed site. Index signing and Pages
deployment use separate jobs and main-branch-restricted environments. The
index-signing job has no APK-signing key or Proton/Bridge credentials. GitHub
can observe repository-update and download requests, including IPs and timing;
no mail content or phone notification keys belong in this feed.

For the initial alpha.1, the fork signing identity was generated after all
local build/test jobs stopped. Alpha.2 reuses that identity for in-place updates. The APK's signature, exact expected certificate,
16 KB page alignment and post-sign manifest policy were verified. Its private
backup is separate from the public source. Keep that backup private and use the
same identity for updates; the public certificate fingerprint is in the validation
receipt and is safe to publish.

Trusting a new Proton commit still means trusting its code and published
dependencies. Automated tests cannot detect every malicious upstream change.
Dependency updates arrive as reviewable PRs; do not auto-merge cryptographic or
release-workflow changes merely because they compile.

Do not commit a keystore, its password, subscription bundle, mailbox credentials,
state directory, SMTP credentials or actual diagnostic mail content. Report
security issues through the enabled GitHub private vulnerability reporting
channel under this repository's Security tab. Do not post credentials or
decrypted mail in public issues.
