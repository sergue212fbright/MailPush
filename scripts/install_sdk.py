#!/usr/bin/env python3
"""Install only version-validated SDK packages requested by the pinned source."""

import argparse, os, re, subprocess
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("source", type=Path)
a = p.parse_args()
properties = dict(
    line.split("=", 1)
    for line in (a.source / "app-configuration.properties").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
sdk = properties["compileSdk"]
ndk = properties["ndkVersion"]
if not re.fullmatch(r"\d{2,3}", sdk) or not re.fullmatch(r"\d+\.\d+\.\d+", ndk):
    raise SystemExit("Unexpected upstream SDK package version")
manager = Path(os.environ["ANDROID_HOME"]) / "cmdline-tools/latest/bin/sdkmanager"
subprocess.run(
    [str(manager), "--licenses"], input=b"y\n" * 100, stdout=subprocess.DEVNULL, check=True
)
subprocess.run(
    [
        str(manager),
        "platforms;android-" + sdk,
        "build-tools;35.0.0",
        "build-tools;36.0.0",
        "ndk;" + ndk,
    ],
    input=b"y\n" * 100,
    check=True,
)
