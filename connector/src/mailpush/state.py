"""Transactional checkpoints and an encrypted-at-application-layer outbox."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
import hashlib
from contextlib import contextmanager
from pathlib import Path


class QueueFull(RuntimeError):
    pass


class State:
    def __init__(self, directory: Path, max_queue: int = 10000):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            directory.chmod(0o700)
        self.path = directory / "mailpush.sqlite3"
        self.max_queue = max_queue
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES ('schema', '1');
            CREATE TABLE IF NOT EXISTS checkpoints
                (mailbox TEXT PRIMARY KEY, validity INTEGER NOT NULL, uid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox
                (id INTEGER PRIMARY KEY, event TEXT NOT NULL, device TEXT NOT NULL,
                 fingerprint TEXT NOT NULL, body BLOB NOT NULL, expires REAL NOT NULL,
                 due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                 UNIQUE(event, device, fingerprint));
            CREATE INDEX IF NOT EXISTS outbox_due ON outbox(due);
            CREATE TABLE IF NOT EXISTS diagnostics
                (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS counters
                (name TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0);
        """)
        if self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] != "1":
            self.db.close()
            raise RuntimeError("Unsupported state schema")
        self.db.commit()
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO meta VALUES('installation',?)", (str(uuid.uuid4()),))
        self.installation = self.db.execute("SELECT value FROM meta WHERE key='installation'").fetchone()[0]
        if os.name != "nt":
            self.path.chmod(0o600)

    def bind_mailbox(self, mailbox: str, username: str, folder: str):
        identity = hashlib.sha256(json.dumps([username, folder]).encode()).hexdigest()
        with self.transaction() as db:
            key = "mailbox_identity_" + mailbox
            old = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            if old and old[0] != identity:
                raise MailboxBindingError("Mailbox ID belongs to another account/folder; configure a new ID")
            db.execute("INSERT OR IGNORE INTO meta VALUES(?,?)", (key, identity))

    def revoke(self, device):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", ("revoked_" + device.id, device.fingerprint))

    def revoked(self, device) -> bool:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", ("revoked_" + device.id,)).fetchone()
            return bool(row and row[0] == device.fingerprint)

    def close(self):
        with self.lock:
            self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock, self.db:
            yield self.db

    def checkpoint(self, mailbox: str):
        with self.lock:
            row = self.db.execute("SELECT validity, uid FROM checkpoints WHERE mailbox=?", (mailbox,)).fetchone()
            return tuple(row) if row else None

    def commit_scan(self, mailbox: str, validity: int, uid: int, jobs=()):
        with self.transaction() as db:
            db.execute("DELETE FROM outbox WHERE expires <= ?", (time.time(),))
            size = db.execute("SELECT count(*) FROM outbox").fetchone()[0]
            if size + len(jobs) > self.max_queue:
                raise QueueFull("Outbox full; mailbox checkpoint has not advanced")
            db.executemany("INSERT OR IGNORE INTO outbox(event,device,fingerprint,body,expires,due) VALUES(?,?,?,?,?,?)", jobs)
            db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (mailbox, validity, uid))

    def enqueue(self, jobs):
        with self.transaction() as db:
            if db.execute("SELECT count(*) FROM outbox").fetchone()[0] + len(jobs) > self.max_queue:
                raise QueueFull("Outbox full")
            db.executemany("INSERT OR IGNORE INTO outbox(event,device,fingerprint,body,expires,due) VALUES(?,?,?,?,?,?)", jobs)

    def next_due(self, now: float):
        with self.lock:
            return self.db.execute("SELECT * FROM outbox WHERE due <= ? OR expires <= ? ORDER BY due,id LIMIT 1", (now, now)).fetchone()

    def finish(self, job_id: int, result: str):
        with self.transaction() as db:
            db.execute("DELETE FROM outbox WHERE id=?", (job_id,))
            db.execute("INSERT INTO counters VALUES(?,1) ON CONFLICT(name) DO UPDATE SET count=count+1", (result,))

    def retry(self, job_id: int, due: float):
        with self.transaction() as db:
            db.execute("UPDATE outbox SET due=?,attempts=attempts+1 WHERE id=?", (due, job_id))

    def diagnostic(self, identifier: str, **data):
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO diagnostics VALUES(?,?)", (identifier, json.dumps({"at": time.time(), **data})))

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]


def snapshot(directory: Path) -> dict:
    path = directory / "mailpush.sqlite3"
    if not path.exists():
        return {"state": "not_started"}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        return {"queued": db.execute("SELECT count(*) FROM outbox").fetchone()[0],
                "counters": dict(db.execute("SELECT name,count FROM counters")),
                "diagnostics": {name: json.loads(data) for name, data in db.execute("SELECT id,data FROM diagnostics")}}


class InstanceLock:
    """OS releases the lock on process exit, including crashes. Status stays readable."""
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = open(directory / "instance.lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                self.file.write(b"0")
                self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Another connector is using this state directory") from None

    def close(self):
        self.file.close()


class MailboxBindingError(RuntimeError):
    pass
