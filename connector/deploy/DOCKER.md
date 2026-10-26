# Docker Compose setup

**Choose one deployment manager.** This page is for ordinary Linux Docker
Compose. For the **TrueNAS Apps manager**, use the separate
[TrueNAS installation guide](../../docs/INSTALL_TRUENAS.md); pasting these relative
Compose paths into Apps can mount the wrong directory or create a second stack.
For an existing working installation, use its upgrade section rather than
repeating setup or replacing its volumes.

The supplied wrapper packages Proton's unmodified official Bridge 3.27.1 amd64
Debian installer and verifies a fixed SHA-256. The connector is independently
installable; see [native installation](NATIVE.md) for a host Bridge. This wrapper
has not been built/run in the build workspace. An owner has reported working
TrueNAS deployment, with its separate [validation scope](../../VALIDATION.md).

## Before starting

Run the shell snippets in **Bash**. You need Docker Compose, an eligible Proton Bridge subscription, a signed MailPush
fork APK and a compatible phone UnifiedPush distributor/service. Phone setup is
in [INSTALL_ANDROID.md](../../docs/INSTALL_ANDROID.md).

Clone/extract the project, then **run all commands below from
`connector/deploy`**. The `-p mailpush` argument keeps this guide's Compose project
and volume names consistent. Keep using it for this deployment.

```sh
cd /absolute/path/to/MailPush/connector/deploy
pwd
sudo docker compose -p mailpush build
sudo mkdir -p config/secrets pairing
sudo chown root:10001 config config/secrets pairing
sudo chmod 750 config config/secrets
sudo chmod 770 pairing
if sudo test -e config/config.toml; then
  printf 'Existing config retained: config/config.toml\n'
else
  sudo cp ../config.example.toml config/config.toml
fi
sudo chown root:10001 config/config.toml
sudo chmod 640 config/config.toml
```

Paths inside `compose.yaml` are relative to this directory:

| Host/deployment item | Container path |
| --- | --- |
| `config/config.toml` | `/config/config.toml` |
| `config/secrets/bridge-password` | `/config/secrets/bridge-password` |
| Compose `mailpush_bridge-data` volume | Bridge `/data` |
| Compose `mailpush_connector-data` volume | Connector `/data` |

The images run as UID/GID **10001:10001**. That is different from a host
`apps:apps` account. Do not apply recursive ownership changes to the repository.

## 1. Log into Bridge and export its trusted certificate

Do not start a second Bridge against the same data volume.

```sh
sudo docker compose -p mailpush run --name mailpush-bridge-login --no-deps -it bridge --cli
```

Inside Bridge's prompt, run `help`, `login`, and then `list` / `info 0` after
initial synchronization. Use the actual account index from `list`. Privately
record Bridge's IMAP username, generated password, IMAP port and security mode;
**the connector does not use your normal Proton password**.

For privacy, run `telemetry disable` and confirm if asked. Run `cert export` and
enter `/data` as the destination, then `exit`. That command exports a public
`cert.pem` and private `key.pem` inside the private Bridge volume. Copy **only**
the public certificate:

```sh
sudo docker cp mailpush-bridge-login:/data/cert.pem ./bridge-cert.pem
sudo openssl x509 -in bridge-cert.pem -noout -fingerprint -sha256
sudo docker rm mailpush-bridge-login
sudo docker compose -p mailpush up -d bridge
```

Keep the fingerprint for the next step. Removing the stopped setup container
does not remove its Compose data volume. Do not run `down -v` or remove volumes.
Bridge uses a pass/GPG local credential store in `/data`, with a passphrase-free
local key for unattended restarts. Protect/encrypt the host and backups: someone
who can read the complete volume can recover local credentials and mail data.

## 2. Configure the connector

Edit `config/config.toml`. This is a **complete minimal config**. Replace the
file's contents with it and supply your Bridge username, verified certificate
fingerprint and actual IMAP port:

```toml
schema = 1

[service]
state_dir = "/data"

[[devices]]
id = "phone"
subscription_file = "/data/phone-subscription.json"

[[mailboxes]]
id = "personal"
host = "127.0.0.1"
port = 1143
username = "REPLACE_WITH_BRIDGE_IMAP_USERNAME"
password_file = "/config/secrets/bridge-password"
folder = "INBOX"
tls = "starttls"
tls_pin_sha256 = "REPLACE_WITH_VERIFIED_BRIDGE_CERTIFICATE_SHA256"
devices = ["phone"]
preview = false
skip_seen = true
use_idle = true
```

**Replace** the file rather than appending duplicate service/mailbox/device
tables. Keep `schema = 1` at the top. Use Bridge's
actual port. `starttls` means STARTTLS; use `tls` only for Bridge's deliberately
configured implicit TLS/SSL listener. A verified exported certificate `ca_file`
is an alternative to pinning; do not configure both. Never disable verification.

Create the Bridge password file with a hidden prompt:

```sh
if sudo test -e config/secrets/bridge-password; then
  printf 'Existing password retained. Do not repeat first-install credential setup.\n'
else
  sudo install -o root -g 10001 -m 0640 /dev/null config/secrets/bridge-password
  IFS= read -r -s -p 'Bridge IMAP password: ' MAILPUSH_BRIDGE_PASSWORD
  printf '\n'
  printf '%s\n' "$MAILPUSH_BRIDGE_PASSWORD" | sudo tee config/secrets/bridge-password >/dev/null
  unset MAILPUSH_BRIDGE_PASSWORD
  sudo chown root:10001 config/secrets/bridge-password
  sudo chmod 640 config/secrets/bridge-password
fi
sudo stat -c '%a %u:%g %n' config/config.toml config/secrets/bridge-password
```

Expected file metadata is `640 0:10001`. Files must not be group-writable or
accessible to other users. The receiver bundle lives in the connector's `/data`
volume, avoiding host ACLs that can force new secret files to mode `0770`.
It does not exist until the next step.

## 3. Pair: request goes to server, receipt comes back to phone

Follow [Android setup](../../docs/INSTALL_ANDROID.md) to configure the distributor
and bind a phone profile to mailbox ID `personal`. Export its encrypted request
to your SSH account's home directory as `phone.mailpush`. The commands below
copy it into the protected `pairing` folder. Keep its one-time key separate.

The Bridge service must be running because the Compose connector shares its
network namespace. Pause the connector if it was already running:

```sh
sudo docker compose -p mailpush stop connector
sudo cp "$HOME/phone.mailpush" pairing/phone.mailpush
sudo chown root:10001 pairing/phone.mailpush
sudo chmod 640 pairing/phone.mailpush
sudo docker compose -p mailpush run --rm --no-deps -it \
  -v "$PWD/pairing:/pairing:rw" connector \
  pair --config /config/config.toml --device phone --request /pairing/phone.mailpush
```

The pair command itself performs no network exchange. Enter the fresh phone key
at its hidden prompt. **Compare the printed fingerprint with the phone**, then
copy the encrypted receipt into your SSH account's private home directory:

```sh
sudo install -o "$(id -u)" -g "$(id -g)" -m 0600 pairing/phone.receipt "$HOME/phone.receipt"
```

Transfer that `phone.receipt` back and import it into the same profile. Do not
make the protected directory public to avoid an ownership error. Requests and
receipts expire after a day. Use a fresh request/key, and `--replace` only for a
deliberate re-pair.

## 4. Check, test, then start

Bridge's listener can start before its account finishes loading. Allow it to
warm; do not rapidly retry authentication or repeatedly restart it.

```sh
sudo docker compose -p mailpush run --rm --no-deps connector check --config /config/config.toml
```

Expected:

```text
mailbox=personal code=imap_ok idle=True
Configuration and receiver keys valid. No notification was sent.
```

If the check fails, keep the connector stopped and use
[troubleshooting](../../docs/TROUBLESHOOTING.md). A wrong password, wrong Bridge
volume and temporarily unloaded account require different fixes.

After the check succeeds and the receipt is imported:

```sh
sudo docker compose -p mailpush run --rm --no-deps connector test --config /config/config.toml --device phone
sudo docker compose -p mailpush up -d connector
sudo docker compose -p mailpush logs --since 30s --tail 30 connector
sudo docker compose -p mailpush exec connector mailpush status --state-dir /data
```

The encrypted test should reach the phone as **Encrypted test received**. A
queued/accepted test or healthy container is not a phone-delivery receipt. Initial
service startup baselines old mail, so send a **fresh email**, leave it unread and
check the phone. Then verify your own screen-off/reboot/app-lock scenarios.

For sender/subject previews, set the mailbox's `preview = true`, run
`sudo docker compose -p mailpush restart connector`, and enable **Show sender and
subject** in that phone profile. Only the connector needs restarting for that
config edit. See [preview privacy and behavior](../../docs/NOTIFICATION_PREVIEWS.md).

Remove temporary pairing transfer copies after success. Keep protected backups
of config, subscription/state, Bridge storage and the private APK signing backup.

## Daily operation and upgrades

```sh
sudo docker compose -p mailpush logs --since 5m --tail 60 connector
sudo docker compose -p mailpush restart connector
sudo docker compose -p mailpush stop
sudo docker compose -p mailpush start
```

Use `start` for existing stopped containers. Use `up -d` when applying intentional
image/configuration changes. If Bridge is recreated, recreate the connector too
so it joins the new namespace. Preserve named volumes during updates;
**`docker compose down -v` destroys this stack's stored credentials/checkpoints**.
A same-signer phone APK update preserves its existing account and pairing; do not
uninstall/re-pair just to update the app.

## Existing Bridge and other platforms

* **Linux host Bridge:** use `compose.host.yaml`. Add `-f compose.host.yaml` to
  every Compose command for that deployment. It runs only the connector with
  host networking. Log into/export the certificate using your existing host
  Bridge; do not run this guide's Bridge service/login commands.
* **Another reviewed Bridge image or architecture:** use `compose.external.yaml`
  with `BRIDGE_IMAGE` set to an image and fixed version you trust. Adapt its
  volume paths/login/certificate instructions. The supplied official installer
  wrapper is **amd64 only**.
* **macOS/Windows host Bridge:** a [native connector](NATIVE.md) avoids Docker
  Desktop loopback differences, which have not been validated here.

The connector alone can build on architectures supported by Python/cryptography;
that does not make the pinned amd64 Bridge package an ARM image.

Primary references: [Proton Bridge CLI guide](https://proton.me/support/bridge-cli-guide),
[pinned CLI certificate-export implementation](https://github.com/ProtonMail/proton-bridge/blob/v3.27.1/internal/frontend/cli/system.go),
[official Bridge release](https://github.com/ProtonMail/proton-bridge/releases/tag/v3.27.1).
