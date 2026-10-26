from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import load
from .monitor import connect
from .service import dispatch_one, enqueue_test, run
from .push import Sender
from .state import InstanceLock, State, snapshot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only IMAP to encrypted UnifiedPush connector")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "check", "test", "revoke"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--config", default=os.environ.get("MAILPUSH_CONFIG", "config.toml"))
        if name in ("test", "revoke"):
            cmd.add_argument("--device")
    pair = sub.add_parser("pair", help="Import an encrypted request exported by the Android app")
    pair.add_argument("--config", default=os.environ.get("MAILPUSH_CONFIG", "config.toml"))
    pair.add_argument("--request", required=True)
    pair.add_argument("--device", required=True)
    pair.add_argument("--replace", action="store_true")
    pair.add_argument("--receipt", help="Encrypted receipt to import back into the phone")
    cert = sub.add_parser("certificate", help="Inspect an IMAP certificate without logging in")
    cert.add_argument("--host", default="127.0.0.1")
    cert.add_argument("--port", type=int, default=1143)
    cert.add_argument("--tls", choices=["tls", "starttls"], default="starttls")
    cert.add_argument("--output", help="New public PEM certificate file")
    vapid = sub.add_parser("vapid-keygen", help="Generate an optional sender identity for providers requiring VAPID")
    vapid.add_argument("--private", required=True)
    for name in ("status", "healthcheck"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--state-dir", default=os.environ.get("MAILPUSH_STATE_DIR", "state"))
    args = parser.parse_args(argv)
    if os.name != "nt":
        os.umask(0o077)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("mailpush").setLevel(logging.INFO)
    try:
        if args.command == "status":
            print(json.dumps(snapshot(Path(args.state_dir)), indent=2))
            return 0
        if args.command == "healthcheck":
            try:
                data = json.loads((Path(args.state_dir) / "heartbeat.json").read_text())
                healthy = 0 <= time.time() - data["at"] <= 30
            except (OSError, ValueError, KeyError, TypeError):
                healthy = False
            return 0 if healthy else 1
        if args.command == "certificate":
            from .certificates import inspect_certificate
            fingerprint = inspect_certificate(args.host, args.port, args.tls, args.output)
            print("Observed certificate SHA-256 (not yet trusted): " + fingerprint)
            print("Verify this against the Bridge owner's certificate before configuring tls_pin_sha256.")
            return 0
        if args.command == "vapid-keygen":
            from py_vapid import Vapid
            from cryptography.hazmat.primitives import serialization
            import base64
            path = Path(args.private)
            key = Vapid(); key.generate_keys()
            with open(path, "xb") as output:
                output.write(key.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            public = key.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            print("VAPID public key: " + base64.urlsafe_b64encode(public).rstrip(b"=").decode())
            return 0
        if args.command == "pair":
            from .pairing import import_request
            fingerprint = import_request(args.config, args.request, args.device, args.replace, receipt_path=args.receipt)
            print(f"Pairing imported. Compare fingerprint with phone: {fingerprint}")
            print("Import the encrypted .receipt file into the phone, then restart the connector. Keep the generated receiver file private.")
            return 0
        config = load(args.config)
        if args.command == "revoke":
            devices = [d for d in config.devices if d.id == args.device]
            if not devices:
                raise ValueError("Specify an existing device with --device")
            state = State(config.state_dir, config.max_queue)
            try:
                state.revoke(devices[0])
            finally:
                state.close()
            print("Device revoked for this receiver key. A fresh phone registration is required to pair again.")
            return 0
        if args.command == "check":
            # Read-only, bounded connection check. Does not initialize checkpoints or send pushes.
            for box in config.mailboxes:
                client = connect(box)
                try:
                    client.select_folder(box.folder, readonly=True)
                    print(f"mailbox={box.id} code=imap_ok idle={client.has_capability('IDLE')}")
                finally:
                    client.shutdown()
            print("Configuration and receiver keys valid. No notification was sent.")
            return 0
        if args.command == "test":
            lock = InstanceLock(config.state_dir)
            state = State(config.state_dir, config.max_queue)
            sender = Sender(config.request_timeout)
            try:
                enqueue_test(config, state, args.device)
                # A single pass; transient failures remain queued for the service to retry.
                while dispatch_one(config, state, sender):
                    pass
                print("Encrypted test queued. Inspect status for push-server acceptance; receipt requires the Android receiver.")
                return 0
            finally:
                sender.close()
                state.close()
                lock.close()
        stop = threading.Event()
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        run(config, stop)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Exception bodies from libraries or remote services may include private information.
        from .config import ConfigError
        message = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
        print(f"mailpush: operation failed: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
