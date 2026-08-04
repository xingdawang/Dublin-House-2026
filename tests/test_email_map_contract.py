from __future__ import annotations

import base64

import pytest

from dublin_house import emailer
from dublin_house.emailer import resolve_inline_images, send_html, validate_inline_images
from dublin_house.report_validation import validate_report_html


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlWQAAAAASUVORK5CYII="
)


def _report_html(*, cid: str, overview_title: str) -> str:
    return f"""
    <!doctype html><html><body>
      <div>更新日期：2026-08-04 · 信息核验：来源核验截至 2026-08-04</div>
      <div>本期重点：测试</div>
      <div>本期条目</div><div>独立地图位置</div><div>当前重点</div>
      <div>地图颜色汇总（各颜色数量之和）
        <span style="border-radius:50%"></span>
      </div>
      <h2>{overview_title}</h2>
      <a href="https://www.google.com/maps/search/?api=1&query=South+Dublin">
        <img src="cid:{cid}" alt="Google Maps" width="640"
             style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:10px">
      </a>
      <a href="https://www.google.com/maps/search/?api=1&query=South+Dublin">
        在 Google Maps 中打开总览
      </a>
    </body></html>
    """


@pytest.mark.parametrize(
    ("cid", "overview_title"),
    [
        ("sales-map", "所有房源位置总览"),
        ("rental-map", "所有出租位置总览"),
    ],
)
def test_canonical_map_contract_accepts_valid_inline_png(tmp_path, cid: str, overview_title: str):
    image_path = tmp_path / f"{cid}.png"
    image_path.write_bytes(PNG_1X1)
    html = _report_html(cid=cid, overview_title=overview_title)

    validate_report_html(
        html,
        overview_title=overview_title,
        require_static_map=True,
        map_cid=cid,
    )
    validated = validate_inline_images(html, {cid: image_path})

    assert validated[cid][0] == image_path
    assert validated[cid][1] == PNG_1X1


@pytest.mark.parametrize(
    ("cid", "expected_name"),
    [("sales-map", "sales_map.png"), ("rental-map", "rental_map.png")],
)
def test_canonical_map_attachment_is_resolved_from_cid(cid: str, expected_name: str):
    html = f'<img src="cid:{cid}">'

    images = resolve_inline_images(html)

    assert images[cid].name == expected_name
    assert images[cid].parent.name == "output"


def test_remote_google_static_map_url_is_rejected():
    html = _report_html(cid="sales-map", overview_title="所有房源位置总览").replace(
        "cid:sales-map",
        "https://maps.googleapis.com/maps/api/staticmap?size=640x480&key=secret",
    )

    with pytest.raises(ValueError, match="missing|unsafe"):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
            map_cid="sales-map",
        )


def test_missing_cid_attachment_fails_closed():
    html = _report_html(cid="sales-map", overview_title="所有房源位置总览")

    with pytest.raises(ValueError, match="Missing inline image attachments"):
        validate_inline_images(html, {})


def test_send_html_builds_related_message_with_content_id(monkeypatch, tmp_path):
    image_path = tmp_path / "sales_map.png"
    image_path.write_bytes(PNG_1X1)
    sent_messages = []

    class FakeSMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def ehlo(self):
            return None

        def starttls(self):
            return None

        def login(self, *_args):
            return None

        def send_message(self, message):
            sent_messages.append(message)

    monkeypatch.setattr(
        emailer,
        "_email_settings",
        lambda: ("sender@example.com", "password", "to@example.com", "smtp.example.com", 587),
    )
    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)

    send_html(
        "Canonical map",
        '<html><body><img src="cid:sales-map"></body></html>',
        inline_images={"sales-map": image_path},
    )

    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message.get_content_type() == "multipart/related"
    assert [part["Content-ID"] for part in message.walk() if part["Content-ID"]] == ["<sales-map>"]
