#!/usr/bin/env python3
"""Assemble a Proton-derived source tree without changing our checked-in source.

The checked integration patch is intentionally strict: when upstream context has
changed, preparation stops. No fuzzy patching, text guessing or AI-generated
repairs are allowed in unattended release builds.
"""

from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFICIAL = "https://github.com/ProtonMail/android-mail.git"


class PreparationError(ValueError):
    pass


def revision(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise PreparationError("Upstream revision must be a full commit SHA")
    return value


def version_code(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 2100000000:
        raise PreparationError("Invalid Android versionCode")
    return value


def git(*args: str, cwd: Path | None = None) -> str:
    env = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        env=env,
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


def _without_gradle_comments(source: str) -> str:
    """Mask comments without mistaking URLs inside quoted strings for comments."""
    masked = list(source)
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end < 0 else end
        elif source.startswith("/*", index):
            end, depth = index + 2, 1
            while end < len(source) and depth:
                if source.startswith("/*", end):
                    depth += 1
                    end += 2
                elif source.startswith("*/", end):
                    depth -= 1
                    end += 2
                else:
                    end += 1
            if depth:
                raise PreparationError("Unterminated comment in prepared Gradle script")
        elif source[index] in {"'", '"'}:
            quote = source[index]
            delimiter = quote * 3 if source.startswith(quote * 3, index) else quote
            end = index + len(delimiter)
            while end < len(source) and not source.startswith(delimiter, end):
                end += 2 if len(delimiter) == 1 and source[end] == "\\" else 1
            if end >= len(source):
                raise PreparationError("Unterminated string in prepared Gradle script")
            index = end + len(delimiter)
            continue
        else:
            index += 1
            continue
        for position in range(index, end):
            if masked[position] != "\n":
                masked[position] = " "
        index = end
    return "".join(masked)


def assert_no_sentry_build_plugins(destination: Path) -> None:
    """Stop before Gradle can load Sentry's separately instrumented build plugin.

    Empty runtime DSNs do not disable the build plugin's own telemetry. Inspect
    the actual patched scripts for known plugin IDs, artifact coordinates and
    catalog accessors. Runtime-only Sentry API dependencies remain allowed.
    This guard is deliberately conservative; it does not execute/evaluate DSL.
    """
    forbidden = (
        r"io\.sentry\.(?:android|jvm)\.gradle\b",
        r"io\.sentry:sentry-(?:android|jvm)-gradle-plugin\b",
        r"\blibs\s*\.\s*sentry\s*\.\s*gradle\b",
        r"\blibs\s*\.\s*plugins\s*\.\s*sentry\b",
        r"\bfindLibrary\s*\(\s*[\"']sentry-gradle[\"']\s*\)",
    )
    for relative in ("build.gradle.kts", "app/build.gradle.kts"):
        source = _without_gradle_comments((destination / relative).read_text())
        if any(re.search(pattern, source) for pattern in forbidden):
            raise PreparationError("Sentry build-plugin reference remains in " + relative)


def apply_overlay(destination: Path, commit: str, code: int, application_id: str) -> dict:
    commit = revision(commit)
    code = version_code(code)
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}", application_id):
        raise PreparationError("Invalid application ID")
    destination = destination.resolve()
    if git("rev-parse", "HEAD", cwd=destination) != commit:
        raise PreparationError("Checkout is not the selected commit")
    if git("status", "--porcelain", "--untracked-files=no", cwd=destination):
        raise PreparationError("Tracked upstream files are already modified")
    module = destination / "mailpush-module"
    if module.exists() or module.is_symlink():
        raise PreparationError("Refusing to replace an existing module")
    patch = ROOT / "patches/integration.patch"
    # git apply checks all context before modifying a single tracked file.
    git("apply", "--check", str(patch), cwd=destination)
    git("apply", str(patch), cwd=destination)
    shutil.copytree(
        ROOT / "modules/mailpush",
        module,
        ignore=shutil.ignore_patterns("build", ".gradle", "__pycache__"),
    )
    target = destination / "app/src/main/kotlin/ch/protonmail/android/mailpush"
    if target.exists():
        raise PreparationError("Upstream now defines our adapter namespace; review required")
    shutil.copytree(ROOT / "adapter/src/main/kotlin/ch/protonmail/android/mailpush", target)
    # Resource-free optional telemetry calls are replaced without changing the
    # API consumed by upstream feature code. See privacy.patch for exact scope.
    privacy = ROOT / "patches/privacy.patch"
    if privacy.exists():
        git("apply", "--check", str(privacy), cwd=destination)
        git("apply", str(privacy), cwd=destination)
    # Never mark a tree prepared while a telemetry-capable Sentry build plugin
    # remains. Disabling uploads or runtime DSNs alone is insufficient.
    assert_no_sentry_build_plugins(destination)
    config = destination / "app-configuration.properties"
    text = config.read_text()
    for key, value in [("applicationId", application_id), ("versionCode", str(code))]:
        text, n = re.subn(r"^" + key + r"=.*$", key + "=" + value, text, flags=re.M)
        if n != 1:
            raise PreparationError("Upstream build property changed: " + key)
    config.write_text(text)
    detekt = destination / "config/detekt/config.yml"
    detekt.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "config/detekt-proton-core.yml", detekt)
    proguard = destination / "app/proguard/mailpush-privacy.pro"
    proguard.write_text((ROOT / "modules/mailpush/release-logging.pro").read_text())
    data = {
        "schema": 1,
        "upstream_commit": commit,
        "application_id": application_id,
        "version_code": code,
        "integration_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
    }
    (destination / ".mailpush-prepared.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--destination", type=Path, default=ROOT / ".work/proton")
    p.add_argument("--revision")
    p.add_argument("--version-code", type=int, default=1000002)
    p.add_argument(
        "--existing", action="store_true", help="Apply to an already checked-out, clean source tree"
    )
    a = p.parse_args()
    config = json.loads((ROOT / "upstream.json").read_text())
    sha = revision(a.revision or config["commit"])
    code = version_code(a.version_code)
    if config["repository"] != OFFICIAL:
        raise PreparationError("Only the official Proton source repository is supported")
    dest = a.destination.expanduser().resolve()
    if not a.existing:
        if dest.exists():
            raise PreparationError("Destination exists; use a fresh build directory")
        dest.mkdir(parents=True)
        git("init", str(dest))
        git("remote", "add", "origin", OFFICIAL, cwd=dest)
        git("fetch", "--depth=1", "origin", sha, cwd=dest)
        git("checkout", "--detach", sha, cwd=dest)
    print(json.dumps(apply_overlay(dest, sha, code, config["application_id"]), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (PreparationError, subprocess.CalledProcessError, OSError) as e:
        # Library/tool error text is not echoed: it can include local credentials.
        raise SystemExit(
            "Preparation failed: "
            + (str(e) if isinstance(e, PreparationError) else type(e).__name__)
        )
