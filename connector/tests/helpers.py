import base64
import json
import os
import select
import socketserver
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import http_ece
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from mailpush.config import Device


def recipient(identifier="phone", endpoint="https://example.invalid/push"):
    import hashlib
    private = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)
    enc = lambda data: base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    sub = {"endpoint": endpoint, "keys": {"p256dh": enc(private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)), "auth": enc(auth)}}
    fingerprint = hashlib.sha256(json.dumps(sub, sort_keys=True).encode()).hexdigest()
    return Device(identifier, sub, fingerprint), private, auth


class PushServer:
    def __init__(self):
        self.requests = []
        self.responses = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                outer.requests.append((self.path, dict(self.headers), body))
                status, headers = outer.responses.pop(0) if outer.responses else (201, {})
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.server.server_port}/push?up=1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class IMAPServer:
    """Small wire-protocol test double, parsed by the real IMAPClient library."""
    def __init__(self, idle=True, tls_context=None):
        self.messages = {}
        self.next_uid = 1
        self.validity = 12345
        self.commands = []
        self.idle_enabled = idle
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def write(self, line):
                self.wfile.write(line.encode() if isinstance(line, str) else line)
                self.wfile.flush()

            def handle(self):
                selected_count = 0
                self.write("* OK Local test IMAP\r\n")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    text = line.decode().strip()
                    outer.commands.append(text)
                    tag, command, *rest = text.split(" ", 2)
                    command = command.upper()
                    args = rest[0] if rest else ""
                    if command == "CAPABILITY":
                        self.write("* CAPABILITY IMAP4rev1" + (" IDLE" if outer.idle_enabled else "") + "\r\n")
                    elif command == "LOGIN":
                        pass
                    elif command in {"EXAMINE", "SELECT"}:
                        selected_count = len(outer.messages)
                        self.write(f"* {len(outer.messages)} EXISTS\r\n* OK [UIDVALIDITY {outer.validity}] valid\r\n* OK [UIDNEXT {outer.next_uid}] next\r\n")
                    elif command == "UID" and args.startswith("SEARCH"):
                        start = int(args.split()[-1].split(":")[0])
                        largest = max(outer.messages, default=0)
                        # Emulate the reversed n:* range required by the IMAP specification.
                        lower, upper = min(start, largest), max(start, largest)
                        found = [uid for uid in sorted(outer.messages) if lower <= uid <= upper]
                        self.write("* SEARCH" + "".join(f" {uid}" for uid in found) + "\r\n")
                    elif command == "UID" and args.startswith("FETCH"):
                        wanted = args.split()[1]
                        uids = [int(uid) for uid in wanted.split(",")]
                        for uid in uids:
                            if uid not in outer.messages:
                                continue
                            message = outer.messages[uid]
                            flags = "\\Seen" if message["seen"] else ""
                            date = message["date"].strftime("%d-%b-%Y %H:%M:%S %z")
                            prefix = f'* {uid} FETCH (UID {uid} FLAGS ({flags}) INTERNALDATE "{date}"'
                            if "BODY.PEEK" in args:
                                raw = message["headers"]
                                self.write(prefix + f" BODY[HEADER.FIELDS (FROM SUBJECT)] {{{len(raw)}}}\r\n")
                                self.write(raw)
                                self.write(")\r\n")
                            else:
                                self.write(prefix + ")\r\n")
                    elif command == "IDLE":
                        self.write("+ idling\r\n")
                        count = selected_count
                        while True:
                            if select.select([self.connection], [], [], 0.05)[0]:
                                if self.rfile.readline().strip() != b"DONE":
                                    return
                                break
                            current = len(outer.messages)
                            if current != count:
                                self.write(f"* {current} EXISTS\r\n")
                                count = current
                        selected_count = count
                    elif command == "LOGOUT":
                        self.write("* BYE\r\n" + tag + " OK logout\r\n")
                        return
                    else:
                        self.write(tag + " BAD unsupported\r\n")
                        continue
                    self.write(tag + " OK complete\r\n")

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

            def get_request(self):
                client, address = super().get_request()
                if tls_context:
                    client = tls_context.wrap_socket(client, server_side=True)
                return client, address

        self.server = Server(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_address[1]

    def add(self, seen=False, date=None):
        uid = self.next_uid
        self.next_uid += 1
        self.messages[uid] = {"seen": seen, "date": date or datetime.now(timezone.utc),
                              "headers": b"From: Alice <alice@example.com>\r\nSubject: private-test-subject\r\n\r\n"}
        return uid

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
