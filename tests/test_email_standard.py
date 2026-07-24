import pytest

from dublin_house.report_validation import validate_direct_url, validate_report_html


CANONICAL_SALES_HTML = """
<p>更新日期：2026-07-24 · 信息核验：2026-07-24 上午</p>
<p>本期重点：两个项目即将开放。</p>
<div>本期条目 12 独立地图位置 12 当前重点 10</div>
<h2>所有房源位置总览</h2>
<a href="https://www.google.com/maps/search/?api=1&amp;query=South+Dublin+housing">
南都柏林住房销售位置总览
</a>
<p>1 Foothills 2 St Laurence Park</p>
<a href="https://www.google.com/maps/search/?api=1&amp;query=Killinarden+Dublin+24">Google Maps</a>
"""


def test_report_accepts_jul_24_0913_reference_format():
    validate_report_html(CANONICAL_SALES_HTML, overview_title="所有房源位置总览")


def test_report_rejects_missing_focus_summary():
    html = CANONICAL_SALES_HTML.replace("本期重点：两个项目即将开放。", "")
    with pytest.raises(ValueError):
        validate_report_html(html, overview_title="所有房源位置总览")


def test_report_rejects_missing_map_overview_link():
    html = CANONICAL_SALES_HTML.replace(
        "https://www.google.com/maps/search/?api=1&amp;query=South+Dublin+housing",
        "https://example.com/overview",
    )
    with pytest.raises(ValueError):
        validate_report_html(html, overview_title="所有房源位置总览")


def test_report_rejects_old_cid_map_format():
    html = CANONICAL_SALES_HTML + '<img alt="map" src="cid:sales-map">'
    with pytest.raises(ValueError, match="obsolete format"):
        validate_report_html(html, overview_title="所有房源位置总览")


def test_report_rejects_old_static_map_format():
    html = CANONICAL_SALES_HTML + (
        '<img src="https://maps.googleapis.com/maps/api/staticmap?size=640x480&amp;key=test">'
    )
    with pytest.raises(ValueError, match="obsolete format"):
        validate_report_html(html, overview_title="所有房源位置总览")


def test_direct_url_rejects_home_page():
    with pytest.raises(ValueError):
        validate_direct_url("https://affordablehomes.ie/", title="Foothills")


def test_direct_url_accepts_concrete_project_page():
    validate_direct_url(
        "https://affordablehomes.ie/buy/foothills/",
        title="Foothills",
    )
