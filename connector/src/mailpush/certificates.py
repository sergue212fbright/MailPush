"""Read-only certificate inspection; deliberately sends no IMAP credentials."""
import hashlib
import imaplib
import ssl
from pathlib import Path


def inspect_certificate(host: str, port: int, mode: str, output: str | None = None) -> str:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    client = imaplib.IMAP4_SSL(host, port, ssl_context=context, timeout=20) if mode == "tls" else imaplib.IMAP4(host, port, timeout=20)
    try:
        if mode == "starttls":
            client.starttls(ssl_context=context)
        der = client.sock.getpeercert(binary_form=True)
        if output:
            with open(output, "x", encoding="ascii") as file:
                file.write(ssl.DER_cert_to_PEM_cert(der))
        return hashlib.sha256(der).hexdigest()
    finally:
        client.shutdown()
