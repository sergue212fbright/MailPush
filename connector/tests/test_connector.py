import dataclasses
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import http_ece

from mailpush.config import Config, ConfigError, Mailbox, load
from mailpush.monitor import connect, scan, watch
from mailpush.push import Outcome, Sender, encrypt, retry_after
from mailpush.service import dispatch_one, enqueue_test
from mailpush.state import InstanceLock, QueueFull, State
from helpers import IMAPServer, PushServer, recipient


class Fixture(unittest.TestCase):
    def setUp(self):
        self.old_umask = os.umask(0o077)
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.state = State(self.directory / "state")
        self.device, self.private, self.auth = recipient()
        self.box = Mailbox("personal", "127.0.0.1", 1143, "local-test", "local-test-password", tls="none", device_ids=("phone",))
        self.config = Config(self.directory / "state", (self.device,), (self.box,))

    def tearDown(self):
        self.state.close()
        self.temp.cleanup()
        os.umask(self.old_umask)

    def decrypt(self, body):
        return json.loads(http_ece.decrypt(body, private_key=self.private, auth_secret=self.auth, version="aes128gcm"))


class EncryptionTests(Fixture):
    def test_roundtrip_padding_and_fresh_encryption(self):
        payload = {"v": 1, "type": "test", "subject": "private-test-subject"}
        first, second = encrypt(self.device, payload), encrypt(self.device, payload)
        self.assertNotEqual(first, second)
        self.assertNotIn(b"private-test-subject", first)
        clear = http_ece.decrypt(first, private_key=self.private, auth_secret=self.auth, version="aes128gcm")
        self.assertEqual(len(clear), 2048)
        self.assertEqual(json.loads(clear), payload)

    def test_modified_ciphertext_and_wrong_recipient_rejected(self):
        body = encrypt(self.device, {"v": 1})
        _, wrong_private, _ = recipient()
        with self.assertRaises(Exception):
            http_ece.decrypt(body, private_key=wrong_private, auth_secret=self.auth, version="aes128gcm")
        corrupt = body[:-1] + bytes([body[-1] ^ 1])
        with self.assertRaises(Exception):
            self.decrypt(corrupt)

    def test_payload_limit(self):
        with self.assertRaises(ValueError):
            encrypt(self.device, {"subject": "x" * 10000})

    def test_outbox_does_not_store_plaintext_preview(self):
        body = encrypt(self.device, {"subject": "private-test-subject"})
        self.state.enqueue([("event", "phone", self.device.fingerprint, body, time.time() + 60, time.time())])
        for file in (self.directory / "state").glob("mailpush.sqlite3*"):
            self.assertNotIn(b"private-test-subject", file.read_bytes())


class IMAPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server = IMAPServer()
        self.box = dataclasses.replace(self.box, port=self.server.port)
        self.config = dataclasses.replace(self.config, mailboxes=(self.box,))
        self.client = connect(self.box)

    def tearDown(self):
        self.client.shutdown()
        self.server.close()
        super().tearDown()

    def test_first_start_skips_history_then_sends_only_new_uid(self):
        self.server.add()
        scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.count(), 0)
        self.server.add()
        scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.count(), 1)
        payload = self.decrypt(self.state.next_due(time.time())["body"])
        self.assertEqual(payload["type"], "new_mail")
        self.assertNotIn("sender", payload)
        self.assertNotIn("subject", payload)
        scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.count(), 1)
        self.assertFalse(any("BODY" in command or "SELECT " in command for command in self.server.commands))

    def test_uid_range_does_not_repeat_last_existing_message(self):
        self.server.add()
        scan(self.client, self.box, self.config, self.state)
        for _ in range(3):
            scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.count(), 0)

    def test_preview_uses_peek_and_preserves_read_state(self):
        box = dataclasses.replace(self.box, preview=True)
        scan(self.client, box, self.config, self.state)
        uid = self.server.add()
        scan(self.client, box, self.config, self.state)
        payload = self.decrypt(self.state.next_due(time.time())["body"])
        self.assertEqual(payload["subject"], "private-test-subject")
        self.assertIn("Alice", payload["sender"])
        self.assertFalse(self.server.messages[uid]["seen"])
        self.assertTrue(any("BODY.PEEK" in command for command in self.server.commands))

    def test_seen_and_old_messages_advance_without_alerts(self):
        scan(self.client, self.box, self.config, self.state)
        self.server.add(seen=True)
        self.server.add(date=datetime.now(timezone.utc) - timedelta(days=3))
        scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.count(), 0)
        self.assertEqual(self.state.checkpoint("personal"), (12345, 2))

    def test_skip_seen_can_be_disabled(self):
        scan(self.client, self.box, self.config, self.state)
        self.server.add(seen=True)
        scan(self.client, dataclasses.replace(self.box, skip_seen=False), self.config, self.state)
        self.assertEqual(self.state.count(), 1)

    def test_uidvalidity_reset_baselines_without_flood(self):
        scan(self.client, self.box, self.config, self.state)
        self.server.add()
        self.server.validity = 67890
        scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.checkpoint("personal"), (67890, 1))
        self.assertEqual(self.state.count(), 0)

    def test_restart_catches_mail_received_while_offline(self):
        scan(self.client, self.box, self.config, self.state)
        self.state.close()
        self.server.add()
        self.state = State(self.directory / "state")
        scan(self.client, self.box, self.config, self.state)
        self.assertEqual(self.state.count(), 1)

    def test_bounded_batches_catch_up(self):
        scan(self.client, self.box, self.config, self.state)
        for _ in range(105):
            self.server.add()
        self.assertEqual(scan(self.client, self.box, self.config, self.state), 100)
        self.assertEqual(scan(self.client, self.box, self.config, self.state), 5)
        self.assertEqual(self.state.count(), 105)

    def test_real_idle_receives_new_mail(self):
        self.client.select_folder("INBOX", readonly=True)
        self.client.idle()
        try:
            self.server.add()
            events = self.client.idle_check(timeout=2)
            self.assertTrue(events)
        finally:
            self.client.idle_done()


class PersistenceTests(Fixture):
    def test_queue_capacity_rolls_back_checkpoint_and_deliveries(self):
        self.state.max_queue = 1
        self.state.commit_scan("personal", 1, 10)
        jobs = [(str(n), "phone", self.device.fingerprint, b"ciphertext", time.time() + 60, time.time()) for n in range(2)]
        with self.assertRaises(QueueFull):
            self.state.commit_scan("personal", 1, 11, jobs)
        self.assertEqual(self.state.checkpoint("personal"), (1, 10))
        self.assertEqual(self.state.count(), 0)

    def test_encrypted_queue_survives_reopen(self):
        enqueue_test(self.config, self.state)
        before = self.state.next_due(time.time())
        self.state.close()
        self.state = State(self.directory / "state")
        after = self.state.next_due(time.time())
        self.assertEqual(before["body"], after["body"])
        self.assertEqual(before["event"], after["event"])

    def test_second_process_lock_refused(self):
        first = InstanceLock(self.directory)
        try:
            with self.assertRaises(RuntimeError):
                InstanceLock(self.directory)
        finally:
            first.close()
        second = InstanceLock(self.directory)
        second.close()


class HTTPTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server = PushServer()
        self.device, self.private, self.auth = recipient(endpoint=self.server.endpoint)
        self.config = dataclasses.replace(self.config, devices=(self.device,))
        self.sender = Sender(2)

    def tearDown(self):
        self.sender.close()
        self.server.close()
        super().tearDown()

    def test_real_http_encrypted_delivery(self):
        enqueue_test(self.config, self.state)
        self.assertTrue(dispatch_one(self.config, self.state, self.sender))
        self.assertEqual(self.state.count(), 0)
        path, headers, body = self.server.requests[0]
        self.assertEqual(path, "/push?up=1")
        self.assertEqual(headers["Content-Encoding"], "aes128gcm")
        self.assertEqual(headers["X-Firebase"], "no")
        self.assertEqual(headers["X-UnifiedPush"], "1")
        self.assertGreater(int(headers["TTL"]), 0)
        self.assertEqual(self.decrypt(body)["type"], "test")

    def test_429_retries_same_event_after_retry_after(self):
        self.server.responses = [(429, {"Retry-After": "120"})]
        enqueue_test(self.config, self.state)
        event = self.state.next_due(time.time())["event"]
        dispatch_one(self.config, self.state, self.sender)
        self.assertEqual(self.state.count(), 1)
        self.assertIsNone(self.state.next_due(time.time() + 60))
        with self.state.transaction() as db:
            db.execute("UPDATE outbox SET due=0")
        dispatch_one(self.config, self.state, self.sender)
        self.assertEqual(self.state.count(), 0)
        self.assertEqual(self.decrypt(self.server.requests[0][2])["event_id"], event)
        self.assertEqual(self.server.requests[0][2], self.server.requests[1][2])

    def test_410_is_permanent(self):
        self.server.responses = [(410, {})]
        enqueue_test(self.config, self.state)
        dispatch_one(self.config, self.state, self.sender)
        self.assertEqual(self.state.count(), 0)
        self.assertEqual(self.state.db.execute("SELECT count FROM counters WHERE name='permanent_failure'").fetchone()[0], 1)

    def test_redirect_not_followed(self):
        self.server.responses = [(307, {"Location": self.server.endpoint + "&redirected=1"})]
        enqueue_test(self.config, self.state)
        dispatch_one(self.config, self.state, self.sender)
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.state.count(), 0)

    def test_expired_job_is_not_sent(self):
        enqueue_test(self.config, self.state)
        with self.state.transaction() as db:
            db.execute("UPDATE outbox SET expires=0")
        dispatch_one(self.config, self.state, self.sender)
        self.assertEqual(self.server.requests, [])

    def test_changed_keys_never_receive_old_ciphertext(self):
        enqueue_test(self.config, self.state)
        changed, _, _ = recipient(endpoint=self.server.endpoint)
        config = dataclasses.replace(self.config, devices=(changed,))
        dispatch_one(config, self.state, self.sender)
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.state.count(), 0)

    def test_imap_to_http_end_to_end(self):
        imap = IMAPServer()
        box = dataclasses.replace(self.box, port=imap.port, preview=True)
        client = connect(box)
        try:
            scan(client, box, self.config, self.state)
            imap.add()
            scan(client, box, self.config, self.state)
            dispatch_one(self.config, self.state, self.sender)
            payload = self.decrypt(self.server.requests[0][2])
            self.assertEqual(payload["subject"], "private-test-subject")
            self.assertEqual(payload["mailbox"], "personal")
            self.assertNotIn(b"private-test-subject", self.server.requests[0][2])
        finally:
            client.shutdown()
            imap.close()

    def test_retry_after_http_date(self):
        from email.utils import formatdate
        now = time.time()
        self.assertGreater(retry_after(formatdate(now + 300, usegmt=True), now), 298)
        self.assertEqual(retry_after("not-a-date", now), 0)


class ConfigTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.directory / "subscription.json").write_text(json.dumps(self.device.subscription))
        (self.directory / "password").write_text("local-test-secret\n")
        self.base = '''schema = 1
[service]
state_dir = "data"
[[devices]]
id = "phone"
subscription_file = "subscription.json"
[[mailboxes]]
id = "personal"
host = "127.0.0.1"
username = "example"
password_file = "password"
tls = "none"
'''
        self.file = self.directory / "config.toml"

    def parse(self, text=None):
        self.file.write_text(text or self.base)
        return load(self.file)

    def test_relative_paths_and_secret_file(self):
        config = self.parse()
        self.assertEqual(config.mailboxes[0].password, "local-test-secret")
        self.assertEqual(config.state_dir, self.directory / "data")
        self.assertNotIn("local-test-secret", repr(config))

    def test_unknown_settings_rejected(self):
        with self.assertRaises(ConfigError):
            self.parse(self.base.replace("state_dir", "state_dri"))

    def test_remote_plaintext_imap_rejected(self):
        with self.assertRaises(ConfigError):
            self.parse(self.base.replace('host = "127.0.0.1"', 'host = "remote.example.com"'))

    def test_public_http_push_rejected(self):
        sub = dict(self.device.subscription, endpoint="http://remote.example.com/push")
        (self.directory / "subscription.json").write_text(json.dumps(sub))
        with self.assertRaises(ConfigError):
            self.parse()

    def test_loopback_http_requires_opt_in(self):
        sub = dict(self.device.subscription, endpoint="http://127.0.0.1:1234/push")
        (self.directory / "subscription.json").write_text(json.dumps(sub))
        with self.assertRaises(ConfigError):
            self.parse()
        self.parse(self.base.replace('[service]', '[service]\nallow_http_loopback = true'))

    def test_invalid_receiver_keys_rejected(self):
        sub = json.loads(json.dumps(self.device.subscription))
        sub["keys"]["auth"] = "AA"
        (self.directory / "subscription.json").write_text(json.dumps(sub))
        with self.assertRaises(ConfigError):
            self.parse()

    def test_duplicate_device_id_rejected(self):
        with self.assertRaises(ConfigError):
            self.parse(self.base + '\n[[devices]]\nid="phone"\nsubscription_file="subscription.json"\n')

    def test_duplicate_secret_sources_rejected(self):
        with self.assertRaises(ConfigError):
            self.parse(self.base + '\npassword_env="ALSO_CONFIGURED"\n')


class LifecycleTests(Fixture):
    def test_real_service_idle_delivery_status_and_shutdown(self):
        imap, push = IMAPServer(), PushServer()
        device, private, auth = recipient(endpoint=push.endpoint)
        (self.directory / "subscription.json").write_text(json.dumps(device.subscription))
        (self.directory / "password").write_text("local-test-password")
        config_file = self.directory / "config.toml"
        config_file.write_text(f'''schema=1
[service]
state_dir="live-state"
allow_http_loopback=true
[[devices]]
id="phone"
subscription_file="subscription.json"
[[mailboxes]]
id="personal"
host="127.0.0.1"
port={imap.port}
username="example"
password_file="password"
tls="none"
preview=true
''')
        process = subprocess.Popen([sys.executable, "-m", "mailpush.cli", "run", "--config", str(config_file)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not any(" IDLE" in command for command in imap.commands) and time.monotonic() < deadline:
                if process.poll() is not None:
                    self.fail("Service exited before entering IDLE")
                time.sleep(0.05)
            self.assertTrue(any(" IDLE" in command for command in imap.commands))
            imap.add()
            while not push.requests and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(push.requests)
            clear = json.loads(http_ece.decrypt(push.requests[0][2], private_key=private, auth_secret=auth, version="aes128gcm"))
            self.assertEqual(clear["subject"], "private-test-subject")
            check = subprocess.run([sys.executable, "-m", "mailpush.cli", "status", "--state-dir", str(self.directory / "live-state")], capture_output=True, text=True, timeout=5)
            self.assertEqual(check.returncode, 0)
            data = json.loads(check.stdout)
            self.assertIn("diagnostics", data)
            if os.name != "nt":
                process.terminate()
                stdout, stderr = process.communicate(timeout=12)
                self.assertEqual(process.returncode, 0)
                self.assertNotIn("private-test-subject", stdout + stderr)
                self.assertNotIn("local-test-password", stdout + stderr)
                self.assertNotIn(push.endpoint, stdout + stderr)
                self.assertFalse((self.directory / "live-state" / "heartbeat.json").exists())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
            imap.close()
            push.close()


if __name__ == "__main__":
    unittest.main()
