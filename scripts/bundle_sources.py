#!/usr/bin/env python3
"""Bundle the exact assembled source, excluding caches, credentials and binaries."""

import argparse, tarfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("source", type=Path)
p.add_argument("--output", required=True, type=Path)
a = p.parse_args()
blocked = {".git", ".gradle", ".kotlin", "build", ".cxx", "__pycache__", "secrets", "keystore", ".idea"}
a.output.parent.mkdir(parents=True, exist_ok=True)
with tarfile.open(a.output, "w:gz") as archive:
    for path in sorted(a.source.rglob("*")):
        relative = path.relative_to(a.source)
        if not path.is_file() or path.is_symlink() or any(x in blocked for x in relative.parts):
            continue
        if path.suffix in {".apk", ".p12", ".jks", ".keystore", ".pyc"} or path.name in {
            "local.properties",
            ".env",
        }:
            continue
        archive.add(path, arcname=Path("proton-mailpush-source") / relative, recursive=False)
print("Assembled corresponding source bundle created.")
