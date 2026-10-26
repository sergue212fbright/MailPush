from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
import uuid

from .config import Config
from .monitor import watch
from .push import Sender, encrypt
from .state import InstanceLock, State

LOG = logging.getLogger("mailpush")


def dispatch_one(config: Config, state: State, sender: Sender) -> bool:
    now = time.time()
    job = state.next_due(now)
    if job is None:
        return False
    devices = {d.id: d for d in config.devices}
    device = devices.get(job["device"])
    if job["expires"] <= now:
        state.finish(job["id"], "expired")
    elif device is None or device.fingerprint != job["fingerprint"] or state.revoked(device):
        state.finish(job["id"], "recipient_changed")
    else:
        outcome = sender.send(device, job["body"], job["expires"])
        state.diagnostic("device_" + device.id, code=outcome.code, accepted=outcome.accepted)
        if outcome.accepted:
            state.finish(job["id"], "accepted_by_push_server")
            LOG.info("device=%s code=accepted_by_push_server", device.id)
        elif outcome.permanent:
            state.finish(job["id"], "permanent_failure")
            LOG.warning("device=%s code=%s action=discard", device.id, outcome.code)
        else:
            delay = max(outcome.retry_after, min(900, 2 ** min(job["attempts"] + 1, 10)) + random.uniform(0, 1))
            state.retry(job["id"], now + delay)
            LOG.warning("device=%s code=%s action=retry", device.id, outcome.code)
    return True


def delivery_loop(config: Config, state: State, stop: threading.Event):
    sender = Sender(config.request_timeout)
    try:
        while not stop.is_set():
            if not dispatch_one(config, state, sender):
                stop.wait(0.5)
    finally:
        sender.close()


def enqueue_test(config: Config, state: State, device_id: str | None = None):
    devices = [d for d in config.devices if device_id is None or d.id == device_id]
    if not devices:
        raise ValueError("Unknown device ID")
    now = time.time()
    event = {"v": 1, "type": "test", "event_id": str(uuid.uuid4()), "mailbox": "test",
             "created_at": int(now), "expires_at": int(now) + config.ttl_seconds, "source": state.installation}
    state.enqueue([(event["event_id"], d.id, d.fingerprint, encrypt(d, event), event["expires_at"], now) for d in devices if not state.revoked(d)])


def run(config: Config, stop: threading.Event):
    lock = InstanceLock(config.state_dir)
    state = State(config.state_dir, config.max_queue)
    threads = []
    heartbeat = config.state_dir / "heartbeat.json"
    try:
        for box in config.mailboxes:
            threads.append(threading.Thread(target=watch, args=(box, config, state, stop), name="mailbox_" + box.id, daemon=True))
        threads.append(threading.Thread(target=delivery_loop, args=(config, state, stop), name="delivery", daemon=True))
        for thread in threads:
            thread.start()
        LOG.info("code=started mailboxes=%s devices=%s", len(config.mailboxes), len(config.devices))
        while not stop.is_set():
            if not all(t.is_alive() for t in threads):
                raise RuntimeError("A worker stopped unexpectedly")
            temporary = heartbeat.with_suffix(".tmp")
            temporary.write_text(json.dumps({"at": time.time(), "pid": os.getpid()}), encoding="utf-8")
            temporary.replace(heartbeat)
            stop.wait(5)
    finally:
        stop.set()
        # Let a bounded socket operation or IDLE check complete before closing SQLite.
        deadline = time.monotonic() + 45
        for thread in threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        heartbeat.unlink(missing_ok=True)
        if not any(t.is_alive() for t in threads):
            state.close()
        lock.close()
        LOG.info("code=stopped")
