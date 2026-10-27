# Android setup: install, pair and test

Use this page for the **phone**. Use [TrueNAS setup](INSTALL_TRUENAS.md),
[Docker Compose](../connector/deploy/DOCKER.md), or
[native installation](../connector/deploy/NATIVE.md) for the server.

MailPush is an unofficial Proton Mail Android fork. It is one mail application
with an embedded notification module, plus a separate server connector. You do
not install a second MailPush notification companion on the phone.

## Already paired? Updating is much shorter

1. Install the newer signed MailPush APK **over the existing fork**. Keep the
   existing installation and its app data. An in-place update needs the same
   signing certificate and a higher versionCode.
2. Open the fork and confirm your account and encrypted-push profile are still
   present. In **Encrypted push**, an existing account should still show
   **Paired**. Normal in-place updates preserve this setup; leave **Pair again**
   and the export/import steps alone unless you are replacing a pairing.
3. To enable sender/subject previews, follow [Enable previews](#enable-previews).
   Existing paired installations do not need another pairing just for previews.
4. Send a **new email**, leave it unread, and check the notification.

If Android rejects the update as incompatible, stop and verify the APK's signing
identity. Uninstalling clears app data and can require account setup and pairing
again; it is not the normal update procedure.

## Before the first installation

Have these ready:

| Item | Where it belongs |
| --- | --- |
| Consistently signed MailPush APK | Phone |
| UnifiedPush-capable distributor, such as the Google-free ntfy app | Phone |
| Preferred HTTPS UnifiedPush service | Configured in the distributor |
| Configured Bridge and connector image/installation, ready for pairing | Server |
| Bridge-generated IMAP credentials | Connector's private server configuration |

The distributor maintains the phone's push connection. The ntfy **server alone**
is not the Android distributor. Our notification module asks the distributor for
a delivery endpoint; that endpoint is paired with the connector below.

The Proton account is signed into **inside the mail app**. The phone pairing UI
does not ask you to paste a Proton password, Bridge password, server private key,
or connector subscription file into it.

## 1. Install the signed mail APK

Open this project's [releases](https://github.com/sergue212fbright/MailPush/releases)
and download **`MailPush.apk`** from the newest automated build's Assets. The
initial manual alpha instead uses a filename beginning `MailPush-ProtonMail-`.
Check that release's `SHA256SUMS`, signature information and
[validation notes](../VALIDATION.md). A source-code ZIP or `source.tar.gz` is
source for rebuilding, not an installable APK. Maintainers may use their own
consistently signed build instead.

The application ID is `ch.protonmail.android.mailpush`. It can coexist with
official Proton Mail, but updates for this fork must use this fork's signing
identity. They do not update the official Proton APK.

Install the APK through Android's package installer and sign into your Proton
account normally. Keep the official app available while you test the fork.

## 2. Prepare the distributor

Install and open a UnifiedPush-capable distributor. Configure its HTTPS public
or self-hosted server and confirm that the distributor is connected before
returning to the mail app.

If the mail app later says **Install a UnifiedPush distributor**, the installed
build is not being detected as a distributor. Check that application's build
and UnifiedPush support. A push-server URL or a manually subscribed ntfy topic
does not replace this registration step.

Keep the distributor permitted to run in the background. If Android reports
that it is restricted, review its app battery/background settings and its own
instructions. Menu names vary by Android/GrapheneOS version. Do not disable
system security protections or grant unrelated permissions to solve delivery.

## 3. Open encrypted-push settings

Inside the **fork's** Proton Mail settings, open:

**Settings → App customization → Encrypted push**

Unlock through Proton Mail's normal app authorization if requested. Then:

1. Tap **Choose push service** and select your distributor. If one is already
   selected, its name is shown with **Change push service**. Changing it can
   change delivery endpoints and require pairing again.
2. If shown, tap **Allow notifications** and grant Android's notification
   permission. Also check the mail fork's notification/channel settings if
   notifications were previously disabled.
3. Tap **Add email account**.

If asked to sign in first, sign into Proton Mail in the fork and return to this
screen. A paired account's card shows its status and preview choice; setup and
repair controls do not need to be repeated each time you open settings.

## 4. Bind the correct account and mailbox ID

In **Add email account**:

1. Select the signed-in account that should open when you tap an alert.
2. For a first single-account setup, keep **Connector mailbox IDs** as `personal`.
3. Leave **Advanced options** closed for an ordinary ntfy setup. The optional
   provider VAPID public key belongs there; enter one only if your chosen provider
   explicitly requires it and its corresponding sender identity is configured.
4. Tap **Continue**.

`personal` is a local name. It must match `id = "personal"` in the connector's
mailbox section; it is not your email address. The connector device ID `phone`
is another local name used by server commands.

Account binding stays on this phone. Check the selected account yourself:
matching local mailbox names cannot prove that the server's Bridge mailbox is
the same Proton account you selected.

The account starts with **Setup needed**. Wait for **1. Save your pairing
request** and its **Save pairing request** button. If it is still waiting for the
push service, open the distributor and check its connection, then use **Retry
registration** or **Refresh status**. Repeatedly exporting files will not repair
push registration.

## 5. Export one encrypted request

In that account's card:

1. Tap **Save pairing request** under **1. Save your pairing request**.
2. Save the `.mailpush` file using Android's document picker. Its generated name
   starts with `mailpush-`; on the server you may rename it `phone.mailpush`.
3. After export, the app displays a **one-time pairing key** and a fingerprint.
   You can reopen them with **Show one-time key** while the request is pending.
4. Transfer the encrypted `.mailpush` file to the server's `pairing` directory.
5. Enter the one-time key only into the connector's hidden pairing prompt. Keep
   that key separate from the transferred file.

Do not put the key in a shell command, repository, issue, log, or chat. The
encrypted settings screen intentionally blocks screenshots. The request/key
pair expires after one day. **Create a new request** saves a new request/key
pair; use the matching newest file and key together.

Now follow the **pair** step in your server installation guide. Keep this phone
profile: it is where the returned receipt must be imported.

## 6. Compare the fingerprint and import the receipt

The server pairing command should print:

```text
Pairing imported. Compare fingerprint with phone: ...
Import the encrypted .receipt file into the phone, then restart the connector.
```

Compare its fingerprint with the fingerprint shown by **Show one-time key** on
the phone. If they do not match, stop and resolve the mismatch. Do not activate
an unexpected pairing.

Transfer the server's encrypted `.receipt` file back to the phone. Return to the
**same account card**, tap **Import connector receipt** under **2. Finish
pairing**, and choose that file.

The phone verifies the receipt using the pending pairing key. Importing the
original `.mailpush` request here is the wrong direction.

Expected result:

```text
Pairing complete. Send an encrypted test from the connector to check delivery.
```

The account now shows **Paired**. This confirms the receipt was accepted; it is
not a live connection or delivery check. A successful server import alone is only
half the pairing; this phone receipt import is required too.

## 7. Verify delivery in two stages

Follow the server guide to run its **check**, then **test** command, with the
connector service paused where that guide requires it.

1. **Connection check:** `mailpush check` confirms configuration, receiver keys
   and an authenticated read-only IMAP connection. It deliberately sends no
   notification.
2. **Encrypted test:** `mailpush test` queues an encrypted alert. Confirm the
   phone displays **Encrypted test received**. Push-server acceptance or a
   server heartbeat alone is not proof that the phone received it.

Start/resume the normal connector, send a **fresh email**, and leave it unread.
The first service run baselines existing messages; old mail does not become a
batch of new notifications. Generic mail alerts say **You have new mail**.

The account's **Last alert** provides local evidence of receipt. Its detailed
registration status is under **Account options**. Tapping an alert opens the
bound account's inbox.
Exact unread counts, message-specific navigation, mark-read/archive buttons and
clearing alerts when mail is read elsewhere are not implemented.

After initial success, separately test your own screen-off, reboot, app-lock and
network-change behavior. See [troubleshooting](TROUBLESHOOTING.md) if delivery
stops; avoid deleting the profile as the first diagnostic step.

## Enable previews

Both of these settings are required:

1. **Server:** set `preview = true` in the existing connector mailbox section,
   then restart only the connector so it reloads the configuration.
2. **Phone:** in the paired account's card, enable **Show sender and subject**.
   **About notification previews** explains the server requirement and what
   becomes visible to Android.

Send another fresh unread email. Synthetic test alerts stay generic even when
previews are on. The notification can display sender, subject and the local
account label; it does not fetch a mail body or attachment for a preview.

These fields remain inside the encrypted push payload while relayed through
ntfy. Once displayed, decrypted details are available to Android's notification
system and authorized notification listeners, including while Proton Mail's
own app lock is enabled. Android's lock-screen and channel privacy settings
control display. Turning previews off clears that profile's current alerts.
Read [preview privacy and configuration](NOTIFICATION_PREVIEWS.md) before opting
in.

## Re-pairing and removal

A routine same-certificate APK update does not require re-pairing. Clearing app
data, uninstalling, removing a profile or changing the push endpoint can require
a fresh pairing. An **Endpoint changed: export pairing again** status means the
old subscription is no longer the right one.

Open **Account options** on the relevant account card to see connector mailbox
IDs, detailed registration status and these maintenance actions:

| Action | When to use it |
| --- | --- |
| **Reconnect push service** | Retry the current distributor registration after checking that the distributor is running. It is not a delivery test. |
| **Pair again** | Deliberately replace an existing pairing. A confirmation precedes creating a fresh request; finish the server replacement and phone receipt steps together. |
| **Remove alert setup** | Stop using this phone's alert pairing for that account. This deletes its local pairing and notification keys; the email account remains signed in. |

When replacing a registration, use a fresh phone request and matching key, then
follow the server guide's explicit `--replace` procedure and import the new
receipt. Removing a profile deletes its local pairing/notification keys. Revoke
the device on the connector as well when it should no longer receive alerts.

The push screen follows Android's system light/dark appearance. Its styling is
owned by the push module, so Proton Mail's separate app-only appearance override
does not control this screen.

## Current validation scope

The owner reported working generic alerts and sender/subject previews on
GrapheneOS through TrueNAS, Bridge and ntfy. Those are functional observations,
not an independent security audit. Initial local software-emulator failures
remain in the historical receipts. Later, GitHub's accelerated API 35 emulator
passed its then-current 11 Android device checks with zero skips. The
[GitHub checkpoint](validation/github-ci.json) records that successful fixture
run separately from the full production build and automatic signing/release
setup. The [validation record](../VALIDATION.md) explains each result's scope.
