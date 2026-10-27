# Building and testing

This GitHub-linked fork keeps its maintained module, connector and patches on
`main`; `proton-upstream` preserves the original Proton source/history. Builds
assemble a complete Android app from an exact official commit plus our additions.
`module-check` alone builds a library, not an installable Proton Mail app. Do not
run the official reference branch's build and assume it contains MailPush.

Prerequisites: Python 3.11+ (CI uses 3.12), git, JDK 17, Android SDK command-line
tools and enough RAM/disk for a full Proton release/R8 build. Run from repo root.
`ANDROID_HOME` must name your SDK. Do not expose signing/SMTP secrets to Gradle.

```sh
python3 scripts/prepare_upstream.py --version-code 1000002
python3 scripts/verify_wrapper.py .work/proton
python3 scripts/install_sdk.py .work/proton
cd .work/proton
./gradlew --no-daemon :app:assembleProdRelease
```

CI gives the full Proton build a 6 GiB Gradle heap, limits it to two workers and
disables parallel project execution. Proton's default 4 GiB heap exhausted Java
memory when R8 and Kotlin lint ran together. On a machine with enough RAM, use
the same bounded command as CI:

```sh
./gradlew --no-daemon --no-parallel --max-workers=2 \
  '-Dorg.gradle.jvmargs=-Xmx6g -XX:MaxMetaspaceSize=1g -Dfile.encoding=UTF-8' \
  '-Pkotlin.daemon.jvmargs=-Xmx1536m' :app:assembleProdRelease
```

`--revision` accepts a full 40-character commit from the fixed official repository.
Preparation refuses an existing destination unless `--existing` is deliberate; it
requires a clean selected checkout and refuses an existing receiver module. Use
a fresh destination when updating rather than applying a second overlay over
modified source. The produced APK has application ID `ch.protonmail.android.mailpush`.

Preparation also checks that the Sentry Gradle build plugin is absent. The patch
removes its plugin/classpath/configuration while retaining the runtime APIs
required by upstream code. Empty Sentry DSNs alone are not a build-telemetry gate.
The existing `MainInitializer` calls `MailPushInitializer.install` after its
dependencies; the adapter is a plain Kotlin object rather than another AndroidX
startup initializer.

Do not use `alphaRelease` as a privacy release: upstream alpha/dev flavours have
debug-menu behaviour. Our supported target is `prodRelease`, unsigned until the
isolated signer runs.

## Tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r connector/requirements-lock.txt
.venv/bin/pip install --no-deps ./connector
.venv/bin/python -m unittest discover -s connector/tests -v
python3 -m unittest discover -s tests -v
python3 scripts/verify_wrapper.py module-check
cd module-check
./gradlew :mailpush:assembleRelease :mailpush:testReleaseUnitTest :mailpush:lintRelease
cd ..
.venv/bin/python connector/tools/verify_android_interop.py modules/mailpush
```

With exactly one connected disposable Android emulator, also run:

```sh
module-check/gradlew -p module-check :mailpush:assembleDebugAndroidTest
python3 scripts/run_device_checks.py
```

The strict runner grants the synthetic test application's notification permission,
runs only `DeviceSecurityTest`, and requires each checked-in method to start/pass
exactly once with zero skips. A zero ADB exit alone is not sufficient. Receipts
are written under `.work/device-checks`. The CI emulator uses API 35 with KVM.
These tests exercise real Keystore/SQLite and key deletion, using synthetic data.
They do not test Proton login, distribution uptime or GrapheneOS background policy.

For the full build, audit the unsigned APK with `scripts/audit_apk.py`, then sign
using `scripts/sign_apk.py` only in your private release environment. The expected
certificate SHA-256 must be set; debug signing is intentionally disabled. Keep the
same certificate and increase Android versionCode for every installed update.

## Rebuilding a release's corresponding-source archive

The release includes the assembled Proton tree, module, adapter, applied patches,
licenses and `.mailpush-prepared.json`. Build caches, APKs and credentials are
excluded. Archives omit Git history. Proton's build currently asks git for a
display hash: initialize a local git repository and make a local source commit
before building this extracted tree, then run its Gradle wrapper. That local
display hash will differ; original provenance remains in `.mailpush-prepared.json`
and release metadata. Bit-for-bit reproducibility has not been demonstrated.

The signed APK and a source archive are distinct artifacts. Never run build code
from an extracted upstream archive on the runner that holds your signing key.

## Dependency updates

Dependabot groups workflow actions, Android libraries, Android build tools and
F-Droid tooling into separate reviewable pull requests. It does not merge them.
The module check currently uses the tested Gradle 8.13 / Android Gradle Plugin
8.13.2 pair. Major toolchain migrations require manual compatibility review.
F-Droid server 2.4.5 requires `ruamel.yaml>=0.15,<0.17.22`; upgrade the server and
its complete lock together before relaxing that bound.

Gradle verifies dependencies against `module-check/gradle/verification-metadata.xml`.
A bot changing a version alone cannot approve the new artifacts. For a reviewed
library update, resolve and test all affected configurations in an environment
without production secrets:

```sh
cd module-check
./gradlew --no-daemon --write-verification-metadata sha256 \
  :mailpush:assembleRelease :mailpush:testReleaseUnitTest \
  :mailpush:lintRelease :mailpush:assembleDebugAndroidTest
```

Inspect the metadata diff and independently compare new hashes with the exact
artifacts from official Google Maven / Maven Central. Commit the verified hashes
with the version change, then rerun those tasks without the write flag. Never
disable dependency verification to make a pull request green. Runtime library
changes also require the Android device gate and full Proton build before a
signed release. Python F-Droid lock changes must retain `--require-hashes` and
pass its complete installation and keyless repository preflight.
