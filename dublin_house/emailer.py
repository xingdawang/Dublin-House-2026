from __future__ import annotations

import os
import re
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .common import ROOT


CID_PATTERN = re.compile(r"cid:([^\"'\s>]+)", re.IGNORECASE)


def render(template_name: str, **context) -> str:
    env = Environment(
        loader=FileSystemLoader(ROOT / "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template(template_name).render(**context)


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
    validated_images = validate_inline_images(html, inline_images)

    message = MIMEMultipart("related")
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_USER"]
    message["To"] = os.getenv("EMAIL_TO", "wxd598113636@gmail.com")

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText("Please view this email in an HTML-capable client.", "plain", "utf-8"))
    alternative.attach(MIMEText(html, "html", "utf-8"))
    message.attach(alternative)

    for cid, (path, payload) in validated_images.items():
        image = MIMEImage(payload)
        image.add_header("Content-ID", f"<{cid}>")
        image.add_header("Content-Disposition", "inline", filename=path.name)
        message.attach(image)

    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_APP_PASSWORD"])
        smtp.send_message(message)
