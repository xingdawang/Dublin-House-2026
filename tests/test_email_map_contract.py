from __future__ import annotations

import base64

import pytest

from dublin_house.emailer import validate_inline_images
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
