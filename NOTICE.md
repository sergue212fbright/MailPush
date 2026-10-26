# Source and attribution

This is an unofficial modification of [Proton Mail Android](https://github.com/ProtonMail/android-mail).
Proton Mail and its native/core libraries retain their upstream authorship,
licenses, notices, icons and marks. The initial source pin is recorded in
`upstream.json`. It is not an official Proton release or an endorsement.

The maintained fork/adapter is GPL-3.0-or-later. The original MailPush receiver
and independently installable Python connector have MIT provenance, retained in
`modules/mailpush/LICENSE-MIT-PROVENANCE` and `connector/LICENSE`. Linking the
receiver into the GPL application does not remove those provenance notices.

UnifiedPush connector, Tink and their transitive libraries retain their upstream
licenses. Receiver notices are in `modules/mailpush/licenses`; Python dependency
attribution is in `connector/THIRD_PARTY.md`. Prepared corresponding-source
archives retain the original Proton tree's notices. Distributing an APK also
requires distributing its corresponding source and applicable license material.

The checked-in Detekt YAML is a build configuration from Proton's
`protoncore_android/config/detekt/config.yml`, originally retrieved at blob
`1677153e3f35c806aea77edcd380fcb07f9b8151`. Its retained content is configuration,
not a fetched script executed with release credentials.
