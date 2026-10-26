#!/usr/bin/env python3
"""Audit the compiled APK, not just source or Gradle settings, before signing.

The native Rust library and Proton's account behaviour still need on-device
validation. These gates make specific, checkable claims rather than declaring an
entire application 'secure' because it compiled.
"""

from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path


def audit(apk: Path, aapt: Path, application_id: str, expected_code: int | None = None) -> dict:
    if not apk.is_file() or apk.stat().st_size > 600_000_000:
        raise ValueError("Invalid APK")
    badging = subprocess.check_output([str(aapt), "dump", "badging", str(apk)], text=True)
    xml = subprocess.check_output(
        [str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"], text=True
    )
    if not re.search(r"package: name='" + re.escape(application_id) + r"'", badging):
        raise ValueError("Wrong APK application ID")
    code = int(re.search(r"versionCode='(\d+)'", badging)[1])
    if expected_code is not None and code != expected_code:
        raise ValueError("Wrong APK versionCode")
    if "application-debuggable" in badging:
        raise ValueError("Debuggable APK rejected")
    for permission in [
        "com.google.android.gms.permission.AD_ID",
        "android.permission.ACCESS_ADSERVICES_AD_ID",
        "android.permission.ACCESS_ADSERVICES_ATTRIBUTION",
        "android.permission.ACCESS_ADSERVICES_TOPICS",
    ]:
        if permission in badging:
            raise ValueError("Unexpected advertising permission")
    if not re.search(r"android:allowBackup\([^)]*\)=\(type 0x12\)0x0", xml):
        raise ValueError("Backups are not explicitly disabled")
    if not re.search(r"android:usesCleartextTraffic\([^)]*\)=\(type 0x12\)0x0", xml):
        raise ValueError("Cleartext traffic is not explicitly disabled")
    if not re.search(r"E: profileable\b[^\n]*\n\s+A: android:shell\([^)]*\)=\(type 0x12\)0x0", xml):
        raise ValueError("Shell profiling is not explicitly disabled")
    # aapt indentation identifies each manifest component and its attributes.
    components = []
    current = []
    level = None
    for line in xml.splitlines():
        element = re.match(r"^(\s*)E: ([A-Za-z_-]+)\b", line)
        if element and current and len(element[1]) <= level:
            components.append("\n".join(current))
            current = []
            level = None
        if element and element[2] in {
            "activity",
            "activity-alias",
            "service",
            "receiver",
            "provider",
        }:
            current = [line]
            level = len(element[1])
        elif current:
            current.append(line)
    if current:
        components.append("\n".join(current))
    if not components:
        raise ValueError("Compiled manifest components could not be parsed")
    for item in components:
        if any(
            name in item
            for name in [
                "FirebaseInitProvider",
                "FirebaseInstanceIdReceiver",
                "com.google.firebase.messaging.FirebaseMessagingService",
                "io.sentry.android.core.SentryInitProvider",
                "io.sentry.android.core.SentryPerformanceProvider",
            ]
        ):
            raise ValueError("Unexpected automatic push/telemetry entry point")
        if "PMFirebaseMessagingService" in item and not re.search(
            r"android:enabled\([^)]*\)=\(type 0x12\)0x0", item
        ):
            raise ValueError("Proton FCM service is not disabled")
        if "app.mailpush.companion." in item and not re.search(
            r"android:exported\([^)]*\)=\(type 0x12\)0x0", item
        ):
            raise ValueError("Unexpected exported MailPush component")
    if "app.mailpush.companion.MailPushService" not in xml:
        raise ValueError("Embedded receiver missing")
    return {
        "schema": 1,
        "application_id": application_id,
        "version_code": code,
        "apk_bytes": apk.stat().st_size,
        "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
        "manifest_policy": "passed",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("apk", type=Path)
    p.add_argument("--aapt", required=True, type=Path)
    p.add_argument("--application-id", default="ch.protonmail.android.mailpush")
    p.add_argument("--version-code", type=int)
    p.add_argument("--output", type=Path)
    a = p.parse_args()
    result = audit(a.apk, a.aapt, a.application_id, a.version_code)
    if a.output:
        a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
