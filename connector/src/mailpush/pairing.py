"""Authenticated offline import: no listening setup port and no plaintext handoff."""
from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import tempfile
import time
import tomllib
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import ConfigError, decode64, identifier, load, path_at

AAD = b"MailPush pairing v1"
RECEIPT_AAD = b"MailPush receipt v1"


def fingerprint(bundle: dict) -> str:
    fields = ["MailPush binding v2", bundle["binding"], bundle["endpoint"], bundle["keys"]["p256dh"], bundle["keys"]["auth"], *bundle["mailboxes"]]
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()[:24]


def seal(payload: dict, key: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(12)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    body = AESGCM(key).encrypt(nonce, json.dumps(payload, separators=(",", ":")).encode(), aad)
    return json.dumps({"format": "mailpush-receipt-v1", "nonce": enc(nonce), "ciphertext": enc(body)}, separators=(",", ":")).encode()


def decrypt_request(data: bytes, key_text: str, now: float | None = None) -> dict:
    if len(data) > 65536:
        raise ConfigError("Pairing file exceeds 64 KiB")
    try:
        key = decode64("".join(key_text.split()))
        envelope = json.loads(data)
        if len(key) != 32 or set(envelope) != {"format", "nonce", "ciphertext"} or envelope["format"] != "mailpush-pairing-v1":
            raise ValueError()
        nonce = decode64(envelope["nonce"])
        if len(nonce) != 12:
            raise ValueError()
        bundle = json.loads(AESGCM(key).decrypt(nonce, decode64(envelope["ciphertext"]), AAD))
        if bundle.get("format") != "mailpush-receiver-v2" or str(uuid.UUID(bundle["binding"])) != bundle["binding"]:
            raise ValueError()
        clock = time.time() if now is None else now
        created = bundle["created_at"]
        if type(created) is not int or not -300 <= clock - created <= 86400:
            raise ValueError()
        if not isinstance(bundle["mailboxes"], list) or not 1 <= len(bundle["mailboxes"]) <= 32:
            raise ValueError()
        bundle["mailboxes"] = [identifier(value) for value in bundle["mailboxes"]]
        if len(set(bundle["mailboxes"])) != len(bundle["mailboxes"]):
            raise ValueError()
        return bundle
    except ConfigError:
        raise
    except Exception:
        raise ConfigError("Pairing failed: wrong key, damaged file, or expired request; export a fresh request") from None


def import_request(config_path: str, request_path: str, device_id: str, replace: bool = False, key: str | None = None, receipt_path: str | None = None) -> str:
    path = Path(config_path).expanduser().resolve()
    raw = tomllib.loads(path.read_text())
    device_id = identifier(device_id)
    entries = [d for d in raw.get("devices", []) if d.get("id") == device_id]
    if len(entries) != 1:
        raise ConfigError("Add a unique device table with subscription_file before pairing")
    target = path_at(path.parent, entries[0]["subscription_file"])
    if target.is_symlink() or (target.exists() and not replace):
        raise ConfigError("Receiver file already exists or is a symlink; use --replace for a deliberate re-pair")
    file = Path(request_path)
    if file.stat().st_size > 65536:
        raise ConfigError("Pairing file exceeds 64 KiB")
    key = getpass.getpass("One-time pairing key from phone: ") if key is None else key
    bundle = decrypt_request(file.read_bytes(), key)
    receipt = Path(receipt_path) if receipt_path else file.with_suffix(".receipt")
    if receipt.is_symlink() or (receipt.exists() and not replace):
        raise ConfigError("Receipt file exists; choose --receipt with a fresh filename")
    targets = {box["id"] for box in raw.get("mailboxes", []) if device_id in box.get("devices", [d["id"] for d in raw.get("devices", [])])}
    if not targets.issubset(set(bundle["mailboxes"])):
        raise ConfigError("Phone did not approve the configured mailbox IDs; update the phone and export again")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous = target.read_bytes() if target.exists() else None
    previous_mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=".pair-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(bundle, output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, target)
        try:
            config = load(path)
            from .state import State
            state = State(config.state_dir, config.max_queue)
            try:
                source = state.installation
            finally:
                state.close()
            payload = {"format": "mailpush-receipt-v2", "binding": bundle["binding"],
                       "source": source, "fingerprint": fingerprint(bundle), "mailboxes": bundle["mailboxes"],
                       "created_at": int(time.time())}
            receipt_data = seal(payload, decode64("".join(key.split())), RECEIPT_AAD)
            flags = os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0) | (os.O_TRUNC if replace else os.O_EXCL)
            with os.fdopen(os.open(receipt, flags, 0o600), "wb") as receipt_file:
                receipt_file.write(receipt_data)
                receipt_file.flush()
                os.fsync(receipt_file.fileno())
        except Exception:
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
                target.chmod(previous_mode)
            raise
    finally:
        Path(name).unlink(missing_ok=True)
    # The owner compares this to the phone; no subscription/secret printed.
    return fingerprint(bundle)
