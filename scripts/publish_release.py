#!/usr/bin/env python3
"""Publish only checked signed artifacts; never execute code from the build job.

The release begins as a draft. The upstream pin advances only after all assets
are uploaded. A version guard protects concurrent owner edits; published assets
are never replaced in place. Failures leave a visible draft for inspection.
"""

from __future__ import annotations
import argparse, base64, hashlib, json, os, re, urllib.request, urllib.error
from pathlib import Path


def request(path: str, method: str = "GET", payload=None, *, binary: bytes | None = None):
    token = os.environ["GH_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid repository")
    base = "https://uploads.github.com" if binary is not None else "https://api.github.com"
    if not path.startswith("/repos/" + repo + "/"):
        raise ValueError("API path outside this repository")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "MailPush-release",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = (
        binary
        if binary is not None
        else json.dumps(payload).encode() if payload is not None else None
    )
    if data is not None:
        headers["Content-Type"] = (
            "application/octet-stream" if binary is not None else "application/json"
        )
    with urllib.request.urlopen(
        urllib.request.Request(base + path, data=data, headers=headers, method=method), timeout=60
    ) as r:
        return json.loads(r.read(2_000_001))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("--upstream", required=True)
    p.add_argument("--module-sha256", required=True)
    p.add_argument("--tag", required=True)
    a = p.parse_args()
    if not re.fullmatch("[a-f0-9]{40}", a.upstream) or not re.fullmatch(
        "[a-f0-9]{64}", a.module_sha256
    ):
        raise ValueError("Invalid source provenance")
    tag = "mailpush-" + a.upstream[:12] + "-" + a.module_sha256[:12]
    if a.tag != tag:
        raise ValueError("Release tag mismatch")
    root = a.directory.resolve()
    files = sorted(x for x in root.iterdir() if x.is_file())
    names = {x.name for x in files}
    required = {"MailPush.apk", "source.tar.gz", "release.json", "SHA256SUMS"}
    if names != required:
        raise ValueError("Unexpected release files")
    # Check sums again after the isolated signing job produced the final APK.
    covered = set()
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if (
            name not in required - {"SHA256SUMS"}
            or name in covered
            or not re.fullmatch("[a-f0-9]{64}", digest)
            or hashlib.sha256((root / name).read_bytes()).hexdigest() != digest
        ):
            raise ValueError("Release checksum mismatch")
        covered.add(name)
    if covered != required - {"SHA256SUMS"}:
        raise ValueError("Incomplete release checksums")
    repo = os.environ["GITHUB_REPOSITORY"]
    prefix = "/repos/" + repo
    try:
        request(prefix + "/releases/tags/" + tag)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    else:
        raise ValueError(
            "Release tag already exists; never overwrite a published or partial release"
        )
    metadata = json.loads((root / "release.json").read_text())
    if (
        metadata.get("upstream_commit") != a.upstream
        or metadata.get("module_sha256") != a.module_sha256
    ):
        raise ValueError("Release provenance mismatch")
    if (
        type(metadata.get("version_code")) is not int
        or not 1 <= metadata["version_code"] <= 2100000000
    ):
        raise ValueError("Invalid release versionCode")
    body = (
        "Unofficial Proton Mail build with encrypted UnifiedPush support.\n\n"
        + "Upstream source: `"
        + a.upstream
        + "`\nModule/workflow source SHA-256: `"
        + a.module_sha256
        + "`\n"
        + "Android versionCode: "
        + str(metadata["version_code"])
        + "\n\n"
        + "Generic alerts by default; sender/subject previews require explicit opt-in. See repository validation notes before relying on this alpha.\n"
    )
    release = request(
        prefix + "/releases",
        "POST",
        {
            "tag_name": tag,
            "name": "MailPush build " + str(metadata["version_code"]),
            "body": body,
            "draft": True,
            "prerelease": True,
            "target_commitish": os.environ["GITHUB_SHA"],
        },
    )
    release_id = release["id"]
    if type(release_id) is not int:
        raise ValueError("Invalid release ID")
    from urllib.parse import quote

    for file in files:
        request(
            prefix + "/releases/" + str(release_id) + "/assets?name=" + quote(file.name, safe=""),
            "POST",
            binary=file.read_bytes(),
        )
    current = request(prefix + "/contents/upstream.json?ref=main")
    config = json.loads(base64.b64decode(current["content"]))
    if config["commit"] != a.upstream:
        config["commit"] = a.upstream
        request(
            prefix + "/contents/upstream.json",
            "PUT",
            {
                "message": "Track validated Proton source " + a.upstream[:12],
                "content": base64.b64encode(
                    (json.dumps(config, indent=2) + "\n").encode()
                ).decode(),
                "sha": current["sha"],
                "branch": "main",
            },
        )
    request(prefix + "/releases/" + str(release_id), "PATCH", {"draft": False})
    print("Published signed prerelease:", tag)


if __name__ == "__main__":
    main()
