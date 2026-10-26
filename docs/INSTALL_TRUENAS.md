# TrueNAS Apps: install MailPush

Run the shell snippets in **Bash**. This guide is for **Linux amd64 TrueNAS with Docker-based Apps** and the supplied
Bridge wrapper. It uses the Apps manager for the running application and the
TrueNAS shell for one-time setup. The wrapper packages Proton's unmodified Bridge
3.27.1. One owner has reported working TrueNAS → Bridge → ntfy → GrapheneOS delivery,
including sender/subject previews. This is alpha software, not a general TrueNAS
compatibility certification; see [validation](../VALIDATION.md).

**Already receiving notifications? Do not repeat fresh setup.** Use
[Existing installations](#existing-installations) below. In particular, keep your
existing Bridge volume, connector volume, config and phone pairing.

For ordinary Docker Compose, use [the Compose guide](../connector/deploy/DOCKER.md).
For the phone, use [Android setup](INSTALL_ANDROID.md).

## The four pieces

| Piece | What it does | Where it runs |
| --- | --- | --- |
| Official Proton Mail Bridge | Logs in to Proton and provides local IMAP | Bridge container |
| MailPush connector | Detects new mail and encrypts alerts | Connector container |
| UnifiedPush distributor, such as a compatible ntfy Android build | Receives push traffic | Phone |
| MailPush Proton Mail fork | Decrypts alerts and posts Proton Mail notifications | Phone |

You need a Proton plan eligible for Bridge, a signed MailPush APK, a compatible
UnifiedPush distributor, and an HTTPS push service. Your own ntfy server and a
compatible public service are both possible. The relay receives encrypted alert
contents; it can still observe connection metadata. Bridge's host has decrypted
mail access, so protect its storage and backups.

## Fresh setup: choose one directory

Use a dedicated application directory on your pool. The example below uses
`/mnt/tank/apps/mailpush`; **change that example to your actual pool/dataset path**.
Do not install packages into the TrueNAS host OS. Git, Docker and an editor must
already be available, or upload/extract the source using your normal admin tools.

```sh
MAILPUSH_ROOT=/mnt/tank/apps/mailpush
sudo git clone https://github.com/sergue212fbright/MailPush.git "$MAILPUSH_ROOT"
cd "$MAILPUSH_ROOT/connector/deploy"
pwd
```

If the source already exists, do not clone over it. Set `MAILPUSH_ROOT` to its
existing directory, then run the last two commands. **Keep this shell open**:
commands below use its current directory. After reconnecting, set the variable and
`cd` again.

The output of `pwd` must end in **`/connector/deploy`**. The Compose file is
`connector/deploy/compose.yaml`, not the repository root.

| Host path relative to this directory | Container path | Contents |
| --- | --- | --- |
| `config/config.toml` | `/config/config.toml` | Connector settings |
| `config/secrets/bridge-password` | `/config/secrets/bridge-password` | Bridge-generated IMAP password |
| `pairing/phone.mailpush` | `/pairing/phone.mailpush`, during pairing only | Encrypted phone request |
| Docker volume `mailpush-bridge-data` | Bridge `/data` | Bridge account/cache/local keychain |
| Docker volume `mailpush-connector-data` | Connector `/data` | Checkpoints, queue, private subscription bundle |

Fresh setup deliberately uses explicit external volume names. They are shared
by the login step and the Apps YAML, so you cannot accidentally log into one
Bridge volume and run another. **Existing Apps installations may instead use
`ix-mailpush_bridge-data` and `ix-mailpush_connector-data`. Do not replace them
with these fresh-setup volumes.**

## 1. Build the two local images and create persistent storage

Run in `connector/deploy`:

```sh
sudo docker compose build
sudo docker image inspect mailpush-bridge:3.27.1 mailpush-connector:0.3.0a1 >/dev/null
sudo docker volume create mailpush-bridge-data
sudo docker volume create mailpush-connector-data
sudo mkdir -p config/secrets pairing
sudo chown root:10001 config config/secrets pairing
sudo chmod 750 config config/secrets
sudo chmod 770 pairing
```

The containers run as **UID/GID `10001:10001`**. The TrueNAS host's `apps:apps`
account is commonly `568:568`; that is a different identity. Do not recursively
change the whole source tree to `apps:apps`, and do not use `chmod 777`.

Initialize only the connector volume's top directory:

```sh
sudo docker run --rm --pull=never --network none --user 0:0 \
  --mount type=volume,src=mailpush-connector-data,dst=/data \
  --entrypoint sh mailpush-connector:0.3.0a1 \
  -c 'chown 10001:10001 /data && chmod 700 /data'
```

**Checkpoint:** both `docker image inspect` and the initialization command must
succeed. `pull=never` errors mean the image was not built on this TrueNAS host;
do not substitute an unknown image or continue with an empty image variable.

## 2. Log into Bridge once, in the same volume Apps will use

Do not run another Bridge against this volume at the same time.

```sh
sudo docker run --name mailpush-bridge-login -it --pull=never \
  --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true \
  --mount type=volume,src=mailpush-bridge-data,dst=/data \
  mailpush-bridge:3.27.1 --cli
```

Inside the **Bridge prompt**, not your Linux shell:

1. Enter `help` to confirm the commands for this version.
2. Enter `login` and complete Proton authentication privately.
3. Wait for initial synchronization to finish.
4. Enter `list`, then `info 0` for the first account. With multiple accounts, use
   the actual index shown by `list`.
5. Privately record **IMAP username, IMAP password, port and security mode**.
   These are Bridge's mail-client credentials. The connector must **not** use
   your normal Proton login password.
6. For the privacy-focused setup, enter `telemetry disable` and confirm if asked.
7. Enter `cert export`; when asked for a path, enter `/data`.
8. Enter `exit` after the export succeeds.

`cert export` writes **both** `cert.pem` and `key.pem`. They stay inside the private
Bridge volume. Copy only the public certificate and inspect its fingerprint:

```sh
sudo docker cp mailpush-bridge-login:/data/cert.pem ./bridge-cert.pem
sudo openssl x509 -in bridge-cert.pem -noout -fingerprint -sha256
sudo docker rm mailpush-bridge-login
```

Keep the printed SHA-256 fingerprint for the next step. The stopped setup
container can be removed; the external volume retains the Bridge account and
certificate. Do not copy `key.pem` into the source repository, pairing folder or
public issue.

If a failed earlier attempt left `mailpush-bridge-login`, inspect it before
reusing the name. `sudo docker start -ai mailpush-bridge-login` resumes its CLI.
Do not launch a second copy against the same volume.

## 3. Write the connector config and password

```sh
if sudo test -e config/config.toml; then
  printf 'Existing config retained: config/config.toml\n'
else
  sudo cp ../config.example.toml config/config.toml
fi
sudo chown root:10001 config/config.toml
sudo chmod 640 config/config.toml
sudo nano config/config.toml
```

Use this minimal structure, replacing only the three marked Bridge values:

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
port = 1143 # Replace if Bridge's IMAP port differs.
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

Keep `tls = "starttls"` when Bridge says STARTTLS. For an intentionally configured
implicit TLS/SSL listener, use `tls = "tls"` and its actual port. The fingerprint
may contain colons; the connector normalizes them. Trusting Bridge's exported
certificate as `ca_file` is an alternative, but do not configure both methods.
Never disable TLS to get past a certificate error.

Create the password file using a hidden prompt. This keeps the password out of
command history and chat:

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

**Checkpoint:** both files should show `640 0:10001`. The connector accepts secret
file modes `0600` or `0640`; group-writable or other-user-accessible secret files
are rejected. If ACLs force new files to `0770`, see
[permissions troubleshooting](TROUBLESHOOTING.md#permissions-and-acls).

`subscription_file` is intentionally in the connector's **Docker volume** at
`/data/phone-subscription.json`. It does not exist yet. Pairing creates it in step
4. Do not create an empty subscription file or change the config back to a host
ACL-controlled secret directory.

## 4. Pair the phone before starting the connector

Follow [Android setup](INSTALL_ANDROID.md) through exporting the encrypted pairing
request. Use mailbox ID **`personal`** on the phone, matching the config above.
First transfer the encrypted request to your SSH account's home directory as
`phone.mailpush`. The commands below copy it into the protected deployment
folder. Keep the phone's one-time pairing key separate from the request.

```sh
sudo cp "$HOME/phone.mailpush" pairing/phone.mailpush
sudo chown root:10001 pairing/phone.mailpush
sudo chmod 640 pairing/phone.mailpush
sudo docker run --rm -it --pull=never --user 10001:10001 \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --env MAILPUSH_STATE_DIR=/data \
  --mount "type=bind,src=$PWD/config,dst=/config,readonly" \
  --mount "type=bind,src=$PWD/pairing,dst=/pairing" \
  --mount type=volume,src=mailpush-connector-data,dst=/data \
  mailpush-connector:0.3.0a1 pair --config /config/config.toml \
  --device phone --request /pairing/phone.mailpush
```

Enter the **one-time key currently shown by the phone** at the hidden prompt.
Successful output begins `Pairing imported. Compare fingerprint with phone:`.

1. Compare the connector's fingerprint with the phone's fingerprint.
2. Copy the newly generated encrypted receipt to your SSH account's home
   directory, readable only by your account:

   ```sh
   sudo install -o "$(id -u)" -g "$(id -g)" -m 0600 pairing/phone.receipt "$HOME/phone.receipt"
   ```

   Transfer that `phone.receipt` back to the phone. Do not make the protected
   pairing directory public just to copy it.
3. Import the receipt into the **same phone profile** that exported the request.

The phone-to-server request and server-to-phone receipt are different files.
Both pairing transfers expire; a wrong key, old request or wrong profile requires
exporting a fresh request. Do not repeatedly guess keys. An existing subscription
requires a deliberate `--replace` re-pair, not deletion of all state.

## 5. Install the running application in TrueNAS Apps

In the Apps manager, choose **Install via YAML** for a Custom App. Use the
application name **`mailpush`**: lowercase letters, not `MailPush`, spaces or
underscores. Exact menu placement varies between TrueNAS versions.

Paste this Compose YAML. **Change its one absolute `source:` path** to the actual
`connector/deploy/config` directory from your `pwd`. The images were built in
step 1; `pull_policy: never` uses those local images.

```yaml
services:
  bridge:
    image: mailpush-bridge:3.27.1
    pull_policy: never
    platform: linux/amd64
    user: "10001:10001"
    restart: unless-stopped
    volumes:
      - bridge-data:/data
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=32m

  connector:
    image: mailpush-connector:0.3.0a1
    pull_policy: never
    user: "10001:10001"
    restart: unless-stopped
    depends_on: [bridge]
    network_mode: service:bridge
    volumes:
      - type: bind
        source: /mnt/tank/apps/mailpush/connector/deploy/config
        target: /config
        read_only: true
      - connector-data:/data
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=16m
    stop_grace_period: 60s

volumes:
  bridge-data:
    external: true
    name: mailpush-bridge-data
  connector-data:
    external: true
    name: mailpush-connector-data
```

There are no published IMAP/SMTP ports and no Docker socket mount. The connector
shares Bridge's network namespace, so `127.0.0.1` reaches Bridge. A normal private
Docker network with `host = "127.0.0.1"` would reach the connector itself instead.

## 6. Check once against the actual Apps containers

In your TrueNAS shell, define this discovery function. It requires exactly one
Bridge and one connector in the Apps project, avoiding stale container names:

```sh
mailpush_find_containers() {
  MAILPUSH_CONNECTOR=$(sudo docker ps -aq \
    --filter label=com.docker.compose.project=ix-mailpush \
    --filter label=com.docker.compose.service=connector)
  MAILPUSH_BRIDGE=$(sudo docker ps -aq \
    --filter label=com.docker.compose.project=ix-mailpush \
    --filter label=com.docker.compose.service=bridge)
  case "$MAILPUSH_CONNECTOR" in ''|*$'\n'*) printf 'Expected one connector; inspect Apps status.\n'; return 1;; esac
  case "$MAILPUSH_BRIDGE" in ''|*$'\n'*) printf 'Expected one Bridge; inspect Apps status.\n'; return 1;; esac
}
mailpush_find_containers
```

Bridge can start its TLS listener before it has loaded the remote account. A
startup `ConnectionRefusedError` can be brief; repeated `LoginError` needs the
checks below. **Do not repeatedly restart the whole App or hammer login checks.**
Leave Bridge running and pause only the connector:

```sh
mailpush_find_containers && sudo docker stop "$MAILPUSH_CONNECTOR"
```

Allow Bridge to finish loading the account. Inspect recent Bridge logs privately:

```sh
sudo docker logs --since 2m --tail 40 "$MAILPUSH_BRIDGE"
```

Then run one check using the **deployed image, actual mounts and current Bridge
network namespace**. It checks config, TLS and IMAP login; no notification is
sent and no checkpoint is initialized:

```sh
MAILPUSH_IMAGE=$(sudo docker inspect --format '{{.Image}}' "$MAILPUSH_CONNECTOR")
test -n "$MAILPUSH_IMAGE" && sudo docker run --rm --pull=never \
  --user 10001:10001 --network "container:$MAILPUSH_BRIDGE" \
  --volumes-from "$MAILPUSH_CONNECTOR:ro" --read-only \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --entrypoint mailpush "$MAILPUSH_IMAGE" check --config /config/config.toml
```

**Expected:** `mailbox=personal code=imap_ok idle=True`, then
`Configuration and receiver keys valid. No notification was sent.`

If it fails, leave the connector stopped and use the matching
[troubleshooting entry](TROUBLESHOOTING.md). After the check succeeds, send one
encrypted test while the service remains stopped. This command uses the same
mounts but permits writing the test queue in `/data`:

```sh
sudo docker run --rm --pull=never --user 10001:10001 \
  --network "container:$MAILPUSH_BRIDGE" --volumes-from "$MAILPUSH_CONNECTOR" \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --entrypoint mailpush "$MAILPUSH_IMAGE" test --config /config/config.toml --device phone
```

The server reports an encrypted test was queued. Confirm that the **phone**
displays **Encrypted test received**; the server output alone is not a receipt.
If the phone is silent, use [phone troubleshooting](TROUBLESHOOTING.md#connector-accepted-a-test-but-the-phone-is-silent).
After confirming the test, start only the same existing connector:

```sh
sudo docker start "$MAILPUSH_CONNECTOR"
sudo docker logs --since 30s --tail 25 "$MAILPUSH_CONNECTOR"
```

**Expected:** `code=started mailboxes=1 devices=1`, with no recurring IMAP errors.
The first service run baselines existing messages. Send a **fresh email**, leave
it unread and confirm it reaches the phone. An empty queue or healthy container
alone does not prove phone delivery. See the phone guide for the generic encrypted
test alert and optional previews.

After pairing and delivery are confirmed, remove the transfer copies securely
from their temporary locations. Retain config, both persistent volumes and the
private APK signing backup; back them up using your normal protected storage
process. Never publish their contents.

## Everyday commands

These commands are for the Apps manager installation named `mailpush`:

| Task | Command |
| --- | --- |
| List current containers | `sudo docker ps -a --filter label=com.docker.compose.project=ix-mailpush` |
| Connector logs | Run `mailpush_find_containers`, then `sudo docker logs --since 5m --tail 60 "$MAILPUSH_CONNECTOR"` |
| Follow logs | `sudo docker logs --since 30s --follow "$MAILPUSH_CONNECTOR"` (Ctrl+C stops following, not the container) |
| Restart connector after a config edit | Discover current IDs, then `sudo docker restart "$MAILPUSH_CONNECTOR"` |
| Stop the entire App | `sudo midclt call --job app.stop mailpush` |
| Start the entire App | `sudo midclt call --job app.start mailpush` |

Stopping the App can remove its containers; starting it can recreate both
containers. Re-discover IDs afterward. Do not use ordinary `docker compose up`
against the checked-out example to manage an Apps-created deployment: it can
start a separate stack with different volumes.

## Existing installations

Your existing app, config and volume names are authoritative. For an already
working installation, **do not create fresh volumes, repeat Bridge login or
re-pair the phone** just to add previews or install a same-signer APK update.

1. Install the updated signed APK over the existing MailPush fork. Preserve its
   signing identity; do not uninstall first.
2. Find the real config mount, using the discovery function from step 6:

   ```sh
   mailpush_find_containers && sudo docker inspect "$MAILPUSH_CONNECTOR" \
     --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
   ```

3. Edit the host file mounted as `/config/config.toml`. For previews, change
   `preview = true` in the existing `personal` mailbox section.
4. Restart **only the connector**, then enable **Show sender and subject** in
   that phone profile. See [notification previews](NOTIFICATION_PREVIEWS.md).

For a Bridge/container image update, preserve the actual mounted data volumes.
A recreated Bridge has a new network namespace, so its connector must be
recreated to join it. Recheck TLS against the trusted certificate and perform the
warm-Bridge login check above before concluding that credentials are wrong.
