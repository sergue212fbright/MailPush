# Changes

## 0.3.0a1

- Package the unchanged v2 connector protocol for the receiver embedded in the
  Proton Mail fork; replace companion/toggle setup instructions.
- Verify cross-language pairing against the extracted Android library module.
- Keep Bridge and connector deployment independent of Proton Android internals.
  Server previews remain off by default; the fork displays only generic alerts.

## 0.2.0a1

- Proton Mail only Android companion with UnifiedPush registration and encrypted local notifications; official Proton app remains independently updated.
- Offline AES-GCM request/receipt pairing, approved mailbox scope, connector source binding and endpoint rotation handling.
- Verified TLS certificate pinning before IMAP login, certificate inspection command and stricter Unix secret permissions.
- Stable source/event IDs, persistent receiver revocation, mailbox identity guards and bounded shutdown.
- Explicit ntfy Firebase-disable headers, VAPID key generation, full-stack official Bridge installer wrapper and native/container setup guides.
- Expanded connector security tests and Android policy/crypto interoperability tests. See VALIDATION.md for executed checks and outstanding device/runtime tests.

## 0.1.0a1

Initial standalone connector, encrypted outbox, IMAP IDLE/reconciliation, Docker/native packaging and local protocol fixtures.
