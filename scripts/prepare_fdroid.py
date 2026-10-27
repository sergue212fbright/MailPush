#!/usr/bin/env python3
"""Prepare an unsigned binary F-Droid feed without any private signing key.

Only APKs from this repository's automated releases are accepted. Their package,
version, expected APK certificate, compiled manifest and checksums are verified
before fdroidserver parses them. The separate index signer receives a manifest
of public files; configuration, download metadata and caches stay outside site/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MAX_SITE_BYTES = 650_000_000
MAX_RELEASES = 3
MAX_API_BYTES = 5_000_000
MAX_SOURCE_BYTES = 64_000_000
ASSETS = {"MailPush.apk", "source.tar.gz", "release.json", "SHA256SUMS"}
INDEX_FILES = {"entry.json", "index-v1.json", "index-v2.json"}
CDN_HOSTS = {"release-assets.githubusercontent.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com"}
TAG = re.compile(r"mailpush-([a-f0-9]{12})-([a-f0-9]{12})")
HEX = re.compile(r"[a-f0-9]{64}")


class FeedError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_policy(path: Path) -> dict:
    policy = json.loads(path.read_text())
    required = {"schema", "repository", "application_id", "apk_certificate_sha256",
                "repo_certificate_sha256", "repo_url", "repo_name", "repo_description"}
    if not isinstance(policy, dict) or set(policy) != required or policy["schema"] != 1:
        raise FeedError("Unsupported F-Droid policy fields/schema")
    repository = policy["repository"]
    if not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise FeedError("Invalid GitHub repository")
    owner, name = repository.split("/")
    expected_url = "https://" + owner.lower() + ".github.io/" + name + "/fdroid/repo"
    if policy["repo_url"] != expected_url:
        raise FeedError("Repository URL does not match the configured GitHub Pages project")
    if not isinstance(policy["application_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,}", policy["application_id"]):
        raise FeedError("Invalid application ID")
    for key in ("apk_certificate_sha256", "repo_certificate_sha256"):
        if not isinstance(policy[key], str) or not HEX.fullmatch(policy[key]):
            raise FeedError("Invalid expected certificate fingerprint")
    if policy["apk_certificate_sha256"] == policy["repo_certificate_sha256"]:
        raise FeedError("The repository index must use a separate signing identity")
    for key in ("repo_name", "repo_description"):
        if not isinstance(policy[key], str) or not 1 <= len(policy[key]) <= 3000 or "\0" in policy[key]:
            raise FeedError("Invalid public repository description")
    return policy


def validate_url(url: str, repository: str, *, redirect: bool = False) -> None:
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        raise FeedError("Invalid download URL")
    parsed = urllib.parse.urlsplit(url)
    try:
        safe_port = parsed.port in (None, 443)
    except ValueError as error:
        raise FeedError("Invalid download URL port") from error
    decoded_path = urllib.parse.unquote(parsed.path)
    if (parsed.scheme != "https" or not safe_port or parsed.username is not None
            or parsed.password is not None or parsed.fragment or "\\" in decoded_path
            or any(part in {".", ".."} for part in decoded_path.split("/"))):
        raise FeedError("Only approved HTTPS downloads are supported")
    if parsed.hostname == "api.github.com" and parsed.path.startswith("/repos/" + repository + "/"):
        return
    if parsed.hostname == "github.com" and parsed.path.startswith("/" + repository + "/releases/download/"):
        return
    if redirect and parsed.hostname in CDN_HOSTS:
        return
    raise FeedError("Download URL is outside the configured GitHub repository/asset CDN")


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, repository: str):
        self.repository = repository

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.repository, redirect=True)
        # A GitHub asset redirect carries its own short-lived authorization.
        # Never carry repository credentials, cookies or proxy auth to the CDN.
        clean = {k: v for k, v in req.headers.items()
                 if k.lower() not in {"authorization", "cookie", "proxy-authorization"}}
        return urllib.request.Request(newurl, headers=clean, method="GET")


class GitHubDownloads:
    def __init__(self, repository: str):
        self.repository = repository
        self.deadline = time.monotonic() + 1800
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            AssetRedirect(repository))

    def response(self, url: str):
        validate_url(url, self.repository)
        if time.monotonic() >= self.deadline:
            raise FeedError("GitHub download time budget exceeded")
        headers = {"User-Agent": "MailPush-FDroid", "Accept": "application/octet-stream"}
        if urllib.parse.urlsplit(url).hostname == "api.github.com":
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if token:
                headers["Authorization"] = "Bearer " + token
        return self.opener.open(urllib.request.Request(url, headers=headers), timeout=30)

    def small(self, url: str, limit: int) -> bytes:
        deadline = min(self.deadline, time.monotonic() + 120)
        blocks, size = [], 0
        with self.response(url) as response:
            while block := response.read1(min(65_536, limit + 1)):
                size += len(block)
                if size > limit or time.monotonic() >= deadline:
                    raise FeedError("GitHub metadata exceeds its size/time limit")
                blocks.append(block)
        return b"".join(blocks)

    def file(self, url: str, path: Path, expected_size: int, expected_sha: str) -> None:
        digest, size = hashlib.sha256(), 0
        deadline = min(self.deadline, time.monotonic() + 900)
        with self.response(url) as response, path.open("xb") as output:
            # read1 returns available data after at most one underlying read, so
            # trickling bodies cannot postpone our wall-clock deadline forever.
            while block := response.read1(65_536):
                size += len(block)
                if size > expected_size or time.monotonic() >= deadline:
                    raise FeedError("Asset exceeds its advertised size or download budget")
                digest.update(block)
                output.write(block)
        if size != expected_size or digest.hexdigest() != expected_sha:
            raise FeedError("Downloaded release asset checksum/size mismatch")


def checksums(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise FeedError("Release checksums must be ASCII") from error
    result = {}
    for line in lines:
        match = re.fullmatch(r"([a-f0-9]{64})  (MailPush\.apk|source\.tar\.gz|release\.json)", line)
        if not match or match[2] in result:
            raise FeedError("Unexpected or duplicate checksum entry")
        result[match[2]] = match[1]
    if set(result) != ASSETS - {"SHA256SUMS"}:
        raise FeedError("Incomplete release checksum set")
    return result


def release_assets(release: dict, repository: str) -> dict:
    tag = release.get("tag_name", "")
    if not isinstance(tag, str) or not TAG.fullmatch(tag) or release.get("draft") is not False:
        raise FeedError("Not a published automated MailPush release")
    if release.get("author", {}).get("login") != "github-actions[bot]":
        raise FeedError("Release was not published by GitHub Actions")
    if type(release.get("id")) is not int or release["id"] <= 0:
        raise FeedError("Invalid GitHub release identifier")
    assets = release.get("assets")
    if not isinstance(assets, list) or {a.get("name") for a in assets} != ASSETS or len(assets) != len(ASSETS):
        raise FeedError("Unexpected automated release asset set")
    output = {}
    for asset in assets:
        name = asset["name"]
        url = "https://github.com/" + repository + "/releases/download/" + tag + "/" + name
        if asset.get("browser_download_url") != url or asset.get("state") != "uploaded":
            raise FeedError("Unexpected release asset location/state")
        if type(asset.get("size")) is not int or asset["size"] <= 0:
            raise FeedError("Invalid release asset size")
        output[name] = {**asset, "url": url}
    if output["release.json"]["size"] > 32_768 or output["SHA256SUMS"]["size"] > 4096:
        raise FeedError("Release metadata exceeds its size limit")
    if output["MailPush.apk"]["size"] > 600_000_000 or output["source.tar.gz"]["size"] > MAX_SOURCE_BYTES:
        raise FeedError("Release binary/source exceeds its size limit")
    return output


def validate_release(release: dict, assets: dict, metadata_bytes: bytes,
                     checksum_bytes: bytes, policy: dict) -> dict:
    sums = checksums(checksum_bytes)
    if hashlib.sha256(metadata_bytes).hexdigest() != sums["release.json"]:
        raise FeedError("Release metadata checksum mismatch")
    metadata = json.loads(metadata_bytes)
    code = metadata.get("version_code")
    upstream, module = metadata.get("upstream_commit", ""), metadata.get("module_sha256", "")
    if (metadata.get("schema") != 1 or metadata.get("application_id") != policy["application_id"] or type(code) is not int
            or not 1 <= code <= 2_100_000_000 or not re.fullmatch(r"[a-f0-9]{40}", upstream)
            or not HEX.fullmatch(module)):
        raise FeedError("Invalid release application/version/source provenance")
    tag = "mailpush-" + upstream[:12] + "-" + module[:12]
    if metadata.get("release_tag") != tag or release["tag_name"] != tag:
        raise FeedError("Release source/tag binding mismatch")
    if (metadata.get("manifest_policy") != "passed" or metadata.get("apk_sha256") != sums["MailPush.apk"]
            or type(metadata.get("apk_bytes")) is not int or metadata["apk_bytes"] != assets["MailPush.apk"]["size"]):
        raise FeedError("Release APK metadata/checksum mismatch")
    if release.get("name") != "MailPush build " + str(code):
        raise FeedError("Release title/version binding mismatch")
    for name, digest in sums.items():
        reported = assets[name].get("digest")
        if reported is not None and reported != "sha256:" + digest:
            raise FeedError("GitHub asset digest differs from release checksums")
    reported = assets["SHA256SUMS"].get("digest")
    if reported is not None and reported != "sha256:" + hashlib.sha256(checksum_bytes).hexdigest():
        raise FeedError("GitHub checksum-file digest mismatch")
    return {"release_id": release["id"], "tag": tag, "upstream_commit": upstream,
            "module_sha256": module, "version_code": code,
            "apk_sha256": sums["MailPush.apk"], "apk_bytes": metadata["apk_bytes"],
            "source_sha256": sums["source.tar.gz"], "source_bytes": assets["source.tar.gz"]["size"],
            "assets": assets}


def newest_unique(releases: list[dict]) -> list[dict]:
    unique = {}
    for release in releases:
        code = release["version_code"]
        if code in unique and any(unique[code][key] != release[key] for key in
                                  ("apk_sha256", "source_sha256", "upstream_commit", "module_sha256")):
            raise FeedError("Two releases advertise conflicting APK/source provenance for one versionCode")
        unique.setdefault(code, release)
    selected = [unique[c] for c in sorted(unique, reverse=True)[:MAX_RELEASES]]
    if not selected:
        raise FeedError("No verified automated signed release is available")
    if sum(r["apk_bytes"] + r["source_bytes"] for r in selected) >= MAX_SITE_BYTES:
        raise FeedError("Selected APKs and source already exceed the Pages budget")
    return selected


def public_path(relative: str, application_id: str) -> bool:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        return False
    if len(path.parts) == 1:
        return relative in INDEX_FILES or bool(re.fullmatch(
            re.escape(application_id) + r"_[1-9][0-9]*(?:\.apk|_src\.tar\.gz)", relative))
    return (len(path.parts) == 2 and bool(re.fullmatch(r"icons(?:-[0-9]+)?", path.parts[0]))
            and bool(re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:png|webp|jpg|jpeg)", path.parts[1])))


def site_manifest(site: Path, policy: dict) -> list[dict]:
    files, size = [], 0
    for path in sorted(site.rglob("*")):
        if path.is_symlink():
            raise FeedError("Symlinks are not permitted in the Pages artifact")
        if not path.is_file():
            continue
        relative = path.relative_to(site).as_posix()
        if path.stat().st_nlink != 1 or not relative.startswith("fdroid/repo/") or not public_path(relative[len("fdroid/repo/"):], policy["application_id"]):
            raise FeedError("Unexpected public file or hardlink")
        size += path.stat().st_size
        if size > MAX_SITE_BYTES:
            raise FeedError("Generated Pages feed exceeds 650 MB")
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return files


def clean_environment() -> dict:
    # APK/resource parsers do not need repository tokens or any signing secrets.
    allowed = {"PATH", "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "HOME",
               "TMPDIR", "LANG", "LC_ALL", "CI", "GITHUB_ACTIONS", "VIRTUAL_ENV",
               "LD_LIBRARY_PATH"}
    return {k: v for k, v in os.environ.items() if k in allowed}


def verify_apk(apk: Path, tools: Path, policy: dict, code: int) -> None:
    verified = subprocess.run([str(tools / "apksigner"), "verify", "--verbose", "--print-certs", str(apk)],
                              check=True, capture_output=True, text=True, timeout=120, env=clean_environment())
    signers = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([a-f0-9]{64})", verified.stdout)
    if signers != [policy["apk_certificate_sha256"]]:
        raise FeedError("APK does not have the configured single release signer")
    audited = subprocess.run([sys.executable, str(ROOT / "scripts/audit_apk.py"), str(apk),
                              "--aapt", str(tools / "aapt"), "--application-id", policy["application_id"],
                              "--version-code", str(code)], check=True, capture_output=True,
                             text=True, timeout=120, env=clean_environment())
    if json.loads(audited.stdout).get("manifest_policy") != "passed":
        raise FeedError("Compiled APK manifest audit failed")


def prepare(output: Path, tools: Path) -> None:
    import yaml  # Installed with the pinned fdroidserver tooling; safe data only.

    policy = load_policy(ROOT / "fdroid/config.json")
    public_der = (ROOT / "fdroid/repo-certificate.der").read_bytes()
    if not 128 <= len(public_der) <= 16_384 or hashlib.sha256(public_der).hexdigest() != policy["repo_certificate_sha256"]:
        raise FeedError("Public repository certificate differs from policy")
    if output.exists() or output.is_symlink():
        raise FeedError("Refusing to replace an existing preparation directory")
    download = GitHubDownloads(policy["repository"])
    # The workflow publishes monotonically increasing versionCodes. Bound the
    # metadata scan to GitHub's newest 100 releases, then sort verified numeric
    # metadata rather than trusting API order, release titles or tag strings.
    listing = json.loads(download.small("https://api.github.com/repos/" + policy["repository"] + "/releases?per_page=100", MAX_API_BYTES))
    if not isinstance(listing, list):
        raise FeedError("Unexpected GitHub release response")
    candidates = []
    for release in listing:
        if release.get("draft") or not TAG.fullmatch(release.get("tag_name", "")):
            continue
        assets = release_assets(release, policy["repository"])
        candidates.append(validate_release(release, assets,
            download.small(assets["release.json"]["url"], 32_768),
            download.small(assets["SHA256SUMS"]["url"], 4096), policy))
    selected = newest_unique(candidates)
    with tempfile.TemporaryDirectory(prefix="mailpush-fdroid-") as temporary:
        work = Path(temporary)
        repo = work / "repo"
        repo.mkdir()
        (work / "metadata").mkdir()
        metadata = yaml.safe_load((ROOT / "fdroid/metadata.yaml").read_text())
        if not isinstance(metadata, dict) or any(k in metadata for k in ("Builds", "Repo", "RepoType", "Binaries")):
            raise FeedError("Binary repository metadata must not contain build/VCS instructions")
        metadata["AllowedAPKSigningKeys"] = [policy["apk_certificate_sha256"]]
        metadata["CurrentVersionCode"] = selected[0]["version_code"]
        metadata.pop("CurrentVersion", None)
        (work / "metadata" / (policy["application_id"] + ".yml")).write_text(yaml.safe_dump(metadata, sort_keys=False))
        config = {"repo_url": policy["repo_url"], "repo_name": policy["repo_name"],
                  "repo_description": policy["repo_description"], "repo_keyalias": "fdroidrepo",
                  "repo_pubkey": public_der.hex(), "archive_older": 0,
                  "repo_maxage": 14 * 86_400,
                  "sdk_path": str(tools.parent.parent), "apksigner": str(tools / "apksigner")}
        (work / "config.yml").write_text(yaml.safe_dump(config, sort_keys=False))
        for release in selected:
            stem = policy["application_id"] + "_" + str(release["version_code"])
            apk, source = repo / (stem + ".apk"), repo / (stem + "_src.tar.gz")
            download.file(release["assets"]["MailPush.apk"]["url"], apk, release["apk_bytes"], release["apk_sha256"])
            verify_apk(apk, tools, policy, release["version_code"])
            # Corresponding source remains an inert archive; it is never unpacked
            # or executed by feed preparation, signing or Pages deployment.
            download.file(release["assets"]["source.tar.gz"]["url"], source, release["source_bytes"], release["source_sha256"])
            release["apk_path"] = "fdroid/repo/" + apk.name
            release["source_path"] = "fdroid/repo/" + source.name
        subprocess.run(["fdroid", "update", "--nosign"], cwd=work, check=True,
                       timeout=600, env=clean_environment(), stdout=subprocess.DEVNULL)
        # Only the supported v1/v2 feed is transferred. The signer generates a
        # fixed landing page from trusted policy; no prepared HTML is published.
        for name in ("index_unsigned.jar", "index.xml"):
            (repo / name).unlink(missing_ok=True)
        target = output / "site/fdroid/repo"
        target.mkdir(parents=True)
        for path in repo.rglob("*"):
            if path.is_symlink():
                raise FeedError("Generated feed contains a symlink")
            if path.is_file() and public_path(path.relative_to(repo).as_posix(), policy["application_id"]):
                dest = target / path.relative_to(repo)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
        if not all((target / name).is_file() for name in INDEX_FILES):
            raise FeedError("fdroidserver did not produce the complete unsigned index set")
        files = site_manifest(output / "site", policy)
        manifest = {"schema": 1, **{k: policy[k] for k in (
            "repository", "application_id", "repo_url", "apk_certificate_sha256", "repo_certificate_sha256")},
            "version_codes": [r["version_code"] for r in selected],
            "releases": [{k: v for k, v in r.items() if k != "assets"} for r in selected],
            "site_files": files, "site_bytes": sum(f["bytes"] for f in files)}
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Prepared unsigned F-Droid feed:", len(selected), "versions,", manifest["site_bytes"], "public bytes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build-tools", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.build_tools.resolve())


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Redirect URLs can contain short-lived CDN credentials. Do not echo
        # network/library exception text or subprocess output into public logs.
        message = str(error) if isinstance(error, FeedError) else type(error).__name__
        raise SystemExit("F-Droid preparation failed: " + message)
