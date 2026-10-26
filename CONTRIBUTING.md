# Contributing to MailPush

Start with the [README](README.md). The `main` branch contains the maintained
module, adapter, patches, connector and documentation. `proton-upstream` preserves
the original Proton starting point. Complete release source is attached to each
APK release; do not copy a second Android snapshot into `main`.

Please document the user-visible problem and validation for a change. Keep Proton
integration patches small and strict. Do not add permissive patch fallbacks,
disable certificate checks, bypass secret-file modes, or replace failed release
gates with warnings. Keep real credentials/mail out of fixtures and reports.

Run `python3 -m unittest discover -s tests -v` for release tooling, and the relevant
connector/module/device checks in [BUILDING.md](docs/BUILDING.md) for changes to
those components. Android device tests must all run without skips before an
automated signed release. Functional owner reports have their own scope and do
not replace automated security tests.

Pull requests do not receive signing or SMTP secrets. Do not add workflows that
execute untrusted contribution code with release credentials. Changes to
cryptography, the host-account boundary or publication need careful review.

Use a GitHub no-reply commit email if you do not want a personal address exposed
in public history. Report sensitive security issues privately using the
repository's enabled private-reporting channel; see [SECURITY.md](SECURITY.md).
