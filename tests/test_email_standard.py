import httpx
import pytest

from dublin_house.report_validation import (
    validate_direct_url,
    validate_live_rental_url,
    validate_report_html,
)


CANONICAL_SALES_HTML = """
<p>更新日期：2026-07-26 · 信息核验：2026-07-26 上午</p>
<p>本期重点：两个项目即将开放。</p>
<div>本期条目 12 独立地图位置 12 当前重点 10</div>
<div>地图颜色汇总（各颜色数量之和＝12 个地图点位）</div>
<div>市场资讯卡不计入地图</div>
<h2>所有房源位置总览</h2>
<a href="https://www.google.com/maps/search/?api=1&amp;query=South+Dublin+housing">
  <img src="cid:sales-map"
       alt="南都柏林住房销售 Google Maps 总览"
       width="640"
       style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:10px">
</a>
<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:#2563eb"></span>
<p>1 Foothills 2 St Laurence Park</p>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Killinarden+Dublin+24">Google Maps</a>
<a href="https://www.google.com/maps/search/?api=1&amp;query=South+Dublin+housing">在 Google Maps 中打开总览</a>
"""


def test_report_accepts_canonical_static_map_format():
    validate_report_html(
        CANONICAL_SALES_HTML,
        overview_title="所有房源位置总览",
        require_static_map=True,
    )


def test_report_accepts_delta_first_inventory_focus_label():
    html = CANONICAL_SALES_HTML.replace(
        "本期重点：两个项目即将开放。",
        "当前库存重点：两个项目持续跟踪。",
    )
    validate_report_html(
        html,
        overview_title="所有房源位置总览",
        require_static_map=True,
    )


def test_report_rejects_missing_focus_summary():
    html = CANONICAL_SALES_HTML.replace("本期重点：两个项目即将开放。", "")
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_report_rejects_missing_map_overview_link():
    html = CANONICAL_SALES_HTML.replace(
        "https://www.google.com/maps/search/?api=1&amp;query=South+Dublin+housing",
        "https://example.com/overview",
    ).replace(
        "https://www.google.com/maps/search/?api=1&amp;query=Killinarden+Dublin+24",
        "https://example.com/listing-map",
    )
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_report_rejects_remote_static_map_format():
    html = CANONICAL_SALES_HTML.replace(
        "cid:sales-map",
        "https://maps.googleapis.com/maps/api/staticmap?size=640x480&amp;key=test",
    )
    with pytest.raises(ValueError, match="missing|unsafe"):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_report_rejects_missing_static_map():
    html = CANONICAL_SALES_HTML.replace(
        '<img src="cid:sales-map"\n       alt="南都柏林住房销售 Google Maps 总览"\n       width="640"\n       style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:10px">',
        "",
    )
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_report_rejects_missing_marker_legend():
    html = CANONICAL_SALES_HTML.replace("border-radius:50%", "border-radius:0")
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_report_rejects_empty_sales_section_placeholder():
    html = CANONICAL_SALES_HTML + "<p>本期没有合适项目。</p>"
    with pytest.raises(ValueError, match="obsolete.*format"):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_direct_url_rejects_home_page():
    with pytest.raises(ValueError):
        validate_direct_url("https://affordablehomes.ie/", title="Foothills")


def test_direct_url_accepts_concrete_project_page():
    validate_direct_url(
        "https://affordablehomes.ie/buy/foothills/",
        title="Foothills",
    )


def test_live_rental_url_rejects_detail_page_that_says_property_is_unavailable(monkeypatch):
    url = "https://www.daft.ie/for-rent/example-home-dublin-8/123456"

    def fake_get(*_args, **_kwargs):
        return httpx.Response(
            200,
            text="<main><h1>Example Home</h1><p>This property is no longer available.</p></main>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("dublin_house.report_validation.httpx.get", fake_get)

    with pytest.raises(ValueError, match="no longer available"):
        validate_live_rental_url(url, title="Example Home")
