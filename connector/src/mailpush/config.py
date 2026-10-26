"""File-based configuration shared by native and container installations."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import re
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec


class ConfigError(ValueError):
    pass


def decode64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", value):
        raise ConfigError("IDs must contain 1–48 letters, digits, underscores or hyphens")
    return value


def bounded(value: object, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ConfigError(f"{name} must be an integer between {low} and {high}")
    return value


def boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ConfigError(f"{name} must be true or false")
    return value


def path_at(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def secret(base: Path, item: dict, prefix: str) -> str:
    env = item.get(prefix + "_env")
    filename = item.get(prefix + "_file")
    if bool(env) == bool(filename):
        raise ConfigError(f"Set exactly one of {prefix}_env or {prefix}_file")
    if env:
        value = os.environ.get(env, "")
    else:
        value = private_text(path_at(base, filename)).rstrip("\r\n")
    if not value or len(value) > 16384 or "\x00" in value or "\r" in value or "\n" in value:
        raise ConfigError(f"Missing or invalid {prefix} secret")
    return value


def private_text(path: Path) -> str:
    if os.name != "nt" and path.stat().st_mode & 0o027:
        raise ConfigError("Secret files must not be group-writable or accessible to other users; use 0600 or 0640")
    if path.stat().st_size > 65536:
        raise ConfigError("Secret file exceeds 64 KiB")
    return path.read_text(encoding="utf-8")


def known(item: dict, allowed: set[str], section: str) -> None:
    if not isinstance(item, dict) or set(item) - allowed:
        raise ConfigError(f"Unknown setting or invalid table in {section}")


@dataclass(frozen=True)
class Device:
    id: str
    subscription: dict = field(repr=False)
    fingerprint: str
    ca_file: str | None = None
    bearer_token: str | None = field(default=None, repr=False)
    vapid_key_file: str | None = None
    vapid_subject: str | None = None
    binding: str | None = None
    allowed_mailboxes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Mailbox:
    id: str
    host: str
    port: int
    username: str = field(repr=False)
    password: str = field(repr=False)
    folder: str = "INBOX"
    tls: str = "starttls"
    ca_file: str | None = None
    device_ids: tuple[str, ...] = ()
    preview: bool = False
    skip_seen: bool = True
    use_idle: bool = True
    poll_seconds: int = 60
    reconcile_seconds: int = 300
    max_age_seconds: int = 86400
    tls_pin_sha256: str | None = None


@dataclass(frozen=True)
class Config:
    state_dir: Path
    devices: tuple[Device, ...]
    mailboxes: tuple[Mailbox, ...]
    ttl_seconds: int = 43200
    request_timeout: int = 15
    max_queue: int = 10000


def load(filename: str | Path) -> Config:
    try:
        return _load(Path(filename).expanduser().resolve())
    except ConfigError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Never echo configuration values, IMAP credentials or capability URLs.
        raise ConfigError(f"Cannot load configuration or referenced file ({type(exc).__name__})") from None


def _load(filename: Path) -> Config:
    base = filename.parent
    raw = tomllib.loads(filename.read_text(encoding="utf-8"))
    known(raw, {"schema", "service", "devices", "mailboxes"}, "root")
    if raw.get("schema") != 1:
        raise ConfigError("Configuration schema must be 1")
    service = raw.get("service", {})
    known(service, {"state_dir", "ttl_seconds", "request_timeout", "max_queue", "allow_http_loopback"}, "service")
    allow_http = boolean(service.get("allow_http_loopback", False), "allow_http_loopback")
    devices = []
    for item in raw.get("devices", []):
        known(item, {"id", "subscription_file", "ca_file", "bearer_token_file", "bearer_token_env", "vapid_key_file", "vapid_subject"}, "devices")
        bundle = json.loads(private_text(path_at(base, item["subscription_file"])))
        binding = bundle.get("binding")
        allowed = bundle.get("mailboxes", [])
        if binding is not None:
            if str(uuid.UUID(binding)) != binding or not isinstance(allowed, list) or not allowed or len(allowed) > 32:
                raise ConfigError("Invalid receiver binding or mailbox allowlist")
            allowed = [identifier(value) for value in allowed]
            if len(set(allowed)) != len(allowed):
                raise ConfigError("Duplicate receiver mailbox binding")
        sub = bundle
        # A standard PushSubscription JSON; discard unrelated client-side fields.
        sub = {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}}
        url = urlsplit(sub["endpoint"])
        if (not isinstance(sub["endpoint"], str) or len(sub["endpoint"]) > 4096 or any(ord(c) < 33 for c in sub["endpoint"])
                or not url.hostname or url.username or url.password or url.fragment
                or (url.scheme != "https" and not (allow_http and url.scheme == "http" and loopback(url.hostname)))):
            raise ConfigError("Push endpoints require HTTPS; HTTP loopback needs explicit opt-in")
        _ = url.port
        key = decode64(sub["keys"]["p256dh"])
        if len(key) != 65 or key[0] != 4 or len(decode64(sub["keys"]["auth"])) != 16:
            raise ConfigError("Invalid Web Push receiver keys")
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)
        vapid = str(path_at(base, item["vapid_key_file"])) if item.get("vapid_key_file") else None
        bearer = secret(base, item, "bearer_token") if item.get("bearer_token_file") or item.get("bearer_token_env") else None
        if vapid and (bearer or not str(item.get("vapid_subject", "")).startswith(("mailto:", "https://"))):
            raise ConfigError("VAPID requires a contact subject and cannot share Authorization with a bearer token")
        if vapid:
            from py_vapid import Vapid
            private_text(Path(vapid))
            Vapid.from_file(vapid)
        fingerprint = hashlib.sha256(json.dumps({"subscription": sub, "binding": binding}, sort_keys=True).encode()).hexdigest()
        devices.append(Device(identifier(item["id"]), sub, fingerprint,
                              str(path_at(base, item["ca_file"])) if item.get("ca_file") else None,
                              bearer, vapid, item.get("vapid_subject"), binding, tuple(allowed)))
    ids = {device.id for device in devices}
    if not ids or len(ids) != len(devices):
        raise ConfigError("Configure at least one device with a unique ID")
    mailboxes = []
    for item in raw.get("mailboxes", []):
        known(item, {"id", "host", "port", "username", "password_env", "password_file", "folder", "tls", "ca_file", "tls_pin_sha256", "devices", "preview", "skip_seen", "use_idle", "poll_seconds", "reconcile_seconds", "max_age_seconds"}, "mailboxes")
        tls = item.get("tls", "starttls")
        host = item.get("host", "127.0.0.1")
        if tls not in {"starttls", "tls", "none"} or (tls == "none" and not loopback(host)):
            raise ConfigError("IMAP TLS must be starttls or tls; none is allowed only on loopback")
        pin = item.get("tls_pin_sha256")
        if pin is not None:
            if not isinstance(pin, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", pin.replace(":", "")) or tls == "none" or item.get("ca_file"):
                raise ConfigError("TLS pin must be a SHA-256 certificate fingerprint; choose pinning or CA verification")
            pin = pin.replace(":", "").lower()
        targets = item.get("devices", sorted(ids))
        if not isinstance(targets, list) or not targets or set(targets) - ids or len(set(targets)) != len(targets):
            raise ConfigError("Mailbox references unknown, duplicate or empty device IDs")
        username, folder = item["username"], item.get("folder", "INBOX")
        if not isinstance(username, str) or not username or not isinstance(folder, str) or not folder or any(c in username + folder for c in "\x00\r\n"):
            raise ConfigError("Invalid IMAP username or folder")
        mailboxes.append(Mailbox(
            id=identifier(item["id"]), host=host,
            port=bounded(item.get("port", 993 if tls == "tls" else 1143), 1, 65535, "port"),
            username=username, password=secret(base, item, "password"), folder=folder, tls=tls,
            ca_file=str(path_at(base, item["ca_file"])) if item.get("ca_file") else None,
            device_ids=tuple(targets), preview=boolean(item.get("preview", False), "preview"),
            skip_seen=boolean(item.get("skip_seen", True), "skip_seen"),
            use_idle=boolean(item.get("use_idle", True), "use_idle"),
            poll_seconds=bounded(item.get("poll_seconds", 60), 5, 3600, "poll_seconds"),
            reconcile_seconds=bounded(item.get("reconcile_seconds", 300), 30, 1500, "reconcile_seconds"),
            max_age_seconds=bounded(item.get("max_age_seconds", 86400), 60, 604800, "max_age_seconds"),
            tls_pin_sha256=pin))
    if not mailboxes or len({box.id for box in mailboxes}) != len(mailboxes):
        raise ConfigError("Configure at least one mailbox with a unique ID")
    for device in devices:
        assigned = {box.id for box in mailboxes if device.id in box.device_ids}
        if device.binding and not assigned.issubset(device.allowed_mailboxes):
            raise ConfigError("Configured mailbox is outside the phone's approved binding; pair again with matching IDs")
    return Config(
        path_at(base, os.environ.get("MAILPUSH_STATE_DIR", service.get("state_dir", "state"))).resolve(),
        tuple(devices), tuple(mailboxes),
        bounded(service.get("ttl_seconds", 43200), 60, 86400, "ttl_seconds"),
        bounded(service.get("request_timeout", 15), 1, 60, "request_timeout"),
        bounded(service.get("max_queue", 10000), 10, 1000000, "max_queue"))
