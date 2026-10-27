#!/usr/bin/env python3
"""Run the synthetic Android security suite and reject missing/skipped tests.

ADB may return zero even when instrumentation crashes. Gradle can also report a
successful task when a JUnit assumption skipped a security check. Publication
therefore depends on named method results, not either process exit code alone.
This runner uses only a disposable emulator; no real account or signing key is
needed. The emulator action remains responsible for booting/stopping Android.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
TEST_CLASS = "app.mailpush.companion.DeviceSecurityTest"
TEST_PACKAGE = "app.mailpush.companion.test"
RUNNER = TEST_PACKAGE + "/androidx.test.runner.AndroidJUnitRunner"
TEST_SOURCE = "modules/mailpush/src/androidTest/java/app/mailpush/companion/DeviceSecurityTest.java"


class DeviceCheckError(RuntimeError):
    pass


def expected_methods(project: Path) -> set[str]:
    # The checked-in class is the source of truth as the suite grows. A changed
    # annotation/signature that this deliberately narrow parser cannot recognize
    # fails closed when the Android runner reports the unmatched method/count.
    names = re.findall(r"@Test\s+public\s+void\s+([A-Za-z_$][\w$]*)\s*\(",
                       (project / TEST_SOURCE).read_text())
    if not names or len(set(names)) != len(names):
        raise DeviceCheckError("Expected a nonempty suite with unique test methods")
    return set(names)


def evaluate_instrumentation(output: str, expected: set[str], adb_exit: int | None) -> dict:
    """Require one start/pass per expected method and a successful final result."""
    statuses, pending, reasons = [], {}, []
    for line in output.splitlines():
        field = re.fullmatch(r"INSTRUMENTATION_STATUS: (class|test|numtests|current)=(.*)", line)
        if field:
            pending[field[1]] = field[2]
        code = re.fullmatch(r"INSTRUMENTATION_STATUS_CODE: (-?\d+)", line)
        if code:
            statuses.append({**pending, "code": int(code[1])})
            pending = {}
    started, passed, finished = set(), set(), set()
    for status in statuses:
        name, code = status.get("test"), status["code"]
        if status.get("class") != TEST_CLASS or name not in expected:
            reasons.append("Unknown or missing test class/method")
            continue
        if status.get("numtests") != str(len(expected)):
            reasons.append("Reported suite size differs from the checked-in test class")
        current = status.get("current", "")
        if not current.isdigit() or not 1 <= int(current) <= len(expected):
            reasons.append("Invalid test index")
        if code == 1:
            if name in started or name in finished:
                reasons.append("Duplicate test start: " + name)
            started.add(name)
        else:
            if name not in started or name in finished:
                reasons.append("Missing start or duplicate result: " + name)
            finished.add(name)
            if code == 0:
                passed.add(name)
            else:
                reasons.append("Test did not pass: " + name + " (status " + str(code) + ")")
    if not expected or started != expected or passed != expected or finished != expected:
        reasons.append("Not every expected method started and passed exactly once")
    summaries = re.findall(r"^OK\s*\((\d+)\s+tests?\)\s*$", output, re.M)
    if summaries != [str(len(expected))]:
        reasons.append("Missing, duplicate or incorrect final test count")
    if re.findall(r"^INSTRUMENTATION_CODE: (-?\d+)\s*$", output, re.M) != ["-1"]:
        reasons.append("Instrumentation did not return its successful final result")
    if adb_exit != 0:
        reasons.append("ADB instrumentation process did not exit successfully")
    if any(marker in output for marker in (
        "FAILURES!!!", "INSTRUMENTATION_FAILED", "INSTRUMENTATION_ABORTED",
        "Process crashed", "INSTRUMENTATION_RESULT: shortMsg=",
    )):
        reasons.append("Instrumentation reported a failure or crash")
    return {
        "status": "failed" if reasons else "passed",
        "expected_tests": len(expected), "expected_methods": sorted(expected),
        "test_methods_started": len(started), "tests_run": len(finished),
        "passed": len(passed),
        "failures": sum(s["code"] == -2 for s in statuses),
        "errors": sum(s["code"] == -1 for s in statuses),
        "skipped": sum(s["code"] in {-3, -4} for s in statuses),
        "adb_test_exit": adb_exit, "test_statuses": statuses,
        "validation_errors": list(dict.fromkeys(reasons)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / ".work/device-checks")
    args = parser.parse_args()
    project, out = args.project.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    transcript = out / "instrumentation.txt"
    transcript.write_text("")  # Never leave a previous successful transcript.
    result = {"schema": 1, "status": "failed", "synthetic_data_only": True,
              "test_class": TEST_CLASS, "commands": {}, "tests_run": 0}
    begun = time.monotonic()

    def capture(stage: str, command: list[str], timeout: int, check: bool = True) -> tuple[str, int]:
        print("Android device checks: " + stage, flush=True)
        try:
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors="replace", timeout=timeout)
            text, code = completed.stdout, completed.returncode
        except subprocess.TimeoutExpired as error:
            partial = error.stdout or ""
            text = partial.decode("utf-8", "replace") if isinstance(partial, bytes) else partial
            (out / ("instrumentation.txt" if stage == "instrumentation" else stage + ".txt")).write_text(
                text.replace(str(project), "<repo>") + "\n[command timed out]\n")
            result["commands"][stage] = {"timed_out": True, "limit_seconds": timeout}
            raise DeviceCheckError(stage + " exceeded its bounded timeout") from error
        (out / ("instrumentation.txt" if stage == "instrumentation" else stage + ".txt")).write_text(
            text.replace(str(project), "<repo>"))
        result["commands"][stage] = {"exit_code": code, "limit_seconds": timeout}
        if check and code:
            raise DeviceCheckError(stage + " failed (exit " + str(code) + ")")
        return text, code

    expected: set[str] = set()
    try:
        expected = expected_methods(project)
        result.update({"expected_tests": len(expected), "expected_methods": sorted(expected)})
        sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
        if not sdk:
            raise DeviceCheckError("ANDROID_HOME or ANDROID_SDK_ROOT must identify the SDK")
        adb = str(Path(sdk) / "platform-tools/adb")
        devices, _ = capture("devices", [adb, "devices"], 20)
        online = re.findall(r"^(emulator-\d+)\s+device\s*$", devices, re.M)
        if len(online) != 1:
            raise DeviceCheckError("Expected exactly one online disposable Android emulator")
        serial = online[0]
        result["emulator_serial"] = serial
        prefix = [adb, "-s", serial]
        apks = list((project / "modules/mailpush/build/outputs/apk/androidTest/debug").glob("*.apk"))
        if len(apks) != 1 or apks[0].is_symlink() or not apks[0].is_file():
            raise DeviceCheckError("Expected exactly one newly built instrumentation APK")
        with apks[0].open("rb") as stream:
            result["test_apk_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        capture("install", prefix + ["install", "-r", "-t", "-g", str(apks[0])], 180)
        # The live opt-out case intentionally skips when notifications are
        # blocked. Grant explicitly, then reject any remaining skip in the gate.
        capture("notification-permission", prefix + ["shell", "pm", "grant", TEST_PACKAGE,
                "android.permission.POST_NOTIFICATIONS"], 30)
        output, code = capture("instrumentation", prefix + ["shell", "am", "instrument", "-w", "-r",
                               "-e", "class", TEST_CLASS, RUNNER], 600, check=False)
        result.update(evaluate_instrumentation(output, expected, code))
        if result["status"] == "passed":
            # The UI test draws only its synthetic account fixture into these
            # exact files. Never collect screenshots of a real mail app/window,
            # disable FLAG_SECURE, or pull arbitrary device directories.
            previews = []
            for appearance in ("light", "dark"):
                name = "paired-" + appearance + ".png"
                path = out / name
                capture("ui-preview-" + appearance, prefix + ["pull",
                        "/sdcard/Android/data/" + TEST_PACKAGE + "/files/ui-preview/" + name,
                        str(path)], 30)
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                previews.append({"file": name, "sha256": digest, "bytes": path.stat().st_size,
                                 "synthetic_data_only": True})
            result["ui_previews"] = previews
    except (DeviceCheckError, OSError, ValueError) as error:
        # Preserve partial method results on timeout without turning them into
        # passes. The transcript is synthetic test output, never a real inbox.
        if expected and transcript.stat().st_size:
            result.update(evaluate_instrumentation(transcript.read_text(), expected, None))
        result.update({"status": "failed", "error": str(error).replace(str(project), "<repo>")})
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - begun, 1)
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Android device gate: " + result["status"] + "; receipt: " + str(out / "result.json"), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
