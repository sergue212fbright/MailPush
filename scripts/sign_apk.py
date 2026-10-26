#!/usr/bin/env python3
"""Sign in an isolated CI job; upstream Gradle never sees a release key.

Only file-based password references are passed to apksigner. Private files live
in a temporary 0700 directory, are never uploaded, and are removed on exit.
"""

from __future__ import annotations
import argparse, base64, os, re, subprocess, tempfile
from pathlib import Path
from audit_apk import audit


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("apk", type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--build-tools", required=True, type=Path)
    p.add_argument("--version-code", required=True, type=int)
    a = p.parse_args()
    expected = os.environ.get("SIGNING_CERT_SHA256", "").lower()
    if not re.fullmatch("[a-f0-9]{64}", expected):
        raise ValueError("Configure the expected release certificate SHA-256")
    audit(a.apk, a.build_tools / "aapt", "ch.protonmail.android.mailpush", a.version_code)
    key = base64.b64decode(os.environ["SIGNING_KEY_BASE64"], validate=True)
    password = os.environ["SIGNING_PASSWORD"]
    alias = os.environ.get("SIGNING_ALIAS", "mailpush")
    if not 128 <= len(key) <= 100000 or not password or "\n" in password or "\r" in password:
        raise ValueError("Invalid signing configuration")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    if a.output.exists() or a.output.is_symlink():
        raise ValueError("Refusing to overwrite signing output")
    with tempfile.TemporaryDirectory(prefix="mailpush-sign-") as name:
        folder = Path(name)
        folder.chmod(0o700)
        store = folder / "release.p12"
        store.write_bytes(key)
        store.chmod(0o600)
        secret = folder / "password"
        secret.write_text(password + "\n")
        secret.chmod(0o600)
        # PKCS12 uses the store password for the private key. Passing the same
        # password file twice makes apksigner read EOF on the second access.
        subprocess.run(
            [
                str(a.build_tools / "apksigner"),
                "sign",
                "--v4-signing-enabled",
                "false",
                "--ks",
                str(store),
                "--ks-key-alias",
                alias,
                "--ks-pass",
                "file:" + str(secret),
                "--out",
                str(a.output),
                str(a.apk),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    verified = subprocess.check_output(
        [str(a.build_tools / "apksigner"), "verify", "--verbose", "--print-certs", str(a.output)],
        text=True,
    )
    certs = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([a-f0-9]+)", verified)
    if certs != [expected]:
        a.output.unlink(missing_ok=True)
        raise ValueError("Unexpected release signer")
    subprocess.run(
        [str(a.build_tools / "zipalign"), "-c", "-P", "16", "4", str(a.output)],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    print("Release signature and alignment verified; certificate SHA-256:", expected)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        raise SystemExit(
            "Signing failed (" + type(e).__name__ + "); no private signing details are logged."
        )
