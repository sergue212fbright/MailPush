#!/usr/bin/env python3
"""Send a minimal owner-configured failure email through verified TLS SMTP.

Only this trusted notification job receives SMTP credentials. The compiler and
pull-request jobs receive none. A notification failure is itself an error; it is
never silently reported as successful. No mail content or build logs are sent.
"""

from __future__ import annotations
import os, re, smtplib, ssl
from email.headerregistry import Address
from email.message import EmailMessage


def address(value: str) -> str:
    if not value or len(value) > 320 or "\r" in value or "\n" in value:
        raise ValueError("Invalid notification address")
    parsed = Address(addr_spec=value)
    if not parsed.domain or not parsed.username:
        raise ValueError("Invalid notification address")
    return parsed.addr_spec


def build_message(env: dict) -> EmailMessage:
    message = EmailMessage()
    message["From"] = address(env["MAIL_FROM"])
    message["To"] = address(env["MAIL_TO"])
    message["Subject"] = "MailPush automatic update needs attention"
    repo = env.get("GITHUB_REPOSITORY", "")
    run = env.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not run.isdigit():
        raise ValueError("Invalid workflow link")
    message.set_content(
        "A MailPush update check, build, test, signing or publication step failed. Review the run before installing its artifacts.\n\n"
        + "Review: https://github.com/"
        + repo
        + "/actions/runs/"
        + run
        + "\n\n"
        + "This email intentionally contains no mail contents, credentials, endpoint URLs or build logs.\n"
    )
    return message


def send(env: dict) -> None:
    message = build_message(env)
    host = env["MAIL_HOST"]
    mode = env.get("MAIL_MODE", "ssl")
    port = int(env.get("MAIL_PORT", "465" if mode == "ssl" else "587"))
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or not 1 <= port <= 65535:
        raise ValueError("Invalid SMTP server")
    if mode not in {"ssl", "starttls"}:
        raise ValueError("Only verified TLS SMTP is supported")
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    client = (
        smtplib.SMTP_SSL(host, port, timeout=20, context=context)
        if mode == "ssl"
        else smtplib.SMTP(host, port, timeout=20)
    )
    with client:
        if mode == "starttls":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(env["MAIL_USER"], env["MAIL_PASSWORD"])
        client.send_message(message)


if __name__ == "__main__":
    try:
        send(dict(os.environ))
        print("Failure email submitted to the configured SMTP server.")
    except Exception as e:
        raise SystemExit(
            "Failure email was not sent ("
            + type(e).__name__
            + "). Check notification configuration."
        )
