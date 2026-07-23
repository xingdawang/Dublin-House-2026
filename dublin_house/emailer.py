from __future__ import annotations

import os
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import ROOT


def render(template_name: str, **context) -> str:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template(template_name).render(**context)


def send_html(subject: str, html: str, *, inline_images: dict[str, Path] | None = None) -> None:
    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_USER"]
    message["To"] = os.getenv("EMAIL_TO", "wxd598113636@gmail.com")

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText("Please view this email in an HTML-capable client.", "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    message.attach(alternative)

    for cid, path in (inline_images or {}).items():
        if not path.exists():
            continue
        image = MIMEImage(path.read_bytes())
        image.add_header("Content-ID", f"<{cid}>")
        image.add_header("Content-Disposition", "inline", filename=path.name)
        message.attach(image)

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"])
        smtp.send_message(message)
