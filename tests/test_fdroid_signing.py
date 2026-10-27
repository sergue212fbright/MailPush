"""Trust-boundary tests; fixtures contain no real APK, repository key or mail.

The fdroidserver/JDK backends are mocked here to exercise rejection and secret
lifetime independently of tool availability. A real disposable-key protocol
proof is separate evidence, never inferred from these tests.
"""

from __future__ import annotations

import base64
from contextlib import ExitStack, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sign_fdroid as signer


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SigningFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.prepared = self.root / "prepared"
        self.repo = self.prepared / "site/fdroid/repo"
        self.repo.mkdir(parents=True)
        self.output = self.root / "signed"
        self.policy_folder = self.root / "policy"
        self.policy_folder.mkdir()
        self.public = b"SYNTHETIC PUBLIC CERTIFICATE, NOT AN X509 PRODUCTION IDENTITY" * 8
        self.policy = {
            "schema": 1, "repository": signer.REPOSITORY, "application_id": signer.APPLICATION_ID,
            "repo_url": signer.REPO_URL, "apk_certificate_sha256": signer.APK_CERTIFICATE,
            "repo_certificate_sha256": digest(self.public), "repo_name": "MailPush",
            "repo_description": "Synthetic test repository",
        }
        dump(self.policy_folder / "config.json", self.policy)
        (self.policy_folder / "repo-certificate.der").write_bytes(self.public)
        self.code = 1000003
        apk = f"{signer.APPLICATION_ID}_{self.code}.apk"
        source = f"{signer.APPLICATION_ID}_{self.code}_src.tar.gz"
        (self.repo / apk).write_bytes(b"SYNTHETIC APK BYTE FIXTURE, NOT INSTALLABLE")
        (self.repo / source).write_bytes(b"INERT CORRESPONDING-SOURCE FIXTURE, NEVER EXTRACTED")
        (self.repo / "icons").mkdir()
        (self.repo / "icons/icon.png").write_bytes(b"SYNTHETIC IMAGE BYTE FIXTURE")
        self.release = {
            "release_id": 123, "tag": "mailpush-" + "a" * 12 + "-" + "b" * 12,
            "upstream_commit": "a" * 40, "module_sha256": "b" * 64,
            "version_code": self.code,
            "apk_path": "fdroid/repo/" + apk, "apk_bytes": (self.repo / apk).stat().st_size,
            "apk_sha256": signer.sha256_file(self.repo / apk),
            "source_path": "fdroid/repo/" + source, "source_bytes": (self.repo / source).stat().st_size,
            "source_sha256": signer.sha256_file(self.repo / source),
        }
        timestamp = int(time.time() * 1000)
        self.v1 = {
            "repo": {"timestamp": timestamp, "name": self.policy["repo_name"],
                     "description": self.policy["repo_description"], "address": signer.REPO_URL,
                     "maxage": signer.INDEX_MAX_AGE_SECONDS},
            "requests": {"install": [], "uninstall": []},
            "apps": [{"packageName": signer.APPLICATION_ID, "allowedAPKSigningKeys": [signer.APK_CERTIFICATE],
                      "suggestedVersionCode": str(self.code)}],
            "packages": {signer.APPLICATION_ID: [{
                "packageName": signer.APPLICATION_ID, "versionCode": self.code,
                "signer": signer.APK_CERTIFICATE, "hashType": "sha256",
                "hash": self.release["apk_sha256"], "size": self.release["apk_bytes"],
                "apkName": apk, "srcname": source,
            }]},
        }
        self.v2 = {
            "repo": {"timestamp": timestamp, "name": {"en-US": self.policy["repo_name"]},
                     "description": {"en-US": self.policy["repo_description"]}, "address": signer.REPO_URL,
                     "icon": {"en-US": {"name": "/icons/icon.png", "size": (self.repo / "icons/icon.png").stat().st_size,
                                         "sha256": signer.sha256_file(self.repo / "icons/icon.png")}}},
            "packages": {signer.APPLICATION_ID: {
                "metadata": {"preferredSigner": signer.APK_CERTIFICATE},
                "versions": {self.release["apk_sha256"]: {
                    "manifest": {"versionCode": self.code, "signer": {"sha256": [signer.APK_CERTIFICATE]}},
                    "file": {"name": "/" + apk, "size": self.release["apk_bytes"], "sha256": self.release["apk_sha256"]},
                    "src": {"name": "/" + source, "size": self.release["source_bytes"], "sha256": self.release["source_sha256"]},
                }},
            }},
        }
        self.manifest = {
            "schema": 1, **{k: self.policy[k] for k in (
                "repository", "application_id", "repo_url", "apk_certificate_sha256", "repo_certificate_sha256")},
            "version_codes": [self.code], "releases": [self.release],
        }
        self.entry = {"timestamp": timestamp, "diffs": {}, "maxAge": signer.INDEX_MAX_AGE_SECONDS,
                      "index": {"name": "/index-v2.json", "numPackages": 1}}
        self.write_indices()
        self.tools = self.root / "sdk/build-tools/36.0.0"
        self.tools.mkdir(parents=True)
        for name in ("aapt", "apksigner"):
            (self.tools / name).write_text("synthetic tool path, never executed")

    def refresh_inventory(self):
        rows = [{"path": p.relative_to(self.prepared / "site").as_posix(), "bytes": p.stat().st_size,
                 "sha256": signer.sha256_file(p)}
                for p in sorted((self.prepared / "site").rglob("*")) if p.is_file()]
        self.manifest.update({"site_files": rows, "site_bytes": sum(r["bytes"] for r in rows)})
        dump(self.prepared / "manifest.json", self.manifest)

    def write_indices(self):
        dump(self.repo / "index-v1.json", self.v1)
        dump(self.repo / "index-v2.json", self.v2)
        self.entry["index"].update({"sha256": signer.sha256_file(self.repo / "index-v2.json"),
                                    "size": (self.repo / "index-v2.json").stat().st_size})
        dump(self.repo / "entry.json", self.entry)
        self.refresh_inventory()

    def validate(self):
        manifest, inventory = signer.validate_manifest(self.prepared, self.policy)
        signer.validate_indices(self.repo, manifest, inventory, self.policy)
        return manifest, inventory

    def mocked_tools(self):
        stack = ExitStack()
        stack.enter_context(mock.patch.object(signer.importlib.metadata, "version", return_value="2.4.5"))
        stack.enter_context(mock.patch.object(signer.shutil, "which", side_effect=lambda name, **_: "/trusted/bin/" + name))
        stack.enter_context(mock.patch.object(signer, "verify_parser_isolation", return_value={"synthetic_mock": True}))
        # Avoid requiring PyYAML or fdroidserver in the independent policy suite.
        yaml = SimpleNamespace(safe_dump=lambda data, stream, **_: stream.write(json.dumps(data)))
        stack.enter_context(mock.patch.dict(sys.modules, {"yaml": yaml}))
        return stack


class ManifestBoundaryTests(SigningFixture):
    def test_valid_single_application_chain(self):
        manifest, inventory = self.validate()
        self.assertEqual([1000003], manifest["version_codes"])
        self.assertEqual(6, len(inventory))

    def test_unknown_file_cannot_be_smuggled_through_a_complete_hash_manifest(self):
        (self.repo / "config.yml").write_text("not public")
        self.refresh_inventory()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_unlisted_file_is_rejected(self):
        (self.repo / "index.html").write_text("<script>untrusted</script>")
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_changed_file_hash_is_rejected(self):
        (self.repo / f"{signer.APPLICATION_ID}_{self.code}.apk").write_bytes(b"changed bytes")
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_size_total_and_policy_identity_are_checked(self):
        for field, bad in [("site_bytes", 650_000_001), ("schema", True),
                           ("application_id", "other.application.id"),
                           ("repo_url", "https://attacker.invalid/repo"),
                           ("repo_certificate_sha256", "0" * 64)]:
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = bad
                dump(self.prepared / "manifest.json", self.manifest)
                with self.assertRaises(signer.SigningError):
                    self.validate()
                self.manifest[field] = original

    def test_version_count_order_uniqueness_and_boolean_rejected(self):
        for codes in [[], [True], [1, 1], [1, 2], [4, 3, 2, 1], [2_100_000_001]]:
            with self.subTest(codes=codes):
                self.manifest["version_codes"] = codes
                dump(self.prepared / "manifest.json", self.manifest)
                with self.assertRaises(signer.SigningError):
                    self.validate()

    def test_manifest_canonical_paths_reject_traversal_and_aliases(self):
        for path in ["/fdroid/repo/entry.json", "fdroid/repo/../secret", "fdroid//repo/entry.json",
                     "fdroid/repo/./entry.json", "fdroid\\repo\\entry.json", "fdroid/repo/%2e%2e"]:
            with self.subTest(path=path), self.assertRaises(signer.SigningError):
                signer.allowed_public_path(path)

    def test_symlink_file_is_rejected(self):
        path = self.repo / "index-v1.json"
        other = self.root / "outside.json"
        path.rename(other)
        path.symlink_to(other)
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_symlink_directory_is_rejected(self):
        (self.prepared / "site/hidden").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_hardlink_file_is_rejected(self):
        os.link(self.repo / "index-v1.json", self.root / "another-name.json")
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_unknown_artifact_root_file_is_rejected(self):
        (self.prepared / "private-keystore").write_text("never accepted")
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_duplicate_json_keys_are_rejected(self):
        (self.prepared / "manifest.json").write_text('{"schema":1,"schema":1}')
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_release_provenance_must_bind_source_and_apk(self):
        self.release["tag"] = "mailpush-" + "c" * 12 + "-" + "b" * 12
        self.refresh_inventory()
        with self.assertRaises(signer.SigningError):
            self.validate()


class IndexBoundaryTests(SigningFixture):
    def test_entry_cannot_redirect_to_another_index_file(self):
        self.entry["index"]["name"] = "/../index-v2.json"
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_entry_index_hash_must_match_actual_file(self):
        self.entry["index"]["sha256"] = "0" * 64
        dump(self.repo / "entry.json", self.entry)
        self.refresh_inventory()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v1_signer_is_not_just_accepted_from_an_artifact_manifest(self):
        self.v1["packages"][signer.APPLICATION_ID][0]["signer"] = "0" * 64
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v1_cannot_request_install_or_uninstall(self):
        self.v1["requests"]["uninstall"] = [signer.APPLICATION_ID]
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v2_cannot_request_install_or_uninstall(self):
        self.v2["repo"]["requests"] = {"install": [], "uninstall": ["other.installed.application"]}
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_obb_downloads_are_rejected_in_both_index_formats(self):
        self.v1["packages"][signer.APPLICATION_ID][0]["obbMainFile"] = "outside.obb"
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()
        del self.v1["packages"][signer.APPLICATION_ID][0]["obbMainFile"]
        version = next(iter(self.v2["packages"][signer.APPLICATION_ID]["versions"].values()))
        version["obbMainFile"] = {"name": "/../outside.obb", "sha256": "0" * 64, "size": 1}
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_unknown_v2_file_descriptor_cannot_reference_external_content(self):
        metadata = self.v2["packages"][signer.APPLICATION_ID]["metadata"]
        metadata["screenshots"] = {"en-US": {"phone": [{"name": "https://attacker.invalid/track.png",
                                                         "sha256": "0" * 64, "size": 1}]}}
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_ipfs_file_override_is_not_a_second_download_source(self):
        version = next(iter(self.v2["packages"][signer.APPLICATION_ID]["versions"].values()))
        version["file"]["ipfsCIDv1"] = "untrusted-ipfs-identifier"
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v1_suggested_version_cannot_downgrade(self):
        self.v1["apps"][0]["suggestedVersionCode"] = "1000002"
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v2_cannot_add_a_second_application(self):
        self.v2["packages"]["unrelated.application.id"] = {}
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v2_apk_path_and_source_hash_are_verified(self):
        package = next(iter(self.v2["packages"][signer.APPLICATION_ID]["versions"].values()))
        package["src"]["sha256"] = "0" * 64
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_v2_icon_hash_is_verified(self):
        self.v2["repo"]["icon"]["en-US"]["sha256"] = "0" * 64
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_future_timestamp_is_rejected(self):
        self.v1["repo"]["timestamp"] = self.v2["repo"]["timestamp"] = self.entry["timestamp"] = int((time.time() + 86400) * 1000)
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()

    def test_stale_preparation_and_unbounded_index_lifetime_are_rejected(self):
        self.entry["maxAge"] = 365 * 86400
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()
        self.entry["maxAge"] = signer.INDEX_MAX_AGE_SECONDS
        self.v1["repo"]["timestamp"] = self.v2["repo"]["timestamp"] = self.entry["timestamp"] = int((time.time() - 7200) * 1000)
        self.write_indices()
        with self.assertRaises(signer.SigningError):
            self.validate()


class SecretBoundaryTests(SigningFixture):
    def test_runtime_isolation_receipt_is_checked_not_just_command_arguments(self):
        expected = {"uid": 65534, "gid": 65534, "pid": 1, "parent_pid": 0, "capabilities": "none",
                    "no_new_privileges": True, "network_interfaces": ["lo"], "fdroidserver": "2.4.5"}
        with mock.patch.object(signer, "isolated_command", return_value=json.dumps(expected).encode()):
            self.assertEqual(expected, signer.verify_parser_isolation({"PATH": "/trusted/bin"}, self.root))
        expected["uid"] = 0
        with mock.patch.object(signer, "isolated_command", return_value=json.dumps(expected).encode()):
            with self.assertRaises(signer.SigningError):
                signer.verify_parser_isolation({"PATH": "/trusted/bin"}, self.root)

    def test_parser_environment_never_fetches_or_passes_secret_values(self):
        class Values(dict):
            def __getitem__(self, name):
                if name not in signer.SAFE_ENVIRONMENT:
                    raise AssertionError("Secret value was accessed")
                return super().__getitem__(name)
        env = Values(PATH="/trusted/bin", HOME="/private-home", FDROID_KEYSTORE_BASE64="private",
                     FDROID_KEYSTORE_PASSWORD="private", GH_TOKEN="private", GITHUB_TOKEN="private",
                     SIGNING_PASSWORD="private", JAVA_TOOL_OPTIONS="untrusted-agent", CODEX_APPS_AUTHORIZATION="private")
        self.assertEqual({"PATH": "/trusted/bin", "HOME": "/private-home"}, signer.clean_environment(env))

    def test_bad_preparation_never_reads_signing_material(self):
        (self.repo / "entry.json").write_text("damaged")
        with mock.patch.object(signer, "signing_material") as key:
            with self.assertRaises(signer.SigningError):
                signer.sign_repository(self.prepared, self.output, self.tools, policy_folder=self.policy_folder)
            key.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_bad_apk_never_reads_signing_material(self):
        with self.mocked_tools(), mock.patch.object(signer, "verify_apk", side_effect=signer.SigningError("Rejected APK")), \
                mock.patch.object(signer, "signing_material") as key:
            with self.assertRaises(signer.SigningError):
                signer.sign_repository(self.prepared, self.output, self.tools, policy_folder=self.policy_folder)
            key.assert_not_called()

    def test_apk_auditors_receive_only_clean_environment(self):
        seen = []
        def backend(arguments, env, **_):
            seen.append((arguments, env))
            if any(Path(arg).name == "apksigner" for arg in arguments):
                return b"Signer #1 certificate SHA-256 digest: " + signer.APK_CERTIFICATE.encode() + b"\n"
            return json.dumps({"application_id": signer.APPLICATION_ID, "version_code": self.code, "manifest_policy": "passed"}).encode()
        with mock.patch.object(signer, "command", side_effect=backend), \
                mock.patch.object(signer.shutil, "which", side_effect=lambda name, **_: "/trusted/bin/" + name):
            signer.verify_apk(self.repo / "synthetic.apk", self.code, self.tools, {"PATH": "/trusted/bin"})
        self.assertEqual(2, len(seen))
        self.assertTrue(all(env == {} for _, env in seen))
        self.assertTrue(all("sign" not in args for args, _ in seen))
        for args, _ in seen:
            for required in ("--pid", "--mount-proc", "--net", "--reuid=65534", "--regid=65534", "--no-new-privs", "--clear-groups"):
                self.assertIn(required, args)
            self.assertIn("PATH=/trusted/bin", args)

    def test_isolation_failure_never_reads_key_or_falls_back(self):
        with self.mocked_tools(), mock.patch.object(signer, "verify_parser_isolation", side_effect=signer.SigningError("Isolation unavailable")), \
                mock.patch.object(signer, "signing_material") as key:
            with self.assertRaises(signer.SigningError):
                signer.sign_repository(self.prepared, self.output, self.tools, policy_folder=self.policy_folder)
            key.assert_not_called()

    def test_verify_only_produces_receipt_without_key_or_signed_site(self):
        with self.mocked_tools(), mock.patch.object(signer, "verify_apk") as apk, \
                mock.patch.object(signer, "signing_material") as key:
            result = signer.sign_repository(self.prepared, self.output, self.tools,
                                             policy_folder=self.policy_folder, verify_only=True)
        key.assert_not_called()
        apk.assert_called_once()
        self.assertEqual("preflight_verified", result["status"])
        self.assertFalse(result["signed_site_created"])
        self.assertFalse((self.output / "site").exists())
        self.assertTrue((self.output / "manifest.json").is_file())

    def test_wrong_private_identity_never_signs_or_publishes(self):
        paths = []
        def backend(arguments, env, **_):
            self.assertEqual("-exportcert", arguments[1])
            keyfile = Path(arguments[arguments.index("-keystore") + 1])
            paths.append(keyfile)
            self.assertEqual(0o600, keyfile.stat().st_mode & 0o777)
            return b"WRONG PUBLIC CERTIFICATE"
        with self.mocked_tools(), mock.patch.object(signer, "verify_apk"), \
                mock.patch.object(signer, "signing_material", return_value=(b"SYNTHETIC TEST KEY" * 20, "SYNTHETIC-PASSWORD")), \
                mock.patch.object(signer, "command", side_effect=backend):
            with self.assertRaises(signer.SigningError):
                signer.sign_repository(self.prepared, self.output, self.tools, policy_folder=self.policy_folder)
        self.assertFalse(self.output.exists())
        self.assertTrue(paths and all(not p.exists() for p in paths))

    def test_signed_site_contains_no_key_config_or_status_and_apk_is_unchanged(self):
        calls, workdirs = [], []
        def backend(arguments, env, *, cwd=None, **_):
            self.assertFalse(set(env) - signer.SAFE_ENVIRONMENT)
            if "-exportcert" in arguments:
                calls.append("certificate")
                return self.public
            if arguments[1:4] == ["-m", "fdroidserver", "signindex"]:
                calls.append("signindex")
                workdirs.append(cwd)
                self.assertEqual(0o600, (cwd / "config.yml").stat().st_mode & 0o777)
                for name in signer.SIGNED_FILES:
                    with zipfile.ZipFile(cwd / "repo" / name, "w") as jar:
                        payload = name.replace(".jar", ".json")
                        jar.write(cwd / "repo" / payload, payload)
                        jar.writestr("META-INF/MANIFEST.MF", "SYNTHETIC MANIFEST")
                        jar.writestr("META-INF/FDROIDRE.RSA", "SYNTHETIC SIGNATURE FIXTURE")
                (cwd / "repo/status").mkdir()
                (cwd / "repo/status/signindex.json").write_text("not published")
                return b""
            self.assertIn("-c", arguments)
            calls.append("public verification")
            for private in ("config.yml", "private-password", "private-keystore"):
                self.assertFalse((cwd / private).exists())
            return json.dumps({"v1_signature_and_pin": "passed", "v2_entry_signature_and_pin": "passed"}).encode()
        def apk(*_):
            calls.append("APK verified")
        def key():
            self.assertEqual(["APK verified"], calls)
            calls.append("key read")
            return b"SYNTHETIC TEST KEY" * 20, "SYNTHETIC-PASSWORD"
        with self.mocked_tools(), mock.patch.object(signer, "verify_apk", side_effect=apk), \
                mock.patch.object(signer, "signing_material", side_effect=key), \
                mock.patch.object(signer, "command", side_effect=backend):
            receipt = signer.sign_repository(self.prepared, self.output, self.tools, policy_folder=self.policy_folder)
        self.assertEqual(["APK verified", "key read", "certificate", "signindex", "public verification"], calls)
        files = signer.scan_tree(self.output / "site")
        self.assertEqual(9, len(files))
        self.assertTrue(all(n.startswith("fdroid/repo/") for n in files))
        self.assertFalse(any("status" in n or "private" in n or n.endswith(".yml") for n in files))
        self.assertEqual(self.release["apk_sha256"], signer.sha256_file(self.output / "site" / self.release["apk_path"]))
        self.assertFalse(receipt["apk_resigned"])
        self.assertTrue(all(not p.exists() for p in workdirs))

    def test_cli_never_logs_backend_exception_or_key_values(self):
        stderr = io.StringIO()
        arguments = ["sign_fdroid.py", "--input", "prepared", "--output", "signed", "--build-tools", "tools"]
        with mock.patch.object(sys, "argv", arguments), mock.patch.object(signer, "sign_repository", side_effect=ValueError("SYNTHETIC-PRIVATE-PASSWORD")), redirect_stderr(stderr):
            self.assertEqual(1, signer.main())
        self.assertNotIn("SYNTHETIC-PRIVATE-PASSWORD", stderr.getvalue())
        self.assertIn("ValueError", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
