from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr


def _parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _extract_email(value: str) -> str:
    _, addr = parseaddr(value)
    return addr.strip().lower()


def is_valid_email(value: str) -> bool:
    addr = _extract_email(value)
    if not addr or "@" not in addr:
        return False
    local, _, domain = addr.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if any(ch.isspace() for ch in addr):
        return False
    return True


def smtp_config_from_env() -> dict[str, object]:
    host = os.getenv("SMTP_HOST")
    port_raw = os.getenv("SMTP_PORT", "587")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM")
    use_tls = _parse_bool(os.getenv("SMTP_USE_TLS"), default=True)

    if not host:
        raise ValueError("SMTP_HOST is required.")
    try:
        port = int(port_raw.strip())
    except ValueError as exc:
        raise ValueError("SMTP_PORT must be an integer.") from exc
    if not smtp_from:
        raise ValueError("SMTP_FROM is required.")
    if not is_valid_email(smtp_from):
        raise ValueError("SMTP_FROM must contain a valid email address.")

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "smtp_from": smtp_from,
        "use_tls": use_tls
    }


def send_email_via_smtp(
    *,
    to: str,
    subject: str,
    body: str,
    reply_to: str | None = None
) -> str | None:
    config = smtp_config_from_env()
    message = EmailMessage()
    message_id = make_msgid()
    message["Message-ID"] = message_id
    message["From"] = str(config["smtp_from"])
    message["To"] = to
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    with smtplib.SMTP(
        host=str(config["host"]),
        port=int(config["port"]),
        timeout=10.0
    ) as server:
        server.ehlo()
        if bool(config["use_tls"]):
            server.starttls()
            server.ehlo()
        username = config.get("username")
        if username:
            server.login(str(username), str(config.get("password") or ""))
        failures = server.send_message(message)
        if failures:
            raise smtplib.SMTPException("SMTP rejected one or more recipients.")
    return message_id
