import pytest

from dublin_house.emailer import validate_inline_images
from dublin_house.report_validation import validate_direct_url, validate_report_html


def test_report_requires_cid_map_and_summary_cards():
    html = """
    <div>本期条目 独立地图位置 当前重点</div>
    <img alt="南都柏林住房销售位置总览" src="cid:sales-map">
    """
    validate_report_html(
        html,
        expected_map_alt="南都柏林住房销售位置总览",
        expected_map_cid="sales-map",
    )


def test_report_rejects_link_only_map():
    html = "本期条目 独立地图位置 当前重点 <a href='https://maps.google.com'>地图</a>"
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            expected_map_alt="南都柏林住房销售位置总览",
            expected_map_cid="sales-map",
        )


def test_report_rejects_remote_static_map():
    html = """
    本期条目 独立地图位置 当前重点
    <img alt="南都柏林住房销售位置总览"
         src="https://maps.googleapis.com/maps/api/staticmap?size=640x480&key=test">
    """
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            expected_map_alt="南都柏林住房销售位置总览",
            expected_map_cid="sales-map",
        )


def test_report_rejects_map_error_fallback():
    html = """
    本期条目 独立地图位置 当前重点 地图暂不可用
    <img alt="南都柏林住房租赁位置总览" src="cid:rental-map">
    """
    with pytest.raises(ValueError):
        validate_report_html(
            html,
            expected_map_alt="南都柏林住房租赁位置总览",
            expected_map_cid="rental-map",
        )


def test_sender_rejects_missing_cid_attachment():
    html = '<img alt="南都柏林住房销售位置总览" src="cid:sales-map">'
    with pytest.raises(ValueError, match="Missing inline image attachments"):
        validate_inline_images(html, {})


def test_sender_rejects_missing_inline_image_file(tmp_path):
    html = '<img alt="南都柏林住房销售位置总览" src="cid:sales-map">'
    with pytest.raises(FileNotFoundError, match="sales-map"):
        validate_inline_images(html, {"sales-map": tmp_path / "missing.png"})


def test_direct_url_rejects_home_page():
    with pytest.raises(ValueError):
        validate_direct_url("https://affordablehomes.ie/", title="Foothills")


def test_direct_url_accepts_concrete_project_page():
    validate_direct_url(
        "https://affordablehomes.ie/buy/foothills/",
        title="Foothills",
    )
