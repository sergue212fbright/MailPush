"""Read-only IMAP monitoring. No private Proton API or Bridge implementation hooks."""

from __future__ import annotations

import logging
import ssl
import threading
import time
import uuid
import hashlib
import hmac
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser

from imapclient import IMAPClient

from .config import Config, Mailbox
from .push import encrypt
from .state import State

LOG = logging.getLogger("mailpush")
HEADER_REQUEST = "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]"


def connect(box: Mailbox) -> IMAPClient:
    context = ssl.create_default_context(cafile=box.ca_file)
    if box.tls_pin_sha256:
        # Pin verification below replaces CA/hostname verification, before LOGIN.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    client = IMAPClient(box.host, port=box.port, ssl=box.tls == "tls", ssl_context=context, timeout=20)
    try:
        if box.tls == "starttls":
            client.starttls(ssl_context=context)
        if box.tls_pin_sha256:
            observed = hashlib.sha256(client.socket().getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(observed, box.tls_pin_sha256):
                raise ssl.SSLCertVerificationError("IMAP certificate pin mismatch")
        client.login(box.username, box.password)
        client.normalise_times = False
        return client
    except BaseException:
        client.shutdown()
        raise


def clean(value: object, limit: int) -> str:
    return "".join(c for c in str(value) if c.isprintable())[:limit]


def scan(client: IMAPClient, box: Mailbox, config: Config, state: State) -> int:
    state.bind_mailbox(box.id, box.username, box.folder)
    selected = client.select_folder(box.folder, readonly=True)
    validity = int(selected[b"UIDVALIDITY"])
    checkpoint = state.checkpoint(box.id)
    if checkpoint is None or checkpoint[0] != validity:
        # Baseline using UIDNEXT, avoiding a historical mailbox notification flood.
        baseline = max(0, int(selected[b"UIDNEXT"]) - 1)
        state.commit_scan(box.id, validity, baseline)
        state.diagnostic("mailbox_" + box.id, code="baseline_created" if checkpoint is None else "uidvalidity_reset", last_uid=baseline)
        LOG.info("mailbox=%s code=%s", box.id, "baseline_created" if checkpoint is None else "uidvalidity_reset")
        return 0
    last_uid = checkpoint[1]
    # IMAP n:* is a reversed range when n exceeds the largest UID. Filter locally.
    uids = sorted(int(uid) for uid in client.search(["UID", f"{last_uid + 1}:*"]) if int(uid) > last_uid)[:100]
    fields = ["FLAGS", "INTERNALDATE"] + ([HEADER_REQUEST] if box.preview else [])
    fetched = client.fetch(uids, fields) if uids else {}
    devices = {d.id: d for d in config.devices}
    for uid in uids:
        now = time.time()
        data = fetched.get(uid)
        jobs = []
        if data:
            date = data.get(b"INTERNALDATE")
            if not isinstance(date, datetime):
                # Do not silently advance past a malformed/incomplete server reply.
                raise ValueError("Missing IMAP INTERNALDATE")
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            flags = data.get(b"FLAGS", ())
            seen = b"\\Seen" in flags or "\\Seen" in flags
            if now - date.timestamp() <= box.max_age_seconds and not (box.skip_seen and seen):
                event_id = str(uuid.uuid5(uuid.UUID(state.installation), f"{box.id}:{validity}:{uid}"))
                event = {"v": 1, "type": "new_mail", "event_id": event_id, "mailbox": box.id,
                         "created_at": int(now), "expires_at": int(now) + config.ttl_seconds,
                         "source": state.installation}
                if box.preview:
                    headers = next((value for key, value in data.items() if isinstance(key, bytes) and key.startswith(b"BODY[HEADER.FIELDS")), None)
                    if not isinstance(headers, bytes):
                        raise ValueError("Missing requested IMAP headers")
                    message = BytesParser(policy=policy.default).parsebytes(headers, headersonly=True)
                    event.update(sender=clean(message.get("From", ""), 160), subject=clean(message.get("Subject", ""), 240))
                for device_id in box.device_ids:
                    device = devices[device_id]
                    if state.revoked(device):
                        continue
                    jobs.append((event_id, device.id, device.fingerprint, encrypt(device, event), event["expires_at"], now))
        # Ciphertext and checkpoint are committed in the same SQLite transaction.
        state.commit_scan(box.id, validity, uid, jobs)
    state.diagnostic("mailbox_" + box.id, code="scan_ok", last_uid=uids[-1] if uids else last_uid)
    return len(uids)


def watch(box: Mailbox, config: Config, state: State, stop: threading.Event):
    delay = 1
    while not stop.is_set():
        client = None
        try:
            client = connect(box)
            idle_supported = box.use_idle and client.has_capability("IDLE")
            while not stop.is_set():
                scanned = scan(client, box, config, state)
                delay = 1
                if scanned == 100:
                    continue  # Catch up in bounded batches before waiting again.
                if idle_supported:
                    client.idle()
                    try:
                        deadline = time.monotonic() + box.reconcile_seconds
                        while not stop.is_set() and time.monotonic() < deadline:
                            if client.idle_check(timeout=min(5, max(0.1, deadline - time.monotonic()))):
                                break
                    finally:
                        client.idle_done()
                else:
                    stop.wait(box.poll_seconds)
        except Exception as exc:
            # Remote error strings can contain credentials, headers or other private data.
            code = "imap_" + type(exc).__name__
            LOG.warning("mailbox=%s code=%s retry_seconds=%s", box.id, code, delay)
            state.diagnostic("mailbox_" + box.id, code=code)
            stop.wait(delay)
            delay = min(delay * 2, 300)
        finally:
            if client is not None:
                try:
                    client.shutdown()
                except Exception:
                    pass
