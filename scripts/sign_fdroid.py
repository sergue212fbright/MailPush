#!/usr/bin/env python3
"""Sign only F-Droid repository metadata, never an APK.

The preparation artifact is untrusted input. Validate its complete file list,
APK identities and both index formats before reading a repository signing key.
The APK parsers and public-index verifier receive a minimal environment, and
the temporary key/configuration never enter the deployable site directory.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "sergue212fbright/MailPush"
APPLICATION_ID = "ch.protonmail.android.mailpush"
REPO_URL = "https://sergue212fbright.github.io/MailPush/fdroid/repo"
APK_CERTIFICATE = "bf65bf147b85f377575579d8569cfa6dda715d309ec0aabdfd7b42800f52e79e"
MAX_SITE_BYTES = 650_000_000
MAX_JSON_BYTES = 4_000_000
MAX_SOURCE_BYTES = 64_000_000
MAX_FILES = 256
INDEX_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
HEX = re.compile(r"[a-f0-9]{64}")
INDEX_FILES = {"entry.json", "index-v1.json", "index-v2.json"}
SIGNED_FILES = {"entry.jar", "index-v1.jar"}
SAFE_ENVIRONMENT = {
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR", "TEMP", "TMP",
    "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "SYSTEMROOT", "WINDIR",
    "COMSPEC", "PATHEXT",
}


class SigningError(ValueError):
    """Messages are fixed descriptions: never include backend output/secrets."""


def clean_environment(source=None) -> dict[str, str]:
    source = os.environ if source is None else source
    # Iterate names first, so discarded secret values are not even fetched.
    return {name: source[name] for name in source if name in SAFE_ENVIRONMENT}


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def regular_file(path: Path, *, maximum: int = MAX_SITE_BYTES) -> os.stat_result:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or not 0 < info.st_size <= maximum):
        raise SigningError("Expected a bounded regular file without links")
    return info


def real_directory(path: Path) -> None:
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise SigningError("Expected a real directory without links")


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SigningError("Duplicate JSON keys are forbidden")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    regular_file(path, maximum=MAX_JSON_BYTES)
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(data, dict):
        raise SigningError("Expected a JSON object")
    return data


def require_hex(value) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise SigningError("Invalid SHA-256 digest")
    return value


def require_code(value) -> int:
    if type(value) is not int or not 1 <= value <= 2_100_000_000:
        raise SigningError("Invalid Android version code")
    return value


def load_policy(folder: Path) -> tuple[dict, bytes]:
    policy = read_json(folder / "config.json")
    fields = {"schema", "repository", "application_id", "apk_certificate_sha256",
              "repo_certificate_sha256", "repo_url", "repo_name", "repo_description"}
    if (set(policy) != fields or type(policy["schema"]) is not int or policy["schema"] != 1
            or policy["repository"] != REPOSITORY or policy["application_id"] != APPLICATION_ID
            or policy["repo_url"] != REPO_URL or policy["apk_certificate_sha256"] != APK_CERTIFICATE):
        raise SigningError("Repository policy does not match this application and Pages URL")
    for name in ("apk_certificate_sha256", "repo_certificate_sha256"):
        require_hex(policy[name])
    if policy["repo_certificate_sha256"] == policy["apk_certificate_sha256"]:
        raise SigningError("Repository and APK signing identities must be separate")
    for name in ("repo_name", "repo_description"):
        text = policy[name]
        if not isinstance(text, str) or not 1 <= len(text) <= 3000 or any(ord(c) < 32 for c in text):
            raise SigningError("Invalid public repository description")
    certificate = folder / "repo-certificate.der"
    regular_file(certificate, maximum=20_000)
    public = certificate.read_bytes()
    if hashlib.sha256(public).hexdigest() != policy["repo_certificate_sha256"]:
        raise SigningError("Public repository certificate does not match its pinned fingerprint")
    return policy, public


def safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or any(c in value for c in ("\\", "\0", "%")):
        raise SigningError("Invalid public path")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value or any(p in {".", ".."} for p in path.parts):
        raise SigningError("Public path must be canonical and relative")
    return path


def allowed_public_path(value: str) -> bool:
    parts = safe_relative(value).parts
    if len(parts) < 3 or parts[:2] != ("fdroid", "repo"):
        return False
    tail = parts[2:]
    if len(tail) == 1:
        return tail[0] in INDEX_FILES or bool(re.fullmatch(
            re.escape(APPLICATION_ID) + r"_[1-9][0-9]*(?:\.apk|_src\.tar\.gz)", tail[0]))
    return (len(tail) == 2 and bool(re.fullmatch(r"icons(?:-[1-9][0-9]{0,3})?", tail[0]))
            and bool(re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:png|webp|jpe?g)", tail[1])))


def scan_tree(root: Path) -> dict[str, Path]:
    """Walk without following directory links; reject every nonregular leaf."""
    real_directory(root)
    files = {}
    for directory, directories, names in os.walk(root, followlinks=False):
        here = Path(directory)
        for name in directories:
            real_directory(here / name)
        for name in names:
            path = here / name
            regular_file(path)
            files[path.relative_to(root).as_posix()] = path
            if len(files) > MAX_FILES:
                raise SigningError("Too many repository files")
    return files


def validate_manifest(prepared: Path, policy: dict) -> tuple[dict, dict[str, dict]]:
    real_directory(prepared)
    if {p.name for p in prepared.iterdir()} != {"manifest.json", "site"}:
        raise SigningError("Unexpected preparation artifact contents")
    manifest = read_json(prepared / "manifest.json")
    if type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise SigningError("Unsupported preparation manifest schema")
    for field in ("repository", "application_id", "repo_url", "apk_certificate_sha256", "repo_certificate_sha256"):
        if manifest.get(field) != policy[field]:
            raise SigningError("Preparation manifest identity differs from policy")
    codes = manifest.get("version_codes")
    if not isinstance(codes, list) or not 1 <= len(codes) <= 3:
        raise SigningError("Expected one to three Android versions")
    for code in codes:
        require_code(code)
    if codes != sorted(set(codes), reverse=True):
        raise SigningError("Android versions must be unique and descending")
    rows = manifest.get("site_files")
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
        raise SigningError("Missing or oversized public file manifest")
    inventory, total = {}, 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise SigningError("Invalid public file record")
        name = row["path"]
        if not allowed_public_path(name) or name in inventory:
            raise SigningError("Unexpected or duplicate public file")
        if type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_SITE_BYTES:
            raise SigningError("Invalid public file size")
        require_hex(row["sha256"])
        total += row["bytes"]
        inventory[name] = row
    if total > MAX_SITE_BYTES or manifest.get("site_bytes") != total or type(manifest.get("site_bytes")) is not int:
        raise SigningError("Public site size differs from its bounded manifest")
    actual = scan_tree(prepared / "site")
    if set(actual) != set(inventory):
        raise SigningError("Public file inventory is incomplete or contains unknown files")
    for name, path in actual.items():
        info = regular_file(path)
        if info.st_size != inventory[name]["bytes"] or sha256_file(path) != inventory[name]["sha256"]:
            raise SigningError("Prepared public file size or checksum differs")
    required = {"fdroid/repo/" + name for name in INDEX_FILES}
    for code in codes:
        required.update({f"fdroid/repo/{APPLICATION_ID}_{code}.apk",
                         f"fdroid/repo/{APPLICATION_ID}_{code}_src.tar.gz"})
    nonicons = {name for name in inventory if "/icons" not in name}
    if nonicons != required:
        raise SigningError("APK/source/index set does not match the advertised versions")
    releases = manifest.get("releases")
    if not isinstance(releases, list) or len(releases) != len(codes):
        raise SigningError("Missing release provenance")
    provenance = {}
    for release in releases:
        if not isinstance(release, dict):
            raise SigningError("Invalid release provenance")
        code = require_code(release.get("version_code"))
        if code not in codes or code in provenance or type(release.get("release_id")) is not int or release["release_id"] <= 0:
            raise SigningError("Release provenance version or identity differs")
        upstream, module = release.get("upstream_commit"), release.get("module_sha256")
        if not isinstance(upstream, str) or not re.fullmatch(r"[a-f0-9]{40}", upstream):
            raise SigningError("Invalid release source commit")
        require_hex(module)
        if release.get("tag") != "mailpush-" + upstream[:12] + "-" + module[:12]:
            raise SigningError("Release tag does not bind its recorded source")
        for prefix, suffix, maximum in (("apk", ".apk", 600_000_000), ("source", "_src.tar.gz", MAX_SOURCE_BYTES)):
            path = f"fdroid/repo/{APPLICATION_ID}_{code}{suffix}"
            row = inventory[path]
            if (release.get(prefix + "_path") != path or release.get(prefix + "_sha256") != row["sha256"]
                    or type(release.get(prefix + "_bytes")) is not int or release[prefix + "_bytes"] != row["bytes"]
                    or row["bytes"] > maximum):
                raise SigningError("Release APK/source provenance differs from public files")
        provenance[code] = release
    return manifest, inventory


def indexed_file(entry, inventory: dict, *, exact_name: str | None = None,
                 entry_index: bool = False) -> str:
    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
        raise SigningError("Invalid indexed public file")
    allowed = {"name", "size", "sha256"} | ({"numPackages"} if entry_index else set())
    if set(entry) != allowed:
        raise SigningError("Unsupported indexed file fields")
    name = entry["name"]
    if not name.startswith("/") or name.startswith("//"):
        raise SigningError("Indexed files must use repository-relative absolute paths")
    relative = name[1:]
    safe_relative(relative)
    full = "fdroid/repo/" + relative
    if full not in inventory or (exact_name is not None and relative != exact_name):
        raise SigningError("Index references an unknown public file")
    row = inventory[full]
    if (entry.get("sha256") != row["sha256"] or type(entry.get("size")) is not int
            or entry["size"] != row["bytes"]):
        raise SigningError("Indexed file checksum or size differs")
    return relative


def validate_indices(repo: Path, manifest: dict, inventory: dict, policy: dict) -> None:
    v1 = read_json(repo / "index-v1.json")
    v2 = read_json(repo / "index-v2.json")
    entry = read_json(repo / "entry.json")
    codes = manifest["version_codes"]
    releases = {r["version_code"]: r for r in manifest["releases"]}
    for record, localized in ((v1.get("repo"), False), (v2.get("repo"), True)):
        if not isinstance(record, dict) or record.get("address") != policy["repo_url"] or record.get("mirrors"):
            raise SigningError("Index repository address differs from policy")
        for field in ("name", "description"):
            expected = policy["repo_" + field]
            if record.get(field) != ({"en-US": expected} if localized else expected):
                raise SigningError("Index repository description differs from policy")
        timestamp = record.get("timestamp")
        if (type(timestamp) is not int
                or not int((time.time() - 3600) * 1000) <= timestamp <= int((time.time() + 600) * 1000)):
            raise SigningError("Invalid repository timestamp")
    if (type(v1["repo"].get("maxage")) is not int or v1["repo"]["maxage"] != INDEX_MAX_AGE_SECONDS
            or type(entry.get("maxAge")) is not int or entry["maxAge"] != INDEX_MAX_AGE_SECONDS):
        raise SigningError("Repository index lifetime must be exactly fourteen days")
    if (type(entry.get("timestamp")) is not int or entry.get("timestamp") != v2["repo"]["timestamp"]
            or v1["repo"]["timestamp"] != entry["timestamp"] or entry.get("diffs") != {}
            or type(entry.get("index", {}).get("numPackages")) is not int
            or entry["index"]["numPackages"] != 1):
        raise SigningError("Entry timestamp/package/diff scope differs")
    indexed_file(entry["index"], inventory, exact_name="index-v2.json", entry_index=True)
    if v1.get("requests") != {"install": [], "uninstall": []}:
        raise SigningError("Repository must not request application install/removal")
    if v2["repo"].get("requests", {"install": [], "uninstall": []}) != {"install": [], "uninstall": []}:
        raise SigningError("v2 repository must not request application install/removal")
    apps = v1.get("apps")
    if not isinstance(apps, list) or len(apps) != 1 or apps[0].get("packageName") != APPLICATION_ID:
        raise SigningError("Index must contain exactly the MailPush application")
    app = apps[0]
    if app.get("allowedAPKSigningKeys") != [APK_CERTIFICATE] or str(app.get("suggestedVersionCode")) != str(codes[0]):
        raise SigningError("Suggested application version or signer differs")
    if set(v1.get("packages", {})) != {APPLICATION_ID} or set(v2.get("packages", {})) != {APPLICATION_ID}:
        raise SigningError("Unexpected package in F-Droid index")
    packages = v1["packages"][APPLICATION_ID]
    if not isinstance(packages, list) or len(packages) != len(codes):
        raise SigningError("Unexpected v1 version set")
    seen = set()
    for package in packages:
        if any(name.startswith("obb") or name == "ipfsCIDv1" for name in package):
            raise SigningError("OBB and alternate-IPFS downloads are unsupported")
        code = require_code(package.get("versionCode"))
        if code not in releases or code in seen:
            raise SigningError("Unexpected or duplicate v1 version")
        seen.add(code)
        release = releases[code]
        if (package.get("packageName") != APPLICATION_ID or package.get("signer") != APK_CERTIFICATE
                or package.get("hashType") != "sha256" or package.get("hash") != release["apk_sha256"]
                or package.get("size") != release["apk_bytes"]
                or package.get("apkName") != f"{APPLICATION_ID}_{code}.apk"
                or package.get("srcname") != f"{APPLICATION_ID}_{code}_src.tar.gz"):
            raise SigningError("v1 APK/source path, hash, size or signer differs")
    v2package = v2["packages"][APPLICATION_ID]
    if v2package.get("metadata", {}).get("preferredSigner") != APK_CERTIFICATE:
        raise SigningError("v2 preferred signer differs")
    versions = v2package.get("versions", {})
    if set(versions) != {r["apk_sha256"] for r in releases.values()}:
        raise SigningError("Unexpected v2 APK hash/version set")
    for digest, package in versions.items():
        if any(name.startswith("obb") for name in package):
            raise SigningError("OBB downloads are unsupported for this application")
        code = require_code(package.get("manifest", {}).get("versionCode"))
        if code not in releases:
            raise SigningError("Unexpected v2 Android version")
        release = releases[code]
        if digest != release["apk_sha256"] or package["manifest"].get("signer", {}).get("sha256") != [APK_CERTIFICATE]:
            raise SigningError("v2 APK signer/hash binding differs")
        indexed_file(package.get("file"), inventory, exact_name=f"{APPLICATION_ID}_{code}.apk")
        indexed_file(package.get("src"), inventory, exact_name=f"{APPLICATION_ID}_{code}_src.tar.gz")
        if package.get("releaseChannels", []):
            raise SigningError("Unexpected alternate release channel")
    # Every icon advertised by v2 also participates in the signed hash chain.
    for group in (v2["repo"].get("icon", {}), v2package.get("metadata", {}).get("icon", {})):
        if not isinstance(group, dict):
            raise SigningError("Invalid localized icon metadata")
        for icon in group.values():
            path = indexed_file(icon, inventory)
            if not path.startswith("icons"):
                raise SigningError("Repository icon points outside its image directories")
    # Future/optional image metadata must not smuggle an unchecked URL, OBB or
    # traversal path. Every v2 file descriptor has its bytes in our inventory.
    def check_references(node):
        if isinstance(node, dict):
            if "name" in node and ("sha256" in node or "size" in node):
                indexed_file(node, inventory)
            for value in node.values():
                check_references(value)
        elif isinstance(node, list):
            for value in node:
                check_references(value)
    check_references(v2)


def command(arguments: list[str], environment: dict, *, cwd: Path | None = None, timeout: int = 120) -> bytes:
    completed = subprocess.run(arguments, env=environment, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, timeout=timeout, check=False)
    if completed.returncode:
        raise SigningError("A required verification or signing command failed")
    if len(completed.stdout) > MAX_JSON_BYTES:
        raise SigningError("Verification command output exceeded its bound")
    return completed.stdout


def isolated_command(arguments: list[str], environment: dict, *, cwd: Path | None = None,
                     timeout: int = 120) -> bytes:
    """Run public-input parsers as nobody in new PID/proc/network namespaces.

    Merely removing variables from a child's environment is not isolation from
    its parent's environment. Different UID plus private /proc prevents that
    access; no capabilities, no-new-privileges and no network limit a compromised
    parser. GitHub's Ubuntu runner must support this. There is no unsafe fallback.
    """
    utilities = {name: shutil.which(name, path=environment.get("PATH"))
                 for name in ("sudo", "unshare", "setpriv", "env")}
    if not all(utilities.values()):
        raise SigningError("Required public-parser namespace isolation tools are unavailable")
    public_env = {name: value for name, value in environment.items() if name in SAFE_ENVIRONMENT}
    public_env.update({"HOME": "/tmp", "TMPDIR": "/tmp"})
    prefix = [str(utilities["sudo"]), "-n", str(utilities["unshare"]), "--pid", "--fork", "--mount-proc", "--net",
              str(utilities["setpriv"]), "--no-new-privs", "--bounding-set=-all", "--inh-caps=-all",
              "--ambient-caps=-all", "--reuid=65534", "--regid=65534", "--clear-groups",
              str(utilities["env"]), "-i"]
    prefix += [name + "=" + value for name, value in sorted(public_env.items())]
    return command(prefix + arguments, {}, cwd=cwd, timeout=timeout)


ISOLATION_PROBE = r'''
import importlib.metadata, json, os, socket
from pathlib import Path
from fdroidserver import common, index
status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
assert os.getuid() == os.getgid() == 65534 and os.getgroups() == []
assert os.getpid() == 1 and os.getppid() == 0
assert status["NoNewPrivs"].strip() == "1"
assert all(int(status[key].strip(), 16) == 0 for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"))
assert [name for _, name in socket.if_nameindex()] == ["lo"]
assert importlib.metadata.version("fdroidserver") == "2.4.5"
assert not any(name.startswith(("FDROID_", "SIGNING_", "MAIL_", "SMTP_")) or name in ("GH_TOKEN", "GITHUB_TOKEN") for name in os.environ)
print(json.dumps({"uid": 65534, "gid": 65534, "pid": 1, "parent_pid": 0, "capabilities": "none",
                  "no_new_privileges": True, "network_interfaces": ["lo"], "fdroidserver": "2.4.5"}))
'''


def verify_parser_isolation(environment: dict, work: Path) -> dict:
    result = json.loads(isolated_command([str(Path(sys.executable).resolve()), "-c", ISOLATION_PROBE],
                                        environment, cwd=work, timeout=30))
    expected = {"uid": 65534, "gid": 65534, "pid": 1, "parent_pid": 0, "capabilities": "none",
                "no_new_privileges": True, "network_interfaces": ["lo"], "fdroidserver": "2.4.5"}
    if result != expected:
        raise SigningError("Public parser process isolation could not be established")
    return result


def verify_apk(path: Path, code: int, build_tools: Path, environment: dict,
               audit_script: Path | None = None) -> None:
    output = isolated_command([str(build_tools / "apksigner"), "verify", "--verbose", "--print-certs", str(path)],
                              environment, cwd=path.parent)
    fingerprints = re.findall(rb"Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})", output)
    if fingerprints != [APK_CERTIFICATE.encode("ascii")]:
        raise SigningError("APK signing certificate differs from the installed fork")
    # Resolve the base interpreter under /opt or /usr rather than a potentially
    # unreadable workspace venv. The trusted script is copied into public /tmp.
    public_python = str(Path(sys.executable).resolve())
    audited = isolated_command([public_python, str(audit_script or ROOT / "scripts/audit_apk.py"), str(path),
                                "--aapt", str(build_tools / "aapt"), "--application-id", APPLICATION_ID,
                                "--version-code", str(code)], environment, cwd=path.parent)
    result = json.loads(audited)
    if (result.get("application_id") != APPLICATION_ID or result.get("version_code") != code
            or result.get("manifest_policy") != "passed"):
        raise SigningError("Compiled APK manifest verification failed")


def verify_signed_jar_shape(path: Path, payload_name: str, original: bytes) -> None:
    regular_file(path, maximum=MAX_JSON_BYTES + 100_000)
    with zipfile.ZipFile(path) as jar:
        members = jar.infolist()
        names = [member.filename for member in members]
        if len(names) > 12 or len(set(names)) != len(names):
            raise SigningError("Unexpected signed-index JAR members")
        for member in members:
            name = member.filename
            allowed = (name in {payload_name, "META-INF/", "META-INF/MANIFEST.MF"}
                       or re.fullmatch(r"META-INF/[A-Za-z0-9_-]{1,64}\.(?:SF|RSA|DSA|EC)", name))
            if (not allowed or member.file_size > MAX_JSON_BYTES
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise SigningError("Unexpected signed-index JAR member")
        if jar.read(payload_name) != original:
            raise SigningError("Signing changed the public index payload")


VERIFY_PUBLIC = r'''
import hashlib, json, sys
from pathlib import Path
from fdroidserver import common, index
repo, public_path, jarsigner = map(Path, sys.argv[1:])
public = public_path.read_bytes()
pin = hashlib.sha256(public).hexdigest()
common.config = {"jarsigner": str(jarsigner)}
for name, legacy in (("index-v1.jar", True), ("entry.jar", False)):
    data, cert, fingerprint = index.get_index_from_jar(str(repo / name), fingerprint=pin, allow_deprecated=legacy)
    assert cert == public and fingerprint.lower() == pin
    assert data == json.loads((repo / name.replace(".jar", ".json")).read_text())
print(json.dumps({"v1_signature_and_pin": "passed", "v2_entry_signature_and_pin": "passed"}))
'''


def signing_material() -> tuple[bytes, str]:
    # This is intentionally called only after complete artifact/APK checks.
    encoded = os.environ.get("FDROID_KEYSTORE_BASE64", "")
    password = os.environ.get("FDROID_KEYSTORE_PASSWORD", "")
    if not encoded or not password:
        raise SigningError(
            "Missing repository signing secrets: configure both FDROID_KEYSTORE_BASE64 "
            "and FDROID_KEYSTORE_PASSWORD in mailpush-fdroid and explicitly pass both "
            "names when calling the reusable workflow"
        )
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, UnicodeError):
        raise SigningError("Invalid repository signing configuration") from None
    if not 128 <= len(key) <= 100_000 or not password or any(c in password for c in "\r\n\0"):
        raise SigningError("Invalid repository signing configuration")
    return key, password


def clear_private(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    # Cleanup never follows a link that a failed backend might have left.
    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        descriptor = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            os.ftruncate(descriptor, 0)
        finally:
            os.close(descriptor)
    path.unlink()


def write_private(path: Path, contents: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(contents)


def landing_page(policy: dict, codes: list[int]) -> str:
    add_uri = "fdroidrepos://" + policy["repo_url"].split("://", 1)[1] + "?fingerprint=" + policy["repo_certificate_sha256"]
    items = "".join('<li>VersionCode ' + str(code) + ': <a href="' + APPLICATION_ID + '_' + str(code)
                    + '.apk">APK</a> · <a href="' + APPLICATION_ID + '_' + str(code)
                    + '_src.tar.gz">corresponding source</a></li>' for code in codes)
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + html.escape(policy["repo_name"]) + '</title><h1>'
            + html.escape(policy["repo_name"]) + '</h1><p>' + html.escape(policy["repo_description"])
            + '</p><p><a href="' + html.escape(add_uri, quote=True) + '">Add this repository to F-Droid</a></p>'
            '<p>Repository: ' + html.escape(policy["repo_url"]) + '</p><p>Repository certificate SHA-256: <code>'
            + policy["repo_certificate_sha256"] + '</code></p><p>APK certificate SHA-256: <code>'
            + APK_CERTIFICATE + '</code></p><ul>' + items + '</ul><p>Unofficial alpha software. '
            'Repository metadata signing does not change the APK signing identity.</p></html>\n')


def sign_repository(prepared: Path, output: Path, build_tools: Path, *, policy_folder: Path | None = None,
                    verify_only: bool = False) -> dict:
    policy, public = load_policy(policy_folder or ROOT / "fdroid")
    prepared = prepared.absolute()
    output = output.absolute()
    if output.exists() or output.is_symlink() or output == prepared or prepared in output.parents or output in prepared.parents:
        raise SigningError("Refusing an existing or overlapping output directory")
    manifest, inventory = validate_manifest(prepared, policy)
    environment = clean_environment()
    if importlib.metadata.version("fdroidserver") != "2.4.5":
        raise SigningError("This signer requires the reviewed fdroidserver version 2.4.5")
    tools = {name: shutil.which(name, path=environment.get("PATH")) for name in ("keytool", "jarsigner")}
    if not all(tools.values()):
        raise SigningError("JDK keytool and jarsigner are required")
    for name in ("aapt", "apksigner"):
        if not (build_tools / name).is_file():
            raise SigningError("Android build tools are required")
    # /tmp is deliberate: the runner's home/workspace can be mode 0750. Only
    # these staged public bytes need to be readable by the isolated nobody UID.
    with tempfile.TemporaryDirectory(prefix="mailpush-fdroid-sign-", dir="/tmp") as temporary:
        work = Path(temporary)
        work.chmod(0o755)
        repo = work / "repo"
        repo.mkdir()
        repo.chmod(0o755)
        audit_script = work / "audit_apk.py"
        shutil.copyfile(ROOT / "scripts/audit_apk.py", audit_script)
        audit_script.chmod(0o644)
        for name, row in inventory.items():
            source = prepared / "site" / name
            destination = repo / Path(name).relative_to("fdroid/repo")
            destination.parent.mkdir(parents=True, exist_ok=True)
            regular_file(source)
            shutil.copyfile(source, destination)
            destination.chmod(0o644)
            if destination.stat().st_size != row["bytes"] or sha256_file(destination) != row["sha256"]:
                raise SigningError("Input changed while staging its public files")
        validate_indices(repo, manifest, inventory, policy)
        isolation = verify_parser_isolation(environment, work)
        for code in manifest["version_codes"]:
            verify_apk(repo / f"{APPLICATION_ID}_{code}.apk", code, build_tools, environment, audit_script)
        if verify_only:
            receipt = {**manifest, "status": "preflight_verified", "fdroidserver": "2.4.5",
                       "apk_identity_and_manifest": "passed", "index_signatures": "not_created",
                       "parser_isolation": "different_uid_65534_pid_proc_net_namespaces_no_capabilities",
                       "parser_isolation_receipt": isolation,
                       "repository_private_key_read": False, "signed_site_created": False}
            output.mkdir(parents=True)
            (output / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
            return receipt
        # No key has been read, decoded, written or passed to a process above.
        # Lock the parent before creating any secret. Isolated parser processes
        # cannot traverse it or read its 0600 files, even if they persisted.
        work.chmod(0o700)
        keyfile, passfile, config = work / "private-keystore", work / "private-password", work / "config.yml"
        settings = {}
        try:
            key, password = signing_material()
            write_private(keyfile, key)
            write_private(passfile, (password + "\n").encode("utf-8"))
            actual_public = command([str(tools["keytool"]), "-exportcert", "-alias", "fdroidrepo",
                                     "-keystore", str(keyfile), "-storepass:file", str(passfile)], environment)
            if actual_public != public:
                raise SigningError("Repository keystore certificate differs from its pinned public certificate")
            import yaml
            settings = {
                "repo_url": policy["repo_url"], "repo_name": policy["repo_name"],
                "repo_description": policy["repo_description"], "repo_pubkey": public.hex(),
                "archive_older": 0, "apksigner": str(build_tools / "apksigner"),
                "aapt": str(build_tools / "aapt"), "sdk_path": str(build_tools.parent.parent),
                "jarsigner": tools["jarsigner"], "keytool": tools["keytool"],
                "keystore": str(keyfile), "repo_keyalias": "fdroidrepo",
                "keystorepass": password, "keypass": password,
            }
            # Exclusive creation starts private, before plaintext is written.
            descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                yaml.safe_dump(settings, stream, sort_keys=False)
            command([sys.executable, "-m", "fdroidserver", "signindex"], environment, cwd=work, timeout=300)
        finally:
            for private in (config, passfile, keyfile):
                clear_private(private)
            settings.clear()
            key, password = None, None
        # Signing may create status diagnostics outside the allowlisted public
        # output. Never copy them, configuration or arbitrary signer output.
        for name, row in inventory.items():
            path = repo / Path(name).relative_to("fdroid/repo")
            regular_file(path)
            if path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
                raise SigningError("Signing changed a prepared public file or APK")
        for name in SIGNED_FILES:
            # A restrictive caller umask must not make public JARs unreadable
            # to the isolated verification UID (or the eventual static host).
            (repo / name).chmod(0o644)
            verify_signed_jar_shape(repo / name, name.replace(".jar", ".json"),
                                    (repo / name.replace(".jar", ".json")).read_bytes())
        public_path = work / "verified-public-certificate.der"
        public_path.write_bytes(public)
        public_path.chmod(0o644)
        # All private files were removed before making the public data readable
        # for the isolated, pinned F-Droid client verification process.
        work.chmod(0o755)
        verification = json.loads(isolated_command([str(Path(sys.executable).resolve()), "-c", VERIFY_PUBLIC,
                                                   str(repo), str(public_path), str(tools["jarsigner"])],
                                                  environment, cwd=work, timeout=180))
        expected_verification = {"v1_signature_and_pin": "passed", "v2_entry_signature_and_pin": "passed"}
        if verification != expected_verification:
            raise SigningError("Pinned F-Droid client verification failed")
        validate_indices(repo, manifest, inventory, policy)
        staged = work / "deployment"
        public_repo = staged / "site/fdroid/repo"
        public_repo.mkdir(parents=True)
        names = set(inventory) | {"fdroid/repo/" + name for name in SIGNED_FILES}
        for name in sorted(names):
            destination = staged / "site" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo / Path(name).relative_to("fdroid/repo"), destination)
        (public_repo / "index.html").write_text(landing_page(policy, manifest["version_codes"]))
        for directory, directories, names in os.walk(staged / "site"):
            Path(directory).chmod(0o755)
            for name in names:
                (Path(directory) / name).chmod(0o644)
        public_files = scan_tree(staged / "site")
        rows = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
                for name, path in sorted(public_files.items())]
        total = sum(row["bytes"] for row in rows)
        if total > MAX_SITE_BYTES:
            raise SigningError("Signed public site exceeds its deployment budget")
        receipt = {**manifest, "status": "verified", "fdroidserver": "2.4.5",
                   "site_files": rows, "site_bytes": total, **verification,
                   "v2_index_file_binding": "passed", "apk_identity_and_manifest": "passed",
                   "apk_bytes_unchanged": True, "apk_resigned": False,
                   "repository_key_alias": "fdroidrepo", "legacy_v0_published": False,
                   "parser_isolation": "different_uid_65534_pid_proc_net_namespaces_no_capabilities",
                   "parser_isolation_receipt": isolation,
                   "private_material_in_site": False}
        (staged / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, output)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build-tools", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify all unsigned inputs and isolated APK checks without reading a key or signing")
    args = parser.parse_args()
    try:
        sign_repository(args.input, args.output, args.build_tools.resolve(), verify_only=args.verify_only)
    except SigningError as error:
        # These messages are fixed strings defined in this module. Explain the
        # failed policy check while keeping all backend exception text private.
        print("F-Droid repository verification failed: " + str(error), file=sys.stderr)
        return 1
    except Exception as error:
        # Backend errors can contain configuration or remote metadata. Only the
        # exception class is logged, never command output or secret values.
        print("F-Droid metadata signing failed (" + type(error).__name__ + "). No private details are logged.", file=sys.stderr)
        return 1
    print("F-Droid public-input isolation preflight verified; no key read or index signed."
          if args.verify_only else "F-Droid v1/v2 signatures and pinned certificate verified; APK bytes unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
