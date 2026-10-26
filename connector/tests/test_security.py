import base64
import dataclasses
import hashlib
import json
import os
import ssl
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mailpush.config import Config, ConfigError, Mailbox, load
from mailpush.monitor import connect, scan
from mailpush.pairing import AAD, RECEIPT_AAD, decrypt_request, fingerprint, import_request
from mailpush.push import Sender
from mailpush.service import dispatch_one, enqueue_test
from mailpush.state import MailboxBindingError, State
from helpers import recipient, IMAPServer


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.old_umask = os.umask(0o077)
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.device, self.private, self.auth = recipient()
        self.key = os.urandom(32); self.key_text = self.enc(self.key)
        self.bundle = {"format": "mailpush-receiver-v2", "binding": str(uuid.uuid4()), "mailboxes": ["personal"], "created_at": int(time.time()), **self.device.subscription}
        (self.root / "password").write_text("synthetic-local-password")
        self.config_file = self.root / "config.toml"
        self.config_file.write_text('''schema=1
[service]
state_dir="state"
[[devices]]
id="phone"
subscription_file="receiver.json"
[[mailboxes]]
id="personal"
host="127.0.0.1"
username="synthetic"
password_file="password"
tls="none"
devices=["phone"]
''')

    def tearDown(self):
        self.temp.cleanup(); os.umask(self.old_umask)

    @staticmethod
    def enc(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    def request(self, bundle=None):
        nonce = os.urandom(12)
        data = json.dumps(bundle or self.bundle, separators=(",", ":")).encode()
        return json.dumps({"format": "mailpush-pairing-v1", "nonce": self.enc(nonce), "ciphertext": self.enc(AESGCM(self.key).encrypt(nonce, data, AAD))}).encode()

    def test_pairing_roundtrip_and_bound_receipt(self):
        request = self.root / "phone.mailpush"; request.write_bytes(self.request())
        seen = import_request(str(self.config_file), str(request), "phone", key=self.key_text)
        self.assertEqual(seen, fingerprint(self.bundle))
        config = load(self.config_file)
        self.assertEqual(config.devices[0].binding, self.bundle["binding"])
        envelope = json.loads((self.root / "phone.receipt").read_bytes())
        receipt = json.loads(AESGCM(self.key).decrypt(base64.urlsafe_b64decode(envelope["nonce"] + "=="), base64.urlsafe_b64decode(envelope["ciphertext"] + "=="), RECEIPT_AAD))
        self.assertEqual(receipt["binding"], self.bundle["binding"])
        state = State(config.state_dir)
        try: self.assertEqual(receipt["source"], state.installation)
        finally: state.close()
        self.assertNotIn(self.bundle["keys"]["auth"].encode(), request.read_bytes())

    def test_wrong_pairing_key_rejected(self):
        with self.assertRaises(ConfigError): decrypt_request(self.request(), self.enc(os.urandom(32)))

    def test_expired_request_rejected(self):
        self.bundle["created_at"] = int(time.time()) - 86401
        with self.assertRaises(ConfigError): decrypt_request(self.request(), self.key_text)

    def test_request_cannot_be_reflected_as_receipt(self):
        raw = json.loads(self.request())
        with self.assertRaises(Exception):
            AESGCM(self.key).decrypt(base64.urlsafe_b64decode(raw["nonce"] + "=="), base64.urlsafe_b64decode(raw["ciphertext"] + "=="), RECEIPT_AAD)

    def test_pairing_rejects_unapproved_mailbox(self):
        self.bundle["mailboxes"] = ["other"]
        request = self.root / "phone.mailpush"; request.write_bytes(self.request())
        with self.assertRaises(ConfigError): import_request(str(self.config_file), str(request), "phone", key=self.key_text)
        self.assertFalse((self.root / "receiver.json").exists())

    def test_existing_receiver_requires_deliberate_replace(self):
        request = self.root / "phone.mailpush"; request.write_bytes(self.request())
        (self.root / "receiver.json").write_text("existing")
        with self.assertRaises(ConfigError): import_request(str(self.config_file), str(request), "phone", key=self.key_text)
        self.assertEqual((self.root / "receiver.json").read_text(), "existing")

    def test_invalid_pairing_preserves_previous_receiver(self):
        request = self.root / "phone.mailpush"
        self.bundle["keys"]["auth"] = "bad"
        request.write_bytes(self.request())
        original = json.dumps(self.device.subscription)
        (self.root / "receiver.json").write_text(original)
        with self.assertRaises(ConfigError): import_request(str(self.config_file), str(request), "phone", key=self.key_text, replace=True)
        self.assertEqual((self.root / "receiver.json").read_text(), original)

    @unittest.skipIf(os.name == "nt", "Unix permission validation")
    def test_world_readable_secret_rejected(self):
        (self.root / "receiver.json").write_text(json.dumps(self.device.subscription))
        (self.root / "password").chmod(0o644)
        with self.assertRaises(ConfigError): load(self.config_file)

    def test_mailbox_identity_cannot_silently_change(self):
        state = State(self.root / "state")
        try:
            state.bind_mailbox("personal", "first", "INBOX")
            with self.assertRaises(MailboxBindingError): state.bind_mailbox("personal", "second", "INBOX")
        finally: state.close()

    def test_installation_identity_persists_and_is_distinct(self):
        first = State(self.root / "state"); identifier = first.installation; first.close()
        second = State(self.root / "state"); different = State(self.root / "other-state")
        try:
            self.assertEqual(second.installation, identifier)
            self.assertNotEqual(different.installation, identifier)
        finally: second.close(); different.close()

    def test_revoked_device_cannot_send_queued_alert(self):
        state = State(self.root / "state")
        box = Mailbox("personal", "127.0.0.1", 1143, "synthetic", "password", tls="none", device_ids=("phone",))
        config = Config(self.root / "state", (self.device,), (box,))
        class MustNotSend:
            def send(self, *args): raise AssertionError("Revoked delivery attempted")
        try:
            enqueue_test(config, state); state.revoke(self.device)
            dispatch_one(config, state, MustNotSend())
            self.assertEqual(state.count(), 0)
            enqueue_test(config, state)
            self.assertEqual(state.count(), 0)
        finally: state.close()


class CertificatePinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        private = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "localhost")])
        certificate = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
        certificate = certificate.serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(days=1)).not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
        self.cert = certificate.sign(private, hashes.SHA256())
        (self.root / "cert.pem").write_bytes(self.cert.public_bytes(serialization.Encoding.PEM))
        (self.root / "key.pem").write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.load_cert_chain(self.root / "cert.pem", self.root / "key.pem")
        self.server = IMAPServer(tls_context=context)
        self.box = Mailbox("personal", "127.0.0.1", self.server.port, "synthetic", "password", tls="tls", device_ids=("phone",), tls_pin_sha256=self.cert.fingerprint(hashes.SHA256()).hex())

    def tearDown(self):
        self.server.close(); self.temp.cleanup()

    def test_matching_pin_allows_login_with_self_signed_bridge_certificate(self):
        client = connect(self.box)
        try: self.assertTrue(any("LOGIN" in command for command in self.server.commands))
        finally: client.shutdown()

    def test_wrong_pin_never_sends_login(self):
        with self.assertRaises(ssl.SSLCertVerificationError): connect(dataclasses.replace(self.box, tls_pin_sha256="0" * 64))
        self.assertFalse(any("LOGIN" in command for command in self.server.commands))

    def test_untrusted_certificate_without_pin_is_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError): connect(dataclasses.replace(self.box, tls_pin_sha256=None))
        self.assertFalse(any("LOGIN" in command for command in self.server.commands))
