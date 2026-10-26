#!/usr/bin/env python3
"""Select published upstream source and skip a source/module pair already released.

GitHub's source publication cadence is upstream-controlled. This tracks the
configured public branch, not an unavailable private development tree or Play
Store release. All API response values are data, never shell code.
"""

from __future__ import annotations
import argparse, hashlib, json, os, re, urllib.request, urllib.error
from pathlib import Path
from prepare_upstream import ROOT, OFFICIAL, revision


def module_digest(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for folder in ["modules", "adapter", "patches", "scripts", ".github", "module-check", "config"]:
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and not any(
                x in {"build", "__pycache__", ".gradle"} for x in path.parts
            ):
                digest.update(
                    path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
                )
    policy = json.loads((root / "upstream.json").read_text())
    digest.update(
        json.dumps(
            {k: policy[k] for k in ["repository", "track", "application_id", "base_version_code"]},
            sort_keys=True,
        ).encode()
    )
    return digest.hexdigest()


def api(path: str) -> object:
    if not path.startswith("/repos/") or "://" in path:
        raise ValueError("Invalid API path")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MailPush-updater",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urllib.request.urlopen(
        urllib.request.Request("https://api.github.com" + path, headers=headers), timeout=30
    ) as response:
        return json.loads(response.read(2_000_001))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=ROOT / ".work/selection.json")
    p.add_argument("--pinned", action="store_true")
    a = p.parse_args()
    config = json.loads((ROOT / "upstream.json").read_text())
    branch = config["track"]
    if config["repository"] != OFFICIAL:
        raise ValueError("Only the official Proton source repository is supported")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", branch):
        raise ValueError("Unsupported branch name")
    sha = revision(
        config["commit"]
        if a.pinned
        else api("/repos/ProtonMail/android-mail/commits/" + branch)["sha"]
    )
    digest = module_digest()
    tag = "mailpush-" + sha[:12] + "-" + digest[:12]
    needed = True
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if repository:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        try:
            release = api("/repos/" + repository + "/releases/tags/" + tag)
            needed = bool(release.get("draft"))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    run = int(os.environ.get("GITHUB_RUN_NUMBER", "1"))
    code = config["base_version_code"] + run
    if not 1 <= code <= 2100000000:
        raise ValueError("versionCode range exceeded")
    data = {
        "upstream_commit": sha,
        "module_sha256": digest,
        "release_tag": tag,
        "version_code": code,
        "needed": needed,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(data, indent=2) + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            for name, value in data.items():
                out.write(name + "=" + str(value).lower() + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
