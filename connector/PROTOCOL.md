# MailPush protocol v2

Project-specific alerts inside RFC 8291 Web Push encryption. The receiver runs inside the MailPush fork of Proton Mail. The official, separately signed Proton APK cannot receive this envelope or adopt this fork's notifications.

## Pairing

The Android UnifiedPush library registers with the selected distributor and generates recipient keys. The export plaintext is:

```json
{"format":"mailpush-receiver-v2","binding":"PHONE_PROFILE_UUID","mailboxes":["personal"],"created_at":1792933200,"endpoint":"https://ntfy.example/upACTUAL_ENDPOINT?up=1","keys":{"p256dh":"BASE64URL_P256_PUBLIC_KEY","auth":"BASE64URL_AUTH_SECRET"}}
```

Use the exact returned endpoint/query; the example is not usable. No recipient private key is exported. The app encrypts with random AES-256-GCM key and 12-byte nonce, UTF-8 AAD `MailPush pairing v1`. Outer fields are exactly `format` (`mailpush-pairing-v1`), `nonce`, `ciphertext`. Binary fields and the one-time key are unpadded URL-safe Base64. Size limit is 64 KiB. Maximum age is one day with 300 seconds future skew.

The owner transfers the request and provides its key separately at a hidden terminal prompt. The connector validates the bundle and mailbox approvals, stores it privately, and returns a receipt encrypted with that key, a fresh nonce, distinct AAD `MailPush receipt v1` and outer format `mailpush-receipt-v1`. Receipt plaintext:

```json
{"format":"mailpush-receipt-v2","binding":"PHONE_PROFILE_UUID","source":"CONNECTOR_INSTALLATION_UUID","fingerprint":"24_lowercase_hex_characters","mailboxes":["personal"],"created_at":1792933200}
```

The fingerprint is the first 24 hex characters of SHA-256 over the UTF-8 newline-joined fields `MailPush binding v2`, binding, exact endpoint, p256dh, auth, then mailbox IDs in approved order, with no trailing newline. The app verifies the fingerprint, binding, exact mailbox list, source UUID and age, then marks the profile paired and discards the pending one-time key. Distinct AAD blocks request/receipt reflection. Without the receipt, alerts fail closed.

The one-time key authenticates the handoff: an attacker with both file and key can impersonate pairing. Keep transfer files private, then delete them. No listening pairing API is used.

## Transport and events

POST binary RFC 8291 `aes128gcm`, `Content-Type: application/octet-stream`, bounded `TTL`, `Urgency: normal`, `X-Firebase: no`, `X-UnifiedPush: 1`. UTF-8 JSON is space-padded to exactly 2048 bytes before encryption, with fresh ephemeral crypto material per recipient/event. No plaintext title, preview, account address or click URL is sent in headers. HTTPS is verified; redirects and ambient proxies/.netrc are disabled.

ntfy's documented UnifiedPush binary/Base64 mechanism transports the ciphertext. Server policies/rate limits, optional bearer auth or VAPID, and distributor connectivity apply. VAPID public keys go on the phone before registration; the matching private key/subject is configured on the connector. Access control is separate from recipient encryption.

```json
{"v":2,"type":"new_mail","event_id":"EVENT_UUID","binding":"PHONE_PROFILE_UUID","source":"CONNECTOR_INSTALLATION_UUID","mailbox":"personal","created_at":1792933200,"expires_at":1792976400}
```

Types: `new_mail`, `test` only. Times must be JSON integers, Unix UTC seconds. Lifetime 60–86400 seconds, future skew at most 300 seconds. Unknown version/type, unencrypted input, wrong binding/source, unapproved mailbox, invalid UTF-8, expired data or over-4096-byte plaintext is rejected. Synthetic `test` has no real mailbox. Optional sender/subject have limits of 160/240 Unicode codepoints; control/format characters are stripped for display. No body, attachment, Proton token, IMAP password, URL or command is included.

Mail event IDs are UUIDv5 of stable installation namespace plus mailbox ID/UIDVALIDITY/UID. The phone deduplicates SHA-256 identifiers until expiry, with no previews in its ledger. Claiming before posting leaves a small crash window that can lose an alert. Android stores displayed notification text; enabled previews are exposed to authorized notification listeners. Preview-capable phone profiles separately opt in to display: missing or non-boolean `show_previews` remains off. Server preview fields alone cannot enable phone display. Synthetic test alerts remain generic. Public notification copies contain only generic text; Android/user/channel policy controls lock-screen visibility.

## Lifecycle

One profile binds one connector and approved mailbox IDs. Up to eight profiles, with distinct keys/subscriptions. Endpoint changes invalidate pairing. Remove/unregister on the phone and revoke the receiver fingerprint on the server. Deleting server state creates a new source UUID and requires pairing again.

The connector accepts legacy bare PushSubscriptions for v1 fixture/developer clients. The phone intentionally accepts only bound v2; no downgrade fallback.

No phone delivery acknowledgements, direct-message navigation, message actions, read-state clearing or Proton sign-out synchronization. Delivery depends on Bridge, push service/distributor and Android power management.
