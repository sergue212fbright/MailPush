# MailPush updates through a custom F-Droid repository

This is a **MailPush-maintained repository hosted on GitHub Pages**, for use with
an F-Droid-compatible Android client. It is separate from the official
`f-droid.org` catalog: inclusion here does not mean F-Droid builds, reviews or
endorses this application. MailPush remains an unofficial Proton Mail fork and
**public alpha software**.

**Setup in progress:** the address below is proposed, not yet verified live.
The repository signing identity is pinned below, but the first deployed index
and its QR/link still need verification before following the phone steps.
Until then, use the signed APKs on
[GitHub Releases](https://github.com/sergue212fbright/MailPush/releases) and the
[Android installation guide](INSTALL_ANDROID.md).

## Already using MailPush?

You can normally switch from downloading our APK manually to receiving it
through this repository **without uninstalling or pairing again**. The feed must
distribute the same application, signed with the same existing APK certificate:

| Check | Expected value |
| --- | --- |
| Android application ID | `ch.protonmail.android.mailpush` |
| APK signing certificate SHA-256 | `bf65bf147b85f377575579d8569cfa6dda715d309ec0aabdfd7b42800f52e79e` |
| Update versionCode | Higher than the installed versionCode |

An in-place update normally keeps the account, paired encrypted-push profiles
and notification settings. This does not update the separately signed official
Proton Mail app. **Do not uninstall MailPush to resolve an update error:** that
clears its app data and can require signing in and pairing again.

## 1. Add the repository on the phone

First install an F-Droid-compatible client from a source you trust. Exact menu
names vary between clients; the usual route in F-Droid is **Settings →
Repositories → Add**.

The address will be confirmed after the first signed repository is deployed.
The repository fingerprint is already pinned in the project's public policy:

```text
Proposed repository URL — NOT YET VERIFIED:
https://sergue212fbright.github.io/MailPush/fdroid/repo

Repository signing certificate SHA-256:
e3b363f72b7048233f0f6dd8f7848e7e1b192a3b40c802ccb4ebbc3875c64176
```

1. Open the verified repository link on the phone, or paste the complete HTTPS
   URL into the client's **Add repository** screen.
2. Check the **repository signing fingerprint** against the fingerprint published
   on this page. It authenticates the repository index, not the APK. Stop if it
   differs or the repository is still marked as awaiting deployment verification.
3. Confirm and enable the repository, then refresh its contents.
4. Find **MailPush** and confirm the application ID above before installing.

**QR alternative:** once published, scan the repository's QR code from another
screen and open it with your F-Droid client. It must encode the verified HTTPS
repository URL with its fingerprint. Review the imported address and fingerprint
before enabling it. The live QR code has not yet been verified; a QR scanner is
not needed for the manual route.

Adding the repository does not install the mail app or change its server
configuration. You do not enter a Proton password, Bridge password, ntfy endpoint,
subscription file or pairing key into the F-Droid client.

## 2. Install or update MailPush

Select the MailPush entry from this repository and choose **Install** or
**Update**. Android may ask you to allow this F-Droid client to install apps.
Grant that permission to the installer you chose, then approve the installation
when Android asks. This is a permission for the installer, not the mail app.

For a first installation, continue with the
[Android setup and pairing guide](INSTALL_ANDROID.md#2-prepare-the-distributor).
You still need a UnifiedPush distributor and a configured Bridge connector.

For an existing installation, open MailPush after the update and check that its
account and encrypted-push profile are present. Send a fresh email, leave it
unread, and confirm a notification. The connector and Bridge do not need to be
reinstalled or re-paired just because the APK was updated.

## 3. Choose how updates are installed

Enable repository refresh and update notifications in your chosen client. If
you want automatic installation, enable that client's automatic-update setting
and follow its Android permission prompts. **A published APK is not proof that
the phone installed it:** client settings, Android rules and user approval can
still require an installation tap, especially the first time this installer
updates an app installed manually.

MailPush releases are currently **alphas/prereleases**. Using this repository is
an explicit choice to receive those alpha updates. If your client hides unstable
or prerelease versions, review that setting for MailPush. A GitHub prerelease
label alone is not a promise about how every F-Droid-compatible client labels
the same version.

The repository is intended to publish the already signed GitHub release APK,
without changing its application ID or signing certificate. The normal build,
device-test and release gates still apply. Failed upstream builds can delay a
new release; a repository refresh does not repair a failed build or update Bridge
and the connector. See [update behavior](UPDATES.md) and
[upgrading the existing installation](UPGRADING.md).

## Privacy and trust

The **repository signing key** authenticates the index: the list of versions,
APK hashes and download metadata. The **APK signing key** identifies the Android
application and permits updates over the installed app. They are separate keys;
the index key must not replace or re-sign the existing APK identity.

This feed distributes public application files. GitHub and its delivery
infrastructure can see requests such as IP addresses, refresh times and download
metadata. These requests do not need your mail, connector credentials, ntfy
subscription or private pairing keys. Adding this update source does not route
email or encrypted-push delivery through the F-Droid repository.

A valid index signature identifies the repository publisher; it does not make
alpha software independently audited. Keep the repository fingerprint trusted,
keep Android's signature verification enabled, and check a surprising signing
change with the maintainer before accepting it.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Repository missing, empty or HTTP 404 | The proposed address is not usable until publication is verified. Afterwards, use the complete `/fdroid/repo/` URL, enable the repository and refresh. A GitHub project homepage or release page is not the repository index. |
| Latest APK not shown yet | Compare GitHub Releases with the repository's last successful publication. Refresh the enabled source; GitHub Pages and client caches can delay visibility. Check whether the installed versionCode is already as new, and whether the client filters alpha versions. |
| Repository fingerprint or index signature error | Stop. Confirm the URL and fingerprint from this project's trusted documentation. Do not disable signature checking or accept a new key merely to clear the error. Report the error without private files. |
| Android says update is incompatible | Confirm the app ID and APK certificate above. A differently signed build or official Proton Mail cannot be updated by this APK. Keep the existing app installed while investigating. |
| Android asks for install permission | Allow app installation for your chosen F-Droid client, then retry the installation and approve Android's prompt. Menu names vary by Android version. |
| Update notification appears but app did not update | Open the client and finish the pending installation. Review its background/update settings and the installed app's version; automatic downloads and automatic installation are separate. |
| Mail alerts stop after an update | Check the paired profile, distributor connection and Android notification permission using [troubleshooting](TROUBLESHOOTING.md). Do not delete the profile or uninstall as the first step. |

For a public bug report, include the client name/version, installed MailPush
version, failing step and a few redacted error lines. Never include passwords,
one-time keys, subscription files/endpoints, mail contents or signing backups.
Use [private vulnerability reporting](https://github.com/sergue212fbright/MailPush/security/advisories/new)
for security findings.

## Maintainer setup and forks

Users adding the feed on a phone do not need GitHub environments, signing keys
or a personal fork. Maintainers use the
[`fdroid.yml` workflow](../.github/workflows/fdroid.yml), which prepares public
release files, signs the index on a separate runner, and deploys the allowlisted
public site on a third runner. It runs after successful release publication,
can be started manually, and refreshes weekly even without a new APK.

| Term | Meaning |
| --- | --- |
| GitHub Pages | Public HTTPS hosting for the repository index and application downloads; it does not run Bridge or the connector. |
| Signed repository index | Public metadata listing the APK and its hash, authenticated with the repository key. |
| `mailpush-fdroid` | Protected GitHub Actions environment for repository-index signing. Restrict deployments to the reviewed `main` branch. |
| `github-pages` | Separate deployment environment, also restricted to `main`; its runner publishes public files and receives no index-signing key. |
| Repository-index secret | Private key/password material held only in `mailpush-fdroid`, with an encrypted offline backup. Base64 is encoding, not encryption. |
| Repository fingerprint | Public SHA-256 fingerprint of the index-signing certificate, published with the repository URL and QR code. |
| Existing APK signing identity | The Android signing key already configured in `mailpush-signing`; preserve it when distributing existing MailPush APKs. |

Configure these values through GitHub's private settings. Never paste their
secret contents into an issue, terminal log or chat:

| Setting | Location and purpose |
| --- | --- |
| `FDROID_KEYSTORE_BASE64` | Secret in `mailpush-fdroid`: encoded repository-index keystore. This is a separate key from APK signing. |
| `FDROID_KEYSTORE_PASSWORD` | Secret in `mailpush-fdroid`: that keystore's password. |
| `fdroidrepo` | Fixed alias expected inside the repository keystore; this is not a secret or a configurable Actions variable. |
| `FDROID_READY` | Repository Actions variable; keep `false` until the unsigned preparation test and restricted environment setup pass. Set `true` deliberately for the first signed publication. |
| `fdroid/config.json` and `fdroid/repo-certificate.der` | Reviewed public policy and index certificate. The certificate hash must match the policy and the private keystore identity. |

For a separate maintained fork:

1. Finish the [build, signing and update setup](UPDATES.md), including a tested
   signed APK. Keep any existing APK identity for an already installed fork.
2. Review the repository-publication workflow and use your own GitHub Pages
   address. Do not publish another maintainer's address or fingerprint as yours.
3. Keep `FDROID_READY=false`, run **Actions → Publish MailPush F-Droid repository**
   on `main`, and require the preparation job to pass. It checks release metadata,
   source/APK hashes, the APK certificate and the unsigned repository without
   index-signing secrets.
4. Create the branch-restricted `mailpush-fdroid` environment, provision its two
   secrets above, and ensure its fixed `fdroidrepo` key matches your committed
   public certificate and policy. Keep private material outside the source tree
   and public logs. Do not replace an established repository key on routine runs.
5. In **Settings → Pages**, select **GitHub Actions** as the source. Restrict the
   `github-pages` environment to `main`. After the setup checks pass, enable
   `FDROID_READY=true` and manually run the workflow to sign and deploy the
   repository containing the verified release APK and corresponding source.
6. Independently check the live HTTPS URL, index signature and fingerprint, APK
   certificate/hash and versionCode. Test an in-place upgrade with an F-Droid
   client before advertising the repository as ready.
7. Publish the verified URL, fingerprint and matching QR code together. Preserve
   the index key across updates; treat a key change as a trust migration rather
   than quietly replacing it.

The public policy for `sergue212fbright/MailPush` already pins its repository
certificate. That is not a request to regenerate its key. The live address and
first deployment remain unverified until the status at the top of this guide
is updated after a successful publication check.

Official F-Droid references: [adding a repository](https://f-droid.org/en/tutorials/add-repo/),
[setting up a repository](https://f-droid.org/en/docs/Setup_an_F-Droid_App_Repo/),
and [repository versus APK signing](https://f-droid.org/docs/Signing_Process/).
