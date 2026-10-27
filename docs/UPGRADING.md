# Update a working installation

If notifications already work, start here. A GitHub repository being created does
not require moving your runtime configuration, replacing volumes or pairing again.

## Update the phone APK

1. Obtain the newer signed APK from the project's release channel.
2. Verify that it is for `ch.protonmail.android.mailpush`, has a higher
   versionCode, and uses the same signing certificate as your installed fork.
   The supplied alpha.1/alpha.2 certificate is recorded in [validation](../VALIDATION.md).
3. Install **over** the current fork. Keep its app data; do not uninstall first.
4. Open the app, confirm the account/profile remains present, and send a fresh
   unread message to test delivery.

An incompatible-signature error needs investigation, not a reset. Only the same
release identity can update the installed APK in place. Preserve the private
signing backup if you maintain your own releases.

## Enable sender and subject

The original alpha.1 APK always displayed a generic alert. A preview-capable APK
needs both opt-ins:

1. Edit the **actual host file mounted as `/config/config.toml`**. In the existing
   mailbox section, set `preview = true`.
2. Restart only the connector so it reloads the configuration.
3. On the phone, open **Settings → App customization → Encrypted push**, find the
   paired profile and enable **Show sender and subject**.
4. Send a new unread email. Synthetic test alerts stay generic.

For a TrueNAS Apps installation named `mailpush`, discover its current connector
before restarting it:

```sh
MAILPUSH_CONNECTOR=$(sudo docker ps -q \
  --filter label=com.docker.compose.project=ix-mailpush \
  --filter label=com.docker.compose.service=connector)
case "$MAILPUSH_CONNECTOR" in
  ''|*$'\n'*) printf 'Expected one running connector; check Apps status.\n';;
  *) sudo docker restart "$MAILPUSH_CONNECTOR";;
esac
```

For an ordinary Compose deployment, run `docker compose restart connector` from
that same project's `connector/deploy` directory. See
[privacy choices](NOTIFICATION_PREVIEWS.md) before enabling previews.

## Keep the existing server configuration authoritative

The running containers determine your real mount paths, image IDs and volume
names. In an existing TrueNAS Apps deployment these may be
`ix-mailpush_bridge-data` and `ix-mailpush_connector-data`; fresh-install examples
use different explicitly named volumes. Do not substitute the examples for
working storage.

Before a planned server-image update, retain a protected backup of:

* The real connector config and Bridge-generated password file.
* The Bridge data volume, including its account, certificate and local keychain.
* The connector data volume, including subscription, queue and checkpoints.
* The APK signing backup, kept separately and privately.

An extracted source ZIP is not necessarily a Git checkout. Do not run `git init`,
clone over it, remove its directory, or reset it to get the new documentation:
your runtime config may be inside that directory. You can browse the new guides
on GitHub or clone into a **different** directory first.

The connector and Bridge can update separately from the Android fork. Use your
actual deployment manager and preserved storage. Recreating Bridge also changes
its network namespace, so recreate the associated connector to join it. Wait for
Bridge's account to load, verify TLS against the trusted certificate, and perform
one controlled login check. The [TrueNAS guide](INSTALL_TRUENAS.md#existing-installations)
and [troubleshooting guide](TROUBLESHOOTING.md) provide those commands.

`docker compose down -v`, replacing a volume, or uninstalling the phone app can
remove essential state. These are not normal update steps.
