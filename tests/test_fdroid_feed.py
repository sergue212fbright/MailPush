"""Trust-boundary tests for public binary-feed preparation; no network or keys."""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_fdroid import (AssetRedirect, FeedError, GitHubDownloads, checksums, clean_environment, load_policy,
                           newest_unique, public_path, release_assets,
                           site_manifest, validate_release, validate_url)


REPOSITORY = "owner/MailPush"
APP = "ch.protonmail.android.mailpush"
UPSTREAM = "a" * 40
MODULE = "b" * 64
TAG = "mailpush-" + UPSTREAM[:12] + "-" + MODULE[:12]
POLICY = {"schema": 1, "repository": REPOSITORY, "application_id": APP,
          "apk_certificate_sha256": "c" * 64, "repo_certificate_sha256": "d" * 64,
          "repo_url": "https://owner.github.io/MailPush/fdroid/repo",
          "repo_name": "MailPush", "repo_description": "Synthetic fixture"}


def release_fixture(code=1000003):
    apk, source = b"synthetic signed APK placeholder", b"synthetic inert source archive"
    metadata = {"schema": 1, "application_id": APP, "version_code": code, "upstream_commit": UPSTREAM,
                "module_sha256": MODULE, "release_tag": TAG, "manifest_policy": "passed",
                "apk_sha256": hashlib.sha256(apk).hexdigest(), "apk_bytes": len(apk)}
    data = {"MailPush.apk": apk, "source.tar.gz": source,
            "release.json": json.dumps(metadata).encode()}
    sums = "".join(hashlib.sha256(value).hexdigest() + "  " + name + "\n"
                   for name, value in data.items()).encode()
    data["SHA256SUMS"] = sums
    release = {"id": 123, "tag_name": TAG, "name": "MailPush build " + str(code),
               "draft": False, "author": {"login": "github-actions[bot]"},
               "assets": [{"name": name, "size": len(value), "state": "uploaded",
                           "digest": "sha256:" + hashlib.sha256(value).hexdigest(),
                           "browser_download_url": "https://github.com/" + REPOSITORY +
                           "/releases/download/" + TAG + "/" + name}
                          for name, value in data.items()]}
    return release, data


class FeedPolicyTests(unittest.TestCase):
    def policy(self, changes=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "policy.json"
            path.write_text(json.dumps({**POLICY, **(changes or {})}))
            return load_policy(path)

    def test_distinct_pinned_index_and_apk_identities(self):
        self.assertEqual(APP, self.policy()["application_id"])
        with self.assertRaises(FeedError):
            self.policy({"repo_certificate_sha256": POLICY["apk_certificate_sha256"]})

    def test_unknown_policy_fields_and_foreign_pages_origin_rejected(self):
        for changes in ({"command": "anything"}, {"repo_url": "https://evil.test/fdroid/repo"},
                        {"repo_url": "http://owner.github.io/MailPush/fdroid/repo"},
                        {"apk_certificate_sha256": "not a fingerprint"}):
            with self.subTest(changes=changes), self.assertRaises(FeedError):
                self.policy(changes)

    def test_metadata_or_archive_paths_are_not_public_files(self):
        for path in ("config.yml", "../key.p12", "index.xml", "index_unsigned.jar",
                     "index.html", "cache/apkcache.json", "icons/secret.js", "icons/../../key.p12"):
            self.assertFalse(public_path(path, APP), path)
        self.assertTrue(public_path(APP + "_1000003.apk", APP))
        self.assertTrue(public_path(APP + "_1000003_src.tar.gz", APP))
        self.assertTrue(public_path("icons-640/" + APP + ".1000003.png", APP))

    def test_manifest_rejects_symlinks_hardlinks_and_unknown_files(self):
        for kind in ("symlink", "hardlink", "unexpected"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                site = Path(folder) / "site"
                repo = site / "fdroid/repo"
                repo.mkdir(parents=True)
                external = Path(folder) / "private"
                external.write_text("not public")
                destination = repo / "entry.json"
                if kind == "symlink":
                    destination.symlink_to(external)
                elif kind == "hardlink":
                    destination.hardlink_to(external)
                else:
                    (repo / "config.yml").write_text("private setting")
                with self.assertRaises(FeedError):
                    site_manifest(site, POLICY)


class DownloadBoundaryTests(unittest.TestCase):
    def test_read_only_token_is_sent_only_to_the_repository_api(self):
        download = GitHubDownloads(REPOSITORY)
        with patch.dict(os.environ, {"GH_TOKEN": "synthetic-api-token"}, clear=True), \
                patch.object(download.opener, "open", return_value=io.BytesIO(b"[]")) as opened:
            download.response("https://api.github.com/repos/owner/MailPush/releases")
            self.assertEqual("Bearer synthetic-api-token", opened.call_args.args[0].get_header("Authorization"))
            download.response("https://github.com/owner/MailPush/releases/download/tag/release.json")
            self.assertIsNone(opened.call_args.args[0].get_header("Authorization"))

    def test_temporary_http_failure_retries_the_original_approved_url(self):
        download = GitHubDownloads(REPOSITORY)
        url = "https://api.github.com/repos/owner/MailPush/releases"
        error = urllib.error.HTTPError(url, 503, "untrusted remote text", {}, io.BytesIO(b"private body"))
        response = io.BytesIO(b"[]")
        with patch.object(download.opener, "open", side_effect=[error, response]) as opened, \
                patch("prepare_fdroid.time.sleep") as sleep:
            self.assertIs(response, download.response(url))
            self.assertEqual(2, opened.call_count)
            self.assertTrue(all(call.args[0].full_url == url for call in opened.call_args_list))
            sleep.assert_called_once_with(1)

    def test_newly_published_asset_can_retry_but_api_not_found_is_permanent(self):
        download = GitHubDownloads(REPOSITORY)
        for api in (False, True):
            url = ("https://api.github.com/repos/owner/MailPush/releases" if api else
                   "https://github.com/owner/MailPush/releases/download/tag/release.json")
            error = urllib.error.HTTPError(url, 404, "not found", {}, io.BytesIO())
            with self.subTest(api=api), patch.object(download.opener, "open", side_effect=[error, io.BytesIO(b"ok")]) as opened, \
                    patch("prepare_fdroid.time.sleep"):
                if api:
                    with self.assertRaisesRegex(FeedError, "GitHub API returned HTTP 404"):
                        download.response(url)
                    self.assertEqual(1, opened.call_count)
                else:
                    self.assertEqual(b"ok", download.response(url).read())
                    self.assertEqual(2, opened.call_count)

    def test_http_failures_do_not_disclose_signed_urls_headers_or_bodies(self):
        download = GitHubDownloads(REPOSITORY)
        url = "https://api.github.com/repos/owner/MailPush/releases"
        error = urllib.error.HTTPError("https://release-assets.githubusercontent.com/file?secret=DO-NOT-LOG",
            403, "DO-NOT-LOG", {"X-RateLimit-Remaining": "0", "Authorization": "DO-NOT-LOG"}, io.BytesIO(b"DO-NOT-LOG"))
        with patch.object(download.opener, "open", side_effect=error) as opened:
            with self.assertRaisesRegex(FeedError, "GitHub API returned HTTP 403 .*rate limited") as caught:
                download.response(url)
            self.assertNotIn("DO-NOT-LOG", str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
            self.assertEqual(1, opened.call_count)

    def test_http_retry_count_and_requested_wait_are_bounded(self):
        download = GitHubDownloads(REPOSITORY)
        url = "https://api.github.com/repos/owner/MailPush/releases"
        failures = [urllib.error.HTTPError(url, 502, "bad gateway", {}, io.BytesIO()) for _ in range(3)]
        with patch.object(download.opener, "open", side_effect=failures) as opened, patch("prepare_fdroid.time.sleep") as sleep:
            with self.assertRaisesRegex(FeedError, "HTTP 502"):
                download.response(url)
            self.assertEqual(3, opened.call_count)
            self.assertEqual([1, 2], [call.args[0] for call in sleep.call_args_list])
        for requested in ("31", "Wed, 18 Nov 2026 22:00:00 GMT", "untrusted"):
            error = urllib.error.HTTPError(url, 503, "wait", {"Retry-After": requested}, io.BytesIO())
            with self.subTest(requested=requested), patch.object(download.opener, "open", side_effect=error) as opened, \
                    patch("prepare_fdroid.time.sleep") as sleep:
                with self.assertRaises(FeedError):
                    download.response(url)
                self.assertEqual(1, opened.call_count)
                sleep.assert_not_called()

    def test_http_retry_honors_short_retry_after_and_global_deadline(self):
        download = GitHubDownloads(REPOSITORY)
        url = "https://api.github.com/repos/owner/MailPush/releases"
        error = urllib.error.HTTPError(url, 503, "wait", {"Retry-After": "4"}, io.BytesIO())
        with patch.object(download.opener, "open", side_effect=[error, io.BytesIO()]), patch("prepare_fdroid.time.sleep") as sleep:
            download.response(url)
            sleep.assert_called_once_with(4)
        download.deadline = 10
        with patch("prepare_fdroid.time.monotonic", return_value=10), patch.object(download.opener, "open") as opened:
            with self.assertRaisesRegex(FeedError, "time budget exceeded"):
                download.response(url)
            opened.assert_not_called()

    def test_subprocess_environment_does_not_contain_ambient_credentials(self):
        with patch.dict(os.environ, {"GH_TOKEN": "synthetic", "CODEX_APPS_AUTHORIZATION": "synthetic",
                                     "FDROID_PASSWORD": "synthetic", "HTTPS_PROXY": "https://example.test"}):
            env = clean_environment()
            self.assertFalse({"GH_TOKEN", "CODEX_APPS_AUTHORIZATION", "FDROID_PASSWORD", "HTTPS_PROXY"} & env.keys())
            self.assertIn("PATH", env)

    def test_asset_size_or_hash_mismatch_is_rejected(self):
        download = GitHubDownloads(REPOSITORY)
        for size, digest in ((2, hashlib.sha256(b"abc").hexdigest()), (3, "a" * 64)):
            with self.subTest(size=size), tempfile.TemporaryDirectory() as folder:
                with patch.object(download, "response", return_value=io.BytesIO(b"abc")):
                    with self.assertRaises(FeedError):
                        download.file("unused in fixture", Path(folder) / "asset", size, digest)

    def test_oversized_metadata_is_rejected(self):
        download = GitHubDownloads(REPOSITORY)
        with patch.object(download, "response", return_value=io.BytesIO(b"too much")):
            with self.assertRaises(FeedError):
                download.small("unused in fixture", 3)

    def test_only_this_repository_and_approved_https_cdns(self):
        validate_url("https://api.github.com/repos/owner/MailPush/releases?per_page=100", REPOSITORY)
        validate_url("https://release-assets.githubusercontent.com/a?token=short-lived", REPOSITORY, redirect=True)
        for url in ("http://github.com/owner/MailPush/releases/download/tag/file", "file:///etc/passwd",
                    "https://api.github.com/repos/someone/Other/releases", "https://evil.test/file",
                    "https://api.github.com/repos/owner/MailPush/../../Other/releases",
                    "https://api.github.com/repos/owner/MailPush/%2e%2e/private",
                    "https://github.com@evil.test/owner/MailPush/releases/download/tag/file",
                    "https://github.com:8443/owner/MailPush/releases/download/tag/file"):
            with self.subTest(url=url), self.assertRaises(FeedError):
                validate_url(url, REPOSITORY, redirect=True)

    def test_redirect_does_not_forward_authentication_to_cdn(self):
        request = urllib.request.Request("https://api.github.com/repos/owner/MailPush/releases",
            headers={"Authorization": "Bearer synthetic-token", "Cookie": "synthetic-cookie",
                     "Proxy-Authorization": "synthetic-proxy", "User-Agent": "MailPush"})
        redirected = AssetRedirect(REPOSITORY).redirect_request(request, None, 302, "", {},
            "https://release-assets.githubusercontent.com/example?signature=temporary")
        headers = {key.lower(): value for key, value in redirected.headers.items()}
        self.assertFalse({"authorization", "cookie", "proxy-authorization"} & headers.keys())
        self.assertEqual("MailPush", headers["user-agent"])


class ReleaseBoundaryTests(unittest.TestCase):
    def verified(self, release=None, data=None):
        fixture, files = release_fixture()
        release, data = release or fixture, data or files
        assets = release_assets(release, REPOSITORY)
        return validate_release(release, assets, data["release.json"], data["SHA256SUMS"], POLICY)

    def test_correct_automated_release_metadata_is_accepted(self):
        self.assertEqual(1000003, self.verified()["version_code"])

    def test_checksum_traversal_duplicate_and_missing_coverage_rejected(self):
        _, data = release_fixture()
        for value in (data["SHA256SUMS"] + b"a" * 64 + b"  ../key.p12\n",
                      data["SHA256SUMS"] * 2,
                      b"\n".join(data["SHA256SUMS"].splitlines()[:2])):
            with self.subTest(value=value), self.assertRaises(FeedError):
                checksums(value)

    def test_foreign_author_asset_url_and_extra_assets_rejected(self):
        release, _ = release_fixture()
        release["author"]["login"] = "another-publisher"
        with self.assertRaises(FeedError):
            release_assets(release, REPOSITORY)
        release, _ = release_fixture()
        release["assets"][0]["browser_download_url"] = "https://evil.test/MailPush.apk"
        with self.assertRaises(FeedError):
            release_assets(release, REPOSITORY)
        release, _ = release_fixture()
        release["assets"].append({"name": "config.yml"})
        with self.assertRaises(FeedError):
            release_assets(release, REPOSITORY)

    def test_metadata_tampering_and_github_digest_mismatch_rejected(self):
        release, data = release_fixture()
        data["release.json"] += b" "
        with self.assertRaises(FeedError):
            self.verified(release, data)
        release, data = release_fixture()
        release["assets"][0]["digest"] = "sha256:" + "e" * 64
        with self.assertRaises(FeedError):
            self.verified(release, data)

    def test_actual_metadata_version_is_sorted_and_deduplicated(self):
        releases = []
        for code in (1000004, 1000002, 1000005, 1000003, 1000005):
            release, data = release_fixture(code)
            releases.append(validate_release(release, release_assets(release, REPOSITORY),
                data["release.json"], data["SHA256SUMS"], POLICY))
        self.assertEqual([1000005, 1000004, 1000003], [r["version_code"] for r in newest_unique(releases)])

    def test_conflicting_version_code_and_oversize_feed_rejected(self):
        first = self.verified()
        with self.assertRaises(FeedError):
            newest_unique([first, {**first, "apk_sha256": "f" * 64}])
        with self.assertRaises(FeedError):
            newest_unique([{**first, "apk_bytes": 650_000_000}])


if __name__ == "__main__":
    unittest.main()
