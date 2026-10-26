"""RFC 8291 encryption and bounded, non-redirecting HTTPS delivery."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
from py_vapid import Vapid
from pywebpush import WebPusher

from .config import Device

PADDED_SIZE = 2048


def encrypt(device: Device, payload: dict) -> bytes:
    if device.binding:
        payload = {**payload, "v": 2, "binding": device.binding}
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(serialized) > PADDED_SIZE:
        raise ValueError("Alert exceeds the payload limit")
    # JSON accepts trailing whitespace. Fixed-size plaintext reduces size leakage.
    padded = serialized.ljust(PADDED_SIZE, b" ")
    return bytes(WebPusher(device.subscription).encode(padded, content_encoding="aes128gcm")["body"])


@dataclass(frozen=True)
class Outcome:
    accepted: bool
    permanent: bool = False
    code: str = ""
    retry_after: float = 0


def retry_after(value: str | None, now: float) -> float:
    if not value:
        return 0
    try:
        return max(0.0, float(int(value)))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0.0, date.timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 0


class Sender:
    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        # Do not silently pick up .netrc credentials or ambient proxies.
        self.session.trust_env = False

    def close(self) -> None:
        self.session.close()

    def send(self, device: Device, body: bytes, expires: float) -> Outcome:
        now = time.time()
        remaining = int(expires - now)
        if remaining <= 0:
            return Outcome(False, True, "expired")
        headers = {"Content-Type": "application/octet-stream", "Content-Encoding": "aes128gcm",
                   "TTL": str(remaining), "Urgency": "normal",
                   "X-Firebase": "no", "X-UnifiedPush": "1"}
        try:
            if device.bearer_token:
                headers["Authorization"] = "Bearer " + device.bearer_token
            if device.vapid_key_file:
                url = urlsplit(device.subscription["endpoint"])
                claims = {"sub": device.vapid_subject, "aud": f"{url.scheme}://{url.netloc}", "exp": int(now) + 3600}
                headers.update(Vapid.from_file(device.vapid_key_file).sign(claims))
            with self.session.post(device.subscription["endpoint"], data=body, headers=headers,
                                   timeout=(self.timeout, self.timeout), allow_redirects=False,
                                   verify=device.ca_file or True, stream=True) as response:
                status = response.status_code
                # Do not read, log or trust arbitrary response bodies.
                if 200 <= status < 300:
                    return Outcome(True, code=f"http_{status}")
                permanent = 300 <= status < 500 and status not in {408, 425, 429}
                return Outcome(False, permanent, f"http_{status}", retry_after(response.headers.get("Retry-After"), now))
        except (requests.RequestException, OSError, ValueError) as exc:
            return Outcome(False, code=f"transport_{type(exc).__name__}")
