#!/usr/bin/env python3
"""Local development receiver. Contains private test keys; never expose publicly."""

import argparse
import base64
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import http_ece
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="demo-secrets")
    parser.add_argument("--port", default=8769, type=int)
    args = parser.parse_args()
    if os.name != "nt":
        os.umask(0o077)
    directory = Path(args.output)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = ec.generate_private_key(ec.SECP256R1())
    auth = os.urandom(16)

    def b64(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length > 4096:
                self.send_error(413)
                return
            try:
                data = http_ece.decrypt(self.rfile.read(length), private_key=private, auth_secret=auth, version="aes128gcm")
                print(json.dumps(json.loads(data), indent=2), flush=True)
                self.send_response(201)
                self.end_headers()
            except Exception:
                self.send_error(400, "Invalid encrypted alert")

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", args.port), Receiver)
    sub = {"endpoint": f"http://127.0.0.1:{server.server_port}/push",
           "keys": {"p256dh": b64(private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)), "auth": b64(auth)}}
    (directory / "subscription.json").write_text(json.dumps(sub, indent=2))
    print(f"Development subscription written to {directory / 'subscription.json'}. Private key remains in this process; restarting creates a new subscription.", flush=True)
    print("Set allow_http_loopback=true for this local test only. This is not an Android receiver.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
