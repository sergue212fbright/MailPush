# MailPush for Proton Mail

An **unofficial Proton Mail Android fork** with end-to-end encrypted
UnifiedPush/ntfy notifications and a lightweight connector for Proton Mail Bridge.
Mail only. No Google push service is required for this notification path.

**Public alpha.** An owner reports working alerts and sender/subject previews on
GrapheneOS through TrueNAS, Bridge and ntfy. The notification module has since
passed **all eleven Android security tests on GitHub, with zero skips**, alongside
connector, release-policy, JVM and interoperability checks. See the
[GitHub validation checkpoint](docs/validation/github-ci.json),
[latest workflow status](https://github.com/sergue212fbright/MailPush/actions) and
[validation limits](VALIDATION.md). The production build, protected-environment
signing and automatic publication have also passed. Upstream checks run every
six hours; compatible changes publish signed alpha APKs after the gates pass.
See the [signed release receipt](docs/validation/github-release.json).
This is not an independent security audit.

**[Download signed APKs and exact corresponding source](https://github.com/sergue212fbright/MailPush/releases).**

## Start here

Choose the guide for **your actual deployment manager**. TrueNAS Apps and a
shell-managed Compose project are different installation paths.

| What you want to do | Guide |
| --- | --- |
| Install using **TrueNAS Apps → Install via YAML** | **[TrueNAS installation](docs/INSTALL_TRUENAS.md)** |
| Install using ordinary **Docker Compose** | **[Docker Compose installation](connector/deploy/DOCKER.md)** |
| Install without Docker, alongside an existing Bridge | [Native installation](connector/deploy/NATIVE.md) |
| Install and pair the **Android app** | **[Android setup](docs/INSTALL_ANDROID.md)** |
| Configure the GitHub-hosted F-Droid feed (setup in progress) | [Custom update repository](docs/F_DROID.md) |
| Update an already working installation | **[Upgrading without resetting setup](docs/UPGRADING.md)** |
| Fix an error or a silent phone | **[Troubleshooting](docs/TROUBLESHOOTING.md)** |
| Enable optional sender/subject previews | [Notification previews](docs/NOTIFICATION_PREVIEWS.md) |
| Configure GitHub builds, signing and failure notices | [Automatic updates](docs/UPDATES.md) |
| Build the Android fork yourself | [Building and testing](docs/BUILDING.md) |

**The Compose file is [`connector/deploy/compose.yaml`](connector/deploy/compose.yaml).**
It is not at the repository root. The guides name the working directory before
commands, explain every mounted path, and include checkpoints before continuing.
If you already receive notifications, follow the upgrade guide instead of
repeating Bridge login, pairing or fresh-volume setup.

## What runs where

| Component | Location | Purpose |
| --- | --- | --- |
| Official Proton Mail Bridge | Your server | Signs into Proton and exposes local IMAP |
| MailPush connector | Server, alongside Bridge | Detects new mail and encrypts a small alert |
| ntfy or another compatible UnifiedPush relay | Public service or your server | Carries ciphertext to the phone |
| UnifiedPush distributor, such as a compatible ntfy Android build | Phone | Maintains the push connection |
| MailPush Proton Mail fork | Phone | Verifies/decrypts alerts and posts its own notifications |

The phone uses **one integrated mail app**, not a separate notification companion.
Android attributes its notifications and permitted launcher dots to this fork.
A precise unread count, chat bubbles, native message actions and clearing alerts
when mail is read elsewhere are not implemented. Tapping opens the bound inbox.

The package is `ch.protonmail.android.mailpush`. It can coexist with official
Proton Mail; its APK does not update the separately signed official application.
It is not published or endorsed by Proton. Bridge requires an eligible Proton plan.

## Privacy choices

The default notification is **Proton Mail — You have new mail**. Sender/subject
previews require both `preview = true` in the mailbox config and **Show sender and
subject** in the phone's paired profile. No body or attachment is fetched for a
preview. Those header fields remain inside the authenticated, padded, end-to-end
encrypted push payload when carried by ntfy.

Enabling previews shares the decrypted details with Android's notification
service and authorized notification listeners, including while Proton's app lock
is enabled. The app supplies a separate generic public notification; Android's
lock-screen/channel settings control what is shown. Turning previews off clears
that profile's existing alerts.

A public relay can still observe IP addresses, endpoints, timing and sizes and can
delay/drop traffic. Bridge and its host have decrypted-mail access. Keep host
storage, credentials, pairing files, state and signing backups private. See the
[threat model](SECURITY.md); this project has not had an independent security audit.

## How the fork stays maintainable

This repository is a GitHub-linked fork of
[Proton Mail Android](https://github.com/ProtonMail/android-mail).

* **`main`** contains our connector, documentation, isolated notification module,
  adapter, small strict patches and release workflow.
* **[`proton-upstream`](https://github.com/sergue212fbright/MailPush/tree/proton-upstream)**
  preserves Proton's original source/history at the starting commit. It is a
  reference branch, not the source of the MailPush installation instructions.
* [`upstream.json`](upstream.json) records the official source pin. Preparation
  checks out an exact official Proton commit into `.work/proton`, applies the
  checked patches and copies our module/adapter. The release's corresponding-source
  archive contains the complete assembled Android app for that APK.

Keeping the maintained code on `main` avoids a second, stale copy of the Android
app. **Do not use “Sync fork” on `main` to update MailPush.** The release workflow
selects official source, builds it with our additions and stops if patches, tests,
manifest policy or signing checks fail. It does not invent unattended AI fixes.

Proton changes can still require maintenance. The workflow tracks publicly
published source, which may lag app-store releases. Read [update setup and
limits](docs/UPDATES.md) before enabling publication.

## Source and contributions

The maintained fork/adapter is GPL-3.0-or-later. Receiver and Python connector MIT
provenance and third-party licenses are retained; see [NOTICE.md](NOTICE.md).
APKs must be distributed with their applicable corresponding source.

Keep pull requests focused. Changes to cryptography, account binding, patches,
workflow permissions and signing code need deliberate review. Never put real
mail, passwords, subscription bundles, pairing keys or signing material in an
issue or commit. See [CONTRIBUTING.md](CONTRIBUTING.md).
