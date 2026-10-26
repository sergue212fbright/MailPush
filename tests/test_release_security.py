"""Negative tests for boundaries that can otherwise publish an unsafe build.

These are policy tests, not a replacement for compiling the real Proton fork or
testing a real Android Keystore. All mail/paths/certificates here are synthetic.
"""

import hashlib, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_apk import audit
from prepare_upstream import (
    revision, version_code, PreparationError, assert_no_sentry_build_plugins, apply_overlay,
)
from notify_failure import address, build_message, send
from upstream_check import module_digest
import publish_release

BADGING = (
    "package: name='ch.protonmail.android.mailpush' versionCode='1000001' versionName='7.12.0'\n"
)
XML = """E: manifest
  E: application
    A: android:allowBackup(0x01010280)=(type 0x12)0x0
    A: android:usesCleartextTraffic(0x010104ec)=(type 0x12)0x0
    E: profileable
      A: android:shell(0x01010554)=(type 0x12)0x0
    E: service
      A: android:name(0x01010003)="app.mailpush.companion.MailPushService"
      A: android:exported(0x01010010)=(type 0x12)0x0
    E: service
      A: android:name(0x01010003)="ch.protonmail.android.PMFirebaseMessagingService"
      A: android:enabled(0x0101000e)=(type 0x12)0x0
      A: android:exported(0x01010010)=(type 0x12)0x0
"""
ENV = {
    "MAIL_FROM": "builds@example.test",
    "MAIL_TO": "owner@example.test",
    "MAIL_HOST": "smtp.example.test",
    "MAIL_USER": "synthetic-user",
    "MAIL_PASSWORD": "synthetic-password",
    "GITHUB_REPOSITORY": "owner/mailpush",
    "GITHUB_RUN_ID": "12345",
}


class ManifestTests(unittest.TestCase):
    def check(self, badging=BADGING, xml=XML):
        with tempfile.TemporaryDirectory() as folder:
            apk = Path(folder) / "app.apk"
            apk.write_bytes(b"synthetic")
            with patch("audit_apk.subprocess.check_output", side_effect=[badging, xml]):
                return audit(apk, Path("aapt"), "ch.protonmail.android.mailpush", 1000001)

    def test_valid_policy(self):
        self.assertEqual("passed", self.check()["manifest_policy"])

    def test_wrong_package(self):
        with self.assertRaises(ValueError):
            self.check(BADGING.replace(".mailpush", ""))

    def test_wrong_code(self):
        with self.assertRaises(ValueError):
            self.check(BADGING.replace("1000001", "1000002"))

    def test_debuggable(self):
        with self.assertRaises(ValueError):
            self.check(BADGING + "application-debuggable\n")

    def test_advertising_permission(self):
        with self.assertRaises(ValueError):
            self.check(
                BADGING + "uses-permission: name='com.google.android.gms.permission.AD_ID'\n"
            )

    def test_cleartext_not_explicitly_disabled(self):
        with self.assertRaises(ValueError):
            self.check(xml=XML.replace("android:usesCleartextTraffic", "android:other"))

    def test_backups_enabled(self):
        with self.assertRaises(ValueError):
            self.check(
                xml=XML.replace(
                    "android:allowBackup(0x01010280)=(type 0x12)0x0",
                    "android:allowBackup(0x01010280)=(type 0x12)0xffffffff",
                )
            )

    def test_exported_receiver(self):
        with self.assertRaises(ValueError):
            self.check(
                xml=XML.replace(
                    "android:exported(0x01010010)=(type 0x12)0x0",
                    "android:exported(0x01010010)=(type 0x12)0xffffffff",
                    1,
                )
            )

    def test_shell_profiling_enabled(self):
        with self.assertRaises(ValueError):
            self.check(
                xml=XML.replace(
                    "android:shell(0x01010554)=(type 0x12)0x0",
                    "android:shell(0x01010554)=(type 0x12)0xffffffff",
                )
            )

    def test_fcm_enabled(self):
        with self.assertRaises(ValueError):
            self.check(
                xml=XML.replace(
                    "android:enabled(0x0101000e)=(type 0x12)0x0",
                    "android:enabled(0x0101000e)=(type 0x12)0xffffffff",
                )
            )

    def test_firebase_provider(self):
        with self.assertRaises(ValueError):
            self.check(
                xml=XML
                + '    E: provider\n      A: android:name="com.google.firebase.provider.FirebaseInitProvider"\n'
            )

    def test_sentry_automatic_providers(self):
        for name in ["SentryInitProvider", "SentryPerformanceProvider"]:
            with self.subTest(provider=name), self.assertRaises(ValueError):
                self.check(xml=XML + '    E: provider\n      A: android:name="io.sentry.android.core.' + name + '"\n')

    def test_component_indentation_is_not_hard_coded(self):
        self.assertEqual(
            "passed", self.check(xml=XML.replace("    ", "        "))["manifest_policy"]
        )


class InputTests(unittest.TestCase):
    def test_revision_is_commit_not_shell_or_branch(self):
        for value in ["main", "a" * 39, "A" * 40, "a" * 40 + "\n", "$(true)", "--upload-pack=bad"]:
            with self.assertRaises(PreparationError):
                revision(value)
        self.assertEqual("a" * 40, revision("a" * 40))

    def test_version_code_bounds(self):
        for value in [True, 0, -1, 2100000001, "1"]:
            with self.assertRaises(PreparationError):
                version_code(value)

    def test_source_digest_ignores_advanced_pin_but_not_code(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "modules").mkdir()
            code = root / "modules/receiver.java"
            code.write_text("one")
            policy = {
                "repository": "ProtonMail/android-mail",
                "track": "main",
                "application_id": "ch.protonmail.android.mailpush",
                "base_version_code": 1000000,
                "commit": "a" * 40,
            }
            config = root / "upstream.json"
            config.write_text(json.dumps(policy))
            first = module_digest(root)
            policy["commit"] = "b" * 40
            config.write_text(json.dumps(policy))
            self.assertEqual(first, module_digest(root))
            code.write_text("two")
            self.assertNotEqual(first, module_digest(root))
            code.write_text("one")
            (root / "config").mkdir()
            (root / "config/policy.yml").write_text("policy")
            self.assertNotEqual(first, module_digest(root))


class BuildPluginPrivacyTests(unittest.TestCase):
    def check(self, root_script="", app_script=""):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "app").mkdir()
            (root / "build.gradle.kts").write_text(root_script)
            (root / "app/build.gradle.kts").write_text(app_script)
            assert_no_sentry_build_plugins(root)

    def test_applied_plugin_is_rejected_in_either_script(self):
        for declaration in [
            'plugins { id("io.sentry.android.gradle") }',
            'apply(plugin = "io.sentry.android.gradle")',
            'plugins { id("io.sentry.jvm.gradle") }',
        ]:
            for position in ["root_script", "app_script"]:
                with self.subTest(declaration=declaration, position=position):
                    with self.assertRaises(PreparationError):
                        self.check(**{position: declaration})

    def test_catalog_build_classpath_is_rejected(self):
        with self.assertRaises(PreparationError):
            self.check('buildscript { dependencies { classpath(libs.sentry.gradle) } }')

    def test_literal_build_classpath_is_rejected(self):
        with self.assertRaises(PreparationError):
            self.check('buildscript { dependencies { classpath("io.sentry:sentry-android-gradle-plugin:5.12.2") } }')

    def test_split_catalog_accessor_cannot_hide_after_comments(self):
        with self.assertRaises(PreparationError):
            self.check('buildscript { dependencies { classpath(libs /* note */ . sentry . gradle) } }')

    def test_find_library_and_plugin_alias_are_rejected(self):
        for declaration in [
            'classpath(libs.findLibrary("sentry-gradle").get())',
            'plugins { alias(libs.plugins.sentry.android.gradle) }',
        ]:
            with self.subTest(declaration=declaration), self.assertRaises(PreparationError):
                self.check(app_script=declaration)

    def test_urls_do_not_hide_applied_plugin_later_on_same_line(self):
        with self.assertRaises(PreparationError):
            self.check(app_script='val url = "https://example.test"; apply(plugin = "io.sentry.android.gradle")')

    def test_runtime_only_api_dependencies_and_removal_comments_are_allowed(self):
        self.check(
            root_script='// Removed classpath(libs.sentry.gradle)\nplugins { id("com.android.application") }',
            app_script='''
                /* Removed id("io.sentry.android.gradle").
                   /* Nested Kotlin comment: io.sentry:sentry-android-gradle-plugin */
                */
                val sentryDSN = ""
                val url = "https://example.test"
                dependencies {
                    implementation("io.sentry:sentry-android-core:8.37.1")
                    implementation("io.sentry:sentry-android-timber:8.37.1")
                    implementation(libs.sentry)
                }
            ''',
        )

    def test_incomplete_build_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(OSError):
                assert_no_sentry_build_plugins(Path(name))

    def test_preparation_never_marks_unsafe_tree_ready(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "app").mkdir()
            (root / "build.gradle.kts").write_text('buildscript { dependencies { classpath(libs.sentry.gradle) } }')
            (root / "app/build.gradle.kts").write_text('plugins { id("com.android.application") }')
            # Simulate a patch whose context still applies but fails to remove
            # the build dependency. Real overlay copies and the final guard run.
            def fake_git(*arguments, **kwargs):
                return "a" * 40 if arguments[:2] == ("rev-parse", "HEAD") else ""
            with patch("prepare_upstream.git", side_effect=fake_git):
                with self.assertRaises(PreparationError):
                    apply_overlay(root, "a" * 40, 1000001, "ch.protonmail.android.mailpush")
            self.assertFalse((root / ".mailpush-prepared.json").exists())


class EmailTests(unittest.TestCase):
    def test_header_injection_rejected(self):
        for value in ["owner@example.test\r\nBcc: other@example.test", "missing-domain", ""]:
            with self.assertRaises(ValueError):
                address(value)

    def test_minimal_failure_notice(self):
        message = build_message(ENV)
        body = message.get_content()
        self.assertIn("https://github.com/owner/mailpush/actions/runs/12345", body)
        self.assertNotIn(ENV["MAIL_PASSWORD"], body)
        self.assertNotIn(ENV["MAIL_USER"], body)

    def test_ssl_verifies_certificates(self):
        with patch("notify_failure.smtplib.SMTP_SSL") as smtp:
            send(ENV)
            context = smtp.call_args.kwargs["context"]
            self.assertTrue(context.check_hostname)
            self.assertEqual(2, context.verify_mode)
            smtp.return_value.__enter__.return_value.login.assert_not_called()
            # The same object is used inside the context; no fallback client exists.
            smtp.return_value.login.assert_called_once_with(ENV["MAIL_USER"], ENV["MAIL_PASSWORD"])

    def test_starttls_precedes_authentication(self):
        client = MagicMock()
        with patch("notify_failure.smtplib.SMTP", return_value=client):
            send({**ENV, "MAIL_MODE": "starttls", "MAIL_PORT": "587"})
        names = [c[0] for c in client.method_calls]
        self.assertLess(names.index("starttls"), names.index("login"))

    def test_tls_failure_never_logs_in(self):
        client = MagicMock()
        client.starttls.side_effect = OSError("synthetic handshake failure")
        with patch("notify_failure.smtplib.SMTP", return_value=client):
            with self.assertRaises(OSError):
                send({**ENV, "MAIL_MODE": "starttls"})
        client.login.assert_not_called()
        client.send_message.assert_not_called()


class PublicationTests(unittest.TestCase):
    def test_incomplete_checksum_set_never_calls_github(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for file in ["MailPush.apk", "source.tar.gz", "release.json"]:
                (root / file).write_bytes(b"synthetic")
            (root / "SHA256SUMS").write_text(
                hashlib.sha256(b"synthetic").hexdigest() + "  MailPush.apk\n"
            )
            args = [
                "publish_release.py",
                name,
                "--upstream",
                "a" * 40,
                "--module-sha256",
                "b" * 64,
                "--tag",
                "mailpush-" + ("a" * 12) + "-" + ("b" * 12),
            ]
            with patch.object(sys, "argv", args), patch.object(publish_release, "request") as api:
                with self.assertRaises(ValueError):
                    publish_release.main()
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
