# GitHub builds and updates

The workflow can check Proton's published Android source every six hours, apply
our small patches, run the tests, build an APK and publish a signed alpha release.
An upstream change that breaks a patch or check stops publication. It does not
make an AI repair. Bridge and the connector remain separate installations.

**Automatic builds are separate from installation on the phone.** A successful
GitHub run creates a downloadable APK. Keep the same Android package and signing
certificate when installing an update. Releases are prereleases while this is
alpha software; an independent updater must include prereleases if used.

## Start with one complete unsigned run

1. Use `main` as the repository's default branch. Read the repository layout in
   [BUILDING.md](BUILDING.md); the strict build always selects an exact official
   Proton commit and combines it with our maintained module.
2. In GitHub, open **Actions → Validate and update MailPush**. Enable workflows
   if GitHub presents its fork-workflow notice, then run the workflow on `main`.
3. Leave `SIGNING_READY`, `AUTO_PUBLISH` and `FAILURE_EMAIL_ENABLED` unset or
   `false`. No private signing key or SMTP credential is needed for this run.
4. Require successful `select`, `checks`, `device` and `build` jobs. The device
   gate must run every current test with zero skips; the current suite has eleven
   methods. A successful app build alone is insufficient.
5. Read the uploaded device receipt and manifest audit. A source/patch failure
   means maintenance is needed; do not bypass a failing gate to make a release.

The existing APK was functionally tested by its owner on GrapheneOS, including
sender/subject previews. Its eleven local automated Android checks could not run
because the software emulator failed. The first live GitHub KVM device job is
therefore a real remaining validation step, not an already-passed check.

## Reuse the existing signing identity

**Do not generate a new key for an already installed MailPush fork.** Use the
private signing backup supplied with that APK. A different signing certificate
will prevent an in-place update and will not preserve the existing installation.
For the delivered alpha.1 and alpha.2 APKs, the certificate SHA-256 is:

```text
bf65bf147b85f377575579d8569cfa6dda715d309ec0aabdfd7b42800f52e79e
```

Keep an encrypted offline backup of the PKCS12 file and its password. Neither the
backup nor its password belongs in this repository, an issue, a pull request, or
chat. GitHub receives the private key only when the owner deliberately configures
the signing environment below. Base64 is an encoding, not encryption.

## Create branch-restricted environments

In **repository Settings → Environments**, create these environments before
turning release switches on:

| Environment | Deployment branch policy | Secrets stored here |
| --- | --- | --- |
| `mailpush-signing` | Selected branches: `main` only | `SIGNING_KEY_BASE64`, `SIGNING_PASSWORD` |
| `mailpush-notifications` | Selected branches: `main` only | Optional SMTP secrets listed below |

Do not use an unrestricted environment or put these secrets in repository-wide
Actions secrets. Required reviewers may be added if you want manual approval of
each signing run; omit reviewers for unattended releases. Branch restriction and
code review still matter. Changes to workflow/signing code can affect release
security and should be reviewed deliberately.

### Signing settings

Under **Settings → Secrets and variables → Actions → Variables**, add:

| Repository variable | Value |
| --- | --- |
| `SIGNING_ALIAS` | `mailpush` for the supplied backup |
| `SIGNING_CERT_SHA256` | The exact lowercase fingerprint above, without colons |
| `SIGNING_READY` | Keep `false` until the key/password and restricted environment are configured; then `true` |
| `AUTO_PUBLISH` | Keep `false` until the first signed APK is verified; then `true` |

In the **`mailpush-signing` environment**, add the two secrets:

| Environment secret | Value |
| --- | --- |
| `SIGNING_KEY_BASE64` | Base64 encoding of the existing private PKCS12 file |
| `SIGNING_PASSWORD` | That file's existing password |

Load the encoding into GitHub privately; do not print it into terminal logs or
paste it into chat. The signing job runs separately from the upstream Gradle
build. It checks the unsigned manifest, expected certificate, signature and
16 KB page alignment. The source archive is treated as data in the signing job.

Run the workflow on `main` with `SIGNING_READY=true` and `AUTO_PUBLISH=false`.
Download the `signed-release` artifact, verify its fingerprint and versionCode,
and test an in-place phone upgrade. Only then enable `AUTO_PUBLISH=true` and run
again to create the first public prerelease. No re-pairing is normally needed
for an update with the same package/signing identity and compatible profile data.

## Failure notifications

The simplest starting point is GitHub's own email notifications. In your personal
GitHub **Settings → Notifications → System → Actions**, choose **Email** and
**Only notify for failed workflows**. Scheduled notifications go to the workflow's
associated user; see the official documentation below. This does not require
putting an email password into this project.

The optional SMTP job is available for a separate minimal notice. Its message
contains only a generic failure status and run link, with no mail content or
build logs. Use an SMTP service you control; a Proton mailbox password is not a
GitHub SMTP credential. Never expose Bridge's local ports to GitHub runners.

Put these credentials only in the **`mailpush-notifications` environment**:

| Environment secret | Value |
| --- | --- |
| `MAIL_USER` | SMTP username |
| `MAIL_PASSWORD` | SMTP/app password |
| `MAIL_FROM` | One sender address |
| `MAIL_TO` | One notification recipient |

Add these repository variables if using SMTP:

| Variable | Value |
| --- | --- |
| `MAIL_HOST` | SMTP provider hostname |
| `MAIL_PORT` | `465` for implicit TLS, or `587` for STARTTLS |
| `MAIL_MODE` | `ssl` or `starttls`; certificate verification stays enabled |
| `FAILURE_EMAIL_ENABLED` | `true` only after configuration |

Test a controlled failure before relying on SMTP. No real SMTP delivery has yet
been verified for this project. GitHub's own failure notifications are a useful
second channel: a broken SMTP service cannot reliably report its own failure.

## Update behavior and limits

* The workflow tracks the configured **public Proton source branch**, initially
  `main`. Source publication may lag app-store releases. It does not scrape APK
  stores or assume a public commit is the newest store APK.
* Already-published upstream/module combinations are skipped. Module, patch,
  release-tooling and workflow changes affect the release identity.
* VersionCodes use `base_version_code + GITHUB_RUN_NUMBER`. The current base is
  `1000002`, matching the highest manually delivered APK. The first CI run uses
  `1000003`. Keep this repository/workflow counter; raise the base above existing
  releases if migrating. Never lower installed versionCodes.
* The publisher stages a draft and assets before publication. Releases include
  the APK, exact corresponding source, metadata and checksums. It refuses to
  overwrite an existing published or partial release. Inspect a leftover draft
  before retrying a failed publication.
* A GitHub-linked fork does not mean **Sync fork** safely reapplies our patches.
  Use this build workflow for MailPush updates. Review changes to source layout,
  APIs, dependencies and the release workflow when strict checks fail.
* GitHub can delay schedules and can disable public-repository schedules after
  60 days without repository activity. Check **Actions** periodically, including
  during long periods with no upstream changes. This is not an external uptime
  monitor or a guarantee of zero maintenance.

Official references: [GitHub Actions notifications](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications),
[scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[secure Actions use](https://docs.github.com/en/actions/reference/security/secure-use).
