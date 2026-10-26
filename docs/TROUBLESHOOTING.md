# Troubleshooting MailPush

Start with the **first failing checkpoint**, not a reset of the whole stack.
Keep the phone pairing, both persistent volumes and your config. These steps
never require posting your passwords, pairing key, subscription JSON or decrypted
mail to an issue or chat.

Choose the commands for your deployment:

| Your deployment | Start here |
| --- | --- |
| TrueNAS Apps manager | [TrueNAS guide](INSTALL_TRUENAS.md), including its container-discovery function |
| Ordinary Docker Compose | [Compose guide](../connector/deploy/DOCKER.md); run commands in `connector/deploy` |
| Native Python service | [Native guide](../connector/deploy/NATIVE.md); use its service user and config path |

## Quick symptom map

| Symptom | Most useful next check |
| --- | --- |
| `PermissionError` while loading config | Actual bind mount, UID10001, directory traversal and secret modes |
| `FileNotFoundError` while loading config | Mounted `config.toml`, password path and whether pairing has created the subscription |
| `Secret files must not be group-writable...` | Actual **file mode**, including new files created under a TrueNAS ACL |
| `docker: invalid reference format` | Image argument/variable is empty or malformed |
| `Pairing failed: wrong key, damaged file, or expired request` | Fresh matching phone request/key and clock; do not guess repeatedly |
| `imap_ConnectionRefusedError` | Bridge running/listening, correct port, shared network namespace |
| Self-signed certificate / TLS handshake error | Correct TLS mode and trusted Bridge certificate pin/CA |
| `imap_LoginError`, `no such user` | Warm Bridge, exact Bridge IMAP credentials and the **same Bridge volume** |
| `too many login attempts` | Pause connector retries, then do one controlled check |
| `No such container` after stopping Apps | TrueNAS removed/recreated containers; start through Apps and discover current IDs |
| Connector runs but phone is silent | Complete receipt import, distributor registration, permissions and a fresh unread message |
| Subject/sender absent | Both preview switches and updated APK; synthetic tests remain generic |

## Collect the right container IDs

For a TrueNAS application named **`mailpush`**, paste the discovery function from
[TrueNAS setup, step 6](INSTALL_TRUENAS.md#6-check-once-against-the-actual-apps-containers).
Then run:

```sh
mailpush_find_containers
sudo docker inspect "$MAILPUSH_CONNECTOR" \
  --format 'user={{.Config.User}} network={{.HostConfig.NetworkMode}}{{println}}{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
sudo docker inspect "$MAILPUSH_BRIDGE" \
  --format 'status={{.State.Status}}{{println}}{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
sudo docker logs --since 5m --tail 40 "$MAILPUSH_CONNECTOR"
```

The connector should run as `10001:10001` and share the **current** Bridge
container's network namespace. Find the host directory mounted at `/config`.
Edit that directory's `config.toml`; a different file elsewhere in the repository
will not change the running App.

Container IDs are temporary. Re-run discovery after changing/stopping/starting
an App. If the App is stopped and the containers no longer exist:

```sh
sudo midclt call --job app.start mailpush
```

Wait for the job, then discover again. Do not substitute `docker start` with a
previously deleted name. Starting the entire App can recreate Bridge too; allow
its account to load before testing credentials.

## Permissions and ACLs

### What the connector requires

Secret files must be `0600` or `0640`. They must also be readable by the actual
container user. For this image, it is **UID/GID10001**, not the TrueNAS host's
`apps:apps` UID/GID568. Parent directories need traversal permission.

For the standard host password/config layout, run in `connector/deploy`:

```sh
sudo chown root:10001 config config/secrets
sudo chmod 750 config config/secrets
sudo chown root:10001 config/config.toml config/secrets/bridge-password
sudo chmod 640 config/config.toml config/secrets/bridge-password
sudo stat -c '%a %u:%g %n' config config/secrets config/config.toml config/secrets/bridge-password
```

Do not run broad recursive `chown`/`chmod` commands on the source repository,
whole pool, existing application volumes or unrelated data. Do not disable the
secret-permission check or make files world-readable.

A TrueNAS dataset ACL may force **newly created files** to `0770`, even when the
program requested `0600`. A password showing `0640` does not prove that a new
pairing subscription will have the same mode. The documented fresh setup stores
the generated receiver bundle at **`/data/phone-subscription.json`** in the
connector's Docker volume to avoid that host-file creation trap.

If host permission changes do not stick, review the ACL on the dedicated config
location using your TrueNAS administration process. Use a suitable private
runtime location and allow the container identity access while retaining the
required file modes. Do not strip ACLs from a dataset containing unrelated files.

### Inspect file metadata without printing secrets

For a running TrueNAS connector, this prints only existence, modes, ownership and
readability. It also creates and removes one empty permissions probe in `/data`;
it does not inspect message contents or alter state/checkpoints:

```sh
mailpush_find_containers && sudo docker exec -i "$MAILPUSH_CONNECTOR" python - <<'PY'
from pathlib import Path
import os, stat, tomllib
config_path = Path('/config/config.toml')
print('runtime uid:gid=', f'{os.getuid()}:{os.getgid()}')
def inspect(label, path):
    try:
        s = path.stat()
    except FileNotFoundError:
        print(label, 'MISSING', str(path))
        return
    except OSError as error:
        print(label, type(error).__name__)
        return
    mode = stat.S_IMODE(s.st_mode)
    print(label, str(path), f'mode={mode:04o}', f'owner={s.st_uid}:{s.st_gid}',
          f'regular_file={stat.S_ISREG(s.st_mode)}', f'readable={os.access(path, os.R_OK)}',
          'secret_mode_OK=' + str(not bool(mode & 0o027)))
inspect('config', config_path)
try:
    raw = tomllib.loads(config_path.read_text())
    for section, field in [('mailboxes', 'password_file'), ('devices', 'subscription_file')]:
        for item in raw.get(section, []):
            value = item.get(field)
            if value:
                path = Path(value)
                inspect(field, path if path.is_absolute() else config_path.parent / path)
except Exception as error:
    print('config parsing:', type(error).__name__)
probe = Path('/data/.mailpush-permissions-probe')
fd = None
try:
    fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    print('NEW /data FILE mode=', f'{stat.S_IMODE(os.fstat(fd).st_mode):04o}')
except Exception as error:
    print('new-file probe:', type(error).__name__)
finally:
    if fd is not None:
        os.close(fd)
        probe.unlink()
PY
```

If the service is stopped or continually restarting, do not keep racing
`docker exec`. Use the one-off deployed-image/mount procedure in the TrueNAS guide
or inspect host metadata with `stat`; never print the file contents.

## Missing config, password or receiver file

1. Inspect the running mount list above. The directory mounted to `/config`
   must contain `config.toml` directly. Mounting the repository's root `config`
   instead of **`connector/deploy/config`** is a common mistake.
2. A relative `password_file = "secrets/bridge-password"` resolves relative to
   the config file, so inside the container it means
   `/config/secrets/bridge-password`.
3. A fresh `subscription_file = "/data/phone-subscription.json"` is created by
   `mailpush pair`. `mailpush check`/`run` cannot succeed before it exists.
4. Do not create empty placeholder JSON or paste a push endpoint manually.
   Pairing establishes the cryptographic binding and returns a receipt for the
   phone to import.

For an existing pairing, keep the original subscription file and connector
state. If migrating its path, back up and privately move that exact bundle with
the correct UID/mode before editing `subscription_file`. Changing the path alone
does not move the file or create a new pairing.

## Invalid image reference

`docker: invalid reference format` happens before MailPush runs. In particular,
an empty `"$MAILPUSH_IMAGE"` is not an image name. Do not reuse a variable from an
old SSH session or copy a command without the preceding assignment.

For the existing Apps connector:

```sh
mailpush_find_containers && \
MAILPUSH_IMAGE=$(sudo docker inspect --format '{{.Image}}' "$MAILPUSH_CONNECTOR") && \
test -n "$MAILPUSH_IMAGE" && \
sudo docker image inspect "$MAILPUSH_IMAGE" --format '{{.Id}}'
```

The output should be a `sha256:...` image ID. Fresh setup uses the explicit local
tag `mailpush-connector:0.3.0a1` after building it; do not invent a registry URL.

## Pairing errors

| Error/stage | Action |
| --- | --- |
| Subscription file missing before pairing | Expected on first setup. Run `pair`, not `check`/`run`, after preparing the config/password. |
| Subscription or receipt already exists | Back it up; use `--replace` only for an intentional re-pair with the matching fresh phone request. |
| Wrong key / damaged file / expired request | Export a new request, copy it without modification, and use its newly shown one-time key. Check server/phone clocks. |
| Fingerprint differs | Stop. Do not activate the pairing; confirm the files/profile/key came from the intended phone and connector. |
| Connector says imported but phone remains pending | Copy **the encrypted `.receipt`** back and import it into the same phone profile. The request alone is not activation. |
| Mode error after entering the right key | Inspect the newly created target's mode and its parent ACL. Use the documented `/data` receiver location; a key retry will not fix an ACL. |

The one-time key belongs at the connector's hidden prompt. Do not pass it as a
shell argument, place it in shell history or send it with an issue report. Requests
and receipts expire after one day. Delete temporary transfer copies after success,
not the installed private receiver bundle.

## Connection refused or repeated IMAP errors

Confirm Bridge is running, the configured port is its actual IMAP port, and the
connector shares the current Bridge namespace. `depends_on` orders container
startup; it does not prove Bridge's account is ready.

A recreated Bridge container has a new namespace. The connector must be recreated
against that new Bridge by its deployment manager. Merely restarting a connector
whose namespace points to a deleted Bridge can leave the wrong network binding.

Do not expose IMAP to the Internet or switch to plaintext to bypass this problem.

## TLS certificate errors and Bridge `bad record MAC`

A Bridge log such as `Cannot upgrade connection ... tls: bad record MAC` does not
by itself prove a cipher or server bug. In the observed setup, the corresponding
client error was a rejected self-signed certificate.

1. Match `tls = "starttls"` to Bridge STARTTLS, or `tls = "tls"` to its implicit
   TLS/SSL mode and port. They are not interchangeable.
2. Export the certificate from **your own active Bridge volume**, as described in
   the installation guide, and compare its SHA-256 fingerprint.
3. Configure that verified value as `tls_pin_sha256`, or use the exported public
   certificate as `ca_file`. Choose one verification method.
4. Run one controlled `mailpush check` before resuming the service.

`mailpush certificate` only **observes** what a server presented. An observation
without comparison to a trusted copy is not sufficient evidence of identity.
Never use `CERT_NONE`, disable verification in production, accept an unexplained
changed fingerprint, or distribute Bridge's exported private `key.pem`.

## LoginError: wrong credentials, `no such user`, or startup timing

Three separate mistakes can look like a login problem:

* The config uses the normal Proton password instead of Bridge's generated IMAP
  password, or an IMAP username/address different from Bridge's `info` output.
* Initial login used one Bridge volume, while Apps started another empty volume.
* The correct Bridge has opened its listener but has not finished loading its
  account yet. TLS readiness is not account readiness.

Pause only the connector. Leave Bridge running and use the **one-off check
against its actual current namespace** in the TrueNAS guide. Check once after the
account is loaded. If the response is still a login failure, use the private
redacted diagnostic below. Do not run a fast retry loop.

This one-off diagnostic pauses the connector, uses the deployed image/mounts,
and reveals the server's error while replacing its configured username/password
with `[redacted]`. Run in Bash after defining the discovery function:

```sh
mailpush_find_containers &&
MAILPUSH_IMAGE=$(sudo docker inspect --format '{{.Image}}' "$MAILPUSH_CONNECTOR") &&
sudo docker stop "$MAILPUSH_CONNECTOR" >/dev/null &&
sudo docker run --rm -i --pull=never --user 10001:10001 \
  --network "container:$MAILPUSH_BRIDGE" --volumes-from "$MAILPUSH_CONNECTOR:ro" \
  --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --entrypoint python "$MAILPUSH_IMAGE" - <<'PY'
from mailpush.config import load
from mailpush.monitor import connect
box = next(b for b in load('/config/config.toml').mailboxes if b.id == 'personal')
try:
    client = connect(box)
except Exception as error:
    message = str(error)
    for value in sorted((box.password, box.username), key=len, reverse=True):
        if value:
            message = message.replace(value, '[redacted]')
    print(type(error).__name__ + ': ' + message)
else:
    print('IMAP login OK')
    client.shutdown()
PY
```

The connector remains stopped. Start the existing connector only after the
controlled check succeeds: `sudo docker start "$MAILPUSH_CONNECTOR"`.

If the server says **`too many login attempts`**, stop connector retries first.
Allow Bridge to recover and make one check with confirmed credentials. Do not
keep entering the normal Proton password or recreate/clear Bridge to reset the
counter. The correct retry behavior depends on the Bridge version; no fixed
cooldown duration is promised here.

### Re-enter the actual Apps Bridge CLI

If you must inspect `list`/`info` again, use the deployed Bridge image and volume,
with both services stopped individually. The following applies to the supplied
wrapper, whose runtime paths are configured by the image:

```sh
mailpush_find_containers && \
MAILPUSH_BRIDGE_IMAGE=$(sudo docker inspect --format '{{.Image}}' "$MAILPUSH_BRIDGE") && \
sudo docker stop "$MAILPUSH_CONNECTOR" "$MAILPUSH_BRIDGE" && \
sudo docker run --rm -it --pull=never --user 10001:10001 \
  --volumes-from "$MAILPUSH_BRIDGE" --cap-drop ALL --security-opt no-new-privileges:true \
  "$MAILPUSH_BRIDGE_IMAGE" --cli
```

Use `list` and the correct `info` index. Enter `exit`. Then start the existing
Bridge with `sudo docker start "$MAILPUSH_BRIDGE"`, allow its account to load,
perform one check, and start only the existing connector after the check succeeds.
Do not run the CLI simultaneously with the background Bridge on the same volume.
For another Bridge image or custom runtime path overrides, follow that image's
own instructions rather than assuming this wrapper's `/data` layout.

A warning about `dbus-launch`/SecretService can coexist with a working `pass`
keychain fallback. Use successful account loading and the controlled IMAP check
to assess it. Do not install random host packages or remove the keychain merely
to silence the warning.

## Connector accepted a test but the phone is silent

`mailpush test` says the encrypted event was queued; that is not a phone delivery
receipt. A push provider accepting HTTP likewise does not prove the app displayed
an alert.

Check this order:

1. ntfy/distributor has an active UnifiedPush registration and network access.
2. MailPush's profile completed the **receipt import** and shows paired status.
3. The phone profile is bound to the intended signed-in Proton account and local
   mailbox ID `personal` matches the server.
4. Android permits notifications for the MailPush fork/channel. Inspect any
   restrictions placed on either the distributor or the mail fork.
5. Run one encrypted test while the connector service is paused, as described in
   the deployment guide, then resume it.
6. Send a **new** email and leave it unread. Initial startup baselines old mail;
   already processed/seen mail may correctly produce no alert.

For temporary debugging, keep changes limited to the affected app/distributor;
do not disable device-wide security settings. See [Android setup](INSTALL_ANDROID.md).

## Previews still show “You have new mail”

All of these must be true:

* You installed the preview-capable MailPush APK over the existing fork.
* The **actual mounted config** has `preview = true` in the relevant mailbox.
* You restarted **only the connector** after editing that file.
* The matching phone profile has **Show sender and subject** enabled.
* You tested a new mail event with useful sender/subject headers.

Synthetic test alerts remain generic. Turning either preview switch off restores
generic mail alerts. Android lock-screen settings control what opted-in details
are displayed; app-lock does not erase details already shared with Android's
notification system and authorized listeners. No body snippet, mark-read/archive
actions or direct per-message navigation are implemented.

## What to include in a support issue

Include deployment type, TrueNAS version, CPU architecture, image version/digest,
APK versionCode, error **code**, the stage that failed, and whether a controlled
IMAP check succeeded. Metadata-only permissions/mount diagnostics are useful after
redacting host paths if desired.

Do **not** attach config/password contents, pairing keys, subscription bundles,
Bridge private volumes, signing backups, public capability URLs, decrypted mail,
or unredacted Bridge logs. Review every log excerpt before posting; Bridge logs
can include account identifiers even though the connector intentionally logs
minimal error codes.
