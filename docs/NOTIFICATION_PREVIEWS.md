# Sender and subject previews

The original 0.3.0-alpha.1 APK always displays **Proton Mail — You have new mail**.
The preview-capable update keeps that default and adds a separate phone opt-in.
The existing connector already supports the necessary encrypted header fields;
no connector or Bridge image rebuild is required.

## Enable previews

1. Install the preview-capable APK over the existing fork. It must have the same
   application ID and signing certificate and a higher Android versionCode.
   Keeping the existing installation preserves the local account and pairing.
2. On the server, edit the running connector's `config.toml`. In the existing
   `[[mailboxes]]` section for the desired mailbox, set:

   ```toml
   preview = true
   ```

3. Restart only the connector so it reloads that file. For the existing TrueNAS
   Apps installation named `mailpush`:

   ```sh
   sudo docker restart ix-mailpush-connector-1
   ```

   For a normal Compose deployment, run `docker compose restart connector` from
   that same Compose project. Bridge can keep running; its account loading need
   not restart with this configuration change.
4. On the phone, open **Settings → App customization → Encrypted push**, find
   the paired account's card and enable **Show sender and subject**. Tap **About
   notification previews** for the privacy explanation. The setup screen requires
   the host's normal authorization. No new pairing is needed for this preference;
   **Pair again** under **Account options** is a separate repair action.
5. Send a new email and leave it unread while testing. Previously processed
   events and synthetic test alerts do not become email previews.

The notification shows the sender, subject and local profile label when those
fields are available. Tapping it opens the bound account's inbox. Body snippets,
message-specific navigation, mark-read and archive actions are not implemented.

## Privacy choices

Both server and phone opt-ins are needed. Leaving either off preserves generic
alerts. Only From/Subject headers are fetched for previews; the connector does not
fetch a body or attachment. Sender/subject remain inside the authenticated,
end-to-end encrypted, padded notification payload when relayed through ntfy.

Once displayed, those decrypted fields are available to Android's notification
system and authorized notification listeners, including when Proton Mail's app
lock is enabled. The application supplies a separate generic public notification
and requests private visibility. Android's lock-screen and channel settings
determine what the lock screen displays; configure them for the privacy you want.
Turning the phone's preview toggle off clears that profile's existing alerts.

The transport, recipient keys, account binding, replay checks, encrypted job
storage and Proton integration entry points are unchanged by this feature.
