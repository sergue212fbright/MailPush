# MailPush Connector

**0.3.0a1 — connector for the MailPush Proton Mail fork.** Watches an unmodified Proton Mail Bridge and sends encrypted alerts to the receiver embedded in the fork through UnifiedPush. Notification taps enter the fork's normal account and app-lock flow. Start with the repository's root `README.md`.

Python 3.11+; Docker, venv, pipx and systemd all use the same package/config/state. Linux is validated here; macOS/Windows paths are provided but not executed. Bridge needs a Proton subscription that includes Bridge access. Mail only.

## Native quick start

Log into Bridge using its own interface and keep it running. Use Bridge's generated IMAP password, **never your Proton account password**, in this connector.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-lock.txt
.venv/bin/pip install --no-deps .
cp config.example.toml config.toml
mkdir -m 700 secrets
```

Edit `config.toml`: Bridge username/port, password file, trusted TLS certificate pin or CA, and mailbox IDs. Create the password file with mode 0600 (0640 with a private service group is accepted). Defaults are deliberately incomplete until you supply trust and pairing material.

To inspect a listening Bridge certificate without sending credentials:

```sh
.venv/bin/mailpush certificate --host 127.0.0.1 --port 1143 --tls starttls
```

This certificate is **observed, not automatically trusted**. Verify its SHA-256 fingerprint against your own Bridge installation, then set `tls_pin_sha256`. Alternatively set `ca_file` to Bridge's trusted exported certificate/CA. Certificate changes fail closed until deliberately verified. Explicit `tls = "none"` is permitted only on loopback for owners choosing local plaintext.

In the fork's Settings → Encrypted push, select a distributor, bind a signed-in account to matching mailbox IDs and export its encrypted request. Transfer it to the host; enter the phone's one-time key at the hidden prompt:

```sh
.venv/bin/mailpush pair --config config.toml --device phone --request phone.mailpush
```

Compare the printed fingerprint to the phone, transfer `phone.receipt` back and import it. Requests/receipts expire after one day. Transfer the key separately: anyone with both file and key can impersonate pairing. Delete transfer files afterward. The recipient private key stays on the phone.

```sh
.venv/bin/mailpush check --config config.toml
.venv/bin/mailpush test --config config.toml --device phone
.venv/bin/mailpush run --config config.toml
```

`check` makes a read-only IMAP connection. `test` queues a synthetic encrypted alert and makes one delivery pass. Stop a running connector before `test`; both use the state lock. HTTP acceptance is not phone receipt. Check the phone and `status`.

## Deployment

| Installation | Entry point |
| --- | --- |
| Bridge + connector in Docker | [deploy/DOCKER.md](deploy/DOCKER.md) |
| Existing host Bridge | Native commands, or Docker host variant |
| Linux service | [deploy/NATIVE.md](deploy/NATIVE.md) |
| Other supervisor / pipx | `mailpush run --config ...` |

The included Bridge container wraps Proton's pinned official amd64 installer without changing it. This is unofficial container packaging, not a Proton-supported container. The connector is architecture-independent. No Docker socket, inbound HTTP API, proprietary Proton API or database server is needed.

## Operations

```sh
mailpush --version
mailpush check --config config.toml
mailpush pair --config config.toml --request phone.mailpush --device phone
mailpush run --config config.toml
mailpush test --config config.toml --device phone
mailpush revoke --config config.toml --device phone
mailpush status --state-dir ./state
mailpush healthcheck --state-dir ./state
mailpush vapid-keygen --private secrets/vapid-private.pem
```

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

Alerts say “You have new mail” by default. To display sender/subject with a preview-capable fork APK, set `preview = true` in the relevant mailbox and enable **Show sender and subject** on that phone profile. The original 0.3.0-alpha.1 APK always remains generic. Preview fields stay inside the encrypted, padded payload; only From/Subject headers are fetched, and no email text appears in HTTP headers. Displayed previews are shared with Android's notification system and authorized notification listeners; Android's lock-screen settings control visibility. Requests disable ntfy Firebase forwarding. The receiver delegates push networking to the distributor; the full Proton app still needs Internet access for mail. See root `SECURITY.md` for the exact notification privacy and upstream telemetry limits.

Compatible public ntfy services can carry ciphertext but still see endpoints, IPs, sizes and timing, and can delay/drop/replay packets. They must permit UnifiedPush publishing; the distributor must remain connected. Use the exact returned endpoint/query, not an arbitrary topic. Bearer auth or VAPID controls access separately from encryption. HTTPS is verified; redirects and ambient proxy/.netrc settings are disabled.

Bridge and its host retain decrypted-mail access. Protect/encrypt host storage and backups. This is unaudited alpha software. See the kit's `SECURITY.md`, [PROTOCOL.md](PROTOCOL.md) and [VALIDATION.md](VALIDATION.md).

## Updates and development

Bridge and this connector remain independently replaceable. Stop the connector, back up config/secrets/state, replace its wheel/container, then restart with existing state. The Android fork follows the separate checked-patch update process in root `docs/UPDATES.md`. Endpoint changes require re-pairing. Phone updates need the same APK signing key; keep your private backup private.

```sh
python -m unittest discover -s tests -v
python -m build
```

Versions are pinned in `requirements-lock.txt`. The local demo receiver is a fixture, not a phone app. MIT license. Unaffiliated with Proton, ntfy or UnifiedPush.
