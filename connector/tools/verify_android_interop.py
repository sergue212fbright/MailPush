#!/usr/bin/env python3
"""Verify a synthetic JVM-generated pairing request with the real Python importer."""
import json
import sys
from pathlib import Path
from mailpush.pairing import decrypt_request

android = Path(sys.argv[1] if len(sys.argv) > 1 else "../modules/mailpush")
module = android / "app" if (android / "app/src").exists() else android
fixture = json.loads((module / "src/test/resources/interop.json").read_text())
request = (module / "build/interop/java-request.mailpush").read_bytes()
actual = decrypt_request(request, fixture["profile"]["pending_key"], now=fixture["now"])
if actual != fixture["bundle"]:
    raise SystemExit("Cross-language pairing verification failed")
print("Java AES-GCM pairing request verified by Python; binding and mailbox scope match.")
