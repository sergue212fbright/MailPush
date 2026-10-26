#!/usr/bin/env python3
"""Create the exact release asset set after the isolated signing boundary.

Neither this script nor the signer extracts or executes the corresponding-source
archive. The archive remains data until a person chooses to rebuild it.
"""

import argparse, hashlib, json, shutil
from pathlib import Path
from audit_apk import audit

p = argparse.ArgumentParser()
p.add_argument("--input", required=True, type=Path)
p.add_argument("--output", required=True, type=Path)
p.add_argument("--build-tools", required=True, type=Path)
p.add_argument("--version-code", required=True, type=int)
a = p.parse_args()
selection = json.loads((a.input / "selection.json").read_text())
if selection["version_code"] != a.version_code:
    raise SystemExit("Selected versionCode mismatch")
metadata = audit(
    a.output / "MailPush.apk",
    a.build_tools / "aapt",
    "ch.protonmail.android.mailpush",
    a.version_code,
)
metadata.update({k: selection[k] for k in ["upstream_commit", "module_sha256", "release_tag"]})
metadata["validation"] = "Automated gates passed; see VALIDATION.md for manual-device limits."
shutil.copyfile(a.input / "source.tar.gz", a.output / "source.tar.gz")
(a.output / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
assets = ["MailPush.apk", "source.tar.gz", "release.json"]
(a.output / "SHA256SUMS").write_text(
    "".join(
        hashlib.sha256((a.output / n).read_bytes()).hexdigest() + "  " + n + "\n" for n in assets
    )
)
