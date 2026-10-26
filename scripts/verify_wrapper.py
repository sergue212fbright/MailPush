#!/usr/bin/env python3
"""Pin the wrapper ZIP to the official Gradle distribution checksum.

Do not execute Gradle before validating its wrapper JAR separately (CI runs the
Gradle-maintained wrapper-validation action). No arbitrary distribution host or
custom checksum URL is accepted.
"""

from pathlib import Path
import argparse, hashlib, re, urllib.request

p = argparse.ArgumentParser()
p.add_argument("source", type=Path)
a = p.parse_args()
file = a.source / "gradle/wrapper/gradle-wrapper.properties"
text = file.read_text()
urls = re.findall(r"^distributionUrl=(.+)$", text, re.M)
if len(urls) != 1:
    raise SystemExit("Invalid wrapper URL")
url = urls[0].replace("\\:", ":")
if not re.fullmatch(
    r"https://services\.gradle\.org/distributions/gradle-[0-9]+(?:\.[0-9]+){1,2}-bin\.zip", url
):
    raise SystemExit("Wrapper distribution is not an approved official URL")
# Validate the JAR ourselves as well: hidden assembled source directories can be
# missed by an action's glob rules. Checksums are always obtained from Gradle.
version = re.search(r"/gradle-([0-9.]+)-bin\.zip$", url)[1]
with urllib.request.urlopen(
    "https://services.gradle.org/distributions/gradle-" + version + "-wrapper.jar.sha256",
    timeout=30,
) as r:
    wrapper_sha = r.read(128).decode().strip()
if (
    not re.fullmatch("[a-f0-9]{64}", wrapper_sha)
    or hashlib.sha256((a.source / "gradle/wrapper/gradle-wrapper.jar").read_bytes()).hexdigest()
    != wrapper_sha
):
    raise SystemExit("Gradle wrapper JAR differs from the official checksum")
with urllib.request.urlopen(url + ".sha256", timeout=30) as r:
    sha = r.read(128).decode().strip()
if not re.fullmatch("[a-f0-9]{64}", sha):
    raise SystemExit("Invalid official Gradle checksum")
existing = re.findall(r"^distributionSha256Sum=(.+)$", text, re.M)
if existing and existing != [sha]:
    raise SystemExit("Upstream wrapper checksum differs from official Gradle checksum")
if not existing:
    text += "\ndistributionSha256Sum=" + sha + "\n"
file.write_text(text)
print("Official Gradle distribution SHA-256 pinned:", sha)
