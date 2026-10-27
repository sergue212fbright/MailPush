# Native connector: virtual environment or Linux service

Docker is optional. This installs **only the connector**, alongside an existing,
logged-in Proton Mail Bridge. Bridge remains a separate application and must keep
running. Use its generated IMAP username/password, never your Proton login
password. Python **3.11+**, `venv`, and package-download access are required.

This guide uses Bash on an ordinary Linux host; the foreground route also uses
standard macOS paths. **Do not install Python packages or a systemd service into
the TrueNAS host OS.** Use [TrueNAS Apps](../../docs/INSTALL_TRUENAS.md) there.
Phone setup is in [INSTALL_ANDROID.md](../../docs/INSTALL_ANDROID.md).

Choose **one** route below. Existing installations should use [Upgrades](#upgrades)
rather than recreate config, state or pairing.

## Foreground: run as your own user

Run from a checkout directory you own. Every relative command below starts in
**`MailPush/connector`**, not the repository root or `connector/deploy`:

```sh
cd /absolute/path/to/MailPush/connector
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps .
if [ ! -e config.toml ]; then cp config.example.toml config.toml; fi
mkdir -p secrets state pairing
chmod 700 secrets state pairing
chmod 600 config.toml
```

Edit `config.toml`. Keep `schema = 1`, set Bridge's actual username/IMAP port,
`tls = "starttls"` for STARTTLS (or `"tls"` for its implicit TLS listener), and a
**verified** `tls_pin_sha256`. Keep `state_dir = "state"`,
`subscription_file = "secrets/phone-subscription.json"`, and
`password_file = "secrets/bridge-password"` for this foreground layout.

Export Bridge's public certificate through its own interface and inspect its
SHA-256 fingerprint. For a public PEM file at `bridge-cert.pem`:

```sh
openssl x509 -in bridge-cert.pem -noout -fingerprint -sha256
```

A trusted `ca_file` is an alternative to pinning; choose one. If exporting also
produces a private `key.pem`, keep that key private and out of the connector.
`certificate` only observes a listening server; it does not establish trust:

```sh
.venv/bin/mailpush certificate --host 127.0.0.1 --port 1143 --tls starttls
```

Create a new private password file without putting its contents in command
history. Existing files are retained:

```sh
if [ -e secrets/bridge-password ]; then
  printf 'Existing password retained.\n'
else
  (umask 077; : > secrets/bridge-password)
  IFS= read -r -s -p 'Bridge IMAP password: ' MAILPUSH_BRIDGE_PASSWORD
  printf '\n'
  printf '%s\n' "$MAILPUSH_BRIDGE_PASSWORD" > secrets/bridge-password
  unset MAILPUSH_BRIDGE_PASSWORD
  chmod 600 secrets/bridge-password
fi
```

On the phone, bind mailbox ID `personal` and export a fresh encrypted request.
Privately copy it to `pairing/phone.mailpush`, keeping the one-time key separate.
**Stop any running connector first** (Ctrl+C for a foreground process):

```sh
chmod 600 pairing/phone.mailpush
.venv/bin/mailpush pair --config config.toml --device phone \
  --request pairing/phone.mailpush --receipt pairing/phone.receipt
```

Enter the matching phone key at the hidden prompt. Compare fingerprints, copy
`pairing/phone.receipt` back, and import it into that same phone profile. Pairing
is an offline import and does not need a listening setup port. The generated
private subscription is separate from those temporary transfers.

```sh
.venv/bin/mailpush check --config config.toml &&
.venv/bin/mailpush test --config config.toml --device phone
```

`check` should report `code=imap_ok`; it sends no alert. If either command fails,
fix that stage before continuing. Confirm the **phone** receives **Encrypted test
received**, then start the normal service:

```sh
.venv/bin/mailpush run --config config.toml
```

Send a fresh unread email; initial startup baselines old mail. Ctrl+C stops the
foreground service.
`test` and `run` share an instance lock: do not run a test beside the service.

In another shell, use the same directory for status:

```sh
cd /absolute/path/to/MailPush/connector
.venv/bin/mailpush status --state-dir ./state
```

All TOML-relative paths resolve beside the config file, not beside the executable.
An exported `MAILPUSH_STATE_DIR` overrides TOML: ensure it does not send pairing
and the service to different state directories.

## Linux systemd: dedicated service account

This route is independent of the foreground route. Run its installation commands
from **`MailPush/connector`**. If replacing an existing service, stop it before
changing binaries; retain config, receiver bundle and state.

```sh
cd /absolute/path/to/MailPush/connector
id mailpush >/dev/null 2>&1 || sudo useradd --system --user-group \
  --home-dir /var/lib/mailpush --shell /usr/sbin/nologin mailpush
id mailpush
sudo install -d -o root -g root -m 755 /opt/mailpush
sudo python3 -m venv /opt/mailpush/venv
sudo /opt/mailpush/venv/bin/python -m pip install -r requirements-lock.txt
sudo /opt/mailpush/venv/bin/python -m pip install --no-deps .
sudo install -d -o root -g mailpush -m 750 /etc/mailpush /etc/mailpush/secrets
sudo install -d -o mailpush -g mailpush -m 700 /var/lib/mailpush /var/lib/mailpush/pairing
if sudo test -e /etc/mailpush/config.toml; then
  printf 'Existing service config retained.\n'
else
  sudo install -o root -g mailpush -m 640 config.example.toml /etc/mailpush/config.toml
fi
sudo nano /etc/mailpush/config.toml
```

The service uses the actual `mailpush` UID/GID created by your OS, **not** Docker's
fixed UID10001. If that account already existed, verify it is the intended private
service identity before continuing. `/opt` contains root-owned code; `/etc`
contains read-only configuration/secrets; `/var/lib/mailpush` is service-writable.

Use these **absolute paths** in the service config, plus Bridge's actual values:

```toml
schema = 1

[service]
state_dir = "/var/lib/mailpush"

[[devices]]
id = "phone"
subscription_file = "/var/lib/mailpush/phone-subscription.json"

[[mailboxes]]
id = "personal"
host = "127.0.0.1"
port = 1143
username = "REPLACE_WITH_BRIDGE_IMAP_USERNAME"
password_file = "/etc/mailpush/secrets/bridge-password"
tls = "starttls"
tls_pin_sha256 = "REPLACE_WITH_VERIFIED_BRIDGE_CERTIFICATE_SHA256"
folder = "INBOX"
devices = ["phone"]
preview = false
```

Replace existing tables rather than appending duplicates. For CA verification
instead of pinning, copy only Bridge's trusted **public certificate** into
`/etc/mailpush/secrets/bridge-ca.pem`, root:mailpush mode0640; configure its
absolute `ca_file` and remove `tls_pin_sha256`. `ProtectHome=true` prevents the
service from reading certificates/secrets in your home directory.

Create Bridge's password with a hidden prompt; leave an existing password intact:

```sh
if sudo test -e /etc/mailpush/secrets/bridge-password; then
  printf 'Existing service password retained.\n'
else
  sudo install -o root -g mailpush -m 640 /dev/null /etc/mailpush/secrets/bridge-password
  IFS= read -r -s -p 'Bridge IMAP password: ' MAILPUSH_BRIDGE_PASSWORD
  printf '\n'
  printf '%s\n' "$MAILPUSH_BRIDGE_PASSWORD" | sudo tee /etc/mailpush/secrets/bridge-password >/dev/null
  unset MAILPUSH_BRIDGE_PASSWORD
fi
```

Put the phone's fresh encrypted request in your SSH account's home directory as
`phone.mailpush`. While the service is stopped, copy/pair it as the service user:

```sh
sudo install -o mailpush -g mailpush -m 600 "$HOME/phone.mailpush" /var/lib/mailpush/pairing/phone.mailpush
sudo -u mailpush env MAILPUSH_STATE_DIR=/var/lib/mailpush \
  /opt/mailpush/venv/bin/mailpush pair --config /etc/mailpush/config.toml \
  --device phone --request /var/lib/mailpush/pairing/phone.mailpush \
  --receipt /var/lib/mailpush/pairing/phone.receipt
sudo install -o "$(id -u)" -g "$(id -g)" -m 600 /var/lib/mailpush/pairing/phone.receipt "$HOME/phone.receipt"
```

Compare fingerprints **before activation**, then transfer `phone.receipt` back
and import it into the same phone profile. Keep the one-time key separate. The
subscription is generated under `/var/lib/mailpush` as mailpush mode0600. There
is no need to make `/etc/mailpush/secrets` group-writable. Requests and receipts
expire after one day; use fresh matching transfers for a deliberate re-pair.

Check/test before starting systemd:

```sh
sudo -u mailpush env MAILPUSH_STATE_DIR=/var/lib/mailpush \
  /opt/mailpush/venv/bin/mailpush check --config /etc/mailpush/config.toml &&
sudo -u mailpush env MAILPUSH_STATE_DIR=/var/lib/mailpush \
  /opt/mailpush/venv/bin/mailpush test --config /etc/mailpush/config.toml --device phone
```

Stop here if the check fails. Confirm the phone receives the encrypted test,
then install/start the unit from the same `connector` directory:

```sh
sudo install -o root -g root -m 644 deploy/mailpush.service /etc/systemd/system/mailpush.service
sudo systemctl daemon-reload
sudo systemctl enable --now mailpush
sudo journalctl -u mailpush --since '5 minutes ago' --no-pager
sudo -u mailpush /opt/mailpush/venv/bin/mailpush status --state-dir /var/lib/mailpush
```

Send a fresh unread email after startup. The unit waits for network-online,
**not Bridge account readiness**, and does not start/manage Bridge. Let Bridge finish loading before
repeatedly testing credentials. Review [troubleshooting](../../docs/TROUBLESHOOTING.md)
for TLS, permission or login failures; never disable verification to bypass them.

## Upgrades

Stop `run`/systemd before replacing the package. Back up config, secrets,
subscription and the complete state directory privately. From the updated
checkout's **`connector`** directory, repeat the two pip-install commands for
**your existing venv**, then run its `check` once and resume the service. For
systemd, use `sudo systemctl stop mailpush` / `sudo systemctl start mailpush`;
view logs with `sudo journalctl -u mailpush -f`. Keep the same state path/source
UUID. Do not recopy the example over real config or delete the database.

For sender/subject previews, edit the existing mailbox's `preview = true`, restart
the connector, and enable **Show sender and subject** on the phone. Same-signer
APK updates preserve pairing; see [Android upgrades](../../docs/INSTALL_ANDROID.md#already-paired-updating-is-much-shorter).
Delete temporary request/receipt copies after success, keeping the installed
subscription and state. Uninstalling binaries does not require deleting those.

## pipx, macOS and Windows

`pipx install .` from `connector` is an optional alternative; it resolves the
pinned direct dependencies but does not apply this guide's complete transitive
lock. Use a venv above when you need the supplied lock exactly.

On Windows the venv executables are `.venv\Scripts\python.exe` and
`.venv\Scripts\mailpush.exe`. Use private NTFS ACLs for config, secrets and state;
POSIX mode checks do not enforce Windows ACLs. macOS/Windows supervision is
owner-managed: no launchd/Windows-service installer or validation is supplied.
