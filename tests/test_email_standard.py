import pytest

from dublin_house.report_validation import validate_direct_url, validate_report_html


CANONICAL_SALES_HTML = """
<p>更新日期：2026-07-26 · 信息核验：2026-07-26 上午</p>
<p>本期重点：两个项目即将开放。</p>
<div>本期条目 12 独立地图位置 12 当前重点 10</div>
<div>地图颜色汇总（各颜色数量之和＝12 个地图点位）</div>
<div>市场资讯卡不计入地图</div>
<h2>所有房源位置总览</h2>
<a href="https://www.google.com/maps/search/?api=1&amp;query=South+Dublin+housing">
  <img src="https://maps.googleapis.com/maps/api/staticmap?size=640x480&amp;key=test"
       alt="南都柏林住房销售 Google Maps 总览">
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


def test_report_rejects_old_cid_map_format():
    html = CANONICAL_SALES_HTML + '<img alt="map" src="cid:sales-map">'
    with pytest.raises(ValueError, match="obsolete format"):
        validate_report_html(
            html,
            overview_title="所有房源位置总览",
            require_static_map=True,
        )


def test_report_rejects_missing_static_map():
    html = CANONICAL_SALES_HTML.replace(
        '<img src="https://maps.googleapis.com/maps/api/staticmap?size=640x480&amp;key=test"\n       alt="南都柏林住房销售 Google Maps 总览">',
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
    with pytest.raises(ValueError, match="obsolete format"):
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
