# MailPush Connector

**0.3.0a1 — connector for the MailPush Proton Mail fork.** Watches an unmodified Proton Mail Bridge and sends encrypted alerts to the receiver embedded in the fork through UnifiedPush. Notification taps enter the fork's normal account and app-lock flow. Start with the [repository overview](../README.md).

Python 3.11+; Docker, venv, pipx and systemd use the same package/config/state. Linux connector behavior has automated fixture coverage, and the owner reported a working TrueNAS deployment; the native service and macOS/Windows installation examples have not been independently executed here. Bridge needs a Proton subscription that includes Bridge access. Mail only.

## Start with the guide for your installation

| Your setup | Complete instructions |
| --- | --- |
| TrueNAS Apps manager | [TrueNAS installation](../docs/INSTALL_TRUENAS.md) |
| Ordinary Linux Docker Compose | [Compose installation](deploy/DOCKER.md) |
| Bridge already on a Linux/macOS host; foreground connector | [Native venv installation](deploy/NATIVE.md#foreground-run-as-your-own-user) |
| Dedicated Linux systemd service | [Native service installation](deploy/NATIVE.md#linux-systemd-dedicated-service-account) |
| Phone, pairing and APK upgrades | [Android setup](../docs/INSTALL_ANDROID.md) |
| Permissions, pairing, TLS, login or silent phone | [Troubleshooting](../docs/TROUBLESHOOTING.md) |

Choose one server deployment manager. The TrueNAS Apps and ordinary Compose
instructions use different volume/project handling; do not manage an Apps stack
by starting a second Compose stack from the example checkout.

The setup order is **Bridge login → verified certificate/config/password → phone
request → connector pairing → fingerprint comparison → phone receipt import →
connection check → encrypted test → normal service**. Use Bridge's generated IMAP
password, never your Proton account password. A subscription file does not exist
until pairing creates it; do not start `run` against an incomplete config.

The phone's one-time key belongs at the connector's hidden pairing prompt, not
in a command, repository or support issue. Requests and receipts expire after one
day; keep the matching key separate from the encrypted transfer. The recipient
private key stays on the phone. HTTP acceptance of a test is not a phone receipt.

The included Bridge container wraps Proton's pinned official amd64 installer
without changing it. It is unofficial packaging, not a Proton-supported container.
The connector is architecture-independent. No Docker socket, inbound setup API,
proprietary Proton API or database server is needed. For another Bridge image or
host-network variant, use the corresponding section in the Compose guide.

## Operations

These are **foreground-venv reference commands**, run from `MailPush/connector`
after completing the native setup. They do not assume an activated shell or a
global `mailpush` executable. For systemd, use the dedicated service-user and
`/opt/mailpush/venv/bin/mailpush` commands in its guide; for Docker, use its
container commands.

Run `cd /absolute/path/to/MailPush/connector` first. Choose **one** operation;
this table is not a script to run from top to bottom.

| Task | Foreground venv command |
| --- | --- |
| Version | `.venv/bin/mailpush --version` |
| Read-only config/TLS/login check | `.venv/bin/mailpush check --config config.toml` |
| Import a fresh pairing request | `.venv/bin/mailpush pair --config config.toml --device phone --request pairing/phone.mailpush --receipt pairing/phone.receipt` |
| Run the normal service | `.venv/bin/mailpush run --config config.toml` |
| Send a synthetic test, with service stopped | `.venv/bin/mailpush test --config config.toml --device phone` |
| Deliberately revoke the device | `.venv/bin/mailpush revoke --config config.toml --device phone` |
| Inspect state | `.venv/bin/mailpush status --state-dir ./state` |
| Check worker heartbeat | `.venv/bin/mailpush healthcheck --state-dir ./state` |
| Optional new VAPID sender key | `.venv/bin/mailpush vapid-keygen --private secrets/vapid-private.pem` |

`check` makes a read-only IMAP connection and sends no alert. `test` and `run`
share an instance lock: stop a running connector before sending a synthetic test.
`certificate` observes a server certificate without logging in, but an observed
fingerprint is not automatically trusted. Compare it with your own Bridge
certificate. Verified TLS pinning/CA trust is recommended even on loopback; the
program's explicit loopback-only `tls = "none"` option is not the recommended
privacy-focused setup.

`revoke` persistently blocks the receiver fingerprint, including in a running service. Also remove its distributor registration. For a replacement, create a fresh phone profile/keys, stop the connector, `pair --replace`, import the new receipt, and restart. Reusing revoked keys does not undo revocation.

`healthcheck` checks process/worker heartbeats, not upstream or phone reachability. `status` reports mailbox scans, queue size and send outcomes without endpoints, credentials or previews. There is no phone acknowledgement: `accepted_by_push_server` means HTTP acceptance only.

TOML paths are relative to the config file. `MAILPUSH_CONFIG` selects a default file; `MAILPUSH_STATE_DIR` overrides state. Configured `*_env` fields can replace `*_file` secrets; files are preferable. Unix secrets must not be world-accessible or group-writable. On Windows, set private NTFS ACLs; POSIX checks do not enforce Windows ACLs.

State contains encrypted alerts, UID checkpoints, hashed account bindings, a stable source UUID and diagnostic timing. Keep it private. Reusing a mailbox ID for a changed username/folder is rejected: use a new ID and a freshly approved phone profile. A remote account replaced behind an identical username/folder cannot be detected.

## Mail and delivery

- One read-only IMAP connection per account/folder. IDLE where supported; periodic reconciliation/polling otherwise. Latency includes Bridge synchronization.
- First start baselines existing mail without alerts. Restarts catch up within `max_age_seconds`. UIDVALIDITY resets establish a new baseline and can miss alerts during the reset. Moving/copying mail into a watched folder can look new.
- Already-read new messages are skipped by default. No bodies or attachments are fetched. Optional previews read only From/Subject using `BODY.PEEK`.
- Ciphertext and checkpoints commit together. A bounded durable outbox retries with backoff and expires at TTL. Full queues pause checkpoint advancement; permanent failures are counted/dropped. Recipient changes discard incompatible ciphertext.
- Network ambiguity can repeat deliveries. Stable event IDs and phone deduplication suppress repeats until expiry. A narrow phone crash window between claiming an event and posting it can lose an alert; exactly-once delivery is not promised.
- Notifications do not clear when mail is read elsewhere. Taps select the bound account in the fork, with no direct-message navigation or actions. The fork revokes its local profile on account removal; revoke the connector's device separately to stop sending to it.

## Encryption and privacy

RFC 8291 `aes128gcm` encrypts each alert to the phone's P-256 key using maintained pywebpush. The UnifiedPush Android library decrypts using Tink. Plaintext is padded to 2048 bytes. The phone validates encryption, binding/source, approved mailbox, type and expiry before displaying anything. Keys remain app-private and wrapped with Android Keystore; backups are disabled.

Alerts say “You have new mail” by default. To display sender/subject with a preview-capable fork APK, set `preview = true` in the relevant mailbox and enable **Show sender and subject** on that phone profile. The original 0.3.0-alpha.1 APK always remains generic. Preview fields stay inside the encrypted, padded payload; only From/Subject headers are fetched, and no email text appears in HTTP headers. Displayed previews are shared with Android's notification system and authorized notification listeners; Android's lock-screen settings control visibility. Requests disable ntfy Firebase forwarding. The receiver delegates push networking to the distributor; the full Proton app still needs Internet access for mail. See [root SECURITY.md](../SECURITY.md) for the exact notification privacy and upstream telemetry limits.

Compatible public ntfy services can carry ciphertext but still see endpoints, IPs, sizes and timing, and can delay/drop/replay packets. They must permit UnifiedPush publishing; the distributor must remain connected. Use the exact returned endpoint/query, not an arbitrary topic. Bearer auth or VAPID controls access separately from encryption. HTTPS is verified; redirects and ambient proxy/.netrc settings are disabled.

Bridge and its host retain decrypted-mail access. Protect/encrypt host storage and backups. This is unaudited alpha software. See [root security policy](../SECURITY.md), [PROTOCOL.md](PROTOCOL.md), and [validation](../VALIDATION.md).

## Updates and development

Bridge and this connector remain independently replaceable. Stop the connector, back up config/secrets/state, replace its wheel/container, then restart with existing state. Use [native upgrades](deploy/NATIVE.md#upgrades) or the deployment guide's existing-installation steps. The Android fork follows the separate [checked-patch update process](../docs/UPDATES.md). Endpoint changes require re-pairing. Phone updates need the same APK signing key; keep your private backup private.

```sh
cd /absolute/path/to/MailPush/connector
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip wheel --no-deps . --wheel-dir dist
```

Versions are pinned in `requirements-lock.txt`. The local demo receiver is a fixture, not a phone app. MIT license. Unaffiliated with Proton, ntfy or UnifiedPush.
