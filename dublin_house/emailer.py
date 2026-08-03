from __future__ import annotations

import os
import re
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import ROOT


CID_PATTERN = re.compile(r"cid:([^\"'\s>]+)", re.IGNORECASE)
REQUIRED_EMAIL_ENV = ("SMTP_USER", "SMTP_APP_PASSWORD", "EMAIL_TO")


def render(template_name: str, **context) -> str:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template(template_name).render(**context)


def _email_settings() -> tuple[str, str, str, str, int]:
    missing = [name for name in REQUIRED_EMAIL_ENV if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing required email setting(s): " + ", ".join(missing))

    smtp_user = os.environ["SMTP_USER"].strip()
    smtp_password = os.environ["SMTP_APP_PASSWORD"]
    recipients = os.environ["EMAIL_TO"].strip()
    invalid = [value for value in recipients.split(",") if "@" not in parseaddr(value.strip())[1]]
    if invalid:
        raise RuntimeError("Invalid EMAIL_TO recipient(s): " + ", ".join(invalid))

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    return smtp_user, smtp_password, recipients, smtp_host, smtp_port


def validate_smtp_connection() -> None:
    """Verify required settings and authenticate to SMTP without sending an email."""
    smtp_user, smtp_password, _recipients, smtp_host, smtp_port = _email_settings()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(smtp_user, smtp_password)
        code, _ = smtp.noop()
        if code != 250:
            raise RuntimeError(f"SMTP preflight failed with response code {code}")


def validate_inline_images(html: str, inline_images: dict[str, Path] | None) -> dict[str, tuple[Path, bytes]]:
    """Fail closed when CID images referenced by the email are not attachable."""
    images = inline_images or {}
    referenced_cids = set(CID_PATTERN.findall(html))
    provided_cids = set(images)

    missing_cids = referenced_cids - provided_cids
    if missing_cids:
        raise ValueError(f"Missing inline image attachments for CID(s): {', '.join(sorted(missing_cids))}")

    unreferenced_cids = provided_cids - referenced_cids
    if unreferenced_cids:
        raise ValueError(f"Inline image CID(s) are not referenced by the HTML: {', '.join(sorted(unreferenced_cids))}")

    validated: dict[str, tuple[Path, bytes]] = {}
    for cid, path in images.items():
        if not path.is_file():
            raise FileNotFoundError(f"Inline image for CID '{cid}' does not exist: {path}")

        payload = path.read_bytes()
        if not payload:
            raise ValueError(f"Inline image for CID '{cid}' is empty: {path}")

        try:
            MIMEImage(payload)
        except TypeError as exc:
            raise ValueError(f"Inline image for CID '{cid}' is not a recognized image: {path}") from exc

        validated[cid] = (path, payload)

    return validated


def send_html(subject: str, html: str, *, inline_images: dict[str, Path] | None = None) -> None:
    smtp_user, smtp_password, recipients, smtp_host, smtp_port = _email_settings()
    validated_images = validate_inline_images(html, inline_images)

    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = recipients

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText("Please view this email in an HTML-capable client.", "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    message.attach(alternative)

    for cid, (path, payload) in validated_images.items():
        image = MIMEImage(payload)
        image.add_header("Content-ID", f"<{cid}>")
        image.add_header("Content-Disposition", "inline", filename=path.name)
        message.attach(image)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)
